"""Plan selection, whole-set scheduling and replan for sp3-planner/0.2 (contract sections 7-11).

Usage: ``build_plan(planner_input, ScorerAdapter(backend).score_plan)``.

The planner validates planner_input, checks keep requests (KEEP_CONFLICT is
returned before any scoring), scores the base set (the kept activities, often
none), returns ALREADY_MET when the baseline meets every target and there is
no previous plan, and otherwise searches subsets that contain every kept
activity, in a deterministic order by size and activity ID. Each subset is
scheduled as a whole by ``sp3.scheduler.schedule_set`` before it may be scored:
an unschedulable subset is pruned with all of its supersets, and an
undetermined one is neither scored nor extended. Scored subsets are ranked by
the section 9 tuple; the best one is explained, compared with the previous
plan and versioned.

Every score comes from the injected whole-set scorer, once per unique subset,
with ``attribution_order`` taken from that subset's own schedule. The planner
never sums single-activity scores, invents points, or treats a scorer failure
as zero. Planning is pure: inputs are never mutated, no global state is kept,
and the only clock is ``context.as_of``. Results stay DEMO_ONLY and unverified.
``what_if_skip`` previews the plan without one activity; nothing is applied.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
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
    SCORE_COMPARISON_BASIS,
    ChangeLabel,
    ContractError,
    DroppedCode,
    EvaluationStatus,
    ExclusionCode,
    FeasibilityConclusion,
    FeasibilityStatus,
    Interval,
    KeepConflictCode,
    LimitReason,
    Participation,
    PlannerStatus,
    PreviousPlan,
    ProgressStatus,
    ProofKind,
    ReasonCode,
    RegistrationStatus,
    Schedule,
    ScheduleType,
    WarningCode,
    attribution_order,
    build_based_on,
    copy_json,
    exact_object,
    feasible_alone,
    json_number,
    non_empty_string,
    overlaps,
    plan_version,
    reason_code,
    remaining_gap,
    require,
    same_instants,
    timestamp,
    valid_flexible_blocks,
    validate_baseline,
    validate_context,
    validate_intervals,
    validate_keep_requests,
    validate_participation,
    validate_plan_version,
    validate_previous_plan,
    validate_schedule,
    validate_score_response,
)
from sp3.scheduler import MAX_FLEXIBLE_PER_SET, ScheduleResult, ScheduleStatus, schedule_set

__all__ = [
    "DEFAULT_MAX_EVALUATIONS",
    "MAX_FLEXIBLE_PER_SET",
    "PreferenceUtility",
    "ScorePlan",
    "build_plan",
    "what_if_skip",
]

DEFAULT_MAX_EVALUATIONS = 4096

ScorePlan = Callable[[dict[str, Any]], dict[str, Any]]
PreferenceUtility = Callable[[tuple[str, ...], Mapping[str, Any]], float]

_SCORER_STATUSES = tuple(status.value for status in EvaluationStatus)


@dataclass(frozen=True)
class _Candidate:
    activity_id: str
    title: str
    domain: str | None
    mode: str
    status: FeasibilityStatus
    reason_codes: tuple[str, ...]
    schedule: Schedule | None
    fixed_block_json: tuple[Mapping[str, str], ...]
    participation: Participation

    @property
    def minutes(self) -> float:
        """Planned minutes: fixed block minutes or the flexible duration."""
        assert self.schedule is not None
        return self.schedule.planned_minutes


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
    window: tuple[datetime, datetime, datetime]
    available: tuple[Interval, ...]
    candidates: tuple[_Candidate, ...]
    by_id: Mapping[str, _Candidate]
    conflicts: frozenset[frozenset[str]]
    included: frozenset[str]
    previous: PreviousPlan | None
    previous_json: Mapping[str, tuple[Mapping[str, str], ...]]
    kept: tuple[str, ...]
    retained: frozenset[str]
    based_on: Mapping[str, Any]

    def eligible(self, candidate: _Candidate) -> bool:
        """Selectable: FEASIBLE, progress NOT_STARTED and not already counted."""
        return (
            candidate.status is FeasibilityStatus.FEASIBLE
            and candidate.participation.progress is ProgressStatus.NOT_STARTED
            and candidate.activity_id not in self.included
        )

    def pending_confirmation(self) -> list[str]:
        return sorted(
            c.activity_id for c in self.candidates
            if c.participation.progress is ProgressStatus.COMPLETED and c.activity_id not in self.included
        )


@dataclass(frozen=True)
class _Evaluation:
    activity_ids: tuple[str, ...]
    schedule: ScheduleResult
    result: Mapping[str, Any]
    rank: tuple[Any, ...]
    meets_targets: bool


class _SearchStop(Enum):
    EXHAUSTED = "EXHAUSTED"
    DOMINATED = "DOMINATED"
    BUDGET = "BUDGET"


@dataclass
class _SearchFlags:
    """Scheduling limits met while searching or explaining the plan."""

    undetermined_sizes: set[int] = field(default_factory=set)
    not_minimal: bool = False


@dataclass(frozen=True)
class _SearchOutcome:
    best: _Evaluation
    stop: _SearchStop
    met_size: int | None = None


class _ScorerFailure(Exception):
    """Internal control flow: a scorer call did not return an OK result."""

    def __init__(self, status: PlannerStatus, errors: list[dict[str, Any]]) -> None:
        super().__init__(status.value)
        self.status = status
        self.errors = errors


class _Scorer:
    """Builds score requests, validates responses, and counts search evaluations."""

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

    def evaluate(self, activity_ids: tuple[str, ...], order: Sequence[str], *, counted: bool = True) -> Mapping[str, Any]:
        """Score one set; ``counted=False`` keeps the call outside the search budget."""
        selection = {"selected_activity_ids": list(activity_ids), "attribution_order": list(order)}
        request = {**copy_json(self._template), **copy_json(selection)}
        expected = {**self._template, **selection}
        if counted:
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


class _Scheduling:
    """Whole-set scheduling with one cached result per activity set and build_plan call."""

    def __init__(self, plan: _PlannerInput, max_flexible_per_set: int) -> None:
        self._plan = plan
        self._cap = max_flexible_per_set
        self._cache: dict[frozenset[str], ScheduleResult] = {}

    def __call__(self, activity_ids: Iterable[str]) -> ScheduleResult:
        key = frozenset(activity_ids)
        result = self._cache.get(key)
        if result is None:
            result = self._schedule(key)
            if result.status is ScheduleStatus.UNDETERMINED and any(
                known.status is ScheduleStatus.UNSCHEDULABLE and subset < key
                for subset, known in self._cache.items()
            ):
                # Monotonicity: a superset of an unschedulable set is unschedulable.
                result = ScheduleResult(ScheduleStatus.UNSCHEDULABLE, reason="A subset of these activities is unschedulable.")
            self._cache[key] = result
        return result

    def _schedule(self, key: frozenset[str]) -> ScheduleResult:
        plan = self._plan
        previous = {} if plan.previous is None else plan.previous.blocks
        window_start, window_end, as_of = plan.window
        return schedule_set(
            {activity_id: plan.by_id[activity_id].schedule for activity_id in key},
            plan.available,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
            previous_blocks={activity_id: previous[activity_id] for activity_id in key if activity_id in previous},
            keep=[activity_id for activity_id in plan.kept if activity_id in key],
            max_flexible_per_set=self._cap,
        )


def build_plan(
    planner_input: Mapping[str, Any],
    score_plan: ScorePlan,
    *,
    max_evaluations: int = DEFAULT_MAX_EVALUATIONS,
    max_flexible_per_set: int = MAX_FLEXIBLE_PER_SET,
    preference_utility: PreferenceUtility | None = None,
    personalization_strategy: str = "BALANCED",
) -> dict[str, Any]:
    """Return the section-10 planner_output for ``planner_input``.

    ``score_plan`` maps a score_request to a score_response (section 10.1).
    ``max_evaluations`` counts unique scored subsets, including the base set;
    the score_comparison rescore is outside it. ``max_flexible_per_set`` caps
    the flexible activities the scheduler places exactly in one set.
    Raises ContractError when contract_version, request_id or context are
    unusable, because no trustworthy output envelope can be built; every other
    invalid input returns ERROR with limit_reason=INVALID_INPUT.
    """
    if not callable(score_plan):
        raise TypeError("score_plan must be callable")
    if type(max_evaluations) is not int or max_evaluations < 1:
        raise ValueError("max_evaluations must be a positive integer")
    if type(max_flexible_per_set) is not int or max_flexible_per_set < 1:
        raise ValueError("max_flexible_per_set must be a positive integer")
    if preference_utility is not None and not callable(preference_utility):
        raise TypeError("preference_utility must be callable")
    if personalization_strategy not in {"MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"}:
        raise ValueError("personalization_strategy is not supported")
    _validate_envelope(planner_input)
    try:
        plan = _parse_input(planner_input)
    except ContractError as error:
        return _invalid_input_output(planner_input, error)
    conflicts = _keep_conflicts(plan)
    if conflicts:
        return _keep_conflict_output(plan, conflicts)

    scheduling = _Scheduling(plan, max_flexible_per_set)
    scorer = _Scorer(plan, score_plan)
    flags = _SearchFlags()
    try:
        base_schedule = scheduling(plan.kept)
        # Keep requests passed _keep_conflicts, so the kept blocks are a valid schedule.
        assert base_schedule.status is ScheduleStatus.SCHEDULED
        base = _evaluate(
            plan,
            scorer,
            plan.kept,
            base_schedule,
            preference_utility,
            personalization_strategy,
        )
        if plan.previous is None and base.meets_targets:
            return _already_met_output(plan, base, scheduling)
        extra = tuple(c for c in plan.candidates if plan.eligible(c) and c.activity_id not in plan.kept)
        outcome = _search(
            plan,
            extra,
            base,
            scorer,
            scheduling,
            flags,
            max_evaluations,
            preference_utility,
            personalization_strategy,
        ) if extra else _SearchOutcome(base, _SearchStop.EXHAUSTED)
        comparison = _score_comparison(plan, scorer, outcome.best)
    except _ScorerFailure as failure:
        return _scorer_failure_output(plan, failure, scorer.evaluated)
    return _scored_output(plan, outcome, scorer.evaluated, scheduling, flags, comparison)


def what_if_skip(
    planner_input: Mapping[str, Any],
    activity_id: str,
    score_plan: ScorePlan,
    **options: Any,
) -> dict[str, Any]:
    """Preview the plan if the student skips ``activity_id`` (contract section 11).

    The input is deep-copied. On the copy, the activity's progress becomes
    CANCELLED and any keep request on it is dropped; the copy is then planned
    with ``build_plan``. The caller's input is never changed and nothing is
    applied. ``options`` are passed to ``build_plan``.
    """
    copied = deepcopy(planner_input)
    candidates = copied.get("candidates") if isinstance(copied, dict) else None
    require(isinstance(candidates, list), "planner_input.candidates", "must be an array")
    matches = [
        entry for entry in candidates
        if isinstance(entry, dict) and isinstance(entry.get("activity"), dict)
        and entry["activity"].get("activity_id") == activity_id and isinstance(entry.get("participation"), dict)
    ]
    require(len(matches) == 1, "what_if_skip.activity_id", "must name exactly one candidate")
    matches[0]["participation"]["progress"] = ProgressStatus.CANCELLED.value
    if isinstance(copied.get("keep_requests"), list):
        copied["keep_requests"] = [
            request for request in copied["keep_requests"]
            if not (isinstance(request, dict) and request.get("activity_id") == activity_id)
        ]
    return build_plan(copied, score_plan, **options)


# --- Validation -----------------------------------------------------------

def _validate_envelope(planner_input: Any) -> None:
    require(isinstance(planner_input, dict), "planner_input", "must be an object")
    for field_name in ("contract_version", "request_id", "context"):
        require(field_name in planner_input, "planner_input", "missing required or unexpected fields")
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
    available = validate_intervals(planner_input["available_intervals"], "planner_input.available_intervals")
    require(isinstance(planner_input["candidates"], list), "planner_input.candidates", "must be an array")
    candidates = [
        _parse_candidate(entry, f"planner_input.candidates[{index}]", window, available)
        for index, entry in enumerate(planner_input["candidates"])
    ]
    ids = [candidate.activity_id for candidate in candidates]
    require(len(ids) == len(set(ids)), "planner_input.candidates", "activity IDs must be unique")
    conflicts = _parse_conflicts(planner_input["conflict_pairs"], set(ids))
    _check_conflict_coverage(candidates, conflicts)
    previous = validate_previous_plan(planner_input["previous_plan"], "planner_input.previous_plan")
    kept = validate_keep_requests(planner_input["keep_requests"], previous, "planner_input.keep_requests")
    ordered = tuple(sorted(candidates, key=lambda c: c.activity_id))
    by_id = {c.activity_id: c for c in ordered}
    included = frozenset(baseline["included_activity_ids"])
    previous_json: dict[str, tuple[Mapping[str, str], ...]] = {}
    retained: frozenset[str] = frozenset()
    if previous is not None:
        previous_json = {
            item["activity_id"]: tuple(copy_json(block) for block in item["scheduled_blocks"])
            for item in planner_input["previous_plan"]["selected_activities"]
        }
        # P: previous activities not completed and not already counted.
        retained = frozenset(
            activity_id for activity_id in previous.blocks
            if activity_id not in included
            and not (activity_id in by_id and by_id[activity_id].participation.progress is ProgressStatus.COMPLETED)
        )
    return _PlannerInput(
        request_id=planner_input["request_id"],
        context=context,
        baseline=baseline,
        goals=goals,
        preferences=preferences,
        limits=limits,
        window=window,
        available=available,
        candidates=ordered,
        by_id=by_id,
        conflicts=conflicts,
        included=included,
        previous=previous,
        previous_json=previous_json,
        kept=tuple(sorted(kept)),
        retained=retained,
        based_on=build_based_on(context, None if previous is None else previous.plan_version),
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
    for field_name, allowed in (("preferred_domains", ALLOWED_DOMAINS), ("preferred_modes", ALLOWED_MODES)):
        values = preferences[field_name]
        require(isinstance(values, list), f"{path}.{field_name}", "must be an array")
        require(all(isinstance(item, str) and item in allowed for item in values), f"{path}.{field_name}", "contains an unsupported value")
        require(len(values) == len(set(values)), f"{path}.{field_name}", "values must be unique")
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


def _parse_candidate(entry: Any, path: str, window: tuple[datetime, ...], available: tuple[Interval, ...]) -> _Candidate:
    """A section 6.5 candidate, accepted exactly as feasibility produces it."""
    exact_object(entry, CANDIDATE_FIELDS, path)
    activity = exact_object(entry["activity"], ACTIVITY_FIELDS, path + ".activity")
    activity_id = non_empty_string(activity["activity_id"], path + ".activity.activity_id")
    title = non_empty_string(activity["title"], path + ".activity.title")
    domain = activity["domain"]
    require(domain is None or domain in ALLOWED_DOMAINS, path + ".activity.domain", "unsupported domain")
    require(activity["mode"] in ALLOWED_MODES, path + ".activity.mode", "unsupported mode")
    _, _, deadline = (
        None if activity[key] is None else timestamp(activity[key], f"{path}.activity.{key}")
        for key in ("start", "end", "registration_deadline")
    )
    binding = entry["score_binding_ref"]
    if binding is not None:
        non_empty_string(binding, path + ".score_binding_ref")
    participation = validate_participation(entry["participation"], path + ".participation")
    schedule = None if entry["schedule"] is None else validate_schedule(entry["schedule"], path + ".schedule")
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
        require(schedule is not None, path + ".schedule", "FEASIBLE requires a normalized schedule")
        require(
            feasible_alone(schedule, available, *window), path + ".schedule",
            "FEASIBLE schedule does not fit the planning window, as_of and available time",
        )
        if participation.registration is RegistrationStatus.NOT_REGISTERED:
            as_of = window[2]
            require(deadline is not None and as_of < deadline, path + ".activity.registration_deadline", "FEASIBLE requires an open registration deadline")
    else:
        require(bool(codes), path + ".feasibility.reason_codes", "non-FEASIBLE requires a reason code")
    fixed_json: tuple[Mapping[str, str], ...] = ()
    if schedule is not None and schedule.type is ScheduleType.FIXED:
        fixed_json = tuple(copy_json(block) for block in entry["schedule"]["fixed_blocks"])
    return _Candidate(
        activity_id=activity_id,
        title=title,
        domain=domain,
        mode=activity["mode"],
        status=status,
        reason_codes=tuple(codes),
        schedule=schedule,
        fixed_block_json=fixed_json,
        participation=participation,
    )


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
    """Section 6.5: every pair of overlapping FIXED schedules (any status) is listed."""
    fixed = [c for c in candidates if c.schedule is not None and c.schedule.type is ScheduleType.FIXED]
    for index, left in enumerate(fixed):
        for right in fixed[index + 1:]:
            if any(overlaps(a, b) for a in left.schedule.fixed_blocks for b in right.schedule.fixed_blocks):
                require(
                    frozenset((left.activity_id, right.activity_id)) in conflicts,
                    "planner_input.conflict_pairs", "an overlapping FIXED pair is missing",
                )


# --- Keep requests (section 10.4) -------------------------------------------

def _keep_conflicts(plan: _PlannerInput) -> list[dict[str, Any]]:
    """Every conflict of the keep requests, listed per kept activity.

    Per activity, the first that applies: NOT_LISTED, NOT_ELIGIBLE,
    FIXED_CHANGED, BLOCK_INVALID. For each pair of kept activities that pass
    those checks: BLOCK_OVERLAP when their kept blocks overlap, otherwise
    CONFLICT when the pair is a declared conflict. For the whole keep set:
    LIMIT on every kept activity when the number of kept activities, or the
    planned minutes of those that pass, exceed a stated limit. Entries are
    ordered by activity ID, then code order, then the other activity's ID.
    """
    if not plan.kept:
        return []
    assert plan.previous is not None
    # (code, other kept activity or "", message) per kept activity.
    found: dict[str, list[tuple[KeepConflictCode, str, str]]] = {activity_id: [] for activity_id in plan.kept}
    valid: list[str] = []
    for activity_id in plan.kept:
        candidate = plan.by_id.get(activity_id)
        blocks = plan.previous.blocks[activity_id]
        if candidate is None:
            found[activity_id].append((KeepConflictCode.NOT_LISTED, "", "The kept activity is no longer listed among the candidates."))
        elif not plan.eligible(candidate):
            found[activity_id].append((KeepConflictCode.NOT_ELIGIBLE, "", _ineligible_message(plan, candidate)))
        elif candidate.schedule.type is ScheduleType.FIXED and not same_instants(blocks, candidate.schedule.fixed_blocks):
            found[activity_id].append((KeepConflictCode.FIXED_CHANGED, "", "The fixed sessions changed since the previous plan."))
        elif candidate.schedule.type is ScheduleType.FLEXIBLE_WINDOW and not valid_flexible_blocks(candidate.schedule, blocks, plan.available, *plan.window):
            found[activity_id].append((KeepConflictCode.BLOCK_INVALID, "", "The kept block is no longer one sitting inside the usable window and available time."))
        else:
            valid.append(activity_id)
    for index, left in enumerate(valid):
        for right in valid[index + 1:]:
            if any(overlaps(a, b) for a in plan.previous.blocks[left] for b in plan.previous.blocks[right]):
                code, text = KeepConflictCode.BLOCK_OVERLAP, "The kept block overlaps kept activity {}."
            elif frozenset((left, right)) in plan.conflicts:
                code, text = KeepConflictCode.CONFLICT, "The kept activity conflicts with kept activity {}."
            else:
                continue
            found[left].append((code, right, text.format(right)))
            found[right].append((code, left, text.format(left)))
    limits = plan.limits
    minutes = math.fsum(plan.by_id[activity_id].minutes for activity_id in valid)
    if (limits.max_activities is not None and len(plan.kept) > limits.max_activities) or (
        limits.max_duration_minutes is not None and minutes > limits.max_duration_minutes + ABS_TOLERANCE
    ):
        for activity_id in plan.kept:
            found[activity_id].append((KeepConflictCode.LIMIT, "", "Keeping every kept activity exceeds a stated limit."))
    order = list(KeepConflictCode)
    return [
        {"activity_id": activity_id, "code": code.value, "message": message}
        for activity_id in plan.kept
        for code, _, message in sorted(found[activity_id], key=lambda item: (order.index(item[0]), item[1]))
    ]


def _ineligible_message(plan: _PlannerInput, candidate: _Candidate) -> str:
    if candidate.status is FeasibilityStatus.NEEDS_REVIEW:
        return "Feasibility review is pending: " + ", ".join(candidate.reason_codes) + "."
    if candidate.status is FeasibilityStatus.INFEASIBLE:
        return "Feasibility check failed: " + ", ".join(candidate.reason_codes) + "."
    if candidate.participation.progress is ProgressStatus.COMPLETED:
        return "Already completed; it is never scheduled again."
    if candidate.participation.progress is ProgressStatus.CANCELLED:
        return "Cancelled by the student."
    return "Already counted in the baseline."


# --- Scoring and ranking --------------------------------------------------

def _evaluate(
    plan: _PlannerInput,
    scorer: _Scorer,
    activity_ids: tuple[str, ...],
    schedule: ScheduleResult,
    preference_utility: PreferenceUtility | None = None,
    personalization_strategy: str = "BALANCED",
) -> _Evaluation:
    order = attribution_order({activity_id: schedule.blocks[activity_id][0][0] for activity_id in activity_ids})
    result = scorer.evaluate(activity_ids, order)
    rank = _rank(
        plan,
        activity_ids,
        result,
        schedule.time_changes,
        preference_utility,
        personalization_strategy,
    )
    return _Evaluation(activity_ids, schedule, result, rank, meets_targets=rank[0] == 0 and rank[1] == 0)


def _rank(
    plan: _PlannerInput,
    activity_ids: tuple[str, ...],
    result: Mapping[str, Any],
    time_changes: int,
    preference_utility: PreferenceUtility | None = None,
    personalization_strategy: str = "BALANCED",
) -> tuple[Any, ...]:
    """Section 9 ranking tuple; lower is better."""
    after = result["category_after"]
    category_gap = math.fsum(remaining_gap(target, after[category]) for category, target in plan.goals.category_targets)
    total_target = plan.goals.total_target
    total_gap = 0 if total_target is None else remaining_gap(total_target, result["total_after"])
    if plan.previous is None:
        set_changes = time_changes = 0
    else:
        chosen = set(activity_ids)
        set_changes = len(plan.retained - chosen) + len(chosen - plan.retained)
    selected = [plan.by_id[activity_id] for activity_id in activity_ids]
    preference = sum(len(_preference_matches(plan.preferences, c)) for c in selected)
    duration = math.fsum(c.minutes for c in selected)
    if preference_utility is None:
        return (category_gap, total_gap, set_changes, time_changes, len(activity_ids), -preference, duration, activity_ids)

    utility = preference_utility(activity_ids, result)
    if isinstance(utility, bool) or not isinstance(utility, (int, float)) or not math.isfinite(utility):
        raise ValueError("preference_utility must return a finite number")
    if personalization_strategy == "MINIMUM_EFFORT":
        return (category_gap, total_gap, set_changes, time_changes, len(activity_ids), duration, -utility, activity_ids)
    if personalization_strategy == "PREFERENCE_FIRST":
        return (category_gap, total_gap, set_changes, time_changes, -utility, len(activity_ids), duration, activity_ids)
    return (category_gap, total_gap, set_changes, time_changes, len(activity_ids), -utility, duration, activity_ids)


def _preference_matches(preferences: _Preferences, candidate: _Candidate) -> list[tuple[str, str]]:
    matches = []
    if candidate.domain is not None and candidate.domain in preferences.domains:
        matches.append(("domain", candidate.domain))
    if candidate.mode in preferences.modes:
        matches.append(("mode", candidate.mode))
    return matches


def _score_comparison(plan: _PlannerInput, scorer: _Scorer, best: _Evaluation) -> dict[str, Any] | None:
    """Hypothetical score of the still-eligible previous activity set (one extra call).

    It describes that activity set only; its old blocks may no longer be usable.
    """
    if plan.previous is None:
        return None
    previous = plan.previous.blocks
    ids = tuple(sorted(a for a in plan.retained if a in plan.by_id and plan.eligible(plan.by_id[a])))
    result = scorer.evaluate(ids, attribution_order({a: previous[a][0][0] for a in ids}), counted=False)
    return {
        "basis": SCORE_COMPARISON_BASIS,
        "previous_activity_ids": list(ids),
        "previous_projected_by_category": copy_json(dict(result["category_after"])),
        "previous_projected_total": result["total_after"],
        "new_projected_total": best.result["total_after"],
    }


# --- Search ---------------------------------------------------------------

def _search(
    plan: _PlannerInput,
    extra: tuple[_Candidate, ...],
    base: _Evaluation,
    scorer: _Scorer,
    scheduling: _Scheduling,
    flags: _SearchFlags,
    max_evaluations: int,
    preference_utility: PreferenceUtility | None = None,
    personalization_strategy: str = "BALANCED",
) -> _SearchOutcome:
    """Score valid supersets of the base set by increasing size, then lexicographic ID order.

    Dominance applies only without a previous plan: the first two ranking
    components are gaps, which are never negative, and components 3 and 4
    are then always 0. A subset of size k that meets every target has gaps
    (0, 0), the minimum possible, so any larger subset is ranked behind it by
    the fifth component (activity count) whatever its scores. Once size k is
    finished, the best scored subset is therefore optimal over all valid
    subsets, and larger subsets are left unscored with optimality proven.
    With a previous plan, a larger subset can have fewer activity-set
    changes, so every valid subset is scored up to the budget.
    """
    best = base
    met_size: int | None = None
    # PREFERENCE_FIRST may intentionally choose a larger set with greater
    # utility, so the v0.2 activity-count dominance proof no longer applies.
    prune_dominated = plan.previous is None and personalization_strategy != "PREFERENCE_FIRST"
    for activity_ids, schedule in _valid_subsets(plan, extra, scheduling, flags):
        if prune_dominated and met_size is not None and len(activity_ids) > met_size:
            return _SearchOutcome(best, _SearchStop.DOMINATED, met_size)
        if scorer.evaluated >= max_evaluations:
            return _SearchOutcome(best, _SearchStop.BUDGET, met_size)
        evaluation = _evaluate(
            plan,
            scorer,
            activity_ids,
            schedule,
            preference_utility,
            personalization_strategy,
        )
        flags.not_minimal |= not schedule.time_changes_minimal
        if evaluation.rank < best.rank:
            best = evaluation
        if evaluation.meets_targets and met_size is None:
            met_size = len(activity_ids)
    return _SearchOutcome(best, _SearchStop.EXHAUSTED, met_size)


def _valid_subsets(
    plan: _PlannerInput,
    extra: tuple[_Candidate, ...],
    scheduling: _Scheduling,
    flags: _SearchFlags,
) -> Iterator[tuple[tuple[str, ...], ScheduleResult]]:
    """Yield schedulable, conflict-free supersets of the kept set within both limits.

    Order: by the number of added activities, then lexicographically by ID.
    Conflicts, limits and schedulability are each closed under removal, so
    backtracking prunes a branch as soon as one addition breaks any of them,
    and no larger subset exists once a size produces none. An UNDETERMINED
    subset is neither yielded nor extended; it is recorded in ``flags``.
    """
    kept = plan.kept
    addable = [c for c in extra if not any(frozenset((c.activity_id, k)) in plan.conflicts for k in kept)]
    ids = [c.activity_id for c in addable]
    minutes = [c.minutes for c in addable]
    blocked = [
        {j for j, other in enumerate(ids) if frozenset((activity_id, other)) in plan.conflicts}
        for activity_id in ids
    ]
    count = len(ids)
    limits = plan.limits
    largest = count if limits.max_activities is None else min(count, limits.max_activities - len(kept))
    max_duration = limits.max_duration_minutes
    base_minutes = math.fsum(plan.by_id[activity_id].minutes for activity_id in kept)

    def extend(size: int, start: int, chosen: list[int], duration: float) -> Iterator[tuple[tuple[str, ...], ScheduleResult]]:
        for index in range(start, count - (size - len(chosen)) + 1):
            if any(index in blocked[i] for i in chosen):
                continue
            total = duration + minutes[index]
            if max_duration is not None and total > max_duration + ABS_TOLERANCE:
                continue
            chosen.append(index)
            subset = tuple(sorted((*kept, *(ids[i] for i in chosen))))
            schedule = scheduling(subset)
            if len(chosen) == size:
                if schedule.status is ScheduleStatus.SCHEDULED:
                    yield subset, schedule
                elif schedule.status is ScheduleStatus.UNDETERMINED:
                    flags.undetermined_sizes.add(len(subset))
            elif schedule.status is ScheduleStatus.SCHEDULED:
                yield from extend(size, index + 1, chosen, total)
            chosen.pop()

    for size in range(1, largest + 1):
        produced = False
        for item in extend(size, 0, [], base_minutes):
            produced = True
            yield item
        if not produced:
            return


# --- Exclusions and replan changes -------------------------------------------

def _pre_search_exclusion(plan: _PlannerInput, candidate: _Candidate) -> ExclusionCode | None:
    if candidate.status is FeasibilityStatus.NEEDS_REVIEW:
        return ExclusionCode.NEEDS_REVIEW
    if candidate.status is FeasibilityStatus.INFEASIBLE or candidate.participation.progress is not ProgressStatus.NOT_STARTED:
        return ExclusionCode.NOT_FEASIBLE
    if candidate.activity_id in plan.included:
        return ExclusionCode.ALREADY_COUNTED
    return None


def _exclusion(
    plan: _PlannerInput,
    candidate: _Candidate,
    selected: tuple[str, ...],
    scheduling: _Scheduling,
    flags: _SearchFlags,
    lower_priority_message: str,
) -> dict[str, Any]:
    code = _pre_search_exclusion(plan, candidate)
    if code is None:
        code, message = _post_search_exclusion(plan, candidate, selected, scheduling, flags, lower_priority_message)
    else:
        message = _ineligible_message(plan, candidate)
    return {"activity_id": candidate.activity_id, "code": code.value, "message": message}


def _post_search_exclusion(
    plan: _PlannerInput,
    candidate: _Candidate,
    selected: tuple[str, ...],
    scheduling: _Scheduling,
    flags: _SearchFlags,
    lower_priority_message: str,
) -> tuple[ExclusionCode, str]:
    conflicting = [s for s in selected if frozenset((s, candidate.activity_id)) in plan.conflicts]
    if conflicting:
        return ExclusionCode.CONFLICT, "Overlaps with selected activity " + ", ".join(conflicting) + "."
    together = scheduling((*selected, candidate.activity_id))
    if together.status is ScheduleStatus.UNSCHEDULABLE:
        return ExclusionCode.NO_TIME, "No valid schedule exists for it together with the selected activities."
    limits = plan.limits
    if limits.max_activities is not None and len(selected) + 1 > limits.max_activities:
        return ExclusionCode.LIMIT, "Adding it would exceed the activity-count limit."
    if limits.max_duration_minutes is not None:
        duration = math.fsum(plan.by_id[a].minutes for a in (*selected, candidate.activity_id))
        if duration > limits.max_duration_minutes + ABS_TOLERANCE:
            return ExclusionCode.LIMIT, "Adding it would exceed the total-duration limit."
    if together.status is ScheduleStatus.UNDETERMINED:
        flags.undetermined_sizes.add(len(selected) + 1)
        return ExclusionCode.LOWER_PRIORITY, "Scheduling it together with the selected activities was not determined within the scheduling limit."
    return ExclusionCode.LOWER_PRIORITY, lower_priority_message


def _dropped(plan: _PlannerInput, chosen: set[str], excluded: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Activities of P that are not selected, in previous-plan order."""
    if plan.previous is None:
        return []
    previous = plan.previous.blocks
    entries = []
    for activity_id in sorted(plan.retained - chosen, key=lambda a: (previous[a][0][0], a)):
        candidate = plan.by_id.get(activity_id)
        if candidate is None:
            entries.append(_dropped_entry(activity_id, False, DroppedCode.NOT_LISTED, "No longer listed among the candidates."))
            continue
        registered = candidate.participation.registration is RegistrationStatus.REGISTERED
        exclusion = excluded[activity_id]
        if candidate.participation.progress is ProgressStatus.CANCELLED:
            code = DroppedCode.CANCELLED
        elif candidate.status is not FeasibilityStatus.FEASIBLE:
            code = DroppedCode.NO_LONGER_FEASIBLE
        elif exclusion["code"] == ExclusionCode.NO_TIME.value:
            code = DroppedCode.NO_TIME
        else:
            code = DroppedCode.LOWER_PRIORITY
        entries.append(_dropped_entry(activity_id, registered, code, exclusion["message"]))
    return entries


def _dropped_entry(activity_id: str, registered: bool, code: DroppedCode, message: str) -> dict[str, Any]:
    return {"activity_id": activity_id, "registered": registered, "code": code.value, "message": message}


# --- Output ---------------------------------------------------------------

def _issue(code: str, message: str, activity_id: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "activity_id": activity_id}


def _warning(code: WarningCode, message: str) -> dict[str, str]:
    return {"code": code.value, "message": message}


def _warnings(
    plan: _PlannerInput | None,
    *,
    dropped: Sequence[Mapping[str, Any]] = (),
    search_incomplete_message: str | None = None,
) -> list[dict[str, str]]:
    warnings = [
        _warning(WarningCode.DEMO_ONLY, "Projected scores are demo estimates, not awarded or verified points."),
        _warning(WarningCode.TRAVEL_NOT_MODELED, "Travel time between activities is not modeled."),
    ]
    if plan is not None:
        pending = sum(1 for c in plan.candidates if c.status is FeasibilityStatus.NEEDS_REVIEW)
        if pending:
            warnings.append(_warning(WarningCode.PENDING_CANDIDATES, f"{pending} candidate(s) await feasibility review and were not considered."))
        completed = plan.pending_confirmation()
        if completed:
            warnings.append(_warning(WarningCode.PENDING_CONFIRMATION, f"{len(completed)} completed activity(ies) await score confirmation and were not scored."))
    registered = [entry["activity_id"] for entry in dropped if entry["registered"]]
    if registered:
        warnings.append(_warning(WarningCode.DROPS_REGISTERED, "The plan drops registered activity(ies) " + ", ".join(registered) + "; registrations are not cancelled."))
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
    search: dict[str, Any],
    conclusion: FeasibilityConclusion,
    warnings: list[dict[str, str]],
    based_on: Mapping[str, Any],
    selected: list[dict[str, Any]] | None = None,
    excluded: list[dict[str, Any]] | None = None,
    score_summary: dict[str, Any] | None = None,
    proof: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
    dropped: list[dict[str, Any]] | None = None,
    pending_confirmation: list[str] | None = None,
    keep_conflicts: list[dict[str, Any]] | None = None,
    score_comparison: dict[str, Any] | None = None,
    plan_version_value: str | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": request_id,
        "context": deepcopy(dict(context)),
        "status": status.value,
        "selected_activities": selected or [],
        "excluded_candidates": excluded or [],
        "score_summary": score_summary,
        "search": search,
        "feasibility_conclusion": conclusion.value,
        "proof": proof,
        "warnings": warnings,
        "errors": errors or [],
        "mode": DEMO_MODE,
        "official_award_verified": False,
        "dropped_activities": dropped or [],
        "pending_confirmation": pending_confirmation or [],
        "keep_conflicts": keep_conflicts or [],
        "score_comparison": score_comparison,
        "based_on": copy_json(dict(based_on)),
        "plan_version": plan_version_value,
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


def _blocks_json(plan: _PlannerInput, candidate: _Candidate, blocks: Sequence[Interval]) -> list[dict[str, str]]:
    """Emit blocks: fixed sessions and unchanged previous blocks are copied as given."""
    if candidate.schedule.type is ScheduleType.FIXED:
        return [copy_json(dict(block)) for block in candidate.fixed_block_json]
    previous = None if plan.previous is None else plan.previous.blocks.get(candidate.activity_id)
    if previous is not None and same_instants(previous, blocks):
        return [copy_json(dict(block)) for block in plan.previous_json[candidate.activity_id]]
    zone = plan.window[0].tzinfo
    return [{"start": start.astimezone(zone).isoformat(), "end": end.astimezone(zone).isoformat()} for start, end in blocks]


def _change(plan: _PlannerInput, activity_id: str, blocks: Sequence[Interval]) -> ChangeLabel:
    if plan.previous is None or activity_id not in plan.previous.blocks:
        return ChangeLabel.ADDED
    return ChangeLabel.KEPT if same_instants(blocks, plan.previous.blocks[activity_id]) else ChangeLabel.MOVED


def _selected_entry(plan: _PlannerInput, candidate: _Candidate, best: _Evaluation) -> dict[str, Any]:
    blocks = best.schedule.blocks[candidate.activity_id]
    reasons = [
        {
            "code": ReasonCode.GOAL_CONTRIBUTION.value,
            "message": f"Projected to add {_format_points(item['projected_added'])} point(s) to {item['category_id']} (demo estimate, not an awarded score).",
            "category_id": item["category_id"],
            "projected_added": item["projected_added"],
        }
        for item in best.result["contributions"]
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
        "schedule_type": candidate.schedule.type.value,
        "scheduled_blocks": _blocks_json(plan, candidate, blocks),
        "registration": candidate.participation.registration.value,
        "change": _change(plan, candidate.activity_id, blocks).value,
        "reasons": reasons,
    }


def _plan_lists(
    plan: _PlannerInput,
    best: _Evaluation,
    scheduling: _Scheduling,
    flags: _SearchFlags,
    lower_priority_message: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    chosen = set(best.activity_ids)
    blocks = best.schedule.blocks
    selected = sorted((plan.by_id[a] for a in chosen), key=lambda c: (blocks[c.activity_id][0][0], c.activity_id))
    excluded = {
        c.activity_id: _exclusion(plan, c, best.activity_ids, scheduling, flags, lower_priority_message)
        for c in plan.candidates
        if c.activity_id not in chosen
    }
    return [_selected_entry(plan, c, best) for c in selected], list(excluded.values()), _dropped(plan, chosen, excluded)


def _plan_version(plan: _PlannerInput, selected: Sequence[Mapping[str, Any]]) -> str:
    return plan_version(plan.based_on, [(entry["activity_id"], entry["scheduled_blocks"]) for entry in selected])


def _already_met_output(plan: _PlannerInput, empty: _Evaluation, scheduling: _Scheduling) -> dict[str, Any]:
    selected, excluded, dropped = _plan_lists(plan, empty, scheduling, _SearchFlags(), "Not needed: the baseline already meets every target.")
    return _envelope(
        plan.request_id, plan.context,
        status=PlannerStatus.ALREADY_MET,
        selected=selected,
        excluded=excluded,
        score_summary=_score_summary(plan, empty.result),
        search=_search_block(False, True, 1, LimitReason.ALREADY_MET),
        conclusion=FeasibilityConclusion.REACHABLE,
        warnings=_warnings(plan, dropped=dropped),
        dropped=dropped,
        pending_confirmation=plan.pending_confirmation(),
        based_on=plan.based_on,
        plan_version_value=_plan_version(plan, selected),
    )


def _scored_output(
    plan: _PlannerInput,
    outcome: _SearchOutcome,
    evaluated: int,
    scheduling: _Scheduling,
    flags: _SearchFlags,
    comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    best = outcome.best
    budget = outcome.stop is _SearchStop.BUDGET
    lower_priority = "Not part of the best plan found within the evaluation budget." if budget else "Not part of the best-ranked plan."
    selected, excluded, dropped = _plan_lists(plan, best, scheduling, flags, lower_priority)

    # Undetermined sets larger than a target-meeting size are dominated (no previous plan).
    dominated_only = plan.previous is None and outcome.met_size is not None
    relevant = {size for size in flags.undetermined_sizes if not (dominated_only and size > outcome.met_size)}
    scheduling_limited = bool(relevant) or flags.not_minimal
    complete = outcome.stop is _SearchStop.EXHAUSTED and not flags.undetermined_sizes and not flags.not_minimal
    optimality_proven = not budget and not scheduling_limited
    if budget:
        limit_reason: LimitReason | None = LimitReason.EVALUATION_LIMIT
    elif scheduling_limited:
        limit_reason = LimitReason.SCHEDULING_LIMIT
    else:
        limit_reason = None
    messages = []
    if budget:
        messages.append("The evaluation budget ran out; a better plan may exist.")
    if relevant:
        messages.append("Some activity sets exceed the scheduling limit and were not scored; a better plan may exist.")
    if flags.not_minimal:
        messages.append("Time changes were not proven minimal for some activity sets; a better plan may exist.")
    if not complete and not messages:
        messages.append("Larger plans were not scored because a smaller plan meets every target; the plan is still optimal.")

    if best.meets_targets:
        status, conclusion, proof = PlannerStatus.TARGET_MET, FeasibilityConclusion.REACHABLE, None
    elif complete:
        status = PlannerStatus.PARTIAL if best.activity_ids or _has_eligible(plan) else PlannerStatus.NO_FEASIBLE_CANDIDATES
        conclusion = FeasibilityConclusion.PROVEN_UNREACHABLE
        proof = {"kind": ProofKind.EXHAUSTIVE_SEARCH.value, "evaluated_subsets": evaluated}
    else:
        status, conclusion, proof = PlannerStatus.PARTIAL, FeasibilityConclusion.UNDETERMINED, None
    return _envelope(
        plan.request_id, plan.context,
        status=status,
        selected=selected,
        excluded=excluded,
        score_summary=_score_summary(plan, best.result),
        search=_search_block(complete, optimality_proven, evaluated, limit_reason),
        conclusion=conclusion,
        proof=proof,
        warnings=_warnings(plan, dropped=dropped, search_incomplete_message=" ".join(messages) if messages else None),
        dropped=dropped,
        pending_confirmation=plan.pending_confirmation(),
        score_comparison=comparison,
        based_on=plan.based_on,
        plan_version_value=_plan_version(plan, selected),
    )


def _has_eligible(plan: _PlannerInput) -> bool:
    return any(plan.eligible(c) for c in plan.candidates)


def _keep_conflict_output(plan: _PlannerInput, conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    return _envelope(
        plan.request_id, plan.context,
        status=PlannerStatus.KEEP_CONFLICT,
        search=_search_block(False, False, 0, LimitReason.KEEP_CONFLICT),
        conclusion=FeasibilityConclusion.UNDETERMINED,
        warnings=_warnings(plan),
        pending_confirmation=plan.pending_confirmation(),
        keep_conflicts=conflicts,
        based_on=plan.based_on,
    )


def _scorer_failure_output(plan: _PlannerInput, failure: _ScorerFailure, evaluated: int) -> dict[str, Any]:
    return _envelope(
        plan.request_id, plan.context,
        status=failure.status,
        search=_search_block(False, False, evaluated, LimitReason.SP2_FAILURE),
        conclusion=FeasibilityConclusion.UNDETERMINED,
        warnings=_warnings(plan),
        errors=deepcopy(failure.errors),
        pending_confirmation=plan.pending_confirmation(),
        based_on=plan.based_on,
    )


def _invalid_input_output(planner_input: Mapping[str, Any], error: ContractError) -> dict[str, Any]:
    return _envelope(
        planner_input["request_id"], planner_input["context"],
        status=PlannerStatus.ERROR,
        search=_search_block(False, False, 0, LimitReason.INVALID_INPUT),
        conclusion=FeasibilityConclusion.UNDETERMINED,
        warnings=_warnings(None),
        errors=[_issue(LimitReason.INVALID_INPUT.value, str(error))],
        based_on=build_based_on(planner_input["context"], _readable_previous_version(planner_input)),
    )


def _readable_previous_version(planner_input: Mapping[str, Any]) -> str | None:
    previous = planner_input.get("previous_plan")
    if not isinstance(previous, dict):
        return None
    try:
        return validate_plan_version(previous.get("plan_version"), "planner_input.previous_plan.plan_version")
    except ContractError:
        return None
