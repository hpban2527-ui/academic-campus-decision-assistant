"""Checker tests: hand-corrupted planner outputs must yield specific violations."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import CappedAdditiveScorer, StaticTableScorer, at, make_activity, make_candidate, make_planner_input
from sp3.plan_checker import Violation, check_plan
from sp3.planner import build_plan

EXAMPLES = {
    example["name"]: example
    for example in json.loads((Path(__file__).resolve().parent / "fixtures" / "contract_examples.json").read_text(encoding="utf-8"))["examples"]
}


def example_case(name):
    example = EXAMPLES[name]
    planner_input = deepcopy(example["planner_input"])
    output = build_plan(planner_input, StaticTableScorer(example["score_table"]))
    return planner_input, output, StaticTableScorer(example["score_table"])


def codes(violations):
    return {violation.code for violation in violations}


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_valid_plans_pass_and_rescore_exactly_once(name):
    planner_input, output, scorer = example_case(name)
    assert check_plan(planner_input, output, scorer, input_snapshot=deepcopy(planner_input)) == []
    assert scorer.call_count == 1


def test_conflicting_selection_is_reported():
    planner_input, output, scorer = example_case("example_2_conflict_and_preference")
    output["excluded_candidates"] = []
    output["selected_activities"].insert(0, {
        "activity_id": "A", "title": "Sample activity A",
        "start": "2026-11-02T09:00:00+07:00", "end": "2026-11-02T10:00:00+07:00", "reasons": [],
    })
    assert "SELECTED_CONFLICT" in codes(check_plan(planner_input, output, scorer))


def test_missing_candidate_is_reported():
    planner_input, output, scorer = example_case("example_2_conflict_and_preference")
    output["excluded_candidates"] = []
    violations = check_plan(planner_input, output, scorer)
    assert Violation("CANDIDATE_COVERAGE", "every candidate must appear exactly once.", "A") in violations


def test_duplicate_candidate_is_reported():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["excluded_candidates"].append({"activity_id": "A", "code": "LOWER_PRIORITY", "message": "Duplicate."})
    assert "CANDIDATE_COVERAGE" in codes(check_plan(planner_input, output, scorer))


def test_wrong_score_summary_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    output["score_summary"]["projected_by_category"]["C1"] = 26
    assert codes(check_plan(planner_input, output, scorer)) == {"SCORE_SUMMARY_MISMATCH"}


def test_wrong_remaining_gap_is_reported():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["score_summary"]["remaining_by_category"]["C1"] = 0
    assert "SCORE_SUMMARY_MISMATCH" in codes(check_plan(planner_input, output, scorer))


def test_proven_unreachable_without_complete_search_is_reported():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["search"]["complete"] = False
    output["warnings"].append({"code": "SEARCH_INCOMPLETE", "message": "Stopped early."})
    assert "UNPROVEN_UNREACHABLE" in codes(check_plan(planner_input, output, scorer))


def test_proven_unreachable_without_proof_is_reported():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["proof"] = None
    assert codes(check_plan(planner_input, output, scorer)) == {"UNPROVEN_UNREACHABLE"}


def test_proof_count_must_match_valid_subsets():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["search"]["evaluated_subsets"] = 3
    output["proof"]["evaluated_subsets"] = 3
    assert codes(check_plan(planner_input, output, scorer)) == {"SEARCH_COUNT"}


@pytest.mark.parametrize("field,value", [("mode", "OFFICIAL"), ("official_award_verified", True)])
def test_flipped_demo_flag_is_reported(field, value):
    planner_input, output, scorer = example_case("example_1_target_met")
    output[field] = value
    assert codes(check_plan(planner_input, output, scorer)) == {"DEMO_FLAG"}


def test_wrong_exclusion_code_is_reported():
    planner_input, output, scorer = example_case("example_2_conflict_and_preference")
    output["excluded_candidates"][0]["code"] = "LOWER_PRIORITY"
    violations = check_plan(planner_input, output, scorer)
    assert codes(violations) == {"EXCLUSION_CODE"}
    assert violations[0].activity_id == "A"


def test_limit_exclusion_that_would_not_violate_a_limit_is_reported():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["excluded_candidates"][0]["code"] = "LIMIT"
    assert codes(check_plan(planner_input, output, scorer)) == {"EXCLUSION_CODE"}


def test_fabricated_preference_reason_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    output["selected_activities"][0]["reasons"].append({
        "code": "PREFERENCE_MATCH", "message": "Matches preferred domain academic.", "category_id": None, "projected_added": None,
    })
    assert codes(check_plan(planner_input, output, scorer)) == {"REASON_MISMATCH"}


def test_goal_reason_must_use_actual_contribution():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["selected_activities"][0]["reasons"][0]["projected_added"] = 5
    assert codes(check_plan(planner_input, output, scorer)) == {"REASON_MISMATCH"}


def test_target_met_with_remaining_gap_is_reported():
    planner_input, output, scorer = example_case("example_3_unreachable_target_and_cap")
    output["status"] = "TARGET_MET"
    output["feasibility_conclusion"] = "REACHABLE"
    output["proof"] = None
    assert "STATUS_INCOHERENT" in codes(check_plan(planner_input, output, scorer))


def test_conclusion_must_fit_status():
    planner_input, output, scorer = example_case("example_1_target_met")
    output["feasibility_conclusion"] = "UNDETERMINED"
    assert "STATUS_INCOHERENT" in codes(check_plan(planner_input, output, scorer))


def test_missing_required_warning_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    output["warnings"] = output["warnings"][:1]
    assert codes(check_plan(planner_input, output, scorer)) == {"MISSING_WARNING"}


def test_missing_search_incomplete_warning_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    output["search"].update(complete=False, optimality_proven=False, limit_reason="EVALUATION_LIMIT")
    assert "SEARCH_WARNING" in codes(check_plan(planner_input, output, scorer))


def test_optimality_claim_with_exhausted_budget_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    output["search"].update(complete=False, limit_reason="EVALUATION_LIMIT")
    output["warnings"].append({"code": "SEARCH_INCOMPLETE", "message": "Budget ran out."})
    assert codes(check_plan(planner_input, output, scorer)) == {"SEARCH_OVERCLAIM"}


def test_envelope_mismatch_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    output["context"]["baseline_ref"] = "another-baseline"
    assert codes(check_plan(planner_input, output, scorer)) == {"ENVELOPE_MISMATCH"}


def test_input_mutation_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    snapshot = deepcopy(planner_input)
    planner_input["goals"]["category_targets"]["C1"] = 24
    assert "INPUT_MUTATED" in codes(check_plan(planner_input, output, scorer, input_snapshot=snapshot))


def test_failure_output_with_scores_is_reported():
    planner_input, output, scorer = example_case("example_1_target_met")
    output.update(status="ERROR", feasibility_conclusion="UNDETERMINED", selected_activities=[], excluded_candidates=[],
                  errors=[{"code": "SP2_FAILURE", "message": "Scorer failed.", "activity_id": None}])
    output["search"].update(complete=False, optimality_proven=False, limit_reason="SP2_FAILURE")
    assert codes(check_plan(planner_input, output, scorer)) == {"FAILURE_SHAPE"}


def test_selected_limit_violation_and_order_are_reported():
    candidates = [make_candidate(make_activity("A", at(3, 9), at(3, 10))), make_candidate(make_activity("B", at(2, 9), at(2, 10)))]
    planner_input = make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30})
    scorer = CappedAdditiveScorer({"A": ("C1", 5, at(3, 9)), "B": ("C1", 5, at(2, 9))})
    output = build_plan(planner_input, scorer)
    assert check_plan(planner_input, output, scorer) == []
    output["selected_activities"].reverse()
    planner_input["limits"]["max_activities"] = 1
    found = codes(check_plan(planner_input, output, scorer))
    assert {"LIMIT_VIOLATED", "SELECTED_ORDER"} <= found


def test_malformed_output_is_reported_not_raised():
    planner_input, output, scorer = example_case("example_1_target_met")
    assert codes(check_plan(planner_input, {"status": "TARGET_MET"}, scorer)) == {"OUTPUT_SHAPE"}
    output["search"] = None
    assert "OUTPUT_MALFORMED" in codes(check_plan(planner_input, output, scorer))
