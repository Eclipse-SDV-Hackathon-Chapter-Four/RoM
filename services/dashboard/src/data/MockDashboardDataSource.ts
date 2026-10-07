import type { DashboardData, ScenarioId } from "../types/dashboard";
import type { DashboardDataSource, ScenarioInfo, ScenarioSupport } from "./DashboardDataSource";
import mock from "./mock-dashboard.json";

const SCENARIOS: ScenarioInfo[] = [
  { id: "NORMAL", label: "Normal" },
  { id: "WARNING", label: "Warning" },
  { id: "CRITICAL", label: "Critical" },
  { id: "SENSOR_FAULT", label: "Sensor fault" },
];

const snapshots = mock.scenarios as unknown as Record<ScenarioId, DashboardData>;

/** Serves predefined JSON snapshots. No network, no timers. */
export class MockDashboardDataSource implements DashboardDataSource {
  readonly label = "mock data";
  private selected: ScenarioId = "WARNING";

  readonly scenarios: ScenarioSupport = {
    list: () => SCENARIOS,
    current: () => this.selected,
    select: (id) => {
      this.selected = id;
    },
  };

  async fetch(): Promise<DashboardData> {
    return structuredClone(snapshots[this.selected]);
  }
}
