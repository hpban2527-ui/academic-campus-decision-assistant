from __future__ import annotations

import json

import httpx
import pytest

from personalization.providers.base import (
    PreferenceProviderInvalidResponse,
    PreferenceProviderUnavailable,
)
from personalization.providers.ollama import OllamaPreferenceProvider


def _provider(handler) -> OllamaPreferenceProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaPreferenceProvider(client=client, model="qwen3:4b")


def test_interpret_sends_schema_and_validates_output(valid_preference_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert body["model"] == "qwen3:4b"
        assert body["stream"] is False
        assert body["think"] is False
        assert body["keep_alive"] == "30m"
        assert body["options"]["temperature"] == 0
        assert body["options"]["num_predict"] == 512
        assert body["format"]["type"] == "object"
        assert body["messages"][1]["content"] == "Em thích toán"
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(valid_preference_payload)}},
        )

    result = _provider(handler).interpret("Em thích toán")

    assert result.topic_preferences[0].topic_id.value == "mathematics"
    # Schema-valid output still passes through the evidence guardrail: the
    # student did not mention a numeric limit, so invented limits are removed.
    assert result.limits.max_activities is None


def test_interpret_rejects_non_schema_ai_output():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": '{"schedule": []}'}})

    with pytest.raises(PreferenceProviderInvalidResponse) as error:
        _provider(handler).interpret("Tự tạo lịch cho tôi")

    assert error.value.code == "AI_INVALID_SCHEMA"


def test_interpret_reports_unavailable_ollama():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(PreferenceProviderUnavailable) as error:
        _provider(handler).interpret("Em thích online")

    assert error.value.code == "AI_UNAVAILABLE"


def test_health_reports_installed_model():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]})

    health = _provider(handler).health()

    assert health.available is True
    assert health.model == "qwen3:4b"


def test_health_explains_missing_model():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3:1.7b"}]})

    health = _provider(handler).health()

    assert health.available is False
    assert health.code == "AI_MODEL_NOT_FOUND"
    assert "ollama pull qwen3:4b" in (health.message or "")
