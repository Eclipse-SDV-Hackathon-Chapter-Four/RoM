# Made with Claude (Claude Code, Anthropic) — shared RoM "common" module, used by all components.
import io
import json

import pytest

from rom_common import config, contracts
from rom_common.jsonlog import JsonLogger


def test_sensor_roundtrip():
    msg = contracts.parse_sensor_msg(contracts.build_sensor_msg("sensor-01", 42, 1730000000000, 31.5))
    assert (msg.device_id, msg.seq, msg.ts_ms, msg.temp_c) == ("sensor-01", 42, 1730000000000, 31.5)


@pytest.mark.parametrize("bad", [b"not json", b"[]", b'{"temp_c":"hot"}', b'{"seq":1}', b'{"temp_c":true}'])
def test_sensor_rejects_bad_payloads(bad):
    with pytest.raises(contracts.ContractError):
        contracts.parse_sensor_msg(bad)


def test_display_cmd_roundtrip_and_unknown_state():
    raw = contracts.build_display_cmd(contracts.WARNING, 47.2, contracts.REASON_TEMP_ABOVE_WARN, 7, 1)
    assert contracts.parse_display_cmd(raw)["state"] == "WARNING"
    with pytest.raises(contracts.ContractError):
        contracts.build_display_cmd("BOGUS", None, "x", 1, 1)


def test_threshold_defaults_and_env_override(monkeypatch):
    t = config.thresholds()
    assert (t.warn_c, t.crit_c, t.hyst_c, t.stale_ms) == (38.0, 45.0, 2.0, 2000)
    monkeypatch.setenv("WARN_C", "40")
    assert config.thresholds().warn_c == 40.0


def test_endpoint_defaults():
    ep = config.endpoints()
    assert (ep.mqtt_port, ep.kuksa_port) == (1883, 55555)


def test_jsonlog_line_has_required_fields():
    buf = io.StringIO()
    JsonLogger("guardian", run_id="r1", stream=buf).log("state_change", to="WARNING")
    rec = json.loads(buf.getvalue())
    assert rec["component"] == "guardian" and rec["event"] == "state_change"
    assert rec["run_id"] == "r1" and isinstance(rec["ts_ms"], int)


def test_mqtt_client_subscribe_dispatch_and_publish():
    pytest.importorskip("paho.mqtt.client")
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from rom_common.mqtt import MqttClient

    c = MqttClient("t")
    c._client = MagicMock()
    c._client.is_connected.return_value = True
    got = []
    c.subscribe("rom/sensor/#", lambda t, p: got.append((t, p)), qos=1)
    c._client.subscribe.assert_called_with("rom/sensor/#", 1)
    c._dispatch(None, None, SimpleNamespace(topic="rom/sensor/battery/temp", payload=b"x"))
    c._dispatch(None, None, SimpleNamespace(topic="rom/actuator/display/cmd", payload=b"y"))
    assert got == [("rom/sensor/battery/temp", b"x")]
    c.publish("a/b", "hi", qos=1, retain=True)
    c._client.publish.assert_called_with("a/b", "hi", qos=1, retain=True)


def test_fault_codes_pack_and_per_cell():
    assert contracts.cell_fault(2, "signal_stuck") == "battery_guardian.cell2.signal_stuck"
    assert len(contracts.FAULT_CODES) == len(set(contracts.FAULT_CODES)) == 5 + 4 * 3 + 5   # pack + per cell + heartbeat root causes
    assert set(contracts.HEARTBEAT_FAULTS) == set(contracts.HEARTBEAT_DIAGNOSIS_ORDER)
    assert all(c.startswith(contracts.DFM_ENTITY + ".") for c in contracts.FAULT_CODES)
    for cell, kind in ((0, "signal_stuck"), (5, "signal_stuck"), (1, "bogus")):
        with pytest.raises(ValueError):
            contracts.cell_fault(cell, kind)


def test_imbalance_thresholds_default_and_env(monkeypatch):
    t = config.thresholds()
    assert (t.imbalance_c, t.imbalance_s) == (10.0, 2.0)
    monkeypatch.setenv("IMBALANCE_C", "6")
    assert config.thresholds().imbalance_c == 6.0
