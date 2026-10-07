import type { MessageInfo, SensorInfo } from "../types/dashboard";
import { DatabaseIcon } from "./icons";
import { formatTime } from "./stateStyle";

interface Props {
  message: MessageInfo;
  sensor: SensorInfo;
  /** When the dashboard last received data. */
  updatedAt: string;
}

export default function LastMessageCard({ message, sensor, updatedAt }: Props) {
  return (
    <section className="card compact" aria-label="Last message">
      <h2 className="card-title small">
        <span className="icon icon-blue"><DatabaseIcon /></span>Last Message
        <span className="updated">Last update: {formatTime(updatedAt)}</span>
      </h2>
      <dl className="kv">
        <dt>Seq:</dt>
        <dd>{message.seq}</dd>
        <dt>Latency:</dt>
        <dd>{message.latency_ms === null ? "n/a" : `${message.latency_ms} ms`}</dd>
        <dt>Device:</dt>
        <dd className="mono">{sensor.device_id}</dd>
      </dl>
    </section>
  );
}
