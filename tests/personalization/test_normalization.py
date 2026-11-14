from __future__ import annotations

from copy import deepcopy

from personalization.models import StudentPreference
from personalization.normalization import normalize_ai_preference


def test_removes_invented_time_and_hard_exclusions(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["hard_exclusions"] = {
        "campus_ids": ["DONG_HOA"],
        "modes": ["offline"],
        "time_slots": [],
    }
    preference = StudentPreference.model_validate(payload)

    result = normalize_ai_preference(
        "Em ưu tiên online; nếu đi trực tiếp thì thích Nguyễn Văn Cừ.",
        preference,
    )

    assert result.time_preferences == []
    assert result.hard_exclusions.campus_ids == []
    assert result.hard_exclusions.modes == []


def test_keeps_explicit_supported_hard_exclusion(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["mode_preferences"] = []
    payload["hard_exclusions"]["modes"] = ["offline"]
    preference = StudentPreference.model_validate(payload)

    result = normalize_ai_preference(
        "Em tuyệt đối không thể tham gia offline.",
        preference,
    )

    assert [item.value for item in result.hard_exclusions.modes] == ["offline"]


def test_removes_exclusion_not_mentioned_by_user(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["campus_preferences"] = []
    payload["hard_exclusions"] = {
        "campus_ids": ["DONG_HOA"],
        "modes": ["offline"],
        "time_slots": [],
    }
    preference = StudentPreference.model_validate(payload)

    result = normalize_ai_preference(
        "Em không thể tham gia offline.",
        preference,
    )

    assert result.hard_exclusions.campus_ids == []
    assert [item.value for item in result.hard_exclusions.modes] == ["offline"]


def test_removes_soft_preferences_without_text_evidence(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)

    result = normalize_ai_preference("Em chỉ muốn tham gia online.", preference)

    assert result.topic_preferences == []
    assert result.category_priorities == []
    assert result.campus_preferences == []
    assert [item.mode.value for item in result.mode_preferences] == ["online"]
    assert result.time_preferences == []


def test_normalizes_explicit_planning_strategy(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)

    preference_first = normalize_ai_preference(
        "Sở thích quan trọng nhất với em, hãy ưu tiên trước các hoạt động thể thao.",
        preference,
    )
    minimum_effort = normalize_ai_preference(
        "Em muốn ít hoạt động và ít thời gian nhất.",
        preference,
    )

    assert preference_first.strategy.value == "PREFERENCE_FIRST"
    assert minimum_effort.strategy.value == "MINIMUM_EFFORT"


def test_removes_invented_limits_and_keeps_explicit_limits(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)

    without_limits = normalize_ai_preference(
        "Em ưu tiên Đông Hòa vào chiều ngày thường.",
        preference,
    )
    with_limits = normalize_ai_preference(
        "Em tham gia tối đa 4 hoạt động, tổng thời gian không quá 600 phút, "
        "chi phí không quá 200000 đồng.",
        preference,
    )

    assert without_limits.limits.max_activities is None
    assert without_limits.limits.max_duration_minutes is None
    assert without_limits.limits.max_fee is None
    assert with_limits.limits == preference.limits


def test_keeps_explicit_free_only_limit(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["limits"] = {
        "max_activities": None,
        "max_duration_minutes": None,
        "max_fee": 0,
    }
    preference = StudentPreference.model_validate(payload)

    result = normalize_ai_preference("Em chỉ tham gia hoạt động miễn phí.", preference)

    assert result.limits.max_fee == 0
