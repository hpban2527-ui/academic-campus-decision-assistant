"""Checker tests: hand-corrupted planner outputs must yield specific violations."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import (
    CappedAdditiveScorer,
    StaticTableScorer,
    at,
    flexible_schedule,
    keep,
    make_activity,
    make_candidate,
    make_planner_input,
    make_previous_plan,
)
from sp3.plan_checker import Violation, check_plan
from sp3.planner import build_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLES = {
    example["name"]: example
    for example in json.loads((FIXTURES / "contract_examples.json").read_text(encoding="utf-8"))["examples"]
}
CASES = {case["id"]: case for case in json.loads((FIXTURES / "v0_2_planner_cases.json").read_text(encoding="utf-8"))["cases"]}


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
        "activity_id": "A", "title": "Sample activity A", "schedule_type": "FIXED",
        "scheduled_blocks": [{"start": "2026-11-02T09:00:00+07:00", "end": "2026-11-02T10:00:00+07:00"}],
        "registration": "NOT_REGISTERED", "change": "ADDED", "reasons": [],
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
    scorer = CappedAdditiveScorer({"A": ("C1", 5), "B": ("C1", 5)})
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


# v0.2: scheduling, replan and keep requests ------------------------------------------------

def planner_case(case_id):
    case = CASES[case_id]
    planner_input = deepcopy(case["input"])
    output = build_plan(planner_input, StaticTableScorer(case["score_table"]))
    return planner_input, output, StaticTableScorer(case["score_table"])


def entry(output, field, activity_id):
    return next(item for item in output[field] if item["activity_id"] == activity_id)


@pytest.mark.parametrize("case_id", list(CASES))
def test_planner_cases_pass_with_one_rescore_and_one_comparison(case_id):
    planner_input, output, scorer = planner_case(case_id)
    assert check_plan(planner_input, output, scorer, input_snapshot=deepcopy(planner_input)) == []
    rescored = 0 if output["status"] == "KEEP_CONFLICT" else 1 + (planner_input["previous_plan"] is not None)
    assert scorer.call_count == rescored


@pytest.mark.parametrize("case_id,activity_id,code", [
    ("P1", "B", "LOWER_PRIORITY"),  # a proven NO_TIME hidden behind a weaker code
    ("P5", "B", "NO_TIME"),  # NO_TIME without proof: {A, B, X} is schedulable
    ("P8", "R", "NO_TIME"),
])
def test_no_time_must_match_the_brute_force(case_id, activity_id, code):
    planner_input, output, scorer = planner_case(case_id)
    entry(output, "excluded_candidates", activity_id)["code"] = code
    found = codes(check_plan(planner_input, output, scorer))
    assert "EXCLUSION_CODE" in found


def test_overlapping_selected_blocks_are_reported():
    planner_input, output, scorer = planner_case("P2")
    # 10:30-11:30 is a valid sitting for X on its own, but it overlaps F (10:00-11:00).
    entry(output, "selected_activities", "X")["scheduled_blocks"] = [{"start": "2026-11-02T10:30:00+07:00", "end": "2026-11-02T11:30:00+07:00"}]
    assert codes(check_plan(planner_input, output, scorer)) == {"SELECTED_OVERLAP", "PLAN_VERSION"}


@pytest.mark.parametrize("block", [
    {"start": "2026-11-02T11:00:00+07:00", "end": "2026-11-02T11:30:00+07:00"},  # wrong duration
    {"start": "2026-11-02T09:00:00+07:00", "end": "2026-11-02T10:00:00+07:00"},  # before the window opens at 09:30
    {"start": "2026-11-02T12:00:00+07:00", "end": "2026-11-02T13:00:00+07:00"},  # outside window and availability
])
def test_invalid_flexible_block_is_reported(block):
    planner_input, output, scorer = planner_case("P2")
    entry(output, "selected_activities", "X")["scheduled_blocks"] = [block]
    assert "SELECTED_BLOCKS" in codes(check_plan(planner_input, output, scorer))


def test_fixed_blocks_must_be_copied_exactly():
    planner_input, output, scorer = planner_case("P2")
    # Same instant, different text: fixed sessions are copied exactly as received.
    entry(output, "selected_activities", "F")["scheduled_blocks"][0]["start"] = "2026-11-02T03:00:00Z"
    assert "SELECTED_BLOCKS" in codes(check_plan(planner_input, output, scorer))


def test_wrong_change_label_is_reported():
    planner_input, output, scorer = planner_case("P6")
    entry(output, "selected_activities", "X")["change"] = "KEPT"
    assert codes(check_plan(planner_input, output, scorer)) == {"CHANGE_LABEL"}


def test_kept_activity_must_keep_its_block():
    candidates = [make_candidate(make_activity("K", at(2, 8), at(2, 12)), schedule=flexible_schedule(at(2, 8), at(2, 12), 60))]
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 25},
        previous_plan=make_previous_plan({"K": [(at(2, 10), at(2, 11))]}), keep_requests=keep("K"),
    )
    scorer = CappedAdditiveScorer({"K": ("C1", 5)})
    output = build_plan(planner_input, scorer)
    assert check_plan(planner_input, output, scorer) == []
    output["selected_activities"][0]["scheduled_blocks"] = [{"start": at(2, 8), "end": at(2, 9)}]
    output["selected_activities"][0]["change"] = "MOVED"
    assert "KEEP_NOT_HONORED" in codes(check_plan(planner_input, output, scorer))


def test_dropped_activities_must_match_the_previous_plan():
    planner_input, output, scorer = planner_case("P8")
    output["dropped_activities"][0]["registered"] = False
    found = codes(check_plan(planner_input, output, scorer))
    assert {"DROPPED_MISMATCH", "DROPS_REGISTERED_WARNING"} <= found
    planner_input, output, scorer = planner_case("P8")
    output["dropped_activities"] = []
    assert "DROPPED_MISMATCH" in codes(check_plan(planner_input, output, scorer))


def test_pending_confirmation_must_list_completed_uncounted_activities():
    planner_input, output, scorer = planner_case("P7")
    output["pending_confirmation"] = []
    assert codes(check_plan(planner_input, output, scorer)) == {"PENDING_CONFIRMATION"}


@pytest.mark.parametrize("case_id,corrupt", [
    ("P8", lambda c: c.update(previous_projected_total=25)),
    ("P8", lambda c: c.update(previous_activity_ids=[])),
    ("P8", lambda c: c.update(new_projected_total=22)),
    ("P8", lambda c: c.update(basis="PREVIOUS_PLAN")),
])
def test_wrong_score_comparison_is_reported(case_id, corrupt):
    planner_input, output, scorer = planner_case(case_id)
    corrupt(output["score_comparison"])
    assert codes(check_plan(planner_input, output, scorer)) == {"SCORE_COMPARISON"}


def test_score_comparison_presence_follows_the_previous_plan():
    planner_input, output, scorer = planner_case("P6")
    output["score_comparison"] = None
    assert codes(check_plan(planner_input, output, scorer)) == {"SCORE_COMPARISON"}
    planner_input, output, scorer = planner_case("P2")
    output["score_comparison"] = {"basis": "PREVIOUS_ACTIVITY_SET_RESCORED"}
    assert codes(check_plan(planner_input, output, scorer)) == {"SCORE_COMPARISON"}


def test_plan_version_and_based_on_are_recomputed():
    planner_input, output, scorer = planner_case("P2")
    output["plan_version"] = "sp3plan-0000000000000000"
    assert codes(check_plan(planner_input, output, scorer)) == {"PLAN_VERSION"}
    planner_input, output, scorer = planner_case("P5")
    output["based_on"]["previous_plan_version"] = None
    assert codes(check_plan(planner_input, output, scorer)) == {"BASED_ON_MISMATCH", "PLAN_VERSION"}


def test_reasons_must_follow_the_scheduled_attribution_order():
    planner_input, output, scorer = planner_case("P9")
    reasons = {e["activity_id"]: e["reasons"][0] for e in output["selected_activities"]}
    reasons["G"]["projected_added"], reasons["F"]["projected_added"] = 3, 5
    assert codes(check_plan(planner_input, output, scorer)) == {"REASON_MISMATCH"}


def test_keep_conflicts_are_recomputed():
    planner_input, output, scorer = planner_case("P4")
    output["keep_conflicts"] = []
    assert codes(check_plan(planner_input, output, scorer)) == {"KEEP_CONFLICT_MISMATCH"}
    planner_input, output, scorer = planner_case("P4")
    output["search"]["evaluated_subsets"] = 1
    assert "KEEP_CONFLICT_SHAPE" in codes(check_plan(planner_input, output, scorer))
    planner_input, output, scorer = planner_case("P6")
    output["keep_conflicts"] = [{"activity_id": "X", "code": "BLOCK_INVALID", "message": "Invented."}]
    assert codes(check_plan(planner_input, output, scorer)) == {"KEEP_CONFLICT_SHAPE"}


def test_ignored_keep_conflict_is_reported():
    planner_input, output, scorer = planner_case("P6")
    planner_input["keep_requests"] = keep("X")  # X's kept 09:00 block is busy now
    assert "KEEP_CONFLICT_MISSED" in codes(check_plan(planner_input, output, scorer))


def test_scheduling_limit_cannot_claim_completeness():
    planner_input, output, scorer = planner_case("P1")
    output["search"]["limit_reason"] = "SCHEDULING_LIMIT"
    assert "SEARCH_OVERCLAIM" in codes(check_plan(planner_input, output, scorer))


def test_already_met_is_not_allowed_with_a_previous_plan():
    planner_input, output, scorer = planner_case("P6")
    output.update(status="ALREADY_MET", feasibility_conclusion="REACHABLE", selected_activities=[])
    output["search"] = {"complete": False, "optimality_proven": True, "evaluated_subsets": 1, "limit_reason": "ALREADY_MET"}
    assert "ALREADY_MET_SHAPE" in codes(check_plan(planner_input, output, scorer))
