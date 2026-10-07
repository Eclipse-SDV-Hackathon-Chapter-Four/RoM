# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
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
TOPIC_GUARDIAN_FAULT = "rom/guardian/fault"            # QoS 1, no retain (-> DFM)

QOS_SENSOR_TEMP = 0
QOS_SENSOR_STATUS = 1
QOS_DISPLAY_CMD = 1
QOS_GUARDIAN_FAULT = 1

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

# --- Guardian faults -> DFM (names = services/dfm/catalog/battery_guardian.json) ---
FAULT_OVER_TEMP_WARNING = "BatteryOverTempWarning"
FAULT_OVER_TEMP_CRITICAL = "BatteryOverTempCritical"
FAULT_MITIGATION_FAILED = "BatteryMitigationFailed"
FAULT_SIGNAL_STALE = "BatteryTempSignalStale"
FAULT_SIGNAL_STUCK = "BatteryTempSignalStuck"
FAULT_OUT_OF_RANGE = "BatteryTempOutOfRange"
FAULTS = (FAULT_OVER_TEMP_WARNING, FAULT_OVER_TEMP_CRITICAL, FAULT_MITIGATION_FAILED,
          FAULT_SIGNAL_STALE, FAULT_SIGNAL_STUCK, FAULT_OUT_OF_RANGE)
FAILED, PASSED = "Failed", "Passed"


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


def build_fault_event(fault: str, stage: str, ts_ms: int, temp_c: Optional[float], reason: str,
                      seq: Optional[int], msg_id: Optional[str]) -> str:
    """Payload for TOPIC_GUARDIAN_FAULT; services/dfm turns it into a fault-lib record."""
    if fault not in FAULTS or stage not in (FAILED, PASSED):
        raise ContractError(f"unknown_fault_or_stage: {fault} {stage}")
    return json.dumps(
        {"fault": fault, "stage": stage, "ts_ms": ts_ms, "temp_c": temp_c, "reason": reason,
         "seq": seq, "msg_id": msg_id},
        separators=(",", ":"),
    )
