import type { BatteryInfo, HistoryPoint } from "../types/dashboard";
import { ChartIcon } from "./icons";

interface Props {
  history: HistoryPoint[];
  battery: BatteryInfo;
  /** Snapshot time: the right edge of the x axis, so a lost signal shows up as a gap. */
  now: string;
}

const W = 760;
const H = 300;
const M = { left: 48, right: 14, top: 12, bottom: 30 };
const PW = W - M.left - M.right;
const PH = H - M.top - M.bottom;

const hhmm = (ms: number) => new Date(ms).toISOString().slice(11, 16);

export default function TemperatureChart({ history, battery, now }: Props) {
  const { warn_c, crit_c } = battery;
  const times = history.map((p) => Date.parse(p.timestamp));
  const t1 = Date.parse(now);
  const t0 = times.length ? Math.min(times[0], t1 - 60_000) : t1 - 600_000;

  // y range follows the data but always shows both thresholds; it implies no other limits.
  const temps = history.map((p) => p.temperature_c);
  const yMin = Math.floor(Math.min(25, ...temps) / 5) * 5 - 5;
  const yMax = Math.ceil(Math.max(crit_c + 10, ...temps) / 5) * 5 + 5;

  const x = (t: number) => M.left + ((t - t0) / (t1 - t0)) * PW;
  const y = (v: number) => M.top + (1 - (v - yMin) / (yMax - yMin)) * PH;

  const line = history.map((p, i) => `${i ? "L" : "M"}${x(times[i]).toFixed(1)},${y(p.temperature_c).toFixed(1)}`).join(" ");
  const last = history.length - 1;
  const area = history.length
    ? `${line} L${x(times[last]).toFixed(1)},${y(yMin)} L${x(times[0]).toFixed(1)},${y(yMin)} Z`
    : "";

  const yTicks: number[] = [];
  for (let v = Math.ceil(yMin / 10) * 10; v <= yMax; v += 10) yTicks.push(v);
  const xTicks: number[] = [];
  const step = 120_000;
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) xTicks.push(t);

  const signalLost = history.length > 0 && t1 - times[last] > 30_000;

  return (
    <section className="card chart-card" aria-label="Temperature history">
      <h2 className="card-title"><span className="icon"><ChartIcon /></span>Temperature History</h2>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Battery temperature over time with warning at ${warn_c} °C and critical at ${crit_c} °C`}>
        <defs>
          <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        <rect x={M.left} y={y(warn_c)} width={PW} height={y(yMin) - y(warn_c)} fill="#1f7a45" opacity="0.2" />
        <rect x={M.left} y={y(crit_c)} width={PW} height={y(warn_c) - y(crit_c)} fill="#b7791f" opacity="0.28" />
        <rect x={M.left} y={M.top} width={PW} height={y(crit_c) - M.top} fill="#9b2c2c" opacity="0.3" />

        {yTicks.map((v) => (
          <g key={v}>
            <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} className="grid-line" />
            <text x={M.left - 8} y={y(v) + 4} textAnchor="end" className="axis">{v}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={M.top} y2={M.top + PH} className="grid-line" />
            <text x={x(t)} y={H - 8} textAnchor="middle" className="axis">{hhmm(t)}</text>
          </g>
        ))}

        <line x1={M.left} x2={W - M.right} y1={y(warn_c)} y2={y(warn_c)} stroke="#f5b82e" strokeDasharray="5 4" />
        <line x1={M.left} x2={W - M.right} y1={y(crit_c)} y2={y(crit_c)} stroke="#e5484d" strokeDasharray="5 4" />
        <text x={M.left + 10} y={y(crit_c) - 8} className="zone zone-critical">CRITICAL (≥ {crit_c} °C)</text>
        <text x={M.left + 10} y={y(warn_c) - 8} className="zone zone-warning">WARNING (≥ {warn_c} °C)</text>
        <text x={M.left + 10} y={y(yMin) - 8} className="zone zone-normal">NORMAL</text>

        {area && <path d={area} fill="url(#area)" />}
        {line && <path d={line} fill="none" stroke="#38bdf8" strokeWidth="2.2" strokeLinejoin="round" />}
        {history.length > 0 && <circle cx={x(times[last])} cy={y(history[last].temperature_c)} r="4" fill="#38bdf8" />}

        {signalLost && (
          <g>
            <line x1={x(times[last])} x2={x(times[last])} y1={M.top} y2={M.top + PH} stroke="#a78bfa" strokeDasharray="3 4" />
            <text x={x(times[last]) - 6} y={M.top + 16} textAnchor="end" className="zone zone-fault">signal lost</text>
          </g>
        )}
        <text transform={`translate(12 ${M.top + PH / 2}) rotate(-90)`} textAnchor="middle" className="axis">Temperature (°C)</text>
      </svg>
    </section>
  );
}
