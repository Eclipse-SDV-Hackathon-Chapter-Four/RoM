import type { DashboardDataSource } from "../data/DashboardDataSource";
import { useDashboardData } from "../data/useDashboardData";
import { BatteryLogo } from "./icons";
import GuardianStateCard from "./GuardianStateCard";
import LastMessageCard from "./LastMessageCard";
import RecentEvents from "./RecentEvents";
import ScenarioControls from "./ScenarioControls";
import SensorStatusCard from "./SensorStatusCard";
import SystemFlow from "./SystemFlow";
import TemperatureCard from "./TemperatureCard";
import TemperatureChart from "./TemperatureChart";

interface Props {
  source: DashboardDataSource;
  /** 0 = no polling (mock). A live source would pass e.g. 2000. */
  pollMs?: number;
}

export default function Dashboard({ source, pollMs = 0 }: Props) {
  const { data, error, scenario, selectScenario } = useDashboardData(source, pollMs);

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

      {source.scenarios && scenario && (
        <ScenarioControls scenarios={source.scenarios.list()} selected={scenario} onSelect={selectScenario} />
      )}

      {error && <div className="error-banner" role="alert">Data source error: {error}</div>}

      {data ? (
        <main className="grid">
          <TemperatureCard battery={data.battery} />
          <GuardianStateCard guardian={data.guardian} />
          <div className="side-stack">
            <SensorStatusCard sensor={data.sensor} />
            <LastMessageCard message={data.message} sensor={data.sensor} />
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
