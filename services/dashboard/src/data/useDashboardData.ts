import { useCallback, useEffect, useState } from "react";
import type { DashboardData, ScenarioId } from "../types/dashboard";
import type { DashboardDataSource } from "./DashboardDataSource";

/** Loads snapshots from any DashboardDataSource. `pollMs` = 0 loads once (and again on scenario change). */
export function useDashboardData(source: DashboardDataSource, pollMs = 0) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scenario, setScenario] = useState<ScenarioId | null>(source.scenarios?.current() ?? null);

  const load = useCallback(async () => {
    try {
      setData(await source.fetch());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [source]);

  useEffect(() => {
    void load();
    if (pollMs <= 0) return;
    const timer = setInterval(() => void load(), pollMs);
    return () => clearInterval(timer);
  }, [load, pollMs]);

  const selectScenario = useCallback(
    (id: ScenarioId) => {
      source.scenarios?.select(id);
      setScenario(id);
      void load();
    },
    [source, load],
  );

  return { data, error, scenario, selectScenario };
}
