import { useState } from "react";
import type { DashboardDataSource } from "../data/DashboardDataSource";
import { useDashboardData } from "../data/useDashboardData";
import { BatteryLogo } from "./icons";
import GuardianStateCard from "./GuardianStateCard";
import LastMessageCard from "./LastMessageCard";
import RecentEvents from "./RecentEvents";
import LiveStatus from "./LiveStatus";
import DemoControls from "./DemoControls";
import ScenarioRunner from "./ScenarioRunner";
import Cell1SourceSwitch from "./Cell1SourceSwitch";
import { useCell1Source } from "../data/cell1Source";
import DataSourcesCard from "./DataSourcesCard";
import SystemFlow from "./SystemFlow";
import BatteryCellsCard from "./BatteryCellsCard";
import TemperatureChart from "./TemperatureChart";
import SafetyEvidence from "./SafetyEvidence";
import ViewTabs, { type ViewId } from "./ViewTabs";
import type { CellSelection, EventFilter } from "./selection";
import type { DemoScenario, DemoTarget } from "../types/dashboard";

/**
 * view: which top-level view is shown. The Live Monitoring part stays mounted (hidden) while Safety Evidence is shown,
 * so its data subscription, selection and filters survive a round trip between the two.
 */
export default function Dashboard({ source, view }: { source: DashboardDataSource; view: ViewId }) {
  const { data, error } = useDashboardData(source);
  const live = source.mode === "live";
  // The one place that knows what is in focus. Picking a cell focuses the chart and filters the events to it; the event
  // chips can also be changed on their own without moving the cell selection.
  const [selection, setSelection] = useState<CellSelection>("ALL");
  const [eventFilter, setEventFilter] = useState<EventFilter>("ALL");
  const select = (s: CellSelection) => {
    setSelection(s);
    setEventFilter(s);
  };
  // Demo controls drive the simulated inputs; the dashboard then focuses what they touched: the target cell, or the
  // whole pack. Resume returns to the overview.
  const applyDemo = (target: DemoTarget, scenario: DemoScenario) => {
    source.demo?.apply(target, scenario);
    select(target === "PACK" ? "ALL" : target);
  };
  const resumeDemo = () => {
    source.demo?.resume();
    select("ALL");
  };
  // Cell 1 is either the AZ3166 board or simulated (one writer, chosen with the switch); until the switch answers,
  // keep the default topology
  const cell1 = useCell1Source(live);
  const cell1Hw = cell1.state ? cell1.state.mode === "hw" : true;
  const cells = data?.battery.cells.map((c) => (c.id === 1 ? { ...c, source: cell1Hw ? ("HW" as const) : ("SIM" as const) } : c));
  const battery = data && cells ? { ...data.battery, cells } : undefined;
  const sources = data?.sources.map((s) =>
    s.id === "az3166" ? { ...s, cells: cell1Hw ? [1] : [] } : s.id === "simulator" ? { ...s, cells: cell1Hw ? [2, 3, 4] : [1, 2, 3, 4] } : s,
  );

  return (
    <div className="page">
      <header className="header">
        <div className="brand">
          <BatteryLogo />
          <div>
            <h1>Battery Thermal Guardian</h1>
            <p className="subtitle">Real-time Monitoring &amp; Safety Supervision</p>
          </div>
        </div>
        <ViewTabs view={view} />
        <div className="mode">
          {live ? (
            <>
              <span className="mode-badge mode-live">LIVE MODE</span>
              <p>
                {source.label} (uProtocol bus)
                <br />
                {cell1Hw ? "Cell 1 AZ3166 · Cells 2–4 simulator" : "Cells 1–4 simulator"}
              </p>
            </>
          ) : (
            <>
              <span className="mode-badge">DEMO MODE</span>
              <p>
                Using {source.label}
                <br />
                OpenSOVD integration pending
              </p>
            </>
          )}
        </div>
      </header>

      <div className="live-view" hidden={view !== "live"}>
      <div className="demo-bar">
        <LiveStatus live={live} label={live ? "Hardware + simulator" : "Simulated telemetry"} connected={!(live && error)} />
        {live && <ScenarioRunner />}
        {live && <Cell1SourceSwitch {...cell1} />}
        {source.demo && <DemoControls support={source.demo} override={data?.demo_override ?? null} onApply={applyDemo} onResume={resumeDemo} />}
      </div>

      {error && <div className="error-banner" role="alert">Data source error: {error}</div>}

      {data && battery && sources ? (
        <main className="grid">
          <BatteryCellsCard battery={battery} selection={selection} onSelect={select} />
          <GuardianStateCard guardian={data.guardian} battery={battery} />
          <div className="side-stack">
            <DataSourcesCard sources={sources} />
            <LastMessageCard message={data.message} updatedAt={data.timestamp} />
          </div>
          <TemperatureChart history={data.history} battery={battery} now={data.timestamp} selection={selection} onShowAll={() => select("ALL")} />
          <RecentEvents events={data.events} cells={battery.cells} filter={eventFilter} onFilter={setEventFilter} />
          <SystemFlow />
        </main>
      ) : (
        !error && <p className="loading">Loading…</p>
      )}
      </div>

      {view === "evidence" && <SafetyEvidence />}
    </div>
  );
}
