/** Guardian states as produced by services/guardian (MITIGATING is internal to the Guardian). */
export type GuardianState =
  | "CLEAR"
  | "MONITORING"
  | "WARNING"
  | "CRITICAL"
  | "MITIGATING"
  | "SENSOR_FAULT";

/**
 * Per-cell health as the Guardian judges it (services/guardian CellMonitor):
 *  STALE        the cell is missing from the cell messages for longer than STALE_MS, or the whole stream is silent
 *  STUCK        the value has not changed for STUCK_S
 *  OUT_OF_RANGE outside the plausibility bounds
 *  NO_DATA      the cell has not been seen yet
 */
export type CellStatus = "OK" | "STALE" | "STUCK" | "OUT_OF_RANGE" | "NO_DATA";

/** Where a cell's reading comes from in the final demo topology: cell 1 = AZ3166 board, cells 2-4 = simulator. */
export type CellSource = "HW" | "SIM";

export interface CellInfo {
  /** Cell number as in the backend, starting at 1. */
  id: number;
  /** null whenever there is no trustworthy reading (status is not OK). */
  temperature_c: number | null;
  status: CellStatus;
  source: CellSource;
}

export interface BatteryInfo {
  /** Always one entry per cell, in cell order. A cell the backend did not report is present with status NO_DATA / STALE. */
  cells: CellInfo[];
  /** Hottest VALID cell. null when no cell can be trusted. Faulty cells never take part. */
  pack_max_c: number | null;
  pack_max_cell: number | null;
  /** Supervisory demo thresholds (WARN_C / CRIT_C). Not the plausibility bounds. */
  warn_c: number;
  crit_c: number;
}

/** Pack-level state: driven by the hottest valid cell, not by any single sensor. */
export interface GuardianInfo {
  state: GuardianState;
  reason: string;
}

/**
 * What the dashboard can actually tell about a source: whether its cells are reaching the Guardian.
 * NO_DATA is deliberately neutral. Missing telemetry can come from the source, the transport, KUKSA or uProtocol, so it
 * never claims the source itself is offline. A source may only be shown as offline if the data model carries explicit
 * source / heartbeat information that proves it.
 */
export type SourceStatus = "RECEIVING" | "NO_DATA";

/** A producer of cell readings. Final topology: the AZ3166 board (cell 1) and the simulator (cells 2-4). */
export interface SourceInfo {
  id: "az3166" | "simulator";
  name: string;
  /** e.g. the MQTT device_id of the board. */
  detail: string;
  cells: number[];
  status: SourceStatus;
}

export interface MessageInfo {
  /** One counter for the whole cell message. */
  seq: number;
  /** null when the producer sent no epoch timestamp, so latency is unknown. */
  latency_ms: number | null;
  /** Cell ids that were present in the last cell message. */
  cells_reported: number[];
  total_cells: number;
}

export interface HistoryPoint {
  timestamp: string; // ISO 8601
  /** Trustworthy reading per cell id; null = missing or not trusted at that moment. */
  cells: Record<number, number | null>;
  pack_max_c: number | null;
}

interface EventBase {
  /** Unique within a stream; lets the UI key rows. */
  id: number;
  timestamp: string; // ISO 8601
  reason: string;
  /** DFM fault code (battery_guardian.*) when the event corresponds to one. */
  code?: string;
}

/** The Guardian changed its pack state. */
export interface StateEvent extends EventBase {
  kind: "state";
  state: GuardianState;
}

/** A DFM diagnostic fault started (FAILED) or cleared (PASSED). Does not by itself change the pack state. */
export interface FaultEvent extends EventBase {
  kind: "fault";
  stage: "FAILED" | "PASSED";
  /** Faulty cell; null for a pack-level fault such as cell_imbalance. */
  cell: number | null;
}

export type GuardianEvent = StateEvent | FaultEvent;

/** Normalized view model: every data source (mock, OpenSOVD, ...) must produce exactly this. */
export interface DashboardData {
  timestamp: string; // ISO 8601
  battery: BatteryInfo;
  guardian: GuardianInfo;
  sources: SourceInfo[];
  message: MessageInfo;
  history: HistoryPoint[];
  events: GuardianEvent[]; // newest first
}

export type ScenarioId = "NORMAL" | "WARNING" | "CRITICAL" | "CELL_FAULT" | "STREAM_LOSS";
