"""Planner-side contract primitives for sp3-planner/0.2 (sections 4, 7 and 10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sp3.contract import (
    CONTRACT_VERSION,
    ContractError,
    ExclusionCode,
    LimitReason,
    PlannerStatus,
    ScheduleType,
    WarningCode,
    attribution_order,
    feasible_alone,
    merge_intervals,
    overlaps,
    plan_version,
    same_instants,
    usable_window,
    valid_flexible_blocks,
    validate_blocks,
    validate_keep_requests,
    validate_participation,
    validate_previous_plan,
    validate_schedule,
)


def at(day, hour, minute=0):
    return f"2026-11-{day:02d}T{hour:02d}:{minute:02d}:00+07:00"


def dt(day, hour, minute=0):
    return datetime.fromisoformat(at(day, hour, minute))


def block(start, end):
    return {"start": start, "end": end}


def flexible(start, end, minutes):
    return {"type": "FLEXIBLE_WINDOW", "window_start": start, "window_end": end, "duration_minutes": minutes}


PLAN_VERSION = "sp3plan-0123456789abcdef"
BASED_ON = {
    "calendar_version": "cal", "dataset_version": "data", "ruleset_version": "rules",
    "baseline_ref": "base", "previous_plan_version": None,
}


def previous_plan(*activities):
    return {
        "plan_version": PLAN_VERSION,
        "based_on": dict(BASED_ON),
        "selected_activities": [
            {"activity_id": activity_id, "scheduled_blocks": [block(s, e) for s, e in blocks]}
            for activity_id, blocks in activities
        ],
    }


def test_contract_version_is_v0_2():
    assert CONTRACT_VERSION == "sp3-planner/0.2"


def test_new_codes_keep_contract_order():
    assert [code.value for code in ExclusionCode] == [
        "NEEDS_REVIEW", "NOT_FEASIBLE", "ALREADY_COUNTED", "CONFLICT", "NO_TIME", "LIMIT", "LOWER_PRIORITY",
    ]
    assert PlannerStatus.KEEP_CONFLICT.value == "KEEP_CONFLICT"
    assert LimitReason.KEEP_CONFLICT.value == "KEEP_CONFLICT"
    assert {"DROPS_REGISTERED", "PENDING_CONFIRMATION"} <= {code.value for code in WarningCode}


# Schedules --------------------------------------------------------------------

def test_fixed_schedule_with_several_sessions():
    schedule = validate_schedule({"type": "FIXED", "fixed_blocks": [block(at(2, 9), at(2, 10)), block(at(3, 9), at(3, 10))]}, "s")
    assert schedule.type is ScheduleType.FIXED
    assert schedule.fixed_blocks == ((dt(2, 9), dt(2, 10)), (dt(3, 9), dt(3, 10)))
    assert schedule.planned_minutes == 120


def test_adjacent_fixed_sessions_are_allowed():
    validate_schedule({"type": "FIXED", "fixed_blocks": [block(at(2, 9), at(2, 10)), block(at(2, 10), at(2, 11))]}, "s")


def test_flexible_schedule_duration_may_equal_the_window():
    schedule = validate_schedule(flexible(at(2, 9), at(2, 10), 60), "s")
    assert (schedule.window_start, schedule.window_end, schedule.duration_minutes) == (dt(2, 9), dt(2, 10), 60)
    assert schedule.planned_minutes == 60


INVALID_SCHEDULES = {
    "unknown_type": {"type": "ASYNCHRONOUS", "duration_minutes": 30},
    "missing_type": {"fixed_blocks": [block(at(2, 9), at(2, 10))]},
    "not_an_object": [],
    "fixed_empty": {"type": "FIXED", "fixed_blocks": []},
    "fixed_unsorted": {"type": "FIXED", "fixed_blocks": [block(at(3, 9), at(3, 10)), block(at(2, 9), at(2, 10))]},
    "fixed_overlapping": {"type": "FIXED", "fixed_blocks": [block(at(2, 9), at(2, 11)), block(at(2, 10), at(2, 12))]},
    "fixed_reversed_block": {"type": "FIXED", "fixed_blocks": [block(at(2, 10), at(2, 9))]},
    "fixed_empty_block": {"type": "FIXED", "fixed_blocks": [block(at(2, 9), at(2, 9))]},
    "fixed_extra_field": {"type": "FIXED", "fixed_blocks": [block(at(2, 9), at(2, 10))], "duration_minutes": 60},
    "fixed_block_without_offset": {"type": "FIXED", "fixed_blocks": [block("2026-11-02T09:00:00", at(2, 10))]},
    "flexible_reversed_window": flexible(at(2, 10), at(2, 9), 30),
    "flexible_zero_duration": flexible(at(2, 9), at(2, 10), 0),
    "flexible_float_duration": flexible(at(2, 9), at(2, 10), 30.0),
    "flexible_boolean_duration": flexible(at(2, 9), at(2, 10), True),
    "flexible_too_long": flexible(at(2, 9), at(2, 10), 61),
    "flexible_missing_window": {"type": "FLEXIBLE_WINDOW", "duration_minutes": 30},
}


@pytest.mark.parametrize("value", INVALID_SCHEDULES.values(), ids=INVALID_SCHEDULES.keys())
def test_invalid_schedules_are_rejected(value):
    with pytest.raises(ContractError):
        validate_schedule(value, "schedule")


def test_blocks_must_be_non_empty_sorted_and_non_overlapping():
    assert validate_blocks([block(at(2, 9), at(2, 10))], "b") == ((dt(2, 9), dt(2, 10)),)
    for value in ([], None, [block(at(2, 9), at(2, 11)), block(at(2, 10), at(2, 12))]):
        with pytest.raises(ContractError):
            validate_blocks(value, "b")


@pytest.mark.parametrize("value", [
    {"registration": "REGISTERED", "progress": "IN_PROGRESS"},
    {"registration": "PENDING", "progress": "NOT_STARTED"},
    {"registration": "REGISTERED"},
    {"registration": "REGISTERED", "progress": "NOT_STARTED", "keep": True},
])
def test_invalid_participation_is_rejected(value):
    with pytest.raises(ContractError):
        validate_participation(value, "p")


# Interval helpers ----------------------------------------------------------------

def test_half_open_intervals_and_merging():
    assert not overlaps((dt(2, 9), dt(2, 15)), (dt(2, 15), dt(2, 16)))
    assert overlaps((dt(2, 9), dt(2, 15, 1)), (dt(2, 15), dt(2, 16)))
    merged = merge_intervals([(dt(2, 12), dt(2, 13)), (dt(2, 9), dt(2, 10)), (dt(2, 10), dt(2, 11)), (dt(2, 10, 30), dt(2, 10, 45))])
    assert merged == ((dt(2, 9), dt(2, 11)), (dt(2, 12), dt(2, 13)))


def test_same_instants_compares_instants_not_offsets():
    utc = (dt(2, 9).astimezone(timezone.utc), dt(2, 10).astimezone(timezone.utc))
    assert same_instants([utc], [(dt(2, 9), dt(2, 10))])
    assert not same_instants([utc], [(dt(2, 9), dt(2, 11))])


def test_usable_window_is_clipped_by_planning_window_and_as_of():
    schedule = validate_schedule(flexible(at(1, 6), at(9, 0), 30), "s")
    assert usable_window(schedule, dt(1, 0), dt(8, 0), dt(1, 8)) == (dt(1, 8), dt(8, 0))
    ended = validate_schedule(flexible(at(1, 6), at(1, 7), 30), "s")
    assert usable_window(ended, dt(1, 0), dt(8, 0), dt(1, 8)) is None


def test_feasible_alone_requires_one_contiguous_slot():
    schedule = validate_schedule(flexible(at(2, 8), at(2, 12), 60), "s")
    fragments = [(dt(2, 8), dt(2, 8, 30)), (dt(2, 10), dt(2, 10, 30))]
    assert not feasible_alone(schedule, fragments, dt(1, 0), dt(8, 0), dt(1, 8))
    assert feasible_alone(schedule, [(dt(2, 11), dt(2, 13))], dt(1, 0), dt(8, 0), dt(1, 8))
    fixed = validate_schedule({"type": "FIXED", "fixed_blocks": [block(at(2, 9), at(2, 10)), block(at(3, 9), at(3, 10))]}, "s")
    assert not feasible_alone(fixed, [(dt(2, 8), dt(2, 11))], dt(1, 0), dt(8, 0), dt(1, 8))
    assert feasible_alone(fixed, [(dt(2, 8), dt(2, 11)), (dt(3, 9), dt(3, 10))], dt(1, 0), dt(8, 0), dt(1, 8))


def test_valid_flexible_blocks_checks_duration_window_and_availability():
    schedule = validate_schedule(flexible(at(2, 8), at(2, 12), 60), "s")
    available = [(dt(2, 8), dt(2, 12))]
    window = (dt(1, 0), dt(8, 0), dt(1, 8))
    assert valid_flexible_blocks(schedule, [(dt(2, 9), dt(2, 10))], available, *window)
    assert not valid_flexible_blocks(schedule, [(dt(2, 9), dt(2, 10, 30))], available, *window)
    assert not valid_flexible_blocks(schedule, [(dt(2, 11, 30), dt(2, 12, 30))], available, *window)
    assert not valid_flexible_blocks(schedule, [(dt(2, 9), dt(2, 10))], [(dt(2, 9, 30), dt(2, 12))], *window)
    assert not valid_flexible_blocks(schedule, [(dt(2, 8), dt(2, 8, 30)), (dt(2, 9), dt(2, 9, 30))], available, *window)


# Previous plan and keep requests ---------------------------------------------------

def test_previous_plan_and_keep_requests():
    plan = validate_previous_plan(previous_plan(("A", [(at(2, 9), at(2, 10))]), ("B", [(at(3, 9), at(3, 10))])), "p")
    assert plan.plan_version == PLAN_VERSION
    assert plan.blocks["A"] == ((dt(2, 9), dt(2, 10)),)
    assert validate_keep_requests([{"activity_id": "B", "mode": "KEEP_TIME"}], plan, "k") == frozenset({"B"})
    assert validate_previous_plan(None, "p") is None
    assert validate_keep_requests([], None, "k") == frozenset()


@pytest.mark.parametrize("corrupt", [
    lambda p: p.update(plan_version="v1"),
    lambda p: p.update(plan_version="sp3plan-0123456789ABCDEF"),
    lambda p: p["based_on"].pop("baseline_ref"),
    lambda p: p["based_on"].update(previous_plan_version="old"),
    lambda p: p["selected_activities"].append(dict(p["selected_activities"][0])),
    lambda p: p["selected_activities"][0].update(scheduled_blocks=[]),
    lambda p: p["selected_activities"][0].update(start=at(2, 9)),
    lambda p: p.update(selected_activities=None),
])
def test_invalid_previous_plans_are_rejected(corrupt):
    plan = previous_plan(("A", [(at(2, 9), at(2, 10))]))
    corrupt(plan)
    with pytest.raises(ContractError):
        validate_previous_plan(plan, "p")


@pytest.mark.parametrize("requests,with_plan", [
    ([{"activity_id": "A", "mode": "KEEP_ACTIVITY"}], True),
    ([{"activity_id": "A", "mode": "KEEP_TIME"}, {"activity_id": "A", "mode": "KEEP_TIME"}], True),
    ([{"activity_id": "Z", "mode": "KEEP_TIME"}], True),
    ([{"activity_id": "A", "mode": "KEEP_TIME"}], False),
    ([{"activity_id": "A"}], True),
    ({"A": "KEEP_TIME"}, True),
])
def test_invalid_keep_requests_are_rejected(requests, with_plan):
    plan = validate_previous_plan(previous_plan(("A", [(at(2, 9), at(2, 10))])), "p") if with_plan else None
    with pytest.raises(ContractError):
        validate_keep_requests(requests, plan, "k")


def test_contract_errors_do_not_echo_payload_values():
    with pytest.raises(ContractError) as raised:
        validate_participation({"registration": "secret-value", "progress": "NOT_STARTED"}, "p")
    assert "secret-value" not in str(raised.value)


# Attribution order and plan_version ------------------------------------------------

def test_attribution_order_uses_first_block_start_then_id():
    assert attribution_order({"B": dt(2, 9), "A": dt(2, 9), "C": dt(1, 23)}) == ["C", "A", "B"]
    assert attribution_order({"X": dt(2, 9).astimezone(timezone.utc), "W": dt(2, 9) + timedelta(seconds=1)}) == ["X", "W"]


def test_plan_version_is_the_documented_hash():
    blocks = {"B": [block(at(3, 9), at(3, 10))], "A": [block(at(2, 14), at(2, 15)), block(at(2, 9), at(2, 10))]}
    version = plan_version(BASED_ON, blocks.items())
    payload = {
        "based_on": BASED_ON,
        "selected_activities": [
            {"activity_id": "A", "scheduled_blocks": [block(at(2, 9), at(2, 10)), block(at(2, 14), at(2, 15))]},
            {"activity_id": "B", "scheduled_blocks": [block(at(3, 9), at(3, 10))]},
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert version == "sp3plan-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    assert plan_version({**BASED_ON, "calendar_version": "cal-2"}, blocks.items()) != version
    assert plan_version(BASED_ON, {"A": blocks["A"]}.items()) != version
