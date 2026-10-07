/**
 * Demo scenario control: the browser side of vite/scenarios.mjs. It only asks the local dev server to start one of the
 * project's real fault campaigns and reports what the server says; it never produces a verdict itself.
 */
export interface Scenario {
  id: string;
  label: string;
}

export type ScenarioStatus =
  | { status: "idle" }
  | { status: "running"; scenario: string; startedAt?: string }
  | { status: "stopping"; scenario: string; startedAt?: string }
  | { status: "stopped"; scenario: string; exitCode: null; finishedAt?: string; note?: string }
  | { status: "completed"; scenario: string; exitCode: number; finishedAt?: string }
  | { status: "failed"; scenario: string; exitCode: number; error?: string; finishedAt?: string };

export const SCENARIO_API_BASE = import.meta.env?.VITE_SCENARIO_API_BASE || "/api/scenarios";

type FetchFn = typeof fetch;

async function json(res: Response): Promise<Record<string, unknown>> {
  try {
    return (await res.json()) as Record<string, unknown>;
  } catch {
    throw new Error(`HTTP ${res.status}: the answer is not JSON (is the scenario API served?)`);
  }
}

export async function listScenarios(base = SCENARIO_API_BASE, fetchFn: FetchFn = fetch): Promise<Scenario[]> {
  const res = await fetchFn(`${base}`, { cache: "no-store" });
  const body = await json(res);
  if (!res.ok || !Array.isArray(body.scenarios)) throw new Error(typeof body.error === "string" ? body.error : `HTTP ${res.status}`);
  return (body.scenarios as Scenario[]).filter((s) => typeof s?.id === "string" && typeof s?.label === "string");
}

export async function getScenarioStatus(base = SCENARIO_API_BASE, fetchFn: FetchFn = fetch): Promise<ScenarioStatus> {
  const res = await fetchFn(`${base}/status`, { cache: "no-store" });
  const body = await json(res);
  if (!res.ok || typeof body.status !== "string") throw new Error(`HTTP ${res.status}`);
  return body as unknown as ScenarioStatus;
}

/** Resolves with the server's answer; a refusal (409, 503, ...) is thrown with the server's own message. */
export async function runScenario(id: string, base = SCENARIO_API_BASE, fetchFn: FetchFn = fetch): Promise<void> {
  const res = await fetchFn(`${base}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: id }) });
  if (res.status === 202) return;
  const body = await json(res);
  const detail = typeof body.detail === "string" ? `: ${body.detail}` : "";
  throw new Error(`${typeof body.error === "string" ? body.error : `HTTP ${res.status}`}${detail}`);
}

/** Asks the server to stop the campaign it is running (it takes no container or id). A refusal is thrown with the server's message. */
export async function stopScenario(base = SCENARIO_API_BASE, fetchFn: FetchFn = fetch): Promise<void> {
  const res = await fetchFn(`${base}/stop`, { method: "POST" });
  if (res.status === 202) return;
  const body = await json(res);
  throw new Error(typeof body.error === "string" ? body.error : `HTTP ${res.status}`);
}

export interface ScenarioViewState {
  scenarios: Scenario[];
  /** The id chosen in the dropdown. */
  selected: string;
  status: ScenarioStatus;
  /** Starting, running or stopping: the selector and the Run button stay disabled. */
  busy: boolean;
  /** Stop may be clicked: a campaign is running and no stop is in flight. */
  canStop: boolean;
  /** The last request failed (service missing, refused, ...). */
  error: string | null;
  /** The scenario API could not be reached at all (static build, server without the plugin). */
  unavailable: boolean;
}

/**
 * Framework-free state machine so it can be tested without a DOM. Polls /status once per interval only while a
 * scenario runs, and never starts one on its own: only run() does, and only once at a time.
 */
export class ScenarioController {
  private state: ScenarioViewState = { scenarios: [], selected: "", status: { status: "idle" }, busy: false, canStop: false, error: null, unavailable: false };
  private listeners = new Set<(s: ScenarioViewState) => void>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;
  private starting = false;
  private stopping = false;

  private readonly base: string;
  private readonly fetchFn: FetchFn;
  private readonly pollMs: number;
  private readonly onFinished?: (s: ScenarioStatus) => void;

  // explicit fields, no parameter properties: Node's type stripping (used by the tests) does not support those
  constructor(base: string = SCENARIO_API_BASE, fetchFn: FetchFn = (...a) => fetch(...a), pollMs = 1000, onFinished?: (s: ScenarioStatus) => void) {
    this.base = base;
    this.fetchFn = fetchFn;
    this.pollMs = pollMs;
    this.onFinished = onFinished;
  }

  getState = (): ScenarioViewState => this.state;

  subscribe = (fn: (s: ScenarioViewState) => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  private set(patch: Partial<ScenarioViewState>) {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l(this.state));
  }

  select = (id: string) => {
    if (!this.state.busy) this.set({ selected: id });
  };

  /** Loads the list and picks up a campaign that is already running (page refresh during a run). */
  async init(): Promise<void> {
    this.disposed = false; // StrictMode runs effect cleanup and setup twice on the same instance
    try {
      const scenarios = await listScenarios(this.base, this.fetchFn);
      const status = await getScenarioStatus(this.base, this.fetchFn);
      const current = status.status === "idle" ? "" : status.scenario;
      const preferred = scenarios.find((s) => s.id === "thermal_runaway")?.id ?? scenarios[0]?.id ?? "";
      const active = status.status === "running" || status.status === "stopping";
      this.set({ scenarios, selected: scenarios.some((s) => s.id === current) ? current : preferred, status, busy: active, canStop: status.status === "running", unavailable: false, error: null });
      if (active) this.poll();
    } catch (e) {
      this.set({ unavailable: true, error: e instanceof Error ? e.message : String(e) });
    }
  }

  /** Starts the selected scenario. A second call while one is starting or running does nothing. */
  async run(): Promise<void> {
    const id = this.state.selected;
    if (!id || this.state.busy || this.starting) return;
    this.starting = true;
    this.set({ busy: true, error: null });
    try {
      await runScenario(id, this.base, this.fetchFn);
      this.set({ status: { status: "running", scenario: id }, canStop: true });
      this.poll();
    } catch (e) {
      this.set({ busy: false, canStop: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      this.starting = false;
    }
  }

  /** Stops the running campaign for real (server side). Only one stop at a time; polling goes on until the terminal state. */
  async stop(): Promise<void> {
    if (!this.state.canStop || this.stopping) return;
    this.stopping = true;
    const scenario = this.state.status.status === "idle" ? this.state.selected : this.state.status.scenario;
    this.set({ canStop: false, error: null });
    try {
      await stopScenario(this.base, this.fetchFn);
      this.set({ status: { status: "stopping", scenario } });
      this.poll();
    } catch (e) {
      // e.g. the campaign finished a moment ago: show the message and let one status read decide what is true now
      this.set({ error: e instanceof Error ? e.message : String(e) });
      try {
        const status = await getScenarioStatus(this.base, this.fetchFn);
        const active = status.status === "running" || status.status === "stopping";
        this.set({ status, busy: active, canStop: status.status === "running" });
        if (active) this.poll();
        else this.onFinished?.(status);
      } catch {
        // keep the last known state; the next poll will correct it
      }
    } finally {
      this.stopping = false;
    }
  }

  private poll() {
    if (this.timer || this.disposed) return;
    const tick = async () => {
      this.timer = null;
      try {
        const status = await getScenarioStatus(this.base, this.fetchFn);
        if (status.status === "running" || status.status === "stopping") {
          this.set({ status, canStop: status.status === "running" && !this.stopping });
          if (!this.disposed) this.timer = setTimeout(tick, this.pollMs);
          return;
        }
        this.set({ status, busy: false, canStop: false });
        this.onFinished?.(status);
      } catch (e) {
        // transient: keep polling, the run itself is not affected
        this.set({ error: e instanceof Error ? e.message : String(e) });
        if (!this.disposed) this.timer = setTimeout(tick, this.pollMs);
      }
    };
    this.timer = setTimeout(tick, this.pollMs);
  }

  dispose() {
    this.disposed = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}
