# Made with Claude (Claude Code, Anthropic)
import pytest

from evidence_collector import safety_case
from evidence_collector.safety_case import SafetyCaseError

GOOD = """
hazards: [{id: H1, description: hot}]
safety_goals: [{id: SG1, hazards: [H1], description: warn}]
safety_requirements: [{id: SR-01, safety_goal: SG1, description: raise, campaigns: [r1]}]
"""


def test_bundled_safety_case_is_valid():
    case = safety_case.load()
    assert set(case.goals) == {f"SG{i}" for i in range(1, 9)} and len(case.requirements) == 8


def test_every_bundled_campaign_is_traced_and_matches_its_hazard_and_goal():
    campaign = pytest.importorskip("fault_injector.campaign")
    case = safety_case.load()
    for name in campaign.bundled_names():
        c = campaign.load(name)
        trace, errors = case.trace(c.run_id, c.hazard, c.safety_goal)
        assert trace, f"{name}: run_id {c.run_id} is in no safety requirement"
        assert errors == [], f"{name}: {errors}"


def test_trace_reports_mismatches():
    case = safety_case.parse(GOOD)
    assert case.trace("r1", "H1: hot", "SG1: warn")[1] == []
    assert case.trace("nope", "H1", "SG1") == ([], [])
    _, errors = case.trace("r1", "H2: other", "SG2: other")
    assert len(errors) == 2 and "none of SG1's hazards" in errors[0] and "not the goal of SR-01" in errors[1]


@pytest.mark.parametrize("change, words", [
    (("H1, description: hot", "H1, description: hot}, {id: H1, description: again"), "duplicate id H1"),
    (("hazards: [H1]", "hazards: [H9]"), "unknown hazards H9"),
    (("safety_goal: SG1", "safety_goal: SG9"), "unknown safety goal SG9"),
    (("campaigns: [r1]", "campaigns: []"), "needs id, safety_goal, description, campaigns"),
    (("hazards: [{id: H1, description: hot}]", "hazards: [{id: H1, description: hot}, {id: H2, description: x}]"),
     "hazards without a safety goal: H2"),
    (("safety_goals: [{id: SG1, hazards: [H1], description: warn}]",
      "safety_goals: [{id: SG1, hazards: [H1], description: warn}, {id: SG2, hazards: [H1], description: x}]"),
     "safety goals without a requirement: SG2"),
])
def test_broken_chains_are_refused(change, words):
    with pytest.raises(SafetyCaseError, match=words):
        safety_case.parse(GOOD.replace(*change))
