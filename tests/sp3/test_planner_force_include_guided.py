"""FORCE_INCLUDE on large catalogs: the guided_v2 and greedy searches (more than 12 extra candidates).

Regression for the merge of the guided_v2 search: its subsets were built from the KEEP_TIME set only,
so a forced activity could be left out (checker: FORCE_NOT_HONORED). Scores come from
CappedAdditiveScorer, a toy model; NOT real SP2 scoring.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import (
    CappedAdditiveScorer,
    at,
    flexible_schedule,
    keep,
    make_activity,
    make_candidate,
    make_planner_input,
    make_previous_plan,
)
from sp3.contract import KeepMode
from sp3.plan_checker import check_plan
from sp3.planner import build_plan

BASE = {"scores": {"C1": 0}, "caps": {"C1": 60}, "category_targets": {"C1": 20}}
EXTRAS = [f"E{index:02d}" for index in range(14)]  # > 12 extras, so "auto" runs guided_v2


def force(*activity_ids):
    return [{"activity_id": activity_id, "mode": KeepMode.FORCE_INCLUDE.value} for activity_id in activity_ids]


def flexible(activity_id, day, minutes):
    start, end = at(day, 8), at(day, 12)
    return make_candidate(make_activity(activity_id, start, end), "FEASIBLE",
                          schedule=flexible_schedule(start, end, minutes))


def catalog():
    # F is weak and long; every extra alone is stronger and shorter, so a search that forgets F drops it.
    candidates = [flexible("F", 1, 180), flexible("K", 2, 60)]
    candidates += [flexible(activity_id, 3 + index % 4, 30) for index, activity_id in enumerate(EXTRAS)]
    points = {"F": ("C1", 2), "K": ("C1", 5)}
    points.update({activity_id: ("C1", 10) for activity_id in EXTRAS})
    return candidates, CappedAdditiveScorer(points)


def run(planner_input, scorer, **options):
    snapshot = deepcopy(planner_input)
    output = build_plan(planner_input, scorer, **options)
    assert planner_input == snapshot
    assert check_plan(planner_input, output, scorer, input_snapshot=snapshot) == []
    return output


def selected(output):
    return {entry["activity_id"] for entry in output["selected_activities"]}


@pytest.mark.parametrize("method", ["auto", "guided_v2", "greedy", "beam_v1"])
@pytest.mark.parametrize("strategy", ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"])
def test_forced_activity_is_kept_by_large_catalog_searches(method, strategy):
    candidates, scorer = catalog()
    planner_input = make_planner_input(candidates, **BASE, keep_requests=force("F"))
    output = run(planner_input, scorer, search_method=method, personalization_strategy=strategy)
    assert "F" in selected(output)
    assert output["status"] == "TARGET_MET"


@pytest.mark.parametrize("method", ["auto", "guided_v2", "greedy"])
def test_forced_and_kept_activities_survive_a_large_catalog_replan(method):
    candidates, scorer = catalog()
    planner_input = make_planner_input(
        candidates, **BASE,
        previous_plan=make_previous_plan({"K": [(at(2, 9), at(2, 10))]}),
        keep_requests=[*keep("K"), *force("F")],
    )
    output = run(planner_input, scorer, search_method=method)
    assert {"F", "K"} <= selected(output)
    blocks = {entry["activity_id"]: entry["scheduled_blocks"] for entry in output["selected_activities"]}
    assert [(block["start"], block["end"]) for block in blocks["K"]] == [(at(2, 9), at(2, 10))]
