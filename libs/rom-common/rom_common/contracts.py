# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
"""Single source of truth in code for contracts/README.md: VSS path, MQTT topics,
guardian states/reasons, and payload build/parse helpers with validation."""
import json
import math
from dataclasses import dataclass
from typing import Any, Optional

# --- VSS (KUKSA) -----------------------------------------------------------
VSS_BATTERY_TEMP = "Vehicle.Powertrain.TractionBattery.Temperature.Max"
# Custom overlay (infra/vss/rom_overlay.json): one temperature per battery cell, cells are numbered from 1.
VSS_CELL_TEMPS = tuple(f"Vehicle.Powertrain.TractionBattery.Cells.Cell{i}.Temperature" for i in range(1, 5))
N_CELLS = len(VSS_CELL_TEMPS)

# Heartbeats (infra/vss/rom_overlay.json): counters written into KUKSA by the producers; the client forwards them.
VSS_HEARTBEAT_CHIP = "Vehicle.RoM.Heartbeat.Chip"
VSS_HEARTBEAT_ADAPTER = "Vehicle.RoM.Heartbeat.Adapter"
VSS_HEARTBEAT_SIMULATOR = "Vehicle.RoM.Heartbeat.Simulator"

# --- Heartbeat components (what the guardian can tell apart) ---------------
COMPONENT_UPROTOCOL = "uprotocol"      # vss-uprotocol-client + Zenoh: its own beat on the uProtocol heartbeat topic
COMPONENT_DATABROKER = "databroker"    # KUKSA, probed by the client: status ok | down
COMPONENT_ADAPTER = "adapter"          # MQTT -> KUKSA adapter process
COMPONENT_SIMULATOR = "simulator"      # simulator process
COMPONENT_CHIP = "chip"                # the physical sensor chip (AZ3166), or the simulator's stand-in
HB_OK = "ok"
HB_DOWN = "down"
# Heartbeat counters that travel as KUKSA signals, and which component each one stands for. A counter > 0 is a beat;
# 0 means "reporting down" (the adapter writes it for a chip that stopped sending telemetry).
VSS_HEARTBEAT_COMPONENTS = {
    VSS_HEARTBEAT_CHIP: COMPONENT_CHIP,
    VSS_HEARTBEAT_ADAPTER: COMPONENT_ADAPTER,
    VSS_HEARTBEAT_SIMULATOR: COMPONENT_SIMULATOR,
}
# Guardian reason when a component's heartbeat is gone. At most 21 characters: that is the OLED width.
HEARTBEAT_LOST_REASON = {
    COMPONENT_UPROTOCOL: "uP link lost",
    COMPONENT_DATABROKER: "KUKSA down",
    COMPONENT_ADAPTER: "adapter down",
    COMPONENT_SIMULATOR: "sim down",
    COMPONENT_CHIP: "chip silent",
}
# Which component to blame first when several are gone: the one closest to the guardian.
HEARTBEAT_DIAGNOSIS_ORDER = (COMPONENT_UPROTOCOL, COMPONENT_DATABROKER, COMPONENT_ADAPTER, COMPONENT_SIMULATOR,
                             COMPONENT_CHIP)

# --- MQTT topics -----------------------------------------------------------
TOPIC_SENSOR_TEMP = "rom/sensor/battery/temp"          # QoS 0, no retain
TOPIC_SENSOR_STATUS = "rom/sensor/battery/status"      # QoS 1, retain (LWT)
TOPIC_DISPLAY_CMD = "rom/actuator/display/cmd"         # QoS 1, retain

STATUS_ONLINE = "online"      # payload of TOPIC_SENSOR_STATUS
STATUS_OFFLINE = "offline"    # ... also the MQTT Last Will of the board

QOS_SENSOR_TEMP = 0
QOS_SENSOR_STATUS = 1
QOS_DISPLAY_CMD = 1

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


# --- DFM fault codes (catalog services/dfm/catalog/battery_guardian.json) ----
# The DFM entity path = catalog id = SOVD app id. Pack faults have one code; sensor faults have one code per
# cell, so two broken cells are two independent DFM records. The guardian raises them, the DFM stores them,
# OpenSOVD serves them, campaigns list the ones they expect.
DFM_ENTITY = "battery_guardian"
FAULT_OVER_TEMP_WARNING = f"{DFM_ENTITY}.over_temp_warning"
FAULT_OVER_TEMP_CRITICAL = f"{DFM_ENTITY}.over_temp_critical"
FAULT_MITIGATION_FAILED = f"{DFM_ENTITY}.mitigation_failed"
FAULT_SIGNAL_STALE = f"{DFM_ENTITY}.signal_stale"          # the whole cell stream is silent
FAULT_CELL_IMBALANCE = f"{DFM_ENTITY}.cell_imbalance"
FAULT_LINK_INTEGRITY = f"{DFM_ENTITY}.link_integrity"      # duplicated / reordered cell messages (discarded)
PACK_FAULTS = (FAULT_OVER_TEMP_WARNING, FAULT_OVER_TEMP_CRITICAL, FAULT_MITIGATION_FAILED, FAULT_SIGNAL_STALE,
               FAULT_CELL_IMBALANCE, FAULT_LINK_INTEGRITY)
CELL_FAULT_KINDS = ("signal_stale", "signal_stuck", "out_of_range")   # the cell is left out of the pack state
CELL_DIAG_KINDS = ("rate_implausible",)                              # diagnostic only: the reading is kept
# Heartbeat root causes: the one closest to the guardian is raised (HEARTBEAT_DIAGNOSIS_ORDER), not its symptoms.
HEARTBEAT_FAULTS = {
    COMPONENT_UPROTOCOL: f"{DFM_ENTITY}.uprotocol_lost",
    COMPONENT_DATABROKER: f"{DFM_ENTITY}.databroker_down",
    COMPONENT_ADAPTER: f"{DFM_ENTITY}.adapter_down",
    COMPONENT_SIMULATOR: f"{DFM_ENTITY}.simulator_down",
    COMPONENT_CHIP: f"{DFM_ENTITY}.chip_silent",
}


def cell_fault(cell: int, kind: str) -> str:
    """Per-cell sensor fault code, e.g. cell_fault(2, "signal_stuck") -> battery_guardian.cell2.signal_stuck."""
    if kind not in CELL_FAULT_KINDS + CELL_DIAG_KINDS or not 1 <= cell <= N_CELLS:
        raise ValueError(f"no fault code for cell {cell!r} / {kind!r}")
    return f"{DFM_ENTITY}.cell{cell}.{kind}"


FAULT_CODES = (PACK_FAULTS
               + tuple(cell_fault(c, k) for c in range(1, N_CELLS + 1) for k in CELL_FAULT_KINDS + CELL_DIAG_KINDS)
               + tuple(HEARTBEAT_FAULTS.values()))


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
