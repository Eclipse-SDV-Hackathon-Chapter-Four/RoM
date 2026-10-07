# Made with Claude (Claude Code, Anthropic)
import pytest

from simulator.faults import FaultError, FaultState
from simulator.wave import cell_offsets, cell_temps

CELLS = {1: 40.0, 2: 39.0, 3: 38.0, 4: 37.0}


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def state():
    clock = Clock()
    return FaultState(clock), clock


def test_no_faults_changes_nothing():
    fs, _ = state()
    assert fs.apply(CELLS) == CELLS


def test_stuck_holds_the_value_at_injection_and_only_for_its_cell():
    fs, _ = state()
    fs.add("stuck", [2])
    assert fs.apply(CELLS)[2] == 39.0
    out = fs.apply({**CELLS, 2: 50.0, 1: 41.0})
    assert out[2] == 39.0 and out[1] == 41.0


def test_stuck_at_given_value():
    fs, _ = state()
    fs.add("stuck", [1], {"value": 25})
    assert fs.apply(CELLS)[1] == 25.0


def test_spike_lasts_the_given_number_of_samples():
    fs, _ = state()
    fs.add("spike", [1], {"delta": 20, "samples": 2})
    assert [fs.apply(CELLS)[1] for _ in range(3)] == [60.0, 60.0, 40.0]


def test_drift_grows_with_time():
    fs, clock = state()
    fs.add("drift", [1], {"rate_c_per_s": 2})
    assert fs.apply(CELLS)[1] == 40.0
    clock.t = 5
    assert fs.apply(CELLS)[1] == 50.0


def test_out_of_range_defaults_to_200_and_all_cells_when_none_given():
    fs, _ = state()
    fs.add("out_of_range")
    assert set(fs.apply(CELLS).values()) == {200.0}
    fs.clear()
    fs.add("out_of_range", [3], {"value": -50})
    assert fs.apply(CELLS)[3] == -50.0


def test_dropout_removes_cells_or_everything():
    fs, _ = state()
    fs.add("dropout", [1, 2])
    assert fs.apply(CELLS) == {1: None, 2: None, 3: 38.0, 4: 37.0}
    fs.clear()
    fs.add("dropout")
    assert set(fs.apply(CELLS).values()) == {None}


def test_dropout_wins_over_a_signal_fault_on_the_same_cell():
    fs, _ = state()
    fs.add("spike", [1], {"delta": 5})
    fs.add("dropout", [1])
    assert fs.apply(CELLS)[1] is None


def test_replay_interruption_stalls_the_source():
    fs, _ = state()
    assert not fs.source_stalled()
    f = fs.add("replay_interruption")
    assert fs.source_stalled()
    fs.remove(f.id)
    assert not fs.source_stalled()


def test_duration_expires_the_fault():
    fs, clock = state()
    f = fs.add("dropout", duration_s=3)
    clock.t = 2.9
    assert fs.expire() == []
    clock.t = 3.0
    assert [x.id for x in fs.expire()] == [f.id] and fs.active() == []


def test_remove_and_clear():
    fs, _ = state()
    a, b = fs.add("dropout"), fs.add("stuck")
    assert fs.remove(a.id).id == a.id and fs.remove(a.id) is None
    assert [f.id for f in fs.clear()] == [b.id] and fs.active() == []


@pytest.mark.parametrize("args", [
    ("nope",), ("stuck", [0]), ("stuck", [5]), ("stuck", ["1"]), ("stuck", "1"),
    ("spike", [1], {}), ("spike", [1], {"delta": "x"}), ("spike", [1], {"delta": 1, "samples": 0}),
    ("drift", [1], {}), ("out_of_range", [1], {"value": True}), ("stuck", [1], {}, 0), ("stuck", [1], {}, "5"),
    ("replay_interruption", [1]), ("stuck", [1], [1]),
])
def test_invalid_requests_are_rejected(args):
    fs, _ = state()
    with pytest.raises(FaultError):
        fs.add(*args)


def test_cells_are_normalised():
    fs, _ = state()
    assert fs.add("dropout", [3, 1, 3]).cells == [1, 3]


def test_cell_wave_is_deterministic_and_cell_1_is_hottest():
    assert cell_offsets(7) == cell_offsets(7) and cell_offsets(7) != cell_offsets(8)
    for t in range(0, 240, 5):
        temps = cell_temps(t, cell_offsets(7))
        assert temps[0] == max(temps) and temps == sorted(temps, reverse=True)
    assert cell_temps(60, cell_offsets(0))[0] == 69.0  # cell 1 follows the pack wave exactly
