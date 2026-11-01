from __future__ import annotations

from copy import deepcopy

import pytest

from sp3 import (
    AvailabilityContractError,
    FeasibilityEvidence,
    assess_feasibility,
    resolve_availability,
)


WINDOW_START = "2026-11-01T00:00:00+07:00"
WINDOW_END = "2026-11-17T00:00:00+07:00"


def availability(**changes):
    value = {
        "availability_version": "sp3-availability/0.1",
        "timezone": "Asia/Ho_Chi_Minh",
        "week_start": "2026-11-02",
        "apply_scope": "WEEK_ONLY",
        "weekly_blocks": [
            {
                "day_of_week": "MONDAY",
                "start_time": "08:00",
                "end_time": "11:30",
            }
        ],
        "effective_from": None,
        "effective_until": None,
        "exceptions": [],
    }
    value.update(changes)
    return value


def resolve(payload, *, start=WINDOW_START, end=WINDOW_END):
    return resolve_availability(payload, window_start=start, window_end=end)


def test_week_only_expands_the_selected_week_once():
    result = resolve(availability())

    assert result["apply_scope"] == "WEEK_ONLY"
    assert result["effective_from"] == "2026-11-02"
    assert result["effective_until"] == "2026-11-08"
    assert result["available_intervals"] == [
        {
            "start": "2026-11-02T08:00:00+07:00",
            "end": "2026-11-02T11:30:00+07:00",
        }
    ]


def test_semester_weekly_repeats_only_inside_the_planning_window():
    payload = availability(
        apply_scope="SEMESTER_WEEKLY",
        effective_from="2026-10-19",
        effective_until="2026-12-20",
    )

    result = resolve(payload)

    assert result["available_intervals"] == [
        {
            "start": "2026-11-02T08:00:00+07:00",
            "end": "2026-11-02T11:30:00+07:00",
        },
        {
            "start": "2026-11-09T08:00:00+07:00",
            "end": "2026-11-09T11:30:00+07:00",
        },
        {
            "start": "2026-11-16T08:00:00+07:00",
            "end": "2026-11-16T11:30:00+07:00",
        },
    ]


def test_empty_exception_makes_one_repeated_day_unavailable():
    payload = availability(
        apply_scope="SEMESTER_WEEKLY",
        effective_from="2026-11-01",
        effective_until="2026-11-30",
        exceptions=[{"date": "2026-11-09", "blocks": []}],
    )

    result = resolve(payload)

    assert [item["start"] for item in result["available_intervals"]] == [
        "2026-11-02T08:00:00+07:00",
        "2026-11-16T08:00:00+07:00",
    ]


def test_exception_replaces_instead_of_appending_to_the_template():
    payload = availability(
        apply_scope="SEMESTER_WEEKLY",
        effective_from="2026-11-01",
        effective_until="2026-11-30",
        exceptions=[
            {
                "date": "2026-11-09",
                "blocks": [{"start_time": "18:00", "end_time": "21:00"}],
            }
        ],
    )

    result = resolve(payload)
    ninth = [
        item
        for item in result["available_intervals"]
        if item["start"].startswith("2026-11-09")
    ]
    assert ninth == [
        {
            "start": "2026-11-09T18:00:00+07:00",
            "end": "2026-11-09T21:00:00+07:00",
        }
    ]


def test_overlapping_and_adjoining_ui_blocks_are_merged():
    payload = availability(
        weekly_blocks=[
            {"day_of_week": "MONDAY", "start_time": "08:00", "end_time": "10:00"},
            {"day_of_week": "MONDAY", "start_time": "09:30", "end_time": "10:30"},
            {"day_of_week": "MONDAY", "start_time": "10:30", "end_time": "11:00"},
        ]
    )

    assert resolve(payload)["available_intervals"] == [
        {
            "start": "2026-11-02T08:00:00+07:00",
            "end": "2026-11-02T11:00:00+07:00",
        }
    ]


def test_resolver_clips_intervals_to_the_planning_window():
    result = resolve(
        availability(),
        start="2026-11-02T09:00:00+07:00",
        end="2026-11-02T10:00:00+07:00",
    )
    assert result["available_intervals"] == [
        {
            "start": "2026-11-02T09:00:00+07:00",
            "end": "2026-11-02T10:00:00+07:00",
        }
    ]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"week_start": "2026-11-03"}, "must be a Monday"),
        (
            {
                "apply_scope": "SEMESTER_WEEKLY",
                "effective_from": None,
                "effective_until": None,
            },
            "are required",
        ),
        (
            {"effective_from": "2026-11-01", "effective_until": "2026-11-30"},
            "must be null",
        ),
        (
            {
                "weekly_blocks": [
                    {
                        "day_of_week": "MONDAY",
                        "start_time": "22:00",
                        "end_time": "06:00",
                    }
                ]
            },
            "overnight blocks are unsupported",
        ),
        (
            {
                "exceptions": [
                    {"date": "2026-11-09", "blocks": []}
                ]
            },
            "inside the selected apply scope",
        ),
    ],
)
def test_invalid_or_ambiguous_recurrence_inputs_are_rejected(changes, message):
    with pytest.raises(AvailabilityContractError, match=message):
        resolve(availability(**changes))


def test_calendar_version_is_deterministic_and_input_is_not_mutated():
    payload = availability()
    original = deepcopy(payload)

    first = resolve(payload)
    second = resolve(payload)

    assert first["calendar_version"] == second["calendar_version"]
    assert first["calendar_version"].startswith("availability-")
    assert payload == original


def test_resolved_intervals_feed_the_existing_feasibility_contract():
    resolved = resolve(availability())
    activity = {
        "activity_id": "ACT-MONDAY",
        "source": {
            "publisher": "Synthetic fixture",
            "platform": "fixture",
            "URL_post": "https://example.invalid/ACT-MONDAY",
            "URL_registration": None,
        },
        "title": "Monday fixture",
        "domain": "academic",
        "start": "2026-11-02T09:00:00+07:00",
        "end": "2026-11-02T10:00:00+07:00",
        "registration_deadline": "2026-11-01T18:00:00+07:00",
        "mode": "online",
        "location": None,
        "points": 5,
        "mandatory": False,
        "audience": ["Synthetic students"],
        "fee": 0,
        "completion_requirements": "Attend the fixture.",
    }
    request = {
        "contract_version": "sp3-planner/0.1",
        "request_id": "availability-integration",
        "context": {
            "student_id": "synthetic-student",
            "term_id": "SYNTHETIC-DEMO",
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "as_of": "2026-11-01T08:00:00+07:00",
            "timezone": "Asia/Ho_Chi_Minh",
            "baseline_ref": "mock-baseline",
            "dataset_version": "mock-data",
            "ruleset_version": "mock-rules",
            "calendar_version": resolved["calendar_version"],
        },
        "available_intervals": resolved["available_intervals"],
        "activities": [{"activity": activity, "score_binding_ref": "binding-A"}],
    }

    result = assess_feasibility(
        request,
        evidence=FeasibilityEvidence(
            term_verified=True,
            eligibility_by_activity={"ACT-MONDAY": "ELIGIBLE"},
        ),
    )

    assert result["candidates"][0]["feasibility"] == {
        "status": "FEASIBLE",
        "reason_codes": [],
    }
