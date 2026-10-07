import type { BatteryInfo } from "../types/dashboard";
import type { CellSelection } from "./selection";
import { CELL_STATUS_LABEL, cellColor, formatTemp, formatTime } from "./stateStyle";

interface Props {
  battery: BatteryInfo;
  selection: CellSelection;
  onShowAll: () => void;
}

/** One compact line under the chart title: pack overview, or the details of the selected cell. */
export default function ChartFocusBar({ battery, selection, onShowAll }: Props) {
  if (selection === "ALL") {
    const { cells, pack_max_c: max, pack_max_cell: maxCell } = battery;
    const valid = cells.filter((c) => c.in_pack).length;
    return (
      <div className="focus-bar" aria-live="polite">
        <strong>Viewing: All cells</strong>
        <span>Pack Max {max === null ? "--" : `${formatTemp(max)} °C`}{maxCell !== null && ` (Cell ${maxCell})`}</span>
        <span>{valid} of {cells.length} cells valid</span>
        <span className="focus-hint">Click a cell above to focus it</span>
      </div>
    );
  }

  const cell = battery.cells.find((c) => c.id === selection);
  if (!cell) return null;
  const ok = cell.status === "OK";
  return (
    <div className="focus-bar" aria-live="polite">
      <strong><span className="focus-swatch" style={{ background: cellColor(cell.id) }} />Viewing: Cell {cell.id}</strong>
      <span className={`cell-src src-${cell.source.toLowerCase()}`}>{cell.source}</span>
      <span className={`focus-status ${ok ? "ok" : "bad"}`}>{CELL_STATUS_LABEL[cell.status]}</span>
      <span>Now {formatTemp(cell.temperature_c)} °C</span>
      <span>Last valid {cell.last_valid_c === null ? "--" : `${formatTemp(cell.last_valid_c)} °C`}</span>
      <span>Updated {cell.last_update ? formatTime(cell.last_update) : "--"}</span>
      <span className={cell.in_pack ? "focus-in" : "focus-out"}>Pack: {cell.in_pack ? "INCLUDED" : "EXCLUDED"}</span>
      {cell.fault_code && <span className="focus-fault mono" title={cell.fault_code}>{cell.fault_code}</span>}
      <button type="button" className="focus-showall" onClick={onShowAll}>Show all</button>
    </div>
  );
}
