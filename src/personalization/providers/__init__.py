"""Preference AI provider factory."""

from __future__ import annotations

import os

from personalization.providers.base import (
    PreferenceAIProvider,
    PreferenceProviderError,
    PreferenceProviderInvalidResponse,
    PreferenceProviderUnavailable,
    ProviderHealth,
)
from personalization.providers.ollama import OllamaPreferenceProvider


def preference_provider_from_env() -> PreferenceAIProvider:
    provider = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    if provider != "ollama":
        raise PreferenceProviderUnavailable(
            "AI_PROVIDER_UNSUPPORTED",
            f"AI provider '{provider}' chưa được hỗ trợ trong phiên bản này.",
        )
    timeout_text = os.getenv("OLLAMA_TIMEOUT_SECONDS", "60")
    try:
        timeout = float(timeout_text)
    except ValueError as exc:
        raise PreferenceProviderUnavailable(
            "AI_CONFIG_INVALID",
            "OLLAMA_TIMEOUT_SECONDS phải là một số dương.",
        ) from exc
    if timeout <= 0:
        raise PreferenceProviderUnavailable(
            "AI_CONFIG_INVALID",
            "OLLAMA_TIMEOUT_SECONDS phải là một số dương.",
        )
    num_predict_text = os.getenv("OLLAMA_NUM_PREDICT", "512")
    try:
        num_predict = int(num_predict_text)
    except ValueError as exc:
        raise PreferenceProviderUnavailable(
            "AI_CONFIG_INVALID",
            "OLLAMA_NUM_PREDICT phải là một số nguyên dương.",
        ) from exc
    if num_predict <= 0:
        raise PreferenceProviderUnavailable(
            "AI_CONFIG_INVALID",
            "OLLAMA_NUM_PREDICT phải là một số nguyên dương.",
        )
    return OllamaPreferenceProvider(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        timeout_seconds=timeout,
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        num_predict=num_predict,
    )


__all__ = [
    "OllamaPreferenceProvider",
    "PreferenceAIProvider",
    "PreferenceProviderError",
    "PreferenceProviderInvalidResponse",
    "PreferenceProviderUnavailable",
    "ProviderHealth",
    "preference_provider_from_env",
]
