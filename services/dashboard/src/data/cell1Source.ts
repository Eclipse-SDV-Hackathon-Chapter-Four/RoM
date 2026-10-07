// Made with Claude (Claude Code, Anthropic)
/** Cell 1 source switch, the browser side of vite/cell-source.mjs. */
import { useCallback, useEffect, useState } from "react";

export type Cell1Mode = "hw" | "sim" | "both" | "none";

export interface Cell1Source {
  mode: Cell1Mode;
  /** The adapter answers, so the board can be selected. */
  hwAvailable: boolean;
}

const BASE = "/api/cell1-source";
const POLL_MS = 3000;

async function request(init?: RequestInit): Promise<Cell1Source> {
  const res = await fetch(BASE, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || typeof body.mode !== "string") throw new Error(body.error || `HTTP ${res.status}`);
  return { mode: body.mode, hwAvailable: body.hwAvailable === true };
}

/** Current source (polled, so a switch from another tab or curl shows up too) and a setter. */
export function useCell1Source(enabled: boolean) {
  const [state, setState] = useState<Cell1Source | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    const poll = () =>
      request()
        .then((s) => !stop && (setState(s), setError(null)))
        .catch((e) => !stop && setError(e instanceof Error ? e.message : String(e)));
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [enabled]);

  const set = useCallback(async (mode: "hw" | "sim") => {
    setBusy(true);
    try {
      setState(await request({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  return { state, error, busy, set };
}
