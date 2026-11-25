"""A hard budget is never certified with an unknown cost (operational dataset, sp3-activity/0.3)."""
from __future__ import annotations

from api import sp3_real
from personalization.models import StudentPreference
from personalization.scoring import ActivityFeatures, PreferenceUtilityEngine


def test_unknown_fee_is_hard_excluded_under_a_budget_and_never_selected(valid_preference_payload):
    payload = dict(valid_preference_payload, limits={"max_activities": 6, "max_duration_minutes": 2000, "max_fee": 0})
    result = sp3_real.real_plan("first_plan", term_id="HK1_2026_2027", target_total=80, preference=StudentPreference.model_validate(payload))
    fees = {c["activity"]["activity_id"]: c["activity"]["fee"] for c in result["feasibility"]["candidates"]}
    excluded = {item["activity_id"]: item["reasons"] for item in result["personalization"]["hard_excluded"]}
    status = {c["activity"]["activity_id"]: c["feasibility"]["status"] for c in result["feasibility"]["candidates"]}
    unknown = [aid for aid, fee in fees.items() if fee is None]
    assert any("fee:unknown" in excluded.get(aid, []) for aid in unknown)
    assert all(status[aid] != "FEASIBLE" for aid in unknown)
    for item in result["plan"]["selected_activities"]:
        assert fees[item["activity_id"]] is not None and fees[item["activity_id"]] <= 0


def test_without_a_budget_unknown_fee_is_not_a_gate(valid_preference_payload):
    payload = dict(valid_preference_payload, limits={"max_activities": 6, "max_duration_minutes": 2000, "max_fee": None})
    preference = StudentPreference.model_validate(payload)
    engine = PreferenceUtilityEngine(preference, {"A": ActivityFeatures(frozenset(), None, frozenset())},
                              {"A": {"mode": "online", "fee": None}})
    assert engine.hard_exclusion_reasons("A") == []
