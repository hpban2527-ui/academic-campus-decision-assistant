"""Ollama implementation of the preference interpreter."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import httpx
from pydantic import ValidationError

from personalization.models import StudentPreference
from personalization.profile_assistant import (
    PROFILE_EXTRACTION_PROMPT,
    ProfileExtraction,
    deterministic_profile_extraction,
)
from personalization.normalization import normalize_ai_preference
from personalization.prompt import build_system_prompt
from personalization.providers.base import (
    PreferenceProviderInvalidResponse,
    PreferenceProviderUnavailable,
    ProviderHealth,
)


class OllamaPreferenceProvider:
    provider_name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:4b",
        timeout_seconds: float = 60.0,
        keep_alive: str = "30m",
        num_predict: int = 1024,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self._client = client

    def health(self) -> ProviderHealth:
        try:
            response = self._request("GET", "/api/tags")
            response.raise_for_status()
            payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            return ProviderHealth(
                available=False,
                provider=self.provider_name,
                model=self.model,
                code="AI_UNAVAILABLE",
                message="Không thể kết nối Ollama. Hãy chạy 'ollama serve'.",
            )

        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            return ProviderHealth(
                available=False,
                provider=self.provider_name,
                model=self.model,
                code="AI_INVALID_RESPONSE",
                message="Ollama trả về danh sách model không hợp lệ.",
            )

        installed = {
            str(item.get("name") or item.get("model"))
            for item in payload.get("models", [])
            if isinstance(item, dict) and (item.get("name") or item.get("model"))
        }
        if not _model_is_installed(self.model, installed):
            return ProviderHealth(
                available=False,
                provider=self.provider_name,
                model=self.model,
                code="AI_MODEL_NOT_FOUND",
                message=f"Chưa có model {self.model}. Hãy chạy 'ollama pull {self.model}'.",
            )
        return ProviderHealth(True, self.provider_name, self.model)

    def interpret(self, text: str) -> StudentPreference:
        request_body = {
            "model": self.model,
            "stream": False,
            "think": False,
            # Avoid paying the model-load cost for every edit/confirmation
            # cycle in the UI. Ollama accepts duration strings here.
            "keep_alive": self.keep_alive,
            "format": StudentPreference.model_json_schema(),
            # A complete StudentPreference is compact. The old 1,000-token
            # ceiling allowed small local models to spend too long on a bad
            # response before the schema guard rejected it.
            "options": {"temperature": 0, "num_predict": self.num_predict},
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": text},
            ],
        }
        try:
            response = self._request(
                "POST",
                "/api/chat",
                json=request_body,
            )
        except httpx.TimeoutException as exc:
            raise PreferenceProviderUnavailable(
                "AI_TIMEOUT",
                "AI mất quá nhiều thời gian phản hồi. Vui lòng thử lại.",
            ) from exc
        except httpx.RequestError as exc:
            raise PreferenceProviderUnavailable(
                "AI_UNAVAILABLE",
                "Không thể kết nối Ollama. Hãy kiểm tra dịch vụ AI local.",
            ) from exc

        if response.status_code == 404:
            raise PreferenceProviderUnavailable(
                "AI_MODEL_NOT_FOUND",
                f"Ollama chưa có model {self.model}.",
            )
        if response.status_code >= 500:
            raise PreferenceProviderUnavailable(
                "AI_UPSTREAM_ERROR",
                "Ollama đang gặp lỗi. Vui lòng thử lại sau.",
            )
        if response.status_code != 200:
            raise PreferenceProviderInvalidResponse(
                "AI_REQUEST_REJECTED",
                "Ollama từ chối yêu cầu phân tích preference.",
            )

        content = _extract_content(response)
        try:
            preference = StudentPreference.model_validate_json(content)
        except ValidationError as exc:
            raise PreferenceProviderInvalidResponse(
                "AI_INVALID_SCHEMA",
                "AI trả về preference không đúng cấu trúc an toàn.",
            ) from exc
        return normalize_ai_preference(text, preference)

    def interpret_profile(
        self,
        text: str,
        current_profile: dict[str, Any],
        conversation: list[dict[str, str]],
    ) -> ProfileExtraction:
        """Extract strict profile PATCH actions through the real Ollama provider."""

        active_step = next((
            turn.get("content", "").split("=", 1)[1]
            for turn in reversed(conversation)
            if turn.get("content", "").startswith("ACTIVE_ONBOARDING_STEP=")
        ), None)
        step_fields = {
            "1": ("profile",),
            "2": ("weekly_intervals", "exceptions"),
            "3": ("drl_target", "preference_patch"),
        }
        relevant = step_fields.get(active_step, tuple(current_profile))
        compact_profile = {key: current_profile.get(key) for key in relevant if key in current_profile}
        context = json.dumps(compact_profile, ensure_ascii=False, sort_keys=True)
        history = json.dumps(conversation[-6:], ensure_ascii=False)
        messages = [
            {"role": "system", "content": PROFILE_EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"active step: {active_step or 'profile edit'}\ncurrent profile: {context}\nconversation: {history}\nnew message: {text}",
            },
        ]
        request_body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            # Keep Ollama's decoding grammar compact. The richer discriminated
            # action contract is still enforced by Pydantic below.
            "format": _PROFILE_EXTRACTION_FORMAT,
            "options": {"temperature": 0, "num_predict": self.num_predict},
            "messages": messages,
        }
        last_error: PreferenceProviderInvalidResponse | None = None
        for attempt in range(2):
            if attempt:
                request_body["messages"] = messages + [
                    {
                        "role": "user",
                        "content": (
                            "Phan hoi truoc khong hop le hoac bi cat. Tra lai MOT JSON object ngan gon, "
                            "dung schema; chi gom action duoc noi ro hoac mot cau hoi lam ro."
                        ),
                    }
                ]
                request_body["options"] = {
                    "temperature": 0,
                    "num_predict": min(max(self.num_predict * 2, 1024), 2048),
                }
            response = self._profile_request(request_body)
            try:
                extraction = _validate_profile_content(_extract_content(response))
                extraction = _ground_profile_extraction(text, extraction)
                return _supplement_clear_actions(text, conversation, current_profile, extraction)
            except ValidationError as exc:
                last_error = PreferenceProviderInvalidResponse(
                    "AI_INVALID_SCHEMA",
                    "AI trả về thay đổi hồ sơ không đúng cấu trúc an toàn sau khi đã thử sửa một lần.",
                )
                last_error.__cause__ = exc
            except PreferenceProviderInvalidResponse as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _profile_request(self, request_body: dict[str, Any]) -> httpx.Response:
        try:
            response = self._request("POST", "/api/chat", json=request_body)
        except httpx.TimeoutException as exc:
            raise PreferenceProviderUnavailable("AI_TIMEOUT", "AI mất quá nhiều thời gian phản hồi.") from exc
        except httpx.RequestError as exc:
            raise PreferenceProviderUnavailable("AI_UNAVAILABLE", "Không thể kết nối Ollama.") from exc
        if response.status_code == 404:
            raise PreferenceProviderUnavailable("AI_MODEL_NOT_FOUND", f"Ollama chưa có model {self.model}.")
        if response.status_code >= 500:
            raise PreferenceProviderUnavailable("AI_UPSTREAM_ERROR", "Ollama đang gặp lỗi.")
        if response.status_code != 200:
            raise PreferenceProviderInvalidResponse("AI_REQUEST_REJECTED", "Ollama từ chối yêu cầu.")
        return response

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        if self._client is not None:
            return self._client.request(method, url, timeout=self.timeout_seconds, **kwargs)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.request(method, url, **kwargs)


def _extract_content(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
        content = payload["message"]["content"]
    except (ValueError, TypeError, KeyError) as exc:
        raise PreferenceProviderInvalidResponse(
            "AI_INVALID_RESPONSE",
            "Không đọc được phản hồi từ Ollama.",
        ) from exc
    if payload.get("done") is False or payload.get("done_reason") == "length":
        raise PreferenceProviderInvalidResponse(
            "AI_TRUNCATED_RESPONSE",
            "Phản hồi AI bị cắt trước khi hoàn tất. Hãy rút gọn yêu cầu hoặc thử lại.",
        )
    if not isinstance(content, str):
        raise PreferenceProviderInvalidResponse(
            "AI_INVALID_RESPONSE",
            "Phản hồi Ollama không chứa nội dung JSON dạng chuỗi.",
        )
    # Reject a JSON string containing another serialized JSON document.
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PreferenceProviderInvalidResponse(
            "AI_INVALID_JSON",
            "AI không trả về JSON hợp lệ.",
        ) from exc
    if not isinstance(parsed, dict):
        raise PreferenceProviderInvalidResponse(
            "AI_INVALID_JSON",
            "AI phải trả về một JSON object.",
        )
    return content


_PROFILE_EXTRACTION_FORMAT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["actions", "questions"],
    "properties": {
        "actions": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "operation", "value", "match", "source_text"],
                "properties": {
                    "action": {"type": "string", "enum": [
                        "update_drl_goal", "upsert_weekly_interval", "remove_weekly_interval",
                        "upsert_exception", "remove_exception", "update_preferences",
                        "update_profile_field", "update_score",
                    ]},
                    "operation": {"type": "string", "enum": ["add", "replace", "remove", "set"]},
                    "value": {"type": ["object", "integer", "null"]},
                    "match": {"type": ["object", "null"]},
                    "source_text": {"type": "string", "maxLength": 500},
                },
            },
        },
        "questions": {"type": "array", "maxItems": 1, "items": {"type": "string"}},
    },
}


def _model_is_installed(requested: str, installed: set[str]) -> bool:
    if requested in installed:
        return True
    if ":" not in requested and f"{requested}:latest" in installed:
        return True
    return False


def _validate_profile_content(content: str) -> ProfileExtraction:
    """Validate model output, discarding only semantically irrelevant match noise."""

    payload = json.loads(content)
    actions = payload.get("actions") if isinstance(payload, dict) else None
    if isinstance(actions, list):
        normalized_actions: list[Any] = []
        for action in actions:
            if not isinstance(action, dict):
                normalized_actions.append(action)
                continue
            name = action.get("action")
            operation = action.get("operation")
            value = action.get("value")
            if name == "update_profile_field" and isinstance(value, dict):
                aliases = {"class": "class_name"}
                allowed_fields = {"full_name", "class_name", "major"}
                normalized_value = {
                    aliases.get(key, key): item
                    for key, item in value.items()
                    if aliases.get(key, key) in allowed_fields
                }
                if normalized_value:
                    # Ignore model-invented profile keys (for example `school`);
                    # deterministic grounding can still recover explicit supported
                    # fields from the user's text after this payload validates.
                    for field, item in normalized_value.items():
                        normalized_actions.append({**action, "value": {field: item}, "match": None})
                    continue
            if name not in {"remove_weekly_interval", "remove_exception"} and not (
                name == "upsert_weekly_interval" and operation == "replace"
            ):
                # Small local models sometimes echo current-profile fields into
                # `match`. Match has no meaning for these actions, so dropping it
                # cannot broaden or fabricate the requested change.
                action["match"] = None
            normalized_actions.append(action)
        payload["actions"] = normalized_actions
    return ProfileExtraction.model_validate(payload)


def _ground_profile_extraction(user_text: str, extraction: ProfileExtraction) -> ProfileExtraction:
    """Ground audit text and unambiguous weekday mentions in the user's words."""

    payload = extraction.model_dump(mode="json", exclude_unset=True)
    whole_message_days = _mentioned_weekdays(user_text)
    for index, action in enumerate(payload["actions"]):
        action["source_text"] = user_text.strip()[:500]
        if action["action"] != "upsert_weekly_interval" or not isinstance(action.get("value"), dict):
            continue
        source_days = _mentioned_weekdays(extraction.actions[index].source_text)
        grounded_days = source_days if len(source_days) == 1 else whole_message_days
        if len(grounded_days) == 1:
            action["value"]["weekday"] = next(iter(grounded_days))
    return ProfileExtraction.model_validate(payload)


def _supplement_clear_actions(
    user_text: str,
    conversation: list[dict[str, str]],
    current_profile: dict[str, Any],
    extraction: ProfileExtraction,
) -> ProfileExtraction:
    """Add only high-confidence deterministic actions the model omitted."""

    deterministic = deterministic_profile_extraction(user_text, conversation, current_profile)
    if deterministic is None or not deterministic.actions:
        return extraction
    existing = {_profile_action_identity(action) for action in extraction.actions}
    additions = [action for action in deterministic.actions if _profile_action_identity(action) not in existing]
    if not additions:
        return extraction
    return ProfileExtraction(actions=[*extraction.actions, *additions], questions=[])


def _profile_action_identity(action: Any) -> tuple[Any, ...]:
    value = action.value.model_dump(mode="json", exclude_unset=True) if hasattr(action.value, "model_dump") else action.value
    if action.action == "update_profile_field" and isinstance(value, dict):
        return (action.action, *sorted(value))
    if action.action == "update_preferences" and isinstance(value, dict):
        return (action.action, *sorted(value))
    if action.action in {"upsert_weekly_interval", "upsert_exception"} and isinstance(value, dict):
        return (action.action, value.get("date"), value.get("weekday"), value.get("kind"), value.get("start"), value.get("end"))
    return (action.action,)


def _mentioned_weekdays(text: str) -> set[int]:
    normalized = unicodedata.normalize("NFD", text.casefold())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    patterns = {
        0: r"\b(?:thu\s*(?:hai|2)|monday)\b",
        1: r"\b(?:thu\s*(?:ba|3)|tuesday)\b",
        2: r"\b(?:thu\s*(?:tu|4)|wednesday)\b",
        3: r"\b(?:thu\s*(?:nam|5)|thursday)\b",
        4: r"\b(?:thu\s*(?:sau|6)|friday)\b",
        5: r"\b(?:thu\s*(?:bay|7)|saturday)\b",
        6: r"\b(?:chu\s*nhat|sunday)\b",
    }
    return {weekday for weekday, pattern in patterns.items() if re.search(pattern, normalized)}
