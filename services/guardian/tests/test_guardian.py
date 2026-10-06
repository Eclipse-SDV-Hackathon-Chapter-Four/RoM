# Made with Claude (Claude Code, Anthropic)
from rom_common.contracts import CRITICAL, STATES, parse_display_cmd
from guardian.guardian import MITIGATING, SCENARIO, Guardian, display_cmd


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
