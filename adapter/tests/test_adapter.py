# Made with Claude (Claude Code, Anthropic)
import io
import json

from common import contracts
from common.jsonlog import JsonLogger
from adapter.mqtt_kuksa_adapter import Adapter

TOPIC = contracts.TOPIC_SENSOR_TEMP


def make_adapter(write=None):
    buf = io.StringIO()
    writes = []
    adapter = Adapter(write or (lambda path, value: writes.append((path, value))),
                      JsonLogger("adapter", stream=buf))

    def events():
        return [json.loads(line) for line in buf.getvalue().splitlines()]

    return adapter, writes, events


def msg(seq, temp_c=31.5):
    return contracts.build_sensor_msg("sensor-01", seq, 0, temp_c).encode()


def test_valid_message_is_written_to_vss():
    adapter, writes, events = make_adapter()
    adapter.handle(TOPIC, msg(1, 50.0))
    assert writes == [(contracts.VSS_BATTERY_TEMP, 50.0)]
    assert events()[-1]["event"] == "forwarded"


def test_invalid_message_is_rejected_and_not_written():
    adapter, writes, events = make_adapter()
    adapter.handle(TOPIC, b"not json")
    adapter.handle(TOPIC, b'{"temp_c":"hot"}')
    assert writes == []
    assert [e["event"] for e in events()] == ["rejected", "rejected"]
    assert adapter.rejected == 2


def test_seq_gap_duplicate_and_backwards_are_logged():
    adapter, writes, events = make_adapter()
    for seq in (1, 2, 5, 5, 1):
        adapter.handle(TOPIC, msg(seq))
    seq_events = [e for e in events() if e["event"].startswith("seq_")]
    assert [e["event"] for e in seq_events] == ["seq_gap", "seq_duplicate", "seq_backwards"]
    assert seq_events[0]["missing"] == 2
    assert len(writes) == 5  # sequence anomalies are reported, values still forwarded


def test_kuksa_failure_is_logged_and_adapter_keeps_running():
    def failing_write(path, value):
        raise ConnectionError("databroker down")

    adapter, _, events = make_adapter(failing_write)
    adapter.handle(TOPIC, msg(1))
    assert events()[-1]["event"] == "kuksa_write_failed"
    assert adapter.written == 0
