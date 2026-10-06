# Made with Claude (Claude Code, Anthropic)
"""MQTT → KUKSA adapter.

Subscribes to the sensor topic(s), validates each payload against the contract
and writes the value to the KUKSA Databroker. Invalid messages are logged as
event=rejected and never reach the databroker.

Run from the repo root:  python -m adapter.mqtt_kuksa_adapter
"""
import os
import signal
import threading

from common import clock, config, contracts, jsonlog, kuksa, mqtt

# topic -> (VSS path, scale, offset); value written = temp_c * scale + offset
MAPPING = {
    contracts.TOPIC_SENSOR_TEMP: (contracts.VSS_BATTERY_TEMP, 1.0, 0.0),
}

# ts_ms below this is device uptime, not epoch ms (MCU without NTP) -> no latency.
_EPOCH_MS_MIN = 1_000_000_000_000


class Adapter:
    """Transport-free core: handle(topic, payload) -> validate -> write(path, value)."""

    def __init__(self, write, log):
        self._write = write  # (vss_path, value) -> None, raises on failure
        self._log = log
        self._last_seq = {}  # device_id -> last seq seen
        self.received = 0
        self.rejected = 0
        self.written = 0

    def handle(self, topic, payload):
        self.received += 1
        mapping = MAPPING.get(topic)
        if mapping is None:
            self._reject(topic, "unmapped_topic")
            return
        try:
            msg = contracts.parse_sensor_msg(payload)
        except contracts.ContractError as e:
            self._reject(topic, str(e))
            return

        self._check_seq(msg)

        path, scale, offset = mapping
        value = msg.temp_c * scale + offset
        try:
            self._write(path, value)
        except Exception as e:  # databroker down / gRPC error: log and keep going
            self._log.log("kuksa_write_failed", device_id=msg.device_id, seq=msg.seq,
                          vss_path=path, error=str(e))
            return

        self.written += 1
        rec = {"device_id": msg.device_id, "seq": msg.seq, "temp_c": msg.temp_c,
               "vss_path": path, "value": value,
               "received": self.received, "rejected": self.rejected}
        if msg.ts_ms >= _EPOCH_MS_MIN:
            rec["latency_ms"] = clock.now_ms() - msg.ts_ms
        self._log.log("forwarded", **rec)

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

    def __call__(self, path, value):
        with self._lock:
            if self._client is None:
                self._client = kuksa.open_client()
                self._log.log("kuksa_connected")
            try:
                kuksa.set_temp(self._client, value, path)
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


def main():
    log = jsonlog.get_logger("adapter")
    ep = config.endpoints()
    writer = KuksaWriter(log)
    adapter = Adapter(writer, log)

    def on_message(topic, payload):
        try:
            adapter.handle(topic, payload)
        except Exception as e:  # never let an exception kill the paho network thread
            log.log("handler_error", topic=topic, error=repr(e))

    client = mqtt.MqttClient(f"rom-adapter-{os.getpid()}")
    for topic in MAPPING:
        client.subscribe(topic, on_message, qos=contracts.QOS_SENSOR_TEMP)
    client.connect(on_connected=lambda _: log.log("mqtt_connected", topics=list(MAPPING)))
    log.log("started", mqtt=f"{ep.mqtt_host}:{ep.mqtt_port}",
            kuksa=f"{ep.kuksa_host}:{ep.kuksa_port}", mapping=MAPPING)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()

    client.close()
    writer.close()
    log.log("stopped", received=adapter.received, rejected=adapter.rejected, written=adapter.written)


if __name__ == "__main__":
    main()
