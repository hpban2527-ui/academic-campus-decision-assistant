from __future__ import annotations

from copy import deepcopy

import pytest

from personalization.profile_assistant import (
    ProfileAssistantDraft,
    ProfileExtraction,
    ProfilePatchAction,
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

