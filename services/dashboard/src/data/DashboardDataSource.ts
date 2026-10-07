import type { DashboardData, DemoScenario, DemoTarget } from "../types/dashboard";

/**
 * Presentation / test helper offered by mock sources only: push per-cell INPUTS (heat a cell, drop it, freeze it, make it
 * implausible) or cut the whole stream. The Guardian logic still decides every state, status and fault code from those
 * inputs. Live sources omit it.
 */
export interface DemoControls {
  /** null when the combination is supported, otherwise the reason it is not (used as a tooltip). */
  unsupported(target: DemoTarget, scenario: DemoScenario): string | null;
  apply(target: DemoTarget, scenario: DemoScenario): void;
  /** Drop every manual override and go back to the automatic demo loop. */
  resume(): void;
}

/**
 * The only thing the React components know about where data comes from.
 * Implementations: MockDashboardDataSource now (simulated stream), OpenSovdDataSource later.
 */
export interface DashboardDataSource {
  /** "mock" = simulated telemetry, "live" = the running stack. The UI labels itself from this, never silently. */
  readonly mode: "mock" | "live";
  /** Short text for the UI, e.g. "simulated telemetry". */
  readonly label: string;
  /**
   * Calls `onData` with a normalized snapshot now and again whenever new data arrives.
   * How often, and whether by push or by polling, is the source's business. Returns an unsubscribe function.
   */
  subscribe(onData: (data: DashboardData) => void, onError?: (message: string) => void): () => void;
  readonly demo?: DemoControls;
}
