from __future__ import annotations

from copy import deepcopy

import pytest

from personalization.profile_assistant import (
    ProfileAssistantDraft,
    ProfileExtraction,
    ProfilePatchAction,
    deterministic_profile_extraction,
    merge_profile_extraction,
)


def test_multiturn_extraction_merges_without_erasing_confirmed_fields() -> None:
    original = ProfileAssistantDraft.model_validate(
        {
            "profile": {"full_name": "Nguyen An", "major": "CNTT"},
            "drl_target": 95,
            "weekly_intervals": [],
            "exceptions": [],
            "preference_patch": {"preferred_modes": ["online"]},
        }
    )
    extraction = ProfileExtraction(
        actions=[
            ProfilePatchAction(
                action="upsert_weekly_interval",
                operation="add",
                value={
                    "kind": "busy",
                    "weekday": 0,
                    "start": "07:30",
                    "end": "17:30",
                    "recurrence": "weekly",
                },
                source_text="Thu Hai hang tuan hoc 7h30 den 17h30",
            )
        ],
        questions=[],
    )

    merged, changes = merge_profile_extraction(original, extraction)

    assert original.profile.major == "CNTT"
    assert merged.profile.major == "CNTT"
    assert merged.drl_target == 95
    assert merged.weekly_intervals[0].kind == "busy"
    assert changes[0].field == "weekly_intervals"


def test_patch_remove_is_targeted_and_preserves_other_intervals() -> None:
    draft = ProfileAssistantDraft.model_validate(
        {
            "weekly_intervals": [
                {"kind": "busy", "weekday": 0, "start": "08:00", "end": "11:00", "recurrence": "weekly"},
                {"kind": "available", "weekday": 1, "start": "16:30", "end": "21:00", "recurrence": "weekly"},
            ]
        }
    )
    before = deepcopy(draft.model_dump())
    extraction = ProfileExtraction(
        actions=[
            ProfilePatchAction(
                action="remove_weekly_interval",
                operation="remove",
                match={"kind": "busy", "weekday": 0},
                source_text="Xoa lich ban thu Hai",
            )
        ]
    )

    merged, _ = merge_profile_extraction(draft, extraction)

    assert len(merged.weekly_intervals) == 1
    assert merged.weekly_intervals[0].weekday == 1
    assert draft.model_dump() == before


def test_ambiguous_action_requires_clarification_and_does_not_mutate() -> None:
    draft = ProfileAssistantDraft(drl_target=80)
    extraction = ProfileExtraction(actions=[], questions=["Ban muon ap dung lich nay mot lan hay hang tuan?"])

    merged, changes = merge_profile_extraction(draft, extraction)

    assert merged == draft
    assert changes == []


def test_action_schema_rejects_arbitrary_fields_and_unsupported_actions() -> None:
    with pytest.raises(ValueError):
        ProfilePatchAction.model_validate(
            {"action": "run_browser_command", "operation": "set", "value": "open calc", "source_text": "x"}
        )


def test_action_schema_rejects_malformed_weekly_interval_before_merge() -> None:
    with pytest.raises(ValueError):
        ProfileExtraction.model_validate(
            {
                "actions": [
                    {
                        "action": "upsert_weekly_interval",
                        "operation": "set",
                        "value": {"day": 1, "start": "08:00", "end": "10:00"},
                        "match": None,
                        "source_text": "Monday morning is busy",
                    }
                ],
                "questions": [],
            }
        )
    with pytest.raises(ValueError):
        ProfilePatchAction.model_validate(
            {
                "action": "update_drl_goal",
                "operation": "set",
                "value": 90,
                "source_text": "90 diem",
                "invented": True,
            }
        )


def test_score_patch_respects_category_cap() -> None:
    extraction = ProfileExtraction.model_validate(
        {
            "actions": [
                {
                    "action": "update_score",
                    "operation": "set",
                    "value": {"category_id": "C2", "value": 21, "source": "self_reported"},
                    "source_text": "C2 is 21",
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="configured cap"):
        merge_profile_extraction(ProfileAssistantDraft(), extraction)


@pytest.mark.parametrize("message", [
    "T2 hàng tuần mình không rảnh từ 7h30 đến 11h",
    "t2 hang tuan minh ban 7:30-11:00",
])
def test_deterministic_fallback_understands_vietnamese_weekday_time_and_negation(message) -> None:
    extraction = deterministic_profile_extraction(message)

    assert extraction is not None
    interval = extraction.actions[0].value
    assert interval.weekday == 0
    assert interval.start == "07:30"
    assert interval.end == "11:00"
    assert interval.kind == "busy"


def test_deterministic_fallback_completes_clear_multiturn_recurrence() -> None:
    extraction = deterministic_profile_extraction(
        "hàng tuần",
        [{"role": "user", "content": "Thứ 4 mình rảnh 18h đến 20h"},
         {"role": "assistant", "content": "Lịch này lặp hàng tuần phải không?"}],
    )

    assert extraction is not None
    assert extraction.actions[0].value.weekday == 2
    assert extraction.actions[0].value.kind == "available"


def test_deterministic_fallback_asks_one_question_when_time_is_missing() -> None:
    extraction = deterministic_profile_extraction("T6 hàng tuần mình bận")

    assert extraction is not None
    assert extraction.actions == []
    assert len(extraction.questions) == 1


def test_deterministic_extraction_handles_profile_and_preferences_without_erasing_existing() -> None:
    current = ProfileAssistantDraft.model_validate({
        "profile": {"full_name": "", "class_name": "", "major": ""},
        "preference_patch": {"preferred_topics": ["sports"], "preferred_modes": ["offline"]},
    })
    extraction = deterministic_profile_extraction(
        "Mình tên Nguyễn Minh An, lớp 24CNTT1, ngành Khoa học máy tính; thích tình nguyện và online, ưu tiên C4, tối đa 4 hoạt động",
        current=current,
    )

    assert extraction is not None
    merged, changes = merge_profile_extraction(current, extraction)
    assert merged.profile.model_dump() == {
        "full_name": "Nguyễn Minh An", "class_name": "24CNTT1", "major": "Khoa học máy tính"
    }
    assert merged.preference_patch.preferred_topics == ["sports", "volunteer"]
    assert merged.preference_patch.preferred_modes == ["offline", "online"]
    assert merged.preference_patch.preferred_categories == ["C4"]
    assert merged.preference_patch.max_activities == 4
    assert {change.field for change in changes} >= {
        "profile.full_name", "profile.class_name", "profile.major", "preference_patch"
    }


def test_deterministic_extraction_handles_multiple_weekly_intervals() -> None:
    extraction = deterministic_profile_extraction(
        "T2 mình bận 7h30 đến 11h; thứ 4 rảnh 18h-20h; T6 bận 13:00 đến 16:30 hàng tuần"
    )

    assert extraction is not None
    intervals = [action.value for action in extraction.actions if action.action == "upsert_weekly_interval"]
    assert [(item.weekday, item.kind, item.start, item.end) for item in intervals] == [
        (0, "busy", "07:30", "11:00"),
        (2, "available", "18:00", "20:00"),
        (4, "busy", "13:00", "16:30"),
    ]


@pytest.mark.parametrize(("message", "expected"), [
    ("Giam muc tieu xuong 65", 65),
    ("Doi muc tieu thanh 75 diem", 75),
    ("Muc tieu DRL cua minh la 85", 85),
    ("Toi can 90 diem DRL", 90),
    ("Tui muon dat 95 diem ren luyen", 95),
    ("Nang diem ren luyen mong muon len 98", 98),
    ("Muc tieu diem ren luyen la 100", 100),
])
def test_drl_goal_generalizes_to_valid_integer_phrasings(message, expected) -> None:
    extraction = deterministic_profile_extraction(message)
    assert extraction is not None
    assert next(action.value for action in extraction.actions if action.action == "update_drl_goal") == expected


def test_standalone_goal_requires_clear_conversation_context() -> None:
    assert deterministic_profile_extraction("75") is None
    extraction = deterministic_profile_extraction(
        "75",
        [{"role": "assistant", "content": "Ban muon dat bao nhieu diem DRL?"}],
    )
    assert extraction is not None
    assert extraction.actions[0].value == 75


def test_invalid_drl_goal_asks_for_clarification() -> None:
    extraction = deterministic_profile_extraction("Muc tieu DRL cua minh la 105")
    assert extraction is not None
    assert extraction.actions == []
    assert len(extraction.questions) == 1


def test_all_supported_interest_domains_are_recognized() -> None:
    extraction = deterministic_profile_extraction(
        "Thich toan, vat ly, hoa hoc, sinh hoc, lap trinh, tieng Nhat, tai chinh, AI, "
        "cong nghe, nghien cuu khoa hoc, ky nang mem, nghe nghiep, tinh nguyen, moi truong, "
        "nghe thuat, the thao, suc khoe, an toan va giao duc cong dan"
    )
    assert extraction is not None
    preference = next(action.value for action in extraction.actions if action.action == "update_preferences")
    assert set(preference.preferred_topics) == {
        "mathematics", "physics", "chemistry", "biology", "computer_science",
        "foreign_language", "economics_finance", "artificial_intelligence", "technology",
        "research", "soft_skills", "career", "volunteer", "environment", "culture",
        "sports", "health", "safety", "civic_education",
    }


def test_negative_and_edit_operations_do_not_create_positive_preferences() -> None:
    current = ProfileAssistantDraft.model_validate({
        "preference_patch": {"preferred_topics": ["mathematics", "sports", "artificial_intelligence"]}
    })
    extraction = deterministic_profile_extraction(
        "Bo the thao khoi danh sach, them hoa hoc vao so thich",
        current=current,
    )
    assert extraction is not None
    merged, _ = merge_profile_extraction(current, extraction)
    assert merged.preference_patch.preferred_topics == ["mathematics", "artificial_intelligence", "chemistry"]

    negative = deterministic_profile_extraction("Toi khong con thich AI nua", current=current)
    assert negative is not None
    merged, _ = merge_profile_extraction(current, negative)
    assert "artificial_intelligence" not in merged.preference_patch.preferred_topics

    replaced = deterministic_profile_extraction("Doi so thich tu toan sang vat ly", current=current)
    assert replaced is not None
    merged, _ = merge_profile_extraction(current, replaced)
    assert merged.preference_patch.preferred_topics == ["sports", "artificial_intelligence", "physics"]


def test_soft_negative_and_hard_inability_are_not_promoted_to_positive() -> None:
    for message in ("It uu tien the thao", "Khong the tham gia the thao"):
        extraction = deterministic_profile_extraction(message)
        assert extraction is not None
        assert not any(
            action.action == "update_preferences"
            and "sports" in (action.value.preferred_topics or [])
            and action.operation == "add"
            for action in extraction.actions
        )
        assert extraction.questions


def test_multi_intent_mixed_positive_and_negative_topics_with_drl_goal() -> None:
    current = ProfileAssistantDraft.model_validate({
        "drl_target": 80,
        "preference_patch": {"preferred_topics": ["sports", "mathematics"]},
    })
    extraction = deterministic_profile_extraction(
        "Tui muốn đạt 95 điểm rèn luyện, thích hóa học, tiếng Nhật và không thích thể thao.",
        current=current,
    )
    assert extraction is not None
    assert not extraction.questions
    merged, _ = merge_profile_extraction(current, extraction)
    assert merged.drl_target == 95
    assert set(merged.preference_patch.preferred_topics) == {
        "mathematics", "chemistry", "foreign_language",
    }


@pytest.mark.parametrize(("message", "expected_topics"), [
    ("Thích vật lý, hóa học và sinh học.", {"physics", "chemistry", "biology"}),
    ("Quan tâm tiếng Nhật và tiếng Anh.", {"foreign_language"}),
    ("Thích lập trình, bảo mật và công nghệ.", {"computer_science", "safety", "technology"}),
    ("Muốn tham gia hoạt động sức khỏe.", {"health"}),
    ("Thích thiết kế, vẽ và nghệ thuật.", {"culture"}),
    ("Thích hoạt động về tài chính, đầu tư.", {"economics_finance"}),
    ("Quan tâm các cuộc thi nghiên cứu khoa học.", {"research"}),
])
def test_natural_vietnamese_topic_synonyms_and_descriptions(message, expected_topics) -> None:
    extraction = deterministic_profile_extraction(message)
    assert extraction is not None
    assert not extraction.questions
    merged, _ = merge_profile_extraction(ProfileAssistantDraft(), extraction)
    assert set(merged.preference_patch.preferred_topics) == expected_topics


def test_conditional_and_concession_mode_campus_preferences() -> None:
    cond = deterministic_profile_extraction("Nếu phải tham gia trực tiếp thì ưu tiên NVC.")
    assert cond is not None
    assert not cond.questions
    merged_cond, _ = merge_profile_extraction(ProfileAssistantDraft(), cond)
    assert merged_cond.preference_patch.preferred_campuses == ["NVC"]
    assert merged_cond.preference_patch.preferred_modes == []

    conc = deterministic_profile_extraction("Thích online nhưng offline cũng được.")
    assert conc is not None
    assert not conc.questions
    merged_conc, _ = merge_profile_extraction(ProfileAssistantDraft(), conc)
    assert merged_conc.preference_patch.preferred_modes == ["online"]


def test_unresolved_interest_in_comma_list_or_standalone_requests_clarification() -> None:
    for msg in (
        "Mục tiêu ĐRL 95, thích hóa học, thiên văn",
        "Mục tiêu ĐRL 95, thích thiên văn",
    ):
        extraction = deterministic_profile_extraction(msg)
        assert extraction is not None
        assert extraction.questions


def test_relative_dates_use_fixed_simulation_clock() -> None:
    extraction = deterministic_profile_extraction(
        "Ngày mai mình bận 8h đến 10h; thứ 5 tuần này rảnh 14h-16h"
    )
    assert extraction is not None
    merged, _ = merge_profile_extraction(ProfileAssistantDraft(), extraction)
    assert [(str(item.date), item.kind, item.start, item.end) for item in merged.exceptions] == [
        ("2026-11-10", "busy", "08:00", "10:00"),
        ("2026-11-12", "available", "14:00", "16:00"),
    ]

