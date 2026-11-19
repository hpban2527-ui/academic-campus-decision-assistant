from __future__ import annotations

from fastapi.testclient import TestClient

import api.server as server
from personalization.profile_assistant import ProfileExtraction, ProfilePatchAction


class FakeProfileProvider:
    provider_name = "ollama"
    model = "mock-model"

    def interpret_profile(self, text, current_profile, conversation):
        assert current_profile["drl_target"] == 80
        assert conversation[-1]["content"] == "ACTIVE_ONBOARDING_STEP=3"
        return ProfileExtraction(
            actions=[
                ProfilePatchAction(
                    action="update_drl_goal",
                    operation="set",
                    value=90,
                    source_text=text,
                )
            ]
        )


def test_profile_assistant_api_returns_diff_without_persisting(monkeypatch) -> None:
    monkeypatch.setattr(server, "_get_preference_provider", lambda: FakeProfileProvider())
    response = TestClient(server.app).post(
        "/api/profile-assistant/interpret",
        json={"message": "Hãy giúp mình cập nhật mục tiêu", "draft": {"drl_target": 80}, "conversation": [], "onboarding_step": 3},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requires_confirmation"] is True
    assert payload["proposed_draft"]["drl_target"] == 90
    assert payload["changes"][0]["old"] == 80
    assert payload["changes"][0]["new"] == 90
    assert payload["provider"] == "ollama"
    assert payload["latency_ms"] >= 0


def test_profile_assistant_clear_vietnamese_uses_validated_fast_path(monkeypatch) -> None:
    class ProviderMustNotRun:
        provider_name = "ollama"
        model = "mock-model"

        def interpret_profile(self, *args, **kwargs):
            raise AssertionError("clear input should not call Ollama")

    monkeypatch.setattr(server, "_get_preference_provider", lambda: ProviderMustNotRun())
    response = TestClient(server.app).post(
        "/api/profile-assistant/interpret",
        json={"message": "Mục tiêu ĐRL 90", "draft": {"drl_target": 80}, "conversation": [], "onboarding_step": 3},
    )

    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "deterministic-fast-path"
    assert response.json()["proposed_draft"]["drl_target"] == 90


def test_profile_assistant_keeps_all_explicit_multi_intents(monkeypatch) -> None:
    class ProviderMustNotRun:
        provider_name = "ollama"
        model = "mock-model"

        def interpret_profile(self, *args, **kwargs):
            raise AssertionError("fully supported explicit input should be complete")

    monkeypatch.setattr(server, "_get_preference_provider", lambda: ProviderMustNotRun())
    response = TestClient(server.app).post(
        "/api/profile-assistant/interpret",
        json={
            "message": "Tui muá»‘n Ä‘áº¡t 100 Ä‘iá»ƒm rÃ¨n luyá»‡n, Æ°u tiÃªn má»¥c 4, online, Nguyá»…n VÄƒn Cá»«, thÃ­ch ToÃ¡n, AI vÃ  kinh táº¿.",
            "message": "Tui mu\u1ed1n \u0111\u1ea1t 100 \u0111i\u1ec3m r\u00e8n luy\u1ec7n, \u01b0u ti\u00ean m\u1ee5c 4, online, Nguy\u1ec5n V\u0103n C\u1eeb, th\u00edch To\u00e1n, AI v\u00e0 kinh t\u1ebf.",
            "draft": {"drl_target": 80},
            "conversation": [],
            "onboarding_step": 3,
        },
    )

    assert response.status_code == 200, response.text
    draft = response.json()["proposed_draft"]
    assert draft["drl_target"] == 100, response.json()
    assert set(draft["preference_patch"]["preferred_topics"]) == {
        "mathematics", "artificial_intelligence", "economics_finance",
    }
    assert draft["preference_patch"]["preferred_categories"] == ["C4"]
    assert draft["preference_patch"]["preferred_modes"] == ["online"]
    assert draft["preference_patch"]["preferred_campuses"] == ["NVC"]


def test_plan_options_endpoint_returns_three_cacheable_cards(valid_preference_payload) -> None:
    response = TestClient(server.app).post(
        "/api/sp3/personalized/options",
        json={
            "confirmed": True,
            "preference": valid_preference_payload,
            "scenario": "first_plan",
            "total_target": 80,
            "busy_intervals": [],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["options"]) == 3
    assert len(payload["attempted"]) == 3

