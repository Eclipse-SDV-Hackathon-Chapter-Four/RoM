import type { DashboardData } from "../types/dashboard";
import type { DashboardDataSource } from "./DashboardDataSource";
import { LiveModel, type RawEvent } from "./liveModel";

const PAGE = 5000; // the API's maximum page size

/**
 * The running stack, seen through the Evidence Collector (services/evidence-collector), which records every cell,
 * state, fault and heartbeat message of the uProtocol bus. GET /events?since=N&limit=L returns the OLDEST lines after
 * line N, so the tail is located once (a few tiny probes), the recent history is loaded, and afterwards only new lines
 * are fetched. It never falls back to simulated data: if the API is unreachable it reports the error and keeps the last
 * real snapshot on screen.
 */
export class EvidenceCollectorDataSource implements DashboardDataSource {
  readonly mode = "live" as const;
  readonly label = "Evidence Collector";

  private model = new LiveModel();
  private readonly listeners = new Set<{ onData: (d: DashboardData) => void; onError?: (m: string) => void }>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private busy = false; // one request cycle at a time, even when React (StrictMode) subscribes twice
  private initialised = false;
  private lastLine = 0;
  private emptyPolls = 0;
  private failures = 0;
  private latest: DashboardData | null = null;

  /** baseUrl: where the browser reaches the collector (the Vite dev proxy by default). initialLines: history to load. */
  constructor(private readonly baseUrl = "/evidence-api", private readonly pollMs = 500, private readonly initialLines = 2000) {}

  subscribe(onData: (d: DashboardData) => void, onError?: (m: string) => void): () => void {
    const l = { onData, onError };
    this.listeners.add(l);
    if (this.latest) onData(this.latest);
    if (!this.running) {
      this.running = true;
      if (!this.busy) void this.tick(); // a cycle still in flight reschedules itself because running is true again
    }
    return () => {
      this.listeners.delete(l);
      if (this.listeners.size === 0) {
        this.running = false;
        if (this.timer !== null) clearTimeout(this.timer);
        this.timer = null;
      }
    };
  }

  private async tick(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    let delay = this.pollMs;
    try {
      if (!this.initialised) await this.initialise();
      else if ((await this.poll()) === PAGE) delay = 0; // a full page: more is waiting
      this.failures = 0;
      this.latest = this.model.snapshot(Date.now());
      this.listeners.forEach((l) => l.onData(this.latest as DashboardData));
    } catch (e) {
      this.failures++;
      delay = Math.min(5000, this.pollMs * 2 ** Math.min(this.failures, 4));
      const message = `Evidence Collector unreachable (${e instanceof Error ? e.message : String(e)}). Showing the last data received.`;
      this.listeners.forEach((l) => l.onError?.(message));
    } finally {
      this.busy = false;
      if (this.running) this.timer = setTimeout(() => void this.tick(), delay);
    }
  }

  private async fetchEvents(since: number, limit: number): Promise<RawEvent[]> {
    const ctl = new AbortController();
    const timeout = setTimeout(() => ctl.abort(), 4000);
    try {
      const res = await fetch(`${this.baseUrl}/events?since=${since}&limit=${limit}`, { signal: ctl.signal, cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body: unknown = await res.json();
      if (!Array.isArray(body)) throw new Error("unexpected response");
      return body as RawEvent[];
    } finally {
      clearTimeout(timeout);
    }
  }

  private async hasLineAfter(n: number): Promise<boolean> {
    return (await this.fetchEvents(n, 1)).length > 0;
  }

  /** Highest line number in the store: grow exponentially, then bisect. A handful of one-line requests. */
  private async findTail(): Promise<number> {
    if (!(await this.hasLineAfter(0))) return 0;
    let hi = 1;
    while (hi < 2 ** 30 && (await this.hasLineAfter(hi))) hi *= 2;
    let lo = hi >> 1;
    while (lo + 1 < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (await this.hasLineAfter(mid)) lo = mid;
      else hi = mid;
    }
    return lo;
  }

  private ingest(events: RawEvent[]): void {
    for (const e of events) {
      try {
        if (typeof e.line === "number" && typeof e.topic === "string" && typeof e.rx_ts_ms === "number") this.model.ingest(e);
      } catch {
        this.model.rejected++; // a malformed record never takes the dashboard down
      }
    }
  }

  private async initialise(): Promise<void> {
    const tail = await this.findTail();
    this.model = new LiveModel();
    let since = Math.max(0, tail - this.initialLines);
    for (;;) {
      const events = await this.fetchEvents(since, PAGE);
      this.ingest(events);
      if (events.length) since = events[events.length - 1].line;
      if (events.length < PAGE) break;
    }
    this.lastLine = Math.max(since, tail === 0 ? 0 : since);
    this.initialised = true;
    this.emptyPolls = 0;
  }

  /** Returns the number of lines received. */
  private async poll(): Promise<number> {
    const events = await this.fetchEvents(this.lastLine, PAGE);
    if (events.length) {
      this.ingest(events);
      this.lastLine = events[events.length - 1].line;
      this.emptyPolls = 0;
      return events.length;
    }
    // Nothing new for a while: make sure the cursor is not beyond the store (collector data was reset).
    if (++this.emptyPolls >= 20) {
      this.emptyPolls = 0;
      if (this.lastLine > 0 && !(await this.hasLineAfter(this.lastLine - 1))) this.initialised = false;
    }
    return 0;
  }
}
