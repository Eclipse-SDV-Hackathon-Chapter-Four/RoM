import type { GuardianEvent } from "../types/dashboard";
import { ClockIcon } from "./icons";
import { formatTime, STATE_CLASS, STATE_LABEL } from "./stateStyle";

function badge(e: GuardianEvent) {
  if (e.kind === "state") return <span className={`badge ${STATE_CLASS[e.state]}`}>{STATE_LABEL[e.state]}</span>;
  return e.stage === "FAILED"
    ? <span className="badge badge-fault">FAULT</span>
    : <span className="badge badge-cleared">CLEARED</span>;
}

/** Guardian state changes (pack) and DFM diagnostic faults (cell or pack) in one list; the Scope column tells them apart. */
export default function RecentEvents({ events }: { events: GuardianEvent[] }) {
  return (
    <section className="card events-card" aria-label="Recent events">
      <h2 className="card-title"><span className="icon"><ClockIcon /></span>Recent Events</h2>
      <div className="events-scroll">
      <table className="events">
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Scope</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} title={e.code}>
              <td className="mono">{formatTime(e.timestamp)}</td>
              <td>{badge(e)}</td>
              <td>{e.kind === "fault" && e.cell !== null ? `Cell ${e.cell}` : "Pack"}</td>
              <td className="reason-cell">{e.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </section>
  );
}
