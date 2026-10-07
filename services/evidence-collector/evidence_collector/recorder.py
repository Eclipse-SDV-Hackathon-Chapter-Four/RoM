# Made with Claude (Claude Code, Anthropic)
"""Recorder: every message on the RoM topics goes to events.jsonl and the store first, then to the correlator.

Nothing is filtered: duplicates, invalid payloads and periodic repeats are evidence too ("crime scene"). Each
message gets the next line number of events.jsonl (numbering continues after a restart), and a record's raw_events
points to exactly those lines. A crash in the correlator never loses a message.

    topic name   uProtocol topic                parsed with             correlator
    campaign     up://…/1003/1/8005             parse_campaign_event    on_campaign
    fault        up://…/1002/1/8003             parse_fault_event       on_fault
    state        up://…/1002/1/8006             parse_state_event       on_state
    cells        up://…/1001/1/8002             parse_cells_msg         on_other
    heartbeat    up://…/1001/1/8004             parse_heartbeat_msg     on_other
"""
import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from rom_common import clock
from rom_uprotocol import contract

PARSERS = {
    "campaign": contract.parse_campaign_event,
    "fault": contract.parse_fault_event,
    "state": contract.parse_state_event,
    "cells": contract.parse_cells_msg,
    "heartbeat": contract.parse_heartbeat_msg,
}


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


class Recorder:
    def __init__(self, events_path, store, correlator, log=None, now=clock.now_ms):
        self.path = Path(events_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store, self.correlator, self._log, self._now = store, correlator, log, now
        self.line = _count_lines(self.path)
        self.received = 0
        self._lock = threading.Lock()   # one message at a time: line numbers and correlator order stay in step

    def handle(self, topic: str, payload: bytes, msg_id: Optional[str] = None) -> int:
        with self._lock:
            rx = self._now()
            self.line += 1
            self.received += 1
            text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
            item, error = None, None
            try:
                item = PARSERS[topic](text)
            except (contract.ContractError, KeyError) as e:
                error = str(e)
            try:
                body = json.loads(text)
            except ValueError:
                body = text
            entry = {"line": self.line, "rx_ts_ms": rx, "topic": topic, "msg_id": msg_id, "payload": body}
            if error:
                entry["rejected"] = error
            raw = json.dumps(entry, separators=(",", ":"), default=str)
            with self.path.open("a") as f:
                f.write(raw + "\n")
            self.store.add_event(self.line, rx, topic, msg_id, raw)
            try:
                self._route(topic, item)
            except Exception as e:   # the message is already on disk; log and keep recording
                if self._log is not None:
                    self._log.log("correlator_error", line=self.line, topic=topic, error=repr(e))
            return self.line

    def _route(self, topic: str, item) -> None:
        if item is None:
            self.correlator.on_other(self.line)
        elif topic == "campaign":
            self.correlator.on_campaign(asdict(item), self.line)
        elif topic == "fault":
            self.correlator.on_fault(asdict(item), self.line)
        elif topic == "state":
            self.correlator.on_state(asdict(item), self.line)
        else:
            self.correlator.on_other(self.line)

    def tick(self) -> None:
        with self._lock:
            self.correlator.tick()

    def flush(self) -> None:
        with self._lock:
            self.correlator.flush()


def subscribe(transport, recorder: Recorder) -> dict:
    """Register one raw listener per RoM topic on `transport`; returns {topic name: zenoh key or error}."""
    from uprotocol.transport.ulistener import UListener
    from uprotocol.uuid.serializer.uuidserializer import UuidSerializer
    from uprotocol.v1.ucode_pb2 import UCode

    from rom_uprotocol import uris

    topics = {"campaign": uris.campaign_event_topic(), "fault": uris.guardian_fault_topic(),
              "state": uris.guardian_state_topic(), "cells": uris.battery_cells_topic(),
              "heartbeat": uris.heartbeat_topic()}

    class Listener(UListener):
        def __init__(self, name):
            self.name = name

        async def on_receive(self, umsg) -> None:
            recorder.handle(self.name, umsg.payload, UuidSerializer.serialize(umsg.attributes.id))

    result = {}
    for name, uri in topics.items():
        status = transport.register_listener_sync(uri, Listener(name))
        result[name] = status.message if status.code == UCode.OK else f"error: {UCode.Name(status.code)}"
    return result
