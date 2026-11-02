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
import sys

# Match this branch's src layout without requiring an installed package.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# SP2 is a required v1 handoff dependency. ProjectedScorer must fail when the
# real engine is unavailable; these integration tests must never silently skip.

from sp3.plan_checker import check_plan
from sp3.planner import build_plan
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "synthetic_scoring_data.json").read_text(encoding="utf-8"))
RULES = json.loads((REPO / FIXTURE["ruleset_source"]).read_text(encoding="utf-8"))
EXPECTED = FIXTURE["expected"]


def scoring_data(**fact_overrides):
    data = deepcopy(FIXTURE["scoring_data"])
    data["ruleset"] = deepcopy(RULES)
    data["baselines"][0]["facts"].update(fact_overrides)
    return data


def planner_input():
    planner = deepcopy(FIXTURE["planner"])
    activities = {a["activity_id"]: a for a in FIXTURE["scoring_data"]["activities"]}
    candidates = [
        {"activity": deepcopy(activities[entry["activity_id"]]), "score_binding_ref": entry["score_binding_ref"], "feasibility": entry["feasibility"]}
        for entry in planner.pop("candidates")
    ]
    return {"contract_version": "sp3-planner/0.1", "request_id": "synthetic-integration", **planner, "candidates": candidates}


def score_request(selected):
    data = planner_input()
    return {key: data[key] for key in ("contract_version", "request_id", "context", "baseline")} | {"selected_activity_ids": sorted(selected)}


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
    assert {e["activity_id"]: e["code"] for e in output["excluded_candidates"]} == EXPECTED["excluded"]
    assert output["score_summary"] == EXPECTED["score_summary"]
    assert output["search"] == EXPECTED["search"]
    assert output["proof"] == EXPECTED["proof"]
    assert [w["code"] for w in output["warnings"]] == EXPECTED["warning_codes"]
    assert scorer.engine_calls == EXPECTED["engine_calls"]
    assert (output["mode"], output["official_award_verified"]) == ("DEMO_ONLY", False)
    assert check_plan(data, output, ScorerAdapter(scorer).score_plan, input_snapshot=snapshot) == []


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
