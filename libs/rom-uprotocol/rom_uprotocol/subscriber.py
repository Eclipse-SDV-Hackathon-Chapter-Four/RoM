# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""Guardian input over uProtocol: subscribe to the battery temperature topic.

The guardian uses UpSignalSource instead of reading the KUKSA Databroker:

    transport = make_transport(uris.guardian_uri())
    source = UpSignalSource(transport, on_sample=lambda s: ..., on_reject=lambda reason: ...)
    source.start()

Run standalone to watch the topic (stand-in for the guardian):  python -m rom_uprotocol.subscriber
"""
import signal
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from uprotocol.transport.ulistener import UListener
from uprotocol.uri.serializer.uriserializer import UriSerializer
from uprotocol.uuid.serializer.uuidserializer import UuidSerializer
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri
from uprotocol.v1.ustatus_pb2 import UStatus

from rom_common import clock, jsonlog

from . import contract, uris
from .transport import make_transport


@dataclass(frozen=True)
class Sample:
    value: float
    seq: int
    ts_ms: int          # publisher send time (epoch ms)
    source_ts_ms: int   # when the value left KUKSA
    rx_ts_ms: int       # when this process received it
    vss_path: str
    msg_id: str         # uProtocol message UUID — correlation ID for the evidence chain


class _Listener(UListener):
    def __init__(self, source: "UpSignalSource"):
        self._source = source

    async def on_receive(self, umsg: UMessage) -> None:
        self._source.handle(umsg)


class UpSignalSource:
    """Calls on_sample(Sample) for every valid message and on_reject(reason) for invalid ones.

    Callbacks run on the transport's thread — keep them short (e.g. store the latest value).
    """

    def __init__(self, transport, on_sample: Callable[[Sample], None],
                 on_reject: Optional[Callable[[str], None]] = None, topic: Optional[UUri] = None):
        self._transport = transport
        self._on_sample = on_sample
        self._on_reject = on_reject or (lambda reason: None)
        self._topic = topic or uris.battery_temp_topic()
        self._listener = _Listener(self)

    def start(self) -> UStatus:
        return self._transport.register_listener_sync(self._topic, self._listener)

    def handle(self, umsg: UMessage) -> None:
        rx = clock.now_ms()
        if umsg.attributes.payload_format != UPayloadFormat.UPAYLOAD_FORMAT_JSON:
            self._on_reject(f"unexpected_payload_format: {umsg.attributes.payload_format}")
            return
        try:
            msg = contract.parse_signal_msg(umsg.payload)
        except contract.ContractError as e:
            self._on_reject(str(e))
            return
        self._on_sample(Sample(value=msg.value, seq=msg.seq, ts_ms=msg.ts_ms, source_ts_ms=msg.source_ts_ms,
                               rx_ts_ms=rx, vss_path=msg.vss_path,
                               msg_id=UuidSerializer.serialize(umsg.attributes.id)))


def main():
    log = jsonlog.get_logger("up_subscriber")
    last_seq = {"seq": None}

    def on_sample(s: Sample):
        prev, last_seq["seq"] = last_seq["seq"], s.seq
        if prev is not None and s.seq != prev + 1:
            log.log("seq_gap" if s.seq > prev + 1 else "seq_backwards", expected=prev + 1, got=s.seq)
        log.log("received", seq=s.seq, value=s.value, vss_path=s.vss_path, msg_id=s.msg_id,
                latency_ms=s.rx_ts_ms - s.ts_ms, end_to_end_ms=s.rx_ts_ms - s.source_ts_ms)

    transport = make_transport(uris.guardian_uri())
    source = UpSignalSource(transport, on_sample, lambda reason: log.log("rejected", reason=reason))
    status = source.start()
    topic = uris.battery_temp_topic()
    log.log("subscribed", topic="up:" + UriSerializer.serialize(topic), zenoh_key=status.message,
            ok=status.code == UCode.OK)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    transport.close_sync()
    log.log("stopped")


if __name__ == "__main__":
    main()
