from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sp3 import (
    CONTRACT_VERSION,
    FeasibilityContractError,
    FeasibilityEvidence,
    TermScopeStatus,
    assess_feasibility,
)


WINDOW_START = "2026-11-01T00:00:00+07:00"
WINDOW_END = "2026-11-06T00:00:00+07:00"
AS_OF = "2026-11-01T08:00:00+07:00"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v0_2_feasibility_cases.json"


def activity(activity_id: str = "A", **changes):
    value = {
        "activity_id": activity_id,
        "source": {
            "publisher": "Synthetic fixture",
            "platform": "fixture",
            "URL_post": f"https://example.invalid/{activity_id}",
            "URL_registration": None,
        },
        "title": f"Activity {activity_id}",
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
        "completion_requirements": "Attend the fixture session.",
    }
    value.update(changes)
    return value


def participation(registration="NOT_REGISTERED", progress="NOT_STARTED"):
    return {"registration": registration, "progress": progress}


def request(*activities, intervals=None, participation_by_id=None):
    if not activities:
        activities = (activity(),)
    participation_by_id = participation_by_id or {}
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": "feasibility-test",
        "context": {
            "student_id": "synthetic-student",
            "term_id": "SYNTHETIC-DEMO",
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "as_of": AS_OF,
            "timezone": "Asia/Ho_Chi_Minh",
            "baseline_ref": "mock-baseline-01",
            "dataset_version": "mock-data-01",
            "ruleset_version": "mock-rules-01",
            "calendar_version": "mock-calendar-01",
        },
        "available_intervals": intervals
        if intervals is not None
        else [{"start": WINDOW_START, "end": WINDOW_END}],
        "activities": [
            {
                "activity": item,
                "score_binding_ref": f"binding-{item['activity_id']}",
                "participation": participation_by_id.get(
                    item["activity_id"], participation()
                ),
            }
            for item in activities
        ],
    }


def fixed_schedule(*blocks):
    return {
        "type": "FIXED",
        "fixed_blocks": [
            {"start": start, "end": end} for start, end in blocks
        ],
    }


def activity_fixed_schedule(item):
    return fixed_schedule((item["start"], item["end"]))


def flexible_schedule(duration_minutes):
    return {
        "type": "FLEXIBLE_WINDOW",
        "duration_minutes": duration_minutes,
    }


def evidence(
    *activities,
    term_verified=True,
    eligibility_by_activity=None,
    source_review_by_activity=None,
    schedule_by_activity=None,
):
    ids = [item["activity_id"] for item in activities]
    if eligibility_by_activity is None:
        eligibility_by_activity = {item: "ELIGIBLE" for item in ids}
    if source_review_by_activity is None:
        source_review_by_activity = {item: True for item in ids}
    if schedule_by_activity is None:
        schedule_by_activity = {
            item["activity_id"]: activity_fixed_schedule(item)
            for item in activities
        }
    return FeasibilityEvidence(
        term_verified=term_verified,
        eligibility_by_activity=eligibility_by_activity,
        source_review_by_activity=source_review_by_activity,
        schedule_by_activity=schedule_by_activity,
    )


def assessment(payload, trusted=None, index=0):
    return assess_feasibility(payload, evidence=trusted)["candidates"][index][
        "feasibility"
    ]


def test_contract_version_is_v0_2():
    assert CONTRACT_VERSION == "sp3-planner/0.2"


def test_shared_acceptance_fixture_contains_f1_through_f6():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["contract_version"] == CONTRACT_VERSION
    assert [case["id"] for case in fixture["cases"]] == [
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
    ]


def test_complete_activity_returns_normalized_schedule_and_participation():
    item = activity("A")
    payload = request(item)
    result = assess_feasibility(payload, evidence=evidence(item))
    assert result == {
        "contract_version": CONTRACT_VERSION,
        "request_id": "feasibility-test",
        "context": payload["context"],
        "candidates": [
            {
                **payload["activities"][0],
                "schedule": activity_fixed_schedule(item),
                "feasibility": {"status": "FEASIBLE", "reason_codes": []},
            }
        ],
        "conflict_pairs": [],
    }


def test_fixed_evidence_supports_multiple_required_sessions():
    item = activity("A", start=None, end=None)
    payload = request(item)
    schedule = fixed_schedule(
        ("2026-11-02T09:00:00+07:00", "2026-11-02T10:00:00+07:00"),
        ("2026-11-03T09:00:00+07:00", "2026-11-03T10:00:00+07:00"),
    )
    result = assess_feasibility(
        payload,
        evidence=evidence(item, schedule_by_activity={"A": schedule}),
    )
    assert result["candidates"][0]["schedule"] == schedule
    assert result["candidates"][0]["feasibility"]["status"] == "FEASIBLE"


def test_fixed_session_outside_availability_is_infeasible():
    item = activity("A", start=None, end=None)
    payload = request(
        item,
        intervals=[
            {
                "start": "2026-11-02T08:00:00+07:00",
                "end": "2026-11-02T11:00:00+07:00",
            }
        ],
    )
    schedule = fixed_schedule(
        ("2026-11-02T09:00:00+07:00", "2026-11-02T10:00:00+07:00"),
        ("2026-11-03T09:00:00+07:00", "2026-11-03T10:00:00+07:00"),
    )
    assert assessment(
        payload,
        evidence(item, schedule_by_activity={"A": schedule}),
    ) == {
        "status": "INFEASIBLE",
        "reason_codes": ["OUTSIDE_AVAILABILITY"],
    }


def test_flexible_requires_one_contiguous_free_interval():
    item = activity(
        "A",
        start="2026-11-02T08:00:00+07:00",
        end="2026-11-02T12:00:00+07:00",
    )
    payload = request(
        item,
        intervals=[
            {
                "start": "2026-11-02T08:00:00+07:00",
                "end": "2026-11-02T08:30:00+07:00",
            },
            {
                "start": "2026-11-02T10:00:00+07:00",
                "end": "2026-11-02T10:30:00+07:00",
            },
        ],
    )
    assert assessment(
        payload,
        evidence(item, schedule_by_activity={"A": flexible_schedule(60)}),
    ) == {
        "status": "INFEASIBLE",
        "reason_codes": ["OUTSIDE_AVAILABILITY"],
    }


def test_flexible_exact_contiguous_duration_is_feasible():
    item = activity(
        "A",
        start="2026-11-02T08:00:00+07:00",
        end="2026-11-02T12:00:00+07:00",
    )
    payload = request(
        item,
        intervals=[
            {
                "start": "2026-11-02T09:00:00+07:00",
                "end": "2026-11-02T10:00:00+07:00",
            }
        ],
    )
    result = assess_feasibility(
        payload,
        evidence=evidence(item, schedule_by_activity={"A": flexible_schedule(60)}),
    )
    assert result["candidates"][0]["feasibility"] == {
        "status": "FEASIBLE",
        "reason_codes": [],
    }
    assert result["candidates"][0]["schedule"] == {
        "type": "FLEXIBLE_WINDOW",
        "window_start": "2026-11-02T08:00:00+07:00",
        "window_end": "2026-11-02T12:00:00+07:00",
        "duration_minutes": 60,
    }


def test_flexible_duration_larger_than_window_needs_review():
    item = activity("A")
    result = assess_feasibility(
        request(item),
        evidence=evidence(item, schedule_by_activity={"A": flexible_schedule(61)}),
    )
    assert result["candidates"][0]["schedule"] is None
    assert result["candidates"][0]["feasibility"] == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["UNSUPPORTED_SCHEDULE"],
    }


def test_online_without_schedule_evidence_needs_review():
    item = activity("A")
    result = assess_feasibility(
        request(item),
        evidence=evidence(item, schedule_by_activity={}),
    )
    assert result["candidates"][0]["schedule"] is None
    assert result["candidates"][0]["feasibility"] == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["MISSING_SCHEDULE_TYPE"],
    }


def test_same_day_offline_without_evidence_uses_fixed_fallback():
    item = activity("A", mode="offline", location="Room A")
    result = assess_feasibility(
        request(item),
        evidence=evidence(item, schedule_by_activity={}),
    )
    assert result["candidates"][0]["schedule"] == activity_fixed_schedule(item)
    assert result["candidates"][0]["feasibility"]["status"] == "FEASIBLE"


def test_multi_day_offline_without_evidence_needs_schedule_type():
    item = activity(
        "A",
        mode="offline",
        location="Campus",
        start="2026-11-02T09:00:00+07:00",
        end="2026-11-03T10:00:00+07:00",
    )
    result = assess_feasibility(
        request(item),
        evidence=evidence(item, schedule_by_activity={}),
    )
    assert result["candidates"][0]["schedule"] is None
    assert result["candidates"][0]["feasibility"] == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["MISSING_SCHEDULE_TYPE"],
    }


def test_local_date_fallback_uses_vietnam_timezone_not_raw_offsets():
    item = activity(
        "A",
        mode="offline",
        location="Campus",
        start="2026-11-02T23:30:00+08:00",
        end="2026-11-03T00:30:00+08:00",
    )
    result = assess_feasibility(
        request(item),
        evidence=evidence(item, schedule_by_activity={}),
    )
    assert result["candidates"][0]["schedule"]["type"] == "FIXED"


def test_registered_activity_skips_missing_deadline():
    item = activity("A", registration_deadline=None)
    payload = request(
        item,
        participation_by_id={"A": participation("REGISTERED")},
    )
    assert assessment(payload, evidence(item)) == {
        "status": "FEASIBLE",
        "reason_codes": [],
    }


def test_registered_activity_skips_passed_deadline():
    item = activity(
        "A",
        registration_deadline="2026-11-01T07:00:00+07:00",
    )
    payload = request(
        item,
        participation_by_id={"A": participation("REGISTERED")},
    )
    assert assessment(payload, evidence(item)) == {
        "status": "FEASIBLE",
        "reason_codes": [],
    }


def test_not_registered_activity_checks_deadline():
    item = activity("A", registration_deadline=AS_OF)
    assert assessment(request(item), evidence(item)) == {
        "status": "INFEASIBLE",
        "reason_codes": ["DEADLINE_PASSED"],
    }


@pytest.mark.parametrize(
    ("progress", "reason"),
    [("COMPLETED", "ALREADY_COMPLETED"), ("CANCELLED", "CANCELLED")],
)
def test_completed_and_cancelled_are_infeasible(progress, reason):
    item = activity("A")
    payload = request(
        item,
        participation_by_id={"A": participation(progress=progress)},
    )
    assert assessment(payload, evidence(item)) == {
        "status": "INFEASIBLE",
        "reason_codes": [reason],
    }


def test_multi_session_conflicts_are_sorted_unique_and_half_open():
    first = activity("A", start=None, end=None)
    second = activity("B", start=None, end=None)
    adjoining = activity("C", start=None, end=None)
    schedules = {
        "A": fixed_schedule(
            ("2026-11-02T08:00:00+07:00", "2026-11-02T09:00:00+07:00"),
            ("2026-11-03T10:00:00+07:00", "2026-11-03T11:00:00+07:00"),
        ),
        "B": fixed_schedule(
            ("2026-11-03T10:30:00+07:00", "2026-11-03T11:30:00+07:00"),
        ),
        "C": fixed_schedule(
            ("2026-11-02T09:00:00+07:00", "2026-11-02T10:00:00+07:00"),
        ),
    }
    result = assess_feasibility(
        request(first, second, adjoining),
        evidence=evidence(
            first,
            second,
            adjoining,
            schedule_by_activity=schedules,
        ),
    )
    assert result["conflict_pairs"] == [["A", "B"]]


def test_flexible_candidates_never_create_conflict_pairs():
    flexible = activity("A")
    fixed = activity("B")
    result = assess_feasibility(
        request(flexible, fixed),
        evidence=evidence(
            flexible,
            fixed,
            schedule_by_activity={
                "A": flexible_schedule(30),
                "B": activity_fixed_schedule(fixed),
            },
        ),
    )
    assert result["conflict_pairs"] == []


def test_missing_source_review_is_not_implicitly_trusted():
    item = activity("A")
    assert assessment(
        request(item),
        evidence(item, source_review_by_activity={}),
    ) == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["NEEDS_SOURCE_REVIEW"],
    }


def test_unknown_and_failed_eligibility_remain_distinct():
    first = activity("A")
    second = activity("B")
    trusted = evidence(
        first,
        second,
        eligibility_by_activity={"B": "INELIGIBLE"},
    )
    result = assess_feasibility(request(first, second), evidence=trusted)
    assert result["candidates"][0]["feasibility"] == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["MISSING_ELIGIBILITY"],
    }
    assert result["candidates"][1]["feasibility"] == {
        "status": "INFEASIBLE",
        "reason_codes": ["INELIGIBLE"],
    }


@pytest.mark.parametrize(
    ("term_scope", "expected"),
    [
        (TermScopeStatus.IN_SCOPE, {"status": "FEASIBLE", "reason_codes": []}),
        (
            TermScopeStatus.OUT_OF_SCOPE,
            {"status": "INFEASIBLE", "reason_codes": ["OUTSIDE_WINDOW"]},
        ),
        (
            TermScopeStatus.NEEDS_REVIEW,
            {"status": "NEEDS_REVIEW", "reason_codes": ["TERM_UNVERIFIED"]},
        ),
    ],
)
def test_per_activity_term_scope_is_applied(term_scope, expected):
    item = activity("A")
    trusted = FeasibilityEvidence(
        term_verified=None,
        eligibility_by_activity={"A": "ELIGIBLE"},
        term_scope_by_activity={"A": term_scope},
        source_review_by_activity={"A": True},
        schedule_by_activity={"A": activity_fixed_schedule(item)},
    )
    assert assessment(request(item), trusted) == expected


def test_known_failure_wins_over_review_and_keeps_all_reasons():
    item = activity("A", registration_deadline=None)
    trusted = FeasibilityEvidence(
        schedule_by_activity={"A": activity_fixed_schedule(item)},
    )
    assert assessment(request(item, intervals=[]), trusted) == {
        "status": "INFEASIBLE",
        "reason_codes": [
            "OUTSIDE_AVAILABILITY",
            "MISSING_DEADLINE",
            "MISSING_ELIGIBILITY",
            "NEEDS_SOURCE_REVIEW",
            "TERM_UNVERIFIED",
        ],
    }


def test_invalid_fixed_evidence_is_rejected():
    item = activity("A")
    invalid = fixed_schedule(
        ("2026-11-02T10:00:00+07:00", "2026-11-02T11:00:00+07:00"),
        ("2026-11-02T09:00:00+07:00", "2026-11-02T09:30:00+07:00"),
    )
    with pytest.raises(FeasibilityContractError, match="sorted by start"):
        assess_feasibility(
            request(item),
            evidence=evidence(item, schedule_by_activity={"A": invalid}),
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(contract_version="sp3-planner/9.9"), "contract_version"),
        (
            lambda payload: payload["context"].update(
                window_start="2026-11-01T00:00:00"
            ),
            "explicit UTC offset",
        ),
        (
            lambda payload: payload["activities"].append(
                deepcopy(payload["activities"][0])
            ),
            "duplicate ID",
        ),
        (
            lambda payload: payload["activities"][0].pop("participation"),
            "missing fields: participation",
        ),
        (
            lambda payload: payload["activities"][0]["participation"].update(
                progress="UNKNOWN"
            ),
            "must be one of",
        ),
        (lambda payload: payload.update(unexpected=True), "unexpected fields"),
    ],
)
def test_invalid_contract_inputs_are_rejected(mutate, message):
    item = activity("A")
    payload = request(item)
    mutate(payload)
    with pytest.raises(FeasibilityContractError, match=message):
        assess_feasibility(payload, evidence=evidence(item))


def test_assessment_does_not_mutate_request_or_evidence():
    first = activity("A")
    second = activity("B")
    payload = request(first, second)
    trusted = evidence(first, second)
    original_payload = deepcopy(payload)
    original_schedules = deepcopy(trusted.schedule_by_activity)
    assess_feasibility(payload, evidence=trusted)
    assert payload == original_payload
    assert trusted.schedule_by_activity == original_schedules
