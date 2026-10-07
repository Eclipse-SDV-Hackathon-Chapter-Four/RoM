import type { CellInfo, GuardianEvent } from "../types/dashboard";
import { ClockIcon } from "./icons";
import { matchesFilter, type EventFilter } from "./selection";
import { CELL_STATUS_LABEL, cellColor, formatTemp, formatTime, STATE_CLASS, STATE_LABEL } from "./stateStyle";

function badge(e: GuardianEvent) {
  if (e.kind === "state") return <span className={`badge ${STATE_CLASS[e.state]}`}>{STATE_LABEL[e.state]}</span>;
  return e.stage === "FAILED"
    ? <span className="badge badge-fault">FAULT</span>
    : <span className="badge badge-cleared">CLEARED</span>;
}

const scopeBadge = (e: GuardianEvent) =>
  e.kind === "fault" && e.cell !== null
    ? <span className="scope-badge" style={{ "--cc": cellColor(e.cell) } as React.CSSProperties}>C{e.cell}</span>
    : <span className="scope-badge scope-pack">PACK</span>;

const FILTERS: { id: EventFilter; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "PACK", label: "Pack" },
  { id: 1, label: "C1" },
  { id: 2, label: "C2" },
  { id: 3, label: "C3" },
  { id: 4, label: "C4" },
];

/** Current state of one cell as a single line: shown above the event table of a cell filter. */
function CellLine({ cell }: { cell: CellInfo }) {
  const ok = cell.status === "OK";
  return (
    <div className="cell-line" title={cell.fault_code ?? undefined}>
      <strong>Cell {cell.id}</strong>
      <span className={`cell-src src-${cell.source.toLowerCase()}`}>{cell.source}</span>
      <span className={`focus-status ${ok ? "ok" : "bad"}`}>{CELL_STATUS_LABEL[cell.status]}</span>
      <span className={cell.in_pack ? "focus-in" : "focus-out"}>{cell.in_pack ? "INCLUDED" : "EXCLUDED"}</span>
    </div>
  );
}

/** Shown instead of an empty table: what the cell looks like right now. Values come straight from the live data. */
function CellSummary({ cell }: { cell: CellInfo }) {
  const ok = cell.status === "OK";
  return (
    <div className="cell-summary">
      <p className="cell-summary-note">
        {ok ? `No diagnostic faults for Cell ${cell.id} in the recent history.` : "No additional events in this window."}
      </p>
      <dl className="cell-summary-kv">
        <dt>Current status</dt>
        <dd><span className={`focus-status ${ok ? "ok" : "bad"}`}>{CELL_STATUS_LABEL[cell.status]}</span></dd>
        <dt>{ok ? "Current temp" : "Last valid temp"}</dt>
        <dd>{formatTemp(ok ? cell.temperature_c : cell.last_valid_c)} °C</dd>
        <dt>Source</dt>
        <dd>{cell.source}</dd>
        <dt>Pack calculation</dt>
        <dd className={cell.in_pack ? "focus-in" : "focus-out"}>{cell.in_pack ? "INCLUDED" : "EXCLUDED"}</dd>
        <dt>Active fault</dt>
        <dd className={cell.fault_code ? "focus-fault mono" : "muted"} title={cell.fault_code ?? undefined}>{cell.fault_code ?? "None"}</dd>
      </dl>
    </div>
  );
}

interface Props {
  events: GuardianEvent[];
  /** Current cells, for the per-cell summary. */
  cells: CellInfo[];
  filter: EventFilter;
  onFilter: (f: EventFilter) => void;
}

/**
 * Guardian state changes and DFM diagnostic faults in one list, filtered by scope. A cell fault is a diagnostic event
 * of that cell; it never appears as a pack state change unless the Guardian itself went to SENSOR_FAULT.
 */
export default function RecentEvents({ events, cells, filter, onFilter }: Props) {
  const shown = events.filter((e) => matchesFilter(e, filter));
  const cell = typeof filter === "number" ? cells.find((c) => c.id === filter) : undefined;
  return (
    <section className="card events-card" aria-label="Recent events">
      <h2 className="card-title"><span className="icon"><ClockIcon /></span>Recent Events</h2>
      <div className="event-filters" role="group" aria-label="Filter events by scope">
        {FILTERS.map((f) => (
          <button key={String(f.id)} type="button" aria-pressed={filter === f.id}
                  className={`chip${typeof f.id === "number" ? " chip-cell" : ""}`}
                  style={typeof f.id === "number" ? ({ "--cc": cellColor(f.id) } as React.CSSProperties) : undefined}
                  onClick={() => onFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>
      {cell && shown.length > 0 && <CellLine cell={cell} />}
      <div className="events-scroll">
      {cell && shown.length === 0 ? <CellSummary cell={cell} /> : (
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
          {shown.map((e) => (
            <tr key={e.id} title={e.code}>
              <td className="mono">{formatTime(e.timestamp)}</td>
              <td>{badge(e)}</td>
              <td>{scopeBadge(e)}</td>
              <td className="reason-cell">{e.reason}</td>
            </tr>
          ))}
          {shown.length === 0 && (
            <tr className="events-empty"><td colSpan={4}>No events.</td></tr>
          )}
        </tbody>
      </table>
      )}
      </div>
    </section>
  );
}
