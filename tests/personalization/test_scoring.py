from __future__ import annotations

from copy import deepcopy

from personalization.models import StudentPreference
from personalization.scoring import ActivityFeatures, PreferenceUtilityEngine


def test_weighted_utility_uses_all_confirmed_dimensions(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)
    engine = PreferenceUtilityEngine(
        preference,
        {
            "A": ActivityFeatures(
                frozenset({"mathematics"}),
                "NVC",
                frozenset({"weekday_evening"}),
            )
        },
        {"A": {"mode": "online", "fee": 0}},
    )

    result = engine.score_activity("A", "C4")

    assert result.utility == 24
    assert {(item.dimension, item.value, item.weight) for item in result.matches} == {
        ("topic", "mathematics", 5),
        ("category", "C4", 5),
        ("campus", "NVC", 5),
        ("mode", "online", 5),
        ("time", "weekday_evening", 4),
    }


def test_hard_exclusions_and_fee_limit_are_fail_closed(valid_preference_payload):
    payload = valid_preference_payload
    payload["campus_preferences"] = []
    payload["mode_preferences"] = []
    payload["time_preferences"] = []
    payload["hard_exclusions"] = {
        "campus_ids": ["DONG_HOA"],
        "modes": ["offline"],
        "time_slots": ["weekend_morning"],
    }
    payload["limits"]["max_fee"] = 50_000
    preference = StudentPreference.model_validate(payload)
    engine = PreferenceUtilityEngine(
        preference,
        {"A": ActivityFeatures(frozenset(), "DONG_HOA", frozenset({"weekend_morning"}))},
        {"A": {"mode": "offline", "fee": 100_000}},
    )

    assert engine.hard_exclusion_reasons("A") == [
        "campus:DONG_HOA",
        "mode:offline",
        "time:weekend_morning",
        "fee>50000",
    ]


def test_set_utility_uses_sp2_contribution_category(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)
    engine = PreferenceUtilityEngine(
        preference,
        {"A": ActivityFeatures(frozenset(), None, frozenset())},
        {"A": {"mode": "offline", "fee": 0}},
    )

    utility = engine.score_set(
        ("A",),
        {"contributions": [{"activity_id": "A", "category_id": "C4"}]},
    )

    assert utility == 5.0


def test_undetermined_campus_is_excluded_only_when_a_campus_is_impossible(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["campus_preferences"] = []
    payload["hard_exclusions"]["campus_ids"] = ["DONG_HOA"]
    with_exclusion = PreferenceUtilityEngine(
        StudentPreference.model_validate(payload),
        {"A": ActivityFeatures(frozenset(), None, frozenset()),
         "B": ActivityFeatures(frozenset(), None, frozenset()),
         "C": ActivityFeatures(frozenset(), "NVC", frozenset())},
        {"A": {"mode": "offline", "fee": 0}, "B": {"mode": "online", "fee": 0}, "C": {"mode": "offline", "fee": 0}},
    )
    assert with_exclusion.hard_exclusion_reasons("A") == ["campus:unknown"]   # venue unknown, could be DONG_HOA
    assert with_exclusion.hard_exclusion_reasons("B") == []                   # online: no campus to avoid
    assert with_exclusion.hard_exclusion_reasons("C") == []                   # known other campus

    payload["hard_exclusions"]["campus_ids"] = []
    without = PreferenceUtilityEngine(
        StudentPreference.model_validate(payload),
        {"A": ActivityFeatures(frozenset(), None, frozenset())},
        {"A": {"mode": "offline", "fee": 0}},
    )
    assert without.hard_exclusion_reasons("A") == []        # a mere preference never bans an activity
