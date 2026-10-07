import type { ScenarioInfo } from "../data/DashboardDataSource";
import type { ScenarioId } from "../types/dashboard";

interface Props {
  scenarios: ScenarioInfo[];
  selected: ScenarioId;
  onSelect: (id: ScenarioId) => void;
}

export default function ScenarioControls({ scenarios, selected, onSelect }: Props) {
  return (
    <div className="scenarios" role="group" aria-label="Demo scenario">
      <span className="scenarios-label">Demo scenario</span>
      {scenarios.map((s) => (
        <button
          key={s.id}
          type="button"
          className={`scenario-btn scenario-${s.id.toLowerCase()}${s.id === selected ? " active" : ""}`}
          aria-pressed={s.id === selected}
          onClick={() => onSelect(s.id)}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
