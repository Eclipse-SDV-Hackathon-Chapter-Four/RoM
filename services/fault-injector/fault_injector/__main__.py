# Made with Claude (Claude Code, Anthropic)
"""RoM Fault Campaign Runner — placeholder, not implemented yet (see README.md#roadmap).

TODO:
- read campaigns from YAML (seed, run_id, hazard, safety_goal, fault, expected_state, max_detect_ms)
- transport faults (delay, duplicate, drop, reorder) and signal faults (stuck, spike, drift,
  out-of-range) as rom_uprotocol.publisher interceptors: interceptor(message, forward) -> UStatus
- source faults (dropout, replay interruption)
- log campaign_start / fault_injected / campaign_end with run_id for the evidence collector
"""
from rom_common import jsonlog


def main():
    # TODO: implement, see the module docstring and fault-injector/README.md
    jsonlog.get_logger("fault-injector").log("not_implemented", roadmap="README.md#roadmap")


if __name__ == "__main__":
    main()
