# Made with Claude (Claude Code, Anthropic)
import io
import json
import threading

import pytest

pytest.importorskip("uprotocol")

from uprotocol.v1.ucode_pb2 import UCode  # noqa: E402
from uprotocol.v1.ustatus_pb2 import UStatus  # noqa: E402

from rom_common import contracts  # noqa: E402
from rom_common.jsonlog import JsonLogger  # noqa: E402
from rom_uprotocol import contract, uris  # noqa: E402
from rom_uprotocol.publisher import SignalPublisher  # noqa: E402
from vss_uprotocol_client import __main__ as client  # noqa: E402
from vss_uprotocol_client import sources  # noqa: E402


def logger():
    buf = io.StringIO()
    return JsonLogger("vss_publisher", stream=buf), lambda: [json.loads(l) for l in buf.getvalue().splitlines()]


class FakeClient:
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


def test_kuksa_source_yields_updates_and_reconnects_after_failure(monkeypatch):
    clients, stop = [], threading.Event()

    def open_client():
        clients.append(FakeClient())
        return clients[-1]

    def subscribe_temp(client, path):
        if len(clients) == 1:
            yield 40.0, 1
            raise ConnectionError("databroker gone")
        yield 41.0, 2
        stop.set()

    monkeypatch.setattr(sources.kuksa, "open_client", open_client)
    monkeypatch.setattr(sources.kuksa, "subscribe_temp", subscribe_temp)
    log, events = logger()
    src = sources.KuksaSource("Vehicle.X", log, retry_s=(0,))
    assert list(src.updates(stop)) == [("Vehicle.X", 40.0, 1), ("Vehicle.X", 41.0, 2)]
    assert all(c.disconnected for c in clients)
    assert [e["event"] for e in events()] == ["kuksa_connected", "kuksa_disconnected", "kuksa_connected"]


def test_forward_publishes_every_update_on_the_battery_topic():
    class ListSource:
        def updates(self, stop):
            yield from [("Vehicle.X", 30.0, 10), ("Vehicle.X", 31.0, 11)]

    sent = []
    log, events = logger()
    pub = SignalPublisher(lambda m: sent.append(m) or UStatus(code=UCode.OK), uris.battery_temp_topic("v"),
                          ttl_ms=2000, log=log)
    client.forward(ListSource(), pub, threading.Event())
    assert [contract.parse_signal_msg(m.payload).value for m in sent] == [30.0, 31.0]
    assert all(m.attributes.source == uris.battery_temp_topic("v") for m in sent)
    assert [e["event"] for e in events()] == ["published", "published"]


def test_vss_source_path_default_and_env(monkeypatch):
    assert client.vss_source_path() == contracts.VSS_BATTERY_TEMP
    monkeypatch.setenv("VSS_SOURCE_PATH", "Vehicle.Powertrain.TractionBattery.Temperature.Average")
    assert client.vss_source_path().endswith("Average")
