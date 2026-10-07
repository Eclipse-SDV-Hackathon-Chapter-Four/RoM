import { useState } from "react";
import type { DemoControls as DemoControlSupport } from "../data/DashboardDataSource";
import type { DemoOverrideInfo, DemoScenario, DemoTarget } from "../types/dashboard";

const TARGETS: { id: DemoTarget; label: string }[] = [
  { id: "PACK", label: "Pack" },
  { id: 1, label: "C1" },
  { id: 2, label: "C2" },
  { id: 3, label: "C3" },
  { id: 4, label: "C4" },
];

/** Scenario buttons. `packLabel` is how the same action reads when the target is the whole pack. */
const SCENARIOS: { id: DemoScenario; label: string; packLabel?: string; hint: string }[] = [
  { id: "NORMAL", label: "Normal", hint: "back to nominal values" },
  { id: "WARNING", label: "Warning", hint: "heats up above 38 °C" },
  { id: "CRITICAL", label: "Critical", hint: "heats up above 45 °C" },
  { id: "STALE", label: "Stale", hint: "stops reporting, STALE after 2 s" },
  { id: "STUCK", label: "Stuck", packLabel: "All stuck", hint: "freezes at its last value, STUCK after 10 s" },
  { id: "OUT_OF_RANGE", label: "Out of range", packLabel: "All out of range", hint: "reports an implausible value" },
  { id: "STREAM_LOSS", label: "Stream loss", hint: "no cell reaches the Guardian" },
];

interface Props {
  support: DemoControlSupport;
  /** Set while a manual override is in force (comes with the data). */
  override: DemoOverrideInfo | null;
  onApply: (target: DemoTarget, scenario: DemoScenario) => void;
  onResume: () => void;
}

/**
 * Mock-only presentation controls: pick a target (the pack or one cell) and a scenario. They change simulated INPUTS;
 * the Guardian logic derives the state. They do not touch the real board. Collapsed by default.
 */
export default function DemoControls({ support, override, onApply, onResume }: Props) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<DemoTarget>("PACK");
  const isActive = (t: DemoTarget, s: DemoScenario) => !!override?.active.some((a) => a.target === t && a.scenario === s);

  return (
    <div className="scenarios" role="group" aria-label="Demo controls">
      <button type="button" className="scenario-btn toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        Demo controls {open ? "▾" : "▸"}
      </button>

      {!open && override && (
        <span className="override-chip" title="Simulated input override. Resume to return to the automatic loop.">
          Mock override: {override.label}
          <button type="button" className="chip-resume" onClick={onResume}>Resume live</button>
        </span>
      )}

      {open && (
        <>
          <span className="scenarios-label" title="Mock only: changes simulated inputs, never the real board">Target</span>
          <div className="seg" role="group" aria-label="Target">
            {TARGETS.map((t) => (
              <button key={String(t.id)} type="button" aria-pressed={target === t.id}
                      className={`scenario-btn seg-btn${target === t.id ? " active" : ""}`} onClick={() => setTarget(t.id)}>
                {t.label}
              </button>
            ))}
          </div>

          <span className="scenarios-label">Scenario</span>
          <div className="seg" role="group" aria-label="Scenario">
            {SCENARIOS.map((s) => {
              const why = support.unsupported(target, s.id);
              const label = target === "PACK" ? s.packLabel ?? s.label : s.label;
              return (
                <button key={s.id} type="button" disabled={why !== null} aria-pressed={isActive(target, s.id)}
                        title={why ?? `${target === "PACK" ? "Pack" : `Cell ${target}`}: ${s.hint}`}
                        className={`scenario-btn seg-btn${isActive(target, s.id) ? " active" : ""}`}
                        onClick={() => onApply(target, s.id)}>
                  {label}
                </button>
              );
            })}
          </div>

          <button type="button" className={`scenario-btn resume${override ? " armed" : ""}`} disabled={!override} onClick={onResume}
                  title="Drop every manual override and return to the automatic demo loop">
            Resume live
          </button>
          <span className="mock-note">Mock only</span>
        </>
      )}
    </div>
  );
}
