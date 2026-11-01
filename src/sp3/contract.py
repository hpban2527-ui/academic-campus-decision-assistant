
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any

CONTRACT_VERSION = "sp3-planner/0.1"
TIMEZONE = "Asia/Ho_Chi_Minh"
ABS_TOLERANCE = 1e-9


class PlannerStatus(str, Enum):
    ALREADY_MET = "ALREADY_MET"
    TARGET_MET = "TARGET_MET"
    PARTIAL = "PARTIAL"
    NO_FEASIBLE_CANDIDATES = "NO_FEASIBLE_CANDIDATES"
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
    """Declared in the order the contract applies them (section 7.1)."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_FEASIBLE = "NOT_FEASIBLE"
    ALREADY_COUNTED = "ALREADY_COUNTED"
    CONFLICT = "CONFLICT"
    LIMIT = "LIMIT"
    LOWER_PRIORITY = "LOWER_PRIORITY"


class WarningCode(str, Enum):
    DEMO_ONLY = "DEMO_ONLY"
    TRAVEL_NOT_MODELED = "TRAVEL_NOT_MODELED"
    PENDING_CANDIDATES = "PENDING_CANDIDATES"
    SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"


class LimitReason(str, Enum):
    EVALUATION_LIMIT = "EVALUATION_LIMIT"
    ALREADY_MET = "ALREADY_MET"
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


DEMO_MODE = "DEMO_ONLY"
ALLOWED_DOMAINS = frozenset({"academic", "volunteer", "culture_sports", "skills", "career", "other"})
ALLOWED_MODES = frozenset({"online", "offline", "hybrid"})
# Section 4.3 lists these as standard. Upstream may add codes (for example
# WINDOW_ENDED), so validators check the code format, not membership.
STANDARD_FEASIBILITY_REASON_CODES = frozenset({
    "OUTSIDE_WINDOW", "OUTSIDE_AVAILABILITY", "DEADLINE_PASSED", "ALREADY_STARTED",
    "INELIGIBLE", "MISSING_SCHEDULE", "MISSING_DEADLINE", "MISSING_ELIGIBILITY",
    "NEEDS_SOURCE_REVIEW", "TERM_UNVERIFIED", "MISSING_SCORE_BINDING", "UNSUPPORTED_SCHEDULE",
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
PLANNER_INPUT_FIELDS = frozenset({
    "contract_version", "request_id", "context", "baseline", "goals",
    "preferences", "limits", "candidates", "conflict_pairs",
})
CANDIDATE_FIELDS = frozenset({"activity", "score_binding_ref", "feasibility"})
FEASIBILITY_FIELDS = frozenset({"status", "reason_codes"})
GOALS_FIELDS = frozenset({"total_target", "category_targets"})
PREFERENCES_FIELDS = frozenset({"preferred_domains", "preferred_modes"})
LIMITS_FIELDS = frozenset({"max_activities", "max_duration_minutes"})
SCORE_REQUEST_FIELDS = frozenset({
    "contract_version", "request_id", "context", "baseline", "selected_activity_ids",
})
SCORE_RESPONSE_FIELDS = (SCORE_REQUEST_FIELDS - {"baseline"}) | {
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
})
SELECTED_ACTIVITY_FIELDS = frozenset({"activity_id", "title", "start", "end", "reasons"})
EXCLUDED_CANDIDATE_FIELDS = frozenset({"activity_id", "code", "message"})
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


def validate_score_request(request: Any, path: str = "request") -> None:
    """Section 5.1 score_request."""
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
