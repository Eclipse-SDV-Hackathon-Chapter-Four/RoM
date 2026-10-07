import type {
  BatteryInfo,
  DemoScenario,
  DemoTarget,
  CellInfo,
  CellStatus,
  DashboardData,
  GuardianEvent,
  HistoryPoint,
  SourceInfo,
} from "../types/dashboard";
import {
  CRIT_C,
  FAULT_MITIGATION_FAILED,
  FAULT_OVER_TEMP_CRITICAL,
  FAULT_OVER_TEMP_WARNING,
  FAULT_SIGNAL_STALE,
  MockGuardian,
  N_CELLS,
  STATE_EXPLAINED_CODES,
  WARN_C,
  faultReason,
} from "./mockGuardian";
import { ManualOverride, saneC } from "./mockOverride";

/**
 * Deterministic, loopable demo stream of a 4-cell pack. One row = one simulated cell message; a null entry is a cell
 * that is missing from that message, a row of nulls is "nothing arrived". The cell values are scripted; everything
 * else (pack max, Guardian state and reason, per-cell status, DFM fault edges) is computed by MockGuardian, which
 * applies the same rules as services/guardian. Final-demo topology: cell 1 = AZ3166 board, cells 2-4 = simulator.
 */
type Row = (number | null)[];
interface Segment {
  rows: Row[];
}

const r1 = (x: number) => Math.round(x * 10) / 10;
const ramp = (a: number, b: number, n: number) => Array.from({ length: n }, (_, i) => r1(a + ((b - a) * i) / Math.max(1, n - 1)));

/** Simulator cells sit around a shared background level, each with its own offset and a small wiggle. */
const SIM_OFFSET = [0, -0.8, 0.6, -1.5];
type Override = (k: number, cellIdx: number, natural: number) => number | null | undefined;

let tick = 0; // global tick, only used to vary the wiggle
const prev: (number | null)[] = Array(N_CELLS).fill(null);

/** Scripted rows for cell 1 (the board) plus a background level for the simulator cells. */
function rows(cell1: number[], background: number[], override?: Override): Row[] {
  return cell1.map((c1, k) => {
    const row: Row = [];
    for (let i = 0; i < N_CELLS; i++) {
      let v = i === 0 ? c1 : r1(background[k] + SIM_OFFSET[i] + 0.15 * Math.sin(tick * 1.3 + i * 2));
      // A live sensor never repeats a value exactly (the Guardian calls that "stuck"), so nudge equal neighbours.
      if (prev[i] !== null && v === prev[i]) v = r1(v + 0.1);
      const o = override?.(k, i, v);
      const out = o === undefined ? v : o;
      row.push(out);
      if (out !== null) prev[i] = out;
    }
    tick++;
    return row;
  });
}

const wiggle = (base: number, n: number) => Array.from({ length: n }, (_, k) => r1(base + 0.25 * Math.sin(k * 0.9)));

const SEGMENTS: Segment[] = [
  // 1. Normal operation, cell 1 warms up on its own
  { rows: rows([31.0, 31.4, 31.9, 32.3, 32.9, 33.4, 34.0, 34.6, 35.3, 36.0, 36.6, 37.2], ramp(30.8, 32.4, 12)) },
  // 2. Cell 1 crosses 38 °C -> WARNING
  { rows: rows([38.2, 39.0, 39.5, 40.3, 41.0, 41.9, 43.0], ramp(32.6, 34.0, 7)) },
  // 3. Cell 1 crosses 45 °C -> CRITICAL "too hot" -> MITIGATING (requested, in progress) -> CRITICAL "mitigation failed"
  {
    rows: rows([45.2, 46.0, 46.6, 47.1, 47.5, 47.9, 48.2, 48.4, 48.6, 48.4, 47.0, 45.5, 44.0, 41.0], ramp(34.4, 36.5, 14)),
  },
  // 4. Cooling: pack drops below 38 °C -> MONITORING
  { rows: rows([39.5, 38.6, 37.0, 35.5, 34.0, 33.0, 32.2, 31.8, 31.5, 31.3, 31.1, 31.0], ramp(36.0, 31.0, 12)) },
  // 5. Single-cell sensor faults. The pack stays on the healthy cells and never becomes SENSOR_FAULT.
  //    cell 2 frozen (k 0-14), cell 3 drops out of the message (k 4-12), cell 4 reads 175 °C (k 16-19)
  {
    rows: (() => {
      let frozen: number | undefined;
      return rows(wiggle(31.3, 22), Array(22).fill(31.2), (k, i, v) => {
        if (i === 1 && k <= 14) return (frozen ??= v);
        if (i === 2 && k >= 4 && k <= 12) return null;
        if (i === 3 && k >= 16 && k <= 19) return 175;
        return undefined;
      });
    })(),
  },
  // 6. Whole stream lost: nothing arrives. After 2 s the Guardian can trust no cell -> SENSOR_FAULT "stale signal"
  { rows: Array.from({ length: 8 }, (): Row => Array(N_CELLS).fill(null)) },
  // 7. Recovery
  { rows: rows(wiggle(31.0, 6), Array(6).fill(31.0)) },
];

const FLAT: Row[] = SEGMENTS.flatMap((s) => s.rows);
const HISTORY_POINTS = 120;
const MAX_EVENTS = 40;
const DEVICE_ID = "az3166-01";
const BOARD_CELLS = [1];
const SIM_CELLS = [2, 3, 4];

/** Pack-level DFM code behind a Guardian state row, shown as a tooltip. */
const STATE_CODE: Record<string, string> = {
  "WARNING|getting hot": FAULT_OVER_TEMP_WARNING,
  "CRITICAL|too hot": FAULT_OVER_TEMP_CRITICAL,
  "CRITICAL|mitigation failed": FAULT_MITIGATION_FAILED,
  "SENSOR_FAULT|stale signal": FAULT_SIGNAL_STALE,
};

export class TimelineEngine {
  private index = 0;
  private seq = 1800;
  private latency = 90;
  private clock = 0; // simulated seconds, drives the Guardian rules (stale 2 s, stuck 10 s, mitigation 5 s)
  private readonly dt: number;
  private guardian = new MockGuardian();
  private lastKey = "";
  private nextId = 1;
  private lastReported: number[] = [1, 2, 3, 4];
  private manual: ManualOverride | null = null;
  private lastVal: (number | null)[] = Array(N_CELLS).fill(null); // last value each cell reported
  private lastSane: (number | null)[] = Array(N_CELLS).fill(null); // last plausible one (start of a cool-down)
  private lastValid: Record<number, number | null> = {};
  private lastUpdate: Record<number, string> = {};
  private history: HistoryPoint[] = [];
  private events: GuardianEvent[] = [];

  constructor(now: Date, tickMs: number) {
    this.dt = tickMs / 1000;
    // A minute of calm history so the chart is not empty, run through the Guardian so its monitors are warm.
    const prefill = Math.round(60_000 / tickMs);
    for (let i = prefill; i > 0; i--) {
      const cells = [30.9, 30.2, 31.5, 29.5].map((b, c) => r1(b + 0.25 * Math.sin(i / 3 + c * 1.7)));
      this.clock += this.dt;
      const msg: Record<number, number> = {};
      cells.forEach((v, c) => (msg[c + 1] = v));
      this.guardian.update(this.clock, msg);
      const ts = new Date(now.getTime() - i * tickMs).toISOString();
      for (const c of Object.keys(msg).map(Number)) {
        this.lastValid[c] = msg[c];
        this.lastUpdate[c] = ts;
        this.lastVal[c - 1] = this.lastSane[c - 1] = msg[c];
      }
      this.history.push({
        timestamp: ts,
        cells: { ...msg },
        pack_max_c: this.guardian.packMax().temp,
      });
    }
    this.lastKey = `${this.guardian.state}|${this.guardian.reason}`;
    this.events.push({
      id: this.nextId++,
      kind: "state",
      timestamp: new Date(now.getTime() - 60_000).toISOString(),
      state: this.guardian.state,
      reason: this.guardian.reason,
    });
  }

  /** Manual override from the demo controls: from now on the cell values come from the controls, not the loop. */
  applyDemo(target: DemoTarget, scenario: DemoScenario): void {
    this.manual ??= new ManualOverride();
    this.manual.apply(target, scenario, this.lastVal, this.guardian.packMax().cell);
  }

  /** Drop the override and restart the automatic loop from its calm beginning. */
  resume(): void {
    this.manual = null;
    this.index = 0;
  }

  /** Advances one message period and returns the resulting snapshot. */
  step(now: Date): DashboardData {
    let row: Row;
    if (this.manual) {
      row = this.manual.row(this.lastVal, this.lastSane);
    } else {
      row = FLAT[this.index];
      this.index = (this.index + 1) % FLAT.length;
    }
    row.forEach((v, i) => {
      if (v === null) return;
      this.lastVal[i] = v;
      if (saneC(v)) this.lastSane[i] = v;
    });
    this.clock += this.dt;
    const timestamp = now.toISOString();

    const msg: Record<number, number> = {};
    row.forEach((v, i) => {
      if (v !== null) msg[i + 1] = v;
    });
    const arrived = Object.keys(msg).length > 0;

    const edges = this.guardian.update(this.clock, arrived ? msg : null);
    const g = this.guardian;
    const pack = g.packMax();

    if (arrived) {
      this.seq += 1;
      this.latency = 80 + ((this.seq * 37) % 41); // 80..120 ms, repeatable
      this.lastReported = Object.keys(msg).map(Number);
    }

    const cells: CellInfo[] = [];
    for (let c = 1; c <= N_CELLS; c++) {
      if (c in msg) this.lastUpdate[c] = timestamp;
      const status = this.statusOf(c);
      if (status === "OK") this.lastValid[c] = g.cells[c].value;
      // a cell's own diagnostic code; during a whole-stream loss the pack-level signal_stale explains every cell
      const code = Object.keys(g.faults).find((k) => g.faults[k] === c && k.includes(`.cell${c}.`)) ?? (g.staleStream ? FAULT_SIGNAL_STALE : null);
      cells.push({
        id: c,
        temperature_c: status === "OK" ? g.cells[c].value : null,
        status,
        source: BOARD_CELLS.includes(c) ? "HW" : "SIM",
        last_valid_c: this.lastValid[c] ?? null,
        last_update: this.lastUpdate[c] ?? null,
        in_pack: status === "OK",
        fault_code: status === "OK" ? null : code,
      });
    }

    if (arrived) {
      const point: HistoryPoint = { timestamp, cells: {}, pack_max_c: pack.temp };
      for (const c of cells) point.cells[c.id] = c.temperature_c;
      this.history.push(point);
      if (this.history.length > HISTORY_POINTS) this.history.shift();
    }

    // Events: a fault row for each diagnostic edge, a Guardian state row when state/reason changes.
    const fresh: GuardianEvent[] = [];
    for (const e of edges) {
      if (STATE_EXPLAINED_CODES.has(e.code)) continue; // already visible as the pack state row
      fresh.push({
        id: this.nextId++,
        kind: "fault",
        timestamp,
        stage: e.stage,
        cell: /\.cell\d\./.test(e.code) ? e.cell : null, // cell_imbalance is a pack fault
        reason: e.stage === "FAILED" ? faultReason(e.code) : `${faultReason(e.code)} cleared`,
        code: e.code,
      });
    }
    const key = `${g.state}|${g.reason}`;
    if (key !== this.lastKey) {
      this.lastKey = key;
      // pushed last, so it ends up on top: the state change is what the viewer should read first
      fresh.push({ id: this.nextId++, kind: "state", timestamp, state: g.state, reason: g.reason, code: STATE_CODE[key] });
    }
    for (const e of fresh) this.events.unshift(e);
    if (this.events.length > MAX_EVENTS) this.events.length = MAX_EVENTS;

    const battery: BatteryInfo = {
      cells,
      pack_max_c: pack.temp,
      pack_max_cell: pack.cell,
      warn_c: WARN_C,
      crit_c: CRIT_C,
    };

    return {
      timestamp,
      battery,
      guardian: { state: g.state, reason: g.reason },
      sources: this.sources(),
      message: { seq: this.seq, latency_ms: this.latency, cells_reported: [...this.lastReported], total_cells: N_CELLS },
      history: [...this.history],
      events: [...this.events],
      demo_override: this.manual ? this.manual.info() : null,
    };
  }

  private statusOf(c: number): CellStatus {
    const g = this.guardian;
    if (g.cells[c].value === null) return "NO_DATA";
    if (g.staleStream) return "STALE";
    switch (g.cellFaults[c]) {
      case "signal_stale":
        return "STALE";
      case "signal_stuck":
        return "STUCK";
      case "out_of_range":
        return "OUT_OF_RANGE";
      default:
        return "OK";
    }
  }

  /** RECEIVING while at least one of the source's cells reached the Guardian within the stale window, else NO_DATA (cause unknown). */
  private sources(): SourceInfo[] {
    const alive = (ids: number[]) => ids.some((c) => this.clock - this.guardian.cells[c].lastRx <= 2);
    return [
      { id: "az3166", name: "AZ3166", detail: DEVICE_ID, cells: BOARD_CELLS, status: alive(BOARD_CELLS) ? "RECEIVING" : "NO_DATA" },
      { id: "simulator", name: "Simulator", detail: "cells 2–4", cells: SIM_CELLS, status: alive(SIM_CELLS) ? "RECEIVING" : "NO_DATA" },
    ];
  }
}
