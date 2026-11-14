from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from personalization.models import InterpretPreferenceRequest, StudentPreference


def test_valid_preference_contract_is_serializable(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)

    serialized = preference.model_dump(mode="json")
    assert serialized["topic_preferences"][0] == {
        "topic_id": "mathematics",
        "weight": 5,
    }
    assert serialized["strategy"] == "BALANCED"


@pytest.mark.parametrize("weight", [0, 6])
def test_weight_must_stay_between_one_and_five(valid_preference_payload, weight):
    payload = deepcopy(valid_preference_payload)
    payload["topic_preferences"][0]["weight"] = weight

    with pytest.raises(ValidationError):
        StudentPreference.model_validate(payload)


def test_unknown_strategy_is_rejected(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["strategy"] = "LET_AI_DECIDE"

    with pytest.raises(ValidationError):
        StudentPreference.model_validate(payload)


def test_zero_max_activities_is_rejected(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["limits"]["max_activities"] = 0

    with pytest.raises(ValidationError):
        StudentPreference.model_validate(payload)


def test_ai_cannot_invent_extra_fields(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["recommended_activity_ids"] = ["invented-by-ai"]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StudentPreference.model_validate(payload)


def test_duplicate_preferences_are_rejected(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["mode_preferences"].append({"mode": "online", "weight": 3})

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        StudentPreference.model_validate(payload)


def test_soft_preference_cannot_also_be_hard_exclusion(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["hard_exclusions"]["modes"] = ["online"]

    with pytest.raises(ValidationError, match="mode preference and hard exclusion conflict"):
        StudentPreference.model_validate(payload)


def test_interpret_request_strips_text():
    request = InterpretPreferenceRequest(text="  Em thích toán  ")
    assert request.text == "Em thích toán"


def test_interpret_request_rejects_whitespace_only():
    with pytest.raises(ValidationError, match="must contain a preference description"):
        InterpretPreferenceRequest(text="   ")
