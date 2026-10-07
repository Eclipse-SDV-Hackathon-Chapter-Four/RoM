# Made with Claude (Claude Code, Anthropic)
import pytest
from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.ustatus_pb2 import UStatus

from rom_uprotocol.faults import FaultError, TransportFaults


class Wire:
    """Stands in for transport.send_sync and for the delay timer."""

    def __init__(self):
        self.sent, self.timers = [], []

    def send(self, message):
        self.sent.append(message)
        return UStatus(code=UCode.OK)

    def schedule(self, delay_s, fn):
        self.timers.append((delay_s, fn))

    def run_timers(self):
        for _, fn in self.timers:
            fn()
        self.timers = []


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def setup(seed=0):
    wire, clock = Wire(), Clock()
    return TransportFaults(seed, clock, wire.schedule), wire, clock


def push(faults, wire, *messages):
    return [faults(m, wire.send) for m in messages]


def test_without_faults_messages_pass_straight_through():
    f, wire, _ = setup()
    push(f, wire, "a", "b")
    assert wire.sent == ["a", "b"] and f.counts["seen"] == 2


def test_drop_all_and_status_is_still_ok():
    f, wire, _ = setup()
    f.add("drop")
    statuses = push(f, wire, "a", "b")
    assert wire.sent == [] and all(s.code == UCode.OK for s in statuses) and f.counts["dropped"] == 2


def test_drop_probability_is_seeded_and_repeatable():
    def run(seed):
        f, wire, _ = setup(seed)
        f.add("drop", {"probability": 0.5})
        push(f, wire, *range(40))
        return wire.sent
    assert run(1) == run(1) and run(1) != run(2) and 5 < len(run(1)) < 35


def test_duplicate_sends_extra_copies():
    f, wire, _ = setup()
    f.add("duplicate", {"copies": 2})
    push(f, wire, "a")
    assert wire.sent == ["a", "a", "a"] and f.counts["duplicated"] == 2


def test_delay_goes_through_the_timer_not_the_wire():
    f, wire, _ = setup()
    f.add("delay", {"ms": 1500})
    status = push(f, wire, "a")[0]
    assert status.code == UCode.OK and wire.sent == [] and [d for d, _ in wire.timers] == [1.5]
    wire.run_timers()
    assert wire.sent == ["a"]


def test_reorder_swaps_pairs():
    f, wire, _ = setup()
    f.add("reorder")
    push(f, wire, 1, 2, 3, 4)
    assert wire.sent == [2, 1, 4, 3]


def test_clearing_reorder_releases_the_held_message_before_the_next_one():
    f, wire, _ = setup()
    fault = f.add("reorder")
    push(f, wire, 1)
    assert wire.sent == []
    f.remove(fault.id)
    push(f, wire, 2)
    assert wire.sent == [1, 2]


def test_faults_combine_duplicate_then_delay():
    f, wire, _ = setup()
    f.add("duplicate")
    f.add("delay", {"ms": 100})
    push(f, wire, "a")
    assert len(wire.timers) == 2 and wire.sent == []


def test_drop_beats_everything_else():
    f, wire, _ = setup()
    f.add("drop")
    f.add("duplicate")
    push(f, wire, "a")
    assert wire.sent == [] and wire.timers == []


def test_duration_expires_on_the_next_message():
    f, wire, clock = setup()
    f.add("drop", duration_s=5)
    push(f, wire, "a")
    clock.t = 5
    push(f, wire, "b")
    assert wire.sent == ["b"] and f.active() == []


def test_reset_clears_faults_counters_and_reseeds():
    f, wire, _ = setup()
    f.add("drop")
    push(f, wire, "a")
    f.reset(3)
    push(f, wire, "b")
    assert wire.sent == ["b"] and f.counts["dropped"] == 0 and f.counts["seen"] == 1


@pytest.mark.parametrize("args", [
    ("nope",), ("drop", {"probability": 2}), ("drop", {"probability": "x"}), ("delay", {}), ("delay", {"ms": -1}),
    ("duplicate", {"copies": 0}), ("duplicate", {"copies": 99}), ("drop", [1]), ("drop", {}, 0), ("drop", {}, "5"),
])
def test_invalid_requests_are_rejected(args):
    f, _, _ = setup()
    with pytest.raises(FaultError):
        f.add(*args)
