# Made with Claude (Claude Code, Anthropic)
"""uProtocol UTransport over Zenoh 1.x, per up-spec up-l1/zenoh.adoc.

Why our own: the official up-transport-zenoh-python is pinned to zenoh 1.0.0-alpha.6 and uses
the old 4-segment key format. This one follows the current spec and the Rust reference
(up-transport-zenoh-rust), so a Rust guardian on up-transport-zenoh interoperates:

  key        up/{auth}/{ue_type}/{ue_instance}/{ver}/{resource}/{sink... or {}/{}/{}/{}/{}}
  attachment 0x01 (uProtocol major version) + protobuf-encoded UAttributes
  payload    UMessage.payload as-is

Only publish/notification (pub/sub) is implemented — that is all the RoM data path needs.
"""
import asyncio
import json
import threading
from typing import Dict, Optional, Tuple

import zenoh
from uprotocol.transport.ulistener import UListener
from uprotocol.transport.utransport import UTransport
from uprotocol.transport.validator.uattributesvalidator import Validators
from uprotocol.uri.factory.uri_factory import UriFactory
from uprotocol.v1.uattributes_pb2 import UAttributes, UMessageType, UPriority
from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri
from uprotocol.v1.ustatus_pb2 import UStatus

from common import config

UPROTOCOL_MAJOR_VERSION = 1

_PRIORITY = {
    UPriority.UPRIORITY_CS0: zenoh.Priority.BACKGROUND,
    UPriority.UPRIORITY_CS1: zenoh.Priority.DATA_LOW,
    UPriority.UPRIORITY_CS2: zenoh.Priority.DATA,
    UPriority.UPRIORITY_CS3: zenoh.Priority.DATA_HIGH,
    UPriority.UPRIORITY_CS4: zenoh.Priority.INTERACTIVE_LOW,
    UPriority.UPRIORITY_CS5: zenoh.Priority.INTERACTIVE_HIGH,
    UPriority.UPRIORITY_CS6: zenoh.Priority.REAL_TIME,
}

_VALIDATORS = {
    UMessageType.UMESSAGE_TYPE_PUBLISH: Validators.PUBLISH,
    UMessageType.UMESSAGE_TYPE_NOTIFICATION: Validators.NOTIFICATION,
}


def _segment(value: int, wildcard: int) -> str:
    return "*" if value == wildcard else f"{value:X}"


def uri_to_key(uri: UUri, fallback_authority: str) -> str:
    """Five key segments for one UUri (spec "UUri Encoding Rules")."""
    authority = uri.authority_name or fallback_authority
    ue_type, ue_instance = uri.ue_id & 0xFFFF, uri.ue_id >> 16
    return "/".join((
        authority,
        _segment(ue_type, 0xFFFF),
        _segment(ue_instance, 0xFFFF),
        _segment(uri.ue_version_major, UriFactory.WILDCARD_ENTITY_VERSION),
        _segment(uri.resource_id, UriFactory.WILDCARD_RESOURCE_ID),
    ))


def to_zenoh_key(source: UUri, sink: Optional[UUri], fallback_authority: str) -> str:
    dst = uri_to_key(sink, fallback_authority) if sink is not None and sink != UUri() else "{}/{}/{}/{}/{}"
    return f"up/{uri_to_key(source, fallback_authority)}/{dst}"


def attributes_to_attachment(attributes: UAttributes) -> bytes:
    return bytes([UPROTOCOL_MAJOR_VERSION]) + attributes.SerializeToString()


def attachment_to_attributes(attachment: bytes) -> UAttributes:
    if len(attachment) < 2:
        raise ValueError("message has no/invalid attachment")
    if attachment[0] != UPROTOCOL_MAJOR_VERSION:
        raise ValueError(f"expected uProtocol version {UPROTOCOL_MAJOR_VERSION}, got {attachment[0]}")
    attributes = UAttributes()
    attributes.ParseFromString(attachment[1:])
    return attributes


def zenoh_config(cfg: Optional[config.UProtocol] = None) -> zenoh.Config:
    """Zenoh session config from env (ZENOH_MODE / ZENOH_CONNECT / ZENOH_LISTEN)."""
    cfg = cfg or config.uprotocol()
    conf = zenoh.Config()
    conf.insert_json5("mode", json.dumps(cfg.zenoh_mode))
    if cfg.zenoh_connect:
        conf.insert_json5("connect/endpoints", json.dumps(list(cfg.zenoh_connect)))
    if cfg.zenoh_listen:
        conf.insert_json5("listen/endpoints", json.dumps(list(cfg.zenoh_listen)))
    return conf


class ZenohTransport(UTransport):
    """One Zenoh session per process. Listeners are called on Zenoh's callback thread."""

    def __init__(self, source: UUri, conf: Optional[zenoh.Config] = None):
        self._source = source
        self._authority = source.authority_name or config.uprotocol().authority
        self._session = zenoh.open(conf if conf is not None else zenoh_config())
        self._subscribers: Dict[Tuple[str, UListener], zenoh.Subscriber] = {}
        self._lock = threading.Lock()

    def get_source(self) -> UUri:
        return self._source

    def send_sync(self, message: UMessage) -> UStatus:
        """Blocking send for callers without an event loop (e.g. a KUKSA subscription thread)."""
        attributes = message.attributes
        validator = _VALIDATORS.get(attributes.type)
        if validator is None:
            return UStatus(code=UCode.UNIMPLEMENTED, message="only publish/notification are supported")
        result = validator.validator().validate(attributes)
        if result.is_failure():
            return UStatus(code=UCode.INVALID_ARGUMENT, message=result.get_message())

        sink = attributes.sink if attributes.HasField("sink") else None
        key = to_zenoh_key(attributes.source, sink, self._authority)
        try:
            self._session.put(
                key,
                message.payload or b"",
                attachment=attributes_to_attachment(attributes),
                priority=_PRIORITY.get(attributes.priority, zenoh.Priority.DATA_LOW),
            )
        except Exception as e:  # session closed / network error
            return UStatus(code=UCode.INTERNAL, message=f"zenoh put failed: {e}")
        return UStatus(code=UCode.OK)

    async def send(self, message: UMessage) -> UStatus:
        return self.send_sync(message)

    def register_listener_sync(self, source_filter: UUri, listener: UListener,
                               sink_filter: Optional[UUri] = None) -> UStatus:
        key = to_zenoh_key(source_filter, sink_filter, self._authority)

        def on_sample(sample: zenoh.Sample) -> None:
            if sample.attachment is None:
                return  # not a uProtocol message
            try:
                attributes = attachment_to_attributes(sample.attachment.to_bytes())
            except Exception:
                return  # malformed attachment: drop, never kill Zenoh's callback thread
            asyncio.run(listener.on_receive(UMessage(attributes=attributes, payload=sample.payload.to_bytes())))

        with self._lock:
            if (key, listener) in self._subscribers:
                return UStatus(code=UCode.ALREADY_EXISTS, message=key)
            self._subscribers[(key, listener)] = self._session.declare_subscriber(key, on_sample)
        return UStatus(code=UCode.OK, message=key)

    async def register_listener(self, source_filter: UUri, listener: UListener,
                                sink_filter: Optional[UUri] = None) -> UStatus:
        return self.register_listener_sync(source_filter, listener, sink_filter)

    async def unregister_listener(self, source_filter: UUri, listener: UListener,
                                  sink_filter: Optional[UUri] = None) -> UStatus:
        key = to_zenoh_key(source_filter, sink_filter, self._authority)
        with self._lock:
            subscriber = self._subscribers.pop((key, listener), None)
        if subscriber is None:
            return UStatus(code=UCode.NOT_FOUND, message=key)
        subscriber.undeclare()
        return UStatus(code=UCode.OK)

    def close_sync(self) -> None:
        with self._lock:
            subscribers, self._subscribers = list(self._subscribers.values()), {}
        for subscriber in subscribers:
            subscriber.undeclare()
        self._session.close()

    async def close(self) -> None:
        self.close_sync()
