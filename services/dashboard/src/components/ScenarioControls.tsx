import { useState } from "react";
import type { ScenarioSupport } from "../data/DashboardDataSource";

/** Optional, for testing only: jump the simulated stream to a situation. The demo does not need it. */
export default function ScenarioControls({ support }: { support: ScenarioSupport }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="scenarios" role="group" aria-label="Demo controls">
      <button type="button" className="scenario-btn toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        Demo controls {open ? "▾" : "▸"}
      </button>
      {open && (
        <>
          <span className="scenarios-label">Jump to</span>
          {support.list().map((s) => (
            <button key={s.id} type="button" className={`scenario-btn scenario-${s.id.toLowerCase()}`} onClick={() => support.select(s.id)}>
              {s.label}
            </button>
          ))}
        </>
      )}
    </div>
  );
}
