# Made with Claude (Claude Code, Anthropic)
"""MQTT → KUKSA adapter.

Subscribes to the sensor topic(s), validates each payload against the contract
and writes the value to the KUKSA Databroker. Invalid messages are logged as
event=rejected and never reach the databroker.

The board has one temperature sensor: it is written as cell ADAPTER_CELL (default 1) and as
Temperature.Max in one call. A simulator can fill the other cells (SIM_CELLS=2,3,4, `make hw`).

The adapter also keeps two heartbeats alive in KUKSA (Vehicle.RoM.Heartbeat.*), every HEARTBEAT_PERIOD_MS:
  Adapter  always, while this process runs
  Chip     a counter (1, 2, ...) while the board is alive: telemetry arrived within CHIP_TIMEOUT_MS and the board's
           status topic does not say "offline" (a newer telemetry message overrules an older "offline");
           0 while it is not. The explicit 0 lets the guardian react at once instead of waiting for a second
           timeout on top of CHIP_TIMEOUT_MS.
so the guardian can tell "board silent" from "adapter dead" from "databroker down".

Run:  rom-adapter   (or  python -m adapter.mqtt_kuksa_adapter)
"""
import itertools
import os
import signal
import threading
import time

from rom_common import clock, config, contracts, jsonlog, kuksa, mqtt


def build_mapping(cell: int = 1) -> dict:
    """topic -> [(VSS path, scale, offset), ...]; value written = temp_c * scale + offset."""
    if not 1 <= cell <= len(contracts.VSS_CELL_TEMPS):
        raise ValueError(f"ADAPTER_CELL must be 1..{len(contracts.VSS_CELL_TEMPS)}, got {cell}")
    return {contracts.TOPIC_SENSOR_TEMP: [(contracts.VSS_CELL_TEMPS[cell - 1], 1.0, 0.0),
                                          (contracts.VSS_BATTERY_TEMP, 1.0, 0.0)]}


MAPPING = build_mapping(int(os.environ.get("ADAPTER_CELL", "1")))

# ts_ms below this is device uptime, not epoch ms (MCU without NTP) -> no latency.
_EPOCH_MS_MIN = 1_000_000_000_000


class ChipLiveness:
    """Is the physical board alive? Telemetry within `timeout_s` and no newer "offline" status. Transport-free."""

    def __init__(self, timeout_s: float, monotonic=time.monotonic):
        self._timeout_s = timeout_s
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._events = itertools.count(1)      # orders telemetry against status messages
        self._telemetry_at = None
        self._telemetry_event = 0
        self._offline_event = 0

    def on_telemetry(self) -> None:
        with self._lock:
            self._telemetry_at, self._telemetry_event = self._monotonic(), next(self._events)

    def on_status(self, online: bool) -> None:
        with self._lock:
            if not online:
                self._offline_event = next(self._events)

    def alive(self) -> bool:
        with self._lock:
            return (self._telemetry_at is not None
                    and self._monotonic() - self._telemetry_at <= self._timeout_s
                    and self._telemetry_event > self._offline_event)


class Adapter:
    """Transport-free core: handle(topic, payload) -> validate -> write({vss_path: value})."""

    def __init__(self, write, log, mapping=None, chip_timeout_s=None, monotonic=time.monotonic):
        self._write = write  # ({vss_path: value}) -> None, raises on failure
        self._log = log
        self._mapping = mapping if mapping is not None else MAPPING
        timeout_s = chip_timeout_s if chip_timeout_s is not None else config.heartbeat().chip_timeout_ms / 1000
        self.chip = ChipLiveness(timeout_s, monotonic)
        self._last_seq = {}  # device_id -> last seq seen
        self._beats = 0
        self._chip_beats = 0
        self._chip_was_alive = None
        self._beat_failed = False
        self.received = 0
        self.rejected = 0
        self.written = 0

    def handle(self, topic, payload):
        self.received += 1
        if topic == contracts.TOPIC_SENSOR_STATUS:
            self._handle_status(topic, payload)
            return
        mapping = self._mapping.get(topic)
        if mapping is None:
            self._reject(topic, "unmapped_topic")
            return
        try:
            msg = contracts.parse_sensor_msg(payload)
        except contracts.ContractError as e:
            self._reject(topic, str(e))
            return

        self._check_seq(msg)
        self.chip.on_telemetry()

        values = {path: msg.temp_c * scale + offset for path, scale, offset in mapping}
        try:
            self._write(values)
        except Exception as e:  # databroker down / gRPC error: log and keep going
            self._log.log("kuksa_write_failed", device_id=msg.device_id, seq=msg.seq,
                          vss_paths=list(values), error=str(e))
            return

        self.written += 1
        rec = {"device_id": msg.device_id, "seq": msg.seq, "temp_c": msg.temp_c,
               "values": values, "received": self.received, "rejected": self.rejected}
        if msg.ts_ms >= _EPOCH_MS_MIN:
            rec["latency_ms"] = clock.now_ms() - msg.ts_ms
        self._log.log("forwarded", **rec)

    def _handle_status(self, topic, payload):
        text = payload.decode(errors="replace") if isinstance(payload, bytes) else str(payload)
        if text not in (contracts.STATUS_ONLINE, contracts.STATUS_OFFLINE):
            self._reject(topic, f"invalid_status: {text[:20]}")
            return
        self.chip.on_status(text == contracts.STATUS_ONLINE)
        self._log.log("chip_status", status=text)

    def heartbeat_values(self) -> dict:
        """Heartbeat counters for this tick: Adapter always, Chip a counter while the board is alive, else 0."""
        self._beats += 1
        values = {contracts.VSS_HEARTBEAT_ADAPTER: float(self._beats)}
        alive = self.chip.alive()
        if alive:
            self._chip_beats += 1
        values[contracts.VSS_HEARTBEAT_CHIP] = float(self._chip_beats) if alive else 0.0
        if alive != self._chip_was_alive:
            self._log.log("chip_alive" if alive else "chip_lost")
            self._chip_was_alive = alive
        return values

    def beat(self) -> bool:
        """Write this tick's heartbeats. Returns False (and logs once per outage) if KUKSA refused them."""
        try:
            self._write(self.heartbeat_values())
        except Exception as e:
            if not self._beat_failed:
                self._log.log("kuksa_heartbeat_failed", error=str(e))
            self._beat_failed = True
            return False
        self._beat_failed = False
        return True

    def _reject(self, topic, reason):
        self.rejected += 1
        self._log.log("rejected", topic=topic, reason=reason,
                      received=self.received, rejected=self.rejected)

    def _check_seq(self, msg):
        """Lost / duplicated / reordered messages are the first transport-fault signal."""
        last = self._last_seq.get(msg.device_id)
        self._last_seq[msg.device_id] = msg.seq
        if last is None or msg.seq == last + 1:
            return
        if msg.seq > last + 1:
            self._log.log("seq_gap", device_id=msg.device_id, expected=last + 1,
                          got=msg.seq, missing=msg.seq - last - 1)
        elif msg.seq == last:
            self._log.log("seq_duplicate", device_id=msg.device_id, seq=msg.seq)
        else:  # device reboot or reordering
            self._log.log("seq_backwards", device_id=msg.device_id, expected=last + 1, got=msg.seq)


class KuksaWriter:
    """One persistent KUKSA connection; dropped on error and reopened on the next write."""

    def __init__(self, log):
        self._log = log
        self._client = None
        self._lock = threading.Lock()

    def __call__(self, values):
        with self._lock:
            if self._client is None:
                self._client = kuksa.open_client()
                self._log.log("kuksa_connected")
            try:
                kuksa.set_values(self._client, values)
            except Exception:
                self._close_locked()
                raise

    def close(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None


def heartbeat_loop(adapter, period_s, stop):
    while not stop.is_set():
        adapter.beat()
        stop.wait(period_s)


def main():
    log = jsonlog.get_logger("adapter")
    ep = config.endpoints()
    hb = config.heartbeat()
    writer = KuksaWriter(log)
    adapter = Adapter(writer, log)

    def on_message(topic, payload):
        try:
            adapter.handle(topic, payload)
        except Exception as e:  # never let an exception kill the paho network thread
            log.log("handler_error", topic=topic, error=repr(e))

    client = mqtt.MqttClient(f"rom-adapter-{os.getpid()}")
    client.subscribe(contracts.TOPIC_SENSOR_TEMP, on_message, qos=contracts.QOS_SENSOR_TEMP)
    client.subscribe(contracts.TOPIC_SENSOR_STATUS, on_message, qos=contracts.QOS_SENSOR_STATUS)
    topics = [contracts.TOPIC_SENSOR_TEMP, contracts.TOPIC_SENSOR_STATUS]
    client.connect(on_connected=lambda _: log.log("mqtt_connected", topics=topics))
    log.log("started", mqtt=f"{ep.mqtt_host}:{ep.mqtt_port}", kuksa=f"{ep.kuksa_host}:{ep.kuksa_port}",
            mapping=MAPPING, heartbeat_period_ms=hb.period_ms, chip_timeout_ms=hb.chip_timeout_ms)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threading.Thread(target=heartbeat_loop, args=(adapter, hb.period_ms / 1000, stop), daemon=True).start()
    stop.wait()

    client.close()
    writer.close()
    log.log("stopped", received=adapter.received, rejected=adapter.rejected, written=adapter.written)


if __name__ == "__main__":
    main()
