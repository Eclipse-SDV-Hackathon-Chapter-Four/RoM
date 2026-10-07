import type { BatteryInfo } from "../types/dashboard";
import { ThermometerIcon } from "./icons";
import { formatTemp } from "./stateStyle";

/** Display range of the indicator only. It is not a limit and not related to the sensor plausibility bounds. */
const SCALE_MIN = -40;
const SCALE_MAX = 70;
const pct = (v: number) => Math.min(100, Math.max(0, ((v - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)) * 100));

export default function TemperatureCard({ battery }: { battery: BatteryInfo }) {
  const { temperature_c: temp, warn_c, crit_c } = battery;
  const warnAt = pct(warn_c);
  const critAt = pct(crit_c);
  const ticks = [SCALE_MIN, 0, warn_c, crit_c, SCALE_MAX];

  return (
    <section className="card temp-card" aria-label="Battery temperature">
      <h2 className="card-title"><span className="icon icon-red"><ThermometerIcon /></span>Battery Temperature</h2>
      <div className="temp-value" aria-live="polite">
        {formatTemp(temp)}
        <span className="temp-unit"> °C</span>
      </div>

      <div className="gauge">
        <div
          className="gauge-track"
          style={{
            background: `linear-gradient(90deg, #2f9e55 0%, #4cb86a ${warnAt}%, #f5b82e ${warnAt}%, #f59e2e ${critAt}%, #e5484d ${critAt}%, #b42328 100%)`,
          }}
        />
        {temp !== null && <div className="gauge-marker" style={{ left: `${pct(temp)}%` }} />}
        <div className="gauge-ticks">
          {ticks.map((t) => (
            <span key={t} style={{ left: `${pct(t)}%` }}>{t === SCALE_MAX ? `${t}+` : t}</span>
          ))}
        </div>
      </div>

      <p className="card-note">
        Demo thresholds: warning ≥ {warn_c} °C, critical ≥ {crit_c} °C. These are conservative supervisory
        settings, not universal limits.
      </p>
    </section>
  );
}
