import type { SourceInfo } from "../types/dashboard";
import { SignalIcon } from "./icons";

const cellsText = (ids: number[]) => (ids.length === 1 ? `Cell ${ids[0]}` : `Cells ${ids[0]}–${ids[ids.length - 1]}`);

export default function DataSourcesCard({ sources }: { sources: SourceInfo[] }) {
  return (
    <section className="card compact" aria-label="Data sources">
      <h2 className="card-title small"><span className="icon icon-blue"><SignalIcon /></span>Data Sources</h2>
      <ul className="sources">
        {sources.map((s) => (
          <li key={s.id} title={s.status === "NO_DATA" ? `${s.detail}: no telemetry received, cause unknown (source, transport, KUKSA or uProtocol)` : s.detail}>
            <span className={`dot ${s.status === "RECEIVING" ? "dot-on" : "dot-off"}`} />
            <span className="src-name">{s.name}</span>
            <span className="src-cells">{cellsText(s.cells)}</span>
            <span className={`src-status ${s.status === "RECEIVING" ? "on" : "off"}`}>{s.status === "RECEIVING" ? "RECEIVING" : "NO DATA"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
