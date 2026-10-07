# Made with Claude (Claude Code, Anthropic)
"""Streams a sine-wave battery temperature (default 30-69 °C) for 4 cells into the KUKSA databroker.

    rom-simulator --hz 2 --period 120 --duration 0     # 0 = run until Ctrl+C

Writes Vehicle.Powertrain.TractionBattery.Cells.Cell1..4.Temperature (custom overlay, infra/vss/rom_overlay.json)
and Vehicle.Powertrain.TractionBattery.Temperature.Max = the hottest cell that was written. Cell 1 is the hottest,
so without faults Max is the plain wave. Run only one writer of each path at a time.

SIM_CELLS limits the cells it simulates (default 1,2,3,4). With a real board as cell 1 (`make hw`) run SIM_CELLS=2,3,4:
the simulator then leaves cell 1 and Max to the adapter. Every tick it also writes the heartbeat counters
Vehicle.RoM.Heartbeat.Simulator (always) and Vehicle.RoM.Heartbeat.Chip (a simulated chip, only if it owns cell 1).

Faults are injected over HTTP while it runs (SIM_API_PORT, see api.py and README.md): the signal of a cell can be
stuck, spiked, drifted or out of range, and the source can drop cells or stall (replay interruption).

With SIM_COOLING=1 it is also the cooling actuator: while the guardian is MITIGATING (its state over uProtocol) the
simulated cells cool down, see cooling.py.

Env defaults: SIM_HZ, SIM_PERIOD_S, SIM_MIN_C, SIM_MAX_C, SIM_DURATION_S, SIM_SEED, SIM_CELLS, SIM_API_HOST, SIM_API_PORT,
SIM_COOLING, SIM_COOLING_C_PER_S, SIM_COOLING_RELAX_C_PER_S (plus KUKSA_HOST/KUKSA_PORT, UP_*/ZENOH_*).
"""
import argparse
import os
import threading
import time
import uuid
from typing import Callable, Dict, Optional, Sequence

from rom_common import clock, jsonlog, kuksa
from rom_common.contracts import (COMPONENT_CHIP, COMPONENT_SIMULATOR, VSS_BATTERY_TEMP, VSS_CELL_TEMPS,
                                  VSS_HEARTBEAT_CHIP, VSS_HEARTBEAT_SIMULATOR)

from .api import build_api
from .cooling import Cooling
from .faults import FaultState
from .wave import cell_offsets, cell_temps


ALL_CELLS = tuple(range(1, len(VSS_CELL_TEMPS) + 1))


class Session:
    """Run context shared between the sample loop and the HTTP thread."""

    def __init__(self, seed: int = 0, run_id: Optional[str] = None):
        self._lock = threading.Lock()
        self.seed = seed
        self.run_id = run_id
        self._restart = False
        self._wave: dict = {}
        self._state: dict = {}

    def restart(self, seed: int, run_id: Optional[str], wave: Optional[dict] = None) -> None:
        """New run: the loop starts the wave over at t=0 with this seed (and wave = min_c / max_c / period_s)."""
        with self._lock:
            self.seed, self.run_id, self._restart, self._wave = seed, run_id, True, wave or {}

    def take_restart(self) -> Optional[dict]:
        """None if no restart is pending, else the wave overrides of the new run ({} = keep the current wave)."""
        with self._lock:
            if not self._restart:
                return None
            self._restart = False
            return self._wave

    def publish(self, **state) -> None:
        with self._lock:
            self._state = state

    def snapshot(self) -> dict:
        with self._lock:
            return {"run_id": self.run_id, "seed": self.seed, **self._state}


def run(sink: Callable[[Dict[str, float]], None], log, hz: float = 2.0, period_s: float = 120.0,
        min_c: float = 30.0, max_c: float = 69.0, duration_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        faults: Optional[FaultState] = None, session: Optional[Session] = None,
        cells: Sequence[int] = ALL_CELLS, cooling: Optional[Cooling] = None) -> int:
    """Send samples at `hz` until duration_s elapses (0 = forever). Returns the tick count.

    sink gets {vss_path: value} for the simulated cells that are reported, for Max (only if all four cells are
    simulated) and for the heartbeats. Without data (everything dropped out, or the source is stalled) only the
    heartbeats go out: the process is alive, the data is not. Ticks keep their schedule during faults.
    cooling (optional) lowers every simulated cell before the faults are applied.
    """
    cells = tuple(sorted(set(cells)))
    faults = faults if faults is not None else FaultState(monotonic)
    session = session if session is not None else Session()
    log.log("campaign_start", profile="sine", hz=hz, period_s=period_s, min_c=min_c, max_c=max_c,
            duration_s=duration_s, path=VSS_BATTERY_TEMP, cells=[VSS_CELL_TEMPS[c - 1] for c in cells],
            seed=session.seed, writes_max=cells == ALL_CELLS)
    total = int(duration_s * hz) if duration_s > 0 else None
    offsets = cell_offsets(session.seed, len(VSS_CELL_TEMPS))
    start, i, wave_t, beat = monotonic(), 0, 0.0, 0
    try:
        while total is None or i < total:
            new_run = session.take_restart()
            if new_run is not None:
                wave_t, offsets = 0.0, cell_offsets(session.seed, len(VSS_CELL_TEMPS))
                period_s, min_c, max_c = (new_run.get(k, v) for k, v in (("period_s", period_s), ("min_c", min_c),
                                                                       ("max_c", max_c)))
                if cooling is not None:
                    cooling.reset()
            for f in faults.expire():
                log.log("fault_cleared", reason="expired", **f.as_dict())
            stalled = faults.source_stalled()
            cooled = cooling.step() if cooling is not None else 0.0
            reported: Dict[int, float] = {}
            if not stalled:
                wave = {c: round(t + cooled, 2)
                        for c, t in zip(ALL_CELLS, cell_temps(wave_t, offsets, period_s, min_c, max_c))}
                reported = {c: v for c, v in faults.apply({c: wave[c] for c in cells}).items() if v is not None}
                wave_t += 1 / hz
            hottest = max(reported.values()) if reported else None
            values = {VSS_CELL_TEMPS[c - 1]: v for c, v in reported.items()}
            if reported and cells == ALL_CELLS:
                values[VSS_BATTERY_TEMP] = hottest
            beat += 1
            beats = []
            if not faults.heartbeat_lost(COMPONENT_SIMULATOR):
                values[VSS_HEARTBEAT_SIMULATOR] = float(beat)
                beats.append(COMPONENT_SIMULATOR)
            if 1 in cells and not faults.heartbeat_lost(COMPONENT_CHIP):
                values[VSS_HEARTBEAT_CHIP] = float(beat)
                beats.append(COMPONENT_CHIP)
            if values:
                sink(values)
            session.publish(source_time_s=round(wave_t, 3), stalled=stalled, cells=reported, max_c=hottest,
                            heartbeats=beats, faults=[f.as_dict() for f in faults.active()], cooling_c=cooled)
            log.log("sample", seq=i, temp_c=hottest, cells=reported, stalled=stalled, heartbeats=beats,
                    cooling_c=cooled, sent_ts_ms=clock.now_ms())
            i += 1
            sleep(max(0.0, start + i / hz - monotonic()))  # fixed schedule, no drift
    except KeyboardInterrupt:
        pass
    log.log("campaign_end", samples=i)
    return i


def _env(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def main(argv: Optional[list] = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--hz", type=float, default=_env("SIM_HZ", 2))
    p.add_argument("--period", type=float, default=_env("SIM_PERIOD_S", 120))
    p.add_argument("--min", type=float, default=_env("SIM_MIN_C", 30), dest="min_c")
    p.add_argument("--max", type=float, default=_env("SIM_MAX_C", 69), dest="max_c")
    p.add_argument("--duration", type=float, default=_env("SIM_DURATION_S", 0))
    p.add_argument("--seed", type=int, default=int(_env("SIM_SEED", 0)))
    p.add_argument("--cells", default=os.environ.get("SIM_CELLS", "1,2,3,4"),
                   help="cells to simulate, e.g. 2,3,4 when a real board is cell 1")
    p.add_argument("--api-host", default=os.environ.get("SIM_API_HOST", "127.0.0.1"))
    p.add_argument("--api-port", type=int, default=int(_env("SIM_API_PORT", 8080)), help="0 = no HTTP API")
    p.add_argument("--cooling", action="store_true",
                   default=os.environ.get("SIM_COOLING", "").lower() in ("1", "true", "yes"),
                   help="cool the cells while the guardian is MITIGATING (guardian state over uProtocol)")
    a = p.parse_args(argv)
    if a.hz <= 0 or a.period <= 0 or a.min_c >= a.max_c:
        p.error("need hz > 0, period > 0 and min < max")
    try:
        cells = tuple(sorted({int(c) for c in a.cells.split(",") if c.strip()}))
    except ValueError:
        cells = ()
    if not cells or not set(cells) <= set(ALL_CELLS):
        p.error(f"--cells / SIM_CELLS must list cells between 1 and {len(ALL_CELLS)}, e.g. 1,2,3,4")

    log = jsonlog.get_logger("simulator", run_id=uuid.uuid4().hex[:8])
    session, faults = Session(a.seed, log.run_id), FaultState()
    api = None
    if a.api_port > 0:
        try:
            api = build_api(session, faults, log, a.api_host, a.api_port).start()
            log.log("api_started", host=a.api_host, port=api.port)
        except OSError as e:  # e.g. port taken: the simulator is still useful without fault injection
            log.log("api_unavailable", host=a.api_host, port=a.api_port, error=str(e))
    cooling, transport = None, None
    if a.cooling:
        from .cooling import subscribe  # needs rom-uprotocol
        cooling = Cooling(_env("SIM_COOLING_C_PER_S", 3.0), _env("SIM_COOLING_RELAX_C_PER_S", 0.2))
        transport = subscribe(cooling, log)
    client = kuksa.open_client()
    try:
        run(lambda values: kuksa.set_values(client, values), log, a.hz, a.period, a.min_c, a.max_c, a.duration,
            faults=faults, session=session, cells=cells, cooling=cooling)
    finally:
        client.disconnect()
        if transport is not None:
            transport.close_sync()
        if api is not None:
            api.close()


if __name__ == "__main__":
    main()
