/** Guardian states as produced by services/guardian (MITIGATING is internal to the Guardian). */
export type GuardianState =
  | "CLEAR"
  | "MONITORING"
  | "WARNING"
  | "CRITICAL"
  | "MITIGATING"
  | "SENSOR_FAULT";

export type SensorStatus = "ONLINE" | "OFFLINE";

export interface BatteryInfo {
  /** Latest temperature, null when the Guardian has no usable reading. */
  temperature_c: number | null;
  /** Supervisory demo thresholds (WARN_C / CRIT_C). Not the plausibility bounds. */
  warn_c: number;
  crit_c: number;
}

export interface GuardianInfo {
  state: GuardianState;
  reason: string;
}

export interface SensorInfo {
  status: SensorStatus;
  device_id: string;
}

export interface MessageInfo {
  seq: number;
  /** null when the device sent no epoch timestamp, so latency is unknown. */
  latency_ms: number | null;
}

export interface HistoryPoint {
  timestamp: string; // ISO 8601, UTC
  temperature_c: number;
}

export interface GuardianEvent {
  timestamp: string; // ISO 8601, UTC
  state: GuardianState;
  reason: string;
  temperature_c: number | null;
}

/** Normalized view model: every data source (mock, OpenSOVD, ...) must produce exactly this. */
export interface DashboardData {
  timestamp: string; // ISO 8601, UTC
  battery: BatteryInfo;
  guardian: GuardianInfo;
  sensor: SensorInfo;
  message: MessageInfo;
  history: HistoryPoint[];
  events: GuardianEvent[]; // newest first
}

export type ScenarioId = "NORMAL" | "WARNING" | "CRITICAL" | "SENSOR_FAULT";
