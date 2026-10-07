# Made with Claude (Claude Code, Anthropic)
import io
import json

import pytest

from rom_common.contracts import VSS_BATTERY_TEMP, VSS_CELL_TEMPS
from rom_common.jsonlog import JsonLogger
from simulator import simulator
from simulator.faults import FaultState
from simulator.wave import sine_temp


def test_wave_starts_low_peaks_high_and_returns():
    assert sine_temp(0) == 30.0
    assert sine_temp(60) == 69.0           # half of the 120 s period
    assert sine_temp(120) == 30.0


def test_wave_stays_in_range_and_is_continuous():
    vals = [sine_temp(i * 0.5) for i in range(0, 600)]   # 5 periods at 2 Hz
    assert min(vals) >= 30.0 and max(vals) <= 69.0
    assert max(abs(a - b) for a, b in zip(vals, vals[1:])) < 2.0   # no jumps
    assert any(v > 55 for v in vals) and any(v < 43 for v in vals)  # crosses guardian thresholds


def test_wave_respects_custom_params_and_is_deterministic():
    assert sine_temp(10, period_s=20, min_c=0, max_c=10) == 10.0
    assert [sine_temp(t) for t in range(50)] == [sine_temp(t) for t in range(50)]


def _run(**kw):
    sent, out, naps = [], io.StringIO(), []
    clock = {"t": 0.0}
    def sleep(s):
        naps.append(s)
        clock["t"] += s
    n = simulator.run(sent.append, JsonLogger("simulator", "r1", out), sleep=sleep,
                      monotonic=lambda: clock["t"], **kw)
    return n, sent, [json.loads(l) for l in out.getvalue().splitlines()], naps


def _max(sent):
    return [s[VSS_BATTERY_TEMP] for s in sent]


def test_run_sends_hz_times_duration_samples_on_schedule():
    n, sent, logs, naps = _run(hz=2, period_s=10, duration_s=10)
    assert n == len(sent) == 20
    assert _max(sent)[0] == 30.0 and _max(sent)[10] == 69.0
    assert all(abs(s - 0.5) < 1e-9 for s in naps)


def test_run_logs_campaign_and_every_sample():
    _, sent, logs, _ = _run(hz=1, period_s=4, duration_s=4)
    assert [l["event"] for l in logs] == ["campaign_start"] + ["sample"] * 4 + ["campaign_end"]
    assert [l["temp_c"] for l in logs if l["event"] == "sample"] == _max(sent)
    assert all(l["run_id"] == "r1" for l in logs) and logs[-1]["samples"] == 4


def test_run_forever_stops_on_ctrl_c():
    sent = []
    def sink(values):
        sent.append(values)
        if len(sent) == 3:
            raise KeyboardInterrupt
    n = simulator.run(sink, JsonLogger("simulator", None, io.StringIO()), sleep=lambda s: None)
    assert n == 2 and len(sent) == 3


def test_main_writes_to_kuksa_vss_path(monkeypatch):
    calls = []
    class FakeClient:  # mirrors kuksa_client.grpc.VSSClient, see test_vss_client_has_disconnect
        closed = False
        def disconnect(self): self.closed = True
    fake = FakeClient()
    monkeypatch.setattr(simulator.kuksa, "open_client", lambda: fake)
    monkeypatch.setattr(simulator.kuksa, "set_values", lambda c, values: calls.append((c, values)))
    monkeypatch.setattr(simulator.time, "sleep", lambda s: None)
    simulator.main(["--hz", "1", "--period", "4", "--duration", "4", "--api-port", "0"])
    assert [v[VSS_BATTERY_TEMP] for _, v in calls] == [30.0, 49.5, 69.0, 49.5]
    assert all(c is fake for c, _ in calls) and fake.closed


def test_vss_client_has_disconnect():
    # The fake above must not drift from the real client (it once had close(), which VSSClient lacks).
    from kuksa_client.grpc import VSSClient
    assert callable(getattr(VSSClient, "disconnect", None))


def test_main_rejects_bad_range():
    with pytest.raises(SystemExit):
        simulator.main(["--min", "70", "--max", "30"])


def test_run_writes_four_cells_and_max_is_the_hottest():
    _, sent, _, _ = _run(hz=1, period_s=4, duration_s=4)
    for values in sent:
        assert set(values) == {*VSS_CELL_TEMPS, VSS_BATTERY_TEMP}
        assert values[VSS_BATTERY_TEMP] == max(values[p] for p in VSS_CELL_TEMPS) == values[VSS_CELL_TEMPS[0]]
        cells = [values[p] for p in VSS_CELL_TEMPS]
        assert cells == sorted(cells, reverse=True)


def test_dropout_of_the_hottest_cell_lowers_max_and_skips_that_cell():
    faults = FaultState()
    faults.add("dropout", [1])
    _, sent, _, _ = _run(hz=1, period_s=4, duration_s=2, faults=faults)
    assert all(VSS_CELL_TEMPS[0] not in v for v in sent)
    assert all(v[VSS_BATTERY_TEMP] == v[VSS_CELL_TEMPS[1]] for v in sent)


def test_nothing_is_written_when_every_cell_drops_out():
    faults = FaultState()
    faults.add("dropout")
    n, sent, logs, _ = _run(hz=1, period_s=4, duration_s=3, faults=faults)
    assert n == 3 and sent == []
    assert [l["temp_c"] for l in logs if l["event"] == "sample"] == [None] * 3


def test_spike_on_cell_1_raises_max_for_one_sample():
    faults = FaultState()
    faults.add("spike", [1], {"delta": 30, "samples": 1})
    _, sent, _, _ = _run(hz=1, period_s=4, duration_s=2, faults=faults)
    assert _max(sent)[0] == 60.0 and _max(sent)[1] == 49.5


def test_drift_on_cell_1_raises_max_as_time_passes():
    clock = {"t": 0.0}
    faults = FaultState(lambda: clock["t"])
    faults.add("drift", [1], {"rate_c_per_s": 10})
    sent, out = [], io.StringIO()
    simulator.run(sent.append, JsonLogger("simulator", "r1", out), hz=1, period_s=1000, duration_s=3,
                  sleep=lambda s: clock.__setitem__("t", clock["t"] + s), monotonic=lambda: clock["t"], faults=faults)
    base = [sine_temp(t, 1000) for t in range(3)]
    assert _max(sent) == [round(b + 10 * t, 2) for t, b in enumerate(base)]


def test_replay_interruption_pauses_the_wave_and_resumes_where_it_stopped():
    clock = {"t": 0.0}
    faults = FaultState(lambda: clock["t"])
    sent, out = [], io.StringIO()
    def sleep(s):
        clock["t"] += s
        if clock["t"] == 1.0:
            faults.add("replay_interruption", duration_s=2)   # stalls ticks at t=1 and t=2
    simulator.run(sent.append, JsonLogger("simulator", "r1", out), hz=1, period_s=8, duration_s=6, sleep=sleep,
                  monotonic=lambda: clock["t"], faults=faults)
    assert len(sent) == 4                                    # 6 ticks, 2 of them silent
    assert _max(sent) == [sine_temp(t, 8) for t in (0, 1, 2, 3)]   # wave position never skipped


def test_expired_fault_is_logged_as_cleared():
    clock = {"t": 0.0}
    faults = FaultState(lambda: clock["t"])
    faults.add("dropout", duration_s=1)
    out = io.StringIO()
    simulator.run(lambda v: None, JsonLogger("simulator", "r1", out), hz=1, period_s=4, duration_s=3,
                  sleep=lambda s: clock.__setitem__("t", clock["t"] + s), monotonic=lambda: clock["t"], faults=faults)
    events = [json.loads(l) for l in out.getvalue().splitlines()]
    assert [e["reason"] for e in events if e["event"] == "fault_cleared"] == ["expired"]


def test_restart_resets_the_wave_and_reseeds():
    session = simulator.Session(seed=1)
    sent, out, n = [], io.StringIO(), {"i": 0}
    def sleep(s):
        n["i"] += 1
        if n["i"] == 2:
            session.restart(seed=99, run_id="r2")
    simulator.run(sent.append, JsonLogger("simulator", "r1", out), hz=1, period_s=8, duration_s=4, sleep=sleep,
                  monotonic=lambda: 0.0, session=session)
    assert _max(sent) == [sine_temp(0, 8), sine_temp(1, 8), sine_temp(0, 8), sine_temp(1, 8)]
    assert session.seed == 99


def test_restart_can_change_the_wave():
    session = simulator.Session()
    sent, n = [], {"i": 0}
    def sleep(s):
        n["i"] += 1
        if n["i"] == 1:
            session.restart(seed=0, run_id="r2", wave={"min_c": 10.0, "max_c": 20.0, "period_s": 4.0})
    simulator.run(sent.append, JsonLogger("simulator", "r1", io.StringIO()), hz=1, period_s=8, duration_s=3, sleep=sleep,
                  monotonic=lambda: 0.0, session=session)
    assert _max(sent) == [sine_temp(0, 8), sine_temp(0, 4, 10, 20), sine_temp(1, 4, 10, 20)]
