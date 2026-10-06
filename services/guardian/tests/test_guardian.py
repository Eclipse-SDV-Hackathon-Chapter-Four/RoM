# Made with Claude (Claude Code, Anthropic)
from guardian.guardian import SCENARIO, Guardian


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
