# Made with Claude (Claude Code, Anthropic)
"""RoM Fault Campaign Runner: injects the faults of a YAML campaign into the running stack.

    rom-fault-injector list                          bundled campaigns
    rom-fault-injector run thermal_runaway           bundled name, or a path to your own YAML
    rom-fault-injector run my.yaml --dry-run         validate and print the timeline, inject nothing

Signal and source faults go to the simulator API (SIMULATOR_URL, default http://127.0.0.1:8080), transport faults
to the vss-uprotocol-client API (PUBLISHER_URL, needs FAULT_API_PORT there). Exit code 0 = completed.
"""
import argparse
import os
import sys
from typing import Optional

from rom_common import jsonlog

from . import campaign
from .runner import Runner, RunnerError, timeline

DEFAULT_SIMULATOR_URL = "http://127.0.0.1:8080"


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="rom-fault-injector", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="bundled campaigns")
    r = sub.add_parser("run", help="run a campaign")
    r.add_argument("campaign", help="bundled campaign name or path to a YAML file")
    r.add_argument("--simulator-url", default=os.environ.get("SIMULATOR_URL", DEFAULT_SIMULATOR_URL))
    r.add_argument("--publisher-url", default=os.environ.get("PUBLISHER_URL"))
    r.add_argument("--dry-run", action="store_true", help="validate and print the timeline, inject nothing")
    a = p.parse_args(argv)

    if a.command == "list":
        print("\n".join(campaign.bundled_names()))
        return 0

    log = jsonlog.get_logger("fault-injector")
    try:
        c = campaign.load(a.campaign)
    except campaign.CampaignError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    urls = {"simulator": a.simulator_url.rstrip("/")}
    if a.publisher_url:
        urls["publisher"] = a.publisher_url.rstrip("/")
    runner = Runner(c, urls, log)
    try:
        runner.check_urls()
    except RunnerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.dry_run:
        log.run_id = c.run_id
        log.log("campaign_plan", hazard=c.hazard, safety_goal=c.safety_goal, expected_state=c.expected_state,
                max_detect_ms=c.max_detect_ms, seed=c.seed, duration_s=c.duration_s)
        for at_s, _, action, step in timeline(c):
            log.log("plan_step", at_s=at_s, action=action, target=step.target, type=step.type, cells=step.cells,
                    params=step.params)
        return 0
    return 0 if runner.run() == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
