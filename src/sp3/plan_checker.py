"""Independent post-check of a planner_output against its planner_input.

``check_plan`` re-derives every section-7/8 obligation from the input and
re-scores the selected set once through ``score_plan``. It deliberately does
not import the planner or reuse its decisions; it shares only contract.py.
It assumes ``planner_input`` is contract-valid. It does not re-run the search,
so it cannot confirm optimality; tests compare rankings with an oracle.

An empty violation list means the plan passed.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from sp3.contract import (
    ABS_TOLERANCE,
    CONTRACT_VERSION,
    DEMO_MODE,
    PLANNER_OUTPUT_FIELDS,
    EvaluationStatus,
    ExclusionCode,
    FeasibilityConclusion,
    FeasibilityStatus,
    LimitReason,
    PlannerStatus,
    ProofKind,
    ReasonCode,
    WarningCode,
    remaining_gap,
    timestamp,
    validate_score_response,
    within_tolerance,
)

__all__ = ["Violation", "check_plan"]

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
    PlannerStatus.NEEDS_DATA.value: {FeasibilityConclusion.UNDETERMINED.value},
    PlannerStatus.ERROR.value: {FeasibilityConclusion.UNDETERMINED.value},
}


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
        violations.append(Violation("OUTPUT_SHAPE", "planner_output must have exactly the section-7 fields."))
        return violations
    try:
        _Checker(planner_input, planner_output, score_plan, violations).run()
    except (KeyError, TypeError, AttributeError, ValueError):
        violations.append(Violation("OUTPUT_MALFORMED", "planner_output has malformed nested fields."))
    return violations


class _Checker:
    def __init__(self, planner_input: Mapping[str, Any], output: dict[str, Any], score_plan: Callable, violations: list[Violation]) -> None:
        self.input = planner_input
        self.output = output
        self.score_plan = score_plan
        self.violations = violations
        self.candidates = {entry["activity"]["activity_id"]: entry for entry in planner_input["candidates"]}
        self.conflicts = {frozenset(pair) for pair in planner_input["conflict_pairs"]}
        self.included = set(planner_input["baseline"]["included_activity_ids"])

    def flag(self, code: str, message: str, activity_id: str | None = None) -> None:
        self.violations.append(Violation(code, message, activity_id))

    def run(self) -> None:
        self.check_envelope()
        self.check_warnings()
        status = self.output["status"]
        if status not in _EXPECTED_CONCLUSIONS:
            self.flag("STATUS_UNKNOWN", "status is not a contract status.")
            return
        if self.output["feasibility_conclusion"] not in _EXPECTED_CONCLUSIONS[status]:
            self.flag("STATUS_INCOHERENT", "feasibility_conclusion does not fit the status.")
        if status in _FAILURE_STATUSES:
            self.check_failure_shape()
            return
        self.check_coverage()
        selected_ids = [entry["activity_id"] for entry in self.output["selected_activities"]]
        self.check_selection(selected_ids)
        self.check_exclusions(selected_ids)
        self.check_search(status, selected_ids)
        result = self.rescore(selected_ids)
        if result is not None:
            self.check_score_summary(result)
            self.check_reasons(result)
            self.check_status(status, selected_ids)

    # Envelope and flags

    def check_envelope(self) -> None:
        output = self.output
        if output["contract_version"] != CONTRACT_VERSION or output["request_id"] != self.input["request_id"] or output["context"] != self.input["context"]:
            self.flag("ENVELOPE_MISMATCH", "contract_version, request_id or context does not match the input.")
        if output["mode"] != DEMO_MODE or output["official_award_verified"] is not False:
            self.flag("DEMO_FLAG", "mode must be DEMO_ONLY and official_award_verified must be false.")

    def check_warnings(self) -> None:
        codes = [warning["code"] for warning in self.output["warnings"]]
        if len(codes) != len(set(codes)):
            self.flag("WARNING_DUPLICATE", "warning codes repeat.")
        for required in (WarningCode.DEMO_ONLY.value, WarningCode.TRAVEL_NOT_MODELED.value):
            if required not in codes:
                self.flag("MISSING_WARNING", f"warning {required} is required.")
        if self.output["search"]["limit_reason"] == LimitReason.INVALID_INPUT.value:
            return
        pending = any(entry["feasibility"]["status"] == FeasibilityStatus.NEEDS_REVIEW.value for entry in self.candidates.values())
        if pending != (WarningCode.PENDING_CANDIDATES.value in codes):
            self.flag("PENDING_WARNING", "PENDING_CANDIDATES must appear exactly when review is outstanding.")
        if self.output["status"] in _SCORED_STATUSES:
            stopped_early = self.output["search"]["complete"] is False and self.output["status"] != PlannerStatus.ALREADY_MET.value
            if stopped_early != (WarningCode.SEARCH_INCOMPLETE.value in codes):
                self.flag("SEARCH_WARNING", "SEARCH_INCOMPLETE must appear exactly when search stopped early.")

    def check_failure_shape(self) -> None:
        output, search = self.output, self.output["search"]
        if output["selected_activities"] or output["score_summary"] is not None or output["proof"] is not None:
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR must not contain selections, scores or a proof.")
        if search["complete"] is not False or search["optimality_proven"] is not False:
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR must not claim a complete or optimal search.")
        if search["limit_reason"] not in (LimitReason.SP2_FAILURE.value, LimitReason.INVALID_INPUT.value):
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR requires limit_reason SP2_FAILURE or INVALID_INPUT.")
        if not output["errors"]:
            self.flag("FAILURE_SHAPE", "NEEDS_DATA/ERROR requires at least one error.")

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

    def is_eligible(self, activity_id: str) -> bool:
        entry = self.candidates.get(activity_id)
        return entry is not None and entry["feasibility"]["status"] == FeasibilityStatus.FEASIBLE.value and activity_id not in self.included

    def check_selection(self, selected_ids: list[str]) -> None:
        for entry in self.output["selected_activities"]:
            activity_id = entry["activity_id"]
            if not self.is_eligible(activity_id):
                self.flag("SELECTED_NOT_ELIGIBLE", "selected activity is not FEASIBLE or is already counted.", activity_id)
                continue
            activity = self.candidates[activity_id]["activity"]
            if (entry["title"], entry["start"], entry["end"]) != (activity["title"], activity["start"], activity["end"]):
                self.flag("SELECTED_DETAILS", "title or schedule differs from the candidate.", activity_id)
        for index, left in enumerate(selected_ids):
            for right in selected_ids[index + 1:]:
                if frozenset((left, right)) in self.conflicts:
                    self.flag("SELECTED_CONFLICT", f"selected activities {left} and {right} conflict.", left)
        if not all(self.is_eligible(activity_id) for activity_id in selected_ids):
            return
        if self.violates_limits(selected_ids):
            self.flag("LIMIT_VIOLATED", "the selected set exceeds a stated limit.")
        order = sorted(selected_ids, key=lambda activity_id: (self.start(activity_id), activity_id))
        if selected_ids != order:
            self.flag("SELECTED_ORDER", "selected activities must be ordered by start time, then ID.")

    def start(self, activity_id: str) -> datetime:
        return timestamp(self.candidates[activity_id]["activity"]["start"], "activity.start")

    def minutes(self, activity_id: str) -> float:
        activity = self.candidates[activity_id]["activity"]
        end = timestamp(activity["end"], "activity.end")
        return (end - self.start(activity_id)).total_seconds() / 60

    def violates_limits(self, activity_ids: list[str]) -> bool:
        limits = self.input["limits"]
        if limits["max_activities"] is not None and len(activity_ids) > limits["max_activities"]:
            return True
        if limits["max_duration_minutes"] is not None:
            return math.fsum(self.minutes(a) for a in activity_ids) > limits["max_duration_minutes"] + ABS_TOLERANCE
        return False

    def expected_exclusion(self, activity_id: str, selected_ids: list[str]) -> str:
        status = self.candidates[activity_id]["feasibility"]["status"]
        if status == FeasibilityStatus.NEEDS_REVIEW.value:
            return ExclusionCode.NEEDS_REVIEW.value
        if status == FeasibilityStatus.INFEASIBLE.value:
            return ExclusionCode.NOT_FEASIBLE.value
        if activity_id in self.included:
            return ExclusionCode.ALREADY_COUNTED.value
        if any(frozenset((activity_id, other)) in self.conflicts for other in selected_ids):
            return ExclusionCode.CONFLICT.value
        if self.violates_limits([*selected_ids, activity_id]):
            return ExclusionCode.LIMIT.value
        return ExclusionCode.LOWER_PRIORITY.value

    def check_exclusions(self, selected_ids: list[str]) -> None:
        valid_codes = {code.value for code in ExclusionCode}
        eligible_selection = [a for a in selected_ids if self.is_eligible(a)]
        for entry in self.output["excluded_candidates"]:
            activity_id, code = entry["activity_id"], entry["code"]
            if activity_id not in self.candidates:
                continue
            if code not in valid_codes:
                self.flag("EXCLUSION_CODE", "exclusion code is not a contract code.", activity_id)
            elif code != self.expected_exclusion(activity_id, eligible_selection):
                self.flag("EXCLUSION_CODE", f"exclusion code {code} does not follow the contract order.", activity_id)
            if not isinstance(entry["message"], str) or not entry["message"].strip():
                self.flag("EXCLUSION_MESSAGE", "exclusion message must be non-empty.", activity_id)

    # Search block and status

    def eligible_ids(self) -> list[str]:
        return sorted(a for a in self.candidates if self.is_eligible(a))

    def count_valid_subsets(self, stop_after: int) -> int:
        """Count valid subsets including the empty set, stopping past ``stop_after``."""
        ids = self.eligible_ids()
        total = 0

        def visit(start: int, chosen: list[str]) -> None:
            nonlocal total
            total += 1
            for index in range(start, len(ids)):
                if total > stop_after:
                    return
                candidate = [*chosen, ids[index]]
                if any(frozenset((ids[index], other)) in self.conflicts for other in chosen) or self.violates_limits(candidate):
                    continue
                visit(index + 1, candidate)

        visit(0, [])
        return total

    def check_search(self, status: str, selected_ids: list[str]) -> None:
        search, proof = self.output["search"], self.output["proof"]
        evaluated = search["evaluated_subsets"]
        if type(evaluated) is not int or evaluated < 1:
            self.flag("SEARCH_COUNT", "scored outcomes require at least the empty-set evaluation.")
            return
        if status == PlannerStatus.ALREADY_MET.value:
            if search != {"complete": False, "optimality_proven": True, "evaluated_subsets": 1, "limit_reason": LimitReason.ALREADY_MET.value} or selected_ids:
                self.flag("ALREADY_MET_SHAPE", "ALREADY_MET must return the empty plan after one evaluation.")
        elif search["limit_reason"] == LimitReason.EVALUATION_LIMIT.value:
            if search["complete"] or search["optimality_proven"]:
                self.flag("SEARCH_OVERCLAIM", "an exhausted budget cannot prove completeness or optimality.")
        elif search["limit_reason"] is not None:
            self.flag("SEARCH_LIMIT_REASON", "limit_reason does not fit a scored outcome.")
        elif not search["optimality_proven"]:
            self.flag("SEARCH_OVERCLAIM", "a search without a limit must have proven optimality.")
        if search["complete"] and self.count_valid_subsets(evaluated) != evaluated:
            self.flag("SEARCH_COUNT", "a complete search must evaluate every valid subset exactly once.")
        if search["complete"] is False and status != PlannerStatus.ALREADY_MET.value and search["limit_reason"] is None:
            if self.count_valid_subsets(evaluated) <= evaluated:
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

    # Scores and reasons

    def rescore(self, selected_ids: list[str]) -> Mapping[str, Any] | None:
        request = {
            "contract_version": CONTRACT_VERSION,
            "request_id": self.input["request_id"],
            "context": deepcopy(self.input["context"]),
            "baseline": deepcopy(self.input["baseline"]),
            "selected_activity_ids": sorted(selected_ids),
        }
        expected = deepcopy(request)
        try:
            response = deepcopy(self.score_plan(request))
            validate_score_response(response, expected, allowed_statuses=[s.value for s in EvaluationStatus])
        except Exception:
            self.flag("RESCORE_FAILED", "re-scoring the selected set did not return a valid response.")
            return None
        if response["evaluation_status"] != EvaluationStatus.OK.value:
            self.flag("RESCORE_FAILED", "re-scoring the selected set did not return OK.")
            return None
        return response["result"]

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
                self.flag("REASON_MISMATCH", "GOAL_CONTRIBUTION must match the scorer contribution.", activity_id)
            expected_matches = int(activity["domain"] in preferences["preferred_domains"]) + int(activity["mode"] in preferences["preferred_modes"])
            if len(preference) != expected_matches or any(r["category_id"] is not None or r["projected_added"] is not None for r in preference):
                self.flag("REASON_MISMATCH", "PREFERENCE_MATCH must reflect actual matches only.", activity_id)


def _close(actual: Any, expected: Any) -> bool:
    numeric = (int, float)
    if type(actual) not in numeric or type(expected) not in numeric:
        return False
    return within_tolerance(actual, expected)


def _maps_close(actual: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(actual, dict) and actual.keys() == expected.keys() and all(_close(actual[k], expected[k]) for k in expected)
