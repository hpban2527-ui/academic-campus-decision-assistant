"""Dedicated tests for SP3 Inner Scheduler optimizations (Exact DP vs Fast v1 vs Fast v2)."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from schedule_optimization.scenarios import (
    BASE_DAY,
    build_tight_scheduler_instance,
    iso_at,
    make_flexible_schedule,
)
from sp3.contract import overlaps, timestamp, validate_intervals, validate_schedule
from sp3.scheduler import ScheduleStatus, schedule_set


def _assert_non_overlapping_and_valid(result, schedules):
    assert result.status is ScheduleStatus.SCHEDULED
    assert set(result.blocks.keys()) == set(schedules.keys())
    all_blocks = []
    for aid, blocks in result.blocks.items():
        assert len(blocks) == 1
        start, end = blocks[0]
        sched = schedules[aid]
        assert int((end - start).total_seconds() // 60) == sched.duration_minutes
        assert start >= sched.window_start and end <= sched.window_end
        all_blocks.append((start, end))
    all_blocks.sort()
    for left, right in zip(all_blocks, all_blocks[1:]):
        assert not overlaps(left, right)


def test_fast_v2_matches_exact_dp_on_tight_k14():
    schedules, available, options = build_tight_scheduler_instance(14, seed=7, tight=True)
    exact = schedule_set(schedules, available, max_flexible_per_set=16, fast_flexible=False, **options)
    fast_v2 = schedule_set(schedules, available, max_flexible_per_set=0, fast_flexible=True, fast_mode="v2", **options)
    assert exact.status is ScheduleStatus.SCHEDULED
    _assert_non_overlapping_and_valid(fast_v2, schedules)


def test_fast_v2_scales_to_64_flexible_activities():
    schedules, available, options = build_tight_scheduler_instance(64, seed=99, tight=False)
    res = schedule_set(schedules, available, max_flexible_per_set=16, fast_flexible=True, fast_mode="v2", **options)
    _assert_non_overlapping_and_valid(res, schedules)
    assert res.time_changes_minimal is False


def test_fast_v2_preserves_previous_blocks_on_replan_above_cap():
    """When k > 16, Fast v2 should hold non-overlapping previous blocks (0 time_changes),
    whereas Fast v1 drops all previous blocks and causes high churn."""
    schedules, available, options = build_tight_scheduler_instance(22, seed=11, tight=False)
    initial = schedule_set(schedules, available, max_flexible_per_set=16, fast_flexible=True, fast_mode="v2", **options)
    assert initial.status is ScheduleStatus.SCHEDULED

    # Add 2 new flexible activities and replan with previous_blocks from initial
    extra_schedules = dict(schedules)
    for idx in range(2):
        extra_schedules[f"NEW-{idx:02d}"] = validate_schedule(
            make_flexible_schedule(iso_at(35, 8), iso_at(42, 18), 60), f"new[{idx}]"
        )

    replan_v1 = schedule_set(
        extra_schedules,
        available,
        previous_blocks=initial.blocks,
        max_flexible_per_set=16,
        fast_flexible=True,
        fast_mode="v1",
        **options,
    )
    replan_v2 = schedule_set(
        extra_schedules,
        available,
        previous_blocks=initial.blocks,
        max_flexible_per_set=16,
        fast_flexible=True,
        fast_mode="v2",
        **options,
    )

    _assert_non_overlapping_and_valid(replan_v1, extra_schedules)
    _assert_non_overlapping_and_valid(replan_v2, extra_schedules)
    # Fast v2 holds all 22 previous blocks -> 0 time_changes!
    assert replan_v2.time_changes == 0
    assert replan_v2.time_changes <= replan_v1.time_changes
    assert replan_v2.time_changes_minimal is False


def test_fast_v2_available_edf_solves_ect_trap():
    """Adversarial instance where naive Earliest-Completion-Time traps a tight-deadline task."""
    day = BASE_DAY + timedelta(days=2, hours=8)
    avail = validate_intervals([{"start": day.isoformat(), "end": (day + timedelta(hours=4)).isoformat()}], "avail")
    # Task A: 60m, wide deadline (+4h) -> ECT picks A first (finishes +1h)
    # Task B: 90m, tight deadline (+1h30m) -> MUST run at +0h..+1h30m!
    # Plus 16 filler tasks later in the week to push k > 16.
    day3 = BASE_DAY + timedelta(days=3, hours=8)
    avail = validate_intervals(
        [
            {"start": day.isoformat(), "end": (day + timedelta(hours=3)).isoformat()},
            {"start": day3.isoformat(), "end": (day3 + timedelta(hours=20)).isoformat()},
        ],
        "avail",
    )
    schedules = {
        "TRAP-A": validate_schedule(
            make_flexible_schedule(day.isoformat(), (day + timedelta(hours=3)).isoformat(), 60), "A"
        ),
        "TRAP-B": validate_schedule(
            make_flexible_schedule(day.isoformat(), (day + timedelta(minutes=90)).isoformat(), 90), "B"
        ),
    }
    for i in range(16):
        schedules[f"FILL-{i:02d}"] = validate_schedule(
            make_flexible_schedule(day3.isoformat(), (day3 + timedelta(hours=20)).isoformat(), 60), f"F{i}"
        )
    options = {
        "window_start": timestamp(iso_at(1, 0), "ws"),
        "window_end": timestamp(iso_at(10, 0), "we"),
        "as_of": timestamp(iso_at(0, 8), "as_of"),
    }
    res = schedule_set(schedules, avail, max_flexible_per_set=16, fast_flexible=True, fast_mode="v2", **options)
    _assert_non_overlapping_and_valid(res, schedules)
    # TRAP-B must start immediately at day (08:00)
    assert res.blocks["TRAP-B"][0][0] == day


def test_fast_v2_soundness_never_claims_unschedulable_on_heuristic_failure():
    """If heuristic cannot place >16 flexible items when total duration fits, status must be UNDETERMINED, never UNSCHEDULABLE."""
    day = BASE_DAY + timedelta(days=2, hours=8)
    # 18 items of 60m each, all with identical 2-hour window (only 2 can actually fit, though total free across month >= 18h)
    avail = validate_intervals(
        [
            {"start": day.isoformat(), "end": (day + timedelta(hours=2)).isoformat()},
            {"start": iso_at(5, 8), "end": iso_at(10, 18)},
        ],
        "avail",
    )
    schedules = {
        f"IMP-{i:02d}": validate_schedule(
            make_flexible_schedule(day.isoformat(), (day + timedelta(hours=2)).isoformat(), 60), f"imp[{i}]"
        )
        for i in range(18)
    }
    options = {
        "window_start": timestamp(iso_at(1, 0), "ws"),
        "window_end": timestamp(iso_at(12, 0), "we"),
        "as_of": timestamp(iso_at(0, 8), "as_of"),
    }
    res = schedule_set(schedules, avail, max_flexible_per_set=16, fast_flexible=True, fast_mode="v2", **options)
    assert res.status is ScheduleStatus.UNDETERMINED
