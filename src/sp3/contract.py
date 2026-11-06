"""Shared definitions and validators for the sp3-planner/0.2 contract.

The planner, scheduler, scorer adapter, projected scorer and plan checker all
use these primitives, so a timestamp, interval, schedule, participation state,
previous plan or keep request means the same thing everywhere. Validators raise
``ContractError(path, problem)``; the problem text describes structure and never
echoes payload values.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any

CONTRACT_VERSION = "sp3-planner/0.2"
TIMEZONE = "Asia/Ho_Chi_Minh"
ABS_TOLERANCE = 1e-9
PLAN_VERSION_PREFIX = "sp3plan-"
SCORE_COMPARISON_BASIS = "PREVIOUS_ACTIVITY_SET_RESCORED"


class PlannerStatus(str, Enum):
    ALREADY_MET = "ALREADY_MET"
    TARGET_MET = "TARGET_MET"
    PARTIAL = "PARTIAL"
    NO_FEASIBLE_CANDIDATES = "NO_FEASIBLE_CANDIDATES"
    KEEP_CONFLICT = "KEEP_CONFLICT"
    NEEDS_DATA = "NEEDS_DATA"
    ERROR = "ERROR"


class FeasibilityStatus(str, Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class FeasibilityConclusion(str, Enum):
    REACHABLE = "REACHABLE"
    PROVEN_UNREACHABLE = "PROVEN_UNREACHABLE"
    UNDETERMINED = "UNDETERMINED"


class ExclusionCode(str, Enum):
    """Declared in the order the contract applies them (section 10.3)."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_FEASIBLE = "NOT_FEASIBLE"
    ALREADY_COUNTED = "ALREADY_COUNTED"
    CONFLICT = "CONFLICT"
    NO_TIME = "NO_TIME"
    LIMIT = "LIMIT"
    LOWER_PRIORITY = "LOWER_PRIORITY"


class WarningCode(str, Enum):
    """Declared in the order warnings are emitted."""

    DEMO_ONLY = "DEMO_ONLY"
    TRAVEL_NOT_MODELED = "TRAVEL_NOT_MODELED"
    PENDING_CANDIDATES = "PENDING_CANDIDATES"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    DROPS_REGISTERED = "DROPS_REGISTERED"
    SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"


class LimitReason(str, Enum):
    EVALUATION_LIMIT = "EVALUATION_LIMIT"
    SCHEDULING_LIMIT = "SCHEDULING_LIMIT"
    ALREADY_MET = "ALREADY_MET"
    KEEP_CONFLICT = "KEEP_CONFLICT"
    SP2_FAILURE = "SP2_FAILURE"
    INVALID_INPUT = "INVALID_INPUT"


class ReasonCode(str, Enum):
    GOAL_CONTRIBUTION = "GOAL_CONTRIBUTION"
    PREFERENCE_MATCH = "PREFERENCE_MATCH"


class EvaluationStatus(str, Enum):
    OK = "OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ERROR = "ERROR"


class ProofKind(str, Enum):
    EXHAUSTIVE_SEARCH = "EXHAUSTIVE_SEARCH"


class ScheduleType(str, Enum):
    FIXED = "FIXED"
    FLEXIBLE_WINDOW = "FLEXIBLE_WINDOW"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    NOT_REGISTERED = "NOT_REGISTERED"


class ProgressStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class KeepMode(str, Enum):
    KEEP_TIME = "KEEP_TIME"


class ChangeLabel(str, Enum):
    KEPT = "KEPT"
    MOVED = "MOVED"
    ADDED = "ADDED"


class DroppedCode(str, Enum):
    CANCELLED = "CANCELLED"
    NO_LONGER_FEASIBLE = "NO_LONGER_FEASIBLE"
    NO_TIME = "NO_TIME"
    LOWER_PRIORITY = "LOWER_PRIORITY"
    NOT_LISTED = "NOT_LISTED"


class KeepConflictCode(str, Enum):
    """Section 10.4 conflicts, declared in the order they are listed per activity.

    NOT_LISTED, NOT_ELIGIBLE, FIXED_CHANGED and BLOCK_INVALID describe one kept
    activity; BLOCK_OVERLAP and CONFLICT a pair of kept activities; LIMIT the
    whole keep set, which no plan can contain within the stated limits.
    """

    NOT_LISTED = "NOT_LISTED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    FIXED_CHANGED = "FIXED_CHANGED"
    BLOCK_INVALID = "BLOCK_INVALID"
    BLOCK_OVERLAP = "BLOCK_OVERLAP"
    CONFLICT = "CONFLICT"
    LIMIT = "LIMIT"


DEMO_MODE = "DEMO_ONLY"
ALLOWED_DOMAINS = frozenset({"academic", "volunteer", "culture_sports", "skills", "career", "other"})
ALLOWED_MODES = frozenset({"online", "offline", "hybrid"})
# Section 6.4 lists these. Upstream may add codes, so validators check the
# code format, not membership.
STANDARD_FEASIBILITY_REASON_CODES = frozenset({
    "OUTSIDE_WINDOW", "OUTSIDE_AVAILABILITY", "WINDOW_ENDED", "ALREADY_STARTED",
    "DEADLINE_PASSED", "INELIGIBLE", "ALREADY_COMPLETED", "CANCELLED",
    "MISSING_SCHEDULE", "MISSING_SCHEDULE_TYPE", "UNSUPPORTED_SCHEDULE", "MISSING_DEADLINE",
    "MISSING_ELIGIBILITY", "NEEDS_SOURCE_REVIEW", "TERM_UNVERIFIED", "MISSING_SCORE_BINDING",
})

CONTEXT_FIELDS = frozenset({
    "student_id", "term_id", "window_start", "window_end", "as_of", "timezone",
    "baseline_ref", "dataset_version", "ruleset_version", "calendar_version",
})
BASELINE_FIELDS = frozenset({
    "category_scores", "category_caps", "total_score", "max_total_score",
    "included_activity_ids",
})
ACTIVITY_FIELDS = frozenset({
    "activity_id", "source", "title", "domain", "start", "end",
    "registration_deadline", "mode", "location", "points", "mandatory",
    "audience", "fee", "completion_requirements",
})
INTERVAL_FIELDS = frozenset({"start", "end"})
FIXED_SCHEDULE_FIELDS = frozenset({"type", "fixed_blocks"})
FLEXIBLE_SCHEDULE_FIELDS = frozenset({"type", "window_start", "window_end", "duration_minutes"})
PARTICIPATION_FIELDS = frozenset({"registration", "progress"})
PLANNED_ACTIVITY_FIELDS = frozenset({"activity_id", "scheduled_blocks"})
BASED_ON_FIELDS = frozenset({
    "calendar_version", "dataset_version", "ruleset_version", "baseline_ref", "previous_plan_version",
})
PREVIOUS_PLAN_FIELDS = frozenset({"plan_version", "based_on", "selected_activities"})
KEEP_REQUEST_FIELDS = frozenset({"activity_id", "mode"})
PLANNER_INPUT_FIELDS = frozenset({
    "contract_version", "request_id", "context", "baseline", "goals",
    "preferences", "limits", "candidates", "conflict_pairs",
    "available_intervals", "previous_plan", "keep_requests",
})
CANDIDATE_FIELDS = frozenset({"activity", "score_binding_ref", "participation", "schedule", "feasibility"})
FEASIBILITY_FIELDS = frozenset({"status", "reason_codes"})
GOALS_FIELDS = frozenset({"total_target", "category_targets"})
PREFERENCES_FIELDS = frozenset({"preferred_domains", "preferred_modes"})
LIMITS_FIELDS = frozenset({"max_activities", "max_duration_minutes"})
SCORE_REQUEST_FIELDS = frozenset({
    "contract_version", "request_id", "context", "baseline", "selected_activity_ids",
    "attribution_order",
})
SCORE_RESPONSE_FIELDS = (SCORE_REQUEST_FIELDS - {"baseline", "attribution_order"}) | {
    "evaluation_status", "result", "errors", "mode", "official_award_verified",
}
SCORE_RESULT_FIELDS = frozenset({
    "category_after", "category_gain", "total_after", "total_gain", "contributions",
})
CONTRIBUTION_FIELDS = frozenset({"activity_id", "category_id", "rule_id", "projected_added"})
ISSUE_FIELDS = frozenset({"code", "message", "activity_id"})
PLANNER_OUTPUT_FIELDS = frozenset({
    "contract_version", "request_id", "context", "status", "selected_activities",
    "excluded_candidates", "score_summary", "search", "feasibility_conclusion",
    "proof", "warnings", "errors", "mode", "official_award_verified",
    "dropped_activities", "pending_confirmation", "keep_conflicts",
    "score_comparison", "based_on", "plan_version",
})
SELECTED_ACTIVITY_FIELDS = frozenset({
    "activity_id", "title", "schedule_type", "scheduled_blocks", "registration", "change", "reasons",
})
EXCLUDED_CANDIDATE_FIELDS = frozenset({"activity_id", "code", "message"})
DROPPED_ACTIVITY_FIELDS = frozenset({"activity_id", "registered", "code", "message"})
KEEP_CONFLICT_FIELDS = frozenset({"activity_id", "code", "message"})
SCORE_COMPARISON_FIELDS = frozenset({
    "basis", "previous_activity_ids", "previous_projected_by_category",
    "previous_projected_total", "new_projected_total",
})
REASON_FIELDS = frozenset({"code", "message", "category_id", "projected_added"})
WARNING_FIELDS = frozenset({"code", "message"})
SEARCH_FIELDS = frozenset({"complete", "optimality_proven", "evaluated_subsets", "limit_reason"})
PROOF_FIELDS = frozenset({"kind", "evaluated_subsets"})
SCORE_SUMMARY_FIELDS = frozenset({
    "baseline_by_category", "projected_by_category", "gain_by_category",
    "baseline_total", "projected_total", "gain_total",
    "remaining_by_category", "remaining_total",
})

_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")
_PLAN_VERSION_PATTERN = re.compile(re.escape(PLAN_VERSION_PREFIX) + r"[0-9a-f]{16}")

Interval = tuple[datetime, datetime]


class ContractError(ValueError):
    """Contract violation; path/problem describe structure, never raw data."""

    def __init__(self, path: str, problem: str) -> None:
        self.path = path
        self.problem = problem
        super().__init__(f"{path}: {problem}")


def require(condition: bool, path: str, problem: str) -> None:
    if not condition:
        raise ContractError(path, problem)


def exact_object(value: Any, fields: Iterable[str], path: str) -> dict[str, Any]:
    require(isinstance(value, dict), path, "must be an object")
    require(set(value) == set(fields), path, "missing required or unexpected fields")
    return value


def non_empty_string(value: Any, path: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), path, "must be a non-empty string")
    return value


def json_number(value: Any, path: str) -> int | float:
    """A finite, non-negative JSON number; booleans are rejected."""
    require(type(value) in (int, float), path, "must be a JSON number, not a boolean")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite and value >= 0, path, "must be finite and non-negative")
    return value


def finite_sum(values: Iterable[int | float], path: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError):
        raise ContractError(path, "aggregate exceeds finite numeric range") from None
    require(math.isfinite(result), path, "aggregate must be finite")
    return result


def within_tolerance(actual: int | float, expected: int | float) -> bool:
    return math.isclose(actual, expected, rel_tol=0, abs_tol=ABS_TOLERANCE)


def equal_within_tolerance(actual: int | float, expected: int | float, path: str) -> None:
    require(within_tolerance(actual, expected), path, "inconsistent arithmetic")


def copy_json(value: Any) -> Any:
    """Fast deep copy for JSON-shaped data (dicts, lists and scalars)."""
    if isinstance(value, dict):
        return {key: copy_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [copy_json(item) for item in value]
    return value


def remaining_gap(target: int | float, projected: int | float) -> int | float:
    """Section 6 gap ``max(0, target - projected)``; float noise counts as met."""
    gap = target - projected
    return 0 if gap <= ABS_TOLERANCE else gap


def timestamp(value: Any, path: str) -> datetime:
    """An ISO 8601 timestamp with an explicit offset, parsed to an aware datetime."""
    non_empty_string(value, path)
    require(
        _TIMESTAMP_PATTERN.fullmatch(value) is not None,
        path, "must be an ISO 8601 timestamp with an explicit offset",
    )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError(path, "invalid timestamp") from None


def reason_code(value: Any, path: str) -> str:
    non_empty_string(value, path)
    require(_CODE_PATTERN.fullmatch(value) is not None, path, "must be an uppercase reason code")
    return value


def id_list(value: Any, path: str, *, ordered: bool = False) -> list[str]:
    """An array of unique non-empty string IDs, optionally sorted."""
    require(isinstance(value, list), path, "must be an array")
    for identifier in value:
        non_empty_string(identifier, path + "[]")
    require(len(value) == len(set(value)), path, "IDs must be unique")
    if ordered:
        require(value == sorted(value), path, "IDs must be lexicographically sorted")
    return value


def score_map(value: Any, path: str) -> dict[str, int | float]:
    require(isinstance(value, dict) and bool(value), path, "must be a non-empty score map")
    for key, score in value.items():
        non_empty_string(key, path + ".category_id")
        json_number(score, path + ".score")
    return value


def validate_context(value: Any, path: str) -> dict[str, Any]:
    """Section 4.2 context: exact fields, timezone, and a coherent window."""
    context = exact_object(value, CONTEXT_FIELDS, path)
    for name, item in context.items():
        non_empty_string(item, f"{path}.{name}")
    require(context["timezone"] == TIMEZONE, path + ".timezone", "unsupported timezone")
    start, end, as_of = (
        timestamp(context[key], f"{path}.{key}")
        for key in ("window_start", "window_end", "as_of")
    )
    require(start < end and as_of <= end, path, "invalid planning window or as_of")
    return context


def validate_baseline(value: Any, path: str) -> dict[str, Any]:
    """Section 4.2 baseline invariants: matching categories, caps, capped total."""
    baseline = exact_object(value, BASELINE_FIELDS, path)
    scores = score_map(baseline["category_scores"], path + ".category_scores")
    caps = score_map(baseline["category_caps"], path + ".category_caps")
    require(scores.keys() == caps.keys(), path, "score and cap categories must match")
    require(all(scores[key] <= caps[key] for key in scores), path, "category score exceeds its cap")
    total = json_number(baseline["total_score"], path + ".total_score")
    cap = json_number(baseline["max_total_score"], path + ".max_total_score")
    require(total <= cap, path + ".total_score", "exceeds total cap")
    equal_within_tolerance(total, min(finite_sum(scores.values(), path), cap), path + ".total_score")
    id_list(baseline["included_activity_ids"], path + ".included_activity_ids")
    return baseline


# --- Intervals and schedules (sections 3 and 4) ---------------------------------

@dataclass(frozen=True)
class Schedule:
    """A normalized section-4.2 schedule with parsed instants."""

    type: ScheduleType
    fixed_blocks: tuple[Interval, ...] = ()
    window_start: datetime | None = None
    window_end: datetime | None = None
    duration_minutes: int | None = None

    @property
    def planned_minutes(self) -> float:
        """Minutes counted by ``max_duration_minutes`` and the ranking."""
        if self.type is ScheduleType.FIXED:
            return math.fsum(interval_minutes(block) for block in self.fixed_blocks)
        assert self.duration_minutes is not None
        return float(self.duration_minutes)


@dataclass(frozen=True)
class Participation:
    registration: RegistrationStatus
    progress: ProgressStatus


@dataclass(frozen=True)
class PreviousPlan:
    """A validated section-7 previous_plan; blocks are keyed by activity ID."""

    plan_version: str
    based_on: Mapping[str, Any]
    blocks: Mapping[str, tuple[Interval, ...]]


def interval_minutes(interval: Interval) -> float:
    return (interval[1] - interval[0]).total_seconds() / 60


def overlaps(left: Interval, right: Interval) -> bool:
    """Half-open intervals: ``[.., 15:00)`` and ``[15:00, ..)`` do not overlap."""
    return left[0] < right[1] and right[0] < left[1]


def inside(block: Interval, outer: Interval) -> bool:
    return outer[0] <= block[0] and block[1] <= outer[1]


def inside_one(block: Interval, intervals: Iterable[Interval]) -> bool:
    """Whether a single interval contains the whole block."""
    return any(inside(block, outer) for outer in intervals)


def same_instants(left: Sequence[Interval], right: Sequence[Interval]) -> bool:
    """Block lists that denote the same instants, whatever their offsets."""
    return len(left) == len(right) and all(a == b for a, b in zip(left, right))


def merge_intervals(intervals: Iterable[Interval]) -> tuple[Interval, ...]:
    """Sort and merge overlapping or adjoining intervals."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return tuple(merged)


def usable_window(schedule: Schedule, window_start: datetime, window_end: datetime, as_of: datetime) -> Interval | None:
    """Section 6.3 usable window of a FLEXIBLE_WINDOW schedule, or None if empty."""
    assert schedule.window_start is not None and schedule.window_end is not None
    start = max(schedule.window_start, window_start, as_of)
    end = min(schedule.window_end, window_end)
    return (start, end) if start < end else None


def valid_flexible_blocks(
    schedule: Schedule,
    blocks: Sequence[Interval],
    available: Sequence[Interval],
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
) -> bool:
    """One sitting of exactly ``duration_minutes`` inside the usable window and one available interval."""
    if schedule.type is not ScheduleType.FLEXIBLE_WINDOW or len(blocks) != 1:
        return False
    block = blocks[0]
    usable = usable_window(schedule, window_start, window_end, as_of)
    return (
        usable is not None
        and block[1] - block[0] == timedelta(minutes=schedule.duration_minutes or 0)
        and inside(block, usable)
        and inside_one(block, available)
    )


def feasible_alone(
    schedule: Schedule,
    available: Sequence[Interval],
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
) -> bool:
    """Section 6.3 time checks for one activity on its own (FEASIBLE implies these)."""
    if schedule.type is ScheduleType.FIXED:
        return (
            schedule.fixed_blocks[0][0] >= as_of
            and all(window_start <= start and end <= window_end for start, end in schedule.fixed_blocks)
            and all(inside_one(block, available) for block in schedule.fixed_blocks)
        )
    usable = usable_window(schedule, window_start, window_end, as_of)
    if usable is None:
        return False
    duration = timedelta(minutes=schedule.duration_minutes or 0)
    return any(min(usable[1], end) - max(usable[0], start) >= duration for start, end in available)


def validate_interval(value: Any, path: str) -> Interval:
    """Section 4.1 interval ``{start, end}`` with ``start < end``."""
    interval = exact_object(value, INTERVAL_FIELDS, path)
    start = timestamp(interval["start"], path + ".start")
    end = timestamp(interval["end"], path + ".end")
    require(start < end, path, "start must be before end")
    return start, end


def validate_intervals(value: Any, path: str) -> tuple[Interval, ...]:
    """An array of intervals in any order, returned merged and sorted."""
    require(isinstance(value, list), path, "must be an array")
    return merge_intervals(validate_interval(item, f"{path}[{index}]") for index, item in enumerate(value))


def validate_blocks(value: Any, path: str) -> tuple[Interval, ...]:
    """A non-empty array of intervals, sorted by start and non-overlapping."""
    require(isinstance(value, list) and bool(value), path, "must be a non-empty array")
    blocks = tuple(validate_interval(item, f"{path}[{index}]") for index, item in enumerate(value))
    require(
        all(previous[1] <= current[0] for previous, current in zip(blocks, blocks[1:])),
        path, "blocks must be sorted by start and non-overlapping",
    )
    return blocks


def validate_schedule(value: Any, path: str) -> Schedule:
    """Section 4.2 normalized schedule: FIXED or FLEXIBLE_WINDOW."""
    require(isinstance(value, dict), path, "must be an object")
    kind = value.get("type")
    if kind == ScheduleType.FIXED.value:
        exact_object(value, FIXED_SCHEDULE_FIELDS, path)
        return Schedule(ScheduleType.FIXED, fixed_blocks=validate_blocks(value["fixed_blocks"], path + ".fixed_blocks"))
    require(kind == ScheduleType.FLEXIBLE_WINDOW.value, path + ".type", "unsupported schedule type")
    exact_object(value, FLEXIBLE_SCHEDULE_FIELDS, path)
    start = timestamp(value["window_start"], path + ".window_start")
    end = timestamp(value["window_end"], path + ".window_end")
    require(start < end, path, "window_start must be before window_end")
    duration = value["duration_minutes"]
    require(type(duration) is int and duration >= 1, path + ".duration_minutes", "must be a positive integer")
    require(timedelta(minutes=duration) <= end - start, path + ".duration_minutes", "must not exceed the window length")
    return Schedule(ScheduleType.FLEXIBLE_WINDOW, window_start=start, window_end=end, duration_minutes=duration)


def validate_participation(value: Any, path: str) -> Participation:
    """Section 4.3 participation state."""
    participation = exact_object(value, PARTICIPATION_FIELDS, path)
    try:
        registration = RegistrationStatus(participation["registration"])
    except (ValueError, TypeError):
        raise ContractError(path + ".registration", "unsupported registration status") from None
    try:
        progress = ProgressStatus(participation["progress"])
    except (ValueError, TypeError):
        raise ContractError(path + ".progress", "unsupported progress status") from None
    return Participation(registration, progress)


def validate_planned_activity(value: Any, path: str) -> tuple[str, tuple[Interval, ...]]:
    """Section 4.4 planned_activity ``{activity_id, scheduled_blocks}``."""
    planned = exact_object(value, PLANNED_ACTIVITY_FIELDS, path)
    activity_id = non_empty_string(planned["activity_id"], path + ".activity_id")
    return activity_id, validate_blocks(planned["scheduled_blocks"], path + ".scheduled_blocks")


def validate_plan_version(value: Any, path: str) -> str:
    require(
        isinstance(value, str) and _PLAN_VERSION_PATTERN.fullmatch(value) is not None,
        path, "must be a plan version string",
    )
    return value


def validate_based_on(value: Any, path: str) -> dict[str, Any]:
    """Section 10.2 based_on; previous_plan_version is a plan version or null."""
    based_on = exact_object(value, BASED_ON_FIELDS, path)
    for name in BASED_ON_FIELDS - {"previous_plan_version"}:
        non_empty_string(based_on[name], f"{path}.{name}")
    if based_on["previous_plan_version"] is not None:
        validate_plan_version(based_on["previous_plan_version"], path + ".previous_plan_version")
    return based_on


def validate_previous_plan(value: Any, path: str) -> PreviousPlan | None:
    """Section 7 previous_plan: null, or the plan currently in use."""
    if value is None:
        return None
    plan = exact_object(value, PREVIOUS_PLAN_FIELDS, path)
    version = validate_plan_version(plan["plan_version"], path + ".plan_version")
    based_on = validate_based_on(plan["based_on"], path + ".based_on")
    selected = plan["selected_activities"]
    require(isinstance(selected, list), path + ".selected_activities", "must be an array")
    blocks: dict[str, tuple[Interval, ...]] = {}
    for index, item in enumerate(selected):
        activity_id, planned = validate_planned_activity(item, f"{path}.selected_activities[{index}]")
        require(activity_id not in blocks, path + ".selected_activities", "activity IDs must be unique")
        blocks[activity_id] = planned
    return PreviousPlan(version, based_on, blocks)


def validate_keep_requests(value: Any, previous_plan: PreviousPlan | None, path: str) -> frozenset[str]:
    """Section 7 keep_requests: unique KEEP_TIME requests for previous-plan activities."""
    require(isinstance(value, list), path, "must be an array")
    kept: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        request = exact_object(item, KEEP_REQUEST_FIELDS, item_path)
        activity_id = non_empty_string(request["activity_id"], item_path + ".activity_id")
        require(request["mode"] == KeepMode.KEEP_TIME.value, item_path + ".mode", "unsupported keep mode")
        require(activity_id not in kept, path, "keep requests must be unique")
        require(
            previous_plan is not None and activity_id in previous_plan.blocks,
            item_path + ".activity_id", "must reference an activity of previous_plan",
        )
        kept.add(activity_id)
    return frozenset(kept)


# --- Scoring and plan identity (sections 10.1 and 10.2) ------------------------

def attribution_order(first_starts: Mapping[str, datetime]) -> list[str]:
    """Section 10.1 order: first scheduled block start, then activity_id."""
    return sorted(first_starts, key=lambda activity_id: (first_starts[activity_id], activity_id))


def build_based_on(context: Mapping[str, Any], previous_plan_version: str | None) -> dict[str, Any]:
    """Section 10.2 based_on for a planning context."""
    return {
        "calendar_version": context["calendar_version"],
        "dataset_version": context["dataset_version"],
        "ruleset_version": context["ruleset_version"],
        "baseline_ref": context["baseline_ref"],
        "previous_plan_version": previous_plan_version,
    }


def plan_version(based_on: Mapping[str, Any], selected: Iterable[tuple[str, Sequence[Mapping[str, str]]]]) -> str:
    """Section 10.2 plan_version over based_on and the planned blocks.

    Activities are sorted by ID and blocks by start; timestamps are hashed
    exactly as emitted.
    """
    planned = [
        {
            "activity_id": activity_id,
            "scheduled_blocks": sorted(
                ({"start": block["start"], "end": block["end"]} for block in blocks),
                key=lambda block: timestamp(block["start"], "scheduled_blocks[].start"),
            ),
        }
        for activity_id, blocks in sorted(selected, key=lambda item: item[0])
    ]
    payload = {"based_on": dict(based_on), "selected_activities": planned}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return PLAN_VERSION_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def validate_score_request(request: Any, path: str = "request") -> None:
    """Section 10.1 score_request: section 5.1 plus ``attribution_order``."""
    exact_object(request, SCORE_REQUEST_FIELDS, path)
    require(request["contract_version"] == CONTRACT_VERSION, path + ".contract_version", "unsupported version")
    non_empty_string(request["request_id"], path + ".request_id")
    validate_context(request["context"], path + ".context")
    baseline = validate_baseline(request["baseline"], path + ".baseline")
    selected = id_list(request["selected_activity_ids"], path + ".selected_activity_ids", ordered=True)
    require(
        set(baseline["included_activity_ids"]).isdisjoint(selected),
        path + ".selected_activity_ids", "contains an already-counted activity",
    )
    order = id_list(request["attribution_order"], path + ".attribution_order")
    require(sorted(order) == selected, path + ".attribution_order", "must be a permutation of selected_activity_ids")


def validate_score_response(
    response: Any,
    request: Mapping[str, Any],
    *,
    allowed_statuses: Iterable[str],
    path: str = "response",
) -> None:
    """Section 5.2 score_response checked against an already-valid request."""
    exact_object(response, SCORE_RESPONSE_FIELDS, path)
    for key in ("contract_version", "request_id", "context", "selected_activity_ids"):
        require(response[key] == request[key], f"{path}.{key}", "does not match the request")
    require(response["mode"] == DEMO_MODE, path + ".mode", "must remain DEMO_ONLY")
    require(response["official_award_verified"] is False, path + ".official_award_verified", "must be false")
    status = response["evaluation_status"]
    require(isinstance(status, str) and status in set(allowed_statuses), path + ".evaluation_status", "unsupported status")
    errors = response["errors"]
    require(isinstance(errors, list), path + ".errors", "must be an array")
    selected = request["selected_activity_ids"]
    for issue in errors:
        exact_object(issue, ISSUE_FIELDS, path + ".errors[]")
        reason_code(issue["code"], path + ".errors[].code")
        non_empty_string(issue["message"], path + ".errors[].message")
        activity_id = issue["activity_id"]
        require(
            activity_id is None or (isinstance(activity_id, str) and activity_id in selected),
            path + ".errors[].activity_id", "must reference a selected activity or be null",
        )
    if status != EvaluationStatus.OK.value:
        require(response["result"] is None and bool(errors), path, "non-OK results require null result and at least one error")
        return
    require(not errors, path + ".errors", "OK responses must not contain errors")
    _validate_score_result(response["result"], request, path + ".result")


def _validate_score_result(value: Any, request: Mapping[str, Any], path: str) -> None:
    result = exact_object(value, SCORE_RESULT_FIELDS, path)
    after = score_map(result["category_after"], path + ".category_after")
    gain = score_map(result["category_gain"], path + ".category_gain")
    baseline = request["baseline"]
    before, caps = baseline["category_scores"], baseline["category_caps"]
    require(after.keys() == gain.keys() == before.keys(), path, "categories must exactly match the baseline")
    for category in before:
        require(before[category] <= after[category] <= caps[category], path + ".category_after", "category score decreased or exceeds its cap")
        equal_within_tolerance(gain[category], after[category] - before[category], path + ".category_gain")
    total_after = json_number(result["total_after"], path + ".total_after")
    total_gain = json_number(result["total_gain"], path + ".total_gain")
    require(baseline["total_score"] <= total_after <= baseline["max_total_score"], path + ".total_after", "total decreased or exceeds its cap")
    equal_within_tolerance(total_after, min(finite_sum(after.values(), path), baseline["max_total_score"]), path + ".total_after")
    equal_within_tolerance(total_gain, total_after - baseline["total_score"], path + ".total_gain")
    contributions = result["contributions"]
    require(isinstance(contributions, list), path + ".contributions", "must be an array")
    selected = request["selected_activity_ids"]
    seen: set[str] = set()
    per_category: dict[str, list[int | float]] = {category: [] for category in before}
    for item in contributions:
        exact_object(item, CONTRIBUTION_FIELDS, path + ".contributions[]")
        activity_id = non_empty_string(item["activity_id"], path + ".contributions[].activity_id")
        require(activity_id in selected and activity_id not in seen, path + ".contributions", "must cover each selected activity exactly once")
        seen.add(activity_id)
        category = non_empty_string(item["category_id"], path + ".contributions[].category_id")
        require(category in before, path + ".contributions[].category_id", "unknown category")
        non_empty_string(item["rule_id"], path + ".contributions[].rule_id")
        per_category[category].append(json_number(item["projected_added"], path + ".contributions[].projected_added"))
    require(seen == set(selected), path + ".contributions", "missing selected activities")
    for category in before:
        equal_within_tolerance(finite_sum(per_category[category], path + ".contributions"), gain[category], path + ".contributions")
    if not selected:
        require(
            after == before and all(value == 0 for value in gain.values())
            and total_after == baseline["total_score"] and total_gain == 0,
            path, "the empty set must leave the baseline unchanged",
        )
