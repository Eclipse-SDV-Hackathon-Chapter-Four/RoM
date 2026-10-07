import type { DashboardData, ScenarioId } from "../types/dashboard";

export interface ScenarioInfo {
  id: ScenarioId;
  label: string;
}

/** Test-only helper offered by demo sources: jump the simulated stream to a situation. Live sources omit it. */
export interface ScenarioSupport {
  list(): ScenarioInfo[];
  select(id: ScenarioId): void;
}

/**
 * The only thing the React components know about where data comes from.
 * Implementations: MockDashboardDataSource now (simulated stream), OpenSovdDataSource later.
 */
export interface DashboardDataSource {
  /** Short text for the UI, e.g. "simulated telemetry". */
  readonly label: string;
  /**
   * Calls `onData` with a normalized snapshot now and again whenever new data arrives.
   * How often, and whether by push or by polling, is the source's business. Returns an unsubscribe function.
   */
  subscribe(onData: (data: DashboardData) => void, onError?: (message: string) => void): () => void;
  readonly scenarios?: ScenarioSupport;
}
