"""Integration: REAL sp2.drl_engine + REAL data/drl_rules.json on SYNTHETIC data.

The student, activities and bindings are synthetic (fixture label
SYNTHETIC-DEMO); the expected numbers were derived by hand from the rule text,
not from engine output. Passing proves engine/scorer/adapter/planner wiring,
not real-student integration.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sys

# Match this branch's src layout without requiring an installed package.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# SP2 is a required handoff dependency. ProjectedScorer must fail when the
# real engine is unavailable; these integration tests must never silently skip.

from sp3.plan_checker import check_plan
from sp3.planner import build_plan
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "synthetic_scoring_data.json").read_text(encoding="utf-8"))
RULES = json.loads((REPO / FIXTURE["ruleset_source"]).read_text(encoding="utf-8"))
EXPECTED = FIXTURE["expected"]
FLEXIBLE = FIXTURE["flexible_attribution"]


def scoring_data(**fact_overrides):
    data = deepcopy(FIXTURE["scoring_data"])
    data["ruleset"] = deepcopy(RULES)
    data["baselines"][0]["facts"].update(fact_overrides)
    return data


def candidates(entries):
    """Section 6.5 candidates: the trusted activity record plus the fixture's feasibility fields."""
    activities = {a["activity_id"]: a for a in FIXTURE["scoring_data"]["activities"]}
    return [
        {"activity": deepcopy(activities[entry["activity_id"]]), **{k: deepcopy(v) for k, v in entry.items() if k != "activity_id"}}
        for entry in entries
    ]


def planner_input():
    planner = deepcopy(FIXTURE["planner"])
    entries = planner.pop("candidates")
    return {"contract_version": "sp3-planner/0.2", "request_id": "synthetic-integration", **planner, "candidates": candidates(entries)}


def flexible_planner_input():
    data = planner_input()
    data.update(
        request_id="synthetic-integration-flexible",
        candidates=candidates(FLEXIBLE["candidates"]),
        **{key: deepcopy(FLEXIBLE[key]) for key in ("conflict_pairs", "available_intervals", "goals", "previous_plan")},
    )
    return data


def score_request(selected, order=None):
    data = planner_input()
    request = {key: data[key] for key in ("contract_version", "request_id", "context", "baseline")}
    return request | {"selected_activity_ids": sorted(selected), "attribution_order": list(sorted(selected) if order is None else order)}


def test_fixture_is_labelled_synthetic():
    assert FIXTURE["label"] == FIXTURE["scoring_data"]["label"] == "SYNTHETIC-DEMO"
    assert FIXTURE["planner"]["context"]["term_id"] == "SYNTHETIC-DEMO"


def test_integration_real_engine_synthetic_data_end_to_end_plan():
    data = planner_input()
    snapshot = deepcopy(data)
    scorer = ProjectedScorer(InMemoryScoringData(scoring_data()))
    output = build_plan(data, ScorerAdapter(scorer).score_plan)

    assert output["status"] == EXPECTED["status"], output["errors"]
    assert output["feasibility_conclusion"] == EXPECTED["feasibility_conclusion"]
    assert [
        {
            "activity_id": entry["activity_id"],
            "category_id": entry["reasons"][0]["category_id"],
            "projected_added": entry["reasons"][0]["projected_added"],
            "preference_matches": sum(r["code"] == "PREFERENCE_MATCH" for r in entry["reasons"]),
        }
        for entry in output["selected_activities"]
    ] == EXPECTED["selected"]
    assert [entry["change"] for entry in output["selected_activities"]] == EXPECTED["changes"]
    schedules = {c["activity"]["activity_id"]: c["schedule"] for c in data["candidates"]}
    assert all(entry["scheduled_blocks"] == schedules[entry["activity_id"]]["fixed_blocks"] for entry in output["selected_activities"])
    assert {e["activity_id"]: e["code"] for e in output["excluded_candidates"]} == EXPECTED["excluded"]
    assert output["score_summary"] == EXPECTED["score_summary"]
    assert output["search"] == EXPECTED["search"]
    assert output["proof"] == EXPECTED["proof"]
    assert [w["code"] for w in output["warnings"]] == EXPECTED["warning_codes"]
    assert output["dropped_activities"] == EXPECTED["dropped_activities"]
    assert output["score_comparison"] == EXPECTED["score_comparison"]
    assert re.fullmatch(r"sp3plan-[0-9a-f]{16}", output["plan_version"])
    assert scorer.engine_calls == EXPECTED["engine_calls"]
    assert (output["mode"], output["official_award_verified"]) == ("DEMO_ONLY", False)
    assert check_plan(data, output, ScorerAdapter(scorer).score_plan, input_snapshot=snapshot) == []


def test_integration_real_engine_attribution_follows_the_schedule_not_the_window_opening():
    data = flexible_planner_input()
    snapshot = deepcopy(data)
    expected = FLEXIBLE["expected"]
    scorer = ProjectedScorer(InMemoryScoringData(scoring_data()))
    output = build_plan(data, ScorerAdapter(scorer).score_plan)

    assert output["status"] == expected["status"], output["errors"]
    assert [
        {
            "activity_id": entry["activity_id"],
            "change": entry["change"],
            "scheduled_blocks": entry["scheduled_blocks"],
            "projected_added": entry["reasons"][0]["projected_added"],
        }
        for entry in output["selected_activities"]
    ] == expected["selected"]
    assert output["score_summary"]["projected_by_category"] == expected["projected_by_category"]
    assert output["score_summary"]["projected_total"] == expected["projected_total"]
    assert output["search"] == expected["search"]
    assert output["score_comparison"] == expected["score_comparison"]
    assert scorer.engine_calls == expected["engine_calls"]
    assert check_plan(data, output, ScorerAdapter(scorer).score_plan, input_snapshot=snapshot) == []


def test_integration_real_engine_two_orders_same_totals_different_attribution():
    selected = ["FLEX-SEM", "SEM-1", "SEM-3"]
    adapter = ScorerAdapter(ProjectedScorer(InMemoryScoringData(scoring_data())))
    expected = FLEXIBLE["expected"]
    responses = {
        name: adapter.score_plan(score_request(selected, list(order)))
        for name, order in (
            ("window_opening_order_contributions", expected["window_opening_order_contributions"]),
            ("scheduled_order_contributions", expected["scheduled_order_contributions"]),
        )
    }
    for name, response in responses.items():
        assert response["evaluation_status"] == "OK", response["errors"]
        assert [c["activity_id"] for c in response["result"]["contributions"]] == list(expected[name])
        assert {c["activity_id"]: c["projected_added"] for c in response["result"]["contributions"]} == expected[name]
    first, second = (response["result"] for response in responses.values())
    for key in ("category_after", "category_gain", "total_after", "total_gain"):
        assert first[key] == second[key]
    assert first["category_after"]["C1"] == 30 and first["total_after"] == 70


def test_integration_real_engine_synthetic_data_category_cap_in_whole_set():
    case = EXPECTED["capped_three_seminars"]
    response = ScorerAdapter(ProjectedScorer(InMemoryScoringData(scoring_data()))).score_plan(score_request(case["selected_activity_ids"]))
    assert response["evaluation_status"] == "OK", response["errors"]
    assert response["result"]["category_after"]["C1"] == case["C1_after"]
    assert {c["activity_id"]: c["projected_added"] for c in response["result"]["contributions"]} == case["contributions"]
    assert all(c["rule_id"] == "R19" for c in response["result"]["contributions"])


def test_integration_real_engine_synthetic_data_empty_set_matches_baseline():
    response = ScorerAdapter(ProjectedScorer(InMemoryScoringData(scoring_data()))).score_plan(score_request([]))
    assert response["evaluation_status"] == "OK", response["errors"]
    assert response["result"]["category_after"] == FIXTURE["planner"]["baseline"]["category_scores"]
    assert response["result"]["total_after"] == FIXTURE["planner"]["baseline"]["total_score"]


def test_integration_real_engine_unverified_rule_binding_needs_review():
    data = scoring_data()
    data["bindings"][0].update(rule_id="R23", field="institutional_social_survey_participation", operation="SET", value=True)
    response = ScorerAdapter(ProjectedScorer(InMemoryScoringData(data))).score_plan(score_request(["SEM-1"]))
    assert response["evaluation_status"] == "NEEDS_REVIEW"
    assert [(e["code"], e["activity_id"]) for e in response["errors"]] == [("UNVERIFIED_RULE", "SEM-1")]


def test_integration_real_engine_skipped_rule_in_baseline_needs_review():
    # R23 is needs_review in the real ruleset; the engine skips it and flags review.
    data = scoring_data(institutional_social_survey_participation=True)
    response = ScorerAdapter(ProjectedScorer(InMemoryScoringData(data))).score_plan(score_request(["SEM-1"]))
    assert response["evaluation_status"] == "NEEDS_REVIEW"
    assert response["errors"][0]["code"] == "SP2_RULE_SKIPPED"
    assert "R23" in response["errors"][0]["message"]


def test_integration_real_engine_confirmed_score_field_reveals_total_semantics_difference():
    # The engine adds current_confirmed_score to its total; the contract does not.
    data = scoring_data(current_confirmed_score=10)
    response = ScorerAdapter(ProjectedScorer(InMemoryScoringData(data))).score_plan(score_request([]))
    assert response["evaluation_status"] == "ERROR"
    assert response["errors"][0]["code"] == "TOTAL_SEMANTICS_MISMATCH"


def test_integration_real_engine_planner_failure_on_missing_baseline_facts():
    data = scoring_data()
    data["baselines"] = []
    output = build_plan(planner_input(), ScorerAdapter(ProjectedScorer(InMemoryScoringData(data))).score_plan)
    assert output["status"] == "NEEDS_DATA"
    assert output["score_summary"] is None
    assert [e["code"] for e in output["errors"]] == ["MISSING_BASELINE_FACTS"]
    assert output["search"]["evaluated_subsets"] == 1
