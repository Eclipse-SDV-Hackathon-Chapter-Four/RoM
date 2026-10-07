# Made with Claude (Claude Code, Anthropic)
import copy

import pytest

from fault_injector import campaign
from fault_injector.campaign import CampaignError

BASE = {
    "run_id": "r1", "seed": 3, "hazard": "H", "safety_goal": "SG", "expected_state": "CRITICAL", "max_detect_ms": 5000,
    "faults": [{"at_s": 10, "duration_s": 20, "target": "simulator", "type": "drift", "cell": 1,
                "params": {"rate_c_per_s": 1}}],
}


def with_(**changes):
    data = copy.deepcopy(BASE)
    data.update(changes)
    return data


def test_parse_valid_campaign_and_default_duration():
    c = campaign.parse(BASE)
    assert (c.run_id, c.seed, c.expected_state, c.max_detect_ms) == ("r1", 3, "CRITICAL", 5000)
    assert c.duration_s == 40.0   # last fault ends at 30 s + 10 s settle
    f = c.faults[0]
    assert (f.at_s, f.target, f.type, f.cells, f.duration_s) == (10.0, "simulator", "drift", [1], 20.0)
    assert f.request() == {"type": "drift", "params": {"rate_c_per_s": 1}, "cells": [1]}


def test_cell_cells_and_all_cells_forms():
    f = lambda **kw: campaign.parse(with_(faults=[{"at_s": 0, "target": "simulator", "type": "dropout", **kw}])).faults[0]
    assert f(cell=2).cells == [2] and f(cells=[3, 1, 3]).cells == [1, 3] and f().cells == []
    assert "cells" not in f().request()


def test_fault_without_duration_lasts_until_the_end_and_settle_is_configurable():
    c = campaign.parse(with_(settle_s=3, faults=[{"at_s": 5, "target": "simulator", "type": "stuck"}]))
    assert c.faults[0].duration_s is None and c.duration_s == 8.0


def test_explicit_duration_and_baseline():
    c = campaign.parse(with_(duration_s=100, baseline={"min_c": 25, "max_c": 32}))
    assert c.duration_s == 100.0 and c.baseline == {"min_c": 25.0, "max_c": 32.0}


def test_targets():
    c = campaign.parse(with_(faults=BASE["faults"] + [{"at_s": 1, "target": "publisher", "type": "drop"}]))
    assert c.targets() == {"simulator", "publisher"}


@pytest.mark.parametrize("change, message", [
    ({"run_id": ""}, "run_id"), ({"hazard": None}, "hazard"), ({"safety_goal": 3}, "safety_goal"),
    ({"expected_state": "BROKEN"}, "expected_state"), ({"seed": "x"}, "seed"), ({"seed": True}, "seed"),
    ({"max_detect_ms": 0}, "max_detect_ms"), ({"max_detect_ms": None}, "max_detect_ms"),
    ({"faults": []}, "faults"), ({"faults": "x"}, "faults"), ({"colour": "red"}, "unknown keys"),
    ({"duration_s": 20}, "ends before the last fault"), ({"duration_s": 0}, "duration_s"),
    ({"baseline": {"min_c": 40, "max_c": 30}}, "baseline"), ({"baseline": {"min_c": 40}}, "baseline"),
    ({"baseline": {"speed": 1}}, "baseline"),
])
def test_invalid_campaigns(change, message):
    with pytest.raises(CampaignError, match=message):
        campaign.parse(with_(**change))


@pytest.mark.parametrize("fault, message", [
    ({"at_s": 0, "target": "kuksa", "type": "stuck"}, "target"),
    ({"at_s": 0, "target": "simulator", "type": "drop"}, "type"),
    ({"at_s": 0, "target": "publisher", "type": "stuck"}, "type"),
    ({"at_s": -1, "target": "simulator", "type": "stuck"}, "at_s"),
    ({"target": "simulator", "type": "stuck"}, "at_s"),
    ({"at_s": 0, "target": "simulator", "type": "stuck", "duration_s": 0}, "duration_s"),
    ({"at_s": 0, "target": "simulator", "type": "stuck", "cell": 5}, "cell"),
    ({"at_s": 0, "target": "simulator", "type": "stuck", "cell": 1, "cells": [2]}, "not both"),
    ({"at_s": 0, "target": "publisher", "type": "drop", "cell": 1}, "no cell"),
    ({"at_s": 0, "target": "simulator", "type": "stuck", "params": [1]}, "params"),
    ({"at_s": 0, "target": "simulator", "type": "stuck", "speed": 1}, "unknown keys"),
    ({"at_s": 0, "target": "simulator", "type": "heartbeat_loss", "cell": 1}, "whole source"),
    ({"at_s": 0, "target": "simulator", "type": "databroker_down"}, "type"),
    ({"at_s": 0, "target": "publisher", "type": "heartbeat_loss"}, "type"),
    ("stuck", "mapping"),
])
def test_invalid_faults(fault, message):
    with pytest.raises(CampaignError, match=message):
        campaign.parse(with_(faults=[fault]))


def test_fault_after_the_campaign_ends_is_rejected():
    with pytest.raises(CampaignError, match="starts after"):
        campaign.parse(with_(duration_s=5, faults=[{"at_s": 5, "target": "simulator", "type": "stuck"}]))


def test_not_a_mapping():
    with pytest.raises(CampaignError, match="mapping"):
        campaign.parse(["x"])


def test_every_bundled_campaign_is_valid_and_run_ids_are_unique():
    names = campaign.bundled_names()
    assert len(names) >= 6
    loaded = [campaign.load(n) for n in names]
    assert len({c.run_id for c in loaded}) == len(loaded)
    assert any("publisher" in c.targets() for c in loaded) and any(len(c.faults) > 1 for c in loaded)
    # every campaign names the DTCs the evidence must show, except a negative one (no fault, stays MONITORING)
    assert all(c.expected_faults or c.expected_state == "MONITORING" for c in loaded)
    assert any(not c.expected_faults for c in loaded)


def test_expected_faults_are_optional_deduplicated_and_checked_against_the_catalog():
    assert campaign.parse(BASE).expected_faults == []
    codes = ["battery_guardian.cell1.signal_stuck", "battery_guardian.signal_stale", "battery_guardian.signal_stale"]
    assert campaign.parse(with_(expected_faults=codes)).expected_faults == codes[:2]
    for bad in (["battery_guardian.cell5.signal_stuck"], "battery_guardian.signal_stale", [3]):
        with pytest.raises(CampaignError, match="expected_faults"):
            campaign.parse(with_(expected_faults=bad))



def test_tolerated_faults_are_optional_and_checked_against_the_catalog():
    assert campaign.parse(BASE).tolerated_faults == []
    assert campaign.parse(with_(tolerated_faults=["battery_guardian.link_integrity"])).tolerated_faults == [
        "battery_guardian.link_integrity"]
    with pytest.raises(CampaignError, match="tolerated_faults"):
        campaign.parse(with_(tolerated_faults=["battery_guardian.nope"]))


def test_load_by_name_path_and_errors(tmp_path):
    assert campaign.load("thermal_runaway.yaml").run_id == campaign.load("thermal_runaway").run_id
    p = tmp_path / "mine.yaml"
    p.write_text("run_id: x\n")
    with pytest.raises(CampaignError, match="mine.yaml"):
        campaign.load(str(p))
    p.write_text("run_id: [unclosed\n")
    with pytest.raises(CampaignError, match="invalid YAML"):
        campaign.load(str(p))
    with pytest.raises(CampaignError, match="no campaign file"):
        campaign.load("does_not_exist")


def test_heartbeat_and_databroker_faults_are_valid_and_pass_their_params_on():
    c = campaign.parse(with_(faults=[
        {"at_s": 1, "duration_s": 5, "target": "simulator", "type": "heartbeat_loss", "params": {"component": "chip"}},
        {"at_s": 1, "duration_s": 5, "target": "publisher", "type": "databroker_down"},
        {"at_s": 2, "duration_s": 5, "target": "publisher", "type": "drop", "params": {"topic": "heartbeat"}}]))
    assert c.faults[0].request() == {"type": "heartbeat_loss", "params": {"component": "chip"}}
    assert c.faults[1].request() == {"type": "databroker_down", "params": {}}
    assert c.faults[2].request()["params"] == {"topic": "heartbeat"}


def test_heartbeat_codes_are_valid_expected_faults():
    c = campaign.parse(with_(expected_faults=["battery_guardian.chip_silent", "battery_guardian.uprotocol_lost"]))
    assert c.expected_faults == ["battery_guardian.chip_silent", "battery_guardian.uprotocol_lost"]


def test_dfm_target_and_expected_verdict():
    c = campaign.load("opensovd_partial_visibility")
    assert c.expected_verdict == "FAIL" and "dfm" in c.targets()
    assert campaign.load("thermal_runaway").expected_verdict == "PASS"
    with pytest.raises(campaign.CampaignError):
        campaign.parse(with_(expected_verdict="MAYBE"))
