"""API tests for AI-assisted preference interpretation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api import server
from personalization.models import StudentPreference
from personalization.providers.base import (
    PreferenceProviderInvalidResponse,
    PreferenceProviderUnavailable,
    ProviderHealth,
)


client = TestClient(server.app)


class _FakeProvider:
    provider_name = "ollama"
    model = "qwen3:4b"

    def __init__(self, payload):
        self.payload = payload

    def health(self):
        return ProviderHealth(True, self.provider_name, self.model)

    def interpret(self, text):
        return StudentPreference.model_validate(self.payload)


def test_health_endpoint_reports_provider_readiness(monkeypatch, valid_preference_payload):
    fake = _FakeProvider(valid_preference_payload)
    monkeypatch.setattr(server, "_get_preference_provider", lambda: fake)

    response = client.get("/api/preferences/ai-health")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "provider": "ollama",
        "model": "qwen3:4b",
        "code": None,
        "message": None,
    }


def test_interpret_endpoint_returns_validated_preference(monkeypatch, valid_preference_payload):
    server.preference_interpret_cache.clear()
    fake = _FakeProvider(valid_preference_payload)
    monkeypatch.setattr(server, "_get_preference_provider", lambda: fake)

    response = client.post(
        "/api/preferences/interpret",
        json={"text": "  Em thích toán và ưu tiên online  ", "force_ai": True},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["provider"] == "ollama"
    assert result["model"] == "qwen3:4b"
    assert result["cached"] is False
    assert result["processing_ms"] >= 0
    assert result["preference"]["topic_preferences"][0]["topic_id"] == "mathematics"


def test_explicit_preference_bypasses_slow_ai(monkeypatch):
    def must_not_build_provider():
        raise AssertionError("explicit preference should not call AI")

    monkeypatch.setattr(server, "_get_preference_provider", must_not_build_provider)

    response = client.post(
        "/api/preferences/interpret",
        json={"text": "Em thích Toán, ưu tiên online và mục 4. Tối đa 4 hoạt động."},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["method"] == "FAST_RULES"
    assert result["provider"] == "deterministic"
    assert result["model"] is None
    assert result["preference"]["limits"]["max_activities"] == 4


def test_interpret_endpoint_reuses_same_normalized_text(monkeypatch, valid_preference_payload):
    server.preference_interpret_cache.clear()
    fake = _FakeProvider(valid_preference_payload)
    calls = 0

    def interpret(text):
        nonlocal calls
        calls += 1
        return StudentPreference.model_validate(valid_preference_payload)

    fake.interpret = interpret
    monkeypatch.setattr(server, "_get_preference_provider", lambda: fake)

    first = client.post("/api/preferences/interpret", json={"text": "Em thích Toán", "force_ai": True})
    second = client.post("/api/preferences/interpret", json={"text": "  em THÍCH toán  ", "force_ai": True})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert calls == 1


def test_interpret_endpoint_rejects_blank_text():
    response = client.post("/api/preferences/interpret", json={"text": "   "})
    assert response.status_code == 422


def test_interpret_endpoint_rejects_extra_request_fields():
    response = client.post(
        "/api/preferences/interpret",
        json={"text": "Em thích toán", "student_score": 100},
    )
    assert response.status_code == 422


def test_interpret_endpoint_maps_unavailable_provider_to_503(monkeypatch):
    def unavailable():
        raise PreferenceProviderUnavailable("AI_UNAVAILABLE", "Ollama chưa chạy.")

    monkeypatch.setattr(server, "_get_preference_provider", unavailable)

    response = client.post("/api/preferences/interpret", json={"text": "Em thích toán", "force_ai": True})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_UNAVAILABLE"


def test_interpret_endpoint_maps_invalid_ai_output_to_502(monkeypatch, valid_preference_payload):
    server.preference_interpret_cache.clear()
    fake = _FakeProvider(valid_preference_payload)

    def invalid_output(text):
        raise PreferenceProviderInvalidResponse("AI_INVALID_SCHEMA", "Sai schema.")

    fake.interpret = invalid_output
    monkeypatch.setattr(server, "_get_preference_provider", lambda: fake)

    response = client.post("/api/preferences/interpret", json={"text": "Em thích toán", "force_ai": True})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "AI_INVALID_SCHEMA"
