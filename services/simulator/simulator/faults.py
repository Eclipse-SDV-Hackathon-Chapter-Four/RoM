# Made with Claude (Claude Code, Anthropic)
"""Fault engine of the simulator: signal faults change what a cell reports, source faults change whether the
source reports at all. Pure logic, no I/O; the clock is injected so tests do not sleep.

Signal faults (per cell, cells = [] means all cells):
    stuck           hold the value (the one at injection time, or params.value)
    spike           add params.delta for params.samples samples (default 1)
    drift           add params.rate_c_per_s * seconds since injection
    out_of_range    report params.value (default 200 °C), outside the guardian's plausible range
Source faults:
    dropout             the listed cells are not written (all cells if none are listed); the wave keeps running
    replay_interruption the whole source goes silent; the wave is paused and resumes where it stopped

Any fault may carry duration_s (> 0): it clears itself after that many seconds.
"""
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

N_CELLS = 4
SIGNAL_FAULTS = ("stuck", "spike", "drift", "out_of_range")
SOURCE_FAULTS = ("dropout", "replay_interruption")
FAULT_TYPES = SIGNAL_FAULTS + SOURCE_FAULTS
DEFAULT_OUT_OF_RANGE_C = 200.0


class FaultError(ValueError):
    """Invalid fault request (bad type, cell or parameter)."""


@dataclass
class Fault:
    id: int
    type: str
    cells: List[int]
    params: dict
    started_at: float
    duration_s: Optional[float] = None
    _held: Dict[int, float] = field(default_factory=dict, repr=False)   # stuck: value per cell
    _samples_left: Dict[int, int] = field(default_factory=dict, repr=False)  # spike: remaining samples per cell

    def as_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "cells": self.cells, "params": self.params,
                "duration_s": self.duration_s}


def _number(params: dict, key: str, default: Optional[float] = None) -> float:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FaultError(f"params.{key} must be a number")
    return float(value)


def _validate(type_: str, cells, params, duration_s):
    if type_ not in FAULT_TYPES:
        raise FaultError(f"unknown fault type {type_!r}, use one of {', '.join(FAULT_TYPES)}")
    if not isinstance(params, dict):
        raise FaultError("params must be an object")
    cells = [] if cells is None else cells
    if not isinstance(cells, list) or not all(isinstance(c, int) and not isinstance(c, bool) for c in cells):
        raise FaultError("cells must be a list of cell numbers")
    if any(not 1 <= c <= N_CELLS for c in cells):
        raise FaultError(f"cells must be between 1 and {N_CELLS}")
    if type_ == "replay_interruption" and cells:
        raise FaultError("replay_interruption stops the whole source, it takes no cells")
    params = dict(params)
    if type_ == "spike":
        params["delta"] = _number(params, "delta")
        params["samples"] = int(_number(params, "samples", 1))
        if params["samples"] < 1:
            raise FaultError("params.samples must be at least 1")
    elif type_ == "drift":
        params["rate_c_per_s"] = _number(params, "rate_c_per_s")
    elif type_ == "out_of_range":
        params["value"] = _number(params, "value", DEFAULT_OUT_OF_RANGE_C)
    elif type_ == "stuck" and "value" in params:
        params["value"] = _number(params, "value")
    if duration_s is not None:
        if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)) or duration_s <= 0:
            raise FaultError("duration_s must be a positive number")
        duration_s = float(duration_s)
    return sorted(set(cells)), params, duration_s


class FaultState:
    """Active faults; shared between the simulator loop and the HTTP thread."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._faults: Dict[int, Fault] = {}

    def add(self, type_: str, cells=None, params: Optional[dict] = None, duration_s=None) -> Fault:
        cells, params, duration_s = _validate(type_, cells, params or {}, duration_s)
        with self._lock:
            fault = Fault(next(self._ids), type_, cells, params, self._clock(), duration_s)
            self._faults[fault.id] = fault
            return fault

    def remove(self, fault_id: int) -> Optional[Fault]:
        with self._lock:
            return self._faults.pop(fault_id, None)

    def clear(self) -> List[Fault]:
        with self._lock:
            removed, self._faults = list(self._faults.values()), {}
            return removed

    def active(self) -> List[Fault]:
        with self._lock:
            return list(self._faults.values())

    def expire(self) -> List[Fault]:
        """Drop faults whose duration has passed and return them (the caller logs fault_cleared)."""
        now = self._clock()
        with self._lock:
            gone = [f for f in self._faults.values() if f.duration_s is not None and now - f.started_at >= f.duration_s]
            for f in gone:
                del self._faults[f.id]
            return gone

    def source_stalled(self) -> bool:
        return any(f.type == "replay_interruption" for f in self.active())

    def apply(self, values: Dict[int, float]) -> Dict[int, Optional[float]]:
        """Cell values after all active faults; None = the cell is not reported this sample. Call once per sample."""
        now = self._clock()
        out: Dict[int, Optional[float]] = dict(values)
        with self._lock:
            for f in self._faults.values():
                for cell in (f.cells or list(values)):
                    if out.get(cell) is None or f.type in SOURCE_FAULTS:
                        continue
                    out[cell] = self._signal(f, cell, out[cell], now)
            for f in self._faults.values():
                if f.type == "dropout":
                    for cell in (f.cells or list(values)):
                        out[cell] = None
        return out

    @staticmethod
    def _signal(f: Fault, cell: int, value: float, now: float) -> float:
        if f.type == "stuck":
            return f._held.setdefault(cell, f.params.get("value", value))
        if f.type == "spike":
            left = f._samples_left.setdefault(cell, f.params["samples"])
            if left <= 0:
                return value
            f._samples_left[cell] = left - 1
            return round(value + f.params["delta"], 2)
        if f.type == "drift":
            return round(value + f.params["rate_c_per_s"] * (now - f.started_at), 2)
        return f.params["value"]  # out_of_range
