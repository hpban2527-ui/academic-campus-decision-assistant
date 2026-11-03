"""Planner acceptance cases P1-P9 (contract section 12) with static mock scores.

The fixture's candidates and conflict_pairs are the unchanged section 6.5
output of the feasibility module at the commit in ``derived_from``; expected
projections were derived by hand. NOT real SP2 scoring.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import StaticTableScorer
from sp3.plan_checker import check_plan
from sp3.planner import build_plan

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "v0_2_planner_cases.json").read_text(encoding="utf-8"))
CASES = FIXTURE["cases"]
CANDIDATE_FIELDS = {"activity", "score_binding_ref", "participation", "schedule", "feasibility"}


def expected_based_on(planner_input):
    context, previous = planner_input["context"], planner_input["previous_plan"]
    return {
        "calendar_version": context["calendar_version"],
        "dataset_version": context["dataset_version"],
        "ruleset_version": context["ruleset_version"],
        "baseline_ref": context["baseline_ref"],
        "previous_plan_version": None if previous is None else previous["plan_version"],
    }


def expected_plan_version(based_on, selected):
    payload = {
        "based_on": based_on,
        "selected_activities": sorted(
            ({"activity_id": e["activity_id"], "scheduled_blocks": e["scheduled_blocks"]} for e in selected),
            key=lambda item: item["activity_id"],
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sp3plan-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def test_fixture_lists_p1_to_p9_derived_from_the_feasibility_side():
    assert FIXTURE["contract_version"] == "sp3-planner/0.2"
    assert FIXTURE["label"] == "SYNTHETIC-DEMO"
    assert len(FIXTURE["derived_from"]) == 40 and FIXTURE["derived_from"].startswith("cfa42ba")
    assert [case["id"] for case in CASES] == [f"P{index}" for index in range(1, 10)]
    for case in CASES:
        assert case["module"] == "planner" and case["case"] and case["derivation"]
        for candidate in case["input"]["candidates"]:
            assert set(candidate) == CANDIDATE_FIELDS


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_planner_case(case):
    planner_input = deepcopy(case["input"])
    snapshot = deepcopy(planner_input)
    scorer = StaticTableScorer(case["score_table"])
    output = build_plan(planner_input, scorer)
    expected = case["expected"]

    assert planner_input == snapshot
    assert output["status"] == expected["status"], output["errors"]
    assert output["feasibility_conclusion"] == expected["feasibility_conclusion"]
    assert [
        {
            **{key: entry[key] for key in ("activity_id", "schedule_type", "scheduled_blocks", "registration", "change")},
            "reasons": [{key: reason[key] for key in ("code", "category_id", "projected_added")} for reason in entry["reasons"]],
        }
        for entry in output["selected_activities"]
    ] == expected["selected"]
    assert [{"activity_id": e["activity_id"], "code": e["code"]} for e in output["excluded_candidates"]] == expected["excluded"]
    assert [{"activity_id": e["activity_id"], "code": e["code"]} for e in output["keep_conflicts"]] == expected["keep_conflicts"]
    assert [
        {"activity_id": e["activity_id"], "registered": e["registered"], "code": e["code"]} for e in output["dropped_activities"]
    ] == expected["dropped_activities"]
    assert output["pending_confirmation"] == expected["pending_confirmation"]
    assert output["score_comparison"] == expected["score_comparison"]
    assert output["search"] == expected["search"]
    assert output["proof"] == expected["proof"]
    assert [w["code"] for w in output["warnings"]] == expected["warning_codes"]
    if "score_summary" in expected:
        assert output["score_summary"] == expected["score_summary"]
    else:
        summary = output["score_summary"]
        assert (summary["projected_by_category"], summary["remaining_by_category"]) == (
            expected["projected_by_category"], expected["remaining_by_category"],
        )
    assert output["based_on"] == expected_based_on(planner_input)
    if "plan_version" in expected:
        assert output["plan_version"] == expected["plan_version"]
    else:
        assert output["plan_version"] == expected_plan_version(output["based_on"], expected["selected"])
    assert scorer.calls == [tuple(ids) for ids in expected["scorer_calls"]]
    if "attribution_orders" in expected:
        assert scorer.orders[: len(expected["attribution_orders"])] == [tuple(order) for order in expected["attribution_orders"]]
    assert output["errors"] == []
    assert (output["mode"], output["official_award_verified"]) == ("DEMO_ONLY", False)
    assert check_plan(planner_input, output, StaticTableScorer(case["score_table"]), input_snapshot=snapshot) == []
