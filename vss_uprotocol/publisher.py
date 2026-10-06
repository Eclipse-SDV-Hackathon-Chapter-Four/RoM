# Made with Claude (Claude Code, Anthropic)
"""VSS uProtocol Publisher: KUKSA Databroker -> uProtocol (Zenoh).

Subscribes to one VSS path in the databroker (VSS_SOURCE_PATH, default the contract path)
and publishes every update on the uProtocol topic up://<UP_AUTHORITY>/1001/1/8001.
This is the only component that talks to KUKSA on the guardian's side: the guardian reads
uProtocol, never the databroker (challenge architecture rule).

Run from the repo root:  python -m vss_uprotocol.publisher
"""
import signal
import threading

from uprotocol.communication.upayload import UPayload
from uprotocol.transport.builder.umessagebuilder import UMessageBuilder
from uprotocol.uri.serializer.uriserializer import UriSerializer
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.ucode_pb2 import UCode

from common import clock, config, contracts, jsonlog, kuksa
from vss_uprotocol import topics

RETRY_S = (1, 2, 5)  # KUKSA reconnect backoff, last value repeats


class Publisher:
    """Transport-free core: on_value(value, source_ts_ms) -> UMessage -> send(msg) -> UStatus."""

    def __init__(self, send, log, topic, vss_path, ttl_ms):
        self._send = send
        self._log = log
        self._topic = topic
        self._vss_path = vss_path
        self._ttl_ms = ttl_ms
        self.seq = 0
        self.published = 0
        self.failed = 0

    def on_value(self, value, source_ts_ms):
        self.seq += 1
        sent_ts = clock.now_ms()
        payload = contracts.build_signal_msg(self._vss_path, value, self.seq, sent_ts, source_ts_ms)
        message = (UMessageBuilder.publish(self._topic)
                   .with_ttl(self._ttl_ms)
                   .build_from_upayload(UPayload.pack_from_data_and_format(
                       payload, UPayloadFormat.UPAYLOAD_FORMAT_JSON)))
        status = self._send(message)
        if status.code != UCode.OK:
            self.failed += 1
            self._log.log("publish_failed", seq=self.seq, code=UCode.Name(status.code), error=status.message)
            return
        self.published += 1
        self._log.log("published", seq=self.seq, value=value, vss_path=self._vss_path,
                      source_ts_ms=source_ts_ms, published=self.published, failed=self.failed)


def run_kuksa(publisher, vss_path, log, stop):
    """Forward KUKSA updates until stop is set; reconnect with backoff when the databroker goes away."""
    attempt = 0
    while not stop.is_set():
        client = None
        try:
            client = kuksa.open_client()
            log.log("kuksa_connected", vss_path=vss_path)
            attempt = 0
            for value, rx_ms in kuksa.subscribe_temp(client, vss_path):
                publisher.on_value(value, rx_ms)
                if stop.is_set():
                    break
        except Exception as e:
            log.log("kuksa_disconnected", error=str(e))
        finally:
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
        stop.wait(RETRY_S[min(attempt, len(RETRY_S) - 1)])
        attempt += 1


def main():
    from vss_uprotocol.zenoh_transport import ZenohTransport  # zenoh only needed at runtime

    log = jsonlog.get_logger("vss_publisher")
    cfg = config.uprotocol()
    transport = ZenohTransport(topics.publisher_uri())
    topic = topics.battery_temp_topic()
    publisher = Publisher(transport.send_sync, log, topic, cfg.vss_source_path,
                          ttl_ms=config.thresholds().stale_ms)
    log.log("started", topic="up:" + UriSerializer.serialize(topic), vss_path=cfg.vss_source_path,
            zenoh_mode=cfg.zenoh_mode, zenoh_connect=list(cfg.zenoh_connect))

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    # The KUKSA subscription blocks until the next update, so it runs in a daemon thread
    # and the main thread exits as soon as stop is set.
    threading.Thread(target=run_kuksa, args=(publisher, cfg.vss_source_path, log, stop), daemon=True).start()
    stop.wait()

    transport.close_sync()
    log.log("stopped", published=publisher.published, failed=publisher.failed)


if __name__ == "__main__":
    main()
