# Made with Claude (Claude Code, Anthropic)
"""Streams a sine-wave battery temperature (default 30-69 °C) for 4 cells into the KUKSA databroker.

    rom-simulator --hz 2 --period 120 --duration 0     # 0 = run until Ctrl+C

Writes Vehicle.Powertrain.TractionBattery.Cells.Cell1..4.Temperature (custom overlay, infra/vss/rom_cells.json)
and Vehicle.Powertrain.TractionBattery.Temperature.Max = the hottest cell that was written. Cell 1 is the hottest,
so without faults Max is the plain wave. Run only one writer of these paths at a time.

Faults are injected over HTTP while it runs (SIM_API_PORT, see api.py and README.md): the signal of a cell can be
stuck, spiked, drifted or out of range, and the source can drop cells or stall (replay interruption).

Env defaults: SIM_HZ, SIM_PERIOD_S, SIM_MIN_C, SIM_MAX_C, SIM_DURATION_S, SIM_SEED, SIM_API_HOST, SIM_API_PORT
(plus KUKSA_HOST/KUKSA_PORT).
"""
import argparse
import os
import threading
import time
import uuid
from typing import Callable, Dict, Optional

from rom_common import clock, jsonlog, kuksa
from rom_common.contracts import VSS_BATTERY_TEMP, VSS_CELL_TEMPS

from .api import build_api
from .faults import FaultState
from .wave import cell_offsets, cell_temps


class Session:
    """Run context shared between the sample loop and the HTTP thread."""

    def __init__(self, seed: int = 0, run_id: Optional[str] = None):
        self._lock = threading.Lock()
        self.seed = seed
        self.run_id = run_id
        self._restart = False
        self._state: dict = {}

    def restart(self, seed: int, run_id: Optional[str]) -> None:
        """New run: the loop starts the wave over at t=0 with this seed."""
        with self._lock:
            self.seed, self.run_id, self._restart = seed, run_id, True

    def take_restart(self) -> bool:
        with self._lock:
            restart, self._restart = self._restart, False
            return restart

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
        faults: Optional[FaultState] = None, session: Optional[Session] = None) -> int:
    """Send samples at `hz` until duration_s elapses (0 = forever). Returns the tick count.

    sink gets {vss_path: value} for the cells that are reported and for Max; it is not called when nothing is
    reported (everything dropped out, or the source is stalled). Ticks keep their schedule during faults.
    """
    faults = faults if faults is not None else FaultState(monotonic)
    session = session if session is not None else Session()
    log.log("campaign_start", profile="sine", hz=hz, period_s=period_s, min_c=min_c, max_c=max_c,
            duration_s=duration_s, path=VSS_BATTERY_TEMP, cells=list(VSS_CELL_TEMPS), seed=session.seed)
    total = int(duration_s * hz) if duration_s > 0 else None
    offsets = cell_offsets(session.seed, len(VSS_CELL_TEMPS))
    start, i, wave_t = monotonic(), 0, 0.0
    try:
        while total is None or i < total:
            if session.take_restart():
                wave_t, offsets = 0.0, cell_offsets(session.seed, len(VSS_CELL_TEMPS))
            for f in faults.expire():
                log.log("fault_cleared", reason="expired", **f.as_dict())
            stalled = faults.source_stalled()
            reported: Dict[int, float] = {}
            if not stalled:
                cells = dict(enumerate(cell_temps(wave_t, offsets, period_s, min_c, max_c), 1))
                reported = {c: v for c, v in faults.apply(cells).items() if v is not None}
                wave_t += 1 / hz
            hottest = max(reported.values()) if reported else None
            if reported:
                sink({**{VSS_CELL_TEMPS[c - 1]: v for c, v in reported.items()}, VSS_BATTERY_TEMP: hottest})
            session.publish(source_time_s=round(wave_t, 3), stalled=stalled, cells=reported, max_c=hottest,
                            faults=[f.as_dict() for f in faults.active()])
            log.log("sample", seq=i, temp_c=hottest, cells=reported, stalled=stalled, sent_ts_ms=clock.now_ms())
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
    p.add_argument("--api-host", default=os.environ.get("SIM_API_HOST", "127.0.0.1"))
    p.add_argument("--api-port", type=int, default=int(_env("SIM_API_PORT", 8080)), help="0 = no HTTP API")
    a = p.parse_args(argv)
    if a.hz <= 0 or a.period <= 0 or a.min_c >= a.max_c:
        p.error("need hz > 0, period > 0 and min < max")

    log = jsonlog.get_logger("simulator", run_id=uuid.uuid4().hex[:8])
    session, faults = Session(a.seed, log.run_id), FaultState()
    api = None
    if a.api_port > 0:
        try:
            api = build_api(session, faults, log, a.api_host, a.api_port).start()
            log.log("api_started", host=a.api_host, port=api.port)
        except OSError as e:  # e.g. port taken: the simulator is still useful without fault injection
            log.log("api_unavailable", host=a.api_host, port=a.api_port, error=str(e))
    client = kuksa.open_client()
    try:
        run(lambda values: kuksa.set_values(client, values), log, a.hz, a.period, a.min_c, a.max_c, a.duration,
            faults=faults, session=session)
    finally:
        client.disconnect()
        if api is not None:
            api.close()


if __name__ == "__main__":
    main()
