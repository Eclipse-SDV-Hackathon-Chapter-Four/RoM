import { useEffect, useRef, useState } from "react";
import type { BatteryInfo, HistoryPoint } from "../types/dashboard";
import { ChartIcon } from "./icons";
import ChartFocusBar from "./ChartFocusBar";
import type { CellSelection } from "./selection";
import { cellColor, formatTime } from "./stateStyle";

interface Props {
  history: HistoryPoint[];
  battery: BatteryInfo;
  /** Snapshot time: the right edge of the x axis, so a lost signal shows up as a gap. */
  now: string;
  selection: CellSelection;
  onShowAll: () => void;
}

const M = { left: 48, right: 14, top: 12, bottom: 30 };

/** Smallest "round" tick spacing that gives at most eight labels for the visible time span. */
const TICK_STEPS_MS = [10_000, 20_000, 30_000, 60_000, 120_000, 300_000];
const tickStep = (spanMs: number) => TICK_STEPS_MS.find((s) => spanMs / s <= 8) ?? TICK_STEPS_MS[TICK_STEPS_MS.length - 1];

export default function TemperatureChart({ history, battery, now, selection, onShowAll }: Props) {
  // The SVG viewBox follows the container, so the chart fills whatever height the layout gives it
  // and text keeps its real pixel size (no stretching).
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 760, h: 300 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const W = size.w;
  const H = size.h;
  const PW = W - M.left - M.right;
  const PH = H - M.top - M.bottom;

  const { warn_c, crit_c, cells, pack_max_cell: hottest } = battery;
  const times = history.map((p) => Date.parse(p.timestamp));
  const t1 = Date.parse(now);
  const t0 = times.length ? Math.min(times[0], t1 - 60_000) : t1 - 600_000;

  // y range follows the data but always shows both thresholds; it implies no other limits.
  const temps = history.flatMap((p) => Object.values(p.cells).filter((v): v is number => v !== null));
  const yMin = Math.floor(Math.min(25, ...temps) / 5) * 5 - 5;
  const yMax = Math.ceil(Math.max(crit_c + 10, ...temps) / 5) * 5 + 5;

  const x = (t: number) => M.left + ((t - t0) / (t1 - t0)) * PW;
  const y = (v: number) => M.top + (1 - (v - yMin) / (yMax - yMin)) * PH;

  /** One path per cell. A missing / untrusted reading (null) breaks the line instead of being interpolated. */
  const pathFor = (id: number) => {
    let d = "";
    let pen = false;
    history.forEach((p, i) => {
      const v = p.cells[id] ?? null;
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(times[i]).toFixed(1)},${y(v).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };

  const last = history.length - 1;
  const yTicks: number[] = [];
  for (let v = Math.ceil(yMin / 10) * 10; v <= yMax; v += 10) yTicks.push(v);
  const xTicks: number[] = [];
  const step = tickStep(t1 - t0);
  // stop short of the right edge: a centred label there would be clipped
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) if (x(t) <= W - M.right - 24) xTicks.push(t);

  const signalLost = history.length > 0 && t1 - times[last] > 3_000;
  // Emphasised cell: the selected one, or in the pack overview the hottest valid cell (Pack Max). It is drawn last,
  // on top, and thicker; with a selection the other lines stay visible but fade.
  const focus = selection === "ALL" ? null : selection;
  const emphasised = focus ?? hottest;
  const order = [...cells].sort((a, b) => Number(a.id === emphasised) - Number(b.id === emphasised));

  return (
    <section className="card chart-card" aria-label="Temperature history">
      <h2 className="card-title">
        <span className="icon"><ChartIcon /></span>Temperature History
        <ul className="legend" aria-label="Legend">
          {cells.map((c) => (
            <li key={c.id} className={c.status === "OK" ? "" : "legend-off"}>
              <span className="legend-line" style={{ background: cellColor(c.id) }} />
              Cell {c.id}
              <span className="legend-src">{c.source}</span>
            </li>
          ))}
          <li className="legend-note"><span className="legend-thick" />{focus === null ? "Thick line = Pack Max" : `Thick line = Cell ${focus}`}</li>
        </ul>
      </h2>
      <ChartFocusBar battery={battery} selection={selection} onShowAll={onShowAll} />
      <div className="chart-wrap" ref={wrapRef}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Temperature of the four battery cells over time with warning at ${warn_c} °C and critical at ${crit_c} °C`}>
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
            <text x={x(t)} y={H - 8} textAnchor="middle" className="axis">{formatTime(t).slice(0, step < 60_000 ? 8 : 5)}</text>
          </g>
        ))}

        <line x1={M.left} x2={W - M.right} y1={y(warn_c)} y2={y(warn_c)} stroke="#f5b82e" strokeDasharray="5 4" />
        <line x1={M.left} x2={W - M.right} y1={y(crit_c)} y2={y(crit_c)} stroke="#e5484d" strokeDasharray="5 4" />
        {PH >= 100 && ( // on a very short chart the zone names would collide; the dashed threshold lines remain
          <>
            <text x={M.left + 10} y={y(crit_c) - 8} className="zone zone-critical">CRITICAL (≥ {crit_c} °C)</text>
            <text x={M.left + 10} y={y(warn_c) - 8} className="zone zone-warning">WARNING (≥ {warn_c} °C)</text>
            <text x={M.left + 10} y={y(yMin) - 8} className="zone zone-normal">NORMAL</text>
          </>
        )}

        {order.map((c) => {
          const d = pathFor(c.id);
          const isMax = c.id === emphasised;
          const dim = focus !== null && c.id !== focus;
          const tail = last >= 0 ? history[last].cells[c.id] ?? null : null;
          return (
            <g key={c.id}>
              {d && <path d={d} fill="none" stroke={cellColor(c.id)} strokeWidth={isMax ? 3.4 : dim ? 1.4 : 1.8}
                          strokeLinejoin="round" strokeLinecap="round" opacity={isMax ? 1 : dim ? 0.4 : 0.85} />}
              {tail !== null && (
                <circle cx={x(times[last])} cy={y(tail)} r={isMax ? 5 : 3.5} fill={cellColor(c.id)} opacity={dim ? 0.5 : 1}
                        stroke={isMax ? "#fff" : "none"} strokeWidth="1.5" />
              )}
            </g>
          );
        })}

        {signalLost && (
          <g>
            <line x1={x(times[last])} x2={x(times[last])} y1={M.top} y2={M.top + PH} stroke="#a78bfa" strokeDasharray="3 4" />
            <text x={x(times[last]) - 6} y={M.top + 16} textAnchor="end" className="zone zone-fault">signal lost</text>
          </g>
        )}
        <text transform={`translate(12 ${M.top + PH / 2}) rotate(-90)`} textAnchor="middle" className="axis">Temperature (°C)</text>
      </svg>
      </div>
    </section>
  );
}
