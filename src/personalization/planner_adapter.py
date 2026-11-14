"""Stable boundary between confirmed preferences and any SP3 v0.2 input.

Upstream owns extraction, review, feasibility, point/category bindings and the
planner input contract.  Personalization only decorates a deep copy of that
input with confirmed limits and hard exclusions, then exposes the deterministic
utility callback already understood by ``sp3.planner.build_plan``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from personalization.models import StudentPreference
from personalization.scoring import ActivityFeatures, PreferenceUtilityEngine


@dataclass(frozen=True)
class PreparedPersonalization:
    """Integration result that can be passed directly to SP3's planner."""

    planner_input: dict[str, Any]
    engine: PreferenceUtilityEngine
    strategy: str
    hard_excluded: tuple[dict[str, object], ...]

    @property
    def build_plan_options(self) -> dict[str, object]:
        return {
            "preference_utility": self.engine.score_set,
            "personalization_strategy": self.strategy,
        }


def prepare_personalized_planner_input(
    planner_input: Mapping[str, Any],
    preference: StudentPreference,
    features: Mapping[str, ActivityFeatures],
) -> PreparedPersonalization:
    """Decorate an upstream planner input without mutating its owner data.

    Unknown activity IDs remain valid. They can still be ranked from reviewed
    planner fields (mode and scored category), while missing sidecar metadata
    contributes no topic, campus or time utility. This lets Duyên/Tiến
    integrate incrementally without inventing enrichment data.
    """

    prepared = deepcopy(dict(planner_input))
    candidates = prepared.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("planner_input.candidates must be a list")
    limits = prepared.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("planner_input.limits must be an object")
    legacy_preferences = prepared.get("preferences")
    if not isinstance(legacy_preferences, dict):
        raise ValueError("planner_input.preferences must be an object")

    activities: dict[str, Mapping[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or not isinstance(candidate.get("activity"), dict):
            raise ValueError(f"planner_input.candidates[{index}].activity must be an object")
        activity = candidate["activity"]
        activity_id = activity.get("activity_id")
        if not isinstance(activity_id, str) or not activity_id:
            raise ValueError(f"planner_input.candidates[{index}].activity.activity_id is required")
        activities[activity_id] = activity

    # The weighted engine replaces SP3's old unweighted domain/mode preference
    # fields so the same preference is never counted twice.
    prepared["preferences"] = {"preferred_domains": [], "preferred_modes": []}
    _apply_limit(limits, "max_activities", preference.limits.max_activities)
    _apply_limit(limits, "max_duration_minutes", preference.limits.max_duration_minutes)

    engine = PreferenceUtilityEngine(preference, features, activities)
    hard_excluded: list[dict[str, object]] = []
    for candidate in candidates:
        activity_id = candidate["activity"]["activity_id"]
        reasons = engine.hard_exclusion_reasons(activity_id)
        feasibility = candidate.get("feasibility")
        if reasons and isinstance(feasibility, dict) and feasibility.get("status") == "FEASIBLE":
            candidate["feasibility"] = {
                "status": "INFEASIBLE",
                "reason_codes": ["PERSONALIZATION_HARD_EXCLUSION"],
            }
            hard_excluded.append({"activity_id": activity_id, "reasons": reasons})

    return PreparedPersonalization(
        planner_input=prepared,
        engine=engine,
        strategy=preference.strategy.value,
        hard_excluded=tuple(hard_excluded),
    )


def _apply_limit(limits: dict[str, Any], field: str, requested: int | None) -> None:
    if requested is None:
        return
    current = limits.get(field)
    limits[field] = requested if current is None else min(current, requested)
