"""Deterministic guardrails applied after an AI response passes its schema.

Small local models can satisfy JSON Schema while still inferring a hard ban
from a soft preference.  These checks deliberately remove unsupported claims;
they never add a preference that the model or user did not provide.
"""

from __future__ import annotations

import re

from personalization.models import (
    CampusId,
    CategoryId,
    HardExclusions,
    ModeId,
    PersonalizationLimits,
    PlanningStrategy,
    StudentPreference,
    TimeSlotId,
    TopicId,
)


_HARD_MARKERS = (
    "không thể",
    "không tham gia được",
    "tuyệt đối không",
    "không bao giờ",
    "bắt buộc tránh",
)

_CAMPUS_TERMS = {
    CampusId.NVC: ("nguyễn văn cừ", "nvc", "227 nguyễn văn cừ"),
    CampusId.DONG_HOA: ("đông hòa", "dĩ an", "khu đô thị đhqg"),
    CampusId.ONLINE: ("online", "trực tuyến", "từ xa"),
    CampusId.OTHER: ("cơ sở khác", "địa điểm khác"),
}

_MODE_TERMS = {
    ModeId.ONLINE: ("online", "trực tuyến", "từ xa"),
    ModeId.OFFLINE: ("offline", "trực tiếp"),
    ModeId.HYBRID: ("hybrid", "hình thức kết hợp", "kết hợp trực tuyến", "kết hợp online"),
}

_TOPIC_TERMS = {
    TopicId.MATHEMATICS: ("toán", "mathematics"),
    TopicId.ARTIFICIAL_INTELLIGENCE: ("trí tuệ nhân tạo", "ai"),
    TopicId.TECHNOLOGY: ("công nghệ", "technology"),
    TopicId.RESEARCH: ("nghiên cứu", "nckh", "research"),
    TopicId.SOFT_SKILLS: ("kỹ năng mềm", "soft skill"),
    TopicId.CAREER: ("nghề nghiệp", "việc làm", "career"),
    TopicId.VOLUNTEER: ("tình nguyện", "volunteer"),
    TopicId.ENVIRONMENT: ("môi trường", "environment"),
    TopicId.CULTURE: ("văn hóa", "văn nghệ", "culture"),
    TopicId.SPORTS: ("thể thao", "tdtt", "sports"),
    TopicId.HEALTH: ("sức khỏe", "y tế", "health"),
    TopicId.SAFETY: ("an toàn", "phòng cháy", "pccc", "safety"),
    TopicId.CIVIC_EDUCATION: ("công dân", "pháp luật", "chính trị", "civic"),
}

_CATEGORY_TERMS = {
    CategoryId.C1: ("mục 1", "nhóm 1", "c1"),
    CategoryId.C2: ("mục 2", "nhóm 2", "c2"),
    CategoryId.C3: ("mục 3", "nhóm 3", "c3"),
    CategoryId.C4: ("mục 4", "nhóm 4", "c4"),
    CategoryId.C5: ("mục 5", "nhóm 5", "c5"),
}

_PREFERENCE_FIRST_TERMS = (
    "sở thích quan trọng nhất",
    "ưu tiên sở thích",
    "sở thích trước",
    "ưu tiên trước các hoạt động",
)

_MINIMUM_EFFORT_TERMS = (
    "ít hoạt động",
    "ít thời gian nhất",
    "tối thiểu hoạt động",
    "minimum effort",
)

_LIMIT_MARKERS = (
    "tối đa",
    "không quá",
    "nhiều nhất",
    "chỉ",
    "giới hạn",
)

_ACTIVITY_UNITS = ("hoạt động", "sự kiện")
_DURATION_UNITS = ("phút", "giờ", "tiếng")
_FEE_UNITS = ("đồng", "vnd", "vnđ", "nghìn", "triệu", "học phí", "chi phí", "lệ phí")

_TIME_TERMS = {
    TimeSlotId.WEEKDAY_MORNING: ("sáng trong tuần", "sáng ngày thường"),
    TimeSlotId.WEEKDAY_AFTERNOON: ("chiều trong tuần", "chiều ngày thường"),
    TimeSlotId.WEEKDAY_EVENING: ("tối trong tuần", "tối ngày thường"),
    TimeSlotId.WEEKEND_MORNING: ("sáng cuối tuần",),
    TimeSlotId.WEEKEND_AFTERNOON: ("chiều cuối tuần",),
    TimeSlotId.WEEKEND_EVENING: ("tối cuối tuần",),
}

_ANY_TIME_TERMS = (
    "buổi sáng",
    "buổi chiều",
    "buổi tối",
    "sáng",
    "chiều",
    "tối",
    "cuối tuần",
    "trong tuần",
    "ngày thường",
    "weekday",
    "weekend",
)


def normalize_ai_preference(text: str, preference: StudentPreference) -> StudentPreference:
    normalized_text = " ".join(text.casefold().split())
    updates: dict[str, object] = {}

    # A schema-valid small-model response may still fill every optional array
    # with weak guesses.  Retain a soft preference only when its value has a
    # lexical cue in the student's own sentence.
    updates["topic_preferences"] = [
        item for item in preference.topic_preferences
        if _contains_any(normalized_text, _TOPIC_TERMS[item.topic_id])
    ]
    updates["category_priorities"] = [
        item for item in preference.category_priorities
        if _contains_any(normalized_text, _CATEGORY_TERMS[item.category_id])
    ]
    updates["campus_preferences"] = [
        item for item in preference.campus_preferences
        if _contains_any(normalized_text, _CAMPUS_TERMS[item.campus_id])
    ]
    updates["mode_preferences"] = [
        item for item in preference.mode_preferences
        if _contains_any(normalized_text, _MODE_TERMS[item.mode])
    ]
    updates["time_preferences"] = [
        item for item in preference.time_preferences
        if _contains_any(normalized_text, _TIME_TERMS[item.time_slot])
    ] if _contains_any(normalized_text, _ANY_TIME_TERMS) else []

    # Optional numeric limits are especially easy for a model to invent.  A
    # value survives only if the sentence contains a number, a limit marker,
    # and the matching unit.  "Miễn phí" is the explicit form of max_fee=0.
    limits = preference.limits
    updates["limits"] = PersonalizationLimits(
        max_activities=(
            limits.max_activities
            if _has_numeric_limit_evidence(normalized_text, _ACTIVITY_UNITS)
            else None
        ),
        max_duration_minutes=(
            limits.max_duration_minutes
            if _has_numeric_limit_evidence(normalized_text, _DURATION_UNITS)
            else None
        ),
        max_fee=(
            limits.max_fee
            if "miễn phí" in normalized_text
            or _has_numeric_limit_evidence(normalized_text, _FEE_UNITS)
            else None
        ),
    )

    if _contains_any(normalized_text, _PREFERENCE_FIRST_TERMS):
        updates["strategy"] = PlanningStrategy.PREFERENCE_FIRST
    elif _contains_any(normalized_text, _MINIMUM_EFFORT_TERMS):
        updates["strategy"] = PlanningStrategy.MINIMUM_EFFORT
    else:
        updates["strategy"] = PlanningStrategy.BALANCED

    exclusions = preference.hard_exclusions
    if not _contains_any(normalized_text, _HARD_MARKERS):
        updates["hard_exclusions"] = _empty_exclusions()
    else:
        updates["hard_exclusions"] = HardExclusions(
            campus_ids=[
                item
                for item in exclusions.campus_ids
                if _contains_any(normalized_text, _CAMPUS_TERMS[item])
            ],
            modes=[
                item
                for item in exclusions.modes
                if _contains_any(normalized_text, _MODE_TERMS[item])
            ],
            time_slots=[
                item
                for item in exclusions.time_slots
                if _contains_any(normalized_text, _TIME_TERMS[item])
            ],
        )

    if not updates:
        return preference
    return preference.model_copy(update=updates)


def _empty_exclusions() -> HardExclusions:
    return HardExclusions(campus_ids=[], modes=[], time_slots=[])


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(
        (bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text)) if term.isascii() and term.isalnum() and len(term) <= 3 else term in text)
        for term in terms
    )


def _has_numeric_limit_evidence(text: str, units: tuple[str, ...]) -> bool:
    return bool(re.search(r"\d", text)) and _contains_any(text, _LIMIT_MARKERS) and _contains_any(text, units)
