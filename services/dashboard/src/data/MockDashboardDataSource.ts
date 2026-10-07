import type { DashboardData, ScenarioId } from "../types/dashboard";
import type { DashboardDataSource, ScenarioInfo, ScenarioSupport } from "./DashboardDataSource";
import { TimelineEngine } from "./mockTimeline";

const SCENARIOS: ScenarioInfo[] = [
  { id: "NORMAL", label: "Normal" },
  { id: "WARNING", label: "Warning" },
  { id: "CRITICAL", label: "Critical" },
  { id: "SENSOR_FAULT", label: "Sensor fault" },
];

/**
 * Simulated live telemetry: publishes a new snapshot every `tickMs` from a deterministic, looping timeline.
 * No network. The stream runs while at least one subscriber is attached.
 */
export class MockDashboardDataSource implements DashboardDataSource {
  readonly label = "simulated telemetry";
  private readonly engine: TimelineEngine;
  private readonly listeners = new Set<(data: DashboardData) => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private latest: DashboardData;

  constructor(private readonly tickMs = 1000) {
    this.engine = new TimelineEngine(new Date(), tickMs);
    this.latest = this.engine.step(new Date());
  }

  readonly scenarios: ScenarioSupport = {
    list: () => SCENARIOS,
    select: (id: ScenarioId) => {
      this.engine.jumpTo(id);
      this.publish(); // show the new situation immediately instead of waiting for the next tick
    },
  };

  subscribe(onData: (data: DashboardData) => void): () => void {
    this.listeners.add(onData);
    onData(this.latest);
    if (this.timer === null) this.timer = setInterval(() => this.publish(), this.tickMs);
    return () => {
      this.listeners.delete(onData);
      if (this.listeners.size === 0 && this.timer !== null) {
        clearInterval(this.timer);
        this.timer = null;
      }
    };
  }

  private publish(): void {
    this.latest = this.engine.step(new Date());
    this.listeners.forEach((cb) => cb(this.latest));
  }
}
