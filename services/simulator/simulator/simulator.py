# Made with Claude (Claude Code, Anthropic)
"""Streams a sine-wave battery temperature (default 30-69 °C) into the KUKSA databroker.

    rom-simulator --hz 2 --period 120 --duration 0     # 0 = run until Ctrl+C

Writes Vehicle.Powertrain.TractionBattery.Temperature.Max. Run only one writer of this path at a time.
Env defaults: SIM_HZ, SIM_PERIOD_S, SIM_MIN_C, SIM_MAX_C, SIM_DURATION_S (plus KUKSA_HOST/KUKSA_PORT).
"""
import argparse
import os
import time
import uuid
from typing import Callable, Optional

from rom_common import clock, jsonlog, kuksa
from rom_common.contracts import VSS_BATTERY_TEMP

from .wave import sine_temp


def run(sink: Callable[[float], None], log, hz: float = 2.0, period_s: float = 120.0,
        min_c: float = 30.0, max_c: float = 69.0, duration_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic) -> int:
    """Send samples at `hz` until duration_s elapses (0 = forever). Returns the sample count."""
    log.log("campaign_start", profile="sine", hz=hz, period_s=period_s, min_c=min_c, max_c=max_c,
            duration_s=duration_s, path=VSS_BATTERY_TEMP)
    total = int(duration_s * hz) if duration_s > 0 else None
    start, i = monotonic(), 0
    try:
        while total is None or i < total:
            temp = sine_temp(i / hz, period_s, min_c, max_c)
            sink(temp)
            log.log("sample", seq=i, temp_c=temp, sent_ts_ms=clock.now_ms())
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
    a = p.parse_args(argv)
    if a.hz <= 0 or a.period <= 0 or a.min_c >= a.max_c:
        p.error("need hz > 0, period > 0 and min < max")

    log = jsonlog.get_logger("simulator", run_id=uuid.uuid4().hex[:8])
    client = kuksa.open_client()
    try:
        run(lambda t: kuksa.set_temp(client, t), log, a.hz, a.period, a.min_c, a.max_c, a.duration)
    finally:
        client.close()


if __name__ == "__main__":
    main()
