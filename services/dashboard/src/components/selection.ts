import type { GuardianEvent } from "../types/dashboard";

/** What the dashboard is focused on: the whole pack, or one cell (1-4). Held once, in Dashboard. */
export type CellSelection = "ALL" | number;

/** Which Recent Events to list. Follows the selection when a cell is picked, but can also be set on its own. */
export type EventFilter = "ALL" | "PACK" | number;

/**
 * ALL = everything. PACK = Guardian state changes and pack-level diagnostics (no cell). A cell number = diagnostic
 * events of that cell only: a cell fault is not a pack state change, so those stay under PACK.
 */
export function matchesFilter(e: GuardianEvent, filter: EventFilter): boolean {
  if (filter === "ALL") return true;
  if (filter === "PACK") return e.kind === "state" || e.cell === null;
  return e.kind === "fault" && e.cell === filter;
}
