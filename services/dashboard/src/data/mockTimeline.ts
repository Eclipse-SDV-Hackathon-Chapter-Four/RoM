import type { DashboardData, GuardianEvent, GuardianState, HistoryPoint, ScenarioId } from "../types/dashboard";

/**
 * Deterministic, loopable demo stream. One Step = one simulated message period. The states and reasons follow
 * what services/guardian really produces for such a temperature curve (WARN_C 38, CRIT_C 45, stale after 2 s,
 * CRITICAL "too hot" -> MITIGATING -> "mitigation failed" after 5 s, back to MONITORING below WARN_C).
 */
interface Step {
  /** Temperature of the message received in this period; null = no message arrived. */
  temp: number | null;
  state: GuardianState;
  reason: string;
  /** Defaults to ONLINE. */
  sensor?: "ONLINE" | "OFFLINE";
}

const monitoring = (temps: number[]): Step[] => temps.map((temp) => ({ temp, state: "MONITORING", reason: "temp ok" }));
const warning = (temps: number[]): Step[] => temps.map((temp) => ({ temp, state: "WARNING", reason: "getting hot" }));
const critical = (reason: string, temps: number[]): Step[] => temps.map((temp) => ({ temp, state: "CRITICAL", reason }));
const mitigating = (reason: string, temps: number[]): Step[] => temps.map((temp) => ({ temp, state: "MITIGATING", reason }));

const SEGMENTS: { scenario: ScenarioId | null; steps: Step[] }[] = [
  { scenario: "NORMAL", steps: monitoring([31.0, 31.4, 31.9, 32.3, 32.9, 33.4, 34.0, 34.6, 35.3, 36.0, 36.6, 37.2]) },
  { scenario: "WARNING", steps: warning([38.2, 39.0, 39.5, 40.3, 41.0, 41.9, 43.0]) },
  {
    scenario: "CRITICAL",
    steps: [
      ...critical("too hot", [45.2]),
      ...mitigating("cooling requested", [46.0]),
      ...mitigating("cooling in progress", [46.6, 47.1, 47.5, 47.9, 48.2]),
      ...critical("mitigation failed", [48.4, 48.6, 48.4, 47.0, 45.5, 44.0, 41.0]),
    ],
  },
  { scenario: null, steps: monitoring([37.0, 34.0, 33.0, 32.2, 31.8, 31.5, 31.3, 31.1, 31.0, 31.2, 31.1, 31.0]) },
  {
    scenario: "SENSOR_FAULT",
    steps: [
      // Messages stop. The Guardian only flags the signal stale after 2 s, so the first two periods still look fine.
      { temp: null, state: "MONITORING", reason: "temp ok" },
      { temp: null, state: "MONITORING", reason: "temp ok" },
      ...Array.from({ length: 6 }, (): Step => ({ temp: null, state: "SENSOR_FAULT", reason: "stale signal", sensor: "OFFLINE" })),
    ],
  },
  { scenario: null, steps: monitoring([31.0, 30.9, 31.1, 31.0, 31.2, 31.1]) },
];

const FLAT: Step[] = SEGMENTS.flatMap((s) => s.steps);
const SEGMENT_START: Partial<Record<ScenarioId, number>> = {};
{
  let at = 0;
  for (const seg of SEGMENTS) {
    if (seg.scenario && SEGMENT_START[seg.scenario] === undefined) SEGMENT_START[seg.scenario] = at;
    at += seg.steps.length;
  }
}

const HISTORY_POINTS = 120;
const MAX_EVENTS = 20;
const DEVICE_ID = "az3166-01";
const WARN_C = 38;
const CRIT_C = 45;

export class TimelineEngine {
  private index = 0;
  private seq = 1800;
  private latency = 90;
  private lastTemp = 31.0;
  private lastKey = "MONITORING|temp ok";
  private history: HistoryPoint[] = [];
  private events: GuardianEvent[] = [];

  constructor(now: Date, tickMs: number) {
    // Start with a minute of calm history so the chart is not empty, and one initial event.
    const prefill = Math.round(60_000 / tickMs);
    for (let i = prefill; i > 0; i--) {
      this.history.push({
        timestamp: new Date(now.getTime() - i * tickMs).toISOString(),
        temperature_c: Math.round((30.9 + 0.25 * Math.sin(i / 3)) * 10) / 10,
      });
    }
    this.events.push({
      timestamp: new Date(now.getTime() - 60_000).toISOString(),
      state: "MONITORING",
      reason: "temp ok",
      temperature_c: 31.0,
    });
  }

  /** Jump the stream to the start of a situation (demo controls only). */
  jumpTo(id: ScenarioId): void {
    this.index = SEGMENT_START[id] ?? 0;
  }

  /** Advances one message period and returns the resulting snapshot. */
  step(now: Date): DashboardData {
    const st = FLAT[this.index];
    this.index = (this.index + 1) % FLAT.length;
    const timestamp = now.toISOString();

    if (st.temp !== null) {
      this.seq += 1;
      this.latency = 80 + ((this.seq * 37) % 41); // 80..120 ms, repeatable
      this.lastTemp = st.temp;
      this.history.push({ timestamp, temperature_c: st.temp });
      if (this.history.length > HISTORY_POINTS) this.history.shift();
    }

    const shownTemp = st.state === "SENSOR_FAULT" ? null : st.temp ?? this.lastTemp;

    const key = `${st.state}|${st.reason}`;
    if (key !== this.lastKey) {
      this.lastKey = key;
      this.events.unshift({ timestamp, state: st.state, reason: st.reason, temperature_c: shownTemp });
      if (this.events.length > MAX_EVENTS) this.events.pop();
    }

    return {
      timestamp,
      battery: { temperature_c: shownTemp, warn_c: WARN_C, crit_c: CRIT_C },
      guardian: { state: st.state, reason: st.reason },
      sensor: { status: st.sensor ?? "ONLINE", device_id: DEVICE_ID },
      message: { seq: this.seq, latency_ms: this.latency },
      history: [...this.history],
      events: [...this.events],
    };
  }
}
