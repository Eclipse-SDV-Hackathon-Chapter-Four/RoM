# Made with Claude (Claude Code, Anthropic)
import io
import json
import socket
import threading
import time

import pytest

zenoh = pytest.importorskip("zenoh")
pytest.importorskip("uprotocol")

from uprotocol.communication.upayload import UPayload  # noqa: E402
from uprotocol.transport.builder.umessagebuilder import UMessageBuilder  # noqa: E402
from uprotocol.uri.serializer.uriserializer import UriSerializer  # noqa: E402
from uprotocol.v1.uattributes_pb2 import UMessageType, UPayloadFormat  # noqa: E402
from uprotocol.v1.ucode_pb2 import UCode  # noqa: E402
from uprotocol.v1.ustatus_pb2 import UStatus  # noqa: E402

from rom_common.jsonlog import JsonLogger  # noqa: E402
from rom_uprotocol import config, uris as topics  # noqa: E402
from rom_uprotocol import contract as contracts  # noqa: E402
from rom_uprotocol.publisher import SignalPublisher  # noqa: E402
from rom_uprotocol.subscriber import UpSignalSource  # noqa: E402
from rom_uprotocol.transport import available_transports, make_transport, register_transport  # noqa: E402
from rom_uprotocol.transport.zenoh import (  # noqa: E402
    ZenohTransport, attachment_to_attributes, attributes_to_attachment, to_zenoh_key)

VSS_PATH = "Vehicle.Powertrain.TractionBattery.Temperature.Max"

uri = UriSerializer.deserialize


# Examples copied from up-spec up-l1/zenoh.adoc (local authority "device1").
@pytest.mark.parametrize("source, sink, key", [
    ("/10AB/3/80CD", None, "up/device1/10AB/0/3/80CD/{}/{}/{}/{}/{}"),
    ("//device1/10AB/3/80CD", "//device2/300EF/4/0", "up/device1/10AB/0/3/80CD/device2/EF/3/4/0"),
    ("/403AB/3/0", "//device2/CD/4/B", "up/device1/3AB/4/3/0/device2/CD/0/4/B"),
    ("//device2/10AB/3/80CD", None, "up/device2/10AB/0/3/80CD/{}/{}/{}/{}/{}"),
    ("//*/FFFFFFFF/FF/FFFF", "/300EF/4/0", "up/*/*/*/*/*/device1/EF/3/4/0"),
    ("//*/FFFF05A1/2/FFFF", "//device1/300EF/4/B18", "up/*/5A1/*/2/*/device1/EF/3/4/B18"),
])
def test_zenoh_key_matches_up_spec_examples(source, sink, key):
    assert to_zenoh_key(uri(source), uri(sink) if sink else None, "device1") == key


def test_attachment_is_version_byte_plus_uattributes():
    attrs = UMessageBuilder.publish(topics.battery_temp_topic("v")).build().attributes
    raw = attributes_to_attachment(attrs)
    assert raw[0] == 1 and raw[1:] == attrs.SerializeToString()
    assert attachment_to_attributes(raw) == attrs
    with pytest.raises(ValueError):
        attachment_to_attributes(b"\x02" + raw[1:])


def test_signal_payload_roundtrip_and_rejects():
    msg = contracts.parse_signal_msg(contracts.build_signal_msg("Vehicle.X", 51.5, 7, 1000, 990))
    assert (msg.value, msg.seq, msg.ts_ms, msg.source_ts_ms) == (51.5, 7, 1000, 990)
    for bad in (b"nope", b"[]", b'{"value":"hot","seq":1,"ts_ms":0,"source_ts_ms":0}', b'{"value":1}'):
        with pytest.raises(contracts.ContractError):
            contracts.parse_signal_msg(bad)


def test_uprotocol_config_defaults_and_env(monkeypatch):
    cfg = config.uprotocol()
    assert (cfg.authority, cfg.transport, cfg.zenoh_mode, cfg.zenoh_connect) == ("rom-vehicle", "zenoh", "peer", ())
    monkeypatch.setenv("ZENOH_CONNECT", "tcp/zenoh:7447, tcp/10.0.0.2:7447")
    monkeypatch.setenv("UP_TRANSPORT", "fake")
    cfg = config.uprotocol()
    assert cfg.zenoh_connect == ("tcp/zenoh:7447", "tcp/10.0.0.2:7447") and cfg.transport == "fake"


def test_make_transport_uses_registered_factory_and_rejects_unknown(monkeypatch):
    made = []
    register_transport("fake", lambda source: made.append(source) or "fake-transport")
    assert "zenoh" in available_transports() and "fake" in available_transports()
    monkeypatch.setenv("UP_TRANSPORT", "fake")
    assert make_transport(topics.guardian_uri("v")) == "fake-transport"
    assert made == [topics.guardian_uri("v")]
    with pytest.raises(ValueError):
        make_transport(topics.guardian_uri("v"), name="nope")


def make_publisher(send, authority="v", interceptors=()):
    buf = io.StringIO()
    pub = SignalPublisher(send, topics.battery_temp_topic(authority), ttl_ms=2000,
                          log=JsonLogger("vss_publisher", stream=buf), interceptors=interceptors)
    return pub, lambda: [json.loads(line) for line in buf.getvalue().splitlines()]


def test_publisher_builds_publish_messages_with_json_payload_and_seq():
    sent = []
    pub, events = make_publisher(lambda m: sent.append(m) or UStatus(code=UCode.OK))
    pub.publish(VSS_PATH, 50.0, 111)
    pub.publish(VSS_PATH, 51.0, 222)
    assert len(sent) == 2
    attrs = sent[1].attributes
    assert attrs.type == UMessageType.UMESSAGE_TYPE_PUBLISH
    assert attrs.source == topics.battery_temp_topic("v")
    assert attrs.payload_format == UPayloadFormat.UPAYLOAD_FORMAT_JSON and attrs.ttl == 2000
    msg = contracts.parse_signal_msg(sent[1].payload)
    assert (msg.value, msg.seq, msg.source_ts_ms) == (51.0, 2, 222)
    assert [e["event"] for e in events()] == ["published", "published"]


def test_publisher_logs_failed_send_and_keeps_going():
    pub, events = make_publisher(lambda m: UStatus(code=UCode.INTERNAL, message="zenoh down"))
    pub.publish(VSS_PATH, 50.0, 0)
    assert events()[-1]["event"] == "publish_failed" and pub.failed == 1 and pub.published == 0


def test_interceptors_run_in_order_and_can_drop_or_duplicate():
    sent, order = [], []
    ok = UStatus(code=UCode.OK)

    def tag(name):
        def interceptor(message, forward):
            order.append(name)
            return forward(message)
        return interceptor

    def duplicate(message, forward):
        forward(message)
        return forward(message)

    pub, _ = make_publisher(lambda m: sent.append(m) or ok, interceptors=[tag("a"), duplicate, tag("b")])
    pub.publish(VSS_PATH, 50.0, 0)
    assert order == ["a", "b", "b"] and len(sent) == 2

    sent.clear()
    pub, events = make_publisher(lambda m: sent.append(m) or ok, interceptors=[lambda message, forward: ok])
    pub.publish(VSS_PATH, 50.0, 0)
    assert sent == [] and events()[-1]["event"] == "published"  # dropped silently, like a lost frame


def test_signal_source_parses_valid_and_rejects_invalid():
    samples, rejects = [], []
    src = UpSignalSource(transport=None, on_sample=samples.append, on_reject=rejects.append)
    good = UMessageBuilder.publish(topics.battery_temp_topic("v")).build_from_upayload(
        UPayload.pack_from_data_and_format(contracts.build_signal_msg("p", 47.2, 3, 10, 5),
                                           UPayloadFormat.UPAYLOAD_FORMAT_JSON))
    src.handle(good)
    src.handle(UMessageBuilder.publish(topics.battery_temp_topic("v")).build_from_upayload(
        UPayload.pack_from_data_and_format(b"garbage", UPayloadFormat.UPAYLOAD_FORMAT_JSON)))
    src.handle(UMessageBuilder.publish(topics.battery_temp_topic("v")).build_from_upayload(
        UPayload.pack_from_data_and_format(b"{}", UPayloadFormat.UPAYLOAD_FORMAT_TEXT)))
    assert [(s.value, s.seq) for s in samples] == [(47.2, 3)]
    assert samples[0].msg_id and len(rejects) == 2


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _conf(**endpoints):
    conf = zenoh.Config()
    conf.insert_json5("mode", '"peer"')
    conf.insert_json5("scouting/multicast/enabled", "false")
    for kind, eps in endpoints.items():
        conf.insert_json5(f"{kind}/endpoints", json.dumps(eps))
    return conf


def test_publish_reaches_subscriber_over_real_zenoh():
    """End to end in one process: Publisher -> ZenohTransport -> Zenoh -> ZenohTransport -> UpSignalSource."""
    ep = f"tcp/127.0.0.1:{_free_port()}"
    pub_t = ZenohTransport(topics.publisher_uri("test"), _conf(listen=[ep]))
    sub_t = ZenohTransport(topics.guardian_uri("test"), _conf(connect=[ep]))
    try:
        got = threading.Event()
        samples = []
        UpSignalSource(sub_t, lambda s: (samples.append(s), got.set()),
                       topic=topics.battery_temp_topic("test")).start()
        pub, _ = make_publisher(pub_t.send_sync, authority="test")
        deadline = time.monotonic() + 10
        while not got.is_set() and time.monotonic() < deadline:  # wait for the sessions to connect
            pub.publish(VSS_PATH, 42.5, 1)
            got.wait(0.2)
        assert samples and samples[0].value == 42.5
    finally:
        sub_t.close_sync()
        pub_t.close_sync()


# --- 4 cells and guardian fault events --------------------------------------------------------------------------
from rom_uprotocol.subscriber import UpCampaignSource, UpCellsSource, UpFaultSource, UpStateSource  # noqa: E402


def _json_msg(topic, payload, fmt=UPayloadFormat.UPAYLOAD_FORMAT_JSON):
    return UMessageBuilder.publish(topic).build_from_upayload(UPayload.pack_from_data_and_format(payload, fmt))


def test_cells_payload_roundtrip_keeps_missing_cells_missing():
    raw = contracts.build_cells_msg({4: 29.9, 1: 31.2, 2: 30.1}, 7, 1000, 990, "camp-1")
    assert json.loads(raw)["cells"] == {"1": 31.2, "2": 30.1, "4": 29.9}
    msg = contracts.parse_cells_msg(raw)
    assert (msg.cells, msg.seq, msg.ts_ms, msg.source_ts_ms, msg.run_id) == (
        {1: 31.2, 2: 30.1, 4: 29.9}, 7, 1000, 990, "camp-1")
    assert contracts.parse_cells_msg(contracts.build_cells_msg({1: 30.0}, 1, 0, 0)).run_id is None


@pytest.mark.parametrize("bad", [
    b'{"cells":{},"seq":1,"ts_ms":0,"source_ts_ms":0}',
    b'{"cells":{"5":30},"seq":1,"ts_ms":0,"source_ts_ms":0}',
    b'{"cells":{"x":30},"seq":1,"ts_ms":0,"source_ts_ms":0}',
    b'{"cells":{"1":"hot"},"seq":1,"ts_ms":0,"source_ts_ms":0}',
    b'{"cells":{"1":30},"seq":"a","ts_ms":0,"source_ts_ms":0}',
    b'{"cells":{"1":30},"seq":1,"ts_ms":0,"source_ts_ms":0,"run_id":5}',
])
def test_cells_payload_rejects(bad):
    with pytest.raises(contracts.ContractError):
        contracts.parse_cells_msg(bad)


def test_fault_event_roundtrip_and_environment_data():
    event = contracts.FaultEvent(code="battery_guardian.cell2.signal_stuck", stage="FAILED", ts_ms=5, cell=2,
                                 temp_c=31.2, cells="31.2,30.1,,29.9", reason="stuck signal", seq=42,
                                 msg_id="01a1", run_id=None)
    assert contracts.parse_fault_event(contracts.build_fault_event(event)) == event
    assert event.environment_data() == {"cell": "2", "temp_c": "31.2", "cells": "31.2,30.1,,29.9",
                                        "reason": "stuck signal", "seq": "42", "msg_id": "01a1", "ts_ms": "5"}


@pytest.mark.parametrize("change", [{"code": "battery_guardian.nope"}, {"stage": "MAYBE"}, {"ts_ms": None},
                                    {"cell": 1.5}, {"temp_c": "hot"}])
def test_fault_event_rejects(change):
    data = {"code": "battery_guardian.signal_stale", "stage": "PASSED", "ts_ms": 1, **change}
    with pytest.raises(contracts.ContractError):
        contracts.parse_fault_event(json.dumps(data))
    if "code" in change or "stage" in change:
        with pytest.raises(contracts.ContractError):
            contracts.build_fault_event(contracts.FaultEvent(**{"code": data["code"], "stage": data["stage"], "ts_ms": 1}))


def test_cell_and_fault_topics():
    assert UriSerializer.serialize(topics.battery_cells_topic("v")) == "//v/1001/1/8002"
    assert UriSerializer.serialize(topics.guardian_fault_topic("v")) == "//v/1002/1/8003"
    assert to_zenoh_key(topics.guardian_fault_topic("v"), None, "v") == "up/v/1002/0/1/8003/{}/{}/{}/{}/{}"


def test_publish_cells_goes_through_the_interceptors():
    sent, seen = [], []
    ok = UStatus(code=UCode.OK)

    def spy(message, forward):
        seen.append(message)
        return forward(message)

    pub = SignalPublisher(lambda m: sent.append(m) or ok, topics.battery_cells_topic("v"), 2000, interceptors=[spy])
    pub.publish_cells({1: 30.0, 3: 29.0}, 11, "r1")
    assert len(seen) == len(sent) == 1
    assert contracts.parse_cells_msg(sent[0].payload).cells == {1: 30.0, 3: 29.0}


def test_cells_and_fault_sources_parse_and_reject():
    cells, faults, rejects = [], [], []
    UpCellsSource(None, cells.append, rejects.append).handle(
        _json_msg(topics.battery_cells_topic("v"), contracts.build_cells_msg({2: 30.5}, 3, 10, 5, "r1")))
    UpCellsSource(None, cells.append, rejects.append).handle(_json_msg(topics.battery_cells_topic("v"), b"{}"))
    event = contracts.FaultEvent(code="battery_guardian.signal_stale", stage="FAILED", ts_ms=1)
    UpFaultSource(None, faults.append, rejects.append).handle(
        _json_msg(topics.guardian_fault_topic("v"), contracts.build_fault_event(event)))
    assert [(s.cells, s.seq, s.run_id) for s in cells] == [({2: 30.5}, 3, "r1")] and cells[0].msg_id
    assert faults == [event] and len(rejects) == 1


def test_campaign_event_roundtrip_and_rejects():
    event = contracts.CampaignEvent("campaign_start", "thermal-runaway-01", 5, 1,
                                    {"expected_state": "CRITICAL", "max_detect_ms": 35000})
    assert contracts.parse_campaign_event(contracts.build_campaign_event(event)) == event
    for bad in ({"event": "nope"}, {"run_id": ""}, {"run_id": None}, {"ts_ms": "x"}, {"data": [1]}):
        with pytest.raises(contracts.ContractError):
            contracts.parse_campaign_event(json.dumps({"event": "campaign_end", "run_id": "r", "ts_ms": 1, **bad}))
    with pytest.raises(contracts.ContractError):
        contracts.build_campaign_event(contracts.CampaignEvent("nope", "r", 1))


def test_state_event_roundtrip_knows_mitigating_and_rejects():
    event = contracts.StateEvent(state="MITIGATING", previous="CRITICAL", reason="cooling requested", ts_ms=9,
                                 temp_c=46.1, cell=1, cells="46.1,30,30,30", seq=3, msg_id="01a1", run_id="r1")
    assert contracts.parse_state_event(contracts.build_state_event(event)) == event
    for bad in ({"state": "HOT"}, {"previous": None}, {"ts_ms": None}, {"cell": 1.5}, {"temp_c": "hot"}):
        with pytest.raises(contracts.ContractError):
            contracts.parse_state_event(json.dumps({"state": "MONITORING", "previous": "CLEAR", "ts_ms": 1, **bad}))
    with pytest.raises(contracts.ContractError):
        contracts.build_state_event(contracts.StateEvent(state="HOT", previous="CLEAR", reason="", ts_ms=1))


def test_campaign_and_state_topics_and_sources():
    assert UriSerializer.serialize(topics.campaign_event_topic("v")) == "//v/1003/1/8005"
    assert UriSerializer.serialize(topics.guardian_state_topic("v")) == "//v/1002/1/8006"
    got, rejects = [], []
    campaign = contracts.CampaignEvent("campaign_end", "r1", 2, 4, {"status": "completed"})
    state = contracts.StateEvent(state="WARNING", previous="MONITORING", reason="getting hot", ts_ms=3)
    UpCampaignSource(None, got.append, rejects.append).handle(
        _json_msg(topics.campaign_event_topic("v"), contracts.build_campaign_event(campaign)))
    UpStateSource(None, got.append, rejects.append).handle(
        _json_msg(topics.guardian_state_topic("v"), contracts.build_state_event(state)))
    UpStateSource(None, got.append, rejects.append).handle(_json_msg(topics.guardian_state_topic("v"), b"{}"))
    assert got == [campaign, state] and len(rejects) == 1
