from __future__ import annotations

from copy import deepcopy

import pytest

from sp3 import (
    FeasibilityContractError,
    FeasibilityEvidence,
    TermScopeStatus,
    assess_feasibility,
)


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


def request(*activities, intervals=None):
    if not activities:
        activities = (activity(),)
    return {
        "contract_version": "sp3-planner/0.1",
        "request_id": "feasibility-test",
        "context": {
            "student_id": "synthetic-student",
            "term_id": "SYNTHETIC-DEMO",
            "window_start": "2026-11-01T00:00:00+07:00",
            "window_end": "2026-11-04T00:00:00+07:00",
            "as_of": "2026-11-01T08:00:00+07:00",
            "timezone": "Asia/Ho_Chi_Minh",
            "baseline_ref": "mock-baseline-01",
            "dataset_version": "mock-data-01",
            "ruleset_version": "mock-rules-01",
            "calendar_version": "mock-calendar-01",
        },
        "available_intervals": intervals
        if intervals is not None
        else [
            {
                "start": "2026-11-01T00:00:00+07:00",
                "end": "2026-11-04T00:00:00+07:00",
            }
        ],
        "activities": [
            {"activity": item, "score_binding_ref": f"binding-{item['activity_id']}"}
            for item in activities
        ],
    }


def schedule_record(schedule_type="FIXED", required_duration_minutes=None):
    return {
        "schedule_type": schedule_type,
        "required_duration_minutes": required_duration_minutes,
    }


def evidence(
    *ids: str,
    term_verified=True,
    source_review_by_activity=None,
    schedule_by_activity=None,
):
    return FeasibilityEvidence(
        term_verified=term_verified,
        eligibility_by_activity={item: "ELIGIBLE" for item in ids},
        source_review_by_activity=source_review_by_activity or {},
        schedule_by_activity=schedule_by_activity
        or {item: schedule_record() for item in ids},
    )


def assessment(payload, trusted=None, index=0):
    return assess_feasibility(payload, evidence=trusted)["candidates"][index][
        "feasibility"
    ]


def test_complete_activity_is_feasible_with_explicit_trusted_evidence():
    payload = request(activity("A"))

    result = assess_feasibility(payload, evidence=evidence("A"))

    assert result == {
        "contract_version": "sp3-planner/0.1",
        "request_id": "feasibility-test",
        "context": payload["context"],
        "candidates": [
            {
                **payload["activities"][0],
                "feasibility": {"status": "FEASIBLE", "reason_codes": []},
            }
        ],
        "conflict_pairs": [],
    }


@pytest.mark.parametrize(
    ("changes", "expected_reasons"),
    [
        ({"start": None}, ["MISSING_SCHEDULE"]),
        ({"end": None}, ["MISSING_SCHEDULE"]),
        ({"registration_deadline": None}, ["MISSING_DEADLINE"]),
        (
            {"registration_deadline": "2026-11-01T08:00:00+07:00"},
            ["DEADLINE_PASSED"],
        ),
        (
            {
                "start": "2026-11-01T07:00:00+07:00",
                "end": "2026-11-01T09:00:00+07:00",
            },
            ["ALREADY_STARTED"],
        ),
        (
            {
                "start": "2026-11-04T09:00:00+07:00",
                "end": "2026-11-04T10:00:00+07:00",
            },
            ["OUTSIDE_WINDOW", "OUTSIDE_AVAILABILITY"],
        ),
        (
            {
                "start": "2026-11-02T10:00:00+07:00",
                "end": "2026-11-02T09:00:00+07:00",
            },
            ["UNSUPPORTED_SCHEDULE"],
        ),
    ],
)
def test_time_and_deadline_cases_have_expected_output(changes, expected_reasons):
    result = assessment(request(activity("A", **changes)), evidence("A"))
    expected_status = (
        "INFEASIBLE"
        if set(expected_reasons)
        & {"DEADLINE_PASSED", "ALREADY_STARTED", "OUTSIDE_WINDOW"}
        else "NEEDS_REVIEW"
    )
    assert result == {"status": expected_status, "reason_codes": expected_reasons}


def test_activity_outside_free_intervals_is_infeasible():
    payload = request(
        activity("A"),
        intervals=[
            {
                "start": "2026-11-02T07:00:00+07:00",
                "end": "2026-11-02T08:00:00+07:00",
            }
        ],
    )
    assert assessment(payload, evidence("A")) == {
        "status": "INFEASIBLE",
        "reason_codes": ["OUTSIDE_AVAILABILITY"],
    }


def test_overlapping_and_adjoining_free_intervals_are_merged():
    payload = request(
        activity("A", start="2026-11-02T09:30:00+07:00", end="2026-11-02T11:00:00+07:00"),
        intervals=[
            {
                "start": "2026-11-02T09:00:00+07:00",
                "end": "2026-11-02T10:00:00+07:00",
            },
            {
                "start": "2026-11-02T10:00:00+07:00",
                "end": "2026-11-02T10:30:00+07:00",
            },
            {
                "start": "2026-11-02T10:15:00+07:00",
                "end": "2026-11-02T11:00:00+07:00",
            },
        ],
    )
    assert assessment(payload, evidence("A")) == {
        "status": "FEASIBLE",
        "reason_codes": [],
    }


def test_unknown_and_explicitly_failed_eligibility_are_distinct():
    payload = request(activity("A"), activity("B"))
    trusted = FeasibilityEvidence(
        term_verified=True,
        eligibility_by_activity={"B": "INELIGIBLE"},
        schedule_by_activity={
            "A": schedule_record(),
            "B": schedule_record(),
        },
    )
    result = assess_feasibility(payload, evidence=trusted)
    assert result["candidates"][0]["feasibility"] == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["MISSING_ELIGIBILITY"],
    }
    assert result["candidates"][1]["feasibility"] == {
        "status": "INFEASIBLE",
        "reason_codes": ["INELIGIBLE"],
    }


def test_unverified_term_source_and_missing_binding_require_review():
    payload = request(activity("A"))
    payload["activities"][0]["score_binding_ref"] = None
    trusted = FeasibilityEvidence(
        term_verified=None,
        eligibility_by_activity={"A": "ELIGIBLE"},
        source_review_by_activity={"A": False},
        schedule_by_activity={"A": schedule_record()},
    )
    assert assessment(payload, trusted) == {
        "status": "NEEDS_REVIEW",
        "reason_codes": [
            "NEEDS_SOURCE_REVIEW",
            "TERM_UNVERIFIED",
            "MISSING_SCORE_BINDING",
        ],
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
def test_per_activity_data_qa_term_scope_is_applied(term_scope, expected):
    payload = request(activity("A"))
    trusted = FeasibilityEvidence(
        term_verified=None,
        eligibility_by_activity={"A": "ELIGIBLE"},
        term_scope_by_activity={"A": term_scope},
        schedule_by_activity={"A": schedule_record()},
    )
    assert assessment(payload, trusted) == expected


def test_conflicts_are_sorted_unique_and_use_half_open_intervals():
    payload = request(
        activity("C", start="2026-11-02T10:00:00+07:00", end="2026-11-02T11:00:00+07:00"),
        activity("A", start="2026-11-02T09:00:00+07:00", end="2026-11-02T10:00:00+07:00"),
        activity("B", start="2026-11-02T09:30:00+07:00", end="2026-11-02T10:30:00+07:00"),
    )
    result = assess_feasibility(payload, evidence=evidence("A", "B", "C"))
    assert result["conflict_pairs"] == [["A", "B"], ["B", "C"]]


def test_online_with_unknown_schedule_type_needs_review_instead_of_false_rejection():
    payload = request(activity("A"), intervals=[])
    trusted = FeasibilityEvidence(
        term_verified=True,
        eligibility_by_activity={"A": "ELIGIBLE"},
    )

    assert assessment(payload, trusted) == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["MISSING_SCHEDULE_TYPE"],
    }


def test_flexible_online_window_sums_separate_free_time_fragments():
    payload = request(
        activity(
            "A",
            start="2026-11-01T09:00:00+07:00",
            end="2026-11-03T18:00:00+07:00",
        ),
        intervals=[
            {
                "start": "2026-11-02T09:00:00+07:00",
                "end": "2026-11-02T09:30:00+07:00",
            },
            {
                "start": "2026-11-03T14:00:00+07:00",
                "end": "2026-11-03T14:30:00+07:00",
            },
        ],
    )
    trusted = evidence(
        "A",
        schedule_by_activity={
            "A": schedule_record("FLEXIBLE_WINDOW", 60),
        },
    )

    assert assessment(payload, trusted) == {
        "status": "FEASIBLE",
        "reason_codes": [],
    }


def test_flexible_online_window_is_infeasible_only_when_total_free_time_is_too_short():
    payload = request(
        activity(
            "A",
            start="2026-11-01T09:00:00+07:00",
            end="2026-11-03T18:00:00+07:00",
        ),
        intervals=[
            {
                "start": "2026-11-02T09:00:00+07:00",
                "end": "2026-11-02T09:45:00+07:00",
            }
        ],
    )
    trusted = evidence(
        "A",
        schedule_by_activity={
            "A": schedule_record("FLEXIBLE_WINDOW", 60),
        },
    )

    assert assessment(payload, trusted) == {
        "status": "INFEASIBLE",
        "reason_codes": ["OUTSIDE_AVAILABILITY"],
    }


def test_flexible_online_window_without_workload_requires_review_not_rejection():
    payload = request(activity("A"), intervals=[])
    trusted = evidence(
        "A",
        schedule_by_activity={
            "A": schedule_record("FLEXIBLE_WINDOW"),
        },
    )

    assert assessment(payload, trusted) == {
        "status": "NEEDS_REVIEW",
        "reason_codes": ["MISSING_REQUIRED_DURATION"],
    }


def test_asynchronous_online_activity_ignores_clock_availability_and_conflicts():
    payload = request(
        activity("ASYNC"),
        activity("FIXED"),
    )
    trusted = evidence(
        "ASYNC",
        "FIXED",
        schedule_by_activity={
            "ASYNC": schedule_record("ASYNCHRONOUS"),
            "FIXED": schedule_record("FIXED"),
        },
    )

    result = assess_feasibility(payload, evidence=trusted)

    assert result["candidates"][0]["feasibility"] == {
        "status": "FEASIBLE",
        "reason_codes": [],
    }
    assert result["conflict_pairs"] == []


def test_offline_activity_without_schedule_evidence_remains_fixed_time():
    payload = request(
        activity("A", mode="offline", location="Room A"),
        intervals=[],
    )
    trusted = FeasibilityEvidence(
        term_verified=True,
        eligibility_by_activity={"A": "ELIGIBLE"},
    )

    assert assessment(payload, trusted) == {
        "status": "INFEASIBLE",
        "reason_codes": ["OUTSIDE_AVAILABILITY"],
    }


def test_invalid_schedule_evidence_is_rejected():
    payload = request(activity("A"))
    trusted = evidence(
        "A",
        schedule_by_activity={
            "A": schedule_record("FLEXIBLE_WINDOW", -1),
        },
    )

    with pytest.raises(FeasibilityContractError, match="positive number"):
        assess_feasibility(payload, evidence=trusted)


def test_known_failure_wins_over_review_but_keeps_all_reason_codes():
    payload = request(
        activity("A", registration_deadline=None),
        intervals=[],
    )
    assert assessment(
        payload,
        FeasibilityEvidence(
            schedule_by_activity={"A": schedule_record()},
        ),
    ) == {
        "status": "INFEASIBLE",
        "reason_codes": [
            "OUTSIDE_AVAILABILITY",
            "MISSING_DEADLINE",
            "MISSING_ELIGIBILITY",
            "TERM_UNVERIFIED",
        ],
    }


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
        (lambda payload: payload.update(unexpected=True), "unexpected fields"),
    ],
)
def test_invalid_contract_inputs_are_rejected(mutate, message):
    payload = request(activity("A"))
    mutate(payload)
    with pytest.raises(FeasibilityContractError, match=message):
        assess_feasibility(payload, evidence=evidence("A"))


def test_assessment_does_not_mutate_the_request():
    payload = request(activity("A"), activity("B"))
    original = deepcopy(payload)
    assess_feasibility(payload, evidence=evidence("A", "B"))
    assert payload == original
