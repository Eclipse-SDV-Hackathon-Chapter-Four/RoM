import type { GuardianEvent } from "../types/dashboard";
import { ClockIcon } from "./icons";
import { formatTemp, formatTime, STATE_CLASS, STATE_LABEL } from "./stateStyle";

export default function RecentEvents({ events }: { events: GuardianEvent[] }) {
  return (
    <section className="card events-card" aria-label="Recent events">
      <h2 className="card-title"><span className="icon"><ClockIcon /></span>Recent Events</h2>
      <div className="events-scroll">
      <table className="events">
        <thead>
          <tr>
            <th>Time</th>
            <th>State</th>
            <th>Reason</th>
            <th className="num">Temp (°C)</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={`${e.timestamp}-${e.state}-${e.reason}`}>
              <td className="mono">{formatTime(e.timestamp)}</td>
              <td><span className={`badge ${STATE_CLASS[e.state]}`}>{STATE_LABEL[e.state]}</span></td>
              <td>{e.reason}</td>
              <td className="num">{formatTemp(e.temperature_c)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </section>
  );
}
