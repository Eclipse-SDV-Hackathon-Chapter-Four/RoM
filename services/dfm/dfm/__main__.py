# Made with Claude (Claude Code, Anthropic)
"""RoM Diagnostic Fault Manager (DFM) — placeholder, not implemented yet (see README.md#roadmap).

TODO:
- receive fault events from the guardian (over uProtocol) and turn them into fault records
  (code, status active/passive, first/last seen, run_id, context)
- store records and expose them to OpenSOVD
- diagnostic faults for campaigns: delayed DFM write, partial visibility
"""
from rom_common import jsonlog


def main():
    # TODO: implement, see the module docstring and dfm/README.md
    jsonlog.get_logger("dfm").log("not_implemented", roadmap="README.md#roadmap")


if __name__ == "__main__":
    main()
