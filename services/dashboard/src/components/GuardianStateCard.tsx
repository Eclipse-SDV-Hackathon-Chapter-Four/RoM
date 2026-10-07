import type { BatteryInfo, GuardianInfo } from "../types/dashboard";
import { ShieldIcon } from "./icons";
import { CELL_STATUS_LABEL, STATE_CLASS, STATE_LABEL } from "./stateStyle";

/** The Guardian state is a PACK state: it follows the hottest valid cell, not any single sensor. */
export default function GuardianStateCard({ guardian, battery }: { guardian: GuardianInfo; battery: BatteryInfo }) {
  const excluded = battery.cells.filter((c) => c.status !== "OK");
  return (
    <section className="card" aria-label="Guardian state">
      <h2 className="card-title"><span className="icon icon-green"><ShieldIcon /></span>Guardian State<span className="scope-tag">PACK</span></h2>
      <div className={`state-banner ${STATE_CLASS[guardian.state]}`} aria-live="polite">
        {STATE_LABEL[guardian.state]}
      </div>
      <p className="reason">
        Reason: <strong className={STATE_CLASS[guardian.state]}>{guardian.reason}</strong>
      </p>
      <p className="pack-note">
        {excluded.length === 0
          ? `Supervising all ${battery.cells.length} cells`
          : excluded.length === battery.cells.length
            ? "No valid cell left to supervise"
            : `Excluded: ${excluded.map((c) => `Cell ${c.id} ${CELL_STATUS_LABEL[c.status]}`).join(", ")}`}
      </p>
    </section>
  );
}
