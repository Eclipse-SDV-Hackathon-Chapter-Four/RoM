import type { CellStatus, GuardianState } from "../types/dashboard";

/** One colour per Guardian state, shared by every component. Values are CSS variables from dashboard.css. */
export const STATE_CLASS: Record<GuardianState, string> = {
  CLEAR: "state-clear",
  MONITORING: "state-monitoring",
  WARNING: "state-warning",
  CRITICAL: "state-critical",
  MITIGATING: "state-mitigating",
  SENSOR_FAULT: "state-fault",
};

export const STATE_LABEL: Record<GuardianState, string> = {
  CLEAR: "CLEAR",
  MONITORING: "MONITORING",
  WARNING: "WARNING",
  CRITICAL: "CRITICAL",
  MITIGATING: "MITIGATING",
  SENSOR_FAULT: "SENSOR FAULT",
};

export const formatTemp = (value: number | null, digits = 1) => (value === null ? "--" : value.toFixed(digits));

/** HH:MM:SS in the viewer's local time, so it matches the clock next to the screen. */
export const formatTime = (iso: string | number) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** One line colour per cell, used by the chart lines and the legend so a cell keeps its colour everywhere. */
export const CELL_COLORS: Record<number, string> = {
  1: "#38bdf8",
  2: "#4ade80",
  3: "#f472b6",
  4: "#fbbf24",
};
export const cellColor = (id: number) => CELL_COLORS[id] ?? "#cbd5e1";

export const CELL_STATUS_LABEL: Record<CellStatus, string> = {
  OK: "OK",
  STALE: "STALE",
  STUCK: "STUCK",
  OUT_OF_RANGE: "OUT OF RANGE",
  NO_DATA: "NO DATA",
};

/** Temperature tone relative to the supervisory thresholds. */
export const tempTone = (t: number | null, warn: number, crit: number) =>
  t === null ? "tone-none" : t >= crit ? "tone-crit" : t >= warn ? "tone-warn" : "tone-ok";
