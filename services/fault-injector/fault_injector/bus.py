# Made with Claude (Claude Code, Anthropic)
"""Campaign events over uProtocol (up://<UP_AUTHORITY>/1003/1/8005): the evidence collector's START / END markers.

CampaignLog wraps the runner's JSON logger: every campaign event (rom_uprotocol.contract.CAMPAIGN_EVENTS) is
logged exactly as before and also handed to `publish` as a CampaignEvent. Other log lines stay local.
Needs rom-uprotocol (pip extra `uprotocol`), so __main__ only imports this module for --uprotocol.
"""
import os
import time
from typing import Callable, Optional, Tuple

from rom_common import clock
from rom_uprotocol.contract import CAMPAIGN_EVENTS, CampaignEvent, build_campaign_event

DEFAULT_SETTLE_MS = 1000


class CampaignLog:
    def __init__(self, log, publish: Callable[[CampaignEvent], None]):
        self._log, self._publish, self._seq = log, publish, 0

    @property
    def run_id(self) -> Optional[str]:
        return self._log.run_id

    @run_id.setter
    def run_id(self, value: Optional[str]) -> None:
        self._log.run_id = value

    def log(self, event: str, **fields) -> None:
        self._log.log(event, **fields)
        if event in CAMPAIGN_EVENTS and self.run_id is not None:
            self._seq += 1
            self._publish(CampaignEvent(event, self.run_id, clock.now_ms(), self._seq, fields))


def uprotocol_publisher(log) -> Tuple[Callable[[CampaignEvent], None], Callable[[], None]]:
    """(publish, close) on the campaign event topic. Waits ZENOH_SETTLE_MS so Zenoh has connected and knows the
    subscribers before the first event: an event published into an empty network is gone (no TTL, no history)."""
    from rom_uprotocol import uris
    from rom_uprotocol.publisher import SignalPublisher
    from rom_uprotocol.transport import make_transport

    transport = make_transport(uris.campaign_runner_uri())
    publisher = SignalPublisher(transport.send_sync, uris.campaign_event_topic(), ttl_ms=0, log=log)
    time.sleep(int(os.environ.get("ZENOH_SETTLE_MS", DEFAULT_SETTLE_MS)) / 1000)

    def publish(event) -> None:
        publisher.publish_json(lambda seq, ts: build_campaign_event(event), campaign_event=event.event)

    return publish, transport.close_sync
