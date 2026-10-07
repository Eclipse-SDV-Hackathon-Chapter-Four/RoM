import type { GuardianInfo } from "../types/dashboard";
import { ShieldIcon } from "./icons";
import { STATE_CLASS, STATE_LABEL } from "./stateStyle";

export default function GuardianStateCard({ guardian }: { guardian: GuardianInfo }) {
  return (
    <section className="card" aria-label="Guardian state">
      <h2 className="card-title"><span className="icon icon-green"><ShieldIcon /></span>Guardian State</h2>
      <div className={`state-banner ${STATE_CLASS[guardian.state]}`} aria-live="polite">
        {STATE_LABEL[guardian.state]}
      </div>
      <p className="reason">
        Reason: <strong className={STATE_CLASS[guardian.state]}>{guardian.reason}</strong>
      </p>
    </section>
  );
}
