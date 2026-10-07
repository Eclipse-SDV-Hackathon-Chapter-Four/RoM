import type { BatteryInfo } from "../types/dashboard";
import { ThermometerIcon } from "./icons";
import { CELL_STATUS_LABEL, formatTemp, tempTone } from "./stateStyle";

/** Display range of the indicator only. It is not a limit and not related to the sensor plausibility bounds. */
const SCALE_MIN = -40;
const SCALE_MAX = 70;
const pct = (v: number) => Math.min(100, Math.max(0, ((v - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)) * 100));

export default function BatteryCellsCard({ battery }: { battery: BatteryInfo }) {
  const { cells, pack_max_c: packMax, pack_max_cell: packCell, warn_c, crit_c } = battery;
  const warnAt = pct(warn_c);
  const critAt = pct(crit_c);
  const ticks = [SCALE_MIN, 0, warn_c, crit_c, SCALE_MAX];

  return (
    <section className="card cells-card" aria-label="Battery cells">
      <h2 className="card-title"><span className="icon icon-red"><ThermometerIcon /></span>Battery Cells</h2>

      <div className="cells" role="list">
        {cells.map((c) => {
          const ok = c.status === "OK";
          const hottest = ok && c.id === packCell;
          return (
            <div key={c.id} role="listitem"
                 className={`cell ${ok ? tempTone(c.temperature_c, warn_c, crit_c) : "cell-fault"}${hottest ? " cell-hottest" : ""}`}>
              <div className="cell-head">
                <span className="cell-name">CELL {c.id}</span>
                <span className={`cell-src src-${c.source.toLowerCase()}`} title={c.source === "HW" ? "Physical AZ3166 board" : "Simulator"}>
                  {c.source}
                </span>
              </div>
              <div className="cell-temp" aria-live="polite">
                {formatTemp(c.temperature_c)}<span className="cell-unit"> °C</span>
              </div>
              <div className="cell-status">
                <span className={`status-dot ${ok ? "ok" : "bad"}`} />
                {CELL_STATUS_LABEL[c.status]}
                {hottest && <span className="cell-maxtag">MAX</span>}
              </div>
            </div>
          );
        })}
      </div>

      <div className="pack">
        <div className="pack-max" aria-live="polite">
          <span className="pack-label">PACK MAX</span>
          <span className={`pack-value ${tempTone(packMax, warn_c, crit_c)}`}>
            {formatTemp(packMax)}<span className="pack-unit"> °C</span>
          </span>
          <span className="pack-cell">{packCell === null ? "no valid cell" : `Cell ${packCell}`}</span>
        </div>

        <div className="gauge">
          <div
            className="gauge-track"
            style={{
              background: `linear-gradient(90deg, #2f9e55 0%, #4cb86a ${warnAt}%, #f5b82e ${warnAt}%, #f59e2e ${critAt}%, #e5484d ${critAt}%, #b42328 100%)`,
            }}
          />
          {packMax !== null && <div className="gauge-marker" style={{ left: `${pct(packMax)}%` }} />}
          <div className="gauge-ticks">
            {ticks.map((t) => (
              <span key={t} style={{ left: `${pct(t)}%` }}>{t === SCALE_MAX ? `${t}+` : t}</span>
            ))}
          </div>
        </div>
      </div>

      <p className="card-note">
        Demo thresholds: warning ≥ {warn_c} °C, critical ≥ {crit_c} °C, applied to the hottest valid cell.
        A faulty cell is excluded from Pack Max.
      </p>
    </section>
  );
}
