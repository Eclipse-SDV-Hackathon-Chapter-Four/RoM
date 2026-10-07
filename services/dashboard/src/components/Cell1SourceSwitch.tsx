// Made with Claude (Claude Code, Anthropic)
import type { useCell1Source } from "../data/cell1Source";

type Props = ReturnType<typeof useCell1Source>;

/** Cell 1 comes from exactly one writer: the AZ3166 board or the simulator. */
export default function Cell1SourceSwitch({ state, error, busy, set }: Props) {
  const mode = state?.mode;
  return (
    <div className="cell1-switch" role="group" aria-label="Cell 1 source">
      <span className="cell1-label">Cell 1</span>
      <button type="button" className={`scenario-btn${mode === "hw" ? " active" : ""}`} aria-pressed={mode === "hw"}
              disabled={busy || !state?.hwAvailable} onClick={() => set("hw")}
              title={state?.hwAvailable ? "Real readings from the AZ3166 sensor; the simulator leaves cell 1 alone" : "The adapter is not running"}>
        AZ3166 sensor
      </button>
      <button type="button" className={`scenario-btn${mode === "sim" ? " active" : ""}`} aria-pressed={mode === "sim"}
              disabled={busy || !state} onClick={() => set("sim")}
              title="Simulated readings; the board's readings are not written">
        Simulator
      </button>
      {mode === "both" && <span className="scenario-status bad" role="alert">Two writers on cell 1: pick one</span>}
      {mode === "none" && <span className="scenario-status bad" role="alert">Nobody writes cell 1</span>}
      {error && <span className="scenario-status bad" title={error}>Source switch unavailable</span>}
    </div>
  );
}
