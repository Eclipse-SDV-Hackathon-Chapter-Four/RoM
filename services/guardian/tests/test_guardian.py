# Made with Claude (Claude Code, Anthropic)
import io
import json
from types import SimpleNamespace

from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.ustatus_pb2 import UStatus

from rom_common import contracts
from rom_common.contracts import CRITICAL, MONITORING, SENSOR_FAULT, STATES, WARNING, parse_display_cmd
from rom_common.jsonlog import JsonLogger
from rom_uprotocol import contract, uris
from rom_uprotocol.publisher import SignalPublisher
from guardian import guardian as gmod
from guardian.guardian import MITIGATING, SCENARIO, Guardian, display_cmd, fault_edges, report_faults


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


# --- 4 cells ---------------------------------------------------------------------------------------------------
def healthy(t, base=30.0):
    """Four healthy cells that keep moving (so nothing looks stuck), cell 1 the hottest."""
    return {1: base + 0.1 * t, 2: base - 1 + 0.1 * t, 3: base - 1.5 + 0.1 * t, 4: base - 1.2 + 0.1 * t}


def run(g, cells_at, seconds, step=0.5):
    t = 0.0
    while t <= seconds:
        state, reason = g.update(t, cells_at(t))
        t += step
    return state, reason


def test_one_stuck_cell_raises_its_own_code_and_the_pack_stays_monitored():
    g = Guardian()
    state, _ = run(g, lambda t: {**healthy(t), 3: 29.0}, 15)
    assert g.faults == {contracts.cell_fault(3, "signal_stuck"): 3}
    assert state == MONITORING and g.hottest == 1


def test_cell_dropout_is_stale_for_that_cell_only():
    g = Guardian()
    state, _ = run(g, lambda t: {c: v for c, v in healthy(t).items() if t < 5 or c != 2}, 10)
    assert g.faults == {contracts.cell_fault(2, "signal_stale"): 2}
    assert state == MONITORING


def test_out_of_range_cell_is_left_out_of_the_pack_temperature():
    g = Guardian()
    state, _ = run(g, lambda t: {**healthy(t), 1: 200.0}, 3)
    assert contracts.cell_fault(1, "out_of_range") in g.faults
    assert state == MONITORING and g.hottest == 2 and g.temp < 40


def test_a_hot_cell_is_still_caught_while_another_cell_is_broken():
    g = Guardian()
    state, _ = run(g, lambda t: {**healthy(t), 2: 200.0, 1: 40.0 + 0.1 * t}, 4)
    assert state == WARNING
    assert g.faults[contracts.FAULT_OVER_TEMP_WARNING] == 1
    assert contracts.cell_fault(2, "out_of_range") in g.faults


def test_all_cells_stuck_is_a_sensor_fault_with_four_codes():
    g = Guardian()
    state, reason = run(g, lambda t: {1: 30.0, 2: 29.0, 3: 28.5, 4: 28.8}, 12)
    assert (state, reason) == (SENSOR_FAULT, "stuck signal")
    assert set(g.faults) == {contracts.cell_fault(c, "signal_stuck") for c in range(1, 5)}


def test_stale_stream_adds_signal_stale_and_keeps_the_earlier_codes():
    g = Guardian()
    run(g, lambda t: {**healthy(t), 1: 200.0}, 3)
    assert contracts.cell_fault(1, "out_of_range") in g.faults
    for t in (6.0, 6.5):
        state, reason = g.update(t, None)
    assert (state, reason) == (SENSOR_FAULT, "stale signal")
    assert set(g.faults) == {contracts.cell_fault(1, "out_of_range"), contracts.FAULT_SIGNAL_STALE}
    g.update(7.0, healthy(7))
    assert contracts.FAULT_SIGNAL_STALE not in g.faults and g.state == MONITORING


def test_cell_imbalance_needs_the_spread_for_imbalance_s():
    g = Guardian()
    g.update(0.0, {**healthy(0), 1: 30.0 + gmod.IMBALANCE_C + 1})
    assert contracts.FAULT_CELL_IMBALANCE not in g.faults
    g.update(gmod.IMBALANCE_S, {**healthy(gmod.IMBALANCE_S), 1: 30.5 + gmod.IMBALANCE_C + 1})
    assert g.faults[contracts.FAULT_CELL_IMBALANCE] == 1


def test_fault_edges_order_passed_before_failed():
    a, b = contracts.cell_fault(1, "signal_stuck"), contracts.FAULT_SIGNAL_STALE
    assert fault_edges({a: 1}, {b: None}) == [(a, "PASSED", 1), (b, "FAILED", None)]
    assert fault_edges({a: 1}, {a: 1}) == []


def test_report_faults_logs_and_publishes_events_the_dfm_can_parse():
    g = Guardian()
    run(g, lambda t: {**healthy(t), 3: 29.0}, 15)
    buf, sent = io.StringIO(), []
    pub = SignalPublisher(lambda m: sent.append(m) or UStatus(code=UCode.OK), uris.guardian_fault_topic("v"), 0)
    last = SimpleNamespace(seq=31, msg_id="01a1-msg", run_id="sensor-stuck-cell3-01")
    report_faults(g, {}, last, JsonLogger("guardian", stream=buf), pub)
    event = contract.parse_fault_event(sent[0].payload)
    assert (event.code, event.stage, event.cell, event.seq, event.run_id) == (
        contracts.cell_fault(3, "signal_stuck"), "FAILED", 3, 31, "sensor-stuck-cell3-01")
    assert event.cells.split(",")[2] == "29" and event.reason == "stuck signal"
    assert event.environment_data()["cell"] == "3"
    assert sent[0].attributes.source == uris.guardian_fault_topic("v")
    logged = json.loads(buf.getvalue())
    assert logged["event"] == "fault_event" and logged["code"] == event.code
