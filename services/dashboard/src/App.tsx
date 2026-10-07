import { useEffect, useMemo, useState } from "react";
import Dashboard from "./components/Dashboard";
import type { ViewId } from "./components/ViewTabs";
import type { DashboardDataSource } from "./data/DashboardDataSource";
import { EvidenceCollectorDataSource } from "./data/EvidenceCollectorDataSource";
import { MockDashboardDataSource } from "./data/MockDashboardDataSource";

/**
 * The single place that decides where data comes from, explicitly, by VITE_DASHBOARD_SOURCE:
 *   mock (default)  simulated telemetry with demo controls
 *   live            the running stack through the Evidence Collector (VITE_EVIDENCE_API_BASE, default /evidence-api)
 * There is deliberately no automatic fallback from live to mock: simulated numbers must never pass for real ones.
 */
function createSource(): DashboardDataSource | string {
  const kind = import.meta.env.VITE_DASHBOARD_SOURCE ?? "mock";
  if (kind === "live") return new EvidenceCollectorDataSource(import.meta.env.VITE_EVIDENCE_API_BASE || "/evidence-api");
  if (kind === "mock") return new MockDashboardDataSource();
  return `Unknown VITE_DASHBOARD_SOURCE "${kind}": use "mock" or "live".`;
}

/** The view lives in the URL hash (#/live, #/evidence): a refresh or a shared link stays on the same view. */
const viewFromHash = (): ViewId => (window.location.hash === "#/evidence" ? "evidence" : "live");

export default function App() {
  const source = useMemo(createSource, []);
  const [view, setView] = useState<ViewId>(viewFromHash);
  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  if (typeof source === "string") return <div className="error-banner" role="alert">{source}</div>;
  return <Dashboard source={source} view={view} />;
}
