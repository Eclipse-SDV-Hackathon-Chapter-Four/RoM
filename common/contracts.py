# Made with Claude (Claude Code, Anthropic) — shared RoM "common" module, used by all components.
"""Single source of truth in code for contracts/README.md: VSS path, MQTT topics,
guardian states/reasons, and payload build/parse helpers with validation."""
import json
import math
from dataclasses import dataclass
from typing import Any, Optional

# --- VSS (KUKSA) -----------------------------------------------------------
VSS_BATTERY_TEMP = "Vehicle.Powertrain.TractionBattery.Temperature.Max"

# --- MQTT topics -----------------------------------------------------------
TOPIC_SENSOR_TEMP = "rom/sensor/battery/temp"          # QoS 0, no retain
TOPIC_SENSOR_STATUS = "rom/sensor/battery/status"      # QoS 1, retain (LWT)
TOPIC_DISPLAY_CMD = "rom/actuator/display/cmd"         # QoS 1, retain

QOS_SENSOR_TEMP = 0
QOS_SENSOR_STATUS = 1
QOS_DISPLAY_CMD = 1

# --- uProtocol (VSS publisher -> guardian, Zenoh transport) ----------------
# Topic URI: up://<UP_AUTHORITY>/1001/1/8001  (authority from env, see config.uprotocol())
UP_VSS_PUBLISHER_UE_ID = 0x1001          # uEntity "VSS uProtocol Publisher", instance 0
UP_VSS_PUBLISHER_UE_VERSION = 1
UP_RESOURCE_BATTERY_TEMP = 0x8001        # topic: battery temperature (publish range 0x8000-0xFFFE)
UP_GUARDIAN_UE_ID = 0x1002               # uEntity "Battery Thermal Guardian"
UP_GUARDIAN_UE_VERSION = 1

# --- Guardian states and reasons -------------------------------------------
CLEAR = "CLEAR"
MONITORING = "MONITORING"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
SENSOR_FAULT = "SENSOR_FAULT"
STATES = (CLEAR, MONITORING, WARNING, CRITICAL, SENSOR_FAULT)

REASON_TEMP_ABOVE_WARN = "TEMP_ABOVE_WARN"
REASON_TEMP_ABOVE_CRIT = "TEMP_ABOVE_CRIT"
REASON_STALE = "STALE"
REASON_STUCK = "STUCK"
REASON_OUT_OF_RANGE = "OUT_OF_RANGE"


class ContractError(ValueError):
    """Payload does not satisfy the contract (log as event=rejected)."""


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def build_sensor_msg(device_id: str, seq: int, ts_ms: int, temp_c: float) -> str:
    return json.dumps(
        {"device_id": device_id, "seq": seq, "ts_ms": ts_ms, "temp_c": temp_c},
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class SensorMsg:
    device_id: str
    seq: int
    ts_ms: int
    temp_c: float


def parse_sensor_msg(payload: "bytes | str") -> SensorMsg:
    """Parse + validate a rom/sensor/battery/temp payload. Raises ContractError."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as e:
        raise ContractError(f"invalid_json: {e}") from e
    if not isinstance(data, dict):
        raise ContractError("not_an_object")
    if not _is_number(data.get("temp_c")):
        raise ContractError("temp_c_not_a_number")
    seq, ts = data.get("seq", 0), data.get("ts_ms", 0)
    if not _is_number(seq) or not _is_number(ts):
        raise ContractError("seq_or_ts_not_a_number")
    return SensorMsg(
        device_id=str(data.get("device_id", "unknown")),
        seq=int(seq),
        ts_ms=int(ts),
        temp_c=float(data["temp_c"]),
    )


def build_signal_msg(vss_path: str, value: float, seq: int, ts_ms: int, source_ts_ms: int) -> bytes:
    """uProtocol payload (UPAYLOAD_FORMAT_JSON) on UP_RESOURCE_BATTERY_TEMP.

    ts_ms = when the publisher sent it, source_ts_ms = when the value reached the publisher from KUKSA.
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


def build_display_cmd(state: str, temp_c: Optional[float], reason: str, seq: int, ts_ms: int) -> str:
    if state not in STATES:
        raise ContractError(f"unknown_state: {state}")
    return json.dumps(
        {"state": state, "temp_c": temp_c, "reason": reason, "seq": seq, "ts_ms": ts_ms},
        separators=(",", ":"),
    )


def parse_display_cmd(payload: "bytes | str") -> dict:
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as e:
        raise ContractError(f"invalid_json: {e}") from e
    if not isinstance(data, dict) or data.get("state") not in STATES:
        raise ContractError("invalid_display_cmd")
    return data
