import type { GuardianState } from "../types/dashboard";

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
