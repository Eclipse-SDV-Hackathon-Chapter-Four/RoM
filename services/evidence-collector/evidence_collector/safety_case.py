# Made with Claude (Claude Code, Anthropic)
"""Safety case: hazard -> safety goal -> safety requirement -> campaigns (run_id). See safety_case.yaml.

load() validates the whole chain and raises SafetyCaseError if a link is broken, so the collector never starts
with a safety case that cannot back its verdicts. trace(run_id, hazard, safety_goal) answers "which requirements
does this run prove", plus the mismatches between the campaign's own hazard / goal text and the safety case.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

DEFAULT_PATH = Path(__file__).parent / "safety_case.yaml"
_HAZARD_IDS = re.compile(r"\bH\d+\b")
_GOAL_ID = re.compile(r"^\s*(SG\d+)\b")


class SafetyCaseError(ValueError):
    """The safety case is not valid (the message says where)."""


@dataclass(frozen=True)
class SafetyCase:
    hazards: Dict[str, dict]
    goals: Dict[str, dict]
    requirements: Dict[str, dict]
    text: str                       # the YAML as loaded, for the evidence bundle

    def trace(self, run_id: str, hazard: str = "", safety_goal: str = "") -> Tuple[List[dict], List[str]]:
        """(requirements proven by run_id, mismatches). Each requirement comes with its goal and hazards."""
        trace, errors = [], []
        campaign_hazards = set(_HAZARD_IDS.findall(hazard or ""))
        goal_match = _GOAL_ID.match(safety_goal or "")
        for req in self.requirements.values():
            if run_id not in req["campaigns"]:
                continue
            goal = self.goals[req["safety_goal"]]
            trace.append({"requirement": {k: req[k] for k in ("id", "description")},
                          "safety_goal": {k: goal[k] for k in ("id", "description")},
                          "hazards": [self.hazards[h] for h in goal["hazards"]]})
            if not campaign_hazards & set(goal["hazards"]):
                errors.append(f"campaign hazard {hazard!r} is none of {goal['id']}'s hazards "
                              f"({', '.join(goal['hazards'])})")
        if trace and (goal_match is None or goal_match.group(1) not in {t["safety_goal"]["id"] for t in trace}):
            errors.append(f"campaign safety goal {safety_goal!r} is not the goal of "
                          f"{', '.join(t['requirement']['id'] for t in trace)}")
        return trace, errors


def _items(data: dict, key: str, fields: Tuple[str, ...]) -> Dict[str, dict]:
    raw = data.get(key)
    if not isinstance(raw, list) or not raw:
        raise SafetyCaseError(f"{key} must be a non-empty list")
    out = {}
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or any(item.get(f) in (None, "", []) for f in fields):
            raise SafetyCaseError(f"{key}[{i}] needs {', '.join(fields)}")
        if item["id"] in out:
            raise SafetyCaseError(f"{key}: duplicate id {item['id']}")
        out[item["id"]] = item
    return out


def parse(text: str) -> SafetyCase:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SafetyCaseError(f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise SafetyCaseError("the safety case is a YAML mapping")
    hazards = _items(data, "hazards", ("id", "description"))
    goals = _items(data, "safety_goals", ("id", "hazards", "description"))
    reqs = _items(data, "safety_requirements", ("id", "safety_goal", "description", "campaigns"))
    for goal in goals.values():
        missing = [h for h in goal["hazards"] if h not in hazards]
        if missing:
            raise SafetyCaseError(f"safety goal {goal['id']}: unknown hazards {', '.join(missing)}")
    for req in reqs.values():
        if req["safety_goal"] not in goals:
            raise SafetyCaseError(f"requirement {req['id']}: unknown safety goal {req['safety_goal']}")
        if not isinstance(req["campaigns"], list) or not all(isinstance(c, str) for c in req["campaigns"]):
            raise SafetyCaseError(f"requirement {req['id']}: campaigns must be a list of run_ids")
    unguarded = sorted(set(hazards) - {h for g in goals.values() for h in g["hazards"]})
    if unguarded:
        raise SafetyCaseError(f"hazards without a safety goal: {', '.join(unguarded)}")
    unrefined = sorted(set(goals) - {r["safety_goal"] for r in reqs.values()})
    if unrefined:
        raise SafetyCaseError(f"safety goals without a requirement: {', '.join(unrefined)}")
    return SafetyCase(hazards, goals, reqs, text)


def load(path=DEFAULT_PATH) -> SafetyCase:
    path = Path(path)
    try:
        return parse(path.read_text())
    except OSError as e:
        raise SafetyCaseError(f"{path}: {e}") from e
    except SafetyCaseError as e:
        raise SafetyCaseError(f"{path.name}: {e}") from e
