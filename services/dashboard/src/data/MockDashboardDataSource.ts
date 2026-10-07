import type { DashboardData, DemoScenario, DemoTarget } from "../types/dashboard";
import type { DashboardDataSource, DemoControls } from "./DashboardDataSource";
import { unsupportedReason } from "./mockOverride";
import { TimelineEngine } from "./mockTimeline";

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

  readonly demo: DemoControls = {
    unsupported: unsupportedReason,
    apply: (target: DemoTarget, scenario: DemoScenario) => {
      this.engine.applyDemo(target, scenario);
      this.publish(); // show the effect immediately instead of waiting for the next tick
    },
    resume: () => {
      this.engine.resume();
      this.publish();
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
