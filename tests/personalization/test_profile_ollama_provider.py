from __future__ import annotations

import httpx
import pytest

from personalization.profile_assistant import ProfileExtraction
from personalization.providers.base import PreferenceProviderInvalidResponse, PreferenceProviderUnavailable
from personalization.providers.ollama import OllamaPreferenceProvider


def test_profile_interpret_uses_ollama_schema_and_validates_actions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload["format"] == ProfileExtraction.model_json_schema()
        assert "current profile" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": '{"actions":[{"action":"update_drl_goal","operation":"set","value":90,"match":null,"source_text":"90 diem"}],"questions":[]}'
                }
            },
        )

    provider = OllamaPreferenceProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.interpret_profile("doi muc tieu", {"drl_target": 80}, [])

    assert result.actions[0].action == "update_drl_goal"


def test_profile_interpret_surfaces_timeout_and_malformed_response() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = OllamaPreferenceProvider(client=httpx.Client(transport=httpx.MockTransport(timeout_handler)))
    with pytest.raises(PreferenceProviderUnavailable):
        provider.interpret_profile("hello", {}, [])

    provider = OllamaPreferenceProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"message": {"content": "{}"}}))
        )
    )
    with pytest.raises(PreferenceProviderInvalidResponse):
        provider.interpret_profile("hello", {}, [])


def test_profile_interpret_grounds_weekday_and_audit_text_in_user_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": '{"actions":[{"action":"upsert_weekly_interval","operation":"set","value":{"kind":"busy","weekday":1,"start":"08:00","end":"10:00","recurrence":"weekly","source":"ai","confirmed":false},"match":null,"source_text":"made up quote"}],"questions":[]}'
                }
            },
        )

    provider = OllamaPreferenceProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    message = "Thu Hai hang tuan minh ban tu 08:00 den 10:00."
    result = provider.interpret_profile(message, {}, [])

    assert result.actions[0].value.weekday == 0
    assert result.actions[0].source_text == message

