"""Deterministic preference scoring used after explicit student confirmation.

The language model never calls this module.  It only produces a validated
``StudentPreference``; this scorer then compares that confirmed contract with
trusted activity metadata and returns a reproducible utility value.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from personalization.models import StudentPreference


@dataclass(frozen=True)
class ActivityFeatures:
    topics: frozenset[str]
    campus_id: str | None
    time_tags: frozenset[str]


@dataclass(frozen=True)
class UtilityMatch:
    dimension: str
    value: str
    weight: int


@dataclass(frozen=True)
class ActivityUtility:
    activity_id: str
    utility: int
    matches: tuple[UtilityMatch, ...]


def load_activity_features(path: Path) -> dict[str, ActivityFeatures]:
    """Load the reviewed sidecar without allowing unknown shapes to leak in."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "personalization-features/0.1":
        raise ValueError("unsupported personalization feature schema")
    activities = payload.get("activities")
    if not isinstance(activities, dict):
        raise ValueError("personalization activities must be an object")
    result: dict[str, ActivityFeatures] = {}
    for activity_id, raw in activities.items():
        if not isinstance(activity_id, str) or not activity_id or not isinstance(raw, dict):
            raise ValueError("invalid personalization activity entry")
        if set(raw) != {"topics", "campus_id", "time_tags"}:
            raise ValueError(f"invalid personalization fields for {activity_id}")
        topics, time_tags = raw["topics"], raw["time_tags"]
        if not isinstance(topics, list) or not all(isinstance(item, str) for item in topics):
            raise ValueError(f"invalid topics for {activity_id}")
        if not isinstance(time_tags, list) or not all(isinstance(item, str) for item in time_tags):
            raise ValueError(f"invalid time_tags for {activity_id}")
        campus_id = raw["campus_id"]
        if campus_id is not None and not isinstance(campus_id, str):
            raise ValueError(f"invalid campus_id for {activity_id}")
        result[activity_id] = ActivityFeatures(frozenset(topics), campus_id, frozenset(time_tags))
    return result


class PreferenceUtilityEngine:
    """Score activity sets and enforce confirmed hard exclusions.

    Every matching preference contributes its 1..5 weight.  A preference that
    is absent contributes zero; dislikes are not silently converted into bans.
    Category matching uses SP2's real contribution category from the scored
    activity set, while mode/fee come from the trusted SP3 candidate.
    """

    def __init__(
        self,
        preference: StudentPreference,
        features: Mapping[str, ActivityFeatures],
        activities: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.preference = preference
        self.features = dict(features)
        self.activities = dict(activities)
        self._topic = {item.topic_id.value: item.weight for item in preference.topic_preferences}
        self._category = {item.category_id.value: item.weight for item in preference.category_priorities}
        self._campus = {item.campus_id.value: item.weight for item in preference.campus_preferences}
        self._mode = {item.mode.value: item.weight for item in preference.mode_preferences}
        self._time = {item.time_slot.value: item.weight for item in preference.time_preferences}

    def score_activity(self, activity_id: str, category_id: str | None = None) -> ActivityUtility:
        feature = self.features.get(activity_id, ActivityFeatures(frozenset(), None, frozenset()))
        activity = self.activities.get(activity_id, {})
        matches: list[UtilityMatch] = []
        for topic in sorted(feature.topics):
            if topic in self._topic:
                matches.append(UtilityMatch("topic", topic, self._topic[topic]))
        if category_id is not None and category_id in self._category:
            matches.append(UtilityMatch("category", category_id, self._category[category_id]))
        if feature.campus_id is not None and feature.campus_id in self._campus:
            matches.append(UtilityMatch("campus", feature.campus_id, self._campus[feature.campus_id]))
        mode = activity.get("mode")
        if isinstance(mode, str) and mode in self._mode:
            matches.append(UtilityMatch("mode", mode, self._mode[mode]))
        for time_tag in sorted(feature.time_tags):
            if time_tag in self._time:
                matches.append(UtilityMatch("time", time_tag, self._time[time_tag]))
        return ActivityUtility(activity_id, sum(item.weight for item in matches), tuple(matches))

    def score_set(self, activity_ids: Sequence[str], score_result: Mapping[str, Any]) -> float:
        categories = {
            item["activity_id"]: item["category_id"]
            for item in score_result.get("contributions", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("activity_id"), str)
            and isinstance(item.get("category_id"), str)
        }
        return float(sum(self.score_activity(activity_id, categories.get(activity_id)).utility for activity_id in activity_ids))

    def hard_exclusion_reasons(self, activity_id: str) -> list[str]:
        feature = self.features.get(activity_id, ActivityFeatures(frozenset(), None, frozenset()))
        activity = self.activities.get(activity_id, {})
        exclusions = self.preference.hard_exclusions
        reasons: list[str] = []
        if feature.campus_id in {item.value for item in exclusions.campus_ids}:
            reasons.append(f"campus:{feature.campus_id}")
        mode = activity.get("mode")
        if mode in {item.value for item in exclusions.modes}:
            reasons.append(f"mode:{mode}")
        blocked_times = {item.value for item in exclusions.time_slots}
        reasons.extend(f"time:{item}" for item in sorted(feature.time_tags & blocked_times))
        max_fee = self.preference.limits.max_fee
        fee = activity.get("fee")
        if max_fee is not None and isinstance(fee, (int, float)) and not isinstance(fee, bool) and fee > max_fee:
            reasons.append(f"fee>{max_fee}")
        return reasons

    def selected_breakdown(self, score_result: Mapping[str, Any], activity_ids: Sequence[str]) -> list[dict[str, Any]]:
        categories = {
            item["activity_id"]: item["category_id"]
            for item in score_result.get("contributions", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("activity_id"), str)
            and isinstance(item.get("category_id"), str)
        }
        rows = []
        for activity_id in activity_ids:
            scored = self.score_activity(activity_id, categories.get(activity_id))
            rows.append({
                "activity_id": activity_id,
                "utility": scored.utility,
                "matches": [
                    {"dimension": item.dimension, "value": item.value, "weight": item.weight}
                    for item in scored.matches
                ],
            })
        return rows
