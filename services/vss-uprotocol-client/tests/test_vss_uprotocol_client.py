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

    def subscribe_values(client, paths):
        assert paths == ["Vehicle.A", "Vehicle.B"]
        if len(clients) == 1:
            yield {"Vehicle.A": 40.0, "Vehicle.B": 39.0}, 1
            raise ConnectionError("databroker gone")
        yield {"Vehicle.B": 41.0}, 2
        stop.set()

    monkeypatch.setattr(sources.kuksa, "open_client", open_client)
    monkeypatch.setattr(sources.kuksa, "subscribe_values", subscribe_values)
    log, events = logger()
    src = sources.KuksaSource(["Vehicle.A", "Vehicle.B"], log, retry_s=(0,))
    assert list(src.updates(stop)) == [({"Vehicle.A": 40.0, "Vehicle.B": 39.0}, 1), ({"Vehicle.B": 41.0}, 2)]
    assert all(c.disconnected for c in clients)
    assert [e["event"] for e in events()] == ["kuksa_connected", "kuksa_disconnected", "kuksa_connected"]


def test_forward_splits_each_update_into_one_cell_message_and_max():
    c1, c2, c3, c4 = contracts.VSS_CELL_TEMPS
    mx = contracts.VSS_BATTERY_TEMP

    class ListSource:
        def updates(self, stop):
            yield {c1: 33.0, c2: 31.5, c3: 31.0, c4: 32.0, mx: 33.0}, 10
            yield {c1: 33.5, c2: 31.6, c4: 32.1, mx: 33.5}, 11      # cell 3 dropped out of this update

    sent_cells, sent_max = [], []
    log, events = logger()
    ok = UStatus(code=UCode.OK)
    cells_pub = SignalPublisher(lambda m: sent_cells.append(m) or ok, uris.battery_cells_topic("v"), 2000, log=log)
    max_pub = SignalPublisher(lambda m: sent_max.append(m) or ok, uris.battery_temp_topic("v"), 2000, log=log)
    client.forward(ListSource(), max_pub, cells_pub, threading.Event(), run_id=lambda: "camp-1")
    msgs = [contract.parse_cells_msg(m.payload) for m in sent_cells]
    assert [m.cells for m in msgs] == [{1: 33.0, 2: 31.5, 3: 31.0, 4: 32.0}, {1: 33.5, 2: 31.6, 4: 32.1}]
    assert [(m.seq, m.source_ts_ms, m.run_id) for m in msgs] == [(1, 10, "camp-1"), (2, 11, "camp-1")]
    assert all(m.attributes.source == uris.battery_cells_topic("v") for m in sent_cells)
    assert [contract.parse_signal_msg(m.payload).value for m in sent_max] == [33.0, 33.5]
    assert [e["event"] for e in events()] == ["published"] * 4


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


def test_coalesce_merges_per_path_notifications_of_one_write():
    c1, c2, c3, c4 = contracts.VSS_CELL_TEMPS
    mx = contracts.VSS_BATTERY_TEMP

    class PerPathSource:   # what the databroker really does: one notification per path
        def updates(self, stop):
            yield from [({c1: 30.0}, 1), ({c2: 29.0}, 2), ({c3: 28.0}, 3), ({c4: 28.5}, 4), ({mx: 30.0}, 5),
                        ({c1: 30.1}, 11), ({c3: 28.1}, 12), ({c4: 28.6}, 13), ({mx: 30.1}, 14)]   # cell 2 dropped

    batches = list(sources.coalesce(PerPathSource(), threading.Event(), window_s=0.2))
    assert batches == [({c1: 30.0, c2: 29.0, c3: 28.0, c4: 28.5, mx: 30.0}, 1),
                       ({c1: 30.1, c3: 28.1, c4: 28.6, mx: 30.1}, 11)]


def test_coalesce_flushes_after_the_window():
    c1 = contracts.VSS_CELL_TEMPS[0]
    gate = threading.Event()

    class SlowSource:
        def updates(self, stop):
            yield {c1: 30.0}, 1
            gate.wait(2)
            yield {contracts.VSS_CELL_TEMPS[1]: 29.0}, 2

    it = sources.coalesce(SlowSource(), threading.Event(), window_s=0.05)
    assert next(it) == ({c1: 30.0}, 1)   # flushed by the window, before the second update exists
    gate.set()
    assert next(it) == ({contracts.VSS_CELL_TEMPS[1]: 29.0}, 2)


# --- heartbeats -----------------------------------------------------------------------------------------------

from rom_uprotocol.publisher import HeartbeatPublisher  # noqa: E402
from vss_uprotocol_client import heartbeat  # noqa: E402


def test_forward_turns_the_producers_heartbeat_counters_into_heartbeat_messages():
    c1 = contracts.VSS_CELL_TEMPS[0]

    class ListSource:
        def updates(self, stop):
            yield {c1: 30.0, contracts.VSS_HEARTBEAT_SIMULATOR: 7.0, contracts.VSS_HEARTBEAT_CHIP: 7.0}, 10
            yield {contracts.VSS_HEARTBEAT_ADAPTER: 3.0, contracts.VSS_HEARTBEAT_CHIP: 0.0}, 11   # chip: 0 = down

    sent_cells, sent_beats = [], []
    ok = UStatus(code=UCode.OK)
    cells_pub = SignalPublisher(lambda m: sent_cells.append(m) or ok, uris.battery_cells_topic("v"), 2000)
    max_pub = SignalPublisher(lambda m: ok, uris.battery_temp_topic("v"), 2000)
    beats = HeartbeatPublisher(lambda m: sent_beats.append(m) or ok, uris.heartbeat_topic("v"), 1500)
    client.forward(ListSource(), max_pub, cells_pub, threading.Event(), beats_publisher=beats)
    got = [contract.parse_heartbeat_msg(m.payload) for m in sent_beats]
    assert [(h.component, h.status) for h in got] == [("chip", "ok"), ("simulator", "ok"), ("chip", "down"),
                                                       ("adapter", "ok")]
    assert len(sent_cells) == 1                                   # the heartbeat-only update has no cell message
    assert all(m.attributes.source == uris.heartbeat_topic("v") for m in sent_beats)


class ProbeClient:
    def __init__(self, fail=False):
        self.fail, self.disconnected, self.calls = fail, False, 0

    def get_server_info(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("databroker down")

    def disconnect(self):
        self.disconnected = True


def test_probe_reports_up_down_and_reconnects():
    clients = [ProbeClient(fail=True), ProbeClient()]
    probe = heartbeat.DatabrokerProbe(open_client=lambda: clients.pop(0))
    assert probe.check() is False and probe._client is None        # failed call drops the connection
    assert probe.check() is True and probe.check() is True         # reopened, one connection reused
    probe.close()


def test_probe_open_failure_is_down_not_an_exception():
    def refuse():
        raise ConnectionError("refused")
    assert heartbeat.DatabrokerProbe(open_client=refuse).check() is False


def test_databroker_down_fault_forces_the_probe_down_without_touching_kuksa():
    from rom_uprotocol.faults import TransportFaults
    faults, c = TransportFaults(), ProbeClient()
    probe = heartbeat.DatabrokerProbe(faults, open_client=lambda: c)
    assert probe.check() is True
    fault = faults.add("databroker_down", duration_s=30)
    assert probe.check() is False and c.calls == 1
    faults.remove(fault.id)
    assert probe.check() is True


class FakeBeats:
    def __init__(self, stop, after):
        self.sent, self.stop, self.after = [], stop, after

    def publish(self, component, status):
        self.sent.append((component, status))
        if len(self.sent) >= self.after:
            self.stop.set()


def test_uprotocol_beat_repeats_until_stopped():
    stop = threading.Event()
    beats = FakeBeats(stop, after=3)
    heartbeat.beat_uprotocol(beats, 0, stop)
    assert beats.sent == [("uprotocol", "ok")] * 3


def test_databroker_beat_publishes_status_and_logs_only_changes():
    stop = threading.Event()
    log, events = logger()
    answers = iter([True, True, False, False])
    probe = type("P", (), {"check": lambda self: next(answers), "close": lambda self: None})()
    beats = FakeBeats(stop, after=4)
    heartbeat.beat_databroker(beats, probe, 0, stop, log)
    assert beats.sent == [("databroker", "ok")] * 2 + [("databroker", "down")] * 2
    assert [e["event"] for e in events()] == ["databroker_up", "databroker_down"]


def test_fault_api_accepts_databroker_down_and_topic_params():
    server, faults, call, events = _fault_api()
    try:
        status, fault = call("POST", "/faults", {"type": "databroker_down", "duration_s": 5})
        assert status == 201 and faults.is_active("databroker_down")
        status, fault = call("POST", "/faults", {"type": "drop", "params": {"topic": "heartbeat"}})
        assert status == 201 and fault["params"]["topic"] == "heartbeat"
        assert call("POST", "/faults", {"type": "drop", "params": {"topic": "nope"}})[0] == 422
    finally:
        server.close()
