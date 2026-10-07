import type { MessageInfo } from "../types/dashboard";
import { DatabaseIcon } from "./icons";
import { formatTime } from "./stateStyle";

interface Props {
  message: MessageInfo;
  /** When the dashboard last received data. */
  updatedAt: string;
}

export default function LastMessageCard({ message, updatedAt }: Props) {
  const { cells_reported: got, total_cells: total } = message;
  const missing = Array.from({ length: total }, (_, i) => i + 1).filter((c) => !got.includes(c));
  return (
    <section className="card compact" aria-label="Last message">
      <h2 className="card-title small">
        <span className="icon icon-blue"><DatabaseIcon /></span>Last Message
        <span className="updated">Last update: {formatTime(message.received_at ?? updatedAt)}</span>
      </h2>
      <dl className="kv">
        <dt>Seq:</dt>
        <dd>{message.seq}</dd>
        <dt>Latency:</dt>
        <dd>{message.latency_ms === null ? "n/a" : `${message.latency_ms} ms`}</dd>
        <dt>Cells:</dt>
        <dd>
          {got.length} of {total}
          {missing.length > 0 && <span className="kv-note"> · no cell {missing.join(", ")}</span>}
        </dd>
      </dl>
    </section>
  );
}
