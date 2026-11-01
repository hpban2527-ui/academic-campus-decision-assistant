"""Deterministic SP3 constraint and schedule feasibility checks.

The module implements Như Ngọc's side of the SP3 planner contract.  It is
deliberately read-only: it classifies activities and reports pairwise schedule
conflicts, but it does not rank activities, award DRL points, or mutate student
state.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


CONTRACT_VERSION = "sp3-planner/0.1"

_REQUEST_FIELDS = {
    "contract_version",
    "request_id",
    "context",
    "available_intervals",
    "activities",
}
_CONTEXT_FIELDS = {
    "student_id",
    "term_id",
    "window_start",
    "window_end",
    "as_of",
    "timezone",
    "baseline_ref",
    "dataset_version",
    "ruleset_version",
    "calendar_version",
}
_ACTIVITY_ENTRY_FIELDS = {"activity", "score_binding_ref"}
_ACTIVITY_FIELDS = {
    "activity_id",
    "source",
    "title",
    "domain",
    "start",
    "end",
    "registration_deadline",
    "mode",
    "location",
    "points",
    "mandatory",
    "audience",
    "fee",
    "completion_requirements",
}
_SOURCE_FIELDS = {"publisher", "platform", "URL_post", "URL_registration"}
_INTERVAL_FIELDS = {"start", "end"}
_DOMAINS = {"academic", "volunteer", "culture_sports", "skills", "career", "other"}
_MODES = {"online", "offline", "hybrid"}

# Keep reason order stable for the planner, UI, fixtures, and reproducible tests.
_REASON_ORDER = (
    "OUTSIDE_WINDOW",
    "OUTSIDE_AVAILABILITY",
    "WINDOW_ENDED",
    "DEADLINE_PASSED",
    "ALREADY_STARTED",
    "INELIGIBLE",
    "MISSING_SCHEDULE",
    "MISSING_SCHEDULE_TYPE",
    "MISSING_REQUIRED_DURATION",
    "MISSING_DEADLINE",
    "MISSING_ELIGIBILITY",
    "NEEDS_SOURCE_REVIEW",
    "TERM_UNVERIFIED",
    "MISSING_SCORE_BINDING",
    "UNSUPPORTED_SCHEDULE",
)
_INFEASIBLE_REASONS = {
    "OUTSIDE_WINDOW",
    "OUTSIDE_AVAILABILITY",
    "WINDOW_ENDED",
    "DEADLINE_PASSED",
    "ALREADY_STARTED",
    "INELIGIBLE",
}


class FeasibilityContractError(ValueError):
    """Raised when an internal feasibility request violates contract v0.1."""


class FeasibilityStatus(str, Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class TermScopeStatus(str, Enum):
    """Per-activity mapping of Minh Trí's Semester 3 QA classification."""

    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ScheduleType(str, Enum):
    """Meaning of activity ``start``/``end`` for schedule feasibility."""

    FIXED = "FIXED"
    FLEXIBLE_WINDOW = "FLEXIBLE_WINDOW"
    ASYNCHRONOUS = "ASYNCHRONOUS"


@dataclass(frozen=True)
class FeasibilityEvidence:
    """Trusted facts resolved by the backend outside the 14-field activity.

    ``None`` and missing activity IDs intentionally mean "not verified".  This
    prevents the feasibility module from guessing eligibility or term scope
    from free-form audience text.
    """

    term_verified: bool | None = None
    eligibility_by_activity: Mapping[str, EligibilityStatus | str] = field(
        default_factory=dict
    )
    term_scope_by_activity: Mapping[str, TermScopeStatus | str] = field(
        default_factory=dict
    )
    source_review_by_activity: Mapping[str, bool | None] = field(default_factory=dict)
    schedule_by_activity: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class _ParsedActivity:
    entry: Mapping[str, Any]
    activity_id: str
    start: datetime | None
    end: datetime | None
    deadline: datetime | None


@dataclass(frozen=True)
class _ResolvedSchedule:
    schedule_type: ScheduleType | None
    required_duration_minutes: float | None = None


def _fail(path: str, message: str) -> None:
    raise FeasibilityContractError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], path: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        _fail(path, f"missing fields: {', '.join(missing)}")
    if unknown:
        _fail(path, f"unexpected fields: {', '.join(unknown)}")


def _non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    return value


def _timestamp(value: Any, path: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    text = _non_empty_string(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail(path, "must be a valid ISO 8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(path, "must include an explicit UTC offset")
    return parsed


def _number_or_null(value: Any, path: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a non-negative number or null")
    if value < 0 or value != value or value in (float("inf"), float("-inf")):
        _fail(path, "must be a finite non-negative number or null")


def _http_url_or_null(value: Any, path: str, *, nullable: bool) -> None:
    if value is None and nullable:
        return
    text = _non_empty_string(value, path)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _fail(path, "must be an absolute HTTP(S) URL")


def _validate_source(value: Any, path: str) -> None:
    source = _mapping(value, path)
    _exact_fields(source, _SOURCE_FIELDS, path)
    _non_empty_string(source["publisher"], f"{path}.publisher")
    _non_empty_string(source["platform"], f"{path}.platform")
    _http_url_or_null(source["URL_post"], f"{path}.URL_post", nullable=False)
    _http_url_or_null(
        source["URL_registration"], f"{path}.URL_registration", nullable=True
    )


def _validate_activity(value: Any, path: str) -> tuple[str, datetime | None, datetime | None, datetime | None]:
    activity = _mapping(value, path)
    _exact_fields(activity, _ACTIVITY_FIELDS, path)
    activity_id = _non_empty_string(activity["activity_id"], f"{path}.activity_id")
    _validate_source(activity["source"], f"{path}.source")
    _non_empty_string(activity["title"], f"{path}.title")
    if activity["domain"] is not None and activity["domain"] not in _DOMAINS:
        _fail(f"{path}.domain", f"must be null or one of {sorted(_DOMAINS)}")
    start = _timestamp(activity["start"], f"{path}.start", nullable=True)
    end = _timestamp(activity["end"], f"{path}.end", nullable=True)
    deadline = _timestamp(
        activity["registration_deadline"],
        f"{path}.registration_deadline",
        nullable=True,
    )
    if activity["mode"] not in _MODES:
        _fail(f"{path}.mode", f"must be one of {sorted(_MODES)}")
    if activity["location"] is not None and not isinstance(activity["location"], str):
        _fail(f"{path}.location", "must be a string or null")
    if activity["mode"] == "online" and activity["location"] is not None:
        _fail(f"{path}.location", "must be null for an online activity")
    _number_or_null(activity["points"], f"{path}.points")
    if not isinstance(activity["mandatory"], bool):
        _fail(f"{path}.mandatory", "must be a boolean")
    audience = activity["audience"]
    if audience is not None:
        if not isinstance(audience, list) or any(not isinstance(item, str) for item in audience):
            _fail(f"{path}.audience", "must be an array of strings or null")
    _number_or_null(activity["fee"], f"{path}.fee")
    if activity["fee"] is None:
        _fail(f"{path}.fee", "must be a non-negative number")
    _non_empty_string(
        activity["completion_requirements"], f"{path}.completion_requirements"
    )
    return activity_id, start, end, deadline


def _validate_request(request: Any) -> tuple[
    Mapping[str, Any], datetime, datetime, datetime, list[tuple[datetime, datetime]], list[_ParsedActivity]
]:
    payload = _mapping(request, "request")
    _exact_fields(payload, _REQUEST_FIELDS, "request")
    if payload["contract_version"] != CONTRACT_VERSION:
        _fail("request.contract_version", f"must equal {CONTRACT_VERSION!r}")
    _non_empty_string(payload["request_id"], "request.request_id")

    context = _mapping(payload["context"], "request.context")
    _exact_fields(context, _CONTEXT_FIELDS, "request.context")
    for field_name in _CONTEXT_FIELDS - {
        "window_start",
        "window_end",
        "as_of",
    }:
        _non_empty_string(context[field_name], f"request.context.{field_name}")
    if context["timezone"] != "Asia/Ho_Chi_Minh":
        _fail("request.context.timezone", "must equal 'Asia/Ho_Chi_Minh'")
    window_start = _timestamp(context["window_start"], "request.context.window_start")
    window_end = _timestamp(context["window_end"], "request.context.window_end")
    as_of = _timestamp(context["as_of"], "request.context.as_of")
    assert window_start is not None and window_end is not None and as_of is not None
    if window_start >= window_end:
        _fail("request.context", "window_start must be earlier than window_end")
    if as_of > window_end:
        _fail("request.context.as_of", "must not be later than window_end")

    raw_intervals = payload["available_intervals"]
    if not isinstance(raw_intervals, list):
        _fail("request.available_intervals", "must be an array")
    intervals: list[tuple[datetime, datetime]] = []
    for index, raw_interval in enumerate(raw_intervals):
        path = f"request.available_intervals[{index}]"
        interval = _mapping(raw_interval, path)
        _exact_fields(interval, _INTERVAL_FIELDS, path)
        start = _timestamp(interval["start"], f"{path}.start")
        end = _timestamp(interval["end"], f"{path}.end")
        assert start is not None and end is not None
        if start >= end:
            _fail(path, "start must be earlier than end")
        intervals.append((start, end))

    raw_activities = payload["activities"]
    if not isinstance(raw_activities, list):
        _fail("request.activities", "must be an array")
    activities: list[_ParsedActivity] = []
    seen_ids: set[str] = set()
    for index, raw_entry in enumerate(raw_activities):
        path = f"request.activities[{index}]"
        entry = _mapping(raw_entry, path)
        _exact_fields(entry, _ACTIVITY_ENTRY_FIELDS, path)
        activity_id, start, end, deadline = _validate_activity(
            entry["activity"], f"{path}.activity"
        )
        if activity_id in seen_ids:
            _fail(f"{path}.activity.activity_id", f"duplicate ID {activity_id!r}")
        seen_ids.add(activity_id)
        binding = entry["score_binding_ref"]
        if binding is not None:
            _non_empty_string(binding, f"{path}.score_binding_ref")
        activities.append(_ParsedActivity(entry, activity_id, start, end, deadline))
    return payload, window_start, window_end, as_of, _merge_intervals(intervals), activities


def _merge_intervals(
    intervals: Sequence[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals, key=lambda item: (item[0], item[1])):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _covered_by_availability(
    start: datetime,
    end: datetime,
    available_intervals: Sequence[tuple[datetime, datetime]],
) -> bool:
    return any(free_start <= start and end <= free_end for free_start, free_end in available_intervals)


def _available_minutes_within(
    start: datetime,
    end: datetime,
    available_intervals: Sequence[tuple[datetime, datetime]],
) -> float:
    """Sum merged free-time fragments inside a flexible activity window."""

    seconds = 0.0
    for free_start, free_end in available_intervals:
        overlap_start = max(start, free_start)
        overlap_end = min(end, free_end)
        if overlap_start < overlap_end:
            seconds += (overlap_end - overlap_start).total_seconds()
    return seconds / 60


def _resolve_schedule(
    parsed: _ParsedActivity,
    evidence: FeasibilityEvidence,
) -> _ResolvedSchedule:
    """Resolve schedule semantics without changing SP1's 14-field activity.

    Offline and hybrid activities keep the v0.1 fixed-time behaviour when no
    additional evidence is available.  Online activities are deliberately not
    guessed: an unknown online schedule becomes a review state instead of
    being falsely rejected as if its whole availability window were a meeting.
    """

    path = f"evidence.schedule_by_activity[{parsed.activity_id!r}]"
    raw = evidence.schedule_by_activity.get(parsed.activity_id)
    if raw is None:
        mode = parsed.entry["activity"]["mode"]
        if mode == "online":
            return _ResolvedSchedule(None)
        return _ResolvedSchedule(ScheduleType.FIXED)
    value = _mapping(raw, path)
    _exact_fields(value, {"schedule_type", "required_duration_minutes"}, path)
    try:
        schedule_type = ScheduleType(value["schedule_type"])
    except (ValueError, TypeError):
        _fail(path + ".schedule_type", f"must be one of {[item.value for item in ScheduleType]}")

    duration = value["required_duration_minutes"]
    if duration is not None:
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            _fail(path + ".required_duration_minutes", "must be a positive number or null")
        if duration <= 0 or duration != duration or duration in (float("inf"), float("-inf")):
            _fail(path + ".required_duration_minutes", "must be a finite positive number or null")
        duration = float(duration)
    if schedule_type is not ScheduleType.FLEXIBLE_WINDOW and duration is not None:
        _fail(
            path + ".required_duration_minutes",
            "must be null unless schedule_type is FLEXIBLE_WINDOW",
        )
    return _ResolvedSchedule(schedule_type, duration)


def _normalise_eligibility(value: EligibilityStatus | str | None, path: str) -> EligibilityStatus:
    if value is None:
        return EligibilityStatus.NEEDS_REVIEW
    try:
        return EligibilityStatus(value)
    except (ValueError, TypeError):
        _fail(path, f"must be one of {[item.value for item in EligibilityStatus]}")


def _normalise_term_scope(
    value: TermScopeStatus | str | None,
    path: str,
) -> TermScopeStatus | None:
    if value is None:
        return None
    try:
        return TermScopeStatus(value)
    except (ValueError, TypeError):
        _fail(path, f"must be one of {[item.value for item in TermScopeStatus]}")


def _ordered_reasons(reasons: set[str]) -> list[str]:
    return [reason for reason in _REASON_ORDER if reason in reasons]


def _assess_one(
    parsed: _ParsedActivity,
    *,
    schedule: _ResolvedSchedule,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    available_intervals: Sequence[tuple[datetime, datetime]],
    evidence: FeasibilityEvidence,
) -> dict[str, Any]:
    reasons: set[str] = set()
    start, end = parsed.start, parsed.end

    if start is None or end is None:
        reasons.add("MISSING_SCHEDULE")
    elif start >= end:
        reasons.add("UNSUPPORTED_SCHEDULE")
    elif schedule.schedule_type is ScheduleType.FIXED:
        if start < window_start or end > window_end:
            reasons.add("OUTSIDE_WINDOW")
        if start < as_of:
            reasons.add("ALREADY_STARTED")
        if not _covered_by_availability(start, end, available_intervals):
            reasons.add("OUTSIDE_AVAILABILITY")
    else:
        # For flexible/asynchronous online work, start/end describe an access
        # window.  Opening before ``as_of`` is valid; only an ended or wholly
        # out-of-scope window is a certain failure.
        if schedule.schedule_type is None:
            reasons.add("MISSING_SCHEDULE_TYPE")
        if end <= as_of:
            reasons.add("WINDOW_ENDED")
        elif end <= window_start or start >= window_end:
            reasons.add("OUTSIDE_WINDOW")
        elif schedule.schedule_type is ScheduleType.FLEXIBLE_WINDOW:
            duration = schedule.required_duration_minutes
            if duration is None:
                reasons.add("MISSING_REQUIRED_DURATION")
            else:
                usable_start = max(start, window_start, as_of)
                usable_end = min(end, window_end)
                if (
                    usable_start >= usable_end
                    or _available_minutes_within(
                        usable_start, usable_end, available_intervals
                    )
                    < duration
                ):
                    reasons.add("OUTSIDE_AVAILABILITY")

    if parsed.deadline is None:
        reasons.add("MISSING_DEADLINE")
    elif as_of >= parsed.deadline:
        reasons.add("DEADLINE_PASSED")

    eligibility = _normalise_eligibility(
        evidence.eligibility_by_activity.get(parsed.activity_id),
        f"evidence.eligibility_by_activity[{parsed.activity_id!r}]",
    )
    if eligibility is EligibilityStatus.INELIGIBLE:
        reasons.add("INELIGIBLE")
    elif eligibility is EligibilityStatus.NEEDS_REVIEW:
        reasons.add("MISSING_ELIGIBILITY")

    source_review = evidence.source_review_by_activity.get(parsed.activity_id, True)
    if source_review is not True:
        reasons.add("NEEDS_SOURCE_REVIEW")
    term_scope = _normalise_term_scope(
        evidence.term_scope_by_activity.get(parsed.activity_id),
        f"evidence.term_scope_by_activity[{parsed.activity_id!r}]",
    )
    if term_scope is TermScopeStatus.OUT_OF_SCOPE:
        reasons.add("OUTSIDE_WINDOW")
    elif term_scope is TermScopeStatus.NEEDS_REVIEW:
        reasons.add("TERM_UNVERIFIED")
    elif term_scope is None and evidence.term_verified is not True:
        reasons.add("TERM_UNVERIFIED")
    if parsed.entry["score_binding_ref"] is None:
        reasons.add("MISSING_SCORE_BINDING")

    if reasons & _INFEASIBLE_REASONS:
        status = FeasibilityStatus.INFEASIBLE
    elif reasons:
        status = FeasibilityStatus.NEEDS_REVIEW
    else:
        status = FeasibilityStatus.FEASIBLE

    result = deepcopy(dict(parsed.entry))
    result["feasibility"] = {
        "status": status.value,
        "reason_codes": _ordered_reasons(reasons),
    }
    return result


def _conflict_pairs(
    activities: Sequence[_ParsedActivity],
    schedules: Mapping[str, _ResolvedSchedule],
) -> list[list[str]]:
    scheduled = [
        item
        for item in activities
        if schedules[item.activity_id].schedule_type is ScheduleType.FIXED
        and item.start is not None
        and item.end is not None
        and item.start < item.end
    ]
    pairs: set[tuple[str, str]] = set()
    for left_index, left in enumerate(scheduled):
        for right in scheduled[left_index + 1 :]:
            assert left.start is not None and left.end is not None
            assert right.start is not None and right.end is not None
            # Half-open intervals: adjoining activities do not conflict.
            if left.start < right.end and right.start < left.end:
                pairs.add(tuple(sorted((left.activity_id, right.activity_id))))
    return [list(pair) for pair in sorted(pairs)]


def assess_feasibility(
    request: Mapping[str, Any],
    *,
    evidence: FeasibilityEvidence | None = None,
) -> dict[str, Any]:
    """Validate and assess a ``feasibility_request`` from planner contract v0.1.

    Unknown eligibility and term verification are review states, never implicit
    approval.  The backend should pass trusted :class:`FeasibilityEvidence` to
    produce FEASIBLE candidates.
    """

    trusted_evidence = evidence or FeasibilityEvidence()
    (
        payload,
        window_start,
        window_end,
        as_of,
        available_intervals,
        activities,
    ) = _validate_request(request)
    schedules = {
        activity.activity_id: _resolve_schedule(activity, trusted_evidence)
        for activity in activities
    }
    candidates = [
        _assess_one(
            activity,
            schedule=schedules[activity.activity_id],
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
            available_intervals=available_intervals,
            evidence=trusted_evidence,
        )
        for activity in activities
    ]
    return {
        "contract_version": payload["contract_version"],
        "request_id": payload["request_id"],
        "context": deepcopy(payload["context"]),
        "candidates": candidates,
        "conflict_pairs": _conflict_pairs(activities, schedules),
    }
