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
import time
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
    "AVAILABLE_PRESETS",
    "DEFAULT_MAX_EVALUATIONS",
    "MAX_FLEXIBLE_PER_SET",
    "PlanFilters",
    "PresetMode",
    "ScorePlan",
    "SpeedMode",
    "build_plan",
    "recommend_plans",
    "what_if_skip",
]

DEFAULT_MAX_EVALUATIONS = 4096

ScorePlan = Callable[[dict[str, Any]], dict[str, Any]]

_SCORER_STATUSES = tuple(status.value for status in EvaluationStatus)


class PresetMode(str, Enum):
    """Multi-objective schedule recommendation presets."""

    BALANCED = "balanced"
    MAX_SCORE = "max_score"
    MIN_TIME = "min_time"
    MIN_ACTIVITIES = "min_activities"
    ONLINE_FIRST = "online_first"
    PREFERENCE_FIRST = "preference_first"


class SpeedMode(str, Enum):
    """Quality-vs-latency execution profile."""

    AUTO = "auto"
    FAST = "fast"
    BALANCED = "balanced"
    OPTIMAL = "optimal"


AVAILABLE_PRESETS: dict[str, dict[str, str]] = {
    PresetMode.BALANCED.value: {
        "id": PresetMode.BALANCED.value,
        "label": "Balanced (Default Contract)",
        "description": "Prioritizes meeting category and total targets with minimal activities, highest preference match, and shortest total duration.",
    },
    PresetMode.MAX_SCORE.value: {
        "id": PresetMode.MAX_SCORE.value,
        "label": "Maximize Total Points",
        "description": "Prioritizes achieving the highest projected total score and category gains within activity/duration limits.",
    },
    PresetMode.MIN_TIME.value: {
        "id": PresetMode.MIN_TIME.value,
        "label": "Minimize Time Spent",
        "description": "Prioritizes meeting targets with the smallest total duration in minutes.",
    },
    PresetMode.MIN_ACTIVITIES.value: {
        "id": PresetMode.MIN_ACTIVITIES.value,
        "label": "Fewest Activities",
        "description": "Prioritizes meeting targets with the fewest distinct activities.",
    },
    PresetMode.ONLINE_FIRST.value: {
        "id": PresetMode.ONLINE_FIRST.value,
        "label": "Online / Remote First",
        "description": "Prioritizes online and hybrid activities before on-campus activities while meeting score targets.",
    },
    PresetMode.PREFERENCE_FIRST.value: {
        "id": PresetMode.PREFERENCE_FIRST.value,
        "label": "Preference & Location Match",
        "description": "Prioritizes matching preferred domains, modes, locations, and time-of-day windows.",
    },
}


@dataclass(frozen=True)
class PlanFilters:
    """Optional multi-criteria filters and soft preferences for candidate selection."""

    allowed_domains: frozenset[str] | None = None
    allowed_modes: frozenset[str] | None = None
    location_keywords: tuple[str, ...] = ()
    preferred_locations: tuple[str, ...] = ()
    max_fee: int | float | None = None
    mandatory_only: bool = False
    preferred_hours: tuple[tuple[int, int], ...] = ()


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
    location: str | None = None
    points: int | float | None = None
    fee: int | float | None = None
    mandatory: bool | None = None
    score_binding_ref: str | None = None

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
    pool: tuple[_Evaluation, ...] = ()


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

    def __init__(self, plan: _PlannerInput, max_flexible_per_set: int, *, fast_flexible: bool = False) -> None:
        self._plan = plan
        self._cap = max_flexible_per_set
        self._fast_flexible = fast_flexible
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
            fast_flexible=self._fast_flexible,
        )


def _normalize_preset(preset: PresetMode | str | None) -> PresetMode:
    if preset is None:
        return PresetMode.BALANCED
    if isinstance(preset, PresetMode):
        return preset
    try:
        return PresetMode(str(preset).strip().lower())
    except ValueError:
        raise ValueError(f"Unsupported preset: {preset!r}. Expected one of {[p.value for p in PresetMode]}.") from None


def _normalize_speed_mode(speed_mode: SpeedMode | str | None) -> SpeedMode:
    if speed_mode is None:
        return SpeedMode.AUTO
    if isinstance(speed_mode, SpeedMode):
        return speed_mode
    try:
        return SpeedMode(str(speed_mode).strip().lower())
    except ValueError:
        raise ValueError(f"Unsupported speed_mode: {speed_mode!r}. Expected one of {[s.value for s in SpeedMode]}.") from None


def _coerce_filters(filters: PlanFilters | Mapping[str, Any] | None) -> PlanFilters | None:
    if filters is None or isinstance(filters, PlanFilters):
        return filters
    if not isinstance(filters, Mapping):
        raise TypeError("filters must be a PlanFilters instance, a mapping, or None")
    allowed_domains = filters.get("allowed_domains")
    allowed_modes = filters.get("allowed_modes")
    location_keywords = filters.get("location_keywords") or ()
    preferred_locations = filters.get("preferred_locations") or ()
    max_fee = filters.get("max_fee")
    mandatory_only = bool(filters.get("mandatory_only", False))
    raw_hours = filters.get("preferred_hours") or ()
    hours: list[tuple[int, int]] = []
    for item in raw_hours:
        if isinstance(item, Sequence) and len(item) == 2:
            hours.append((int(item[0]), int(item[1])))
    return PlanFilters(
        allowed_domains=None if allowed_domains is None else frozenset(str(d) for d in allowed_domains),
        allowed_modes=None if allowed_modes is None else frozenset(str(m) for m in allowed_modes),
        location_keywords=tuple(str(k) for k in location_keywords if str(k).strip()),
        preferred_locations=tuple(str(k) for k in preferred_locations if str(k).strip()),
        max_fee=max_fee,
        mandatory_only=mandatory_only,
        preferred_hours=tuple(hours),
    )


def build_plan(
    planner_input: Mapping[str, Any],
    score_plan: ScorePlan,
    *,
    max_evaluations: int = DEFAULT_MAX_EVALUATIONS,
    max_flexible_per_set: int = MAX_FLEXIBLE_PER_SET,
    preset: PresetMode | str | None = None,
    speed_mode: SpeedMode | str = SpeedMode.AUTO,
    filters: PlanFilters | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the section-10 planner_output for ``planner_input``.

    ``score_plan`` maps a score_request to a score_response (section 10.1).
    ``max_evaluations`` counts unique scored subsets, including the base set;
    the score_comparison rescore is outside it. ``max_flexible_per_set`` caps
    the flexible activities the scheduler places exactly in one set.
    Optional ``preset``, ``speed_mode``, and ``filters`` enable multi-objective
    preset ranking, quality-vs-latency control, and multi-criteria filtering
    while remaining 100% compatible with sp3-planner/0.2 contracts.
    """
    if not callable(score_plan):
        raise TypeError("score_plan must be callable")
    if type(max_evaluations) is not int or max_evaluations < 1:
        raise ValueError("max_evaluations must be a positive integer")
    if type(max_flexible_per_set) is not int or max_flexible_per_set < 1:
        raise ValueError("max_flexible_per_set must be a positive integer")
    preset_mode = _normalize_preset(preset)
    resolved_speed = _normalize_speed_mode(speed_mode)
    plan_filters = _coerce_filters(filters)
    _validate_envelope(planner_input)
    try:
        plan = _parse_input(planner_input)
    except ContractError as error:
        return _invalid_input_output(planner_input, error)
    conflicts = _keep_conflicts(plan)
    if conflicts:
        return _keep_conflict_output(plan, conflicts)

    extra = tuple(c for c in plan.candidates if plan.eligible(c) and c.activity_id not in plan.kept)
    use_fast_flex = resolved_speed in (SpeedMode.FAST, SpeedMode.BALANCED) or (
        resolved_speed is SpeedMode.AUTO and len(extra) > 12
    )
    scheduling = _Scheduling(plan, max_flexible_per_set, fast_flexible=use_fast_flex)
    scorer = _Scorer(plan, score_plan)
    flags = _SearchFlags()
    try:
        base_schedule = scheduling(plan.kept)
        # Keep requests passed _keep_conflicts, so the kept blocks are a valid schedule.
        assert base_schedule.status is ScheduleStatus.SCHEDULED
        base = _evaluate(plan, scorer, plan.kept, base_schedule, preset=preset_mode, filters=plan_filters)
        if plan.previous is None and base.meets_targets and preset is None and plan_filters is None:
            return _already_met_output(plan, base, scheduling)
        if not extra:
            outcome = _SearchOutcome(base, _SearchStop.EXHAUSTED, pool=(base,))
        elif (
            preset is None
            and resolved_speed is SpeedMode.AUTO
            and plan_filters is None
            and len(extra) <= 12
        ):
            outcome = _search(plan, extra, base, scorer, scheduling, flags, max_evaluations)
        else:
            effective_speed = SpeedMode.BALANCED if (resolved_speed is SpeedMode.AUTO and len(extra) > 12) else (
                SpeedMode.OPTIMAL if resolved_speed is SpeedMode.AUTO else resolved_speed
            )
            outcome = _guided_search(
                plan,
                extra,
                base,
                scorer,
                scheduling,
                flags,
                max_evaluations,
                preset=preset_mode,
                speed_mode=effective_speed,
                filters=plan_filters,
                collect_pool=False,
            )
        comparison = _score_comparison(plan, scorer, outcome.best)
    except _ScorerFailure as failure:
        return _scorer_failure_output(plan, failure, scorer.evaluated)
    return _scored_output(plan, outcome, scorer.evaluated, scheduling, flags, comparison)


def recommend_plans(
    planner_input: Mapping[str, Any],
    score_plan: ScorePlan,
    *,
    preset: PresetMode | str = PresetMode.BALANCED,
    speed_mode: SpeedMode | str = SpeedMode.BALANCED,
    max_plans: int = 5,
    min_jaccard_distance: float = 0.25,
    filters: PlanFilters | Mapping[str, Any] | None = None,
    include_preset_alternatives: bool = True,
    max_evaluations: int = DEFAULT_MAX_EVALUATIONS,
    max_flexible_per_set: int = MAX_FLEXIBLE_PER_SET,
) -> dict[str, Any]:
    """Return 0..max_plans diverse, contract-valid schedule proposals for ``planner_input``.

    Unlike ``build_plan`` (which returns a single ``planner_output``), ``recommend_plans``
    discovers a pool of valid schedules and returns:
    - ``primary_plan``: standard section-10 ``planner_output`` for the chosen preset.
    - ``plans``: list of 0 to ``max_plans`` distinct, non-redundant ``planner_output`` dicts.
      Returns 0 plans when the request fails or has no feasible candidates, 1 plan when
      only one valid schedule exists, or multiple diverse plans when alternatives exist.
    - ``plan_summaries``: concise metadata for each proposed schedule, including which
      presets it satisfies best, projected score, duration, and activity count.
    - ``candidate_stats`` and ``elapsed_ms`` for telemetry and benchmarking.
    """
    t0 = time.perf_counter()
    if type(max_plans) is not int or max_plans < 1:
        raise ValueError("max_plans must be a positive integer")
    preset_mode = _normalize_preset(preset)
    resolved_speed = _normalize_speed_mode(speed_mode)
    plan_filters = _coerce_filters(filters)

    _validate_envelope(planner_input)
    try:
        plan = _parse_input(planner_input)
    except ContractError as error:
        err_out = _invalid_input_output(planner_input, error)
        return {
            "primary_plan": err_out,
            "plans": [],
            "plan_summaries": [],
            "preset": preset_mode.value,
            "speed_mode": resolved_speed.value,
            "candidate_stats": {"total_candidates": 0, "eligible_candidates": 0, "filtered_candidates": 0, "evaluated_subsets": 0},
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    conflicts = _keep_conflicts(plan)
    if conflicts:
        kc_out = _keep_conflict_output(plan, conflicts)
        return {
            "primary_plan": kc_out,
            "plans": [],
            "plan_summaries": [],
            "preset": preset_mode.value,
            "speed_mode": resolved_speed.value,
            "candidate_stats": {
                "total_candidates": len(plan.candidates),
                "eligible_candidates": sum(1 for c in plan.candidates if plan.eligible(c)),
                "filtered_candidates": 0,
                "evaluated_subsets": 0,
            },
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    extra = tuple(c for c in plan.candidates if plan.eligible(c) and c.activity_id not in plan.kept)
    filtered_extra = _apply_filters(extra, plan_filters)
    effective_speed = SpeedMode.BALANCED if (resolved_speed is SpeedMode.AUTO and len(extra) > 12) else (
        SpeedMode.OPTIMAL if resolved_speed is SpeedMode.AUTO else resolved_speed
    )
    use_fast_flex = effective_speed in (SpeedMode.FAST, SpeedMode.BALANCED) or len(extra) > 12
    scheduling = _Scheduling(plan, max_flexible_per_set, fast_flexible=use_fast_flex)
    scorer = _Scorer(plan, score_plan)
    flags = _SearchFlags()

    try:
        base_schedule = scheduling(plan.kept)
        assert base_schedule.status is ScheduleStatus.SCHEDULED
        base = _evaluate(plan, scorer, plan.kept, base_schedule, preset=preset_mode, filters=plan_filters)
        if plan.previous is None and base.meets_targets and preset_mode is not PresetMode.MAX_SCORE:
            already_out = _already_met_output(plan, base, scheduling)
            summary = _summarize_plan_option(0, already_out, base, [preset_mode.value])
            return {
                "primary_plan": already_out,
                "plans": [already_out],
                "plan_summaries": [summary],
                "preset": preset_mode.value,
                "speed_mode": effective_speed.value,
                "candidate_stats": {
                    "total_candidates": len(plan.candidates),
                    "eligible_candidates": len(extra),
                    "filtered_candidates": len(filtered_extra),
                    "evaluated_subsets": scorer.evaluated,
                },
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            }
        if not filtered_extra:
            outcome = _SearchOutcome(base, _SearchStop.BUDGET if (extra and not filtered_extra) else _SearchStop.EXHAUSTED, pool=(base,))
        else:
            outcome = _guided_search(
                plan,
                extra,
                base,
                scorer,
                scheduling,
                flags,
                max_evaluations,
                preset=preset_mode,
                speed_mode=effective_speed,
                filters=plan_filters,
                collect_pool=True,
            )
        comparison = _score_comparison(plan, scorer, outcome.best)
    except _ScorerFailure as failure:
        fail_out = _scorer_failure_output(plan, failure, scorer.evaluated)
        return {
            "primary_plan": fail_out,
            "plans": [],
            "plan_summaries": [],
            "preset": preset_mode.value,
            "speed_mode": effective_speed.value,
            "candidate_stats": {
                "total_candidates": len(plan.candidates),
                "eligible_candidates": len(extra),
                "filtered_candidates": len(filtered_extra),
                "evaluated_subsets": scorer.evaluated,
            },
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    primary_plan = _scored_output(plan, outcome, scorer.evaluated, scheduling, flags, comparison)
    if primary_plan["status"] == PlannerStatus.NO_FEASIBLE_CANDIDATES.value or (
        not outcome.best.activity_ids and not outcome.best.meets_targets
    ):
        return {
            "primary_plan": primary_plan,
            "plans": [],
            "plan_summaries": [],
            "preset": preset_mode.value,
            "speed_mode": effective_speed.value,
            "candidate_stats": {
                "total_candidates": len(plan.candidates),
                "eligible_candidates": len(extra),
                "filtered_candidates": len(filtered_extra),
                "evaluated_subsets": scorer.evaluated,
            },
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    diverse_evals = _select_diverse_evaluations(
        plan,
        outcome,
        preset=preset_mode,
        filters=plan_filters,
        max_plans=max_plans,
        min_jaccard_distance=min_jaccard_distance,
        include_preset_alternatives=include_preset_alternatives,
    )
    plans_list: list[dict[str, Any]] = []
    summaries_list: list[dict[str, Any]] = []
    for idx, (ev, matched_presets) in enumerate(diverse_evals):
        if idx == 0 and ev.activity_ids == outcome.best.activity_ids:
            plan_out = primary_plan
        else:
            alt_outcome = _SearchOutcome(
                best=ev,
                stop=_SearchStop.BUDGET,
                met_size=outcome.met_size,
                pool=outcome.pool,
            )
            alt_comparison = _score_comparison_from_cached(plan, comparison, ev)
            plan_out = _scored_output(plan, alt_outcome, scorer.evaluated, scheduling, flags, alt_comparison)
        plans_list.append(plan_out)
        summaries_list.append(_summarize_plan_option(idx, plan_out, ev, matched_presets))

    return {
        "primary_plan": primary_plan,
        "plans": plans_list,
        "plan_summaries": summaries_list,
        "preset": preset_mode.value,
        "speed_mode": effective_speed.value,
        "candidate_stats": {
            "total_candidates": len(plan.candidates),
            "eligible_candidates": len(extra),
            "filtered_candidates": len(filtered_extra),
            "evaluated_subsets": scorer.evaluated,
        },
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }


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
        location=activity["location"] if isinstance(activity.get("location"), str) else None,
        points=activity["points"] if isinstance(activity.get("points"), (int, float)) and not isinstance(activity.get("points"), bool) else None,
        fee=activity["fee"] if isinstance(activity.get("fee"), (int, float)) and not isinstance(activity.get("fee"), bool) else None,
        mandatory=activity["mandatory"] if isinstance(activity.get("mandatory"), bool) else None,
        score_binding_ref=binding,
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
    *,
    preset: PresetMode = PresetMode.BALANCED,
    filters: PlanFilters | None = None,
) -> _Evaluation:
    order = attribution_order({activity_id: schedule.blocks[activity_id][0][0] for activity_id in activity_ids})
    result = scorer.evaluate(activity_ids, order)
    std_rank = _rank(plan, activity_ids, result, schedule.time_changes)
    meets_targets = std_rank[0] == 0 and std_rank[1] == 0
    rank = (
        std_rank
        if preset is PresetMode.BALANCED and filters is None
        else _rank_for_preset(plan, activity_ids, result, schedule, preset, filters)
    )
    return _Evaluation(activity_ids, schedule, result, rank, meets_targets=meets_targets)


def _rank(plan: _PlannerInput, activity_ids: tuple[str, ...], result: Mapping[str, Any], time_changes: int) -> tuple[Any, ...]:
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
    return (category_gap, total_gap, set_changes, time_changes, len(activity_ids), -preference, duration, activity_ids)


def _extended_preference_score(
    plan: _PlannerInput,
    candidate: _Candidate,
    schedule: ScheduleResult | None,
    filters: PlanFilters | None,
) -> float:
    score = float(len(_preference_matches(plan.preferences, candidate)))
    if filters is not None:
        if filters.preferred_locations and candidate.location:
            loc_lower = candidate.location.lower()
            if any(kw.lower() in loc_lower for kw in filters.preferred_locations):
                score += 1.5
        if filters.preferred_hours:
            blocks = (
                schedule.blocks.get(candidate.activity_id)
                if schedule is not None and candidate.activity_id in schedule.blocks
                else (candidate.schedule.fixed_blocks if candidate.schedule and candidate.schedule.type is ScheduleType.FIXED else None)
            )
            if blocks:
                start_hour = blocks[0][0].hour
                end_hour = blocks[-1][1].hour + (1 if blocks[-1][1].minute > 0 else 0)
                if any(h_start <= start_hour and end_hour <= h_end for h_start, h_end in filters.preferred_hours):
                    score += 1.0
    return score


def _rank_for_preset(
    plan: _PlannerInput,
    activity_ids: tuple[str, ...],
    result: Mapping[str, Any],
    schedule: ScheduleResult,
    preset: PresetMode,
    filters: PlanFilters | None = None,
) -> tuple[Any, ...]:
    """Preset-aware ranking tuple (lower is better)."""
    after = result["category_after"]
    category_gap = math.fsum(remaining_gap(target, after[category]) for category, target in plan.goals.category_targets)
    total_target = plan.goals.total_target
    total_gap = 0 if total_target is None else remaining_gap(total_target, result["total_after"])
    time_changes = schedule.time_changes
    if plan.previous is None:
        set_changes = time_changes = 0
    else:
        chosen = set(activity_ids)
        set_changes = len(plan.retained - chosen) + len(chosen - plan.retained)
    selected = [plan.by_id[activity_id] for activity_id in activity_ids]
    preference = math.fsum(_extended_preference_score(plan, c, schedule, filters) for c in selected)
    duration = math.fsum(c.minutes for c in selected)
    total_after = float(result["total_after"])
    total_gain = float(result["total_gain"])
    online_count = sum(1 for c in selected if c.mode == "online")
    hybrid_count = sum(1 for c in selected if c.mode == "hybrid")
    mandatory_count = sum(1 for c in selected if c.mandatory is True)

    if preset is PresetMode.MAX_SCORE:
        # Maximize total score and category completion first, then preference, then fewer activities & shorter time
        return (
            category_gap,
            total_gap,
            -total_after,
            -total_gain,
            set_changes,
            time_changes,
            -preference,
            len(activity_ids),
            duration,
            activity_ids,
        )
    if preset is PresetMode.MIN_TIME:
        # Meet targets with minimum total duration first, then fewest activities
        return (
            category_gap,
            total_gap,
            duration,
            len(activity_ids),
            set_changes,
            time_changes,
            -preference,
            -total_after,
            activity_ids,
        )
    if preset is PresetMode.MIN_ACTIVITIES:
        # Meet targets with fewest activities first, then minimum duration, then highest score
        return (
            category_gap,
            total_gap,
            len(activity_ids),
            duration,
            -total_after,
            set_changes,
            time_changes,
            -preference,
            activity_ids,
        )
    if preset is PresetMode.ONLINE_FIRST:
        # Meet targets while minimizing non-online activities
        non_online = len(activity_ids) - online_count
        return (
            category_gap,
            total_gap,
            non_online,
            -online_count,
            -hybrid_count,
            len(activity_ids),
            duration,
            -preference,
            activity_ids,
        )
    if preset is PresetMode.PREFERENCE_FIRST:
        # Meet targets while maximizing average preference match, mandatory count, and fewest activities
        avg_pref = preference / max(1, len(activity_ids))
        return (
            category_gap,
            total_gap,
            -avg_pref,
            -mandatory_count,
            len(activity_ids),
            -preference,
            duration,
            set_changes,
            time_changes,
            activity_ids,
        )
    # Default: PresetMode.BALANCED (Contract section 9 order + extended preference support)
    return (category_gap, total_gap, set_changes, time_changes, len(activity_ids), -preference, duration, activity_ids)


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


def _score_comparison_from_cached(
    plan: _PlannerInput,
    base_comparison: dict[str, Any] | None,
    ev: _Evaluation,
) -> dict[str, Any] | None:
    if plan.previous is None or base_comparison is None:
        return None
    copied = copy_json(base_comparison)
    copied["new_projected_total"] = ev.result["total_after"]
    return copied


# --- Filtering, Heuristic Pre-Ranking, and Guided Search ------------------

def _candidate_matches_filters(candidate: _Candidate, filters: PlanFilters | None) -> bool:
    if filters is None:
        return True
    if filters.allowed_domains is not None and candidate.domain not in filters.allowed_domains:
        return False
    if filters.allowed_modes is not None and candidate.mode not in filters.allowed_modes:
        return False
    if filters.mandatory_only and candidate.mandatory is not True:
        return False
    if filters.max_fee is not None and candidate.fee is not None and candidate.fee > filters.max_fee + ABS_TOLERANCE:
        return False
    if filters.location_keywords:
        if not candidate.location:
            return False
        loc_lower = candidate.location.lower()
        if not any(kw.lower() in loc_lower for kw in filters.location_keywords):
            return False
    return True


def _apply_filters(extra: tuple[_Candidate, ...], filters: PlanFilters | None) -> tuple[_Candidate, ...]:
    if filters is None:
        return extra
    return tuple(c for c in extra if _candidate_matches_filters(c, filters))


def _heuristic_candidate_priority(
    plan: _PlannerInput,
    candidate: _Candidate,
    conflict_degrees: Mapping[str, int],
    preset: PresetMode,
    filters: PlanFilters | None,
) -> tuple[Any, ...]:
    """Fast zero-cost structural heuristic for ordering candidates (lower is better)."""
    pts = float(candidate.points or 0.0)
    mins = max(1.0, float(candidate.minutes))
    density = pts / mins
    pref = _extended_preference_score(plan, candidate, None, filters)
    deg = conflict_degrees.get(candidate.activity_id, 0)
    is_online = 1 if candidate.mode == "online" else (0.5 if candidate.mode == "hybrid" else 0.0)
    is_retained = 1 if candidate.activity_id in plan.retained else 0

    if preset is PresetMode.MIN_TIME:
        return (-is_retained, mins, -density, -pts, -pref, deg, candidate.activity_id)
    if preset is PresetMode.ONLINE_FIRST:
        return (-is_retained, -is_online, -pts, mins, -pref, deg, candidate.activity_id)
    if preset is PresetMode.PREFERENCE_FIRST:
        return (-is_retained, -pref, -pts, mins, deg, candidate.activity_id)
    if preset is PresetMode.MAX_SCORE:
        return (-is_retained, -pts, -density, -pref, mins, deg, candidate.activity_id)
    return (-is_retained, -pts, -pref, mins, deg, candidate.activity_id)


def _select_working_pool(
    plan: _PlannerInput,
    candidates: tuple[_Candidate, ...],
    conflict_degrees: Mapping[str, int],
    preset: PresetMode,
    filters: PlanFilters | None,
    cap: int,
) -> tuple[_Candidate, ...]:
    """Select up to ``cap`` diverse, high-value candidates stratified by domain and score_binding_ref."""
    if len(candidates) <= cap:
        return candidates
    ranked = sorted(
        candidates,
        key=lambda c: _heuristic_candidate_priority(plan, c, conflict_degrees, preset, filters),
    )
    by_group: dict[tuple[str | None, str], list[_Candidate]] = {}
    for c in ranked:
        binding_group = (c.score_binding_ref or "").split("-")[0].split(":")[0]
        key = (c.domain, binding_group)
        by_group.setdefault(key, []).append(c)

    selected_ids: set[str] = set()
    pool: list[_Candidate] = []
    # Always include retained activities from previous plan if present
    for c in ranked:
        if c.activity_id in plan.retained and len(pool) < cap:
            selected_ids.add(c.activity_id)
            pool.append(c)

    # Round-robin across (domain, binding_group) buckets so every domain & rule family has top representatives
    group_keys = sorted(by_group.keys(), key=lambda k: (str(k[0]), str(k[1])))
    bucket_Wait: dict[tuple[str | None, str], int] = {k: 0 for k in group_keys}
    while len(pool) < cap:
        added_in_round = False
        for key in group_keys:
            bucket = by_group[key]
            idx = bucket_Wait[key]
            while idx < len(bucket) and bucket[idx].activity_id in selected_ids:
                idx += 1
            if idx < len(bucket):
                cand = bucket[idx]
                selected_ids.add(cand.activity_id)
                pool.append(cand)
                idx += 1
                added_in_round = True
            bucket_Wait[key] = idx
            if len(pool) >= cap:
                break
        if not added_in_round:
            break

    if len(pool) < cap:
        for c in ranked:
            if c.activity_id not in selected_ids:
                selected_ids.add(c.activity_id)
                pool.append(c)
                if len(pool) >= cap:
                    break

    return tuple(sorted(pool, key=lambda c: c.activity_id))


def _guided_search(
    plan: _PlannerInput,
    extra: tuple[_Candidate, ...],
    base: _Evaluation,
    scorer: _Scorer,
    scheduling: _Scheduling,
    flags: _SearchFlags,
    max_evaluations: int,
    *,
    preset: PresetMode = PresetMode.BALANCED,
    speed_mode: SpeedMode = SpeedMode.BALANCED,
    filters: PlanFilters | None = None,
    collect_pool: bool = False,
) -> _SearchOutcome:
    """Multi-stage guided search with Working Pool stratification, Multi-Start Greedy, and Beam Search.

    - When ``len(filtered_extra) <= 12``, ``speed_mode is SpeedMode.OPTIMAL``, and no hard filters
      excluded candidates, executes exact subset enumeration while optionally collecting all scored
      plans into ``pool`` for multi-plan recommendation.
    - When ``len(extra) > 12`` or ``speed_mode`` is ``FAST`` / ``BALANCED``, bounds the search space
      via stratified Working Pool + Singleton Marginal Probe + Multi-Start Constructive Greedy +
      Beam Search so even 500+ candidate inputs finish in tens of milliseconds.
    """
    filtered_extra = _apply_filters(extra, filters)
    has_hard_filter = len(filtered_extra) < len(extra)
    addable_all = tuple(
        c for c in filtered_extra if not any(frozenset((c.activity_id, k)) in plan.conflicts for k in plan.kept)
    )
    if not addable_all:
        stop_empty = _SearchStop.BUDGET if has_hard_filter else _SearchStop.EXHAUSTED
        return _SearchOutcome(base, stop_empty, None, (base,))

    # Exact path for small inputs in OPTIMAL mode when no hard filter dropped candidates
    if len(addable_all) <= 12 and speed_mode is SpeedMode.OPTIMAL and not has_hard_filter:
        best = base
        met_size: int | None = None
        # Dominance by subset size only holds when activity count is the primary tie-breaker after target gaps
        prune_dominated = (
            plan.previous is None
            and preset in (PresetMode.BALANCED, PresetMode.MIN_ACTIVITIES)
            and not collect_pool
        )
        pool_list: list[_Evaluation] = [base] if base.activity_ids else []
        for activity_ids, schedule in _valid_subsets(plan, addable_all, scheduling, flags):
            if prune_dominated and met_size is not None and len(activity_ids) > met_size:
                return _SearchOutcome(best, _SearchStop.DOMINATED, met_size, tuple(pool_list))
            if scorer.evaluated >= max_evaluations:
                return _SearchOutcome(best, _SearchStop.BUDGET, met_size, tuple(pool_list))
            evaluation = _evaluate(plan, scorer, activity_ids, schedule, preset=preset, filters=filters)
            flags.not_minimal |= not schedule.time_changes_minimal
            pool_list.append(evaluation)
            if evaluation.rank < best.rank:
                best = evaluation
            if evaluation.meets_targets and met_size is None:
                met_size = len(activity_ids)
        return _SearchOutcome(best, _SearchStop.EXHAUSTED, met_size, tuple(pool_list))

    # Guided search parameters by speed_mode
    if speed_mode is SpeedMode.FAST:
        working_cap = 24
        beam_width = 8
        seed_count = 6
        mode_budget = min(max_evaluations, 96)
    elif speed_mode is SpeedMode.BALANCED:
        working_cap = 40
        beam_width = 18
        seed_count = 10
        mode_budget = min(max_evaluations, 260)
    else:
        working_cap = 64
        beam_width = 36
        seed_count = 16
        mode_budget = min(max_evaluations, 800)

    conflict_degrees: dict[str, int] = {c.activity_id: 0 for c in addable_all}
    for pair in plan.conflicts:
        items = tuple(pair)
        if len(items) == 2:
            a, b = items
            if a in conflict_degrees:
                conflict_degrees[a] += 1
            if b in conflict_degrees:
                conflict_degrees[b] += 1

    working_pool = _select_working_pool(plan, addable_all, conflict_degrees, preset, filters, working_cap)
    pruned_any = has_hard_filter or (len(working_pool) < len(addable_all))

    kept = plan.kept
    limits = plan.limits
    max_duration = limits.max_duration_minutes
    base_minutes = math.fsum(plan.by_id[a].minutes for a in kept)
    largest = len(working_pool) if limits.max_activities is None else min(len(working_pool), limits.max_activities - len(kept))
    if largest <= 0:
        return _SearchOutcome(base, _SearchStop.BUDGET if pruned_any else _SearchStop.EXHAUSTED, None, (base,))

    best = base
    met_size = len(kept) if base.meets_targets else None
    seen_Evaluations: dict[tuple[str, ...], _Evaluation] = {}
    if base.activity_ids:
        seen_Evaluations[base.activity_ids] = base

    def eval_subset(subset: tuple[str, ...]) -> _Evaluation | None:
        nonlocal best, met_size, pruned_any
        if subset in seen_Evaluations:
            return seen_Evaluations[subset]
        if scorer.evaluated >= mode_budget:
            pruned_any = True
            return None
        duration = math.fsum(plan.by_id[a].minutes for a in subset)
        if max_duration is not None and duration > max_duration + ABS_TOLERANCE:
            return None
        schedule = scheduling(subset)
        if schedule.status is ScheduleStatus.UNDETERMINED:
            flags.undetermined_sizes.add(len(subset))
            pruned_any = True
            return None
        if schedule.status is not ScheduleStatus.SCHEDULED:
            return None
        ev = _evaluate(plan, scorer, subset, schedule, preset=preset, filters=filters)
        flags.not_minimal |= not schedule.time_changes_minimal
        seen_Evaluations[subset] = ev
        if ev.rank < best.rank:
            best = ev
        if ev.meets_targets and (met_size is None or len(subset) < met_size):
            met_size = len(subset)
        return ev

    # Stage 1: Singleton Marginal Probe across Working Pool
    singleton_evals: list[tuple[_Candidate, _Evaluation]] = []
    for cand in working_pool:
        if scorer.evaluated >= mode_budget:
            pruned_any = True
            break
        subset = tuple(sorted((*kept, cand.activity_id)))
        ev = eval_subset(subset)
        if ev is not None:
            singleton_evals.append((cand, ev))

    # Order candidates by actual measured singleton performance (for preset)
    singleton_evals.sort(key=lambda pair: pair[1].rank)
    ordered_cands = [pair[0] for pair in singleton_evals]

    # Map each candidate's standalone category and total gains for fast compatibility matching
    cand_cat_gains: dict[str, Mapping[str, float]] = {}
    cand_total_gain: dict[str, float] = {}
    for cand, ev in singleton_evals:
        cand_cat_gains[cand.activity_id] = ev.result["category_gain"]
        cand_total_gain[cand.activity_id] = float(ev.result["total_gain"])

    # Stage 2: Multi-Start Constructive Greedy Pass (quickly constructs target-meeting diverse plans)
    seeds = singleton_evals[: min(seed_count, len(singleton_evals))]
    for _, seed_ev in seeds:
        if scorer.evaluated >= mode_budget:
            pruned_any = True
            break
        current_ev = seed_ev
        while len(current_ev.activity_ids) - len(kept) < largest:
            if scorer.evaluated >= mode_budget:
                pruned_any = True
                break
            # Stop greedy extension once targets are met unless preset seeks MAX_SCORE
            if current_ev.meets_targets and preset is not PresetMode.MAX_SCORE:
                break
            current_set = set(current_ev.activity_ids)
            current_after = current_ev.result["category_after"]
            caps = plan.baseline["category_caps"]
            unmet_cats = [
                cat
                for cat, target in plan.goals.category_targets
                if remaining_gap(target, current_after[cat]) > 0
            ]
            current_minutes = math.fsum(plan.by_id[a].minutes for a in current_ev.activity_ids)

            # Rank compatible next candidates by cap-aware marginal gain towards unmet categories or preset goal
            next_candidates: list[tuple[tuple[Any, ...], _Candidate]] = []
            for cand in ordered_cands:
                cid = cand.activity_id
                if cid in current_set:
                    continue
                if any(frozenset((cid, s)) in plan.conflicts for s in current_set):
                    continue
                if max_duration is not None and current_minutes + cand.minutes > max_duration + ABS_TOLERANCE:
                    continue
                cat_gains = cand_cat_gains.get(cid, {})
                effective_gains = {
                    cat: min(
                        float(gain),
                        max(0.0, float(caps.get(cat, 100.0)) - float(current_after.get(cat, 0.0))),
                    )
                    for cat, gain in cat_gains.items()
                }
                unmet_help = sum(
                    min(
                        effective_gains.get(cat, 0.0),
                        remaining_gap(dict(plan.goals.category_targets)[cat], current_after[cat]),
                    )
                    for cat in unmet_cats
                )
                tot_help = sum(effective_gains.values())
                if tot_help <= ABS_TOLERANCE:
                    continue
                pref_score = _extended_preference_score(plan, cand, None, filters)
                if preset is PresetMode.MIN_TIME:
                    score_key: tuple[Any, ...] = (0 if unmet_help > 0 else 1, cand.minutes, -unmet_help, -tot_help, cid)
                elif preset is PresetMode.ONLINE_FIRST:
                    is_onl = 1 if cand.mode == "online" else 0
                    score_key = (0 if unmet_help > 0 else 1, -is_onl, -unmet_help, -tot_help, cand.minutes, cid)
                elif preset is PresetMode.PREFERENCE_FIRST:
                    score_key = (0 if unmet_help > 0 else 1, -pref_score, -unmet_help, -tot_help, cand.minutes, cid)
                else:
                    score_key = (0 if unmet_help > 0 else 1, -unmet_help, -tot_help, -pref_score, cand.minutes, cid)
                next_candidates.append((score_key, cand))

            if not next_candidates:
                break
            next_candidates.sort(key=lambda item: item[0])
            extended_ev: _Evaluation | None = None
            # Try top 5 compatible candidates in case earlier ones have a flexible window conflict
            for _, next_cand in next_candidates[:5]:
                if scorer.evaluated >= mode_budget:
                    pruned_any = True
                    break
                trial_subset = tuple(sorted((*current_ev.activity_ids, next_cand.activity_id)))
                trial_ev = eval_subset(trial_subset)
                if trial_ev is not None:
                    # Accept extension if it improves rank or increases total score
                    if trial_ev.rank < current_ev.rank or float(trial_ev.result["total_after"]) > float(current_ev.result["total_after"]) + ABS_TOLERANCE:
                        extended_ev = trial_ev
                        break
            if extended_ev is None:
                break
            current_ev = extended_ev

    # Stage 3: Submodular-Pruned Beam Search across sizes
    current_beam = [pair[1] for pair in singleton_evals[:beam_width]]
    if len(singleton_evals) > beam_width:
        pruned_any = True

    for size in range(2, largest + 1):
        if scorer.evaluated >= mode_budget or not current_beam:
            if current_beam:
                pruned_any = True
            break
        if (
            plan.previous is None
            and preset not in (PresetMode.MAX_SCORE, PresetMode.PREFERENCE_FIRST)
            and met_size is not None
            and len(kept) + size > met_size + (1 if collect_pool else 0)
        ):
            pruned_any = True
            break

        next_beam_map: dict[tuple[str, ...], _Evaluation] = {}
        branch_cap = min(len(ordered_cands), max(12, beam_width))
        if len(ordered_cands) > branch_cap:
            pruned_any = True

        for parent_ev in current_beam:
            if scorer.evaluated >= mode_budget:
                pruned_any = True
                break
            parent_set = set(parent_ev.activity_ids)
            parent_minutes = math.fsum(plan.by_id[a].minutes for a in parent_ev.activity_ids)
            for cand in ordered_cands[:branch_cap]:
                cid = cand.activity_id
                if cid in parent_set:
                    continue
                if any(frozenset((cid, s)) in plan.conflicts for s in parent_set):
                    continue
                if max_duration is not None and parent_minutes + cand.minutes > max_duration + ABS_TOLERANCE:
                    continue
                child_subset = tuple(sorted((*parent_ev.activity_ids, cid)))
                if child_subset in next_beam_map:
                    continue
                child_ev = eval_subset(child_subset)
                if child_ev is not None:
                    # Submodular zero-gain pruning: skip if adding candidate produced 0 score gain and 0 preference gain
                    if (
                        float(child_ev.result["total_after"]) <= float(parent_ev.result["total_after"]) + ABS_TOLERANCE
                        and child_ev.rank[0] >= parent_ev.rank[0] - ABS_TOLERANCE
                        and _extended_preference_score(plan, cand, child_ev.schedule, filters) <= 0
                    ):
                        pruned_any = True
                        continue
                    next_beam_map[child_subset] = child_ev
                if scorer.evaluated >= mode_budget:
                    pruned_any = True
                    break

        sorted_children = sorted(next_beam_map.values(), key=lambda ev: ev.rank)
        if len(sorted_children) > beam_width:
            pruned_any = True
        current_beam = sorted_children[:beam_width]

    pool_tuple = tuple(sorted(seen_Evaluations.values(), key=lambda ev: ev.rank))
    stop_reason = _SearchStop.BUDGET if (pruned_any or scorer.evaluated >= max_evaluations) else _SearchStop.EXHAUSTED
    return _SearchOutcome(best, stop_reason, met_size, pool_tuple)


def _is_redundant_superset(plan: _PlannerInput, ev: _Evaluation, pool_by_ids: Mapping[tuple[str, ...], _Evaluation]) -> bool:
    """Return True if dropping any single non-kept activity yields the exact same or better score & gaps."""
    if len(ev.activity_ids) <= len(plan.kept) + 1:
        return False
    ev_total = float(ev.result["total_after"])
    ev_cat_gap = math.fsum(
        remaining_gap(target, ev.result["category_after"][cat])
        for cat, target in plan.goals.category_targets
    )
    for aid in ev.activity_ids:
        if aid in plan.kept:
            continue
        sub_ids = tuple(x for x in ev.activity_ids if x != aid)
        sub_ev = pool_by_ids.get(sub_ids)
        if sub_ev is not None:
            sub_total = float(sub_ev.result["total_after"])
            sub_cat_gap = math.fsum(
                remaining_gap(target, sub_ev.result["category_after"][cat])
                for cat, target in plan.goals.category_targets
            )
            if sub_cat_gap <= ev_cat_gap + ABS_TOLERANCE and sub_total >= ev_total - ABS_TOLERANCE:
                return True
    return False


def _jaccard_distance(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    set_a, set_b = set(a), set(b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return 1.0 - (len(set_a & set_b) / union)


def _select_diverse_evaluations(
    plan: _PlannerInput,
    outcome: _SearchOutcome,
    *,
    preset: PresetMode,
    filters: PlanFilters | None,
    max_plans: int,
    min_jaccard_distance: float,
    include_preset_alternatives: bool,
) -> list[tuple[_Evaluation, list[str]]]:
    """Select 1..max_plans non-redundant, diverse schedule evaluations from ``outcome.pool``."""
    raw_pool = [ev for ev in outcome.pool if ev.activity_ids or ev.meets_targets]
    if not raw_pool:
        if outcome.best.activity_ids or outcome.best.meets_targets:
            return [(outcome.best, [preset.value])]
        return []

    pool_by_ids = {ev.activity_ids: ev for ev in raw_pool}
    clean_pool = [
        ev for ev in raw_pool
        if ev.activity_ids == outcome.best.activity_ids or not _is_redundant_superset(plan, ev, pool_by_ids)
    ]
    if not clean_pool:
        clean_pool = [outcome.best]

    # When target-meeting schedules exist, only propose target-meeting schedules (unless none exist)
    any_meets = any(ev.meets_targets for ev in clean_pool)
    candidate_pool = [ev for ev in clean_pool if ev.meets_targets] if any_meets else clean_pool

    chosen: list[_Evaluation] = [outcome.best]
    matched_map: dict[tuple[str, ...], list[str]] = {outcome.best.activity_ids: [preset.value]}

    if include_preset_alternatives:
        for alt_preset in PresetMode:
            best_for_alt = min(
                candidate_pool,
                key=lambda ev: _rank_for_preset(plan, ev.activity_ids, ev.result, ev.schedule, alt_preset, filters),
            )
            if best_for_alt.activity_ids in matched_map:
                if alt_preset.value not in matched_map[best_for_alt.activity_ids]:
                    matched_map[best_for_alt.activity_ids].append(alt_preset.value)
            elif len(chosen) < max_plans:
                chosen.append(best_for_alt)
                matched_map[best_for_alt.activity_ids] = [alt_preset.value]

    # Fill remaining slots up to max_plans using Jaccard diversity + preset ranking
    ranked_pool = sorted(
        candidate_pool,
        key=lambda ev: _rank_for_preset(plan, ev.activity_ids, ev.result, ev.schedule, preset, filters),
    )
    for ev in ranked_pool:
        if len(chosen) >= max_plans:
            break
        if ev.activity_ids in matched_map:
            continue
        if all(_jaccard_distance(ev.activity_ids, existing.activity_ids) >= min_jaccard_distance for existing in chosen):
            chosen.append(ev)
            matched_map[ev.activity_ids] = [f"{preset.value}_alt"]

    return [(ev, matched_map[ev.activity_ids]) for ev in chosen]


def _summarize_plan_option(
    index: int,
    plan_output: Mapping[str, Any],
    ev: _Evaluation,
    matched_presets: list[str],
) -> dict[str, Any]:
    duration = round(sum(
        (timestamp(block["end"], "block.end") - timestamp(block["start"], "block.start")).total_seconds() / 60.0
        for item in plan_output.get("selected_activities", [])
        for block in item.get("scheduled_blocks", [])
    ), 2)
    score_summary = plan_output.get("score_summary") or {}
    return {
        "plan_index": index,
        "plan_version": plan_output.get("plan_version"),
        "status": plan_output.get("status"),
        "activity_ids": list(ev.activity_ids),
        "activity_count": len(ev.activity_ids),
        "total_duration_minutes": duration,
        "projected_total": score_summary.get("projected_total", 0),
        "gain_total": score_summary.get("gain_total", 0),
        "meets_targets": ev.meets_targets,
        "matched_presets": matched_presets,
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
    prune_dominated = plan.previous is None
    for activity_ids, schedule in _valid_subsets(plan, extra, scheduling, flags):
        if prune_dominated and met_size is not None and len(activity_ids) > met_size:
            return _SearchOutcome(best, _SearchStop.DOMINATED, met_size)
        if scorer.evaluated >= max_evaluations:
            return _SearchOutcome(best, _SearchStop.BUDGET, met_size)
        evaluation = _evaluate(plan, scorer, activity_ids, schedule)
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
    # Fast O(1) path when all involved schedules are FIXED and there are no keep requests:
    # Each FEASIBLE FIXED candidate fits available time alone, and all overlapping FIXED pairs
    # are in plan.conflicts (checked above), so (*selected, candidate.activity_id) is guaranteed SCHEDULED.
    all_fixed = (
        not plan.kept
        and candidate.schedule is not None
        and candidate.schedule.type is ScheduleType.FIXED
        and all(plan.by_id[s].schedule is not None and plan.by_id[s].schedule.type is ScheduleType.FIXED for s in selected)
    )
    together_status = ScheduleStatus.SCHEDULED if all_fixed else scheduling((*selected, candidate.activity_id)).status
    if together_status is ScheduleStatus.UNSCHEDULABLE:
        return ExclusionCode.NO_TIME, "No valid schedule exists for it together with the selected activities."
    limits = plan.limits
    if limits.max_activities is not None and len(selected) + 1 > limits.max_activities:
        return ExclusionCode.LIMIT, "Adding it would exceed the activity-count limit."
    if limits.max_duration_minutes is not None:
        duration = math.fsum(plan.by_id[a].minutes for a in (*selected, candidate.activity_id))
        if duration > limits.max_duration_minutes + ABS_TOLERANCE:
            return ExclusionCode.LIMIT, "Adding it would exceed the total-duration limit."
    if together_status is ScheduleStatus.UNDETERMINED:
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
