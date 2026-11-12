"""Unit tests for the whole-set scheduler (contract section 8)."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sp3.contract import Schedule, ScheduleType
from sp3.scheduler import MAX_FLEXIBLE_PER_SET, ScheduleStatus, schedule_set

WINDOW_START = datetime.fromisoformat("2026-11-01T00:00:00+07:00")
WINDOW_END = datetime.fromisoformat("2026-11-08T00:00:00+07:00")
AS_OF = datetime.fromisoformat("2026-11-01T08:00:00+07:00")


def t(hour, minute=0, day=2):
    return datetime.fromisoformat(f"2026-11-{day:02d}T{hour:02d}:{minute:02d}:00+07:00")


def fixed(*blocks):
    return Schedule(ScheduleType.FIXED, fixed_blocks=tuple(blocks))


def flexible(start, end, minutes):
    return Schedule(ScheduleType.FLEXIBLE_WINDOW, window_start=start, window_end=end, duration_minutes=minutes)


def run(activities, available, **kwargs):
    options = {"window_start": WINDOW_START, "window_end": WINDOW_END, "as_of": AS_OF, **kwargs}
    return schedule_set(activities, available, **options)


def assert_scheduled(result, expected):
    assert result.status is ScheduleStatus.SCHEDULED, result.reason
    assert dict(result.blocks) == expected


# Exact placement -------------------------------------------------------------------

def test_window_end_order_counterexample_is_scheduled():
    # Placing A first (earliest window end) leaves no 180-minute gap for B.
    activities = {"A": flexible(t(9), t(12), 120), "B": flexible(t(7), t(13), 180)}
    result = run(activities, [(t(7), t(13))], as_of=t(6))
    assert_scheduled(result, {"B": ((t(7), t(10)),), "A": ((t(10), t(12)),)})


def test_two_flexible_activities_competing_for_one_slot_are_unschedulable():
    activities = {"A": flexible(t(8), t(12), 60), "B": flexible(t(8), t(12), 60)}
    assert run({"A": activities["A"]}, [(t(9), t(10))]).status is ScheduleStatus.SCHEDULED
    result = run(activities, [(t(9), t(10))])
    assert result.status is ScheduleStatus.UNSCHEDULABLE
    assert result.blocks == {}


def test_flexible_is_placed_around_a_fixed_block():
    activities = {"F": fixed((t(10), t(11))), "X": flexible(t(9, 30), t(12), 60)}
    assert_scheduled(run(activities, [(t(9), t(12))]), {"F": ((t(10), t(11)),), "X": ((t(11), t(12)),)})


def test_multi_session_fixed_activity_blocks_every_session():
    sessions = ((t(9), t(10)), (t(9, day=3), t(10, day=3)))
    activities = {"M": fixed(*sessions), "X": flexible(t(9), t(12, day=3), 60)}
    available = [(t(9), t(10)), (t(9, day=3), t(11, day=3))]
    assert_scheduled(run(activities, available), {"M": sessions, "X": ((t(10, day=3), t(11, day=3)),)})


def test_one_session_outside_availability_is_unschedulable():
    activities = {"M": fixed((t(9), t(10)), (t(9, day=3), t(10, day=3)))}
    assert run(activities, [(t(8), t(11))]).status is ScheduleStatus.UNSCHEDULABLE


def test_exact_adjacency_is_not_an_overlap():
    activities = {"A": fixed((t(14), t(15))), "B": fixed((t(15), t(16))), "C": flexible(t(13), t(17), 60)}
    assert_scheduled(run(activities, [(t(14), t(17))]), {
        "A": ((t(14), t(15)),), "B": ((t(15), t(16)),), "C": ((t(16), t(17)),),
    })


def test_fixed_blocks_overlapping_by_one_minute_are_unschedulable():
    activities = {"A": fixed((t(14), t(15, 1))), "B": fixed((t(15), t(16)))}
    assert run(activities, [(t(14), t(17))]).status is ScheduleStatus.UNSCHEDULABLE


def test_window_is_clipped_by_as_of():
    activities = {"X": flexible(t(7), t(12), 60)}
    assert_scheduled(run(activities, [(t(7), t(12))], as_of=t(9, 15)), {"X": ((t(9, 15), t(10, 15)),)})
    assert run(activities, [(t(7), t(12))], as_of=t(11, 1)).status is ScheduleStatus.UNSCHEDULABLE


def test_window_is_clipped_by_the_planning_window():
    # The activity window opens at 06:00 and as_of is 06:00, but planning starts at 06:30.
    activities = {"X": flexible(t(6, day=1), t(12), 30)}
    result = run(activities, [(t(5, day=1), t(7, day=1))], window_start=t(6, 30, day=1), as_of=t(6, day=1))
    assert_scheduled(result, {"X": ((t(6, 30, day=1), t(7, day=1)),)})
    clipped_end = run({"X": flexible(t(9), t(13), 60)}, [(t(9), t(13))], window_end=t(9, 59))
    assert clipped_end.status is ScheduleStatus.UNSCHEDULABLE
    fits = run({"X": flexible(t(11), t(13), 60)}, [(t(9), t(13))], window_end=t(12))
    assert_scheduled(fits, {"X": ((t(11), t(12)),)})


def test_duration_equal_to_the_free_slot_fits_and_one_minute_short_does_not():
    activities = {"F": fixed((t(10), t(12))), "X": flexible(t(9), t(12), 60)}
    assert_scheduled(run(activities, [(t(9), t(12))]), {"F": ((t(10), t(12)),), "X": ((t(9), t(10)),)})
    assert run(activities, [(t(9, 1), t(12))]).status is ScheduleStatus.UNSCHEDULABLE


def test_free_fragments_are_not_combined():
    activities = {"X": flexible(t(8), t(12), 60)}
    assert run(activities, [(t(8), t(8, 30)), (t(10), t(10, 30))]).status is ScheduleStatus.UNSCHEDULABLE


def test_adjoining_available_intervals_are_merged():
    activities = {"X": flexible(t(8), t(12), 60)}
    assert_scheduled(run(activities, [(t(9, 30), t(10)), (t(9), t(9, 30))]), {"X": ((t(9), t(10)),)})


def test_ties_on_completion_time_place_the_smaller_id_last():
    activities = {"B": flexible(t(9), t(11), 60), "A": flexible(t(9), t(11), 60)}
    assert_scheduled(run(activities, [(t(9), t(11))]), {"B": ((t(9), t(10)),), "A": ((t(10), t(11)),)})


def test_empty_set_is_scheduled():
    assert_scheduled(run({}, []), {})


def test_computed_blocks_use_the_planning_window_offset():
    utc_window = (t(9).astimezone(timezone.utc), t(12).astimezone(timezone.utc))
    result = run({"X": flexible(*utc_window, 60)}, [(t(9).astimezone(timezone.utc), t(12))])
    assert [moment.isoformat() for moment in result.blocks["X"][0]] == ["2026-11-02T09:00:00+07:00", "2026-11-02T10:00:00+07:00"]


# Kept and retained blocks ------------------------------------------------------------

def test_kept_flexible_block_is_used_exactly():
    activities = {"X": flexible(t(8), t(12), 60), "Y": flexible(t(8), t(12), 60)}
    result = run(activities, [(t(8), t(12))], previous_blocks={"X": [(t(10), t(11))]}, keep={"X"})
    assert_scheduled(result, {"X": ((t(10), t(11)),), "Y": ((t(8), t(9)),)})
    assert result.time_changes == 0


@pytest.mark.parametrize("name,activities,previous", [
    ("outside_available", {"X": flexible(t(8), t(12), 60)}, {"X": [(t(11, 30), t(12, 30))]}),
    ("outside_window", {"X": flexible(t(9), t(12), 60)}, {"X": [(t(8), t(9))]}),
    ("wrong_duration", {"X": flexible(t(8), t(12), 60)}, {"X": [(t(9), t(10, 30))]}),
    ("two_blocks", {"X": flexible(t(8), t(12), 30)}, {"X": [(t(8), t(8, 30)), (t(9), t(9, 30))]}),
    ("fixed_changed", {"X": fixed((t(9), t(10)))}, {"X": [(t(10), t(11))]}),
])
def test_invalid_kept_blocks_are_unschedulable(name, activities, previous):
    result = run(activities, [(t(8), t(12))], previous_blocks=previous, keep={"X"})
    assert result.status is ScheduleStatus.UNSCHEDULABLE


def test_kept_block_overlapping_a_fixed_block_is_unschedulable():
    activities = {"X": flexible(t(8), t(12), 60), "F": fixed((t(9, 30), t(10, 30)))}
    result = run(activities, [(t(8), t(12))], previous_blocks={"X": [(t(9), t(10))]}, keep={"X"})
    assert result.status is ScheduleStatus.UNSCHEDULABLE


def test_keep_must_name_retained_activities_of_the_set():
    with pytest.raises(ValueError):
        run({"X": flexible(t(8), t(12), 60)}, [(t(8), t(12))], keep={"X"})
    with pytest.raises(ValueError):
        run({"X": flexible(t(8), t(12), 60)}, [(t(8), t(12))], previous_blocks={"Y": [(t(8), t(9))]}, keep={"Y"})


def test_retained_flexible_activity_stays_at_its_valid_previous_block():
    activities = {"X": flexible(t(8), t(12), 60)}
    result = run(activities, [(t(8), t(12))], previous_blocks={"X": [(t(10), t(11))]})
    assert_scheduled(result, {"X": ((t(10), t(11)),)})
    assert (result.time_changes, result.time_changes_minimal) == (0, True)


def test_retained_flexible_activity_moves_when_its_previous_block_is_no_longer_free():
    activities = {"X": flexible(t(8), t(12), 60)}
    result = run(activities, [(t(8), t(9, 30)), (t(10, 30), t(12))], previous_blocks={"X": [(t(10), t(11))]})
    assert_scheduled(result, {"X": ((t(8), t(9)),)})
    assert result.time_changes == 1


def test_changed_fixed_sessions_count_as_a_forced_time_change():
    activities = {"F": fixed((t(10), t(11)))}
    result = run(activities, [(t(8), t(12))], previous_blocks={"F": [(t(9), t(10))]})
    assert_scheduled(result, {"F": ((t(10), t(11)),)})
    assert result.time_changes == 1


def test_minimal_time_changes_choose_which_activity_moves():
    # Four one-hour sittings fill 08:00-12:00 and N must use 09:00-10:00 or 10:00-11:00,
    # so X (09:00) and Y (10:00) cannot both stay; one move is the minimum.
    activities = {
        "N": flexible(t(9), t(11), 60),
        "X": flexible(t(8), t(12), 60),
        "Y": flexible(t(8), t(12), 60),
        "Z": flexible(t(8), t(12), 60),
    }
    previous = {"X": [(t(9), t(10))], "Y": [(t(10), t(11))], "Z": [(t(8), t(9))]}
    result = run(activities, [(t(8), t(12))], previous_blocks=previous)
    assert result.status is ScheduleStatus.SCHEDULED
    assert result.time_changes == 1
    # Largest held subsets of size 2 are tried in ID order: {X, Y} fails, {X, Z} succeeds.
    assert result.blocks["X"] == ((t(9), t(10)),) and result.blocks["Z"] == ((t(8), t(9)),)
    assert result.blocks["N"] == ((t(10), t(11)),) and result.blocks["Y"] == ((t(11), t(12)),)


def test_replan_within_the_work_bound_is_exact():
    activities = {"N": flexible(t(9), t(11), 60), "X": flexible(t(8), t(12), 60), "Y": flexible(t(8), t(12), 60)}
    previous = {"X": [(t(9), t(10))], "Y": [(t(10), t(11))]}
    # Budget 3 * 2**3 = 24 units: holding {X, Y} costs 1 * 2 and fails (N has no slot);
    # holding {X} costs 2 * 4 and succeeds with N 10:00 and Y moved to 08:00.
    result = run(activities, [(t(8), t(12))], previous_blocks=previous, max_flexible_per_set=3)
    assert_scheduled(result, {"X": ((t(9), t(10)),), "N": ((t(10), t(11)),), "Y": ((t(8), t(9)),)})
    assert (result.time_changes, result.time_changes_minimal) == (1, True)
    assert run(activities, [(t(8), t(12))], previous_blocks=previous) == result
    assert run(activities, [(t(8), t(12))], previous_blocks=previous, max_flexible_per_set=2).status is ScheduleStatus.UNDETERMINED


def tight_packing():
    # Four one-hour sittings exactly fill 09:00-13:00, so every block starts on the hour.
    # P1-P3 were previously at half past: holding any of them leaves no room for the rest.
    activities = {name: flexible(t(9), t(13), 60) for name in ("N", "P1", "P2", "P3")}
    previous = {"P1": [(t(9, 30), t(10, 30))], "P2": [(t(10, 30), t(11, 30))], "P3": [(t(11, 30), t(12, 30))]}
    return activities, previous


def test_replan_without_any_keepable_subset_moves_everything():
    activities, previous = tight_packing()
    result = run(activities, [(t(9), t(13))], previous_blocks=previous)
    assert (result.status, result.time_changes, result.time_changes_minimal) == (ScheduleStatus.SCHEDULED, 3, True)
    assert_valid(result, activities, [(t(9), t(13))])


def test_replan_bound_reached_returns_the_base_schedule_without_claiming_minimality():
    activities, previous = tight_packing()
    # Budget 4 * 2**4 = 64 units. Held groups, all failing: {P1,P2,P3} costs 2, three pairs cost 8 each,
    # {P1} costs 24 (total 50); {P2} would cost 24 more, so the enumeration stops.
    result = run(activities, [(t(9), t(13))], previous_blocks=previous, max_flexible_per_set=4)
    assert result.status is ScheduleStatus.SCHEDULED
    assert (result.time_changes, result.time_changes_minimal) == (3, False)
    assert dict(result.blocks) == dict(run(activities, [(t(9), t(13))], previous_blocks=previous).blocks)
    assert_valid(result, activities, [(t(9), t(13))])


def assert_valid(result, activities, available):
    blocks = sorted(block for value in result.blocks.values() for block in value)
    assert all(left[1] <= right[0] for left, right in zip(blocks, blocks[1:]))
    for activity_id, schedule in activities.items():
        if schedule.type is ScheduleType.FIXED:
            assert result.blocks[activity_id] == schedule.fixed_blocks
        else:
            ((start, end),) = result.blocks[activity_id]
            assert end - start == timedelta(minutes=schedule.duration_minutes)
            assert schedule.window_start <= start and end <= schedule.window_end
            assert any(s <= start and end <= e for s, e in available)


# Limits and determinism ----------------------------------------------------------------

def test_cap_reached_is_undetermined_never_unschedulable():
    activities = {name: flexible(t(9), t(10), 60) for name in "ABC"}  # truly impossible together
    assert run(activities, [(t(9), t(10))]).status is ScheduleStatus.UNSCHEDULABLE
    capped = run(activities, [(t(9), t(10))], max_flexible_per_set=2)
    assert capped.status is ScheduleStatus.UNDETERMINED
    assert capped.blocks == {}


def test_individual_impossibility_is_still_proven_above_the_cap():
    activities = {"A": flexible(t(9), t(10), 60), "B": flexible(t(9), t(10), 60), "C": flexible(t(13), t(14), 60)}
    assert run(activities, [(t(9), t(10))], max_flexible_per_set=1).status is ScheduleStatus.UNSCHEDULABLE


def test_default_cap_is_sixteen():
    assert MAX_FLEXIBLE_PER_SET == 16
    activities = {f"A{index:02d}": flexible(t(7), t(17), 30) for index in range(17)}
    assert run(activities, [(t(7), t(17))]).status is ScheduleStatus.UNDETERMINED


@pytest.mark.parametrize("value", [-1, 1.5, True, None])
def test_invalid_cap_is_rejected(value):
    with pytest.raises(ValueError):
        run({}, [], max_flexible_per_set=value)


def test_shuffled_inputs_give_identical_results():
    activities = {
        "A": flexible(t(9), t(12), 60), "B": flexible(t(9), t(12), 60), "C": fixed((t(10), t(11))),
        "D": flexible(t(8), t(16), 90), "E": flexible(t(13), t(16), 30),
    }
    available = [(t(8), t(9, 30)), (t(9, 30), t(12)), (t(13), t(16))]
    previous = {"D": [(t(13), t(14, 30))], "B": [(t(9), t(10))]}
    reference = run(activities, available, previous_blocks=previous)
    assert reference.status is ScheduleStatus.SCHEDULED
    rng = random.Random(20261102)
    for _ in range(20):
        items = list(activities.items())
        rng.shuffle(items)
        intervals = list(available)
        rng.shuffle(intervals)
        shuffled_previous = dict(rng.sample(list(previous.items()), len(previous)))
        assert run(dict(items), intervals, previous_blocks=shuffled_previous) == reference


def test_inputs_are_not_mutated():
    activities = {"A": flexible(t(9), t(12), 60), "F": fixed((t(10), t(11)))}
    available = [(t(9), t(12))]
    previous = {"A": [(t(11), t(12))]}
    snapshot = deepcopy((activities, available, previous))
    run(activities, available, previous_blocks=previous, keep={"A"})
    assert (activities, available, previous) == snapshot
