import type {
  BatteryInfo,
  CellInfo,
  CellStatus,
  DashboardData,
  GuardianEvent,
  GuardianState,
  HistoryPoint,
  SourceInfo,
  SourceStatus,
} from "../types/dashboard";

/**
 * Turns the raw bus messages recorded by the Evidence Collector (GET /events) into the normalized DashboardData.
 * It DISPLAYS what the real Guardian decided and never recomputes it: the pack state, its reason, the pack temperature
 * and the hottest cell come from the Guardian's state events; a cell is faulty only while a Guardian fault event
 * (FAILED, not yet PASSED) says so. Message shapes (libs/rom-uprotocol/rom_uprotocol/contract.py):
 *   cells      {"cells": {"1": 26.8, ...}, "seq", "ts_ms", "source_ts_ms"}  only the cells written in that update
 *   state      {"state", "previous", "reason", "ts_ms", "temp_c", "cell", "cells": "26.8,29.5,28.5,27.7", "seq"}
 *   fault      {"code", "stage": "FAILED"|"PASSED", "ts_ms", "cell", "reason", ...}
 *   heartbeat  {"component", "status": "ok"|"down", "seq", "ts_ms"}
 */
export interface RawEvent {
  line: number;
  rx_ts_ms: number;
  topic: string;
  payload: unknown;
  rejected?: string;
}

const N_CELLS = 4;
const WARN_C = 38; // the Guardian's default WARN_C / CRIT_C (rom_common.config); the events do not carry them
const CRIT_C = 45;
const HISTORY_POINTS = 240;
const MAX_EVENTS = 40;
const FRESH_MS = 2000; // a cell counts as "in the last message set" if it was written within the Guardian's stale window
const HEARTBEAT_STALE_MS = 3000; // heartbeats come every 0.5 s
const DEVICE_HINT = "adapter chip heartbeat";

const GUARDIAN_STATES: GuardianState[] = ["CLEAR", "MONITORING", "WARNING", "CRITICAL", "MITIGATING", "SENSOR_FAULT"];

const FAULT_SIGNAL_STALE = "battery_guardian.signal_stale";
const HEARTBEAT_FAULTS: Record<string, string> = {
  "uP link lost": "battery_guardian.uprotocol_lost",
  "KUKSA down": "battery_guardian.databroker_down",
  "adapter down": "battery_guardian.adapter_down",
  "sim down": "battery_guardian.simulator_down",
  "chip silent": "battery_guardian.chip_silent",
};
/** DFM code behind a Guardian state row (tooltip). */
const STATE_CODE: Record<string, string> = {
  "WARNING|getting hot": "battery_guardian.over_temp_warning",
  "CRITICAL|too hot": "battery_guardian.over_temp_critical",
  "CRITICAL|mitigation failed": "battery_guardian.mitigation_failed",
  "SENSOR_FAULT|stale signal": FAULT_SIGNAL_STALE,
};
/** Faults whose start is already a Guardian state row; they get no separate row (same rule as the mock). */
const STATE_EXPLAINED = new Set([
  "battery_guardian.over_temp_warning",
  "battery_guardian.over_temp_critical",
  "battery_guardian.mitigation_failed",
  FAULT_SIGNAL_STALE,
  ...Object.values(HEARTBEAT_FAULTS),
]);
const KIND_REASON: Record<string, string> = {
  signal_stale: "stale signal",
  signal_stuck: "stuck signal",
  out_of_range: "out of range",
};

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const iso = (ms: number) => new Date(ms).toISOString();
const cellOfCode = (code: string): number | null => {
  const m = /^battery_guardian\.cell(\d)\./.exec(code);
  return m ? Number(m[1]) : null;
};
const reasonOfCode = (code: string): string =>
  code.endsWith(".cell_imbalance") ? "cell imbalance" : KIND_REASON[code.slice(code.lastIndexOf(".") + 1)] ?? code.slice(code.lastIndexOf(".") + 1);

export class LiveModel {
  private value: Record<number, number> = {}; // latest reading per cell (held between its updates)
  private lastRx: Record<number, number> = {}; // payload ts_ms of that reading
  private lastTrusted: Record<number, number> = {}; // latest reading taken while the cell had no fault
  private faults = new Map<string, number | null>(); // active DFM codes -> cell
  private faultReason = new Map<string, string>();
  private guardian: { state: GuardianState; reason: string; temp: number | null; cell: number | null } = {
    state: "CLEAR",
    reason: "waiting for the Guardian",
    temp: null,
    cell: null,
  };
  private lastKey: string | null = null;
  private heartbeats = new Map<string, { status: string; rx: number }>();
  private seq = 0;
  private latency: number | null = null;
  private lastEventRx: number | null = null;
  private history: HistoryPoint[] = [];
  private events: GuardianEvent[] = [];
  rejected = 0;

  ingest(e: RawEvent): void {
    this.lastEventRx = e.rx_ts_ms;
    if (e.rejected || !isObj(e.payload)) {
      this.rejected++;
      return;
    }
    const p = e.payload;
    switch (e.topic) {
      case "cells":
        return this.onCells(e, p);
      case "state":
        return this.onState(e, p);
      case "fault":
        return this.onFault(e, p);
      case "heartbeat": {
        const component = p.component;
        if (typeof component === "string" && typeof p.status === "string") this.heartbeats.set(component, { status: p.status, rx: e.rx_ts_ms });
        return;
      }
      default:
        return; // campaign markers etc.: not shown
    }
  }

  private ownKind(cell: number): string | null {
    for (const [code, c] of this.faults) if (cellOfCode(code) === cell && c === cell) return code.slice(code.lastIndexOf(".") + 1);
    return null;
  }

  private onCells(e: RawEvent, p: Record<string, unknown>): void {
    const ts = num(p.ts_ms);
    if (!isObj(p.cells) || ts === null) {
      this.rejected++;
      return;
    }
    for (const [k, v] of Object.entries(p.cells)) {
      const c = Number(k);
      const val = num(v);
      if (!(c >= 1 && c <= N_CELLS) || val === null) continue;
      this.value[c] = val;
      this.lastRx[c] = ts;
      if (this.ownKind(c) === null && this.guardian.state !== "SENSOR_FAULT") this.lastTrusted[c] = val;
    }
    const seq = num(p.seq);
    if (seq !== null) this.seq = seq;
    const src = num(p.source_ts_ms);
    this.latency = src === null ? null : Math.max(0, e.rx_ts_ms - src);

    // one chart point per message: the held value of every cell the Guardian currently trusts, null otherwise
    const point: HistoryPoint = { timestamp: iso(ts), cells: {}, pack_max_c: this.packMax().temp };
    for (let c = 1; c <= N_CELLS; c++) point.cells[c] = this.statusOf(c) === "OK" ? this.value[c] ?? null : null;
    this.history.push(point);
    if (this.history.length > HISTORY_POINTS) this.history.shift();
  }

  private onState(e: RawEvent, p: Record<string, unknown>): void {
    const state = p.state as GuardianState;
    const previous = p.previous as GuardianState;
    const ts = num(p.ts_ms);
    if (!GUARDIAN_STATES.includes(state) || ts === null) {
      this.rejected++;
      return;
    }
    const reason = typeof p.reason === "string" ? p.reason : "";
    this.guardian = { state, reason, temp: num(p.temp_c), cell: num(p.cell) };
    // A row only for a real change: a new state, or a new reason in the same state. The periodic repeat is not an event.
    const key = `${state}|${reason}`;
    const changed = this.lastKey === null ? state !== previous : key !== this.lastKey;
    this.lastKey = key;
    if (!changed) return;
    const code = STATE_CODE[key] ?? (state === "SENSOR_FAULT" ? HEARTBEAT_FAULTS[reason] : undefined);
    this.addEvent({ id: e.line, kind: "state", timestamp: iso(ts), state, reason, code });
  }

  private onFault(e: RawEvent, p: Record<string, unknown>): void {
    const code = p.code;
    const ts = num(p.ts_ms);
    if (typeof code !== "string" || ts === null || (p.stage !== "FAILED" && p.stage !== "PASSED")) {
      this.rejected++;
      return;
    }
    const cellField = num(p.cell);
    const reasonText = typeof p.reason === "string" && p.reason && p.reason !== "cleared" ? p.reason : reasonOfCode(code);
    if (p.stage === "FAILED") {
      this.faults.set(code, cellField);
      this.faultReason.set(code, reasonText);
    } else {
      this.faults.delete(code);
    }
    if (STATE_EXPLAINED.has(code)) return;
    const cell = cellOfCode(code); // cell_imbalance carries the hottest cell but is a pack fault
    this.addEvent({
      id: e.line,
      kind: "fault",
      timestamp: iso(ts),
      stage: p.stage,
      cell,
      reason: p.stage === "FAILED" ? reasonText : `${this.faultReason.get(code) ?? reasonOfCode(code)} cleared`,
      code,
    });
  }

  private addEvent(ev: GuardianEvent): void {
    this.events.unshift(ev);
    if (this.events.length > MAX_EVENTS) this.events.length = MAX_EVENTS;
  }

  /** Pack temperature as the Guardian reported it. Not shown while the Guardian itself is in SENSOR_FAULT / has no data. */
  private packMax(): { temp: number | null; cell: number | null } {
    const g = this.guardian;
    if (g.state === "SENSOR_FAULT" || g.state === "CLEAR" || g.temp === null) return { temp: null, cell: null };
    return { temp: g.temp, cell: g.cell };
  }

  private blindCode(): string | null {
    for (const code of this.faults.keys()) if (code === FAULT_SIGNAL_STALE || Object.values(HEARTBEAT_FAULTS).includes(code)) return code;
    return null;
  }

  private statusOf(c: number): CellStatus {
    if (this.value[c] === undefined) return "NO_DATA";
    const kind = this.ownKind(c);
    if (kind === "signal_stale") return "STALE";
    if (kind === "signal_stuck") return "STUCK";
    if (kind === "out_of_range") return "OUT_OF_RANGE";
    if (this.guardian.state === "SENSOR_FAULT") return this.faults.has(FAULT_SIGNAL_STALE) || this.guardian.reason === "stale signal" ? "STALE" : "UNTRUSTED";
    return "OK";
  }

  private source(component: string, now: number): SourceStatus {
    const hb = this.heartbeats.get(component);
    if (!hb || now - hb.rx > HEARTBEAT_STALE_MS) return "NO_HEARTBEAT";
    return hb.status === "ok" ? "ALIVE" : "DOWN";
  }

  snapshot(now: number): DashboardData {
    const pack = this.packMax();
    const cells: CellInfo[] = [];
    for (let c = 1; c <= N_CELLS; c++) {
      const status = this.statusOf(c);
      const own = [...this.faults.keys()].find((code) => cellOfCode(code) === c);
      cells.push({
        id: c,
        temperature_c: status === "OK" ? this.value[c] ?? null : null,
        status,
        source: c === 1 ? "HW" : "SIM",
        last_valid_c: this.lastTrusted[c] ?? null,
        last_update: this.lastRx[c] === undefined ? null : iso(this.lastRx[c]),
        in_pack: status === "OK",
        fault_code: status === "OK" ? null : own ?? this.blindCode(),
      });
    }
    const battery: BatteryInfo = { cells, pack_max_c: pack.temp, pack_max_cell: pack.cell, warn_c: WARN_C, crit_c: CRIT_C };
    const sources: SourceInfo[] = [
      { id: "az3166", name: "AZ3166", detail: DEVICE_HINT, cells: [1], status: this.source("chip", now) },
      { id: "simulator", name: "Simulator", detail: "simulator heartbeat", cells: [2, 3, 4], status: this.source("simulator", now) },
    ];
    const fresh = Object.keys(this.lastRx).map(Number).filter((c) => now - this.lastRx[c] <= FRESH_MS).sort();
    return {
      timestamp: iso(now),
      battery,
      guardian: { state: this.guardian.state, reason: this.guardian.reason },
      sources,
      message: {
        seq: this.seq,
        latency_ms: this.latency,
        received_at: this.lastEventRx === null ? null : iso(this.lastEventRx),
        cells_reported: fresh,
        total_cells: N_CELLS,
      },
      history: [...this.history],
      events: [...this.events],
    };
  }
}
