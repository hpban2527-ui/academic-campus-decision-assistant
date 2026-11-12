"""Planner v0.2: scheduling, replan, keep requests and what_if_skip, with toy scorers.

Scores come from CappedAdditiveScorer or static tables; NOT real SP2 scoring.
Expected plans below are derived by hand in the comments.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import random
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import (
    CappedAdditiveScorer,
    StaticTableScorer,
    at,
    fixed_schedule,
    flexible_schedule,
    keep,
    make_activity,
    make_candidate,
    make_planner_input,
    make_previous_plan,
    static_result,
)
from sp3.contract import ContractError
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip


def fixed(activity_id, *blocks, status="FEASIBLE", codes=None, **options):
    activity = make_activity(activity_id, blocks[0][0], blocks[-1][1], mode="offline", domain=options.pop("domain", "academic"))
    return make_candidate(activity, status, codes, schedule=fixed_schedule(*blocks), **options)


def flexible(activity_id, start, end, minutes, status="FEASIBLE", codes=None, **options):
    activity = make_activity(activity_id, start, end, domain=options.pop("domain", "academic"))
    return make_candidate(activity, status, codes, schedule=flexible_schedule(start, end, minutes), **options)


def plan(planner_input, scorer, **options):
    """Run the planner, assert the input is untouched and the checker passes."""
    snapshot = deepcopy(planner_input)
    output = build_plan(planner_input, scorer, **options)
    assert planner_input == snapshot
    if output["status"] not in ("ERROR", "NEEDS_DATA"):
        assert check_plan(planner_input, output, scorer, input_snapshot=snapshot) == []
    return output


def model(*ids, points=5):
    return CappedAdditiveScorer({activity_id: ("C1", points) for activity_id in ids})


def selected(output):
    return [(e["activity_id"], [(b["start"], b["end"]) for b in e["scheduled_blocks"]], e["change"]) for e in output["selected_activities"]]


def codes(entries):
    return {entry["activity_id"]: entry["code"] for entry in entries}


def warning_codes(output):
    return [warning["code"] for warning in output["warnings"]]


# Stable replan, moves and forced changes --------------------------------------------

def test_stable_replan_keeps_every_activity_when_equal_alternatives_exist():
    # X and Y sit at 10:00 and 11:00, not at the earliest slots. Z scores the same and
    # matches the preferred domain, but {X, Y} has 0 set changes and 0 time changes.
    candidates = [
        flexible("X", at(2, 8), at(2, 12), 60), flexible("Y", at(2, 8), at(2, 12), 60),
        flexible("Z", at(2, 8), at(2, 12), 60, domain="skills"),
    ]
    previous = make_previous_plan({"X": [(at(2, 10), at(2, 11))], "Y": [(at(2, 11), at(2, 12))]})
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30}, preferred_domains=["skills"],
        available=[(at(2, 8), at(2, 12))], previous_plan=previous,
    )
    output = plan(planner_input, model("X", "Y", "Z"))
    assert selected(output) == [("X", [(at(2, 10), at(2, 11))], "KEPT"), ("Y", [(at(2, 11), at(2, 12))], "KEPT")]
    assert codes(output["excluded_candidates"]) == {"Z": "LOWER_PRIORITY"}
    assert output["dropped_activities"] == []
    assert output["score_comparison"]["previous_activity_ids"] == ["X", "Y"]
    assert output["score_comparison"]["previous_projected_total"] == output["score_comparison"]["new_projected_total"] == 30
    # Without the previous plan the preferred Z would replace one of them.
    fresh = plan({**planner_input, "previous_plan": None}, model("X", "Y", "Z"))
    assert sorted(e["activity_id"] for e in fresh["selected_activities"]) == ["X", "Z"]


def test_activity_moves_without_being_replaced_and_keeps_its_score():
    # A's fixed block is unchanged; X's old 09:00 block is busy now, so X moves to 10:00.
    candidates = [fixed("A", (at(2, 8), at(2, 9))), flexible("X", at(2, 8), at(2, 12), 60)]
    previous = make_previous_plan({"A": [(at(2, 8), at(2, 9))], "X": [(at(2, 9), at(2, 10))]})
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30},
        available=[(at(2, 8), at(2, 9)), (at(2, 10), at(2, 12))], previous_plan=previous,
    )
    output = plan(planner_input, model("A", "X"))
    assert selected(output) == [("A", [(at(2, 8), at(2, 9))], "KEPT"), ("X", [(at(2, 10), at(2, 11))], "MOVED")]
    assert output["status"] == "TARGET_MET"
    comparison = output["score_comparison"]
    assert comparison["previous_projected_total"] == comparison["new_projected_total"] == 30


def test_changed_fixed_sessions_are_a_forced_time_change():
    # A's sessions moved from Nov 2 09:00 to 14:00. Keeping A (0 set changes, 1 time change)
    # still beats dropping it (1 set change).
    candidates = [fixed("A", (at(2, 14), at(2, 15)))]
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 25},
        previous_plan=make_previous_plan({"A": [(at(2, 9), at(2, 10))]}),
    )
    output = plan(planner_input, model("A"))
    assert selected(output) == [("A", [(at(2, 14), at(2, 15))], "MOVED")]


def test_registered_activity_that_is_no_longer_feasible_is_dropped_with_a_warning():
    candidates = [
        fixed("R", (at(2, 9), at(2, 10)), status="INFEASIBLE", codes=["OUTSIDE_AVAILABILITY"], registration="REGISTERED"),
        fixed("B", (at(3, 9), at(3, 10))),
    ]
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 25},
        available=[(at(3, 0), at(4, 0))], previous_plan=make_previous_plan({"R": [(at(2, 9), at(2, 10))]}),
    )
    output = plan(planner_input, model("B"))
    assert [(e["activity_id"], e["registered"], e["code"]) for e in output["dropped_activities"]] == [("R", True, "NO_LONGER_FEASIBLE")]
    assert "OUTSIDE_AVAILABILITY" in output["dropped_activities"][0]["message"]
    assert codes(output["excluded_candidates"]) == {"R": "NOT_FEASIBLE"}
    assert "DROPS_REGISTERED" in warning_codes(output)
    assert output["score_comparison"]["previous_activity_ids"] == []


def test_cancelled_and_completed_previous_activities():
    # C was cancelled (dropped, code CANCELLED). D is completed but not counted yet
    # (pending confirmation, not in P). E is completed and counted (neither).
    candidates = [
        fixed("A", (at(2, 14), at(2, 15))),
        fixed("C", (at(2, 9), at(2, 10)), status="INFEASIBLE", codes=["CANCELLED"], progress="CANCELLED"),
        fixed("D", (at(3, 9), at(3, 10)), status="INFEASIBLE", codes=["ALREADY_COMPLETED"], progress="COMPLETED", registration="REGISTERED"),
        fixed("E", (at(4, 9), at(4, 10)), status="INFEASIBLE", codes=["ALREADY_COMPLETED"], progress="COMPLETED"),
    ]
    previous = make_previous_plan({a: [(at(d, h), at(d, h + 1))] for a, d, h in (("A", 2, 14), ("C", 2, 9), ("D", 3, 9), ("E", 4, 9))})
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 25}, included=["E"], previous_plan=previous,
    )
    scorer = model("A")  # D and E have no score model: scoring them would fail.
    output = plan(planner_input, scorer)
    assert selected(output) == [("A", [(at(2, 14), at(2, 15))], "KEPT")]
    assert [(e["activity_id"], e["registered"], e["code"]) for e in output["dropped_activities"]] == [("C", False, "CANCELLED")]
    assert output["pending_confirmation"] == ["D"]
    assert codes(output["excluded_candidates"]) == {"C": "NOT_FEASIBLE", "D": "NOT_FEASIBLE", "E": "NOT_FEASIBLE"}
    assert warning_codes(output) == ["DEMO_ONLY", "TRAVEL_NOT_MODELED", "PENDING_CONFIRMATION"]
    assert output["score_comparison"]["previous_activity_ids"] == ["A"]


def test_previously_selected_activity_that_is_no_longer_listed_is_dropped():
    candidates = [fixed("A", (at(2, 14), at(2, 15)))]
    previous = make_previous_plan({"OLD": [(at(2, 9), at(2, 10))], "A": [(at(2, 14), at(2, 15))]})
    planner_input = make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 25}, previous_plan=previous)
    output = plan(planner_input, model("A"))
    assert [(e["activity_id"], e["registered"], e["code"]) for e in output["dropped_activities"]] == [("OLD", False, "NOT_LISTED")]
    assert output["score_comparison"]["previous_activity_ids"] == ["A"]


def test_baseline_meeting_targets_with_a_previous_plan_keeps_the_plan():
    # No ALREADY_MET with a previous plan: keeping A has 0 changes and outranks the empty plan.
    candidates = [fixed("A", (at(2, 14), at(2, 15))), fixed("B", (at(3, 9), at(3, 10)))]
    planner_input = make_planner_input(
        candidates, scores={"C1": 28}, caps={"C1": 30}, category_targets={"C1": 25},
        previous_plan=make_previous_plan({"A": [(at(2, 14), at(2, 15))]}),
    )
    output = plan(planner_input, model("A", "B"))
    assert output["status"] == "TARGET_MET"
    assert selected(output) == [("A", [(at(2, 14), at(2, 15))], "KEPT")]
    # Dominance pruning is disabled with a previous plan: all 4 subsets are scored.
    assert output["search"] == {"complete": True, "optimality_proven": True, "evaluated_subsets": 4, "limit_reason": None}


def test_keep_with_baseline_already_meeting_targets_returns_the_kept_plan():
    candidates = [flexible("K", at(2, 8), at(2, 12), 60), fixed("B", (at(3, 9), at(3, 10)))]
    planner_input = make_planner_input(
        candidates, scores={"C1": 28}, caps={"C1": 30}, category_targets={"C1": 25},
        previous_plan=make_previous_plan({"K": [(at(2, 10), at(2, 11))]}), keep_requests=keep("K"),
    )
    scorer = model("K", "B")
    output = plan(planner_input, scorer)
    assert output["status"] == "TARGET_MET"
    assert selected(output) == [("K", [(at(2, 10), at(2, 11))], "KEPT")]
    # Only supersets of the kept set are valid: {K} and {B, K}.
    assert output["search"]["evaluated_subsets"] == 2


def test_dominance_pruning_still_applies_without_a_previous_plan():
    candidates = [fixed("A", (at(2, 14), at(2, 15))), fixed("B", (at(3, 9), at(3, 10)))]
    planner_input = make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 25})
    output = plan(planner_input, model("A", "B"))
    assert output["search"] == {"complete": False, "optimality_proven": True, "evaluated_subsets": 3, "limit_reason": None}
    assert "SEARCH_INCOMPLETE" in warning_codes(output)


def test_no_feasible_candidates_with_a_previous_plan():
    candidates = [fixed("A", (at(2, 9), at(2, 10)), status="INFEASIBLE", codes=["INELIGIBLE"])]
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 25},
        previous_plan=make_previous_plan({"A": [(at(2, 9), at(2, 10))]}),
    )
    scorer = model()
    output = plan(planner_input, scorer)
    assert output["status"] == "NO_FEASIBLE_CANDIDATES"
    assert output["proof"] == {"kind": "EXHAUSTIVE_SEARCH", "evaluated_subsets": 1}
    assert [(e["activity_id"], e["code"]) for e in output["dropped_activities"]] == [("A", "NO_LONGER_FEASIBLE")]
    assert output["score_comparison"]["previous_activity_ids"] == []


# Exclusions and limits ------------------------------------------------------------------

def test_conflict_ranks_before_no_time_and_no_time_before_limit():
    # A and B overlap (declared pair): B is CONFLICT although it has no time either.
    # X and Y compete for the single free hour: Y is NO_TIME although max_activities is also hit.
    candidates = [
        fixed("A", (at(2, 9), at(2, 10))), fixed("B", (at(2, 9, 30), at(2, 10, 30))),
        flexible("X", at(3, 8), at(3, 12), 60), flexible("Y", at(3, 8), at(3, 12), 60),
    ]
    planner_input = make_planner_input(
        candidates, scores={"C1": 10}, caps={"C1": 30}, category_targets={"C1": 30}, max_activities=2,
        conflict_pairs=[["A", "B"]], available=[(at(2, 9), at(2, 11)), (at(3, 9), at(3, 10))],
    )
    output = plan(planner_input, model("A", "B", "X", "Y"))
    assert [e["activity_id"] for e in output["selected_activities"]] == ["A", "X"]
    assert codes(output["excluded_candidates"]) == {"B": "CONFLICT", "Y": "NO_TIME"}


@pytest.mark.parametrize("limit,expected", [(150, ["M", "X"]), (149, ["X"])])
def test_duration_limit_counts_fixed_sessions_and_flexible_duration(limit, expected):
    # M has two 60-minute sessions (120 minutes); X is a 30-minute sitting. Alone, X is shorter.
    candidates = [fixed("M", (at(2, 9), at(2, 10)), (at(3, 9), at(3, 10))), flexible("X", at(2, 13), at(2, 17), 30)]
    planner_input = make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30}, max_duration_minutes=limit)
    output = plan(planner_input, model("M", "X"))
    assert sorted(e["activity_id"] for e in output["selected_activities"]) == expected
    if limit == 149:
        assert codes(output["excluded_candidates"]) == {"M": "LIMIT"}


def test_feasible_but_cancelled_candidate_is_not_selectable():
    # what_if_skip produces this shape: the feasibility status predates the cancellation.
    candidates = [fixed("A", (at(2, 9), at(2, 10)), progress="CANCELLED"), fixed("B", (at(3, 9), at(3, 10)))]
    planner_input = make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30})
    output = plan(planner_input, model("A", "B"))
    assert codes(output["excluded_candidates"]) == {"A": "NOT_FEASIBLE"}
    assert output["excluded_candidates"][0]["message"] == "Cancelled by the student."


# Keep conflicts -------------------------------------------------------------------------

def keep_case(name):
    """(planner_input, expected [(activity_id, code)]) for one kind of keep conflict."""
    base = dict(scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30})
    k_flexible = flexible("K", at(2, 8), at(2, 12), 60)
    if name == "not_listed":
        return make_planner_input([k_flexible], **base, previous_plan=make_previous_plan({"GONE": [(at(2, 9), at(2, 10))]}),
                                  keep_requests=keep("GONE")), [("GONE", "NOT_LISTED")]
    if name in ("needs_review", "infeasible", "cancelled", "counted"):
        options = {
            "needs_review": dict(status="NEEDS_REVIEW", codes=["MISSING_ELIGIBILITY"]),
            "infeasible": dict(status="INFEASIBLE", codes=["INELIGIBLE"]),
            "cancelled": dict(status="INFEASIBLE", codes=["CANCELLED"], progress="CANCELLED"),
            "counted": {},
        }[name]
        candidate = flexible("K", at(2, 8), at(2, 12), 60, **options)
        return make_planner_input([candidate], **base, included=["K"] if name == "counted" else [],
                                  previous_plan=make_previous_plan({"K": [(at(2, 9), at(2, 10))]}), keep_requests=keep("K")), [("K", "NOT_ELIGIBLE")]
    if name == "fixed_changed":
        return make_planner_input([fixed("F", (at(2, 14), at(2, 15)))], **base,
                                  previous_plan=make_previous_plan({"F": [(at(2, 9), at(2, 10))]}), keep_requests=keep("F")), [("F", "FIXED_CHANGED")]
    if name in ("outside_window", "wrong_duration", "outside_availability"):
        block = {"outside_window": (at(2, 12), at(2, 13)), "wrong_duration": (at(2, 9), at(2, 9, 30)), "outside_availability": (at(2, 9), at(2, 10))}[name]
        available = [(at(2, 10), at(2, 12))] if name == "outside_availability" else None
        return make_planner_input([k_flexible], **base, available=available,
                                  previous_plan=make_previous_plan({"K": [block]}), keep_requests=keep("K")), [("K", "BLOCK_INVALID")]
    if name == "overlap":
        candidates = [k_flexible, flexible("L", at(2, 8), at(2, 12), 60), fixed("F", (at(2, 9, 45), at(2, 10, 45)))]
        previous = make_previous_plan({"K": [(at(2, 9), at(2, 10))], "L": [(at(2, 9, 30), at(2, 10, 30))], "F": [(at(2, 9, 45), at(2, 10, 45))]})
        return make_planner_input(candidates, **base, previous_plan=previous, keep_requests=keep("K", "L", "F")), [
            ("F", "BLOCK_OVERLAP"), ("F", "BLOCK_OVERLAP"), ("K", "BLOCK_OVERLAP"), ("K", "BLOCK_OVERLAP"),
            ("L", "BLOCK_OVERLAP"), ("L", "BLOCK_OVERLAP"),
        ]
    if name == "declared_conflict":
        candidates = [fixed("A", (at(2, 9), at(2, 10))), fixed("B", (at(3, 9), at(3, 10)))]
        previous = make_previous_plan({"A": [(at(2, 9), at(2, 10))], "B": [(at(3, 9), at(3, 10))]})
        return make_planner_input(candidates, **base, conflict_pairs=[["A", "B"]], previous_plan=previous,
                                  keep_requests=keep("A", "B")), [("A", "CONFLICT"), ("B", "CONFLICT")]
    if name in ("count_limit", "minutes_limit"):
        candidates = [fixed("A", (at(2, 9), at(2, 11))), flexible("K", at(3, 8), at(3, 12), 60)]
        previous = make_previous_plan({"A": [(at(2, 9), at(2, 11))], "K": [(at(3, 8), at(3, 9))]})
        limits = {"max_activities": 1} if name == "count_limit" else {"max_duration_minutes": 179}
        return make_planner_input(candidates, **base, **limits, previous_plan=previous,
                                  keep_requests=keep("K", "A")), [("A", "LIMIT"), ("K", "LIMIT")]
    if name == "several":
        candidates = [fixed("A", (at(2, 9), at(2, 11))), flexible("K", at(3, 8), at(3, 12), 60)]
        previous = make_previous_plan({"A": [(at(2, 9), at(2, 11))], "K": [(at(3, 13), at(3, 14))], "GONE": [(at(4, 9), at(4, 10))]})
        return make_planner_input(candidates, **base, max_activities=2, previous_plan=previous,
                                  keep_requests=keep("A", "GONE", "K")), [("A", "LIMIT"), ("GONE", "NOT_LISTED"), ("GONE", "LIMIT"), ("K", "BLOCK_INVALID"), ("K", "LIMIT")]
    raise AssertionError(name)


KEEP_CASES = [
    "not_listed", "needs_review", "infeasible", "cancelled", "counted", "fixed_changed", "outside_window",
    "wrong_duration", "outside_availability", "overlap", "declared_conflict", "count_limit", "minutes_limit", "several",
]


@pytest.mark.parametrize("name", KEEP_CASES)
def test_each_keep_conflict_kind_returns_keep_conflict_before_scoring(name):
    planner_input, expected = keep_case(name)
    scorer = StaticTableScorer([])
    output = plan(planner_input, scorer)
    assert output["status"] == "KEEP_CONFLICT"
    assert [(e["activity_id"], e["code"]) for e in output["keep_conflicts"]] == expected
    assert all(e["message"].strip() for e in output["keep_conflicts"])
    assert output["selected_activities"] == [] and output["score_summary"] is None and output["proof"] is None
    assert output["feasibility_conclusion"] == "UNDETERMINED"
    assert output["search"] == {"complete": False, "optimality_proven": False, "evaluated_subsets": 0, "limit_reason": "KEEP_CONFLICT"}
    assert output["plan_version"] is None and output["score_comparison"] is None
    assert output["based_on"]["previous_plan_version"] == planner_input["previous_plan"]["plan_version"]
    assert scorer.call_count == 0


def test_overlap_messages_name_the_other_kept_activity():
    planner_input, _ = keep_case("overlap")
    messages = [e["message"] for e in build_plan(planner_input, StaticTableScorer([]))["keep_conflicts"] if e["activity_id"] == "K"]
    assert messages == ["The kept block overlaps kept activity F.", "The kept block overlaps kept activity L."]


# Scheduling limit ------------------------------------------------------------------------

def three_sittings(window_end_hour):
    candidates = [flexible(name, at(2, 8), at(2, window_end_hour), 60) for name in "ABC"]
    return make_planner_input(
        candidates, scores={"C1": 15}, caps={"C1": 30}, category_targets={"C1": 30},
        available=[(at(2, 8), at(2, 12))],
    )


def test_scheduler_limit_never_claims_impossibility():
    # The three one-hour sittings fit 08:00-11:00, but a cap of 2 cannot decide the triple.
    planner_input = three_sittings(12)
    assert plan(planner_input, model("A", "B", "C"))["status"] == "TARGET_MET"
    output = plan(planner_input, model("A", "B", "C"), max_flexible_per_set=2)
    assert output["status"] == "PARTIAL"
    assert output["feasibility_conclusion"] == "UNDETERMINED"
    assert output["proof"] is None
    assert output["search"] == {"complete": False, "optimality_proven": False, "evaluated_subsets": 7, "limit_reason": "SCHEDULING_LIMIT"}
    assert "SEARCH_INCOMPLETE" in warning_codes(output)
    excluded = output["excluded_candidates"]
    assert codes(excluded) == {"C": "LOWER_PRIORITY"}
    assert "not determined" in excluded[0]["message"]


def test_cap_exceeding_set_is_still_proven_unschedulable_through_a_smaller_set():
    # A and B both need 08:00-09:00, so {A, B} is unschedulable; C (window to 12:00) fits with either.
    # {A, B, C} exceeds a cap of 2 but contains {A, B}: B is NO_TIME and the search is complete.
    candidates = [flexible("A", at(2, 8), at(2, 9), 60), flexible("B", at(2, 8), at(2, 9), 60), flexible("C", at(2, 8), at(2, 12), 60)]
    planner_input = make_planner_input(candidates, scores={"C1": 15}, caps={"C1": 30}, category_targets={"C1": 30}, available=[(at(2, 8), at(2, 12))])
    capped = plan(planner_input, model("A", "B", "C"), max_flexible_per_set=2)
    exact = plan(planner_input, model("A", "B", "C"))
    assert capped == exact
    assert [e["activity_id"] for e in capped["selected_activities"]] == ["A", "C"]
    assert codes(capped["excluded_candidates"]) == {"B": "NO_TIME"}
    assert capped["feasibility_conclusion"] == "PROVEN_UNREACHABLE"
    assert capped["proof"] == {"kind": "EXHAUSTIVE_SEARCH", "evaluated_subsets": 6}


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_scheduling_cap_is_rejected(value):
    with pytest.raises(ValueError):
        build_plan(three_sittings(12), model("A", "B", "C"), max_flexible_per_set=value)


# Scorer calls and failures -----------------------------------------------------------------

def replan_input():
    candidates = [fixed("A", (at(2, 9), at(2, 10))), fixed("B", (at(3, 9), at(3, 10)))]
    return make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30},
        previous_plan=make_previous_plan({"A": [(at(2, 9), at(2, 10))]}),
    )


def table(*rows):
    before = {"C1": 20}
    return [
        {"selected_activity_ids": list(ids), "result": static_result(before, {"C1": 20 + 5 * len(ids)}, 100, 20, [(a, "C1", 5) for a in ids])}
        for ids in rows
    ]


def test_each_subset_is_scored_once_and_the_comparison_call_is_outside_the_budget():
    scorer = StaticTableScorer(table((), ("A",), ("B",), ("A", "B")))
    output = build_plan(replan_input(), scorer, max_evaluations=2)
    assert output["search"]["evaluated_subsets"] == 2
    assert output["search"]["limit_reason"] == "EVALUATION_LIMIT"
    assert scorer.calls == [(), ("A",), ("A",)]
    full = StaticTableScorer(table((), ("A",), ("B",), ("A", "B")))
    output = build_plan(replan_input(), full)
    assert full.calls == [(), ("A",), ("B",), ("A", "B"), ("A",)]
    assert output["search"]["evaluated_subsets"] == 4


@pytest.mark.parametrize("status,planner_status", [("NEEDS_REVIEW", "NEEDS_DATA"), ("ERROR", "ERROR")])
def test_scorer_failure_during_a_replan_search_returns_the_failure_shape(status, planner_status):
    rows = table((), ("B",), ("A", "B"))
    issue = {"code": "MISSING_BINDING", "message": "No trusted binding.", "activity_id": "A"}
    scorer = StaticTableScorer([*rows, {"selected_activity_ids": ["A"], "attribution_order": ["A"], "evaluation_status": status, "errors": [issue]}])
    # {A} fails during the search already (same set, same order): the evaluation count stops at 2.
    output = build_plan(replan_input(), scorer)
    assert output["status"] == planner_status
    assert output["search"] == {"complete": False, "optimality_proven": False, "evaluated_subsets": 2, "limit_reason": "SP2_FAILURE"}
    assert output["errors"] == [issue]
    assert (output["dropped_activities"], output["score_comparison"], output["plan_version"]) == ([], None, None)


def test_failure_only_on_the_comparison_rescore():
    # The previous set {A} is rescored in previous-block order; make only that set fail.
    candidates = [fixed("A", (at(2, 9), at(2, 10)), status="NEEDS_REVIEW", codes=["MISSING_ELIGIBILITY"]), fixed("B", (at(3, 9), at(3, 10)))]
    planner_input = make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30},
        previous_plan=make_previous_plan({"B": [(at(3, 9), at(3, 10))]}),
    )
    issue = {"code": "SP2_ENGINE_FAILURE", "message": "Engine failed.", "activity_id": None}
    scorer = StaticTableScorer(table((), ("B",)))
    calls = []

    def failing_on_comparison(request):
        calls.append(tuple(request["selected_activity_ids"]))
        if len(calls) == 3:
            return {**scorer(request), "evaluation_status": "ERROR", "result": None, "errors": [issue]}
        return scorer(request)

    output = build_plan(planner_input, failing_on_comparison)
    assert calls == [(), ("B",), ("B",)]
    assert output["status"] == "ERROR"
    assert output["search"]["evaluated_subsets"] == 2
    assert output["errors"] == [issue]
    assert "PENDING_CANDIDATES" in warning_codes(output)


# what_if_skip ---------------------------------------------------------------------------------

def what_if_input():
    candidates = [fixed("A", (at(2, 9), at(2, 10)), registration="REGISTERED"), flexible("K", at(3, 8), at(3, 12), 60), fixed("B", (at(4, 9), at(4, 10)))]
    previous = make_previous_plan({"A": [(at(2, 9), at(2, 10))], "K": [(at(3, 10), at(3, 11))]})
    return make_planner_input(
        candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30},
        previous_plan=previous, keep_requests=keep("K"),
    )


def test_what_if_skip_previews_without_changing_the_input():
    planner_input = what_if_input()
    snapshot = deepcopy(planner_input)
    output = what_if_skip(planner_input, "A", model("A", "B", "K"))
    assert planner_input == snapshot
    manual = deepcopy(planner_input)
    manual["candidates"][0]["participation"]["progress"] = "CANCELLED"
    assert output == build_plan(manual, model("A", "B", "K"))
    assert check_plan(manual, output, model("A", "B", "K")) == []
    assert selected(output) == [("K", [(at(3, 10), at(3, 11))], "KEPT"), ("B", [(at(4, 9), at(4, 10))], "ADDED")]
    assert [(e["activity_id"], e["registered"], e["code"]) for e in output["dropped_activities"]] == [("A", True, "CANCELLED")]
    assert "DROPS_REGISTERED" in warning_codes(output)
    assert output["score_comparison"]["previous_activity_ids"] == ["K"]


def test_what_if_skip_of_a_kept_activity_drops_its_keep_request():
    planner_input = what_if_input()
    snapshot = deepcopy(planner_input)
    output = what_if_skip(planner_input, "K", model("A", "B", "K"))
    assert planner_input == snapshot
    assert output["status"] == "TARGET_MET"
    assert [(e["activity_id"], e["code"]) for e in output["dropped_activities"]] == [("K", "CANCELLED")]
    assert [e["activity_id"] for e in output["selected_activities"]] == ["A", "B"]


def test_what_if_skip_requires_a_listed_candidate():
    with pytest.raises(ContractError):
        what_if_skip(what_if_input(), "UNKNOWN", model("A", "B", "K"))


# Determinism and versions ------------------------------------------------------------------------

def mixed_input():
    candidates = [
        fixed("A", (at(2, 9), at(2, 10))), fixed("B", (at(2, 9, 30), at(2, 11)), domain="skills"),
        flexible("C", at(2, 8), at(2, 12), 60), flexible("D", at(2, 8), at(2, 12), 90),
        flexible("E", at(3, 8), at(3, 12), 60, status="NEEDS_REVIEW", codes=["TERM_UNVERIFIED"]),
        fixed("F", (at(3, 9), at(3, 10)), registration="REGISTERED"), flexible("G", at(3, 8), at(3, 11), 120),
    ]
    previous = make_previous_plan({"C": [(at(2, 11), at(2, 12))], "F": [(at(3, 9), at(3, 10))], "OLD": [(at(4, 9), at(4, 10))]})
    return make_planner_input(
        candidates, scores={"C1": 10, "C2": 5}, caps={"C1": 30, "C2": 20}, category_targets={"C1": 25}, total_target=30,
        preferred_domains=["skills", "academic"], max_activities=4,
        conflict_pairs=[["A", "B"], ["C", "G"]],
        available=[(at(2, 8), at(2, 10)), (at(2, 10), at(2, 12)), (at(3, 8), at(3, 11))],
        previous_plan=previous, keep_requests=keep("F"),
    )


def mixed_scorer():
    return CappedAdditiveScorer({"A": ("C1", 3), "B": ("C2", 4), "C": ("C1", 5), "D": ("C1", 5), "E": ("C1", 2), "F": ("C2", 2), "G": ("C1", 4)})


def test_shuffled_inputs_give_identical_output():
    reference = plan(mixed_input(), mixed_scorer())
    assert reference["status"] in ("TARGET_MET", "PARTIAL")
    rng = random.Random(20261103)
    for _ in range(15):
        shuffled = mixed_input()
        for items in (shuffled["candidates"], shuffled["conflict_pairs"], shuffled["available_intervals"],
                      shuffled["previous_plan"]["selected_activities"], shuffled["preferences"]["preferred_domains"]):
            rng.shuffle(items)
        assert plan(shuffled, mixed_scorer()) == reference


def test_plan_version_depends_on_based_on_and_blocks():
    first = plan(mixed_input(), mixed_scorer())
    changed_calendar = mixed_input()
    changed_calendar["context"]["calendar_version"] = "synthetic-calendar-2"
    second = plan(changed_calendar, mixed_scorer())
    assert first["selected_activities"] == second["selected_activities"]
    assert first["plan_version"] != second["plan_version"]
    assert first["based_on"]["previous_plan_version"] == mixed_input()["previous_plan"]["plan_version"]
