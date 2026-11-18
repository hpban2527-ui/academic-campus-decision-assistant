"""Strict data contracts for AI-assisted schedule personalization.

The language model is allowed to translate natural-language preferences into
this contract.  It is not allowed to calculate DRL points, decide eligibility,
or create a schedule.  Those responsibilities stay in SP2/SP3.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TopicId(str, Enum):
    MATHEMATICS = "mathematics"
    ARTIFICIAL_INTELLIGENCE = "artificial_intelligence"
    TECHNOLOGY = "technology"
    RESEARCH = "research"
    SOFT_SKILLS = "soft_skills"
    CAREER = "career"
    VOLUNTEER = "volunteer"
    ENVIRONMENT = "environment"
    CULTURE = "culture"
    SPORTS = "sports"
    HEALTH = "health"
    SAFETY = "safety"
    CIVIC_EDUCATION = "civic_education"


class CategoryId(str, Enum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"


class CampusId(str, Enum):
    NVC = "NVC"
    DONG_HOA = "DONG_HOA"
    ONLINE = "ONLINE"
    OTHER = "OTHER"


class ModeId(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"


class TimeSlotId(str, Enum):
    WEEKDAY_MORNING = "weekday_morning"
    WEEKDAY_AFTERNOON = "weekday_afternoon"
    WEEKDAY_EVENING = "weekday_evening"
    WEEKEND_MORNING = "weekend_morning"
    WEEKEND_AFTERNOON = "weekend_afternoon"
    WEEKEND_EVENING = "weekend_evening"


class PlanningStrategy(str, Enum):
    MINIMUM_EFFORT = "MINIMUM_EFFORT"
    BALANCED = "BALANCED"
    PREFERENCE_FIRST = "PREFERENCE_FIRST"


PreferenceWeight = Annotated[int, Field(ge=1, le=5)]


class StrictModel(BaseModel):
    """Forbid silently accepting invented AI fields."""

    model_config = ConfigDict(extra="forbid")


class TopicPreference(StrictModel):
    topic_id: TopicId
    weight: PreferenceWeight


class CategoryPreference(StrictModel):
    category_id: CategoryId
    weight: PreferenceWeight


class CampusPreference(StrictModel):
    campus_id: CampusId
    weight: PreferenceWeight


class ModePreference(StrictModel):
    mode: ModeId
    weight: PreferenceWeight


class TimePreference(StrictModel):
    time_slot: TimeSlotId
    weight: PreferenceWeight


class PersonalizationLimits(StrictModel):
    max_activities: int | None = Field(default=None, ge=1, le=20)
    max_duration_minutes: int | None = Field(default=None, ge=30, le=10_080)
    max_fee: int | None = Field(default=None, ge=0, le=100_000_000)


class HardExclusions(StrictModel):
    """Values the student explicitly says are impossible, not merely disliked."""

    campus_ids: list[CampusId] = Field(max_length=len(CampusId))
    modes: list[ModeId] = Field(max_length=len(ModeId))
    time_slots: list[TimeSlotId] = Field(max_length=len(TimeSlotId))

    @model_validator(mode="after")
    def reject_duplicates(self) -> "HardExclusions":
        _require_unique(self.campus_ids, "hard_exclusions.campus_ids")
        _require_unique(self.modes, "hard_exclusions.modes")
        _require_unique(self.time_slots, "hard_exclusions.time_slots")
        return self


class StudentPreference(StrictModel):
    topic_preferences: list[TopicPreference] = Field(max_length=len(TopicId))
    category_priorities: list[CategoryPreference] = Field(max_length=len(CategoryId))
    campus_preferences: list[CampusPreference] = Field(max_length=len(CampusId))
    mode_preferences: list[ModePreference] = Field(max_length=len(ModeId))
    time_preferences: list[TimePreference] = Field(max_length=len(TimeSlotId))
    limits: PersonalizationLimits
    hard_exclusions: HardExclusions
    strategy: PlanningStrategy

    @model_validator(mode="after")
    def validate_preference_consistency(self) -> "StudentPreference":
        _require_unique(
            [item.topic_id for item in self.topic_preferences],
            "topic_preferences.topic_id",
        )
        _require_unique(
            [item.category_id for item in self.category_priorities],
            "category_priorities.category_id",
        )
        _require_unique(
            [item.campus_id for item in self.campus_preferences],
            "campus_preferences.campus_id",
        )
        _require_unique(
            [item.mode for item in self.mode_preferences],
            "mode_preferences.mode",
        )
        _require_unique(
            [item.time_slot for item in self.time_preferences],
            "time_preferences.time_slot",
        )

        preferred_campuses = {item.campus_id for item in self.campus_preferences}
        preferred_modes = {item.mode for item in self.mode_preferences}
        preferred_times = {item.time_slot for item in self.time_preferences}
        _require_disjoint(
            preferred_campuses,
            set(self.hard_exclusions.campus_ids),
            "campus preference and hard exclusion",
        )
        _require_disjoint(
            preferred_modes,
            set(self.hard_exclusions.modes),
            "mode preference and hard exclusion",
        )
        _require_disjoint(
            preferred_times,
            set(self.hard_exclusions.time_slots),
            "time preference and hard exclusion",
        )
        return self


class InterpretPreferenceRequest(StrictModel):
    text: str = Field(min_length=1, max_length=2_000)
    force_ai: bool = False

    @field_validator("text")
    @classmethod
    def strip_and_reject_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must contain a preference description")
        return normalized


class BusyInterval(StrictModel):
    start: str
    end: str

    @model_validator(mode="after")
    def validate_interval(self) -> "BusyInterval":
        try:
            start = datetime.fromisoformat(self.start)
            end = datetime.fromisoformat(self.end)
        except ValueError as exc:
            raise ValueError("busy interval timestamps must be ISO-8601") from exc
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("busy interval timestamps must include a timezone")
        if end <= start:
            raise ValueError("busy interval end must be after start")
        return self


class PersonalizedPlanRequest(StrictModel):
    """Only a preference explicitly confirmed by the student may reach SP3."""

    confirmed: Literal[True]
    preference: StudentPreference
    scenario: Literal["first_plan", "replan", "what_if_skip"] = "first_plan"
    total_target: int = Field(default=80, ge=0, le=100)
    busy_intervals: list[BusyInterval] = Field(default_factory=list, max_length=50)


class ConfirmedPreferenceSaveRequest(StrictModel):
    """Persist only a preference the named student explicitly confirmed."""

    student_id: str = Field(min_length=1, max_length=64)
    confirmed: Literal[True]
    preference: StudentPreference
    source_text: str | None = Field(default=None, max_length=2_000)

    @field_validator("student_id")
    @classmethod
    def normalize_student_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("student_id must not be blank")
        return normalized

    @field_validator("source_text")
    @classmethod
    def normalize_source_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def _require_unique(values: list[object], path: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{path} must not contain duplicates")


def _require_disjoint(left: set[object], right: set[object], label: str) -> None:
    overlap = left & right
    if overlap:
        values = ", ".join(sorted(str(item.value if isinstance(item, Enum) else item) for item in overlap))
        raise ValueError(f"{label} conflict: {values}")
