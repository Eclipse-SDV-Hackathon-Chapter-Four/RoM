# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
"""JSON-lines logger to stdout: {"ts_ms":..., "component":..., "event":..., ...}.

This is the raw material for the future evidence collector; include run_id
whenever one exists (it is the correlation ID).
"""
import json
import sys
import threading
from typing import Any, Optional, TextIO

from .clock import now_ms


class JsonLogger:
    def __init__(self, component: str, run_id: Optional[str] = None, stream: Optional[TextIO] = None):
        self.component = component
        self.run_id = run_id
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()

    def log(self, event: str, **fields: Any) -> None:
        rec = {"ts_ms": now_ms(), "component": self.component, "event": event}
        if self.run_id is not None:
            rec["run_id"] = self.run_id
        rec.update(fields)
        line = json.dumps(rec, separators=(",", ":"), default=str)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()


def get_logger(component: str, run_id: Optional[str] = None) -> JsonLogger:
    return JsonLogger(component, run_id)
