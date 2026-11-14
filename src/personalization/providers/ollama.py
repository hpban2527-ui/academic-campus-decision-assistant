"""Ollama implementation of the preference interpreter."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from personalization.models import StudentPreference
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
        num_predict: int = 512,
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


def _model_is_installed(requested: str, installed: set[str]) -> bool:
    if requested in installed:
        return True
    if ":" not in requested and f"{requested}:latest" in installed:
        return True
    return False
