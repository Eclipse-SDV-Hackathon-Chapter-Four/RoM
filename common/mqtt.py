# Made with Claude (Claude Code, Anthropic) — shared RoM "common" module, used by all components.
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
