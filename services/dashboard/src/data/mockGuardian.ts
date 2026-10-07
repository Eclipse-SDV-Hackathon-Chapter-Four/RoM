import type { GuardianState } from "../types/dashboard";

/**
 * Mock-layer replica of the decision rules in services/guardian/guardian/guardian.py (per-cell monitoring, pack
 * temperature = max of the valid cells, SENSOR_FAULT only when no cell can be trusted, DFM fault edges).
 * It exists only so the simulated stream produces the states, reasons and fault codes the real Guardian would
 * produce for the scripted cell values. Nothing in the UI imports it; a real data source replaces it entirely.
 * Heartbeat root causes (uP link lost, KUKSA down, ...) are not modelled.
 */
export const N_CELLS = 4;
export const WARN_C = 38;
export const CRIT_C = 45;
const MIN_C = -40;
const MAX_C = 150;
const STALE_S = 2;
const STUCK_S = 10;
const IMBALANCE_C = 10;
const IMBALANCE_S = 2;
const MITIGATION_TIMEOUT_S = 5;

export type CellFaultKind = "signal_stale" | "signal_stuck" | "out_of_range";

export const DFM_ENTITY = "battery_guardian";
export const FAULT_OVER_TEMP_WARNING = `${DFM_ENTITY}.over_temp_warning`;
export const FAULT_OVER_TEMP_CRITICAL = `${DFM_ENTITY}.over_temp_critical`;
export const FAULT_MITIGATION_FAILED = `${DFM_ENTITY}.mitigation_failed`;
export const FAULT_SIGNAL_STALE = `${DFM_ENTITY}.signal_stale`;
export const FAULT_CELL_IMBALANCE = `${DFM_ENTITY}.cell_imbalance`;
export const cellFaultCode = (cell: number, kind: CellFaultKind) => `${DFM_ENTITY}.cell${cell}.${kind}`;

export const CELL_REASONS: Record<CellFaultKind, string> = {
  signal_stale: "stale signal",
  signal_stuck: "stuck signal",
  out_of_range: "out of range",
};

const THERMAL_FAULTS = [FAULT_OVER_TEMP_WARNING, FAULT_OVER_TEMP_CRITICAL, FAULT_MITIGATION_FAILED];

class CellMonitor {
  value: number | null = null;
  lastRx = 0;
  lastChange = 0;

  feed(now: number, value: number): void {
    if (value !== this.value) this.lastChange = now;
    this.value = value;
    this.lastRx = now;
  }

  fault(now: number, streamStart: number): CellFaultKind | null {
    if (this.value === null) return now - streamStart > STALE_S ? "signal_stale" : null;
    if (now - this.lastRx > STALE_S) return "signal_stale";
    if (!(MIN_C <= this.value && this.value <= MAX_C)) return "out_of_range"; // before stuck: a pinned 200 is out of range
    if (now - this.lastChange > STUCK_S) return "signal_stuck";
    return null;
  }
}

/** Active DFM code -> faulty cell (null for pack faults). */
export type FaultMap = Record<string, number | null>;

export interface FaultEdge {
  code: string;
  stage: "FAILED" | "PASSED";
  cell: number | null;
}

export class MockGuardian {
  state: GuardianState = "CLEAR";
  reason = "no data yet";
  temp: number | null = null;
  hottest: number | null = null;
  staleStream = false;
  cellFaults: Record<number, CellFaultKind | null> = {};
  faults: FaultMap = {};
  /** Latest value of each cell the Guardian has seen (even if it is now judged faulty). */
  readonly cells: Record<number, CellMonitor> = {};

  private firstRx: number | null = null;
  private lastRx = 0;
  private mitigationSince = 0;
  private mitigationFailed = false;
  private imbalanceSince: number | null = null;

  constructor() {
    for (let c = 1; c <= N_CELLS; c++) this.cells[c] = new CellMonitor();
  }

  /** Feed one tick. `cells` = the cells of the message that arrived, null = nothing arrived. Returns the fault edges. */
  update(now: number, cells: Record<number, number> | null): FaultEdge[] {
    if (cells) {
      for (const [c, v] of Object.entries(cells)) this.cells[Number(c)]?.feed(now, v);
      this.lastRx = now;
      if (this.firstRx === null) this.firstRx = now;
    }
    this.staleStream = this.firstRx !== null && now - this.lastRx > STALE_S;

    this.cellFaults = {};
    if (!this.staleStream && this.firstRx !== null) {
      for (let c = 1; c <= N_CELLS; c++) this.cellFaults[c] = this.cells[c].fault(now, this.firstRx);
    }
    const valid: Record<number, number> = {};
    for (let c = 1; c <= N_CELLS; c++) {
      const m = this.cells[c];
      if (m.value !== null && !this.staleStream && !this.cellFaults[c]) valid[c] = m.value;
    }
    const validIds = Object.keys(valid).map(Number);
    if (validIds.length) {
      this.hottest = validIds.reduce((a, b) => (valid[b] > valid[a] ? b : a));
      this.temp = valid[this.hottest];
    }

    const [state, reason] = this.nextState(now, validIds.length > 0);
    if (state === "MITIGATING" && this.state !== "MITIGATING") this.mitigationSince = now;
    this.state = state;
    this.reason = reason;

    const before = this.faults;
    this.faults = this.activeFaults(now, valid);
    return faultEdges(before, this.faults);
  }

  /** Pack temperature of right now: the hottest valid cell, null when no cell can be trusted. */
  packMax(): { temp: number | null; cell: number | null } {
    const hasValid = Object.keys(this.cells).some((k) => {
      const c = Number(k);
      return this.cells[c].value !== null && !this.staleStream && !this.cellFaults[c];
    });
    return hasValid ? { temp: this.temp, cell: this.hottest } : { temp: null, cell: null };
  }

  private nextState(now: number, anyValid: boolean): [GuardianState, string] {
    if (this.firstRx === null) return ["CLEAR", "no data yet"];
    if (this.staleStream) return ["SENSOR_FAULT", "stale signal"];
    if (!anyValid) {
      const kinds = new Set(Object.values(this.cellFaults).filter((k): k is CellFaultKind => !!k));
      return ["SENSOR_FAULT", kinds.size === 1 ? CELL_REASONS[[...kinds][0]] : "no valid cell"];
    }
    const temp = this.temp as number;
    if (temp < WARN_C) {
      this.mitigationFailed = false;
      return ["MONITORING", "temp ok"];
    }
    if (this.state === "MITIGATING") {
      if (now - this.mitigationSince > MITIGATION_TIMEOUT_S) {
        this.mitigationFailed = true;
        return ["CRITICAL", "mitigation failed"];
      }
      return ["MITIGATING", "cooling in progress"];
    }
    if (this.state === "CRITICAL") {
      return this.mitigationFailed ? ["CRITICAL", "mitigation failed"] : ["MITIGATING", "cooling requested"];
    }
    return temp >= CRIT_C ? ["CRITICAL", "too hot"] : ["WARNING", "getting hot"];
  }

  /** DFM codes failing right now. While the input cannot be judged the earlier codes keep their state. */
  private activeFaults(now: number, valid: Record<number, number>): FaultMap {
    if (this.firstRx === null) return {};
    if (this.staleStream) return { ...this.faults, [FAULT_SIGNAL_STALE]: null };

    const active: FaultMap = {};
    for (const [c, kind] of Object.entries(this.cellFaults)) if (kind) active[cellFaultCode(Number(c), kind)] = Number(c);

    const values = Object.values(valid);
    if (!values.length) {
      for (const [code, cell] of Object.entries(this.faults)) if (THERMAL_FAULTS.includes(code)) active[code] = cell;
      this.imbalanceSince = null;
      return active;
    }
    const temp = this.temp as number;
    if (temp >= WARN_C) active[FAULT_OVER_TEMP_WARNING] = this.hottest;
    if (temp >= CRIT_C) active[FAULT_OVER_TEMP_CRITICAL] = this.hottest;
    if (this.state === "CRITICAL" && this.mitigationFailed) active[FAULT_MITIGATION_FAILED] = this.hottest;

    if (values.length >= 2 && Math.max(...values) - Math.min(...values) > IMBALANCE_C) {
      if (this.imbalanceSince === null) this.imbalanceSince = now;
      if (now - this.imbalanceSince >= IMBALANCE_S) active[FAULT_CELL_IMBALANCE] = this.hottest;
    } else {
      this.imbalanceSince = null;
    }
    return active;
  }
}

/** Faults that started or ended, ended first, in a stable order (same as the Guardian's fault_edges). */
function faultEdges(before: FaultMap, after: FaultMap): FaultEdge[] {
  const ended = Object.keys(before).sort().filter((c) => !(c in after)).map((code) => ({ code, stage: "PASSED" as const, cell: before[code] }));
  const started = Object.keys(after).sort().filter((c) => !(c in before)).map((code) => ({ code, stage: "FAILED" as const, cell: after[code] }));
  return [...ended, ...started];
}

/** Codes whose start is already visible as a pack state row ("getting hot", "too hot", ...). */
export const STATE_EXPLAINED_CODES = new Set([...THERMAL_FAULTS, FAULT_SIGNAL_STALE]);

export function faultReason(code: string): string {
  const pack: Record<string, string> = {
    [FAULT_OVER_TEMP_WARNING]: "getting hot",
    [FAULT_OVER_TEMP_CRITICAL]: "too hot",
    [FAULT_MITIGATION_FAILED]: "mitigation failed",
    [FAULT_SIGNAL_STALE]: "stale signal",
    [FAULT_CELL_IMBALANCE]: "cell imbalance",
  };
  return pack[code] ?? CELL_REASONS[code.slice(code.lastIndexOf(".") + 1) as CellFaultKind];
}
