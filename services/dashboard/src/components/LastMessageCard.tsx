import type { MessageInfo, SensorInfo } from "../types/dashboard";
import { DatabaseIcon } from "./icons";

export default function LastMessageCard({ message, sensor }: { message: MessageInfo; sensor: SensorInfo }) {
  return (
    <section className="card compact" aria-label="Last message">
      <h2 className="card-title small"><span className="icon icon-blue"><DatabaseIcon /></span>Last Message</h2>
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
