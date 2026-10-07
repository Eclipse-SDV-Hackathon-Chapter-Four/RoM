# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""uProtocol contract of the RoM data path: entity IDs, topic resources and the VSS signal payload.

Topic URI: up://<UP_AUTHORITY>/1001/1/8001  (authority from env, see config.uprotocol())
"""
import json
from dataclasses import dataclass

from rom_common.contracts import ContractError, _is_number

__all__ = ["ContractError", "SignalMsg", "build_signal_msg", "parse_signal_msg"]

UP_VSS_PUBLISHER_UE_ID = 0x1001          # uEntity "VSS uProtocol Client", instance 0
UP_VSS_PUBLISHER_UE_VERSION = 1
UP_RESOURCE_BATTERY_TEMP = 0x8001        # topic: battery temperature (publish range 0x8000-0xFFFE)
UP_GUARDIAN_UE_ID = 0x1002               # uEntity "Battery Thermal Guardian"
UP_GUARDIAN_UE_VERSION = 1
UP_RESOURCE_GUARDIAN_FAULT = 0x8001      # topic: guardian fault events (Failed/Passed) -> DFM


def build_signal_msg(vss_path: str, value: float, seq: int, ts_ms: int, source_ts_ms: int) -> bytes:
    """uProtocol payload (UPAYLOAD_FORMAT_JSON) on UP_RESOURCE_BATTERY_TEMP.

    ts_ms = when the publisher sent it, source_ts_ms = when the value reached the publisher from its source.
    """
    return json.dumps(
        {"vss_path": vss_path, "value": value, "seq": seq, "ts_ms": ts_ms, "source_ts_ms": source_ts_ms},
        separators=(",", ":"),
    ).encode()


@dataclass(frozen=True)
class SignalMsg:
    vss_path: str
    value: float
    seq: int
    ts_ms: int
    source_ts_ms: int


def parse_signal_msg(payload: "bytes | str") -> SignalMsg:
    """Parse + validate a uProtocol VSS signal payload. Raises ContractError."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as e:
        raise ContractError(f"invalid_json: {e}") from e
    if not isinstance(data, dict):
        raise ContractError("not_an_object")
    if not _is_number(data.get("value")):
        raise ContractError("value_not_a_number")
    if not all(_is_number(data.get(k)) for k in ("seq", "ts_ms", "source_ts_ms")):
        raise ContractError("seq_or_ts_not_a_number")
    return SignalMsg(
        vss_path=str(data.get("vss_path", "")),
        value=float(data["value"]),
        seq=int(data["seq"]),
        ts_ms=int(data["ts_ms"]),
        source_ts_ms=int(data["source_ts_ms"]),
    )
