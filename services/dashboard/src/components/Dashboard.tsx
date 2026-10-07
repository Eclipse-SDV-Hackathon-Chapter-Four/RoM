import type { DashboardDataSource } from "../data/DashboardDataSource";
import { useDashboardData } from "../data/useDashboardData";
import { BatteryLogo } from "./icons";
import GuardianStateCard from "./GuardianStateCard";
import LastMessageCard from "./LastMessageCard";
import RecentEvents from "./RecentEvents";
import LiveStatus from "./LiveStatus";
import ScenarioControls from "./ScenarioControls";
import SensorStatusCard from "./SensorStatusCard";
import SystemFlow from "./SystemFlow";
import TemperatureCard from "./TemperatureCard";
import TemperatureChart from "./TemperatureChart";

export default function Dashboard({ source }: { source: DashboardDataSource }) {
  const { data, error } = useDashboardData(source);

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
        {source.scenarios && <ScenarioControls support={source.scenarios} />}
      </div>

      {error && <div className="error-banner" role="alert">Data source error: {error}</div>}

      {data ? (
        <main className="grid">
          <TemperatureCard battery={data.battery} />
          <GuardianStateCard guardian={data.guardian} />
          <div className="side-stack">
            <SensorStatusCard sensor={data.sensor} />
            <LastMessageCard message={data.message} sensor={data.sensor} updatedAt={data.timestamp} />
          </div>
          <TemperatureChart history={data.history} battery={data.battery} now={data.timestamp} />
          <RecentEvents events={data.events} />
          <SystemFlow />
        </main>
      ) : (
        !error && <p className="loading">Loading…</p>
      )}
    </div>
  );
}
