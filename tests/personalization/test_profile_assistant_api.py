from __future__ import annotations

from fastapi.testclient import TestClient

import api.server as server
from personalization.profile_assistant import ProfileExtraction, ProfilePatchAction


class FakeProfileProvider:
    provider_name = "ollama"
    model = "mock-model"

    def interpret_profile(self, text, current_profile, conversation):
        assert current_profile["drl_target"] == 80
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
        json={"message": "Doi muc tieu thanh 90", "draft": {"drl_target": 80}, "conversation": []},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requires_confirmation"] is True
    assert payload["proposed_draft"]["drl_target"] == 90
    assert payload["changes"][0]["old"] == 80
    assert payload["changes"][0]["new"] == 90
    assert payload["provider"] == "ollama"


def test_plan_options_endpoint_returns_deduplicated_cache_payload(valid_preference_payload) -> None:
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
    assert 1 <= len(payload["options"]) <= 3
    assert len(payload["attempted"]) == 3

