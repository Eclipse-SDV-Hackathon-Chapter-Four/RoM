import type { SourceInfo } from "../types/dashboard";
import type { SourceStatus } from "../types/dashboard";
import { SignalIcon } from "./icons";

/** What each status means; none of them says "offline" unless a heartbeat explicitly reported the source down. */
const STATUS: Record<SourceStatus, { label: string; good: boolean; hint: string }> = {
  RECEIVING: { label: "RECEIVING", good: true, hint: "its cells are reaching the Guardian" },
  NO_DATA: { label: "NO DATA", good: false, hint: "no telemetry received, cause unknown (source, transport, KUKSA or uProtocol)" },
  ALIVE: { label: "ALIVE", good: true, hint: "its heartbeat reports ok" },
  DOWN: { label: "DOWN", good: false, hint: "its heartbeat explicitly reports down" },
  NO_HEARTBEAT: { label: "NO HEARTBEAT", good: false, hint: "no heartbeat seen recently, state unknown" },
};

const cellsText = (ids: number[]) =>
  ids.length === 0 ? "not used" : ids.length === 1 ? `Cell ${ids[0]}` : `Cells ${ids[0]}–${ids[ids.length - 1]}`;

export default function DataSourcesCard({ sources }: { sources: SourceInfo[] }) {
  return (
    <section className="card compact" aria-label="Data sources">
      <h2 className="card-title small"><span className="icon icon-blue"><SignalIcon /></span>Data Sources</h2>
      <ul className="sources">
        {sources.map((s) => {
          const st = STATUS[s.status];
          return (
            <li key={s.id} title={`${s.detail}: ${st.hint}`}>
              <span className={`dot ${st.good ? "dot-on" : "dot-off"}`} />
              <span className="src-name">{s.name}</span>
              <span className="src-cells">{cellsText(s.cells)}</span>
              <span className={`src-status ${st.good ? "on" : "off"}`}>{st.label}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
