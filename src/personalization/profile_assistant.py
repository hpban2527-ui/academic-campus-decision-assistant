"""Strict AI-to-profile patch contract shared by onboarding and profile editing."""

from __future__ import annotations

from copy import deepcopy
from datetime import date as DateValue
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditableProfile(StrictModel):
    full_name: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=64)
    major: str | None = Field(default=None, max_length=100)


class WeeklyProfileInterval(StrictModel):
    kind: Literal["busy", "available"]
    weekday: int = Field(ge=0, le=6)
    start: str
    end: str
    recurrence: Literal["weekly"] = "weekly"
    source: Literal["ai", "manual"] = "ai"
    confirmed: bool = False

    @field_validator("start", "end")
    @classmethod
    def valid_clock(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("time must use HH:MM")
        return value

    @model_validator(mode="after")
    def valid_order(self) -> "WeeklyProfileInterval":
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class DateException(StrictModel):
    date: DateValue
    kind: Literal["busy", "available"]
    start: str
    end: str
    source: Literal["ai", "manual"] = "ai"
    confirmed: bool = False

    @field_validator("start", "end")
    @classmethod
    def valid_clock(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("time must use HH:MM")
        return value

    @model_validator(mode="after")
    def valid_order(self) -> "DateException":
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class PreferencePatch(StrictModel):
    preferred_topics: list[str] = Field(default_factory=list, max_length=20)
    preferred_categories: list[Literal["C1", "C2", "C3", "C4", "C5"]] = Field(default_factory=list)
    preferred_modes: list[Literal["online", "offline", "hybrid"]] = Field(default_factory=list)
    preferred_campuses: list[Literal["NVC", "DONG_HOA", "ONLINE", "OTHER"]] = Field(default_factory=list)
    max_activities: int | None = Field(default=None, ge=1, le=20)
    weekly_participation_hours: float | None = Field(default=None, ge=0.5, le=168)


class ProfileScore(StrictModel):
    value: float | None = Field(default=None, ge=0, le=100)
    source: Literal["confirmed", "self_reported", "unknown"] = "unknown"


class PreferenceUpdatePatch(StrictModel):
    preferred_topics: list[str] | None = Field(default=None, max_length=20)
    preferred_categories: list[Literal["C1", "C2", "C3", "C4", "C5"]] | None = None
    preferred_modes: list[Literal["online", "offline", "hybrid"]] | None = None
    preferred_campuses: list[Literal["NVC", "DONG_HOA", "ONLINE", "OTHER"]] | None = None
    max_activities: int | None = Field(default=None, ge=1, le=20)
    weekly_participation_hours: float | None = Field(default=None, ge=0.5, le=168)

    @model_validator(mode="after")
    def contains_patch(self) -> "PreferenceUpdatePatch":
        if not self.model_fields_set:
            raise ValueError("preference patch must contain at least one field")
        return self


class EditableProfileFieldPatch(StrictModel):
    full_name: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=64)
    major: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def contains_one_field(self) -> "EditableProfileFieldPatch":
        if len(self.model_fields_set) != 1:
            raise ValueError("profile patch must contain exactly one field")
        return self


class ScoreUpdatePatch(StrictModel):
    category_id: Literal["C1", "C2", "C3", "C4", "C5"]
    value: float | None = Field(default=None, ge=0, le=100)
    source: Literal["confirmed", "self_reported", "unknown"]


class WeeklyIntervalMatch(StrictModel):
    kind: Literal["busy", "available"] | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def contains_filter(self) -> "WeeklyIntervalMatch":
        if not self.model_fields_set:
            raise ValueError("weekly interval match must contain a filter")
        return self


class ExceptionMatch(StrictModel):
    date: DateValue | None = None
    kind: Literal["busy", "available"] | None = None
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def contains_filter(self) -> "ExceptionMatch":
        if not self.model_fields_set:
            raise ValueError("exception match must contain a filter")
        return self


class ProfileAssistantDraft(StrictModel):
    profile: EditableProfile = Field(default_factory=EditableProfile)
    drl_target: int | None = Field(default=None, ge=0, le=100)
    weekly_intervals: list[WeeklyProfileInterval] = Field(default_factory=list, max_length=100)
    exceptions: list[DateException] = Field(default_factory=list, max_length=100)
    preference_patch: PreferencePatch = Field(default_factory=PreferencePatch)
    scores: dict[Literal["C1", "C2", "C3", "C4", "C5"], ProfileScore] = Field(default_factory=dict)


ActionName = Literal[
    "update_drl_goal",
    "upsert_weekly_interval",
    "remove_weekly_interval",
    "upsert_exception",
    "remove_exception",
    "update_preferences",
    "update_profile_field",
    "update_score",
]

_SCORE_CAPS = {"C1": 30, "C2": 20, "C3": 25, "C4": 25, "C5": 30}


class ProfilePatchAction(StrictModel):
    action: ActionName
    operation: Literal["add", "replace", "remove", "set"]
    value: (
        int
        | WeeklyProfileInterval
        | DateException
        | PreferenceUpdatePatch
        | EditableProfileFieldPatch
        | ScoreUpdatePatch
        | None
    ) = None
    match: WeeklyIntervalMatch | ExceptionMatch | None = None
    source_text: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def compatible_operation(self) -> "ProfilePatchAction":
        if self.action.startswith("remove_") and self.operation != "remove":
            raise ValueError("remove actions require operation=remove")
        if self.action == "update_drl_goal" and type(self.value) is not int:
            raise ValueError("DRL goal must be an integer")
        expected_values = {
            "upsert_weekly_interval": WeeklyProfileInterval,
            "upsert_exception": DateException,
            "update_preferences": PreferenceUpdatePatch,
            "update_profile_field": EditableProfileFieldPatch,
            "update_score": ScoreUpdatePatch,
        }
        expected_value = expected_values.get(self.action)
        if expected_value is not None and not isinstance(self.value, expected_value):
            raise ValueError(f"{self.action} has an invalid value payload")
        if self.action == "remove_weekly_interval" and not isinstance(self.match, WeeklyIntervalMatch):
            raise ValueError("remove_weekly_interval requires a weekly interval match")
        if self.action == "remove_exception" and not isinstance(self.match, ExceptionMatch):
            raise ValueError("remove_exception requires an exception match")
        if self.action not in {"remove_weekly_interval", "remove_exception", "upsert_weekly_interval"} and self.match is not None:
            raise ValueError(f"{self.action} does not accept match")
        return self


class ProfileExtraction(StrictModel):
    actions: list[ProfilePatchAction] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def require_result(self) -> "ProfileExtraction":
        if not self.actions and not self.questions:
            raise ValueError("AI extraction must contain an action or a clarification question")
        return self


class ProfileChange(StrictModel):
    field: str
    operation: str
    old: Any = None
    new: Any = None
    source_text: str


def _matches(item: BaseModel, expected: dict[str, Any]) -> bool:
    payload = item.model_dump(mode="json")
    allowed = set(payload)
    if not expected or not set(expected) <= allowed:
        raise ValueError("remove match contains unsupported fields")
    return all(payload[key] == value for key, value in expected.items())


def _patch_dict(value: BaseModel | None) -> dict[str, Any]:
    if value is None:
        return {}
    return value.model_dump(mode="json", exclude_unset=True)


def _match_dict(value: BaseModel | None) -> dict[str, Any]:
    if value is None:
        return {}
    return value.model_dump(mode="json", exclude_none=True, exclude_unset=True)


def merge_profile_extraction(
    current: ProfileAssistantDraft | dict[str, Any],
    extraction: ProfileExtraction,
) -> tuple[ProfileAssistantDraft, list[ProfileChange]]:
    """Apply allowlisted PATCH actions to a copy and return an auditable diff."""

    draft = current if isinstance(current, ProfileAssistantDraft) else ProfileAssistantDraft.model_validate(current)
    merged = draft.model_copy(deep=True)
    changes: list[ProfileChange] = []
    for action in extraction.actions:
        old: Any = None
        new: Any = None
        field = action.action
        if action.action == "update_drl_goal":
            old, merged.drl_target = merged.drl_target, int(action.value)
            merged = ProfileAssistantDraft.model_validate(merged.model_dump())
            new, field = merged.drl_target, "drl_target"
        elif action.action == "upsert_weekly_interval":
            interval = WeeklyProfileInterval.model_validate(action.value)
            old = [item.model_dump(mode="json") for item in merged.weekly_intervals]
            if action.operation == "replace":
                expected = _match_dict(action.match) or {"kind": interval.kind, "weekday": interval.weekday}
                merged.weekly_intervals = [item for item in merged.weekly_intervals if not _matches(item, expected)]
            if interval not in merged.weekly_intervals:
                merged.weekly_intervals.append(interval)
            new = [item.model_dump(mode="json") for item in merged.weekly_intervals]
            field = "weekly_intervals"
        elif action.action == "remove_weekly_interval":
            expected = _match_dict(action.match)
            old = [item.model_dump(mode="json") for item in merged.weekly_intervals]
            merged.weekly_intervals = [item for item in merged.weekly_intervals if not _matches(item, expected)]
            new, field = [item.model_dump(mode="json") for item in merged.weekly_intervals], "weekly_intervals"
        elif action.action == "upsert_exception":
            exception = DateException.model_validate(action.value)
            old = [item.model_dump(mode="json") for item in merged.exceptions]
            if action.operation == "replace":
                merged.exceptions = [item for item in merged.exceptions if item.date != exception.date]
            if exception not in merged.exceptions:
                merged.exceptions.append(exception)
            new, field = [item.model_dump(mode="json") for item in merged.exceptions], "exceptions"
        elif action.action == "remove_exception":
            expected = _match_dict(action.match)
            old = [item.model_dump(mode="json") for item in merged.exceptions]
            merged.exceptions = [item for item in merged.exceptions if not _matches(item, expected)]
            new, field = [item.model_dump(mode="json") for item in merged.exceptions], "exceptions"
        elif action.action == "update_preferences":
            old = merged.preference_patch.model_dump(mode="json")
            patch = _patch_dict(action.value if isinstance(action.value, BaseModel) else None)
            unknown = set(patch) - set(PreferencePatch.model_fields)
            if unknown:
                raise ValueError("preference patch contains unsupported fields")
            merged.preference_patch = PreferencePatch.model_validate({**old, **deepcopy(patch)})
            new, field = merged.preference_patch.model_dump(mode="json"), "preference_patch"
        elif action.action == "update_profile_field":
            patch = _patch_dict(action.value if isinstance(action.value, BaseModel) else None)
            if len(patch) != 1 or not set(patch) <= set(EditableProfile.model_fields):
                raise ValueError("profile patch must contain one editable field")
            key, value = next(iter(patch.items()))
            old = getattr(merged.profile, key)
            merged.profile = EditableProfile.model_validate({**merged.profile.model_dump(), key: value})
            new, field = getattr(merged.profile, key), f"profile.{key}"
        elif action.action == "update_score":
            patch = _patch_dict(action.value if isinstance(action.value, BaseModel) else None)
            if set(patch) != {"category_id", "value", "source"} or patch["category_id"] not in {"C1", "C2", "C3", "C4", "C5"}:
                raise ValueError("score patch must identify one supported category and source")
            category = patch.pop("category_id")
            if patch["value"] is not None and patch["value"] > _SCORE_CAPS[category]:
                raise ValueError(f"score for {category} exceeds its configured cap")
            old = merged.scores.get(category)
            merged.scores[category] = ProfileScore.model_validate(patch)
            old = old.model_dump(mode="json") if old else None
            new, field = merged.scores[category].model_dump(mode="json"), f"scores.{category}"
        if old != new:
            changes.append(ProfileChange(field=field, operation=action.operation, old=old, new=new, source_text=action.source_text))
    return merged, changes


PROFILE_EXTRACTION_PROMPT = """You extract Vietnamese student profile PATCH operations only.
Return JSON matching the supplied schema. Never invent scores, dates, times or preferences.
Allowed actions are update_drl_goal, upsert_weekly_interval, remove_weekly_interval,
upsert_exception, remove_exception, update_preferences, update_profile_field and update_score.
Use weekday 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday,
5=Saturday and 6=Sunday, with HH:MM times. Distinguish 'khong ranh' as busy.
For a weekly busy interval, value must be exactly like
{"kind":"busy","weekday":0,"start":"08:00","end":"10:00","recurrence":"weekly","source":"ai","confirmed":false}.
Never use aliases such as day, from or to. Removal filters belong in match, not value.
For preferred_topics use only stable topic IDs from the current StudentPreference vocabulary,
for example volunteer, artificial_intelligence, computer_science, soft_skills or sports.
If recurrence or a specific date is ambiguous, emit no action and ask one concise question.
Preserve unrelated current values; do not calculate DRL points or schedules.
Understand common Vietnamese abbreviations (T2..T7, CN), accented or unaccented text,
informal clocks such as 7h, 7h30 and 19g, and explicit add/remove/replace/negation wording.
Return at most one clarification question, for the single missing fact needed next.
"""


def deterministic_profile_extraction(
    text: str,
    conversation: list[dict[str, str]] | None = None,
) -> ProfileExtraction | None:
    """Conservative fallback for explicit DRL goals and weekly time statements."""

    normalized = _fold_vi(text)
    actions: list[ProfilePatchAction] = []
    goal = re.search(r"(?:muc\s*tieu|drl|diem\s*ren\s*luyen)[^\d]{0,30}(\d{1,3})\b", normalized)
    if goal:
        value = int(goal.group(1))
        if 0 <= value <= 100:
            actions.append(ProfilePatchAction(
                action="update_drl_goal", operation="set", value=value, source_text=text.strip()
            ))

    weekday = _fallback_weekday(normalized)
    schedule_words = re.search(r"\b(?:ban|ranh|hoc|lich|t[2-7]|cn|thu|hang\s*tuan)\b", normalized)
    remove = bool(re.search(r"\b(?:xoa|bo|huy)\b", normalized))
    replace = bool(re.search(r"\b(?:thay|doi|chuyen)\b", normalized))
    if weekday is not None and remove:
        actions.append(ProfilePatchAction(
            action="remove_weekly_interval",
            operation="remove",
            match={"weekday": weekday},
            source_text=text.strip(),
        ))
    elif weekday is not None and schedule_words:
        times = _fallback_times(normalized)
        if len(times) >= 2:
            if times[0] >= times[1]:
                return ProfileExtraction(actions=actions, questions=["Giờ bắt đầu phải trước giờ kết thúc; bạn muốn khung giờ nào?"])
            kind = "busy" if re.search(r"\b(?:khong\s*ranh|ban|hoc|kẹt|ket)\b", normalized) else "available"
            actions.append(ProfilePatchAction(
                action="upsert_weekly_interval",
                operation="replace" if replace else "add",
                value={
                    "kind": kind,
                    "weekday": weekday,
                    "start": times[0],
                    "end": times[1],
                    "recurrence": "weekly",
                    "source": "ai",
                    "confirmed": False,
                },
                match={"weekday": weekday, "kind": kind} if replace else None,
                source_text=text.strip(),
            ))
        elif not actions:
            return ProfileExtraction(actions=[], questions=["Bạn bận hoặc rảnh từ mấy giờ đến mấy giờ?"])

    if actions:
        return ProfileExtraction(actions=actions, questions=[])
    # A short recurrence answer may complete the preceding user statement.
    if normalized in {"hang tuan", "moi tuan", "tuan nao cung vay"} and conversation:
        previous = next((turn.get("content", "") for turn in reversed(conversation) if turn.get("role") == "user"), "")
        if previous:
            return deterministic_profile_extraction(f"{previous} hang tuan", [])
    return None


def _fold_vi(value: str) -> str:
    value = value.casefold().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", value)
    return " ".join("".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").split())


def _fallback_weekday(text: str) -> int | None:
    patterns = {
        0: r"\b(?:t2|thu\s*(?:2|hai))\b", 1: r"\b(?:t3|thu\s*(?:3|ba))\b",
        2: r"\b(?:t4|thu\s*(?:4|tu))\b", 3: r"\b(?:t5|thu\s*(?:5|nam))\b",
        4: r"\b(?:t6|thu\s*(?:6|sau))\b", 5: r"\b(?:t7|thu\s*(?:7|bay))\b",
        6: r"\b(?:cn|chu\s*nhat)\b",
    }
    matches = [day for day, pattern in patterns.items() if re.search(pattern, text)]
    return matches[0] if len(matches) == 1 else None


def _fallback_times(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"(?<!\w)([01]?\d|2[0-3])\s*(?:h|g|:)([0-5]\d)?", text):
        values.append(f"{int(match.group(1)):02d}:{int(match.group(2) or 0):02d}")
    return values


__all__ = [
    "PROFILE_EXTRACTION_PROMPT",
    "ProfileAssistantDraft",
    "ProfileChange",
    "ProfileExtraction",
    "ProfilePatchAction",
    "merge_profile_extraction",
    "deterministic_profile_extraction",
]
