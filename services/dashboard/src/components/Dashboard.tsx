import { useState } from "react";
import type { DashboardDataSource } from "../data/DashboardDataSource";
import { useDashboardData } from "../data/useDashboardData";
import { BatteryLogo } from "./icons";
import GuardianStateCard from "./GuardianStateCard";
import LastMessageCard from "./LastMessageCard";
import RecentEvents from "./RecentEvents";
import LiveStatus from "./LiveStatus";
import DemoControls from "./DemoControls";
import DataSourcesCard from "./DataSourcesCard";
import SystemFlow from "./SystemFlow";
import BatteryCellsCard from "./BatteryCellsCard";
import TemperatureChart from "./TemperatureChart";
import type { CellSelection, EventFilter } from "./selection";
import type { DemoScenario, DemoTarget } from "../types/dashboard";

export default function Dashboard({ source }: { source: DashboardDataSource }) {
  const { data, error } = useDashboardData(source);
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
        <div className="mode">
          <span className="mode-badge">DEMO MODE</span>
          <p>
            Using {source.label}
            <br />
            OpenSOVD integration pending
          </p>
        </div>
      </header>

      <div className="demo-bar">
        <LiveStatus label="Simulated telemetry" />
        {source.demo && <DemoControls support={source.demo} override={data?.demo_override ?? null} onApply={applyDemo} onResume={resumeDemo} />}
      </div>

      {error && <div className="error-banner" role="alert">Data source error: {error}</div>}

      {data ? (
        <main className="grid">
          <BatteryCellsCard battery={data.battery} selection={selection} onSelect={select} />
          <GuardianStateCard guardian={data.guardian} battery={data.battery} />
          <div className="side-stack">
            <DataSourcesCard sources={data.sources} />
            <LastMessageCard message={data.message} updatedAt={data.timestamp} />
          </div>
          <TemperatureChart history={data.history} battery={data.battery} now={data.timestamp} selection={selection} onShowAll={() => select("ALL")} />
          <RecentEvents events={data.events} cells={data.battery.cells} filter={eventFilter} onFilter={setEventFilter} />
          <SystemFlow />
        </main>
      ) : (
        !error && <p className="loading">Loading…</p>
      )}
    </div>
  );
}
