"""Validated, side-effect-free parsing for the UniLife home action assistant."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeeklyInterval(StrictModel):
    kind: Literal["busy", "available"]
    weekday: int = Field(ge=0, le=6)
    start: str
    end: str
    recurrence: Literal["weekly"]
    source_text: str = ""

    @field_validator("start", "end")
    @classmethod
    def validate_time(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("time must use HH:MM")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> "WeeklyInterval":
        if self.end <= self.start:
            raise ValueError("Giờ kết thúc phải sau giờ bắt đầu.")
        return self


class PendingInterval(StrictModel):
    kind: Literal["busy", "available"]
    weekday: int = Field(ge=0, le=6)
    start: str
    end: str | None = None
    recurrence: Literal["weekly"] | None = None
    missing: Literal["end", "recurrence"]
    source_text: str = ""


class AssistantDraft(StrictModel):
    drl_target: int | None = Field(default=None, ge=0, le=100)
    intervals: list[WeeklyInterval] = Field(default_factory=list)
    pending_interval: PendingInterval | None = None
    preferred_modes: list[Literal["online", "offline", "hybrid"]] = Field(default_factory=list)
    soft_time_preferences: list[Literal["morning", "afternoon", "evening"]] = Field(default_factory=list)
    preferences_confirmed: bool = False
    destination: Literal["plan"] = "plan"


class AssistantAction(StrictModel):
    type: Literal[
        "set_drl_target",
        "add_busy_interval",
        "add_available_interval",
        "set_activity_preferences",
        "set_soft_time_preferences",
    ]
    value: Any


class InterpretationResult(StrictModel):
    status: Literal["clarification", "preview", "error"]
    draft: AssistantDraft
    actions: list[AssistantAction] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True


_DAY_NAMES = ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật")
_DAY_VALUES = {
    "2": 0, "hai": 0, "3": 1, "ba": 1, "4": 2, "tu": 2,
    "5": 3, "nam": 3, "6": 4, "sau": 4, "7": 5, "bay": 5,
    "cn": 6,
}
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})(?:h|:)(\d{1,2})?\s*(sang|trua|chieu|toi)?\b")


def _plain(text: str) -> str:
    text = text.lower().replace("đ", "d")
    return "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def _parse_time(match: re.Match[str]) -> str | None:
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3)
    if period in {"chieu", "toi"} and hour < 12:
        hour += 12
    elif period == "sang" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _times(text: str) -> list[str]:
    return [value for match in _TIME_RE.finditer(text) if (value := _parse_time(match))]


def _weekday(text: str) -> int | None:
    if "chu nhat" in text:
        return 6
    match = re.search(
        r"\bthu\s*(2|3|4|5|6|7|hai|ba|tu|nam|sau|bay)\b|\bt\s*([2-7])\b|\bcn\b",
        text,
    )
    if not match:
        return None
    token = next((group for group in match.groups() if group), "cn")
    return _DAY_VALUES[token]


def _is_weekly(text: str) -> bool:
    return bool(re.search(r"\b(?:hang|moi)\s*tuan\b", text))


def _interval_kind(text: str) -> Literal["busy", "available"] | None:
    if re.search(r"\b(?:ranh|trong lich|co the tham gia)\b", text):
        return "available"
    if re.search(r"\b(?:hoc|ban|khong ranh|co lich)\b", text):
        return "busy"
    return None


def _question(pending: PendingInterval) -> str:
    label = "rảnh" if pending.kind == "available" else "bận"
    if pending.missing == "end":
        return f"Khoảng {label} {_DAY_NAMES[pending.weekday]} từ {pending.start} kết thúc lúc mấy giờ?"
    return f"Lịch {_DAY_NAMES[pending.weekday]} {pending.start}–{pending.end} có lặp lại hằng tuần không?"


def _resolve_pending(text: str, draft: AssistantDraft) -> str | None:
    pending = draft.pending_interval
    if pending is None:
        return None
    parsed_times = _times(text)
    if pending.missing == "end" and parsed_times:
        pending.end = parsed_times[-1]
        if pending.recurrence is None and not _is_weekly(text):
            pending.missing = "recurrence"
            return None
        pending.recurrence = "weekly"
    elif pending.missing == "recurrence":
        if _is_weekly(text) or re.search(r"\b(?:co|dung|lap lai)\b", text):
            pending.recurrence = "weekly"
        else:
            return None
    else:
        return None
    if pending.end and pending.recurrence:
        try:
            draft.intervals.append(WeeklyInterval(
                kind=pending.kind,
                weekday=pending.weekday,
                start=pending.start,
                end=pending.end,
                recurrence=pending.recurrence,
                source_text=pending.source_text,
            ))
        except ValidationError:
            return "Khoảng giờ không hợp lệ: giờ kết thúc phải sau giờ bắt đầu."
        draft.pending_interval = None
    return None


def _conflicts(intervals: list[WeeklyInterval]) -> list[str]:
    errors: list[str] = []
    for index, left in enumerate(intervals):
        for right in intervals[index + 1:]:
            overlaps = left.start < right.end and right.start < left.end
            if left.weekday == right.weekday and left.kind != right.kind and overlaps:
                errors.append(
                    f"Thời gian bận và thời gian rảnh bị xung đột vào {_DAY_NAMES[left.weekday]} "
                    f"({max(left.start, right.start)}–{min(left.end, right.end)})."
                )
    return errors


def _actions(draft: AssistantDraft) -> list[AssistantAction]:
    actions: list[AssistantAction] = []
    if draft.drl_target is not None:
        actions.append(AssistantAction(type="set_drl_target", value=draft.drl_target))
    for interval in draft.intervals:
        action_type = "add_busy_interval" if interval.kind == "busy" else "add_available_interval"
        actions.append(AssistantAction(type=action_type, value=interval.model_dump()))
    if draft.preferred_modes:
        actions.append(AssistantAction(type="set_activity_preferences", value=draft.preferred_modes))
    if draft.soft_time_preferences:
        actions.append(AssistantAction(type="set_soft_time_preferences", value=draft.soft_time_preferences))
    return actions


def interpret_message(
    message: str,
    existing_draft: dict[str, Any] | AssistantDraft | None = None,
) -> InterpretationResult:
    """Merge one natural-language turn into a validated, non-executing draft."""
    try:
        draft = (
            existing_draft if isinstance(existing_draft, AssistantDraft)
            else AssistantDraft.model_validate(existing_draft or {})
        )
    except ValidationError as exc:
        raise ValueError("Bản nháp trợ lý không hợp lệ.") from exc
    raw = message.strip()
    if not raw:
        return InterpretationResult(status="error", draft=draft, errors=["Vui lòng mô tả thiết lập bạn muốn."])
    text = _plain(raw)
    pending_error = _resolve_pending(text, draft)
    if pending_error:
        return InterpretationResult(status="error", draft=draft, errors=[pending_error])

    errors: list[str] = []
    target_matches = re.findall(r"(\d{1,3})\s*(?:diem\s*)?(?:ren luyen|drl)\b", text)
    if not target_matches:
        target_matches = re.findall(r"\b(?:muc tieu|muon dat|dat)\D{0,18}(\d{1,3})\s*diem\b", text)
    if target_matches:
        target = int(target_matches[-1])
        if 0 <= target <= 100:
            draft.drl_target = target
        else:
            errors.append("Mục tiêu điểm rèn luyện phải từ 0 đến 100.")

    global_weekly = _is_weekly(text)
    for raw_sentence in re.split(r"[.!?;\n]+", raw):
        sentence = _plain(raw_sentence)
        weekday = _weekday(sentence)
        kind = _interval_kind(sentence)
        parsed_times = _times(sentence)
        if weekday is None or kind is None or not parsed_times:
            continue
        start = parsed_times[0]
        end = parsed_times[1] if len(parsed_times) > 1 else None
        recurrence = "weekly" if global_weekly or _is_weekly(sentence) else None
        if end is None:
            draft.pending_interval = PendingInterval(
                kind=kind, weekday=weekday, start=start, recurrence=recurrence,
                missing="end", source_text=raw_sentence.strip(),
            )
            continue
        if recurrence is None:
            draft.pending_interval = PendingInterval(
                kind=kind, weekday=weekday, start=start, end=end,
                missing="recurrence", source_text=raw_sentence.strip(),
            )
            continue
        try:
            interval = WeeklyInterval(
                kind=kind, weekday=weekday, start=start, end=end,
                recurrence="weekly", source_text=raw_sentence.strip(),
            )
            if not any(item.model_dump() == interval.model_dump() for item in draft.intervals):
                draft.intervals.append(interval)
        except ValidationError:
            errors.append(f"Khoảng giờ {_DAY_NAMES[weekday]} không hợp lệ: giờ kết thúc phải sau giờ bắt đầu.")

    mode_terms = {
        "online": r"\b(?:online|truc tuyen|zoom|meet)\b",
        "offline": r"\b(?:offline|truc tiep|tai truong)\b",
        "hybrid": r"\bhybrid\b",
    }
    for mode, pattern in mode_terms.items():
        if re.search(pattern, text) and mode not in draft.preferred_modes:
            draft.preferred_modes.append(mode)  # type: ignore[arg-type]
    if re.search(r"\b(?:thich|uu tien|muon)\b", text):
        for phrase, value in {
            "buoi sang": "morning", "buoi chieu": "afternoon", "buoi toi": "evening"
        }.items():
            if phrase in text and value not in draft.soft_time_preferences:
                draft.soft_time_preferences.append(value)  # type: ignore[arg-type]

    errors.extend(_conflicts(draft.intervals))
    if errors:
        return InterpretationResult(status="error", draft=draft, errors=errors)
    if draft.pending_interval:
        return InterpretationResult(
            status="clarification", draft=draft,
            questions=[_question(draft.pending_interval)],
        )
    actions = _actions(draft)
    if not actions:
        return InterpretationResult(
            status="error", draft=draft,
            errors=["UniLife Assistant chỉ hỗ trợ thiết lập mục tiêu, lịch và sở thích cho Lập lịch thông minh."],
        )
    return InterpretationResult(status="preview", draft=draft, actions=actions)


__all__ = ["AssistantDraft", "InterpretationResult", "WeeklyInterval", "interpret_message"]
