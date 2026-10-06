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

from common import config, contracts  # noqa: E402
from common.jsonlog import JsonLogger  # noqa: E402
from vss_uprotocol import topics  # noqa: E402
from vss_uprotocol.publisher import Publisher  # noqa: E402
from vss_uprotocol.subscriber import UpSignalSource  # noqa: E402
from vss_uprotocol.zenoh_transport import (  # noqa: E402
    ZenohTransport, attachment_to_attributes, attributes_to_attachment, to_zenoh_key)

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
    assert (cfg.authority, cfg.zenoh_mode, cfg.zenoh_connect) == ("rom-vehicle", "peer", ())
    assert cfg.vss_source_path == contracts.VSS_BATTERY_TEMP
    monkeypatch.setenv("ZENOH_CONNECT", "tcp/zenoh:7447, tcp/10.0.0.2:7447")
    monkeypatch.setenv("VSS_SOURCE_PATH", "Vehicle.Powertrain.TractionBattery.Temperature.Average")
    cfg = config.uprotocol()
    assert cfg.zenoh_connect == ("tcp/zenoh:7447", "tcp/10.0.0.2:7447")
    assert cfg.vss_source_path.endswith("Average")


def make_publisher(send, authority="v"):
    buf = io.StringIO()
    pub = Publisher(send, JsonLogger("vss_publisher", stream=buf), topics.battery_temp_topic(authority),
                    contracts.VSS_BATTERY_TEMP, ttl_ms=2000)
    return pub, lambda: [json.loads(line) for line in buf.getvalue().splitlines()]


def test_publisher_builds_publish_messages_with_json_payload_and_seq():
    sent = []
    pub, events = make_publisher(lambda m: sent.append(m) or UStatus(code=UCode.OK))
    pub.on_value(50.0, 111)
    pub.on_value(51.0, 222)
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
    pub.on_value(50.0, 0)
    assert events()[-1]["event"] == "publish_failed" and pub.failed == 1 and pub.published == 0


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
            pub.on_value(42.5, 1)
            got.wait(0.2)
        assert samples and samples[0].value == 42.5
    finally:
        sub_t.close_sync()
        pub_t.close_sync()
