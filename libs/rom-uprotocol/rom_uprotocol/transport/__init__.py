# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""Transport selection: make_transport(entity_uri) picks the UTransport named by UP_TRANSPORT.

A new transport is added by registering a factory, without touching callers:

    register_transport("someip", lambda source: SomeIpTransport(source))
"""
from typing import Callable, Dict, Optional

from uprotocol.transport.utransport import UTransport
from uprotocol.v1.uri_pb2 import UUri

from .. import config

TransportFactory = Callable[[UUri], UTransport]


def _zenoh(source: UUri) -> UTransport:
    from .zenoh import ZenohTransport  # zenoh is only imported when this transport is used

    return ZenohTransport(source)


_FACTORIES: Dict[str, TransportFactory] = {"zenoh": _zenoh}


def register_transport(name: str, factory: TransportFactory) -> None:
    _FACTORIES[name] = factory


def available_transports() -> tuple:
    return tuple(sorted(_FACTORIES))


def make_transport(source: UUri, name: Optional[str] = None) -> UTransport:
    """Open the transport `name` (default: UP_TRANSPORT env, "zenoh") for the uEntity `source`."""
    name = name or config.uprotocol().transport
    factory = _FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"unknown uProtocol transport {name!r}, available: {', '.join(available_transports())}")
    return factory(source)
