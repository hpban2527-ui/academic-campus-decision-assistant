"""Regression tests for selected SP3 search optimizations."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import CappedAdditiveScorer, at, flexible_schedule, make_activity, make_candidate, make_planner_input
from sp3.contract import timestamp, validate_intervals, validate_schedule
from sp3.plan_checker import check_plan
from sp3.planner import build_plan
from sp3.scheduler import ScheduleStatus, schedule_set


def test_guided_search_respects_ngoc_contract():
    start = datetime.fromisoformat(at(1, 9))
    candidates = []
    scored = {}
    for index in range(70):
        begin = start + timedelta(hours=index)
        finish = begin + timedelta(minutes=30)
        activity_id = f"OPT-{index:03d}"
        activity = make_activity(activity_id, begin.isoformat(), finish.isoformat())
        candidates.append(make_candidate(activity))
        scored[activity_id] = ("C1", 5.0)

    planner_input = make_planner_input(
        candidates,
        scores={"C1": 0},
        caps={"C1": 30},
        category_targets={"C1": 10},
        total_target=10,
        max_activities=3,
    )
    scorer = CappedAdditiveScorer(scored)
    result = build_plan(planner_input, scorer, max_evaluations=100)
    assert result["status"] == "TARGET_MET"
    assert result["search"]["evaluated_subsets"] <= 100
    assert result["search"]["optimality_proven"] is False
    assert check_plan(planner_input, result, scorer) == []


def test_fast_flexible_never_uses_failed_heuristic_as_proof():
    start, end = at(2, 8), at(5, 20)
    available = validate_intervals([{"start": start, "end": end}], "available")
    schedules = {
        f"FLEX-{index:02d}": validate_schedule(
            flexible_schedule(start, end, 60), f"schedule[{index}]"
        )
        for index in range(18)
    }
    options = {
        "window_start": timestamp(start, "start"),
        "window_end": timestamp(end, "end"),
        "as_of": timestamp(at(1, 8), "as_of"),
    }
    baseline = schedule_set(schedules, available, **options)
    assert baseline.status is ScheduleStatus.UNDETERMINED
    optimized = schedule_set(schedules, available, fast_flexible=True, **options)
    assert optimized.status is ScheduleStatus.SCHEDULED
    assert len(optimized.blocks) == 18
    assert optimized.time_changes_minimal is False

