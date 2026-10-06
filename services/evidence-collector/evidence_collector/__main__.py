# Made with Claude (Claude Code, Anthropic)
"""RoM Evidence Collector — placeholder, not implemented yet (see ROADMAP.md).

TODO:
- collect per run_id: campaign (hazard, safety goal, injected fault), guardian detection and
  mitigation events, DFM records as exposed by OpenSOVD
- verdict per run: PASS / FAIL / INCONCLUSIVE with detection latency and mitigation timing
- report over all campaigns (failed scenarios included)
"""
from rom_common import jsonlog


def main():
    # TODO: implement, see the module docstring and evidence-collector/README.md
    jsonlog.get_logger("evidence-collector").log("not_implemented", roadmap="ROADMAP.md")


if __name__ == "__main__":
    main()
