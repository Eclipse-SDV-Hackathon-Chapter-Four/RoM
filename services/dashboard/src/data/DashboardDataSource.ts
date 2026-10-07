import type { DashboardData, ScenarioId } from "../types/dashboard";

export interface ScenarioInfo {
  id: ScenarioId;
  label: string;
}

/** Only demo sources offer scenarios; a live source (OpenSOVD) simply leaves `scenarios` undefined. */
export interface ScenarioSupport {
  list(): ScenarioInfo[];
  current(): ScenarioId;
  select(id: ScenarioId): void;
}

/**
 * The only thing the React components know about where data comes from.
 * Implementations: MockDashboardDataSource now, OpenSovdDataSource later.
 */
export interface DashboardDataSource {
  /** Short text for the UI, e.g. "mock data". */
  readonly label: string;
  /** Returns the current normalized snapshot. */
  fetch(): Promise<DashboardData>;
  readonly scenarios?: ScenarioSupport;
}
