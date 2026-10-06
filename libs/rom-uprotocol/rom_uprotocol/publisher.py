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
from typing import Callable, Sequence

from uprotocol.communication.upayload import UPayload
from uprotocol.transport.builder.umessagebuilder import UMessageBuilder
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri
from uprotocol.v1.ustatus_pb2 import UStatus

from rom_common import clock

from .contract import build_signal_msg

Send = Callable[[UMessage], UStatus]
Interceptor = Callable[[UMessage, Send], UStatus]


def _chain(send: Send, interceptors: Sequence[Interceptor]) -> Send:
    forward = send
    for interceptor in reversed(interceptors):
        forward = (lambda i, nxt: lambda message: i(message, nxt))(interceptor, forward)
    return forward


class SignalPublisher:
    """publish(vss_path, value, source_ts_ms) -> UStatus; logs published / publish_failed if given a log."""

    def __init__(self, send: Send, topic: UUri, ttl_ms: int, log=None,
                 interceptors: Sequence[Interceptor] = ()):
        self._send = _chain(send, interceptors)
        self._topic = topic
        self._ttl_ms = ttl_ms
        self._log = log
        self.seq = 0
        self.published = 0
        self.failed = 0

    def build(self, vss_path: str, value: float, source_ts_ms: int) -> UMessage:
        self.seq += 1
        payload = build_signal_msg(vss_path, value, self.seq, clock.now_ms(), source_ts_ms)
        return (UMessageBuilder.publish(self._topic)
                .with_ttl(self._ttl_ms)
                .build_from_upayload(UPayload.pack_from_data_and_format(
                    payload, UPayloadFormat.UPAYLOAD_FORMAT_JSON)))

    def publish(self, vss_path: str, value: float, source_ts_ms: int) -> UStatus:
        status = self._send(self.build(vss_path, value, source_ts_ms))
        if status.code != UCode.OK:
            self.failed += 1
            self._emit("publish_failed", seq=self.seq, code=UCode.Name(status.code), error=status.message)
        else:
            self.published += 1
            self._emit("published", seq=self.seq, value=value, vss_path=vss_path,
                       source_ts_ms=source_ts_ms, published=self.published, failed=self.failed)
        return status

    def _emit(self, event: str, **fields) -> None:
        if self._log is not None:
            self._log.log(event, **fields)

