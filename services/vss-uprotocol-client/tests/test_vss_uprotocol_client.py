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


def test_fault_api_port_is_off_by_default(monkeypatch):
    monkeypatch.delenv("FAULT_API_PORT", raising=False)
    assert client.fault_api_port() == 0
    monkeypatch.setenv("FAULT_API_PORT", "9090")
    assert client.fault_api_port() == 9090


def _fault_api():
    import urllib.error
    import urllib.request

    from rom_uprotocol.faults import TransportFaults
    from vss_uprotocol_client.fault_api import build_api

    log, events = logger()
    faults = TransportFaults()
    server = build_api(faults, log, "127.0.0.1", 0).start()

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    return server, faults, call, events


def test_fault_api_drop_reaches_the_published_messages():
    server, faults, call, events = _fault_api()
    try:
        sent = []
        log, _ = logger()
        pub = SignalPublisher(lambda m: sent.append(m) or UStatus(code=UCode.OK), uris.battery_temp_topic("v"),
                              ttl_ms=2000, log=log, interceptors=[faults])
        pub.publish("Vehicle.X", 30.0, 1)
        status, fault = call("POST", "/faults", {"type": "drop"})
        assert status == 201 and fault["type"] == "drop"
        pub.publish("Vehicle.X", 31.0, 2)
        call("DELETE", f"/faults/{fault['id']}")
        pub.publish("Vehicle.X", 32.0, 3)
        assert [contract.parse_signal_msg(m.payload).value for m in sent] == [30.0, 32.0]
        # the publisher numbered all three, so the gap is visible to the guardian as a missing seq
        assert [contract.parse_signal_msg(m.payload).seq for m in sent] == [1, 3]
        assert call("GET", "/state")[1]["counts"]["dropped"] == 1
        assert [e["event"] for e in events()] == ["fault_injected", "fault_cleared"]
    finally:
        server.close()


def test_fault_api_validates_and_starts_runs():
    server, faults, call, events = _fault_api()
    try:
        assert call("POST", "/faults", {"type": "delay"})[0] == 422
        assert call("POST", "/faults", {"type": "nope"})[0] == 422
        assert call("POST", "/faults")[0] == 400
        assert call("DELETE", "/faults/9")[0] == 404
        faults.add("drop")
        assert call("POST", "/run", {"run_id": "camp-1", "seed": 5}) == (200, {"run_id": "camp-1", "seed": 5})
        assert faults.active() == [] and events()[-1]["run_id"] == "camp-1"
        assert call("POST", "/run", {"seed": "x"})[0] == 422
    finally:
        server.close()
