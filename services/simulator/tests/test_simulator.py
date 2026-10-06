# Made with Claude (Claude Code, Anthropic)
import io
import json

import pytest

from rom_common.jsonlog import JsonLogger
from simulator import simulator
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


def test_run_sends_hz_times_duration_samples_on_schedule():
    n, sent, logs, naps = _run(hz=2, period_s=10, duration_s=10)
    assert n == len(sent) == 20
    assert sent[0] == 30.0 and sent[10] == 69.0
    assert all(abs(s - 0.5) < 1e-9 for s in naps)


def test_run_logs_campaign_and_every_sample():
    _, sent, logs, _ = _run(hz=1, period_s=4, duration_s=4)
    assert [l["event"] for l in logs] == ["campaign_start"] + ["sample"] * 4 + ["campaign_end"]
    assert [l["temp_c"] for l in logs if l["event"] == "sample"] == sent
    assert all(l["run_id"] == "r1" for l in logs) and logs[-1]["samples"] == 4


def test_run_forever_stops_on_ctrl_c():
    sent = []
    def sink(t):
        sent.append(t)
        if len(sent) == 3:
            raise KeyboardInterrupt
    n = simulator.run(sink, JsonLogger("simulator", None, io.StringIO()), sleep=lambda s: None)
    assert n == 2 and len(sent) == 3


def test_main_writes_to_kuksa_vss_path(monkeypatch):
    calls = []
    class FakeClient:
        closed = False
        def close(self): self.closed = True
    fake = FakeClient()
    monkeypatch.setattr(simulator.kuksa, "open_client", lambda: fake)
    monkeypatch.setattr(simulator.kuksa, "set_temp", lambda c, t: calls.append((c, t)))
    monkeypatch.setattr(simulator.time, "sleep", lambda s: None)
    simulator.main(["--hz", "1", "--period", "4", "--duration", "4"])
    assert [t for _, t in calls] == [30.0, 49.5, 69.0, 49.5]
    assert all(c is fake for c, _ in calls) and fake.closed


def test_main_rejects_bad_range():
    with pytest.raises(SystemExit):
        simulator.main(["--min", "70", "--max", "30"])
