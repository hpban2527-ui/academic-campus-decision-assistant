"""Independent post-check of a planner_output against its planner_input (sp3-planner/0.2).

``check_plan`` re-derives every section 8-10 obligation from the input and
re-scores the selected set once through ``score_plan`` (plus the previous
activity set once when a previous plan exists). It deliberately does not
import the planner or the scheduler or reuse their decisions; it shares only
contract.py. NO_TIME claims and complete-search counts are verified with the
checker's own brute force (every placement order, each block at its earliest
fit) on sets of at most ``BRUTE_FORCE_FLEXIBLE`` flexible activities; larger
sets are left unverified. It assumes ``planner_input`` is contract-valid. It
does not re-run the search, so it cannot confirm optimality; tests compare
rankings with an oracle.

An empty violation list means the plan passed.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations, permutations
import math
from typing import Any

from sp3.contract import (
    ABS_TOLERANCE,
    CONTRACT_VERSION,
    DEMO_MODE,
    DROPPED_ACTIVITY_FIELDS,
    EXCLUDED_CANDIDATE_FIELDS,
    KEEP_CONFLICT_FIELDS,
    PLANNER_OUTPUT_FIELDS,
    SCORE_COMPARISON_BASIS,
    SCORE_COMPARISON_FIELDS,
    SELECTED_ACTIVITY_FIELDS,
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
    PlannerStatus,
    ProgressStatus,
    ProofKind,
    ReasonCode,
    RegistrationStatus,
    Schedule,
    ScheduleType,
    WarningCode,
    attribution_order,
    build_based_on,
    inside,
    inside_one,
    merge_intervals,
    overlaps,
    plan_version,
    remaining_gap,
    same_instants,
    timestamp,
    usable_window,
    valid_flexible_blocks,
    validate_blocks,
    validate_intervals,
    validate_keep_requests,
    validate_participation,
    validate_previous_plan,
    validate_schedule,
    validate_score_response,
    within_tolerance,
)

__all__ = ["BRUTE_FORCE_FLEXIBLE", "Violation", "check_plan"]

BRUTE_FORCE_FLEXIBLE = 6

_SCORED_STATUSES = {
    PlannerStatus.ALREADY_MET.value, PlannerStatus.TARGET_MET.value,
    PlannerStatus.PARTIAL.value, PlannerStatus.NO_FEASIBLE_CANDIDATES.value,
}
_FAILURE_STATUSES = {PlannerStatus.NEEDS_DATA.value, PlannerStatus.ERROR.value}
_EXPECTED_CONCLUSIONS = {
    PlannerStatus.ALREADY_MET.value: {FeasibilityConclusion.REACHABLE.value},
    PlannerStatus.TARGET_MET.value: {FeasibilityConclusion.REACHABLE.value},
    PlannerStatus.PARTIAL.value: {FeasibilityConclusion.UNDETERMINED.value, FeasibilityConclusion.PROVEN_UNREACHABLE.value},
    PlannerStatus.NO_FEASIBLE_CANDIDATES.value: {FeasibilityConclusion.PROVEN_UNREACHABLE.value},
    PlannerStatus.KEEP_CONFLICT.value: {FeasibilityConclusion.UNDETERMINED.value},
    PlannerStatus.NEEDS_DATA.value: {FeasibilityConclusion.UNDETERMINED.value},
    PlannerStatus.ERROR.value: {FeasibilityConclusion.UNDETERMINED.value},
}
_LIMITED = {LimitReason.EVALUATION_LIMIT.value, LimitReason.SCHEDULING_LIMIT.value}


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    activity_id: str | None = None


def check_plan(
    planner_input: Mapping[str, Any],
    planner_output: Any,
    score_plan: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    input_snapshot: Mapping[str, Any] | None = None,
) -> list[Violation]:
    """Return every violation found; ``input_snapshot`` is a pre-planning deep copy."""
    violations: list[Violation] = []
    if input_snapshot is not None and planner_input != input_snapshot:
        violations.append(Violation("INPUT_MUTATED", "planner_input changed during planning."))
    if not isinstance(planner_output, dict) or set(planner_output) != PLANNER_OUTPUT_FIELDS:
        violations.append(Violation("OUTPUT_SHAPE", "planner_output must have exactly the section-10 fields."))
        return violations
    try:
        _Checker(planner_input, planner_output, score_plan, violations).run()
    except (KeyError, TypeError, AttributeError, ValueError, IndexError):
        violations.append(Violation("OUTPUT_MALFORMED", "planner_output has malformed nested fields."))
    return violations


class _Checker:
    def __init__(self, planner_input: Mapping[str, Any], output: dict[str, Any], score_plan: Callable, violations: list[Violation]) -> None:
        self.input = planner_input
        self.output = output
        self.score_plan = score_plan
        self.violations = violations
        self.candidates = {entry["activity"]["activity_id"]: entry for entry in planner_input["candidates"]}
        self.schedules: dict[str, Schedule | None] = {
            activity_id: None if entry["schedule"] is None else validate_schedule(entry["schedule"], "candidate.schedule")
            for activity_id, entry in self.candidates.items()
        }
        self.participation = {
            activity_id: validate_participation(entry["participation"], "candidate.participation")
            for activity_id, entry in self.candidates.items()
        }
        self.conflicts = {frozenset(pair) for pair in planner_input["conflict_pairs"]}
        self.included = set(planner_input["baseline"]["included_activity_ids"])
        context = planner_input["context"]
        self.window = tuple(timestamp(context[key], "context." + key) for key in ("window_start", "window_end", "as_of"))
        self.available = validate_intervals(planner_input["available_intervals"], "available_intervals")
        self.previous = validate_previous_plan(planner_input["previous_plan"], "previous_plan")
        self.kept = sorted(validate_keep_requests(planner_input["keep_requests"], self.previous, "keep_requests"))
        self.previous_blocks = {} if self.previous is None else dict(self.previous.blocks)
        self.retained = {
            activity_id for activity_id in self.previous_blocks
            if activity_id not in self.included
            and not (activity_id in self.participation and self.participation[activity_id].progress is ProgressStatus.COMPLETED)
        }
        self.schedulable_memo: dict[frozenset[str], bool | None] = {}

    def flag(self, code: str, message: str, activity_id: str | None = None) -> None:
        self.violations.append(Violation(code, message, activity_id))

    def run(self) -> None:
        self.check_envelope()
        status = self.output["status"]
        if status not in _EXPECTED_CONCLUSIONS:
            self.flag("STATUS_UNKNOWN", "status is not a contract status.")
            return
        invalid_input = self.output["search"]["limit_reason"] == LimitReason.INVALID_INPUT.value
        self.check_warnings(invalid_input)
        if self.output["feasibility_conclusion"] not in _EXPECTED_CONCLUSIONS[status]:
            self.flag("STATUS_INCOHERENT", "feasibility_conclusion does not fit the status.")
        if not invalid_input:
            self.check_based_on()
            if self.output["pending_confirmation"] != self.pending_confirmation():
                self.flag("PENDING_CONFIRMATION", "pending_confirmation must list completed, uncounted activities.")
        expected_conflicts = self.expected_keep_conflicts()
        if status == PlannerStatus.KEEP_CONFLICT.value:
            self.check_keep_conflict(expected_conflicts)
            return
        if self.output["keep_conflicts"]:
            self.flag("KEEP_CONFLICT_SHAPE", "keep_conflicts must be empty unless the status is KEEP_CONFLICT.")
        if expected_conflicts and not invalid_input:
            self.flag("KEEP_CONFLICT_MISSED", "keep requests conflict, so the status must be KEEP_CONFLICT.")
        if status in _FAILURE_STATUSES:
            self.check_failure_shape()
            return
        self.check_coverage()
        selected_ids = [entry["activity_id"] for entry in self.output["selected_activities"]]
        blocks = self.check_selection(selected_ids)
        self.check_exclusions(selected_ids)
        self.check_dropped(selected_ids)
        self.check_search(status, selected_ids)
        result = self.rescore(selected_ids, blocks)
        if result is not None:
            self.check_score_summary(result)
            self.check_reasons(result)
            self.check_status(status, selected_ids)
        self.check_score_comparison()
        self.check_plan_version()

    # Envelope, flags and warnings

    def check_envelope(self) -> None:
        output = self.output
        if output["contract_version"] != CONTRACT_VERSION or output["request_id"] != self.input["request_id"] or output["context"] != self.input["context"]:
            self.flag("ENVELOPE_MISMATCH", "contract_version, request_id or context does not match the input.")
        if output["mode"] != DEMO_MODE or output["official_award_verified"] is not False:
            self.flag("DEMO_FLAG", "mode must be DEMO_ONLY and official_award_verified must be false.")

    def check_based_on(self) -> None:
        expected = build_based_on(self.input["context"], None if self.previous is None else self.previous.plan_version)
        if self.output["based_on"] != expected:
            self.flag("BASED_ON_MISMATCH", "based_on must name the context versions and the previous plan version.")

    def pending_confirmation(self) -> list[str]:
        return sorted(
            activity_id for activity_id, participation in self.participation.items()
            if participation.progress is ProgressStatus.COMPLETED and activity_id not in self.included
        )

    def check_warnings(self, invalid_input: bool) -> None:
        codes = [warning["code"] for warning in self.output["warnings"]]
        if len(codes) != len(set(codes)):
            self.flag("WARNING_DUPLICATE", "warning codes repeat.")
        for required in (WarningCode.DEMO_ONLY.value, WarningCode.TRAVEL_NOT_MODELED.value):
            if required not in codes:
                self.flag("MISSING_WARNING", f"warning {required} is required.")
        registered = any(entry["registered"] is True for entry in self.output["dropped_activities"])
        if registered != (WarningCode.DROPS_REGISTERED.value in codes):
            self.flag("DROPS_REGISTERED_WARNING", "DROPS_REGISTERED must appear exactly when a dropped activity is registered.")
        if invalid_input:
            return
        pending = any(entry["feasibility"]["status"] == FeasibilityStatus.NEEDS_REVIEW.value for entry in self.candidates.values())
        if pending != (WarningCode.PENDING_CANDIDATES.value in codes):
            self.flag("PENDING_WARNING", "PENDING_CANDIDATES must appear exactly when review is outstanding.")
        if bool(self.pending_confirmation()) != (WarningCode.PENDING_CONFIRMATION.value in codes):
            self.flag("PENDING_CONFIRMATION_WARNING", "PENDING_CONFIRMATION must appear exactly when completed activities await confirmation.")
        status = self.output["status"]
        stopped_early = status in _SCORED_STATUSES and self.output["search"]["complete"] is False and status != PlannerStatus.ALREADY_MET.value
        if stopped_early != (WarningCode.SEARCH_INCOMPLETE.value in codes):
            self.flag("SEARCH_WARNING", "SEARCH_INCOMPLETE must appear exactly when a scored search stopped early.")

    def check_failure_shape(self) -> None:
        output, search = self.output, self.output["search"]
        if output["selected_activities"] or output["excluded_candidates"] or output["score_summary"] is not None or output["proof"] is not None:
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR must not contain selections, exclusions, scores or a proof.")
        if output["dropped_activities"] or output["score_comparison"] is not None or output["plan_version"] is not None:
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR must not contain plan changes, a comparison or a plan version.")
        if search["complete"] is not False or search["optimality_proven"] is not False:
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR must not claim a complete or optimal search.")
        if search["limit_reason"] not in (LimitReason.SP2_FAILURE.value, LimitReason.INVALID_INPUT.value):
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR requires limit_reason SP2_FAILURE or INVALID_INPUT.")
        if not output["errors"]:
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR requires at least one error.")

    # Keep requests

    def is_eligible(self, activity_id: str) -> bool:
        entry = self.candidates.get(activity_id)
        return (
            entry is not None
            and entry["feasibility"]["status"] == FeasibilityStatus.FEASIBLE.value
            and self.participation[activity_id].progress is ProgressStatus.NOT_STARTED
            and activity_id not in self.included
        )

    def minutes(self, activity_id: str) -> float:
        return self.schedules[activity_id].planned_minutes

    def expected_keep_conflicts(self) -> list[tuple[str, str]]:
        """(activity_id, code) entries that section 10.4 requires, in output order.

        Pair-level codes appear once per other kept activity, ordered by its ID.
        """
        if not self.kept:
            return []
        found: dict[str, list[tuple[str, str]]] = {activity_id: [] for activity_id in self.kept}
        passing = []
        for activity_id in self.kept:
            blocks = self.previous_blocks[activity_id]
            schedule = self.schedules.get(activity_id)
            if activity_id not in self.candidates:
                found[activity_id].append((KeepConflictCode.NOT_LISTED.value, ""))
            elif not self.is_eligible(activity_id):
                found[activity_id].append((KeepConflictCode.NOT_ELIGIBLE.value, ""))
            elif schedule.type is ScheduleType.FIXED and not same_instants(blocks, schedule.fixed_blocks):
                found[activity_id].append((KeepConflictCode.FIXED_CHANGED.value, ""))
            elif schedule.type is ScheduleType.FLEXIBLE_WINDOW and not valid_flexible_blocks(schedule, blocks, self.available, *self.window):
                found[activity_id].append((KeepConflictCode.BLOCK_INVALID.value, ""))
            else:
                passing.append(activity_id)
        for left, right in combinations(passing, 2):
            if any(overlaps(a, b) for a in self.previous_blocks[left] for b in self.previous_blocks[right]):
                code = KeepConflictCode.BLOCK_OVERLAP.value
            elif frozenset((left, right)) in self.conflicts:
                code = KeepConflictCode.CONFLICT.value
            else:
                continue
            found[left].append((code, right))
            found[right].append((code, left))
        limits = self.input["limits"]
        minutes = math.fsum(self.minutes(a) for a in passing)
        if (limits["max_activities"] is not None and len(self.kept) > limits["max_activities"]) or (
            limits["max_duration_minutes"] is not None and minutes > limits["max_duration_minutes"] + ABS_TOLERANCE
        ):
            for activity_id in self.kept:
                found[activity_id].append((KeepConflictCode.LIMIT.value, ""))
        order = [code.value for code in KeepConflictCode]
        return [
            (activity_id, code)
            for activity_id in self.kept
            for code, _ in sorted(found[activity_id], key=lambda item: (order.index(item[0]), item[1]))
        ]

    def check_keep_conflict(self, expected: list[tuple[str, str]]) -> None:
        output = self.output
        if output["selected_activities"] or output["excluded_candidates"] or output["dropped_activities"]:
            self.flag("KEEP_CONFLICT_SHAPE", "KEEP_CONFLICT must not select, exclude or drop activities.")
        if output["score_summary"] is not None or output["proof"] is not None or output["score_comparison"] is not None or output["plan_version"] is not None:
            self.flag("KEEP_CONFLICT_SHAPE", "KEEP_CONFLICT must not contain scores, a proof, a comparison or a plan version.")
        if output["search"] != {"complete": False, "optimality_proven": False, "evaluated_subsets": 0, "limit_reason": LimitReason.KEEP_CONFLICT.value}:
            self.flag("KEEP_CONFLICT_SHAPE", "KEEP_CONFLICT must be returned before any scoring.")
        if output["errors"]:
            self.flag("KEEP_CONFLICT_SHAPE", "KEEP_CONFLICT is not an error.")
        entries = output["keep_conflicts"]
        for entry in entries:
            if set(entry) != KEEP_CONFLICT_FIELDS or not isinstance(entry["message"], str) or not entry["message"].strip():
                self.flag("KEEP_CONFLICT_SHAPE", "keep_conflicts entries need activity_id, code and a message.")
        listed = [(entry["activity_id"], entry["code"]) for entry in entries]
        if not expected or listed != expected:
            self.flag("KEEP_CONFLICT_MISMATCH", "keep_conflicts must list every section 10.4 conflict in order.")

    # Selection and exclusions

    def check_coverage(self) -> None:
        listed = [entry["activity_id"] for entry in self.output["selected_activities"]]
        listed += [entry["activity_id"] for entry in self.output["excluded_candidates"]]
        for activity_id in self.candidates:
            if listed.count(activity_id) != 1:
                self.flag("CANDIDATE_COVERAGE", "every candidate must appear exactly once.", activity_id)
        for activity_id in set(listed) - set(self.candidates):
            self.flag("CANDIDATE_COVERAGE", "output lists an unknown activity.", activity_id)
        if self.output["errors"]:
            self.flag("UNEXPECTED_ERRORS", "successful scoring must have no errors.")

    def check_selection(self, selected_ids: list[str]) -> dict[str, tuple[Interval, ...]]:
        """Check each selected entry and return its parsed blocks."""
        parsed: dict[str, tuple[Interval, ...]] = {}
        for entry in self.output["selected_activities"]:
            activity_id = entry["activity_id"]
            if set(entry) != SELECTED_ACTIVITY_FIELDS:
                self.flag("SELECTED_DETAILS", "selected entries need exactly the section-10.2 fields.", activity_id)
                continue
            if not self.is_eligible(activity_id):
                self.flag("SELECTED_NOT_ELIGIBLE", "selected activity is not FEASIBLE, has started or is already counted.", activity_id)
                continue
            schedule = self.schedules[activity_id]
            candidate = self.candidates[activity_id]
            if (entry["title"], entry["schedule_type"], entry["registration"]) != (
                candidate["activity"]["title"], schedule.type.value, self.participation[activity_id].registration.value,
            ):
                self.flag("SELECTED_DETAILS", "title, schedule type or registration differs from the candidate.", activity_id)
            try:
                blocks = validate_blocks(entry["scheduled_blocks"], "scheduled_blocks")
            except ContractError:
                self.flag("SELECTED_BLOCKS", "scheduled_blocks must be non-empty, sorted and non-overlapping.", activity_id)
                continue
            parsed[activity_id] = blocks
            if schedule.type is ScheduleType.FIXED:
                if entry["scheduled_blocks"] != candidate["schedule"]["fixed_blocks"] or not all(inside_one(b, self.available) for b in blocks):
                    self.flag("SELECTED_BLOCKS", "FIXED blocks must equal fixed_blocks inside available time.", activity_id)
            elif not valid_flexible_blocks(schedule, blocks, self.available, *self.window):
                self.flag("SELECTED_BLOCKS", "a flexible activity needs one sitting of its duration inside its usable window and one available interval.", activity_id)
            if entry["change"] != self.expected_change(activity_id, blocks):
                self.flag("CHANGE_LABEL", "change must be ADDED, KEPT or MOVED as compared with previous_plan.", activity_id)
        everything = sorted((block, activity_id) for activity_id, blocks in parsed.items() for block in blocks)
        for (left, left_id), (right, right_id) in zip(everything, everything[1:]):
            if overlaps(left, right):
                self.flag("SELECTED_OVERLAP", f"selected blocks of {left_id} and {right_id} overlap.", left_id)
        for activity_id in self.kept:
            if activity_id not in parsed or not same_instants(parsed[activity_id], self.previous_blocks[activity_id]):
                self.flag("KEEP_NOT_HONORED", "a kept activity must be selected with its previous blocks.", activity_id)
        for left, right in combinations(selected_ids, 2):
            if frozenset((left, right)) in self.conflicts:
                self.flag("SELECTED_CONFLICT", f"selected activities {left} and {right} conflict.", left)
        if not all(self.is_eligible(activity_id) for activity_id in selected_ids):
            return parsed
        if self.violates_limits(selected_ids):
            self.flag("LIMIT_VIOLATED", "the selected set exceeds a stated limit.")
        if len(parsed) == len(selected_ids):
            order = sorted(selected_ids, key=lambda activity_id: (parsed[activity_id][0][0], activity_id))
            if selected_ids != order:
                self.flag("SELECTED_ORDER", "selected activities must be ordered by first block start, then ID.")
        return parsed

    def expected_change(self, activity_id: str, blocks: Sequence[Interval]) -> str:
        if activity_id not in self.previous_blocks:
            return ChangeLabel.ADDED.value
        return ChangeLabel.KEPT.value if same_instants(blocks, self.previous_blocks[activity_id]) else ChangeLabel.MOVED.value

    def violates_limits(self, activity_ids: Iterable[str]) -> bool:
        activity_ids = list(activity_ids)
        limits = self.input["limits"]
        if limits["max_activities"] is not None and len(activity_ids) > limits["max_activities"]:
            return True
        if limits["max_duration_minutes"] is not None:
            return math.fsum(self.minutes(a) for a in activity_ids) > limits["max_duration_minutes"] + ABS_TOLERANCE
        return False

    def allowed_exclusions(self, activity_id: str, selected_ids: list[str]) -> set[str]:
        status = self.candidates[activity_id]["feasibility"]["status"]
        if status == FeasibilityStatus.NEEDS_REVIEW.value:
            return {ExclusionCode.NEEDS_REVIEW.value}
        if status == FeasibilityStatus.INFEASIBLE.value or self.participation[activity_id].progress is not ProgressStatus.NOT_STARTED:
            return {ExclusionCode.NOT_FEASIBLE.value}
        if activity_id in self.included:
            return {ExclusionCode.ALREADY_COUNTED.value}
        if any(frozenset((activity_id, other)) in self.conflicts for other in selected_ids):
            return {ExclusionCode.CONFLICT.value}
        fallback = ExclusionCode.LIMIT.value if self.violates_limits([*selected_ids, activity_id]) else ExclusionCode.LOWER_PRIORITY.value
        schedulable = self.schedulable([*selected_ids, activity_id])
        if schedulable is None:
            return {ExclusionCode.NO_TIME.value, fallback}
        if schedulable:
            return {fallback}
        # An incomplete search may not have determined the joint schedule.
        return {ExclusionCode.NO_TIME.value} if self.output["search"]["complete"] else {ExclusionCode.NO_TIME.value, fallback}

    def check_exclusions(self, selected_ids: list[str]) -> None:
        valid_codes = {code.value for code in ExclusionCode}
        eligible_selection = [a for a in selected_ids if self.is_eligible(a)]
        for entry in self.output["excluded_candidates"]:
            activity_id, code = entry["activity_id"], entry["code"]
            if activity_id not in self.candidates:
                continue
            if set(entry) != EXCLUDED_CANDIDATE_FIELDS or code not in valid_codes:
                self.flag("EXCLUSION_CODE", "exclusion code is not a contract code.", activity_id)
            elif code not in self.allowed_exclusions(activity_id, eligible_selection):
                self.flag("EXCLUSION_CODE", f"exclusion code {code} does not follow the contract order.", activity_id)
            if not isinstance(entry["message"], str) or not entry["message"].strip():
                self.flag("EXCLUSION_MESSAGE", "exclusion message must be non-empty.", activity_id)

    def check_dropped(self, selected_ids: list[str]) -> None:
        excluded = {entry["activity_id"]: entry["code"] for entry in self.output["excluded_candidates"]}
        expected = []
        for activity_id in sorted(self.retained - set(selected_ids), key=lambda a: (self.previous_blocks[a][0][0], a)):
            if activity_id not in self.candidates:
                expected.append((activity_id, False, DroppedCode.NOT_LISTED.value))
                continue
            participation = self.participation[activity_id]
            if participation.progress is ProgressStatus.CANCELLED:
                code = DroppedCode.CANCELLED.value
            elif self.candidates[activity_id]["feasibility"]["status"] != FeasibilityStatus.FEASIBLE.value:
                code = DroppedCode.NO_LONGER_FEASIBLE.value
            elif excluded.get(activity_id) == ExclusionCode.NO_TIME.value:
                code = DroppedCode.NO_TIME.value
            else:
                code = DroppedCode.LOWER_PRIORITY.value
            expected.append((activity_id, participation.registration is RegistrationStatus.REGISTERED, code))
        entries = self.output["dropped_activities"]
        if any(set(entry) != DROPPED_ACTIVITY_FIELDS or not isinstance(entry["message"], str) or not entry["message"].strip() for entry in entries):
            self.flag("DROPPED_SHAPE", "dropped entries need activity_id, registered, code and a message.")
        if [(entry["activity_id"], entry["registered"], entry["code"]) for entry in entries] != expected:
            self.flag("DROPPED_MISMATCH", "dropped_activities must list every unselected previous activity with its code.")

    # Schedulability brute force

    def schedulable(self, activity_ids: Iterable[str]) -> bool | None:
        """Whether the set has a valid joint schedule; None when it is too large to check."""
        key = frozenset(activity_ids)
        if key not in self.schedulable_memo:
            self.schedulable_memo[key] = self._schedulable(key)
        return self.schedulable_memo[key]

    def _schedulable(self, key: frozenset[str]) -> bool | None:
        busy: list[Interval] = []
        flexible: list[tuple[Interval, timedelta]] = []
        for activity_id in sorted(key):
            schedule = self.schedules[activity_id]
            if activity_id in self.kept:
                busy.extend(self.previous_blocks[activity_id])
            elif schedule.type is ScheduleType.FIXED:
                busy.extend(schedule.fixed_blocks)
            else:
                usable = usable_window(schedule, *self.window)
                if usable is None:
                    return False
                flexible.append((usable, timedelta(minutes=schedule.duration_minutes)))
        busy.sort()
        if not all(inside_one(block, self.available) for block in busy) or any(overlaps(a, b) for a, b in zip(busy, busy[1:])):
            return False
        if len(flexible) > BRUTE_FORCE_FLEXIBLE:
            return None
        free = _subtract(self.available, busy)
        for order in permutations(flexible):
            cursor: datetime | None = None
            for usable, duration in order:
                start = _first_fit(free, usable, duration, cursor)
                if start is None:
                    break
                cursor = start + duration
            else:
                return True
        return False

    # Search block and status

    def eligible_ids(self) -> list[str]:
        return sorted(a for a in self.candidates if self.is_eligible(a))

    def count_valid_subsets(self, stop_after: int, *, schedulable: bool = True) -> int | None:
        """Count supersets of the kept set that are valid, stopping past ``stop_after``.

        Returns None when a subset is too large for the brute force.
        """
        extras = [a for a in self.eligible_ids() if a not in self.kept]
        total = 0
        uncertain = False

        def visit(start: int, chosen: list[str]) -> None:
            nonlocal total, uncertain
            total += 1
            for index in range(start, len(extras)):
                if total > stop_after:
                    return
                candidate = [*chosen, extras[index]]
                if any(frozenset((extras[index], other)) in self.conflicts for other in candidate[:-1]) or self.violates_limits(candidate):
                    continue
                if schedulable:
                    joint = self.schedulable(candidate)
                    if joint is None:
                        uncertain = True
                        continue
                    if not joint:
                        continue
                visit(index + 1, candidate)

        visit(0, list(self.kept))
        return None if uncertain else total

    def check_search(self, status: str, selected_ids: list[str]) -> None:
        search, proof = self.output["search"], self.output["proof"]
        evaluated = search["evaluated_subsets"]
        if type(evaluated) is not int or evaluated < 1:
            self.flag("SEARCH_COUNT", "scored outcomes require at least the base-set evaluation.")
            return
        if status == PlannerStatus.ALREADY_MET.value:
            if search != {"complete": False, "optimality_proven": True, "evaluated_subsets": 1, "limit_reason": LimitReason.ALREADY_MET.value} or selected_ids:
                self.flag("ALREADY_MET_SHAPE", "ALREADY_MET must return the empty plan after one evaluation.")
            if self.previous is not None:
                self.flag("ALREADY_MET_SHAPE", "ALREADY_MET is not allowed with a previous plan.")
        elif search["limit_reason"] in _LIMITED:
            if search["complete"] or search["optimality_proven"]:
                self.flag("SEARCH_OVERCLAIM", "a budget or scheduling limit cannot prove completeness or optimality.")
        elif search["limit_reason"] is not None:
            self.flag("SEARCH_LIMIT_REASON", "limit_reason does not fit a scored outcome.")
        elif not search["optimality_proven"]:
            self.flag("SEARCH_OVERCLAIM", "a search without a limit must have proven optimality.")
        if search["complete"]:
            count = self.count_valid_subsets(evaluated)
            if count is not None and count != evaluated:
                self.flag("SEARCH_COUNT", "a complete search must evaluate every valid subset exactly once.")
        elif status != PlannerStatus.ALREADY_MET.value and search["limit_reason"] is None:
            # Larger subsets were left unscored: some unscored candidate subset must exist.
            if self.count_valid_subsets(evaluated, schedulable=False) <= evaluated:
                self.flag("SEARCH_COUNT", "search reports unexplored subsets but none remain.")
        if self.output["feasibility_conclusion"] == FeasibilityConclusion.PROVEN_UNREACHABLE.value:
            expected_proof = {"kind": ProofKind.EXHAUSTIVE_SEARCH.value, "evaluated_subsets": evaluated}
            if not search["complete"] or proof != expected_proof:
                self.flag("UNPROVEN_UNREACHABLE", "PROVEN_UNREACHABLE requires a complete search and a matching proof.")
        elif proof is not None:
            self.flag("UNEXPECTED_PROOF", "a proof is only allowed with PROVEN_UNREACHABLE.")

    def check_status(self, status: str, selected_ids: list[str]) -> None:
        summary = self.output["score_summary"]
        remaining = list(summary["remaining_by_category"].values())
        if summary["remaining_total"] is not None:
            remaining.append(summary["remaining_total"])
        met = all(value == 0 for value in remaining)
        if status in (PlannerStatus.ALREADY_MET.value, PlannerStatus.TARGET_MET.value) and not met:
            self.flag("STATUS_INCOHERENT", f"{status} requires zero remaining gaps.")
        if status in (PlannerStatus.PARTIAL.value, PlannerStatus.NO_FEASIBLE_CANDIDATES.value) and met:
            self.flag("STATUS_INCOHERENT", f"{status} requires a remaining gap.")
        if status == PlannerStatus.NO_FEASIBLE_CANDIDATES.value and (self.eligible_ids() or selected_ids):
            self.flag("STATUS_INCOHERENT", "NO_FEASIBLE_CANDIDATES requires no eligible candidates.")
        if status == PlannerStatus.PARTIAL.value and not self.eligible_ids():
            self.flag("STATUS_INCOHERENT", "PARTIAL without eligible candidates must be NO_FEASIBLE_CANDIDATES.")

    # Scores, reasons, comparison and version

    def score(self, activity_ids: Sequence[str], first_starts: Mapping[str, datetime]) -> Mapping[str, Any] | None:
        request = {
            "contract_version": CONTRACT_VERSION,
            "request_id": self.input["request_id"],
            "context": deepcopy(self.input["context"]),
            "baseline": deepcopy(self.input["baseline"]),
            "selected_activity_ids": sorted(activity_ids),
            "attribution_order": attribution_order(first_starts),
        }
        expected = deepcopy(request)
        try:
            response = deepcopy(self.score_plan(request))
            validate_score_response(response, expected, allowed_statuses=[s.value for s in EvaluationStatus])
        except Exception:
            return None
        if response["evaluation_status"] != EvaluationStatus.OK.value:
            return None
        return response["result"]

    def rescore(self, selected_ids: list[str], blocks: Mapping[str, tuple[Interval, ...]]) -> Mapping[str, Any] | None:
        if set(blocks) != set(selected_ids):
            return None
        result = self.score(selected_ids, {a: blocks[a][0][0] for a in selected_ids})
        if result is None:
            self.flag("RESCORE_FAILED", "re-scoring the selected set did not return a valid OK response.")
        return result

    def check_score_summary(self, result: Mapping[str, Any]) -> None:
        summary, baseline, goals = self.output["score_summary"], self.input["baseline"], self.input["goals"]
        if not isinstance(summary, dict):
            self.flag("SCORE_SUMMARY_MISMATCH", "scored outcomes require a score_summary.")
            return
        after = result["category_after"]
        expected_remaining = {c: remaining_gap(t, after[c]) for c, t in goals["category_targets"].items()}
        total_target = goals["total_target"]
        pairs = [
            (summary["baseline_by_category"], baseline["category_scores"]),
            (summary["projected_by_category"], after),
            (summary["gain_by_category"], result["category_gain"]),
            (summary["remaining_by_category"], expected_remaining),
        ]
        consistent = all(_maps_close(actual, expected) for actual, expected in pairs)
        consistent &= _close(summary["baseline_total"], baseline["total_score"])
        consistent &= _close(summary["projected_total"], result["total_after"])
        consistent &= _close(summary["gain_total"], result["total_gain"])
        if total_target is None:
            consistent &= summary["remaining_total"] is None
        else:
            consistent &= _close(summary["remaining_total"], remaining_gap(total_target, result["total_after"]))
        if not consistent:
            self.flag("SCORE_SUMMARY_MISMATCH", "score_summary differs from the re-scored selected set.")

    def check_reasons(self, result: Mapping[str, Any]) -> None:
        preferences = self.input["preferences"]
        contributions = {item["activity_id"]: item for item in result["contributions"]}
        for entry in self.output["selected_activities"]:
            activity_id = entry["activity_id"]
            if activity_id not in self.candidates:
                continue
            activity = self.candidates[activity_id]["activity"]
            goal = [r for r in entry["reasons"] if r["code"] == ReasonCode.GOAL_CONTRIBUTION.value]
            preference = [r for r in entry["reasons"] if r["code"] == ReasonCode.PREFERENCE_MATCH.value]
            if len(goal) + len(preference) != len(entry["reasons"]):
                self.flag("REASON_MISMATCH", "reason code is not a contract code.", activity_id)
            contribution = contributions.get(activity_id)
            if contribution is None or len(goal) != 1 or goal[0]["category_id"] != contribution["category_id"] or not _close(goal[0]["projected_added"], contribution["projected_added"]):
                self.flag("REASON_MISMATCH", "GOAL_CONTRIBUTION must match the scorer contribution for the scheduled order.", activity_id)
            expected_matches = int(activity["domain"] in preferences["preferred_domains"]) + int(activity["mode"] in preferences["preferred_modes"])
            if len(preference) != expected_matches or any(r["category_id"] is not None or r["projected_added"] is not None for r in preference):
                self.flag("REASON_MISMATCH", "PREFERENCE_MATCH must reflect actual matches only.", activity_id)

    def check_score_comparison(self) -> None:
        comparison = self.output["score_comparison"]
        if self.previous is None:
            if comparison is not None:
                self.flag("SCORE_COMPARISON", "score_comparison must be null without a previous plan.")
            return
        if not isinstance(comparison, dict) or set(comparison) != SCORE_COMPARISON_FIELDS:
            self.flag("SCORE_COMPARISON", "score_comparison needs the documented fields with a previous plan.")
            return
        ids = sorted(a for a in self.retained if self.is_eligible(a))
        if comparison["basis"] != SCORE_COMPARISON_BASIS or comparison["previous_activity_ids"] != ids:
            self.flag("SCORE_COMPARISON", "score_comparison must rescore the eligible previous activities.")
            return
        result = self.score(ids, {a: self.previous_blocks[a][0][0] for a in ids})
        summary = self.output["score_summary"]
        if result is None or not (
            _maps_close(comparison["previous_projected_by_category"], result["category_after"])
            and _close(comparison["previous_projected_total"], result["total_after"])
            and isinstance(summary, dict) and _close(comparison["new_projected_total"], summary["projected_total"])
        ):
            self.flag("SCORE_COMPARISON", "score_comparison differs from a rescore of the previous activity set.")

    def check_plan_version(self) -> None:
        selected = [(entry["activity_id"], entry["scheduled_blocks"]) for entry in self.output["selected_activities"]]
        try:
            expected = plan_version(self.output["based_on"], selected)
        except ContractError:
            expected = None
        if self.output["plan_version"] != expected:
            self.flag("PLAN_VERSION", "plan_version does not match based_on and the planned blocks.")


def _subtract(available: Sequence[Interval], busy: Sequence[Interval]) -> list[Interval]:
    free = []
    for start, end in merge_intervals(available):
        cursor = start
        for busy_start, busy_end in busy:
            if busy_end <= cursor or busy_start >= end:
                continue
            if busy_start > cursor:
                free.append((cursor, busy_start))
            cursor = max(cursor, busy_end)
        if cursor < end:
            free.append((cursor, end))
    return free


def _first_fit(free: Sequence[Interval], usable: Interval, duration: timedelta, after: datetime | None) -> datetime | None:
    """Earliest start at or after ``after`` that fits the usable window and one free interval."""
    for start, end in free:
        begin = max(start, usable[0]) if after is None else max(start, usable[0], after)
        block = (begin, begin + duration)
        if block[1] <= end and inside(block, usable):
            return begin
    return None


def _close(actual: Any, expected: Any) -> bool:
    numeric = (int, float)
    if type(actual) not in numeric or type(expected) not in numeric:
        return False
    return within_tolerance(actual, expected)


def _maps_close(actual: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(actual, dict) and actual.keys() == expected.keys() and all(_close(actual[k], expected[k]) for k in expected)
