# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""SignalPublisher: one VSS value in, one uProtocol publish message out.

Transport-free: it builds the UMessage and hands it to `send` (e.g. ZenohTransport.send_sync).
Interceptors sit between the publisher and `send`, so the message flow can be changed
(fault injection: drop, duplicate, delay, corrupt...) without modifying this class:

    def duplicate(message, forward):
        forward(message)
        return forward(message)

    SignalPublisher(transport.send_sync, topic, ttl_ms=2000, interceptors=[duplicate])

Each interceptor is called as interceptor(message, forward) -> UStatus and decides whether and
how often to call forward(message); the last forward is `send`.
"""
from typing import Callable, Mapping, Optional, Sequence

from uprotocol.communication.upayload import UPayload
from uprotocol.transport.builder.umessagebuilder import UMessageBuilder
from uprotocol.uuid.serializer.uuidserializer import UuidSerializer
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri
from uprotocol.v1.ustatus_pb2 import UStatus

from rom_common import clock
from rom_common.contracts import HB_OK

from .contract import build_cells_msg, build_heartbeat_msg, build_signal_msg

Send = Callable[[UMessage], UStatus]
Interceptor = Callable[[UMessage, Send], UStatus]


def msg_id(message: UMessage) -> str:
    """The uProtocol message id as the subscriber logs it: the correlation ID from sender to evidence."""
    return UuidSerializer.serialize(message.attributes.id)


def _chain(send: Send, interceptors: Sequence[Interceptor]) -> Send:
    forward = send
    for interceptor in reversed(interceptors):
        forward = (lambda i, nxt: lambda message: i(message, nxt))(interceptor, forward)
    return forward


class SignalPublisher:
    """Publishes JSON payloads on one topic through the interceptor chain; logs published / publish_failed.

    publish(vss_path, value, source_ts_ms)         one VSS value       (build_signal_msg)
    publish_cells(cells, source_ts_ms, run_id)     one cell update     (build_cells_msg)
    publish_json(make_payload, **log_fields)       anything else: make_payload(seq, ts_ms) -> bytes
    """

    def __init__(self, send: Send, topic: UUri, ttl_ms: int, log=None,
                 interceptors: Sequence[Interceptor] = ()):
        self._send = _chain(send, interceptors)
        self._topic = topic
        self._ttl_ms = ttl_ms
        self._log = log
        self.seq = 0
        self.published = 0
        self.failed = 0

    def build_json(self, make_payload: Callable[[int, int], bytes]) -> UMessage:
        self.seq += 1
        return (UMessageBuilder.publish(self._topic)
                .with_ttl(self._ttl_ms)
                .build_from_upayload(UPayload.pack_from_data_and_format(
                    make_payload(self.seq, clock.now_ms()), UPayloadFormat.UPAYLOAD_FORMAT_JSON)))

    def publish_json(self, make_payload: Callable[[int, int], bytes], **log_fields) -> UStatus:
        message = self.build_json(make_payload)
        status = self._send(message)
        if status.code != UCode.OK:
            self.failed += 1
            self._emit("publish_failed", seq=self.seq, msg_id=msg_id(message), resource=self._topic.resource_id,
                       code=UCode.Name(status.code), error=status.message)
        else:
            self.published += 1
            self._emit("published", seq=self.seq, msg_id=msg_id(message), resource=self._topic.resource_id,
                       **log_fields, published=self.published, failed=self.failed)
        return status

    def build(self, vss_path: str, value: float, source_ts_ms: int) -> UMessage:
        return self.build_json(lambda seq, ts: build_signal_msg(vss_path, value, seq, ts, source_ts_ms))

    def publish(self, vss_path: str, value: float, source_ts_ms: int) -> UStatus:
        return self.publish_json(lambda seq, ts: build_signal_msg(vss_path, value, seq, ts, source_ts_ms),
                                 value=value, vss_path=vss_path, source_ts_ms=source_ts_ms)

    def publish_cells(self, cells: Mapping[int, float], source_ts_ms: int, run_id: Optional[str] = None) -> UStatus:
        return self.publish_json(lambda seq, ts: build_cells_msg(cells, seq, ts, source_ts_ms, run_id),
                                 cells={str(c): v for c, v in sorted(cells.items())}, source_ts_ms=source_ts_ms)

    def _emit(self, event: str, **fields) -> None:
        if self._log is not None:
            self._log.log(event, **fields)



class HeartbeatPublisher:
    """publish(component, status) -> UStatus on the heartbeat topic, through the same interceptor chain.

    Quiet on success (a heartbeat every 500 ms would drown the log), logs heartbeat_failed. seq counts per component.
    """

    def __init__(self, send: Send, topic: UUri, ttl_ms: int, log=None, interceptors: Sequence[Interceptor] = ()):
        self._send = _chain(send, interceptors)
        self._topic = topic
        self._ttl_ms = ttl_ms
        self._log = log
        self._seqs = {}
        self.published = 0
        self.failed = 0

    def build(self, component: str, status: str = HB_OK) -> UMessage:
        seq = self._seqs[component] = self._seqs.get(component, 0) + 1
        payload = build_heartbeat_msg(component, status, seq, clock.now_ms())
        return (UMessageBuilder.publish(self._topic)
                .with_ttl(self._ttl_ms)
                .build_from_upayload(UPayload.pack_from_data_and_format(
                    payload, UPayloadFormat.UPAYLOAD_FORMAT_JSON)))

    def publish(self, component: str, status: str = HB_OK) -> UStatus:
        message = self.build(component, status)
        result = self._send(message)
        if result.code != UCode.OK:
            self.failed += 1
            if self._log is not None:
                self._log.log("heartbeat_failed", component=component, msg_id=msg_id(message),
                              code=UCode.Name(result.code), error=result.message)
        else:
            self.published += 1
        return result
