from __future__ import annotations

import httpx
import pytest

from personalization.providers.base import PreferenceProviderInvalidResponse, PreferenceProviderUnavailable
from personalization.providers.ollama import OllamaPreferenceProvider


def test_profile_interpret_uses_ollama_schema_and_validates_actions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload["format"]["properties"]["actions"]["maxItems"] == 20
        assert "$defs" not in payload["format"]
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


def test_profile_interpret_splits_grouped_profile_fields_from_small_model() -> None:
    content = (
        '{"actions":[{"action":"update_profile_field","operation":"set",'
        '"value":{"class":"24CNTT1","major":"Khoa hoc may tinh"},'
        '"match":null,"source_text":"lop va nganh"}],"questions":[]}'
    )
    provider = OllamaPreferenceProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"message": {"content": content}})
            )
        )
    )

    result = provider.interpret_profile("lop 24CNTT1, nganh Khoa hoc may tinh", {}, [])

    assert [action.value.model_dump(exclude_unset=True) for action in result.actions] == [
        {"class_name": "24CNTT1"},
        {"major": "Khoa hoc may tinh"},
    ]


def test_profile_interpret_discards_unknown_grouped_field_but_keeps_supported_patch() -> None:
    content = (
        '{"actions":[{"action":"update_profile_field","operation":"set",'
        '"value":{"school":"lop 24CNTT1","major":"Khoa hoc may tinh"},'
        '"match":null,"source_text":"lop va nganh"}],"questions":[]}'
    )
    provider = OllamaPreferenceProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"message": {"content": content}})
            )
        )
    )

    result = provider.interpret_profile("lop 24CNTT1, nganh Khoa hoc may tinh", {}, [])

    patches = [action.value.model_dump(exclude_unset=True) for action in result.actions]
    assert {tuple(patch.items()) for patch in patches} == {
        (("class_name", "24CNTT1"),),
        (("major", "Khoa hoc may tinh"),),
    }


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


def test_profile_interpret_retries_once_after_truncated_json() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"done": True, "done_reason": "length", "message": {"content": '{"actions":['}},
            )
        return httpx.Response(
            200,
            json={"done": True, "done_reason": "stop", "message": {"content": '{"actions":[],"questions":["Bạn muốn đổi mục nào?"]}'}},
        )

    provider = OllamaPreferenceProvider(
        num_predict=512,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.interpret_profile("đổi hồ sơ", {}, [])

    assert result.questions == ["Bạn muốn đổi mục nào?"]
    assert len(calls) == 2
    assert calls[1]["options"]["num_predict"] == 1024


def test_profile_interpret_never_retries_more_than_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"message": {"content": '{"actions":['}})

    provider = OllamaPreferenceProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PreferenceProviderInvalidResponse, match="JSON"):
        provider.interpret_profile("đổi hồ sơ", {}, [])
    assert calls == 2


def test_profile_interpret_supplements_only_clear_action_omitted_by_small_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"content": '{"actions":[{"action":"update_drl_goal","operation":"set","value":90,"match":{"drl_target":80},"source_text":"x"}],"questions":["Lịch nào?"]}'}},
        )

    provider = OllamaPreferenceProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.interpret_profile(
        "T2 hàng tuần mình không rảnh 7h30 đến 11h, mục tiêu DRL 90",
        {"drl_target": 80},
        [],
    )

    assert [action.action for action in result.actions] == ["update_drl_goal", "upsert_weekly_interval"]
    assert result.questions == []

