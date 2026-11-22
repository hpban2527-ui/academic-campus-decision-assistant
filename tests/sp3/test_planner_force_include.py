"""Contract revision 0.2.1: FORCE_INCLUDE keep requests (planner, checker and validator).

Scores come from CappedAdditiveScorer, a toy model; NOT real SP2 scoring.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
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
)
from sp3.contract import ContractError, KeepMode, parse_keep_requests, validate_keep_requests, validate_previous_plan
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip

BASE = {"scores": {"C1": 0}, "caps": {"C1": 30}, "category_targets": {"C1": 10}}


def force(*activity_ids):
    return [{"activity_id": activity_id, "mode": KeepMode.FORCE_INCLUDE.value} for activity_id in activity_ids]


def fixed(activity_id, *blocks, status="FEASIBLE", **options):
    activity = make_activity(activity_id, blocks[0][0], blocks[-1][1], mode="offline")
    return make_candidate(activity, status, schedule=fixed_schedule(*blocks), **options)


def flexible(activity_id, start, end, minutes, status="FEASIBLE", **options):
    activity = make_activity(activity_id, start, end)
    return make_candidate(activity, status, schedule=flexible_schedule(start, end, minutes), **options)


def model(*ids, points=5):
    return CappedAdditiveScorer({activity_id: ("C1", points) for activity_id in ids})


def plan(planner_input, scorer, **options):
    """Run the planner, assert the input is untouched and the independent checker passes."""
    snapshot = deepcopy(planner_input)
    output = build_plan(planner_input, scorer, **options)
    assert planner_input == snapshot
    assert check_plan(planner_input, output, scorer, input_snapshot=snapshot) == []
    return output


def blocks_of(output):
    return {
        entry["activity_id"]: [(b["start"], b["end"]) for b in entry["scheduled_blocks"]]
        for entry in output["selected_activities"]
    }


def conflicts_of(output):
    return [(entry["activity_id"], entry["code"]) for entry in output["keep_conflicts"]]


# Validator -----------------------------------------------------------------------------

def test_force_include_may_name_an_activity_outside_previous_plan():
    previous = validate_previous_plan(make_previous_plan({"A": [(at(2, 9), at(2, 10))]}), "p")
    parsed = parse_keep_requests([*keep("A"), *force("B")], previous, "k")
    assert parsed.keep_time == frozenset({"A"})
    assert parsed.force_include == frozenset({"B"})
    assert parsed.required == frozenset({"A", "B"})
    assert parse_keep_requests(force("B"), None, "k").force_include == frozenset({"B"})
    # validate_keep_requests keeps its 0.2 meaning: the time-frozen IDs.
    assert validate_keep_requests([*keep("A"), *force("B")], previous, "k") == frozenset({"A"})


@pytest.mark.parametrize("requests", [
    [*force("A"), *keep("A")],
    [*force("A"), *force("A")],
    [{"activity_id": "A", "mode": "FORCE_TIME"}],
    [{"activity_id": "A", "mode": ["FORCE_INCLUDE"]}],
    keep("B"),
])
def test_invalid_mixes_are_rejected(requests):
    previous = validate_previous_plan(make_previous_plan({"A": [(at(2, 9), at(2, 10))]}), "p")
    with pytest.raises(ContractError):
        parse_keep_requests(requests, previous, "k")


# Placement -----------------------------------------------------------------------------

def kept_block_case(**options):
    # K is frozen at 09:00-10:00 (window 08:00-12:00). F needs a free 120-minute sitting in
    # its own window 08:00-12:00, which only exists at 10:00-12:00.
    candidates = [flexible("K", at(2, 8), at(2, 12), 60), flexible("F", at(2, 8), at(2, 12), 120)]
    return make_planner_input(
        candidates, **BASE,
        previous_plan=make_previous_plan({"K": [(at(2, 9), at(2, 10))]}),
        keep_requests=[*keep("K"), *force("F")],
        **options,
    )


def test_forced_flexible_activity_is_selected_and_placed_around_kept_blocks():
    output = plan(kept_block_case(), model("K", "F"))
    assert output["status"] == "TARGET_MET"
    assert blocks_of(output) == {
        "K": [(at(2, 9), at(2, 10))],
        "F": [(at(2, 10), at(2, 12))],
    }
    changes = {entry["activity_id"]: entry["change"] for entry in output["selected_activities"]}
    assert changes == {"K": "KEPT", "F": "ADDED"}
    assert output["score_summary"]["projected_total"] == 10


def test_forced_flexible_activity_is_placed_without_any_previous_plan():
    candidates = [flexible("F", at(2, 8), at(2, 12), 120), flexible("G", at(2, 8), at(2, 12), 60)]
    planner_input = make_planner_input(candidates, **BASE, keep_requests=force("F"))
    output = plan(planner_input, model("F", "G"))
    assert "F" in blocks_of(output)
    assert output["based_on"]["previous_plan_version"] is None


def test_force_include_wins_over_a_better_ranked_alternative():
    # G alone meets the target and is shorter, but F is required, so F stays in the plan.
    candidates = [flexible("F", at(2, 8), at(2, 12), 120), flexible("G", at(2, 8), at(2, 12), 30)]
    planner_input = make_planner_input(candidates, **BASE, keep_requests=force("F"))
    output = plan(planner_input, CappedAdditiveScorer({"F": ("C1", 4), "G": ("C1", 10)}))
    assert set(blocks_of(output)) == {"F", "G"}


def test_forced_activity_already_in_previous_plan_is_not_time_frozen():
    # F was planned at 09:00-10:00, but K is frozen at 09:30-10:30, so F has to move.
    candidates = [flexible("K", at(2, 8), at(2, 12), 60), flexible("F", at(2, 8), at(2, 12), 60)]
    planner_input = make_planner_input(
        candidates, **BASE,
        previous_plan=make_previous_plan({"K": [(at(2, 9, 30), at(2, 10, 30))], "F": [(at(2, 9), at(2, 10))]}),
        keep_requests=[*keep("K"), *force("F")],
    )
    output = plan(planner_input, model("K", "F"))
    blocks = blocks_of(output)
    assert blocks["K"] == [(at(2, 9, 30), at(2, 10, 30))]
    assert blocks["F"] != [(at(2, 9), at(2, 10))]
    assert {e["activity_id"]: e["change"] for e in output["selected_activities"]}["F"] == "MOVED"


def test_forced_fixed_activity_outside_previous_plan_is_selected():
    candidates = [fixed("X", (at(3, 9), at(3, 10))), flexible("K", at(2, 8), at(2, 12), 60)]
    planner_input = make_planner_input(
        candidates, **BASE,
        previous_plan=make_previous_plan({"K": [(at(2, 9), at(2, 10))]}),
        keep_requests=[*keep("K"), *force("X")],
    )
    output = plan(planner_input, model("K", "X"))
    assert blocks_of(output)["X"] == [(at(3, 9), at(3, 10))]


def test_what_if_skip_drops_a_forced_activity_request():
    planner_input = kept_block_case()
    output = what_if_skip(planner_input, "F", model("K", "F"))
    assert output["status"] != "KEEP_CONFLICT"
    assert "F" not in blocks_of(output)


# Impossible requests report keep conflicts ------------------------------------------------

def test_force_include_without_a_free_slot_is_a_keep_conflict():
    # K frozen 09:00-10:00 leaves only 08:00-09:00 and 10:00-... but F's window ends at 11:00.
    candidates = [flexible("K", at(2, 8), at(2, 12), 60), flexible("F", at(2, 8), at(2, 11), 120)]
    planner_input = make_planner_input(
        candidates, **BASE,
        previous_plan=make_previous_plan({"K": [(at(2, 9), at(2, 10))]}),
        keep_requests=[*keep("K"), *force("F")],
    )
    scorer = StaticTableScorer([])
    output = plan(planner_input, scorer)
    assert output["status"] == "KEEP_CONFLICT"
    assert conflicts_of(output) == [("F", "NO_TIME")]
    assert output["selected_activities"] == [] and output["score_summary"] is None and output["plan_version"] is None
    assert all(entry["message"].strip() for entry in output["keep_conflicts"])
    assert scorer.call_count == 0


def test_forced_activities_that_only_fail_together_all_report_no_time():
    candidates = [flexible("F", at(2, 8), at(2, 10), 90), flexible("G", at(2, 8), at(2, 10), 90)]
    planner_input = make_planner_input(candidates, **BASE, keep_requests=force("F", "G"))
    output = plan(planner_input, StaticTableScorer([]))
    assert output["status"] == "KEEP_CONFLICT"
    assert conflicts_of(output) == [("F", "NO_TIME"), ("G", "NO_TIME")]


@pytest.mark.parametrize("name,expected", [
    ("not_listed", [("GONE", "NOT_LISTED")]),
    ("infeasible", [("F", "NOT_ELIGIBLE")]),
    ("completed", [("F", "NOT_ELIGIBLE")]),
    ("counted", [("F", "NOT_ELIGIBLE")]),
    ("declared_conflict", [("A", "CONFLICT"), ("F", "CONFLICT")]),
    ("fixed_overlaps_kept_block", [("F", "BLOCK_OVERLAP"), ("K", "BLOCK_OVERLAP")]),
    ("limit", [("F", "LIMIT"), ("K", "LIMIT")]),
])
def test_other_force_include_conflicts(name, expected):
    candidates = [flexible("K", at(2, 8), at(2, 12), 60)]
    previous = make_previous_plan({"K": [(at(2, 9), at(2, 10))]})
    requests = [*keep("K"), *force("F")]
    extra = {}
    if name == "not_listed":
        requests = force("GONE")
        previous = None
    elif name == "infeasible":
        candidates.append(flexible("F", at(2, 8), at(2, 12), 60, status="INFEASIBLE"))
    elif name == "completed":
        candidates.append(flexible("F", at(2, 8), at(2, 12), 60, progress="COMPLETED"))
    elif name == "counted":
        candidates.append(flexible("F", at(2, 8), at(2, 12), 60))
        extra["included"] = ["F"]
    elif name == "declared_conflict":
        candidates = [fixed("A", (at(3, 9), at(3, 10))), fixed("F", (at(4, 9), at(4, 10)))]
        previous = make_previous_plan({"A": [(at(3, 9), at(3, 10))]})
        requests = [*keep("A"), *force("F")]
        extra["conflict_pairs"] = [["A", "F"]]
    elif name == "fixed_overlaps_kept_block":
        candidates.append(fixed("F", (at(2, 9, 30), at(2, 10, 30))))
    elif name == "limit":
        candidates.append(flexible("F", at(2, 8), at(2, 12), 60))
        extra["max_activities"] = 1
    planner_input = make_planner_input(candidates, **BASE, previous_plan=previous, keep_requests=requests, **extra)
    output = plan(planner_input, StaticTableScorer([]))
    assert output["status"] == "KEEP_CONFLICT"
    assert conflicts_of(output) == expected


def test_checker_rejects_a_plan_that_drops_a_forced_activity():
    planner_input = kept_block_case()
    scorer = model("K", "F")
    output = build_plan(planner_input, scorer)
    tampered = deepcopy(output)
    tampered["selected_activities"] = [e for e in tampered["selected_activities"] if e["activity_id"] != "F"]
    codes = {violation.code for violation in check_plan(planner_input, tampered, scorer)}
    assert "FORCE_NOT_HONORED" in codes


# Regression: forcing a plan's own set reproduces the plan ---------------------------------

def regression_input(**options):
    candidates = [
        fixed("A", (at(2, 9), at(2, 10))),
        fixed("B", (at(3, 14), at(3, 15))),
        flexible("C", at(2, 8), at(2, 12), 90),
        flexible("D", at(2, 8), at(2, 12), 60),
        flexible("E", at(2, 8), at(5, 18), 60),
    ]
    return make_planner_input(
        candidates, scores={"C1": 0}, caps={"C1": 30}, category_targets={"C1": 20}, **options,
    )


def test_forcing_the_planned_set_reproduces_projected_score_and_blocks():
    scorer = model("A", "B", "C", "D", "E")
    original = plan(regression_input(), scorer)
    chosen = [entry["activity_id"] for entry in original["selected_activities"]]
    assert len(chosen) >= 2

    forced = plan(regression_input(keep_requests=force(*chosen)), scorer)
    assert [e["activity_id"] for e in forced["selected_activities"]] == chosen
    assert blocks_of(forced) == blocks_of(original)
    assert forced["score_summary"] == original["score_summary"]
    assert forced["status"] == original["status"]


def test_keeping_the_planned_set_reproduces_projected_score_and_blocks():
    scorer = model("A", "B", "C", "D", "E")
    original = plan(regression_input(), scorer)
    chosen = [entry["activity_id"] for entry in original["selected_activities"]]
    previous = make_previous_plan({a: blocks for a, blocks in blocks_of(original).items()})

    kept = plan(regression_input(previous_plan=previous, keep_requests=keep(*chosen)), scorer)
    assert blocks_of(kept) == blocks_of(original)
    assert kept["score_summary"]["projected_total"] == original["score_summary"]["projected_total"]
    assert {e["change"] for e in kept["selected_activities"]} == {"KEPT"}
