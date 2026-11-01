"""Plan selection for sp3-planner/0.1 (contract sections 4.4, 6, 7 and 8).

Usage: ``build_plan(planner_input, ScorerAdapter(backend).score_plan)``.

The planner validates planner_input, scores the empty set, returns ALREADY_MET
when the baseline meets every target, classifies candidates, searches valid
subsets in a deterministic order, and explains the best-ranked plan. Every
subset score comes from the injected whole-set scorer; the planner never sums
single-activity scores, invents points, or treats a scorer failure as zero.

Planning is pure: inputs are never mutated, no global state is kept, and the
only clock is ``context.as_of``. Results stay DEMO_ONLY and unverified.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Any

from sp3.contract import (
    ABS_TOLERANCE,
    ACTIVITY_FIELDS,
    ALLOWED_DOMAINS,
    ALLOWED_MODES,
    CANDIDATE_FIELDS,
    CONTRACT_VERSION,
    DEMO_MODE,
    FEASIBILITY_FIELDS,
    GOALS_FIELDS,
    LIMITS_FIELDS,
    PLANNER_INPUT_FIELDS,
    PREFERENCES_FIELDS,
    ContractError,
    EvaluationStatus,
    ExclusionCode,
    FeasibilityConclusion,
    FeasibilityStatus,
    LimitReason,
    PlannerStatus,
    ProofKind,
    ReasonCode,
    WarningCode,
    copy_json,
    exact_object,
    json_number,
    non_empty_string,
    reason_code,
    remaining_gap,
    require,
    timestamp,
    validate_baseline,
    validate_context,
    validate_score_response,
)

__all__ = ["DEFAULT_MAX_EVALUATIONS", "ScorePlan", "build_plan", "planning_duration_minutes"]

DEFAULT_MAX_EVALUATIONS = 4096

ScorePlan = Callable[[dict[str, Any]], dict[str, Any]]

_SCORER_STATUSES = tuple(status.value for status in EvaluationStatus)


@dataclass(frozen=True)
class _Candidate:
    activity_id: str
    title: str
    domain: str | None
    mode: str
    start_text: str | None
    end_text: str | None
    start: datetime | None
    end: datetime | None
    status: FeasibilityStatus
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class _Goals:
    total_target: int | float | None
    category_targets: tuple[tuple[str, int | float], ...]


@dataclass(frozen=True)
class _Preferences:
    domains: frozenset[str]
    modes: frozenset[str]


@dataclass(frozen=True)
class _Limits:
    max_activities: int | None
    max_duration_minutes: int | float | None


@dataclass(frozen=True)
class _PlannerInput:
    request_id: str
    context: Mapping[str, Any]
    baseline: Mapping[str, Any]
    goals: _Goals
    preferences: _Preferences
    limits: _Limits
    candidates: tuple[_Candidate, ...]
    by_id: Mapping[str, _Candidate]
    conflicts: frozenset[frozenset[str]]
    included: frozenset[str]


@dataclass(frozen=True)
class _Evaluation:
    activity_ids: tuple[str, ...]
    result: Mapping[str, Any]
    rank: tuple[Any, ...]
    meets_targets: bool


class _SearchStop(Enum):
    EXHAUSTED = "EXHAUSTED"
    DOMINATED = "DOMINATED"
    BUDGET = "BUDGET"


@dataclass(frozen=True)
class _SearchOutcome:
    best: _Evaluation
    stop: _SearchStop


class _ScorerFailure(Exception):
    """Internal control flow: a scorer call did not return an OK result."""

    def __init__(self, status: PlannerStatus, errors: list[dict[str, Any]]) -> None:
        super().__init__(status.value)
        self.status = status
        self.errors = errors


class _Scorer:
    """Builds score requests, validates responses, and counts evaluations."""

    def __init__(self, plan: _PlannerInput, score_plan: ScorePlan) -> None:
        self._score_plan = score_plan
        # Private reference copy; each call sends a fresh copy the scorer may mutate.
        self._template = {
            "contract_version": CONTRACT_VERSION,
            "request_id": plan.request_id,
            "context": copy_json(dict(plan.context)),
            "baseline": copy_json(dict(plan.baseline)),
        }
        self.evaluated = 0

    def evaluate(self, activity_ids: tuple[str, ...]) -> Mapping[str, Any]:
        request = {**copy_json(self._template), "selected_activity_ids": list(activity_ids)}
        expected = {**self._template, "selected_activity_ids": list(activity_ids)}
        self.evaluated += 1
        try:
            raw_response = self._score_plan(request)
        except Exception:
            # Exception text may contain private data; never forward it.
            raise _ScorerFailure(PlannerStatus.ERROR, [_issue(
                "SP2_CALL_FAILED", "The projected scorer raised an error; check scorer diagnostics.",
            )]) from None
        try:
            response = copy_json(raw_response)
            validate_score_response(response, expected, allowed_statuses=_SCORER_STATUSES)
        except ContractError as error:
            raise _ScorerFailure(PlannerStatus.ERROR, [_issue("SP2_INVALID_RESPONSE", str(error))]) from None
        except Exception:
            raise _ScorerFailure(PlannerStatus.ERROR, [_issue(
                "SP2_INVALID_RESPONSE", "The projected scorer returned an unreadable response.",
            )]) from None
        status = response["evaluation_status"]
        if status == EvaluationStatus.NEEDS_REVIEW.value:
            raise _ScorerFailure(PlannerStatus.NEEDS_DATA, response["errors"])
        if status == EvaluationStatus.ERROR.value:
            raise _ScorerFailure(PlannerStatus.ERROR, response["errors"])
        return response["result"]


def build_plan(
    planner_input: Mapping[str, Any],
    score_plan: ScorePlan,
    *,
    max_evaluations: int = DEFAULT_MAX_EVALUATIONS,
) -> dict[str, Any]:
    """Return the section-7 planner_output for ``planner_input``.

    ``score_plan`` maps a score_request to a score_response (section 5).
    ``max_evaluations`` counts unique scored subsets, including the empty set.
    Raises ContractError when contract_version, request_id or context are
    unusable, because no trustworthy output envelope can be built; every other
    invalid input returns ERROR with limit_reason=INVALID_INPUT.
    """
    if not callable(score_plan):
        raise TypeError("score_plan must be callable")
    if type(max_evaluations) is not int or max_evaluations < 1:
        raise ValueError("max_evaluations must be a positive integer")
    _validate_envelope(planner_input)
    try:
        plan = _parse_input(planner_input)
    except ContractError as error:
        return _invalid_input_output(planner_input, error)

    scorer = _Scorer(plan, score_plan)
    try:
        empty = _evaluate(plan, scorer, ())
        if empty.meets_targets:
            return _already_met_output(plan, empty)
        eligible = tuple(c for c in plan.candidates if _pre_search_exclusion(c, plan.included) is None)
        if not eligible:
            return _scored_output(plan, _SearchOutcome(empty, _SearchStop.EXHAUSTED), scorer.evaluated)
        outcome = _search(plan, eligible, empty, scorer, max_evaluations)
    except _ScorerFailure as failure:
        return _scorer_failure_output(plan, failure, scorer.evaluated)
    return _scored_output(plan, outcome, scorer.evaluated)


def planning_duration_minutes(activity: _Candidate) -> float:
    """Minutes an activity consumes for ranking and the duration limit.

    v0.1 schedules are one fixed interval, so this is ``end - start``.
    Flexible schedules (v0.2) should change only this function.
    """
    assert activity.start is not None and activity.end is not None
    return (activity.end - activity.start).total_seconds() / 60


# --- Validation -----------------------------------------------------------

def _validate_envelope(planner_input: Any) -> None:
    require(isinstance(planner_input, dict), "planner_input", "must be an object")
    for field in ("contract_version", "request_id", "context"):
        require(field in planner_input, "planner_input", "missing required or unexpected fields")
    require(planner_input["contract_version"] == CONTRACT_VERSION, "planner_input.contract_version", "unsupported version")
    non_empty_string(planner_input["request_id"], "planner_input.request_id")
    validate_context(planner_input["context"], "planner_input.context")


def _parse_input(planner_input: Mapping[str, Any]) -> _PlannerInput:
    exact_object(planner_input, PLANNER_INPUT_FIELDS, "planner_input")
    context = deepcopy(planner_input["context"])
    window = tuple(timestamp(context[key], "planner_input.context." + key) for key in ("window_start", "window_end", "as_of"))
    baseline = deepcopy(validate_baseline(planner_input["baseline"], "planner_input.baseline"))
    goals = _parse_goals(planner_input["goals"], baseline["category_scores"])
    preferences = _parse_preferences(planner_input["preferences"])
    limits = _parse_limits(planner_input["limits"])
    require(isinstance(planner_input["candidates"], list), "planner_input.candidates", "must be an array")
    candidates = [
        _parse_candidate(entry, f"planner_input.candidates[{index}]", window)
        for index, entry in enumerate(planner_input["candidates"])
    ]
    ids = [candidate.activity_id for candidate in candidates]
    require(len(ids) == len(set(ids)), "planner_input.candidates", "activity IDs must be unique")
    conflicts = _parse_conflicts(planner_input["conflict_pairs"], set(ids))
    _check_conflict_coverage(candidates, conflicts)
    ordered = tuple(sorted(candidates, key=lambda c: c.activity_id))
    return _PlannerInput(
        request_id=planner_input["request_id"],
        context=context,
        baseline=baseline,
        goals=goals,
        preferences=preferences,
        limits=limits,
        candidates=ordered,
        by_id={c.activity_id: c for c in ordered},
        conflicts=conflicts,
        included=frozenset(baseline["included_activity_ids"]),
    )


def _parse_goals(value: Any, categories: Mapping[str, Any]) -> _Goals:
    path = "planner_input.goals"
    goals = exact_object(value, GOALS_FIELDS, path)
    total = goals["total_target"]
    if total is not None:
        json_number(total, path + ".total_target")
    targets = goals["category_targets"]
    require(isinstance(targets, dict), path + ".category_targets", "must be an object")
    for category, target in targets.items():
        require(category in categories, path + ".category_targets", "category is not in the baseline")
        json_number(target, path + ".category_targets.target")
    require(total is not None or bool(targets), path, "at least one target is required")
    return _Goals(total, tuple(sorted(targets.items())))


def _parse_preferences(value: Any) -> _Preferences:
    path = "planner_input.preferences"
    preferences = exact_object(value, PREFERENCES_FIELDS, path)
    parsed = []
    for field, allowed in (("preferred_domains", ALLOWED_DOMAINS), ("preferred_modes", ALLOWED_MODES)):
        values = preferences[field]
        require(isinstance(values, list), f"{path}.{field}", "must be an array")
        require(all(isinstance(item, str) and item in allowed for item in values), f"{path}.{field}", "contains an unsupported value")
        require(len(values) == len(set(values)), f"{path}.{field}", "values must be unique")
        parsed.append(frozenset(values))
    return _Preferences(*parsed)


def _parse_limits(value: Any) -> _Limits:
    path = "planner_input.limits"
    limits = exact_object(value, LIMITS_FIELDS, path)
    count = limits["max_activities"]
    if count is not None:
        require(type(count) is int and count >= 0, path + ".max_activities", "must be a non-negative integer or null")
    duration = limits["max_duration_minutes"]
    if duration is not None:
        json_number(duration, path + ".max_duration_minutes")
    return _Limits(count, duration)


def _parse_candidate(entry: Any, path: str, window: tuple[datetime, ...]) -> _Candidate:
    exact_object(entry, CANDIDATE_FIELDS, path)
    activity = exact_object(entry["activity"], ACTIVITY_FIELDS, path + ".activity")
    activity_id = non_empty_string(activity["activity_id"], path + ".activity.activity_id")
    title = non_empty_string(activity["title"], path + ".activity.title")
    domain = activity["domain"]
    require(domain is None or domain in ALLOWED_DOMAINS, path + ".activity.domain", "unsupported domain")
    require(activity["mode"] in ALLOWED_MODES, path + ".activity.mode", "unsupported mode")
    start, end, deadline = (
        None if activity[key] is None else timestamp(activity[key], f"{path}.activity.{key}")
        for key in ("start", "end", "registration_deadline")
    )
    binding = entry["score_binding_ref"]
    if binding is not None:
        non_empty_string(binding, path + ".score_binding_ref")
    feasibility = exact_object(entry["feasibility"], FEASIBILITY_FIELDS, path + ".feasibility")
    try:
        status = FeasibilityStatus(feasibility["status"])
    except (ValueError, TypeError):
        raise ContractError(path + ".feasibility.status", "unsupported feasibility status") from None
    codes = feasibility["reason_codes"]
    require(isinstance(codes, list), path + ".feasibility.reason_codes", "must be an array")
    for code in codes:
        reason_code(code, path + ".feasibility.reason_codes[]")
    require(len(codes) == len(set(codes)), path + ".feasibility.reason_codes", "codes must be unique")
    if status is FeasibilityStatus.FEASIBLE:
        require(not codes, path + ".feasibility.reason_codes", "must be empty for FEASIBLE")
        require(binding is not None, path + ".score_binding_ref", "FEASIBLE requires a score binding")
        _check_feasible_schedule(start, end, deadline, window, path + ".activity")
    else:
        require(bool(codes), path + ".feasibility.reason_codes", "non-FEASIBLE requires a reason code")
    return _Candidate(
        activity_id=activity_id,
        title=title,
        domain=domain,
        mode=activity["mode"],
        start_text=activity["start"],
        end_text=activity["end"],
        start=start,
        end=end,
        status=status,
        reason_codes=tuple(codes),
    )


def _check_feasible_schedule(
    start: datetime | None,
    end: datetime | None,
    deadline: datetime | None,
    window: tuple[datetime, ...],
    path: str,
) -> None:
    """Section 4.3 FEASIBLE invariants for one fixed interval (v0.1)."""
    window_start, window_end, as_of = window
    require(start is not None and end is not None, path, "FEASIBLE requires a complete schedule")
    require(start < end, path, "FEASIBLE requires start before end")
    require(as_of <= start and window_start <= start and end <= window_end, path, "FEASIBLE schedule is outside the planning window")
    require(deadline is not None and as_of < deadline, path + ".registration_deadline", "FEASIBLE requires an open registration deadline")


def _parse_conflicts(value: Any, ids: set[str]) -> frozenset[frozenset[str]]:
    path = "planner_input.conflict_pairs"
    require(isinstance(value, list), path, "must be an array")
    pairs: set[frozenset[str]] = set()
    for pair in value:
        require(isinstance(pair, list) and len(pair) == 2, path + "[]", "must be a pair of activity IDs")
        left, right = (non_empty_string(item, path + "[][]") for item in pair)
        require(left < right, path + "[]", "must contain two distinct IDs in lexicographic order")
        require(left in ids and right in ids, path + "[]", "references an unknown candidate")
        key = frozenset(pair)
        require(key not in pairs, path, "pairs must not repeat")
        pairs.add(key)
    return frozenset(pairs)


def _check_conflict_coverage(candidates: Sequence[_Candidate], conflicts: frozenset[frozenset[str]]) -> None:
    """Section 4.3: overlapping FEASIBLE fixed intervals must be listed as conflicts."""
    feasible = [c for c in candidates if c.status is FeasibilityStatus.FEASIBLE]
    for index, left in enumerate(feasible):
        for right in feasible[index + 1:]:
            if _overlaps(left, right):
                require(
                    frozenset((left.activity_id, right.activity_id)) in conflicts,
                    "planner_input.conflict_pairs", "an overlapping FEASIBLE pair is missing",
                )


def _overlaps(left: _Candidate, right: _Candidate) -> bool:
    assert left.start and left.end and right.start and right.end
    return left.start < right.end and right.start < left.end


# --- Scoring and ranking --------------------------------------------------

def _evaluate(plan: _PlannerInput, scorer: _Scorer, activity_ids: tuple[str, ...]) -> _Evaluation:
    result = scorer.evaluate(activity_ids)
    rank = _rank(plan, activity_ids, result)
    return _Evaluation(activity_ids, result, rank, meets_targets=rank[0] == 0 and rank[1] == 0)


def _rank(plan: _PlannerInput, activity_ids: tuple[str, ...], result: Mapping[str, Any]) -> tuple[Any, ...]:
    """Section 6 ranking tuple; lower is better."""
    after = result["category_after"]
    category_gap = math.fsum(remaining_gap(target, after[category]) for category, target in plan.goals.category_targets)
    total_target = plan.goals.total_target
    total_gap = 0 if total_target is None else remaining_gap(total_target, result["total_after"])
    selected = [plan.by_id[activity_id] for activity_id in activity_ids]
    preference = sum(len(_preference_matches(plan.preferences, c)) for c in selected)
    duration = math.fsum(planning_duration_minutes(c) for c in selected)
    return (category_gap, total_gap, len(activity_ids), -preference, duration, activity_ids)


def _preference_matches(preferences: _Preferences, candidate: _Candidate) -> list[tuple[str, str]]:
    matches = []
    if candidate.domain is not None and candidate.domain in preferences.domains:
        matches.append(("domain", candidate.domain))
    if candidate.mode in preferences.modes:
        matches.append(("mode", candidate.mode))
    return matches


# --- Search ---------------------------------------------------------------

def _search(
    plan: _PlannerInput,
    eligible: tuple[_Candidate, ...],
    empty: _Evaluation,
    scorer: _Scorer,
    max_evaluations: int,
) -> _SearchOutcome:
    """Score valid subsets by increasing size, then lexicographic ID order.

    Dominance: the first two ranking components are gaps, which are never
    negative. A subset of size k that meets every target has gaps (0, 0), the
    minimum possible, so any larger subset is ranked behind it by the third
    component (activity count) whatever its scores. Once size k is finished,
    the best scored subset is therefore optimal over all valid subsets, and
    larger subsets are left unscored with optimality still proven.
    """
    best = empty
    met_size: int | None = None
    for activity_ids in _valid_subsets(eligible, plan.conflicts, plan.limits):
        if met_size is not None and len(activity_ids) > met_size:
            return _SearchOutcome(best, _SearchStop.DOMINATED)
        if scorer.evaluated >= max_evaluations:
            return _SearchOutcome(best, _SearchStop.BUDGET)
        evaluation = _evaluate(plan, scorer, activity_ids)
        if evaluation.rank < best.rank:
            best = evaluation
        if evaluation.meets_targets and met_size is None:
            met_size = len(activity_ids)
    return _SearchOutcome(best, _SearchStop.EXHAUSTED)


def _valid_subsets(
    eligible: tuple[_Candidate, ...],
    conflicts: frozenset[frozenset[str]],
    limits: _Limits,
) -> Iterator[tuple[str, ...]]:
    """Yield non-empty conflict-free subsets within both limits, deterministically.

    Valid subsets are closed under removal (durations are non-negative), so
    backtracking prunes a branch as soon as one addition is invalid, and no
    larger subset exists once a size produces none.
    """
    ids = [c.activity_id for c in eligible]
    durations = [planning_duration_minutes(c) for c in eligible]
    blocked = [
        {j for j, other in enumerate(ids) if frozenset((activity_id, other)) in conflicts}
        for activity_id in ids
    ]
    count = len(ids)
    largest = count if limits.max_activities is None else min(count, limits.max_activities)
    max_duration = limits.max_duration_minutes

    def extend(size: int, start: int, chosen: list[int], duration: float) -> Iterator[tuple[str, ...]]:
        if len(chosen) == size:
            yield tuple(ids[i] for i in chosen)
            return
        for index in range(start, count - (size - len(chosen)) + 1):
            if any(index in blocked[i] for i in chosen):
                continue
            total = duration + durations[index]
            if max_duration is not None and total > max_duration + ABS_TOLERANCE:
                continue
            chosen.append(index)
            yield from extend(size, index + 1, chosen, total)
            chosen.pop()

    for size in range(1, largest + 1):
        produced = False
        for subset in extend(size, 0, [], 0.0):
            produced = True
            yield subset
        if not produced:
            return


# --- Exclusions -----------------------------------------------------------

def _pre_search_exclusion(candidate: _Candidate, included: frozenset[str]) -> ExclusionCode | None:
    if candidate.status is FeasibilityStatus.NEEDS_REVIEW:
        return ExclusionCode.NEEDS_REVIEW
    if candidate.status is FeasibilityStatus.INFEASIBLE:
        return ExclusionCode.NOT_FEASIBLE
    if candidate.activity_id in included:
        return ExclusionCode.ALREADY_COUNTED
    return None


def _exclusion(plan: _PlannerInput, candidate: _Candidate, selected: Sequence[_Candidate], lower_priority_message: str) -> dict[str, Any]:
    code = _pre_search_exclusion(candidate, plan.included)
    if code is ExclusionCode.NEEDS_REVIEW:
        message = "Feasibility review is pending: " + ", ".join(candidate.reason_codes) + "."
    elif code is ExclusionCode.NOT_FEASIBLE:
        message = "Feasibility check failed: " + ", ".join(candidate.reason_codes) + "."
    elif code is ExclusionCode.ALREADY_COUNTED:
        message = "Already counted in the baseline."
    else:
        code, message = _post_search_exclusion(plan, candidate, selected, lower_priority_message)
    return {"activity_id": candidate.activity_id, "code": code.value, "message": message}


def _post_search_exclusion(
    plan: _PlannerInput,
    candidate: _Candidate,
    selected: Sequence[_Candidate],
    lower_priority_message: str,
) -> tuple[ExclusionCode, str]:
    conflicting = [s.activity_id for s in selected if frozenset((s.activity_id, candidate.activity_id)) in plan.conflicts]
    if conflicting:
        return ExclusionCode.CONFLICT, "Overlaps with selected activity " + ", ".join(conflicting) + "."
    limits = plan.limits
    if limits.max_activities is not None and len(selected) + 1 > limits.max_activities:
        return ExclusionCode.LIMIT, "Adding it would exceed the activity-count limit."
    if limits.max_duration_minutes is not None:
        duration = math.fsum(planning_duration_minutes(c) for c in (*selected, candidate))
        if duration > limits.max_duration_minutes + ABS_TOLERANCE:
            return ExclusionCode.LIMIT, "Adding it would exceed the total-duration limit."
    return ExclusionCode.LOWER_PRIORITY, lower_priority_message


# --- Output ---------------------------------------------------------------

def _issue(code: str, message: str, activity_id: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "activity_id": activity_id}


def _warning(code: WarningCode, message: str) -> dict[str, str]:
    return {"code": code.value, "message": message}


def _warnings(plan: _PlannerInput | None, search_incomplete_message: str | None = None) -> list[dict[str, str]]:
    warnings = [
        _warning(WarningCode.DEMO_ONLY, "Projected scores are demo estimates, not awarded or verified points."),
        _warning(WarningCode.TRAVEL_NOT_MODELED, "Travel time between activities is not modeled."),
    ]
    if plan is not None:
        pending = sum(1 for c in plan.candidates if c.status is FeasibilityStatus.NEEDS_REVIEW)
        if pending:
            warnings.append(_warning(WarningCode.PENDING_CANDIDATES, f"{pending} candidate(s) await feasibility review and were not considered."))
    if search_incomplete_message is not None:
        warnings.append(_warning(WarningCode.SEARCH_INCOMPLETE, search_incomplete_message))
    return warnings


def _search_block(complete: bool, optimality_proven: bool, evaluated: int, limit_reason: LimitReason | None) -> dict[str, Any]:
    return {
        "complete": complete,
        "optimality_proven": optimality_proven,
        "evaluated_subsets": evaluated,
        "limit_reason": None if limit_reason is None else limit_reason.value,
    }


def _envelope(
    request_id: str,
    context: Mapping[str, Any],
    *,
    status: PlannerStatus,
    selected: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    score_summary: dict[str, Any] | None,
    search: dict[str, Any],
    conclusion: FeasibilityConclusion,
    proof: dict[str, Any] | None,
    warnings: list[dict[str, str]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": request_id,
        "context": deepcopy(dict(context)),
        "status": status.value,
        "selected_activities": selected,
        "excluded_candidates": excluded,
        "score_summary": score_summary,
        "search": search,
        "feasibility_conclusion": conclusion.value,
        "proof": proof,
        "warnings": warnings,
        "errors": errors,
        "mode": DEMO_MODE,
        "official_award_verified": False,
    }


def _score_summary(plan: _PlannerInput, result: Mapping[str, Any]) -> dict[str, Any]:
    after = result["category_after"]
    total_target = plan.goals.total_target
    return {
        "baseline_by_category": deepcopy(dict(plan.baseline["category_scores"])),
        "projected_by_category": deepcopy(dict(after)),
        "gain_by_category": deepcopy(dict(result["category_gain"])),
        "baseline_total": plan.baseline["total_score"],
        "projected_total": result["total_after"],
        "gain_total": result["total_gain"],
        "remaining_by_category": {category: remaining_gap(target, after[category]) for category, target in plan.goals.category_targets},
        "remaining_total": None if total_target is None else remaining_gap(total_target, result["total_after"]),
    }


def _format_points(value: int | float) -> str:
    return f"{value:g}"


def _selected_entry(plan: _PlannerInput, candidate: _Candidate, result: Mapping[str, Any]) -> dict[str, Any]:
    reasons = [
        {
            "code": ReasonCode.GOAL_CONTRIBUTION.value,
            "message": f"Projected to add {_format_points(item['projected_added'])} point(s) to {item['category_id']} (demo estimate, not an awarded score).",
            "category_id": item["category_id"],
            "projected_added": item["projected_added"],
        }
        for item in result["contributions"]
        if item["activity_id"] == candidate.activity_id
    ]
    reasons.extend(
        {
            "code": ReasonCode.PREFERENCE_MATCH.value,
            "message": f"Matches preferred {dimension} {value}.",
            "category_id": None,
            "projected_added": None,
        }
        for dimension, value in _preference_matches(plan.preferences, candidate)
    )
    return {
        "activity_id": candidate.activity_id,
        "title": candidate.title,
        "start": candidate.start_text,
        "end": candidate.end_text,
        "reasons": reasons,
    }


def _plan_lists(plan: _PlannerInput, best: _Evaluation, lower_priority_message: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chosen = set(best.activity_ids)
    selected = sorted((c for c in plan.candidates if c.activity_id in chosen), key=lambda c: (c.start, c.activity_id))
    excluded = [
        _exclusion(plan, c, selected, lower_priority_message)
        for c in plan.candidates
        if c.activity_id not in chosen
    ]
    return [_selected_entry(plan, c, best.result) for c in selected], excluded


def _already_met_output(plan: _PlannerInput, empty: _Evaluation) -> dict[str, Any]:
    selected, excluded = _plan_lists(plan, empty, "Not needed: the baseline already meets every target.")
    return _envelope(
        plan.request_id, plan.context,
        status=PlannerStatus.ALREADY_MET,
        selected=selected,
        excluded=excluded,
        score_summary=_score_summary(plan, empty.result),
        search=_search_block(False, True, 1, LimitReason.ALREADY_MET),
        conclusion=FeasibilityConclusion.REACHABLE,
        proof=None,
        warnings=_warnings(plan),
        errors=[],
    )


def _scored_output(plan: _PlannerInput, outcome: _SearchOutcome, evaluated: int) -> dict[str, Any]:
    best = outcome.best
    complete = outcome.stop is _SearchStop.EXHAUSTED
    optimality_proven = outcome.stop is not _SearchStop.BUDGET
    if outcome.stop is _SearchStop.BUDGET:
        incomplete_message: str | None = "The evaluation budget ran out; a better plan may exist."
        lower_priority = "Not part of the best plan found within the evaluation budget."
    elif outcome.stop is _SearchStop.DOMINATED:
        incomplete_message = "Larger plans were not scored because a smaller plan meets every target; the plan is still optimal."
        lower_priority = "Not part of the best-ranked plan."
    else:
        incomplete_message = None
        lower_priority = "Not part of the best-ranked plan."
    if best.meets_targets:
        status, conclusion, proof = PlannerStatus.TARGET_MET, FeasibilityConclusion.REACHABLE, None
    elif complete:
        status = PlannerStatus.PARTIAL if best.activity_ids or _has_eligible(plan) else PlannerStatus.NO_FEASIBLE_CANDIDATES
        conclusion = FeasibilityConclusion.PROVEN_UNREACHABLE
        proof = {"kind": ProofKind.EXHAUSTIVE_SEARCH.value, "evaluated_subsets": evaluated}
    else:
        status, conclusion, proof = PlannerStatus.PARTIAL, FeasibilityConclusion.UNDETERMINED, None
    selected, excluded = _plan_lists(plan, best, lower_priority)
    return _envelope(
        plan.request_id, plan.context,
        status=status,
        selected=selected,
        excluded=excluded,
        score_summary=_score_summary(plan, best.result),
        search=_search_block(
            complete, optimality_proven, evaluated,
            LimitReason.EVALUATION_LIMIT if outcome.stop is _SearchStop.BUDGET else None,
        ),
        conclusion=conclusion,
        proof=proof,
        warnings=_warnings(plan, incomplete_message),
        errors=[],
    )


def _has_eligible(plan: _PlannerInput) -> bool:
    return any(_pre_search_exclusion(c, plan.included) is None for c in plan.candidates)


def _scorer_failure_output(plan: _PlannerInput, failure: _ScorerFailure, evaluated: int) -> dict[str, Any]:
    return _envelope(
        plan.request_id, plan.context,
        status=failure.status,
        selected=[],
        excluded=[],
        score_summary=None,
        search=_search_block(False, False, evaluated, LimitReason.SP2_FAILURE),
        conclusion=FeasibilityConclusion.UNDETERMINED,
        proof=None,
        warnings=_warnings(plan),
        errors=deepcopy(failure.errors),
    )


def _invalid_input_output(planner_input: Mapping[str, Any], error: ContractError) -> dict[str, Any]:
    return _envelope(
        planner_input["request_id"], planner_input["context"],
        status=PlannerStatus.ERROR,
        selected=[],
        excluded=[],
        score_summary=None,
        search=_search_block(False, False, 0, LimitReason.INVALID_INPUT),
        conclusion=FeasibilityConclusion.UNDETERMINED,
        proof=None,
        warnings=_warnings(None),
        errors=[_issue(LimitReason.INVALID_INPUT.value, str(error))],
    )
