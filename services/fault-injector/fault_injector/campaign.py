# Made with Claude (Claude Code, Anthropic)
"""Campaign files (YAML): one hazard, the faults that provoke it, and what the guardian must do about it.

    run_id: thermal-runaway-01          # correlation id on every log line, here and in the simulator / publisher
    seed: 7                             # makes the run replayable (cell offsets, drop probability)
    hazard: "H1: thermal runaway of one traction battery cell"
    safety_goal: "SG1: warn at 38 °C and request cooling at 45 °C"
    expected_state: CRITICAL            # what the guardian must reach (evidence collector checks it)
    max_detect_ms: 15000                # ... within this long after the first fault
    duration_s: 60                      # optional; default = last fault end + settle_s (default 10)
    baseline: {min_c: 25, max_c: 32}    # optional nominal wave (+ period_s); keeps it clear of the 38 / 45 °C thresholds
    faults:
      - {at_s: 10, duration_s: 40, target: simulator, type: drift, cell: 1, params: {rate_c_per_s: 0.8}}

`target: simulator` faults (signal and source) go to the simulator API, `target: publisher` faults (transport) to
the vss-uprotocol-client API. duration_s on a fault is optional: without it the fault lasts until the campaign ends.
Fault parameters are checked by the services when the fault is injected.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from rom_common.contracts import STATES

CAMPAIGN_DIR = Path(__file__).parent / "campaigns"
EXPECTED_STATES = STATES + ("MITIGATING",)  # the guardian's internal state; the display shows it as CRITICAL
FAULT_TYPES = {
    "simulator": ("stuck", "spike", "drift", "out_of_range", "dropout", "replay_interruption"),
    "publisher": ("drop", "reorder", "duplicate", "delay"),
}
DEFAULT_SETTLE_S = 10.0


class CampaignError(ValueError):
    """The campaign file is not valid (the message says where)."""


@dataclass(frozen=True)
class FaultStep:
    index: int
    at_s: float
    target: str
    type: str
    cells: List[int] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    duration_s: Optional[float] = None

    def request(self) -> dict:
        """Body for POST /faults. Timing stays with the runner, so no duration_s here."""
        body = {"type": self.type, "params": self.params}
        if self.cells:
            body["cells"] = self.cells
        return body

    def as_dict(self) -> dict:
        return {"index": self.index, "at_s": self.at_s, "target": self.target, "type": self.type,
                "cells": self.cells, "params": self.params, "duration_s": self.duration_s}


@dataclass(frozen=True)
class Campaign:
    run_id: str
    seed: int
    hazard: str
    safety_goal: str
    expected_state: str
    max_detect_ms: int
    duration_s: float
    faults: List[FaultStep]
    baseline: dict = field(default_factory=dict)

    def targets(self) -> set:
        return {f.target for f in self.faults}


def _number(value, where: str, minimum: float, allow_equal: bool = True) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not ok or value < minimum or (not allow_equal and value == minimum):
        raise CampaignError(f"{where} must be a number {'>=' if allow_equal else '>'} {minimum}")
    return float(value)


def _text(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CampaignError(f"{key} is required (non-empty text)")
    return value.strip()


def _baseline(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - {"min_c", "max_c", "period_s"}:
        raise CampaignError("baseline takes min_c, max_c and period_s")
    out = {k: _number(v, f"baseline.{k}", -273.15 if k != "period_s" else 0, k != "period_s") for k, v in raw.items()}
    if ("min_c" in out) != ("max_c" in out) or out.get("min_c", 0) >= out.get("max_c", 1):
        raise CampaignError("baseline needs min_c < max_c, both or neither")
    return out


def _fault(index: int, raw) -> FaultStep:
    where = f"faults[{index}]"
    if not isinstance(raw, dict):
        raise CampaignError(f"{where} must be a mapping")
    unknown = set(raw) - {"at_s", "duration_s", "target", "type", "cell", "cells", "params"}
    if unknown:
        raise CampaignError(f"{where}: unknown keys {', '.join(sorted(unknown))}")
    target = raw.get("target")
    if target not in FAULT_TYPES:
        raise CampaignError(f"{where}.target must be one of {', '.join(FAULT_TYPES)}")
    if raw.get("type") not in FAULT_TYPES[target]:
        raise CampaignError(f"{where}.type must be one of {', '.join(FAULT_TYPES[target])} for target {target}")
    if "cell" in raw and "cells" in raw:
        raise CampaignError(f"{where}: use cell or cells, not both")
    cells = raw.get("cells", [raw["cell"]] if "cell" in raw else [])
    if target == "publisher" and cells:
        raise CampaignError(f"{where}: transport faults hit the whole stream, they take no cell")
    if not isinstance(cells, list) or not all(isinstance(c, int) and not isinstance(c, bool) and 1 <= c <= 4 for c in cells):
        raise CampaignError(f"{where}.cell(s) must be cell numbers between 1 and 4")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise CampaignError(f"{where}.params must be a mapping")
    duration = raw.get("duration_s")
    return FaultStep(index, _number(raw.get("at_s"), f"{where}.at_s", 0), target, raw["type"], sorted(set(cells)),
                     params, None if duration is None else _number(duration, f"{where}.duration_s", 0, False))


def parse(data) -> Campaign:
    if not isinstance(data, dict):
        raise CampaignError("a campaign is a YAML mapping")
    known = {"run_id", "seed", "hazard", "safety_goal", "expected_state", "max_detect_ms", "duration_s", "settle_s",
             "baseline", "faults"}
    if set(data) - known:
        raise CampaignError(f"unknown keys {', '.join(sorted(set(data) - known))}")
    if data.get("expected_state") not in EXPECTED_STATES:
        raise CampaignError(f"expected_state must be one of {', '.join(EXPECTED_STATES)}")
    seed = data.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise CampaignError("seed must be an integer")
    raw_faults = data.get("faults")
    if not isinstance(raw_faults, list) or not raw_faults:
        raise CampaignError("faults must be a non-empty list")
    faults = [_fault(i, f) for i, f in enumerate(raw_faults)]
    last_end = max(f.at_s + (f.duration_s or 0.0) for f in faults)
    duration = (_number(data["duration_s"], "duration_s", 0, False) if "duration_s" in data
                else last_end + _number(data.get("settle_s", DEFAULT_SETTLE_S), "settle_s", 0))
    if duration < last_end:
        raise CampaignError(f"duration_s ({duration:g}) ends before the last fault does ({last_end:g})")
    if any(f.at_s >= duration for f in faults):
        raise CampaignError("a fault starts after the campaign ends")
    return Campaign(_text(data, "run_id"), seed, _text(data, "hazard"), _text(data, "safety_goal"),
                    data["expected_state"], int(_number(data.get("max_detect_ms"), "max_detect_ms", 0, False)),
                    duration, faults, _baseline(data.get("baseline")))


def resolve(name_or_path: str) -> Path:
    """A path, or the name of a bundled campaign (thermal_runaway or thermal_runaway.yaml)."""
    path = Path(name_or_path)
    if path.is_file():
        return path
    bundled = CAMPAIGN_DIR / (name_or_path if name_or_path.endswith((".yaml", ".yml")) else name_or_path + ".yaml")
    if bundled.is_file():
        return bundled
    raise CampaignError(f"no campaign file {name_or_path!r} (bundled: {', '.join(bundled_names()) or 'none'})")


def bundled_names() -> List[str]:
    return sorted(p.stem for p in CAMPAIGN_DIR.glob("*.yaml"))


def load(name_or_path: str) -> Campaign:
    path = resolve(name_or_path)
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise CampaignError(f"{path.name}: invalid YAML: {e}") from e
    try:
        return parse(data)
    except CampaignError as e:
        raise CampaignError(f"{path.name}: {e}") from e
