# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""Subscribers for the RoM topics. The guardian reads uProtocol, never the KUKSA Databroker:

    transport = make_transport(uris.guardian_uri())
    source = UpCellsSource(transport, on_sample=lambda s: ..., on_reject=lambda reason: ...)
    source.start()

    UpSignalSource   battery temperature Max   up://…/1001/1/8001   -> Sample
    UpCellsSource    cell temperatures         up://…/1001/1/8002   -> CellsSample   (guardian input)
    UpFaultSource    guardian fault events     up://…/1002/1/8003   -> FaultEvent    (DFM reporter input)

Watch a topic from a terminal:  rom-up-monitor [--cells | --faults]
"""
import argparse
import signal
import threading
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Optional

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


@dataclass(frozen=True)
class CellsSample:
    cells: Dict[int, float]   # only the cells written in this source update, cell number -> °C
    seq: int
    ts_ms: int
    source_ts_ms: int
    rx_ts_ms: int
    run_id: Optional[str]     # campaign run the publisher was told about, or None
    msg_id: str


class _Listener(UListener):
    def __init__(self, source: "_JsonSource"):
        self._source = source

    async def on_receive(self, umsg: UMessage) -> None:
        self._source.handle(umsg)


class _JsonSource:
    """Subscribe to one JSON topic: parse each message, call on_sample(item) or on_reject(reason).

    Callbacks run on the transport's thread — keep them short (e.g. put the item on a queue).
    """
    default_topic: Callable[[], UUri]

    def __init__(self, transport, on_sample: Callable, on_reject: Optional[Callable[[str], None]] = None,
                 topic: Optional[UUri] = None):
        self._transport = transport
        self._on_sample = on_sample
        self._on_reject = on_reject or (lambda reason: None)
        self.topic = topic or type(self).default_topic()
        self._listener = _Listener(self)

    def start(self) -> UStatus:
        return self._transport.register_listener_sync(self.topic, self._listener)

    def handle(self, umsg: UMessage) -> None:
        rx = clock.now_ms()
        if umsg.attributes.payload_format != UPayloadFormat.UPAYLOAD_FORMAT_JSON:
            self._on_reject(f"unexpected_payload_format: {umsg.attributes.payload_format}")
            return
        try:
            item = self._convert(umsg.payload, rx, UuidSerializer.serialize(umsg.attributes.id))
        except contract.ContractError as e:
            self._on_reject(str(e))
            return
        self._on_sample(item)

    def _convert(self, payload: bytes, rx_ts_ms: int, msg_id: str):
        raise NotImplementedError


class UpSignalSource(_JsonSource):
    """Battery temperature Max (up://…/1001/1/8001) -> on_sample(Sample)."""
    default_topic = staticmethod(uris.battery_temp_topic)

    def _convert(self, payload, rx_ts_ms, msg_id) -> Sample:
        msg = contract.parse_signal_msg(payload)
        return Sample(value=msg.value, seq=msg.seq, ts_ms=msg.ts_ms, source_ts_ms=msg.source_ts_ms,
                      rx_ts_ms=rx_ts_ms, vss_path=msg.vss_path, msg_id=msg_id)


class UpCellsSource(_JsonSource):
    """Battery cell temperatures (up://…/1001/1/8002) -> on_sample(CellsSample). The guardian's input."""
    default_topic = staticmethod(uris.battery_cells_topic)

    def _convert(self, payload, rx_ts_ms, msg_id) -> CellsSample:
        msg = contract.parse_cells_msg(payload)
        return CellsSample(cells=msg.cells, seq=msg.seq, ts_ms=msg.ts_ms, source_ts_ms=msg.source_ts_ms,
                           rx_ts_ms=rx_ts_ms, run_id=msg.run_id, msg_id=msg_id)


class UpFaultSource(_JsonSource):
    """Guardian fault events (up://…/1002/1/8003) -> on_sample(FaultEvent). What the DFM reporter consumes."""
    default_topic = staticmethod(uris.guardian_fault_topic)

    def _convert(self, payload, rx_ts_ms, msg_id) -> contract.FaultEvent:
        return contract.parse_fault_event(payload)


def main(argv: Optional[list] = None):
    """rom-up-monitor [--cells | --faults]: print every message of one RoM topic as a JSON line."""
    parser = argparse.ArgumentParser(description="Print RoM uProtocol messages as JSON lines.")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--cells", action="store_true", help="cell temperatures, up://…/1001/1/8002")
    which.add_argument("--faults", action="store_true", help="guardian fault events, up://…/1002/1/8003")
    args = parser.parse_args(argv)
    log = jsonlog.get_logger("up_subscriber")
    last_seq = {"seq": None}

    def check_seq(seq: int):
        prev, last_seq["seq"] = last_seq["seq"], seq
        if prev is not None and seq != prev + 1:
            log.log("seq_gap" if seq > prev + 1 else "seq_backwards", expected=prev + 1, got=seq)

    def on_sample(s: Sample):
        check_seq(s.seq)
        log.log("received", seq=s.seq, value=s.value, vss_path=s.vss_path, msg_id=s.msg_id,
                latency_ms=s.rx_ts_ms - s.ts_ms, end_to_end_ms=s.rx_ts_ms - s.source_ts_ms)

    def on_cells(s: CellsSample):
        check_seq(s.seq)
        log.log("received", seq=s.seq, cells={str(c): v for c, v in s.cells.items()}, run_id=s.run_id,
                msg_id=s.msg_id, latency_ms=s.rx_ts_ms - s.ts_ms, end_to_end_ms=s.rx_ts_ms - s.source_ts_ms)

    def on_fault(e: contract.FaultEvent):
        log.log("fault_event", **asdict(e))

    if args.faults:
        source_cls, handler = UpFaultSource, on_fault
    elif args.cells:
        source_cls, handler = UpCellsSource, on_cells
    else:
        source_cls, handler = UpSignalSource, on_sample
    transport = make_transport(uris.monitor_uri())
    source = source_cls(transport, handler, lambda reason: log.log("rejected", reason=reason))
    status = source.start()
    log.log("subscribed", topic="up:" + UriSerializer.serialize(source.topic), zenoh_key=status.message,
            ok=status.code == UCode.OK)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    transport.close_sync()
    log.log("stopped")


if __name__ == "__main__":
    main()
