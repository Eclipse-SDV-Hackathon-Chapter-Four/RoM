import { useEffect, useState, useSyncExternalStore } from "react";
import { ScenarioController } from "../data/scenarioApi";

/**
 * Scenario [dropdown] [Run Scenario]: starts one real fault campaign of the running stack through the local dev server.
 * It does not touch the telemetry subscription: the dashboard keeps polling while a campaign runs, and what changes on
 * screen is what the real stack publishes. The outcome shown is the process status only (exit code, or "stopped" after Stop,
 * which interrupts the real campaign); PASS/FAIL verdicts live in the Evidence Collector (Safety Evidence tab).
 */
export default function ScenarioRunner() {
  const [ctl] = useState(() => new ScenarioController());
  const s = useSyncExternalStore(ctl.subscribe, ctl.getState);
  useEffect(() => {
    void ctl.init();
    return () => ctl.dispose();
  }, [ctl]);

  const label = (id: string) => s.scenarios.find((x) => x.id === id)?.label ?? id;
  const st = s.status;

  let line = "Idle";
  let tone = "idle";
  if (st.status === "stopping") {
    line = `Stopping: ${label(st.scenario)}`;
    tone = "running";
  } else if (s.busy && st.status !== "running") {
    line = "Starting…";
    tone = "running";
  } else if (st.status === "running") {
    line = `Running: ${label(st.scenario)}`;
    tone = "running";
  } else if (st.status === "stopped") {
    line = `Scenario stopped: ${label(st.scenario)}`;
    tone = "running";
  } else if (st.status === "completed") {
    line = `Scenario completed: ${label(st.scenario)} (exit code ${st.exitCode})`;
    tone = "ok";
  } else if (st.status === "failed") {
    line = `Scenario failed: ${label(st.scenario)} (exit code ${st.exitCode})`;
    tone = "bad";
  }

  if (s.unavailable) {
    return (
      <div className="scenario-runner" aria-label="Scenario control">
        <span className="scenario-status idle">Scenario control unavailable: needs the local dev server ({s.error})</span>
      </div>
    );
  }

  return (
    <div className="scenario-runner" aria-label="Scenario control">
      <label htmlFor="scenario-select" className="scenario-label">Scenario</label>
      <select id="scenario-select" className="scenario-select" value={s.selected} disabled={s.busy || !s.scenarios.length} onChange={(e) => ctl.select(e.target.value)}>
        {s.scenarios.map((x) => (
          <option key={x.id} value={x.id}>{x.label}</option>
        ))}
      </select>
      <button type="button" className="scenario-btn" disabled={s.busy || !s.selected} onClick={() => void ctl.run()}>
        {s.busy ? "Running…" : "Run Scenario"}
      </button>
      <button type="button" className="scenario-btn stop" disabled={!s.canStop} onClick={() => void ctl.stop()}>
        {st.status === "stopping" ? "Stopping…" : "Stop"}
      </button>
      <span className={`scenario-status ${tone}`} role="status" aria-live="polite">{line}</span>
      {s.error && <span className="scenario-status bad" role="alert">{s.error}</span>}
      {st.status === "stopped" && st.note && <span className="scenario-status scenario-detail">{st.note}</span>}
      {st.status === "failed" && st.error && <span className="scenario-status bad scenario-detail">{st.error}</span>}
    </div>
  );
}
