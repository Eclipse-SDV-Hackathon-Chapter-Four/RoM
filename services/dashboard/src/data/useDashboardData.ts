import { useEffect, useState } from "react";
import type { DashboardData } from "../types/dashboard";
import type { DashboardDataSource } from "./DashboardDataSource";

/** Subscribes to any DashboardDataSource and returns its latest snapshot. */
export function useDashboardData(source: DashboardDataSource) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    return source.subscribe(
      (next) => {
        setData(next);
        setError(null);
      },
      (message) => setError(message),
    );
  }, [source]);

  return { data, error };
}
