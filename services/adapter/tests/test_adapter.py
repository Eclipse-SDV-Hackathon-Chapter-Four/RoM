# Made with Claude (Claude Code, Anthropic)
import io
import json

import pytest

from rom_common import contracts
from rom_common.jsonlog import JsonLogger
from adapter.mqtt_kuksa_adapter import Adapter, ChipLiveness, build_mapping

TOPIC = contracts.TOPIC_SENSOR_TEMP
STATUS = contracts.TOPIC_SENSOR_STATUS
CELL1 = contracts.VSS_CELL_TEMPS[0]


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def make_adapter(write=None, mapping=None, timeout_s=1.5):
    buf = io.StringIO()
    writes, clock = [], Clock()
    adapter = Adapter(write or writes.append, JsonLogger("adapter", stream=buf), mapping or build_mapping(1),
                      chip_timeout_s=timeout_s, monotonic=clock)

    def events():
        return [json.loads(line) for line in buf.getvalue().splitlines()]

    adapter.clock = clock
    return adapter, writes, events


def msg(seq, temp_c=31.5):
    return contracts.build_sensor_msg("sensor-01", seq, 0, temp_c).encode()


def test_valid_message_is_written_to_cell_1_and_max_in_one_call():
    adapter, writes, events = make_adapter()
    adapter.handle(TOPIC, msg(1, 50.0))
    assert writes == [{CELL1: 50.0, contracts.VSS_BATTERY_TEMP: 50.0}]
    assert events()[-1]["event"] == "forwarded"


def test_board_can_be_another_cell():
    adapter, writes, _ = make_adapter(mapping=build_mapping(3))
    adapter.handle(TOPIC, msg(1, 40.0))
    assert set(writes[0]) == {contracts.VSS_CELL_TEMPS[2], contracts.VSS_BATTERY_TEMP}


@pytest.mark.parametrize("cell", [0, 5, -1])
def test_mapping_rejects_a_cell_that_does_not_exist(cell):
    with pytest.raises(ValueError):
        build_mapping(cell)


def test_invalid_message_is_rejected_and_not_written():
    adapter, writes, events = make_adapter()
    adapter.handle(TOPIC, b"not json")
    adapter.handle(TOPIC, b'{"temp_c":"hot"}')
    assert writes == []
    assert [e["event"] for e in events()] == ["rejected", "rejected"]
    assert adapter.rejected == 2
    assert not adapter.chip.alive()        # garbage is not a sign of life


def test_seq_gap_duplicate_and_backwards_are_logged():
    adapter, writes, events = make_adapter()
    for seq in (1, 2, 5, 5, 1):
        adapter.handle(TOPIC, msg(seq))
    seq_events = [e for e in events() if e["event"].startswith("seq_")]
    assert [e["event"] for e in seq_events] == ["seq_gap", "seq_duplicate", "seq_backwards"]
    assert seq_events[0]["missing"] == 2
    assert len(writes) == 5  # sequence anomalies are reported, values still forwarded


def test_kuksa_failure_is_logged_and_adapter_keeps_running():
    def failing_write(values):
        raise ConnectionError("databroker down")

    adapter, _, events = make_adapter(failing_write)
    adapter.handle(TOPIC, msg(1))
    assert events()[-1]["event"] == "kuksa_write_failed"
    assert adapter.written == 0
    assert adapter.chip.alive()            # the board is fine, only KUKSA is not


# --- chip liveness ---------------------------------------------------------------------------------------------

def test_chip_is_alive_only_while_telemetry_keeps_arriving():
    adapter, _, _ = make_adapter()
    assert not adapter.chip.alive()                    # nothing received yet
    adapter.handle(TOPIC, msg(1))
    assert adapter.chip.alive()
    adapter.clock.t += 1.4
    assert adapter.chip.alive()
    adapter.clock.t += 0.2                             # 1.6 s of silence > 1.5 s
    assert not adapter.chip.alive()
    adapter.handle(TOPIC, msg(2))
    assert adapter.chip.alive()


def test_offline_status_kills_the_chip_at_once_and_newer_telemetry_revives_it():
    adapter, _, events = make_adapter()
    adapter.handle(TOPIC, msg(1))
    adapter.handle(STATUS, b"offline")
    assert not adapter.chip.alive()                    # no need to wait for the timeout
    adapter.handle(STATUS, b"online")
    assert not adapter.chip.alive()                    # "online" alone is not telemetry
    adapter.handle(TOPIC, msg(2))
    assert adapter.chip.alive()
    assert [e["status"] for e in events() if e["event"] == "chip_status"] == ["offline", "online"]


def test_retained_offline_delivered_before_the_first_telemetry_does_not_block_the_chip():
    adapter, _, _ = make_adapter()
    adapter.handle(STATUS, b"offline")                 # retained Last Will from the previous session
    adapter.handle(TOPIC, msg(1))
    assert adapter.chip.alive()


def test_invalid_status_is_rejected():
    adapter, _, events = make_adapter()
    adapter.handle(STATUS, b"maybe")
    assert adapter.rejected == 1 and events()[-1]["reason"].startswith("invalid_status")


def test_chip_liveness_class_directly():
    clock = Clock()
    chip = ChipLiveness(2.0, clock)
    chip.on_telemetry()
    clock.t += 1.9
    assert chip.alive()
    clock.t += 0.2
    assert not chip.alive()


# --- heartbeats ------------------------------------------------------------------------------------------------

def test_adapter_beats_always_and_the_chip_counts_while_alive_and_reports_0_otherwise():
    adapter, writes, events = make_adapter()
    adapter.beat()                                     # board never seen: the chip reports 0 (down) at once
    assert writes[-1] == {contracts.VSS_HEARTBEAT_ADAPTER: 1.0, contracts.VSS_HEARTBEAT_CHIP: 0.0}
    adapter.handle(TOPIC, msg(1))
    writes.clear()
    adapter.beat()
    adapter.beat()
    assert writes == [{contracts.VSS_HEARTBEAT_ADAPTER: 2.0, contracts.VSS_HEARTBEAT_CHIP: 1.0},
                      {contracts.VSS_HEARTBEAT_ADAPTER: 3.0, contracts.VSS_HEARTBEAT_CHIP: 2.0}]
    adapter.clock.t += 5                               # board went quiet
    adapter.beat()
    assert writes[-1] == {contracts.VSS_HEARTBEAT_ADAPTER: 4.0, contracts.VSS_HEARTBEAT_CHIP: 0.0}
    assert [e["event"] for e in events() if e["event"].startswith("chip_")] == ["chip_lost", "chip_alive", "chip_lost"]


def test_failed_heartbeat_write_is_logged_once_per_outage():
    state = {"down": True}

    def write(values):
        if state["down"]:
            raise ConnectionError("databroker down")

    adapter, _, events = make_adapter(write)
    assert adapter.beat() is False and adapter.beat() is False
    assert [e["event"] for e in events()].count("kuksa_heartbeat_failed") == 1
    state["down"] = False
    assert adapter.beat() is True
    state["down"] = True
    adapter.beat()
    assert [e["event"] for e in events()].count("kuksa_heartbeat_failed") == 2
