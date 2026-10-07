import { useMemo } from "react";
import Dashboard from "./components/Dashboard";
import { MockDashboardDataSource } from "./data/MockDashboardDataSource";

/**
 * The single place that decides where data comes from. To go live, replace MockDashboardDataSource
 * with an OpenSovdDataSource here; nothing else changes.
 */
export default function App() {
  const source = useMemo(() => new MockDashboardDataSource(), []);
  return <Dashboard source={source} />;
}
