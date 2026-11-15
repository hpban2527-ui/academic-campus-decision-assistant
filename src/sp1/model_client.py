"""Model client for SP1 v2's two prompts (classify, roles) against a served Qwen model.

The batch run used Qwen/Qwen3.5-4B through transformers on Kaggle: one user message, greedy decoding,
thinking disabled, at most 256 (classify) / 768 (roles) new tokens. This client sends the same request to
a served model so a single new post is processed like the batch posts.

Configuration (backend environment; the API key is never logged or returned):
  SP1_LLM_PROVIDER         openai_compatible (default: vLLM, llama.cpp server, LM Studio) or ollama
  SP1_LLM_BASE_URL         service URL (default http://localhost:8001 or http://localhost:11434 for ollama)
  SP1_LLM_MODEL            model ID requested from the service (default Qwen/Qwen3.5-4B, the batch model)
  SP1_LLM_TIMEOUT_SECONDS  per call (default 120)
  SP1_LLM_API_KEY          optional bearer token for openai_compatible services
This is separate from the preference interpreter's OLLAMA_MODEL (default qwen3:4b): a different model,
prompt and purpose.

Every call returns the model ID the service reports for that reply. A reply from another model than the
one requested is rejected (MODEL_MISMATCH), so a recorded model ID always names the model that answered.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

BATCH_MODEL_ID = "Qwen/Qwen3.5-4B"
PROVIDERS = ("openai_compatible", "ollama")
DEFAULT_BASE_URLS = {"openai_compatible": "http://localhost:8001", "ollama": "http://localhost:11434"}
MAX_TOKENS = {"classify": 256, "roles": 768}   # the batch run's max_new_tokens


class SP1ModelError(RuntimeError):
    """A model call failed. code is stable and safe to show; message never contains credentials."""

    def __init__(self, code: str, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class SP1ModelConfig:
    provider: str = "openai_compatible"
    base_url: str = DEFAULT_BASE_URLS["openai_compatible"]
    model: str = BATCH_MODEL_ID
    timeout_seconds: float = 120.0
    api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "SP1ModelConfig":
        env = os.environ if env is None else env
        provider = (env.get("SP1_LLM_PROVIDER") or "openai_compatible").strip().lower()
        if provider not in PROVIDERS:
            raise SP1ModelError("MODEL_CONFIG_INVALID", f"SP1_LLM_PROVIDER must be one of {', '.join(PROVIDERS)}.",
                                retryable=False)
        try:
            timeout = float(env.get("SP1_LLM_TIMEOUT_SECONDS") or 120)
        except ValueError:
            timeout = -1
        if timeout <= 0:
            raise SP1ModelError("MODEL_CONFIG_INVALID", "SP1_LLM_TIMEOUT_SECONDS must be a positive number.",
                                retryable=False)
        return cls(provider=provider,
                   base_url=(env.get("SP1_LLM_BASE_URL") or DEFAULT_BASE_URLS[provider]).rstrip("/"),
                   model=(env.get("SP1_LLM_MODEL") or BATCH_MODEL_ID).strip(),
                   timeout_seconds=timeout, api_key=env.get("SP1_LLM_API_KEY") or None)

    def public(self) -> dict:
        """Configuration safe to show: no API key, no credentials or query in the URL."""
        parts = urlsplit(self.base_url)
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        return {"provider": self.provider, "base_url": urlunsplit((parts.scheme, host, parts.path, "", "")),
                "model": self.model, "timeout_seconds": self.timeout_seconds,
                "batch_model_id": BATCH_MODEL_ID, "is_batch_model": self.model == BATCH_MODEL_ID,
                "api_key_configured": bool(self.api_key)}


@dataclass(frozen=True)
class Completion:
    text: str
    served_model: str
    seconds: float


def prompt_kind(prompt: str) -> str:
    """classify or roles, from the template header (# prompt: sp1_<kind>_v2 ...)."""
    head = prompt.lstrip()[:40]
    for kind in MAX_TOKENS:
        if head.startswith(f"# prompt: sp1_{kind}_v2"):
            return kind
    raise SP1ModelError("PROMPT_UNKNOWN", "The prompt is not an SP1 v2 classify or roles prompt.", retryable=False)


class SP1ModelClient:
    """Synchronous client: complete(prompt) -> Completion. Tests inject an httpx.Client with a mock transport."""

    def __init__(self, config: SP1ModelConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client

    # -- public ---------------------------------------------------------------------------
    def complete(self, prompt: str) -> Completion:
        kind = prompt_kind(prompt)
        started = time.perf_counter()
        if self.config.provider == "ollama":
            body = {"model": self.config.model, "stream": False, "think": False,
                    "options": {"temperature": 0, "num_predict": MAX_TOKENS[kind]},
                    "messages": [{"role": "user", "content": prompt}]}
            payload = self._post("/api/chat", body)
            text = _get(payload, "message", "content")
        else:
            body = {"model": self.config.model, "temperature": 0, "max_tokens": MAX_TOKENS[kind],
                    "messages": [{"role": "user", "content": prompt}],
                    # Qwen chat template: no thinking block, as in the batch run (enable_thinking=False).
                    "chat_template_kwargs": {"enable_thinking": False}}
            payload = self._post("/v1/chat/completions", body)
            text = _get(payload, "choices", 0, "message", "content")
        served = payload.get("model") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not isinstance(served, str) or not served:
            raise SP1ModelError("MODEL_BAD_RESPONSE", "The model service returned an unreadable reply.")
        if not _same_model(self.config.model, served):
            raise SP1ModelError("MODEL_MISMATCH", f"Requested {self.config.model} but the service answered with "
                                                  f"{served}; set SP1_LLM_MODEL to the served model explicitly.",
                                retryable=False)
        return Completion(text=text, served_model=served, seconds=round(time.perf_counter() - started, 3))

    def health(self) -> dict:
        """Which models the service serves, and whether the configured one is among them."""
        result = {**self.config.public(), "available": False, "served_models": [], "code": None, "message": None}
        try:
            if self.config.provider == "ollama":
                payload = self._request("GET", "/api/tags")
                served = [str(m.get("name") or m.get("model")) for m in payload.get("models", []) if isinstance(m, dict)]
            else:
                payload = self._request("GET", "/v1/models")
                served = [str(m.get("id")) for m in payload.get("data", []) if isinstance(m, dict)]
        except SP1ModelError as exc:
            return {**result, "code": exc.code, "message": exc.message}
        except AttributeError:
            return {**result, "code": "MODEL_BAD_RESPONSE", "message": "The model list is not readable."}
        result["served_models"] = served[:20]
        if not any(_same_model(self.config.model, name) for name in served):
            return {**result, "code": "MODEL_NOT_FOUND",
                    "message": f"The service does not serve {self.config.model}."}
        return {**result, "available": True}

    # -- transport ------------------------------------------------------------------------
    def _headers(self) -> dict:
        if self.config.provider == "openai_compatible" and self.config.api_key:
            return {"Authorization": f"Bearer {self.config.api_key}"}
        return {}

    def _post(self, path: str, body: dict) -> Any:
        return self._request("POST", path, json=body)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        base = self.config.base_url
        if self.config.provider == "openai_compatible" and base.endswith("/v1") and path.startswith("/v1/"):
            path = path[3:]
        url = base + path
        try:
            if self._client is not None:
                response = self._client.request(method, url, headers=self._headers(),
                                                timeout=self.config.timeout_seconds, **kwargs)
            else:
                with httpx.Client(timeout=self.config.timeout_seconds) as client:
                    response = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.TimeoutException:
            raise SP1ModelError("MODEL_TIMEOUT", f"The model did not answer within {self.config.timeout_seconds:g} s.") from None
        except httpx.RequestError:
            raise SP1ModelError("MODEL_UNAVAILABLE", "The model service cannot be reached.") from None
        if response.status_code == 404:
            raise SP1ModelError("MODEL_NOT_FOUND", f"The service does not serve {self.config.model}.")
        if response.status_code in (401, 403):
            raise SP1ModelError("MODEL_AUTH_FAILED", "The model service rejected the credentials.", retryable=False)
        if response.status_code >= 500:
            raise SP1ModelError("MODEL_UPSTREAM_ERROR", f"The model service failed (HTTP {response.status_code}).")
        if response.status_code != 200:
            raise SP1ModelError("MODEL_REQUEST_REJECTED", f"The model service rejected the request (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise SP1ModelError("MODEL_BAD_RESPONSE", "The model service returned non-JSON.") from None


def _get(payload: Any, *path: Any) -> Any:
    for key in path:
        try:
            payload = payload[key]
        except (KeyError, IndexError, TypeError):
            return None
    return payload


def _same_model(requested: str, served: str) -> bool:
    """Exact ID, or Ollama's implicit :latest tag."""
    return served == requested or (":" not in requested and served == f"{requested}:latest")
