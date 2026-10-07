# Made with Claude (Claude Code, Anthropic)
"""The DFM catalog and the codes the guardian raises must be the same list, or the DFM drops reports."""
import json
from pathlib import Path

from rom_common import contracts

CATALOG = Path(__file__).parent.parent / "catalog" / "battery_guardian.json"


def test_catalog_matches_the_guardian_fault_codes():
    catalog = json.loads(CATALOG.read_text())
    assert catalog["id"] == contracts.DFM_ENTITY
    ids = [f["id"]["Text"] for f in catalog["faults"]]
    assert sorted(ids) == sorted(contracts.FAULT_CODES) and len(ids) == len(set(ids))


def test_catalog_entries_use_fault_lib_values():
    for fault in json.loads(CATALOG.read_text())["faults"]:
        assert fault["severity"] in ("Warn", "Error", "Fatal")
        assert fault["category"] in ("Hardware", "Communication")
        assert len(fault["id"]["Text"]) <= 64 and len(fault["name"]) <= 64   # fault-lib ShortString
