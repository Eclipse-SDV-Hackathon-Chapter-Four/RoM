# Made with Claude (Claude Code, Anthropic)
import io
import json
import os
from types import SimpleNamespace

from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.ustatus_pb2 import UStatus

from rom_common import contracts
from rom_common.contracts import CRITICAL, MONITORING, SENSOR_FAULT, STATES, WARNING, parse_display_cmd
from rom_common.jsonlog import JsonLogger
from rom_uprotocol import contract, uris
from rom_uprotocol.publisher import SignalPublisher
from guardian import guardian as gmod
from guardian.guardian import (MITIGATING, SCENARIO, Guardian, display_cmd, fault_edges, report_faults,
                               scenario_fault_events)


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


def test_dfm_fixture_matches_scenario():
    fixture = os.path.join(os.path.dirname(__file__), "../../dfm/fixtures/guardian_events.jsonl")
    assert open(fixture).read().splitlines() == scenario_fault_events()  # regenerate: make dfm-fixtures


# --- heartbeats ------------------------------------------------------------------------------------------------
from rom_common.contracts import (CLEAR, COMPONENT_ADAPTER, COMPONENT_CHIP, COMPONENT_DATABROKER,  # noqa: E402
                                  COMPONENT_SIMULATOR, COMPONENT_UPROTOCOL, HB_DOWN, HB_OK, HEARTBEAT_FAULTS)
from rom_uprotocol.subscriber import CellsSample, HeartbeatSample  # noqa: E402
from guardian.heartbeats import HeartbeatMonitor  # noqa: E402


def monitored(required=(COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)):
    return Guardian(heartbeats=HeartbeatMonitor(required, stale_s=1.5, start=0.0, grace_s=5.0))


def beat(g, now, *components, status=HB_OK):
    for c in components:
        g.feed_heartbeat(now, c, status)


def alive(g, t):
    """The whole chain beats and the pack reports at time t."""
    beat(g, t, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    return g.update(t, healthy(t))


def test_nothing_is_expected_without_a_heartbeat_monitor():
    g = Guardian()
    assert g.update(100, healthy(0))[0] == MONITORING and g.lost == []


def test_required_heartbeats_get_a_startup_grace_period():
    g = monitored()
    assert g.update(4.9, None) == (CLEAR, "no data yet") and g.faults == {}
    assert g.update(5.1, None) == (SENSOR_FAULT, "uP link lost")
    assert g.faults == {HEARTBEAT_FAULTS[COMPONENT_UPROTOCOL]: None}


def test_a_healthy_chain_is_monitoring_without_faults():
    g = monitored()
    for t in range(0, 6):
        state, reason = alive(g, t)
    assert (state, reason) == (MONITORING, "temp ok") and g.lost == [] and g.faults == {}


def test_uprotocol_beat_gone_is_the_root_cause_not_its_symptoms():
    g = monitored()
    for t in range(0, 4):
        alive(g, t)
    assert g.update(5.0, None) == (SENSOR_FAULT, "uP link lost")             # nothing beat for 2 s
    assert g.lost == [COMPONENT_UPROTOCOL, COMPONENT_DATABROKER]
    assert g.faults == {HEARTBEAT_FAULTS[COMPONENT_UPROTOCOL]: None}        # one code, no signal_stale on top


def test_databroker_reporting_down_is_named_at_once_while_the_link_is_fine():
    g = monitored()
    alive(g, 1)
    beat(g, 1.2, COMPONENT_UPROTOCOL)
    beat(g, 1.2, COMPONENT_DATABROKER, status=HB_DOWN)
    assert g.update(1.2, None) == (SENSOR_FAULT, "KUKSA down")
    assert g.faults == {HEARTBEAT_FAULTS[COMPONENT_DATABROKER]: None}
    alive(g, 1.5)
    assert g.update(1.6, healthy(1.6))[0] == MONITORING and g.faults == {}   # and it clears when KUKSA is back


def test_a_databroker_beat_that_goes_silent_counts_like_down():
    g = monitored()
    alive(g, 1)
    beat(g, 2.0, COMPONENT_UPROTOCOL)                      # the link keeps beating every period ...
    beat(g, 2.9, COMPONENT_UPROTOCOL)                      # ... only the databroker beat is missing
    assert g.update(2.9, healthy(2.9)) == (SENSOR_FAULT, "KUKSA down")


def test_chip_is_tracked_from_its_first_beat_and_a_dead_chip_overrides_flowing_data():
    g = monitored()
    beat(g, 0.5, COMPONENT_CHIP)
    for t in (1, 1.5):
        alive(g, t)
    for t in (2.0, 2.5, 3.0):
        beat(g, t, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
        state, reason = g.update(t, healthy(t))        # data keeps arriving, the chip stopped beating
    assert (state, reason) == (SENSOR_FAULT, "chip silent") and g.lost == [COMPONENT_CHIP]
    assert g.faults == {HEARTBEAT_FAULTS[COMPONENT_CHIP]: None}
    beat(g, 3.1, COMPONENT_CHIP)
    assert g.update(3.1, healthy(3.1))[0] == MONITORING and g.faults == {}


def test_a_chip_reporting_down_is_silent_at_once():
    g = monitored()
    beat(g, 0.5, COMPONENT_CHIP)
    alive(g, 1)
    beat(g, 1.2, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    beat(g, 1.2, COMPONENT_CHIP, status=HB_DOWN)           # the adapter saw the telemetry stop and reports 0
    assert g.update(1.2, healthy(1.2)) == (SENSOR_FAULT, "chip silent")


def test_a_chip_that_never_beat_is_missed_only_if_it_is_required():
    g = monitored()
    assert alive(g, 10)[0] == MONITORING
    g = monitored(required=(COMPONENT_UPROTOCOL, COMPONENT_DATABROKER, COMPONENT_CHIP))
    beat(g, 6, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    assert g.update(6, healthy(6)) == (SENSOR_FAULT, "chip silent")


def test_producer_is_blamed_before_the_chip_and_simulator_is_named_sim_down():
    g = monitored()
    beat(g, 0.5, COMPONENT_ADAPTER, COMPONENT_CHIP)
    alive(g, 1)
    beat(g, 2.0, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    beat(g, 3.0, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    assert g.update(3.0, healthy(3.0)) == (SENSOR_FAULT, "adapter down") and g.lost == [COMPONENT_ADAPTER, COMPONENT_CHIP]
    g = monitored()
    beat(g, 0.5, COMPONENT_SIMULATOR)
    alive(g, 1)
    beat(g, 2.0, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    beat(g, 3.0, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    assert g.update(3.0, healthy(3.0)) == (SENSOR_FAULT, "sim down")


def test_a_sharper_root_cause_replaces_the_code_and_the_edges_say_so():
    g = monitored()
    beat(g, 0.5, COMPONENT_CHIP)
    alive(g, 1)
    beat(g, 2.0, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    beat(g, 3.0, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
    g.update(3.0, healthy(3.0))                            # chip silent
    before = g.faults
    beat(g, 3.1, COMPONENT_UPROTOCOL)
    beat(g, 3.1, COMPONENT_DATABROKER, status=HB_DOWN)
    g.update(3.1, None)                                    # KUKSA down is closer to the guardian
    assert fault_edges(before, g.faults) == [(HEARTBEAT_FAULTS[COMPONENT_CHIP], "PASSED", None),
                                             (HEARTBEAT_FAULTS[COMPONENT_DATABROKER], "FAILED", None)]


def test_thermal_codes_keep_their_state_while_a_heartbeat_is_lost():
    g = monitored()
    for t in range(0, 6):
        beat(g, t, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER)
        g.update(t, {1: 40.0 + t, 2: 30.0, 3: 30.5 + t * 0.1, 4: 31.0 - t * 0.1})        # cell 1 over WARN_C
    assert contracts.FAULT_OVER_TEMP_WARNING in g.faults
    beat(g, 6.2, COMPONENT_UPROTOCOL)
    beat(g, 6.2, COMPONENT_DATABROKER, status=HB_DOWN)
    g.update(6.2, None)
    assert contracts.FAULT_OVER_TEMP_WARNING in g.faults and HEARTBEAT_FAULTS[COMPONENT_DATABROKER] in g.faults
    assert contracts.FAULT_SIGNAL_STALE not in g.faults    # the heartbeat explains the silence


def test_heartbeat_status_for_logs():
    g = monitored()
    beat(g, 1.0, COMPONENT_UPROTOCOL)
    assert g.heartbeats.status(1.0) == {COMPONENT_DATABROKER: "waiting", COMPONENT_UPROTOCOL: "ok"}
    assert g.heartbeats.status(6.5)[COMPONENT_DATABROKER] == "lost"
    beat(g, 6.6, COMPONENT_DATABROKER, status=HB_DOWN)
    assert g.heartbeats.status(6.6)[COMPONENT_DATABROKER] == "down"


# --- the live loop ---------------------------------------------------------------------------------------------

class Feed:
    """Stands in for the queue: hands out the given items, then ends the loop."""

    def __init__(self, *items):
        self.items = list(items)

    def get(self, timeout=None):
        if not self.items:
            raise KeyboardInterrupt
        return self.items.pop(0)


class Display:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.sent.append(json.loads(payload))


def cells_msg(seq, **cells):
    return CellsSample(cells={int(k[1:]): v for k, v in cells.items()}, seq=seq, ts_ms=1, source_ts_ms=1, rx_ts_ms=1,
                       run_id="r1", msg_id=f"cells{seq}")


def beat_msg(component, status=HB_OK, seq=1):
    return HeartbeatSample(component=component, status=status, seq=seq, ts_ms=1, rx_ts_ms=1, msg_id=f"hb{seq}")


def run_loop(*items, states=None):
    buf, display, sent = io.StringIO(), Display(), []
    faults_out = SignalPublisher(lambda m: sent.append(m) or UStatus(code=UCode.OK), uris.guardian_fault_topic("v"), 0)
    states_out = None if states is None else SignalPublisher(
        lambda m: states.append(contract.parse_state_event(m.payload)) or UStatus(code=UCode.OK),
        uris.guardian_state_topic("v"), 0)
    try:
        gmod.loop(Feed(*items), JsonLogger("guardian", None, buf), display, faults_out, states_out)
    except KeyboardInterrupt:
        pass
    return [json.loads(l) for l in buf.getvalue().splitlines()], display, sent


def test_loop_publishes_every_state_and_reason_change_for_the_evidence_collector():
    states = []
    run_loop(cells_msg(1, c1=30.0, c2=29.0, c3=28.5, c4=28.8),
             beat_msg(COMPONENT_CHIP, HB_OK, seq=1), beat_msg(COMPONENT_CHIP, HB_DOWN, seq=2),
             beat_msg(COMPONENT_DATABROKER, HB_DOWN, seq=3), states=states)
    changes = [(s.previous, s.state, s.reason) for s in states]
    assert changes[:3] == [("CLEAR", "MONITORING", "temp ok"), ("MONITORING", "SENSOR_FAULT", "chip silent"),
                           ("SENSOR_FAULT", "SENSOR_FAULT", "KUKSA down")]
    assert states[1].msg_id == "hb2" and states[1].run_id == "r1" and states[0].cells


def test_loop_reports_a_lost_heartbeat_with_its_message_and_the_dfm_event():
    events, display, sent = run_loop(
        cells_msg(1, c1=30.0, c2=29.0, c3=28.5, c4=28.8),
        beat_msg(COMPONENT_DATABROKER, HB_DOWN, seq=2))
    change = [e for e in events if e["event"] == "state_change"][-1]
    assert (change["to"], change["reason"], change["lost"]) == ("SENSOR_FAULT", "KUKSA down", ["databroker"])
    assert change["msg_id"] == "hb2" and change["run_id"] == "r1"
    fault = [e for e in events if e["event"] == "fault_event"][-1]
    assert (fault["code"], fault["stage"], fault["msg_id"], fault["run_id"]) == (
        HEARTBEAT_FAULTS[COMPONENT_DATABROKER], "FAILED", "hb2", "r1")
    assert contract.parse_fault_event(sent[-1].payload).code == HEARTBEAT_FAULTS[COMPONENT_DATABROKER]
    assert display.sent[-1]["state"] == "SENSOR_FAULT" and display.sent[-1]["reason"] == "KUKSA down"


def test_loop_logs_a_reason_change_inside_the_same_state():
    events, _, _ = run_loop(
        cells_msg(1, c1=30.0, c2=29.0, c3=28.5, c4=28.8),
        beat_msg(COMPONENT_CHIP, HB_OK, seq=1), beat_msg(COMPONENT_CHIP, HB_DOWN, seq=2),
        beat_msg(COMPONENT_DATABROKER, HB_DOWN, seq=3))
    kinds = [(e["event"], e["reason"]) for e in events if e["event"] in ("state_change", "reason_change")]
    assert kinds == [("state_change", "temp ok"), ("state_change", "chip silent"), ("reason_change", "KUKSA down")]
    assert [e for e in events if e["event"] == "reason_change"][0]["previous_reason"] == "chip silent"


def test_loop_survives_a_sensor_fault_before_any_cell_was_seen():
    events, _, _ = run_loop(beat_msg(COMPONENT_UPROTOCOL, HB_DOWN))
    change = [e for e in events if e["event"] == "state_change"][0]
    assert change["to"] == "SENSOR_FAULT" and change["temp_c"] is None


def test_when_the_link_comes_back_the_other_components_are_not_blamed_while_their_beats_are_on_their_way():
    g = monitored()
    beat(g, 0.5, COMPONENT_SIMULATOR)
    for t in (1, 1.5, 2):
        beat(g, t, COMPONENT_UPROTOCOL, COMPONENT_DATABROKER, COMPONENT_SIMULATOR)
    g.update(2, healthy(2))
    assert g.update(5, None)[1] == "uP link lost"                     # a 3 s hole in all beats
    beat(g, 5.1, COMPONENT_UPROTOCOL)                                 # the link is back, the others not yet
    assert g.update(5.1, healthy(5.1))[0] == MONITORING and g.lost == [] and g.faults == {}
    beat(g, 5.4, COMPONENT_DATABROKER, COMPONENT_SIMULATOR)
    assert g.update(5.4, healthy(5.4))[0] == MONITORING
    beat(g, 6.0, COMPONENT_UPROTOCOL)
    beat(g, 6.5, COMPONENT_UPROTOCOL)
    g.update(7.0, healthy(7.0))                                       # databroker really went silent afterwards
    assert g.lost[0] == COMPONENT_DATABROKER
