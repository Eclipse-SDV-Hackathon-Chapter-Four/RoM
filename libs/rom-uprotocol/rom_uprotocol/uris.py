# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""uProtocol URIs of the RoM data path (numbers live in rom_uprotocol/contract.py)."""
from typing import Optional

from uprotocol.v1.uri_pb2 import UUri

from . import config, contract


def _authority(authority: Optional[str]) -> str:
    return authority if authority is not None else config.uprotocol().authority


def publisher_uri(authority: Optional[str] = None) -> UUri:
    """uEntity of the VSS uProtocol Client (resource 0 = the entity itself)."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_VSS_PUBLISHER_UE_ID,
                ue_version_major=contract.UP_VSS_PUBLISHER_UE_VERSION)


def battery_temp_topic(authority: Optional[str] = None) -> UUri:
    """Topic the guardian subscribes to: up://<authority>/1001/1/8001."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_VSS_PUBLISHER_UE_ID,
                ue_version_major=contract.UP_VSS_PUBLISHER_UE_VERSION,
                resource_id=contract.UP_RESOURCE_BATTERY_TEMP)


def guardian_uri(authority: Optional[str] = None) -> UUri:
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_GUARDIAN_UE_ID,
                ue_version_major=contract.UP_GUARDIAN_UE_VERSION)


def battery_cells_topic(authority: Optional[str] = None) -> UUri:
    """Topic of the cell temperatures (guardian input): up://<authority>/1001/1/8002."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_VSS_PUBLISHER_UE_ID,
                ue_version_major=contract.UP_VSS_PUBLISHER_UE_VERSION,
                resource_id=contract.UP_RESOURCE_BATTERY_CELLS)


def guardian_fault_topic(authority: Optional[str] = None) -> UUri:
    """Topic of the guardian fault events (DFM reporter input): up://<authority>/1002/1/8003."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_GUARDIAN_UE_ID,
                ue_version_major=contract.UP_GUARDIAN_UE_VERSION,
                resource_id=contract.UP_RESOURCE_GUARDIAN_FAULT)


def heartbeat_topic(authority: Optional[str] = None) -> UUri:
    """Topic of the heartbeats: up://<authority>/1001/1/8004."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_VSS_PUBLISHER_UE_ID,
                ue_version_major=contract.UP_VSS_PUBLISHER_UE_VERSION,
                resource_id=contract.UP_RESOURCE_HEARTBEAT)


def campaign_runner_uri(authority: Optional[str] = None) -> UUri:
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_CAMPAIGN_RUNNER_UE_ID,
                ue_version_major=contract.UP_CAMPAIGN_RUNNER_UE_VERSION)


def campaign_event_topic(authority: Optional[str] = None) -> UUri:
    """Topic of the campaign events (evidence markers): up://<authority>/1003/1/8005."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_CAMPAIGN_RUNNER_UE_ID,
                ue_version_major=contract.UP_CAMPAIGN_RUNNER_UE_VERSION,
                resource_id=contract.UP_RESOURCE_CAMPAIGN_EVENT)


def guardian_state_topic(authority: Optional[str] = None) -> UUri:
    """Topic of the guardian state: up://<authority>/1002/1/8006."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_GUARDIAN_UE_ID,
                ue_version_major=contract.UP_GUARDIAN_UE_VERSION,
                resource_id=contract.UP_RESOURCE_GUARDIAN_STATE)


def evidence_collector_uri(authority: Optional[str] = None) -> UUri:
    """uEntity of the evidence collector (a listener only)."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_EVIDENCE_COLLECTOR_UE_ID, ue_version_major=1)


def simulator_uri(authority: Optional[str] = None) -> UUri:
    """uEntity of the simulator's cooling actuator (a listener only)."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_SIMULATOR_UE_ID, ue_version_major=1)


def monitor_uri(authority: Optional[str] = None) -> UUri:
    """uEntity of the rom-up-monitor tool (a listener only, never published as a source)."""
    return UUri(authority_name=_authority(authority), ue_id=contract.UP_MONITOR_UE_ID, ue_version_major=1)
