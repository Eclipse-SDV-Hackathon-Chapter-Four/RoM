# Made with Claude (Claude Code, Anthropic)
import io
import json

import pytest

pytest.importorskip("uprotocol")

from uprotocol.communication.upayload import UPayload  # noqa: E402
from uprotocol.transport.builder.umessagebuilder import UMessageBuilder  # noqa: E402
from uprotocol.v1.uattributes_pb2 import UPayloadFormat  # noqa: E402
from uprotocol.v1.ucode_pb2 import UCode  # noqa: E402
from uprotocol.v1.ustatus_pb2 import UStatus  # noqa: E402

from rom_common.contracts import HB_DOWN, HB_OK  # noqa: E402
from rom_common.jsonlog import JsonLogger  # noqa: E402
from rom_uprotocol import contract, uris  # noqa: E402
from rom_uprotocol.faults import FaultError, TransportFaults  # noqa: E402
from rom_uprotocol.publisher import HeartbeatPublisher  # noqa: E402
from rom_uprotocol.subscriber import UpCellsSource, UpHeartbeatSource, UpSignalSource  # noqa: E402

OK = UStatus(code=UCode.OK)


def test_heartbeat_payload_roundtrip_and_rejects():
    msg = contract.parse_heartbeat_msg(contract.build_heartbeat_msg("databroker", HB_DOWN, 4, 1000))
    assert (msg.component, msg.status, msg.seq, msg.ts_ms) == ("databroker", "down", 4, 1000)
    bad = (b"nope", b"[]", b'{"status":"ok","seq":1,"ts_ms":1}', b'{"component":"","status":"ok","seq":1,"ts_ms":1}',
           b'{"component":"x","status":"maybe","seq":1,"ts_ms":1}', b'{"component":"x","status":"ok","seq":"1","ts_ms":1}')
    for payload in bad:
        with pytest.raises(contract.ContractError):
            contract.parse_heartbeat_msg(payload)


def test_heartbeat_topic_is_next_to_the_signal_and_cell_topics():
    sig, cells, hb = uris.battery_temp_topic("v"), uris.battery_cells_topic("v"), uris.heartbeat_topic("v")
    assert (hb.ue_id, hb.ue_version_major, hb.resource_id) == (sig.ue_id, sig.ue_version_major, 0x8004)
    assert (sig.resource_id, cells.resource_id) == (0x8001, 0x8002)


def test_heartbeat_publisher_sends_on_the_heartbeat_topic_with_per_component_seq():
    sent, buf = [], io.StringIO()
    pub = HeartbeatPublisher(lambda m: sent.append(m) or OK, uris.heartbeat_topic("v"), ttl_ms=1500,
                             log=JsonLogger("c", None, buf))
    pub.publish("uprotocol")
    pub.publish("databroker", HB_DOWN)
    pub.publish("uprotocol")
    assert all(m.attributes.source == uris.heartbeat_topic("v") and m.attributes.ttl == 1500 for m in sent)
    parsed = [contract.parse_heartbeat_msg(m.payload) for m in sent]
    assert [(h.component, h.status, h.seq) for h in parsed] == [("uprotocol", "ok", 1), ("databroker", "down", 1),
                                                                ("uprotocol", "ok", 2)]
    assert pub.published == 3 and buf.getvalue() == ""


def test_heartbeat_publisher_logs_failures():
    buf = io.StringIO()
    pub = HeartbeatPublisher(lambda m: UStatus(code=UCode.INTERNAL, message="down"), uris.heartbeat_topic("v"), 1500,
                             log=JsonLogger("c", None, buf))
    pub.publish("uprotocol")
    assert pub.failed == 1 and json.loads(buf.getvalue())["event"] == "heartbeat_failed"


def test_heartbeat_source_parses_valid_and_rejects_invalid():
    beats, rejects = [], []
    src = UpHeartbeatSource(transport=None, on_sample=beats.append, on_reject=rejects.append)
    topic = uris.heartbeat_topic("v")

    def msg(payload, fmt=UPayloadFormat.UPAYLOAD_FORMAT_JSON):
        return UMessageBuilder.publish(topic).build_from_upayload(UPayload.pack_from_data_and_format(payload, fmt))

    src.handle(msg(contract.build_heartbeat_msg("uprotocol", HB_OK, 9, 77)))
    src.handle(msg(b"garbage"))
    src.handle(msg(b"{}", UPayloadFormat.UPAYLOAD_FORMAT_TEXT))
    assert [(b.component, b.status, b.seq, b.ts_ms) for b in beats] == [("uprotocol", "ok", 9, 77)]
    assert beats[0].msg_id and len(rejects) == 2


def test_each_source_listens_on_its_own_topic():
    assert UpSignalSource(None, lambda s: None).topic == uris.battery_temp_topic()
    assert UpCellsSource(None, lambda s: None).topic == uris.battery_cells_topic()
    assert UpHeartbeatSource(None, lambda s: None).topic == uris.heartbeat_topic()


# --- transport faults can target one stream -------------------------------------------------------------------

class Wire:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return OK


def hb_msg():
    return UMessageBuilder.publish(uris.heartbeat_topic("v")).build_from_upayload(
        UPayload.pack_from_data_and_format(contract.build_heartbeat_msg("uprotocol", HB_OK, 1, 1),
                                           UPayloadFormat.UPAYLOAD_FORMAT_JSON))


def sig_msg():
    return UMessageBuilder.publish(uris.battery_temp_topic("v")).build_from_upayload(
        UPayload.pack_from_data_and_format(contract.build_signal_msg("p", 1.0, 1, 1, 1),
                                           UPayloadFormat.UPAYLOAD_FORMAT_JSON))


def test_drop_with_topic_heartbeat_loses_only_heartbeats():
    f, wire = TransportFaults(), Wire()
    f.add("drop", {"topic": "heartbeat"})
    hb, sig = hb_msg(), sig_msg()
    f(hb, wire.send)
    f(sig, wire.send)
    assert wire.sent == [sig] and f.counts["dropped"] == 1


def test_drop_with_topic_signal_keeps_heartbeats_flowing():
    f, wire = TransportFaults(), Wire()
    f.add("drop", {"topic": "signal"})
    hb, sig = hb_msg(), sig_msg()
    f(sig, wire.send)
    f(hb, wire.send)
    assert wire.sent == [hb]


def test_default_topic_is_all_and_reorder_holds_one_message_per_stream():
    f, wire = TransportFaults(), Wire()
    assert f.add("drop").params["topic"] == "all"
    f.clear()
    f.add("reorder")
    s1, h1, s2, h2 = sig_msg(), hb_msg(), sig_msg(), hb_msg()
    for m in (s1, h1, s2, h2):
        f(m, wire.send)
    assert wire.sent == [s2, s1, h2, h1]     # each stream swaps its own pair, they do not mix


def test_invalid_topic_is_rejected():
    with pytest.raises(FaultError, match="topic"):
        TransportFaults().add("drop", {"topic": "everything"})
