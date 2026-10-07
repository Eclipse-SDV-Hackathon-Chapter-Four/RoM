# Made with Claude (Claude Code, Anthropic)
import io
import json

import pytest

from rom_common.contracts import VSS_CELL_TEMPS
from rom_common.jsonlog import JsonLogger
from simulator import simulator
from simulator.cooling import COMMAND_TTL_S, Cooling
from simulator.faults import FaultState
from simulator.wave import cell_offsets, cell_temps


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_cools_while_mitigating_and_relaxes_back_afterwards():
    clock = Clock()
    c = Cooling(3.0, 0.5, clock)
    assert c.step() == 0.0
    c.on_state("MITIGATING")
    clock.t = 2.0
    assert c.step() == -6.0 and c.active()
    c.on_state("MONITORING")
    clock.t = 4.0
    assert c.step() == -5.0                       # relaxes at 0.5 °C/s, never above 0
    clock.t = 100.0
    assert c.step() == 0.0


def test_a_silent_guardian_is_no_cooling_request():
    clock = Clock()
    c = Cooling(3.0, 0.0, clock)
    c.step()
    c.on_state("MITIGATING")
    clock.t = COMMAND_TTL_S + 0.1
    assert not c.active()


def test_reset_on_a_new_run():
    clock = Clock()
    c = Cooling(3.0, 0.0, clock)
    c.step()
    c.on_state("MITIGATING")
    clock.t = 1.0
    c.step()
    c.reset()
    assert c.step() == 0.0 and not c.active()


def test_simulator_applies_cooling_before_the_faults():
    clock = {"t": 0.0}
    mono = lambda: clock["t"]  # noqa: E731
    cooling, faults = Cooling(4.0, 0.0, mono), FaultState(mono)
    cooling.on_state("MITIGATING")
    faults.add("stuck", [2], {"value": 30.0})
    sent, out = [], io.StringIO()

    def sleep(s):
        clock["t"] += s
        cooling.on_state("MITIGATING")             # the guardian keeps repeating its state

    simulator.run(sent.append, JsonLogger("simulator", "r1", out), hz=2, duration_s=2, sleep=sleep, monotonic=mono,
                  faults=faults, cooling=cooling)
    wave = cell_temps(1.5, cell_offsets(0), 120, 30, 69)
    last = sent[-1]
    assert last[VSS_CELL_TEMPS[0]] == pytest.approx(wave[0] - 6.0)   # 1.5 s at 4 °C/s
    assert last[VSS_CELL_TEMPS[1]] == 30.0                            # a stuck sensor does not see the cooling
    assert json.loads(out.getvalue().splitlines()[-2])["cooling_c"] == -6.0


def test_closed_loop_thermal_runaway_is_mitigated_without_mitigation_failed():
    """thermal_runaway.yaml against the real guardian logic: drift 0.7 °C/s on cell 1 from 10 s to 60 s, calm wave
    25-32 °C, guardian at 2 Hz, cooling at the default 3 °C/s. Cooling must win within MITIGATION_TIMEOUT_S."""
    gmod = pytest.importorskip("guardian.guardian")
    clock = Clock()
    cooling, g = Cooling(clock=clock), gmod.Guardian()
    offsets, states, faults = cell_offsets(7), [], set()
    for i in range(0, 140):
        clock.t = i * 0.5
        cooled = cooling.step()
        cells = {c + 1: round(v + cooled, 2) for c, v in enumerate(cell_temps(clock.t, offsets, 120, 25, 32))}
        if 10 <= clock.t < 60:
            cells[1] = round(cells[1] + 0.7 * (clock.t - 10), 2)
        state, _ = g.update(clock.t, cells)
        cooling.on_state(state)
        states.append(state)
        faults |= set(g.faults)
    assert "MITIGATING" in states and "CRITICAL" in states
    assert "battery_guardian.mitigation_failed" not in faults
    assert states[-1] == "MONITORING"
