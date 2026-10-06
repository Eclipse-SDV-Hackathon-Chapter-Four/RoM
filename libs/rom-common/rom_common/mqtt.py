# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
"""Thin paho-mqtt helper (paho-mqtt is imported lazily so other modules work without it).

Auto-reconnect is enabled; on every (re)connect the subscriptions are re-issued.
"""
from typing import Callable, Optional

from . import config


def make_client(client_id: str, will_topic: Optional[str] = None, will_payload: Optional[str] = None,
                will_qos: int = 1, will_retain: bool = True):
    import paho.mqtt.client as mqtt

    try:  # paho-mqtt >= 2.0
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=client_id)
    if will_topic:
        client.will_set(will_topic, will_payload, qos=will_qos, retain=will_retain)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    return client


def connect(client, subscriptions: Optional[dict] = None,
            on_message: Optional[Callable] = None, on_connected: Optional[Callable] = None):
    """Connect using MQTT_HOST/MQTT_PORT and start the network loop in a background thread.

    subscriptions: {topic: qos}, re-subscribed after every reconnect.
    """
    ep = config.endpoints()
    subs = subscriptions or {}

    def _on_connect(c, userdata, *args):
        for topic, qos in subs.items():
            c.subscribe(topic, qos)
        if on_connected:
            on_connected(c)

    client.on_connect = _on_connect
    if on_message:
        client.on_message = lambda c, u, msg: on_message(msg.topic, msg.payload)
    client.connect_async(ep.mqtt_host, ep.mqtt_port, keepalive=30)
    client.loop_start()
    return client


class MqttClient:
    """Convenience wrapper: connect, publish(), subscribe(topic, handler), close().

    Subscriptions are remembered and re-issued after every reconnect. Handlers are
    called as handler(topic, payload_bytes) on the paho network thread, and may use
    MQTT wildcards (+, #).
    """

    def __init__(self, client_id: str, will_topic: Optional[str] = None,
                 will_payload: Optional[str] = None, will_qos: int = 1, will_retain: bool = True):
        self._client = make_client(client_id, will_topic, will_payload, will_qos, will_retain)
        self._handlers = {}  # topic filter -> (qos, handler)
        self._on_connected = None

    def connect(self, on_connected: Optional[Callable] = None) -> "MqttClient":
        self._on_connected = on_connected
        self._client.on_message = self._dispatch
        connect(self._client, on_connected=self._resubscribe)
        return self

    def publish(self, topic: str, payload, qos: int = 0, retain: bool = False) -> None:
        """Queue a message; paho delivers it once connected (QoS>0 survives reconnects)."""
        self._client.publish(topic, payload, qos=qos, retain=retain)

    def subscribe(self, topic: str, handler: Callable[[str, bytes], None], qos: int = 0) -> None:
        self._handlers[topic] = (qos, handler)
        if self._client.is_connected():
            self._client.subscribe(topic, qos)

    def _resubscribe(self, client) -> None:
        for topic, (qos, _) in self._handlers.items():
            client.subscribe(topic, qos)
        if self._on_connected:
            self._on_connected(self)

    def _dispatch(self, client, userdata, msg) -> None:
        from paho.mqtt.client import topic_matches_sub

        for topic, (_, handler) in list(self._handlers.items()):
            if topic_matches_sub(topic, msg.topic):
                handler(msg.topic, msg.payload)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
