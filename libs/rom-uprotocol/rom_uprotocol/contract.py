# Made with Claude (Claude Code, Anthropic) — RoM "rom_uprotocol" library.
"""uProtocol contract of the RoM data path: entity IDs, topic resources and payloads.

    up://<UP_AUTHORITY>/1001/1/8001   battery temperature Max   (VSS uProtocol Client)   build_/parse_signal_msg
    up://<UP_AUTHORITY>/1001/1/8002   battery cell temperatures (VSS uProtocol Client)   build_/parse_cells_msg
    up://<UP_AUTHORITY>/1002/1/8003   guardian fault events     (guardian -> DFM)         build_/parse_fault_event

Authority from env, see config.uprotocol(). All payloads are UPAYLOAD_FORMAT_JSON.
"""
import json
from dataclasses import asdict, dataclass
from typing import Dict, Mapping, Optional

from rom_common.contracts import FAULT_CODES, N_CELLS, ContractError, _is_number

__all__ = ["ContractError", "SignalMsg", "build_signal_msg", "parse_signal_msg", "CellsMsg", "build_cells_msg",
           "parse_cells_msg", "FaultEvent", "build_fault_event", "parse_fault_event", "FAULT_STAGES"]

UP_VSS_PUBLISHER_UE_ID = 0x1001          # uEntity "VSS uProtocol Client", instance 0
UP_VSS_PUBLISHER_UE_VERSION = 1
UP_RESOURCE_BATTERY_TEMP = 0x8001        # topic: battery temperature (publish range 0x8000-0xFFFE)
UP_RESOURCE_BATTERY_CELLS = 0x8002       # topic: battery cell temperatures (the guardian's input)
UP_GUARDIAN_UE_ID = 0x1002               # uEntity "Battery Thermal Guardian"
UP_GUARDIAN_UE_VERSION = 1
UP_RESOURCE_GUARDIAN_FAULT = 0x8003      # topic: guardian fault events (FAILED / PASSED edges for the DFM)
UP_MONITOR_UE_ID = 0x10FF                # uEntity of the rom-up-monitor tool


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


def _load_object(payload) -> dict:
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as e:
        raise ContractError(f"invalid_json: {e}") from e
    if not isinstance(data, dict):
        raise ContractError("not_an_object")
    return data


def build_cells_msg(cells: Mapping[int, float], seq: int, ts_ms: int, source_ts_ms: int,
                    run_id: Optional[str] = None) -> bytes:
    """uProtocol payload on UP_RESOURCE_BATTERY_CELLS: the cells of ONE source update, keyed "1".."4".

    A cell that was not written in that update is absent: that is how a single-cell dropout shows up.
    run_id is the campaign run the publisher was told about (POST /run), or null.
    """
    return json.dumps(
        {"cells": {str(c): v for c, v in sorted(cells.items())}, "seq": seq, "ts_ms": ts_ms,
         "source_ts_ms": source_ts_ms, "run_id": run_id},
        separators=(",", ":"),
    ).encode()


@dataclass(frozen=True)
class CellsMsg:
    cells: Dict[int, float]
    seq: int
    ts_ms: int
    source_ts_ms: int
    run_id: Optional[str] = None


def parse_cells_msg(payload: "bytes | str") -> CellsMsg:
    """Parse + validate a cell temperature payload. Raises ContractError."""
    data = _load_object(payload)
    raw = data.get("cells")
    if not isinstance(raw, dict) or not raw:
        raise ContractError("cells_missing")
    cells = {}
    for key, value in raw.items():
        if not (isinstance(key, str) and key.isdigit() and 1 <= int(key) <= N_CELLS):
            raise ContractError(f"bad_cell: {key}")
        if not _is_number(value):
            raise ContractError(f"cell_value_not_a_number: {key}")
        cells[int(key)] = float(value)
    if not all(_is_number(data.get(k)) for k in ("seq", "ts_ms", "source_ts_ms")):
        raise ContractError("seq_or_ts_not_a_number")
    run_id = data.get("run_id")
    if run_id is not None and not isinstance(run_id, str):
        raise ContractError("run_id_not_a_string")
    return CellsMsg(cells, int(data["seq"]), int(data["ts_ms"]), int(data["source_ts_ms"]), run_id)


FAULT_STAGES = ("FAILED", "PASSED")


@dataclass(frozen=True)
class FaultEvent:
    """One edge of one DFM fault. Every field but code / stage / ts_ms may be None.

    cell      the cell a sensor fault belongs to (hottest cell for imbalance), None for pack faults
    temp_c    pack temperature (max of the valid cells) when the edge happened
    cells     all cell values at that moment, "31.2,30.1,,29.9" (cell 1..4, empty = no value)
    seq / msg_id / run_id   the cell message that triggered the edge: correlation for the evidence chain
    """
    code: str
    stage: str
    ts_ms: int
    cell: Optional[int] = None
    temp_c: Optional[float] = None
    cells: str = ""
    reason: str = ""
    seq: Optional[int] = None
    msg_id: Optional[str] = None
    run_id: Optional[str] = None

    def environment_data(self) -> Dict[str, str]:
        """The DFM record's environment data (strings), keys as in services/dfm/README.md."""
        fields = {"cell": self.cell, "temp_c": self.temp_c, "cells": self.cells, "reason": self.reason,
                  "seq": self.seq, "msg_id": self.msg_id, "ts_ms": self.ts_ms, "run_id": self.run_id}
        return {k: str(v) for k, v in fields.items() if v is not None and v != ""}


def build_fault_event(event: FaultEvent) -> bytes:
    if event.code not in FAULT_CODES:
        raise ContractError(f"unknown_fault_code: {event.code}")
    if event.stage not in FAULT_STAGES:
        raise ContractError(f"unknown_stage: {event.stage}")
    return json.dumps(asdict(event), separators=(",", ":")).encode()


def parse_fault_event(payload: "bytes | str") -> FaultEvent:
    """Parse + validate a guardian fault event. Raises ContractError."""
    data = _load_object(payload)
    if data.get("code") not in FAULT_CODES:
        raise ContractError(f"unknown_fault_code: {data.get('code')}")
    if data.get("stage") not in FAULT_STAGES:
        raise ContractError(f"unknown_stage: {data.get('stage')}")
    if not _is_number(data.get("ts_ms")):
        raise ContractError("ts_not_a_number")
    for key in ("cell", "seq"):
        if data.get(key) is not None and not (_is_number(data[key]) and float(data[key]).is_integer()):
            raise ContractError(f"{key}_not_an_integer")
    if data.get("temp_c") is not None and not _is_number(data["temp_c"]):
        raise ContractError("temp_c_not_a_number")
    return FaultEvent(
        code=data["code"], stage=data["stage"], ts_ms=int(data["ts_ms"]),
        cell=None if data.get("cell") is None else int(data["cell"]),
        temp_c=None if data.get("temp_c") is None else float(data["temp_c"]),
        cells=str(data.get("cells") or ""), reason=str(data.get("reason") or ""),
        seq=None if data.get("seq") is None else int(data["seq"]),
        msg_id=data.get("msg_id"), run_id=data.get("run_id"),
    )
