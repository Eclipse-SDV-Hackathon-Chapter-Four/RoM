# Made with Claude (Claude Code, Anthropic)
import json
import os

from rom_common.contracts import (CLEAR, CRITICAL, FAILED, FAULT_MITIGATION_FAILED, FAULT_OVER_TEMP_CRITICAL,
                                  FAULT_OVER_TEMP_WARNING, FAULT_SIGNAL_STUCK, FAULTS, MONITORING, PASSED,
                                  SENSOR_FAULT, STATES, WARNING, parse_display_cmd)
from guardian.guardian import (MITIGATING, SCENARIO, Guardian, active_faults, display_cmd, scenario_fault_events)


def test_scenario_transitions():
    g, seen = Guardian(), []
    for t, temp in enumerate(SCENARIO):
        before = g.state
        state, reason = g.update(t, temp)
        if state != before:
            seen.append(reason)
    assert seen == ["temp ok", "getting hot", "too hot", "cooling requested", "temp ok", "stale signal",
                    "temp ok", "out of range", "temp ok", "getting hot", "stuck signal", "temp ok",
                    "too hot", "cooling requested", "mitigation failed"]


def test_display_cmd_follows_contract():
    for state in STATES:
        cmd = parse_display_cmd(display_cmd(state, 31.456, "why", 7, 1730000000000))
        assert (cmd["state"], cmd["temp_c"], cmd["reason"], cmd["seq"]) == (state, 31.46, "why", 7)
    assert parse_display_cmd(display_cmd("CLEAR", None, "no data yet", 1, 1))["temp_c"] is None


def test_display_cmd_shows_mitigating_as_critical():
    cmd = parse_display_cmd(display_cmd(MITIGATING, 46.0, "cooling requested", 2, 1))
    assert (cmd["state"], cmd["reason"]) == (CRITICAL, "cooling requested")


def test_active_faults_table():
    assert active_faults(WARNING, "getting hot") == {FAULT_OVER_TEMP_WARNING}
    assert active_faults(MITIGATING, "cooling requested") == {FAULT_OVER_TEMP_CRITICAL}
    assert active_faults(CRITICAL, "mitigation failed") == {FAULT_OVER_TEMP_CRITICAL, FAULT_MITIGATION_FAILED}
    assert active_faults(SENSOR_FAULT, "stuck signal") == {FAULT_SIGNAL_STUCK}
    assert active_faults(MONITORING, "temp ok") == active_faults(CLEAR, "no data yet") == frozenset()


def test_scenario_reports_every_fault_and_clears_it():
    events = [json.loads(e) for e in scenario_fault_events()]
    stages = {}
    for e in events:
        stages.setdefault(e["fault"], []).append(e["stage"])
    assert set(stages) == set(FAULTS)
    for fault, seen in stages.items():
        assert seen[0] == FAILED and all(a != b for a, b in zip(seen, seen[1:])), fault  # Failed/Passed alternate
    assert all(stages[f][-1] == PASSED for f in FAULTS if f not in (FAULT_OVER_TEMP_CRITICAL, FAULT_MITIGATION_FAILED))


def test_dfm_fixture_matches_scenario():
    fixture = os.path.join(os.path.dirname(__file__), "../../dfm/fixtures/guardian_events.jsonl")
    assert open(fixture).read().splitlines() == list(scenario_fault_events())  # regenerate: make dfm-fixtures
