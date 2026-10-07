# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""Transport faults as a publisher interceptor: TransportFaults(message, forward) -> UStatus.

    faults = TransportFaults(seed=7)
    SignalPublisher(transport.send_sync, topic, ttl_ms=2000, interceptors=[faults])
    faults.add("delay", {"ms": 1500}, duration_s=10)       # steer it at runtime, e.g. from an HTTP handler

Fault types (applied per message, in this order when several are active):
    drop        lose the message with params.probability (default 1.0, drawn from the seeded RNG)
    reorder     hold one message and send it after the next one (pairs swap places)
    duplicate   send params.copies extra copies (default 1)
    delay       send params.ms later, from a timer thread (a delay beyond the TTL arrives expired)

A message that is dropped, held or delayed still returns OK to the publisher: the sender cannot tell.
A held message with nobody behind it stays held until the next message or until `reorder` is cleared.
"""
import itertools
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.ustatus_pb2 import UStatus

TRANSPORT_FAULTS = ("drop", "reorder", "duplicate", "delay")


class FaultError(ValueError):
    """Invalid fault request (bad type or parameter)."""


@dataclass
class TransportFault:
    id: int
    type: str
    params: dict
    started_at: float
    duration_s: Optional[float] = None

    def as_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "params": self.params, "duration_s": self.duration_s}


def _number(params: dict, key: str, default=None, minimum: float = 0.0, maximum: Optional[float] = None) -> float:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FaultError(f"params.{key} must be a number")
    if value < minimum or (maximum is not None and value > maximum):
        raise FaultError(f"params.{key} must be between {minimum} and {maximum if maximum is not None else 'infinity'}")
    return float(value)


def _schedule(delay_s: float, fn: Callable[[], None]) -> None:
    timer = threading.Timer(delay_s, fn)
    timer.daemon = True
    timer.start()


class TransportFaults:
    def __init__(self, seed: int = 0, clock: Callable[[], float] = time.monotonic,
                 schedule: Callable[[float, Callable[[], None]], None] = _schedule):
        self._clock = clock
        self._schedule = schedule
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._faults: Dict[int, TransportFault] = {}
        self._rng = random.Random(seed)
        self._held: Optional[UMessage] = None  # waiting for the next message
        self.counts = {"seen": 0, "dropped": 0, "reordered": 0, "duplicated": 0, "delayed": 0}

    # --- control ---------------------------------------------------------------------------------------------
    def add(self, type_: str, params: Optional[dict] = None, duration_s=None) -> TransportFault:
        if type_ not in TRANSPORT_FAULTS:
            raise FaultError(f"unknown fault type {type_!r}, use one of {', '.join(TRANSPORT_FAULTS)}")
        if params is not None and not isinstance(params, dict):
            raise FaultError("params must be an object")
        params = dict(params or {})
        if type_ == "drop":
            params["probability"] = _number(params, "probability", 1.0, 0.0, 1.0)
        elif type_ == "duplicate":
            params["copies"] = int(_number(params, "copies", 1, 1.0, 10.0))
        elif type_ == "delay":
            params["ms"] = _number(params, "ms")
        if duration_s is not None:
            if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)) or duration_s <= 0:
                raise FaultError("duration_s must be a positive number")
            duration_s = float(duration_s)
        with self._lock:
            fault = TransportFault(next(self._ids), type_, params, self._clock(), duration_s)
            self._faults[fault.id] = fault
            return fault

    def remove(self, fault_id: int) -> Optional[TransportFault]:
        with self._lock:
            return self._faults.pop(fault_id, None)

    def clear(self) -> List[TransportFault]:
        with self._lock:
            removed, self._faults = list(self._faults.values()), {}
            return removed

    def active(self) -> List[TransportFault]:
        with self._lock:
            return list(self._faults.values())

    def expire(self) -> List[TransportFault]:
        """Drop faults whose duration has passed and return them (the caller logs fault_cleared)."""
        now = self._clock()
        with self._lock:
            gone = [f for f in self._faults.values() if f.duration_s is not None and now - f.started_at >= f.duration_s]
            for f in gone:
                del self._faults[f.id]
            return gone

    def reset(self, seed: int) -> None:
        """New run: no faults, fresh RNG, zeroed counters."""
        with self._lock:
            self._faults, self._held = {}, None
            self._rng = random.Random(seed)
            self.counts = dict.fromkeys(self.counts, 0)

    # --- interceptor -------------------------------------------------------------------------------------------
    def __call__(self, message: UMessage, forward: Callable[[UMessage], UStatus]) -> UStatus:
        self.expire()
        with self._lock:
            out = self._plan(message)
        return self._emit(out, forward)

    def _plan(self, message: UMessage) -> List[tuple]:
        """What to send now, as (message, delay_s). Called with the lock held; sends nothing itself."""
        out: List[tuple] = []
        kinds = {f.type: f for f in self._faults.values()}
        self.counts["seen"] += 1
        if self._held is not None and "reorder" not in kinds:   # reorder was cleared: release what it was holding
            out.append((self._held, 0.0))
            self._held = None
        if "drop" in kinds and self._rng.random() < kinds["drop"].params["probability"]:
            self.counts["dropped"] += 1
            return out
        msgs = [message]
        if "reorder" in kinds:
            if self._held is None:
                self._held = message
                self.counts["reordered"] += 1
                return out
            msgs, self._held = [message, self._held], None
        if "duplicate" in kinds:
            extra = kinds["duplicate"].params["copies"]
            msgs = [m for m in msgs for _ in range(1 + extra)]
            self.counts["duplicated"] += extra
        delay_s = kinds["delay"].params["ms"] / 1000 if "delay" in kinds else 0.0
        if delay_s:
            self.counts["delayed"] += len(msgs)
        out.extend((m, delay_s) for m in msgs)
        return out

    def _emit(self, out: List[tuple], forward: Callable[[UMessage], UStatus]) -> UStatus:
        status = UStatus(code=UCode.OK)
        for message, delay_s in out:
            if delay_s > 0:
                self._schedule(delay_s, lambda m=message: forward(m))
            else:
                status = forward(message)
        return status
