import type { DemoOverrideInfo, DemoScenario, DemoTarget } from "../types/dashboard";
import { N_CELLS } from "./mockGuardian";

/**
 * Manual override of the simulated stream, for presentations and tests. It only produces per-cell INPUT values:
 * heat a cell up, stop reporting it, freeze it, make it implausible, or cut the whole stream. It never sets a Guardian
 * state, a cell status or a fault code; mockGuardian derives all of those from the values, exactly as for the loop.
 */
type Mode = "nominal" | "warning" | "critical" | "stale" | "stuck" | "oor";

const MODE_OF: Record<DemoScenario, Mode | null> = {
  NORMAL: "nominal",
  WARNING: "warning",
  CRITICAL: "critical",
  STALE: "stale",
  STUCK: "stuck",
  OUT_OF_RANGE: "oor",
  STREAM_LOSS: null,
};
const SCENARIO_OF: Record<Mode, DemoScenario> = {
  nominal: "NORMAL",
  warning: "WARNING",
  critical: "CRITICAL",
  stale: "STALE",
  stuck: "STUCK",
  oor: "OUT_OF_RANGE",
};
const MODE_LABEL: Record<Mode, string> = {
  nominal: "Normal",
  warning: "Warning",
  critical: "Critical",
  stale: "Stale",
  stuck: "Stuck",
  oor: "Out of range",
};

/** A reading outside the plausible range (-40..150 °C). */
export const IMPLAUSIBLE_C = 175;
const LEVEL = { warning: 40.5, critical: 47.5 }; // plateau of a heated cell: above WARN_C 38 / CRIT_C 45
const RATE = 2; // °C per tick while heating up or cooling down
const BASE = [31.0, 30.2, 31.4, 29.7]; // nominal level per cell
const SANE_MIN = -40;
const SANE_MAX = 100;

const r1 = (x: number) => Math.round(x * 10) / 10;

/** null = supported; otherwise why the combination makes no sense (shown as a tooltip). */
export function unsupportedReason(target: DemoTarget, scenario: DemoScenario): string | null {
  if (target === "PACK" && scenario === "STALE") return "A silent cell is a single-cell fault. Whole-stream silence is Stream loss.";
  if (target !== "PACK" && scenario === "STREAM_LOSS") return "Stream loss affects every cell. Choose the Pack target.";
  return null;
}

export const saneC = (v: number) => v >= SANE_MIN && v <= SANE_MAX;

export class ManualOverride {
  private modes: Mode[] = Array(N_CELLS).fill("nominal");
  private frozen: (number | null)[] = Array(N_CELLS).fill(null);
  private loss = false;
  private packScenario: DemoScenario | null = null;
  private tick = 0;

  /**
   * lastVal: last value each cell reported (a stuck cell freezes at it). hottest: current Pack Max cell, the one a
   * Pack Warning / Critical heats up.
   */
  apply(target: DemoTarget, scenario: DemoScenario, lastVal: (number | null)[], hottest: number | null): void {
    const mode = MODE_OF[scenario];
    if (target === "PACK") {
      this.modes = Array(N_CELLS).fill("nominal");
      this.loss = scenario === "STREAM_LOSS";
      this.packScenario = scenario;
      if (mode === "warning" || mode === "critical") this.modes[(hottest ?? 1) - 1] = mode;
      if (mode === "stuck" || mode === "oor") this.modes = Array(N_CELLS).fill(mode); // "all cells stuck / out of range"
      if (mode === "stuck") this.frozen = lastVal.slice();
      return;
    }
    // a single cell: whole-stream loss and any earlier pack-level choice end here
    this.loss = false;
    this.packScenario = null;
    this.modes[target - 1] = mode ?? "nominal";
    if (mode === "stuck") this.frozen[target - 1] = lastVal[target - 1];
  }

  /** One message worth of cell values (null = that cell is missing from the message). */
  row(lastVal: (number | null)[], lastSane: (number | null)[]): (number | null)[] {
    this.tick++;
    if (this.loss) return Array(N_CELLS).fill(null);
    return this.modes.map((mode, i) => {
      if (mode === "stale") return null;
      if (mode === "stuck") return this.frozen[i] ?? BASE[i];
      if (mode === "oor") return IMPLAUSIBLE_C;
      const level = mode === "warning" ? LEVEL.warning : mode === "critical" ? LEVEL.critical : BASE[i];
      const cur = lastSane[i] ?? level;
      const diff = level - cur;
      let v = Math.abs(diff) > RATE ? cur + Math.sign(diff) * RATE : level + 0.15 * Math.sin(this.tick * 1.3 + i * 2);
      v = r1(v);
      if (lastVal[i] !== null && v === lastVal[i]) v = r1(v + 0.1); // a live sensor never repeats a value exactly
      return v;
    });
  }

  info(): DemoOverrideInfo {
    const active: DemoOverrideInfo["active"] = this.modes.map((m, i) => ({ target: (i + 1) as DemoTarget, scenario: SCENARIO_OF[m] }));
    if (this.loss) active.push({ target: "PACK", scenario: "STREAM_LOSS" });
    else if (this.packScenario) active.push({ target: "PACK", scenario: this.packScenario });

    let label: string;
    const faulty = this.modes.map((m, i) => ({ m, i })).filter((x) => x.m !== "nominal");
    if (this.loss) label = "Stream loss";
    else if (faulty.length === 0) label = "All cells normal";
    else if (faulty.length === N_CELLS && new Set(this.modes).size === 1) label = `All cells ${MODE_LABEL[this.modes[0]].toLowerCase()}`;
    else label = faulty.map((x) => `C${x.i + 1} ${MODE_LABEL[x.m]}`).join(" · ");
    return { label, active };
  }
}
