"""SP1 model client: request shape, served-model check, stable error codes, health and configuration.

The HTTP layer is mocked with httpx.MockTransport; nothing here calls a real model.
"""
import json

import httpx
import pytest

from sp1.model_client import BATCH_MODEL_ID, SP1ModelClient, SP1ModelConfig, SP1ModelError, prompt_kind


# Model client (HTTP level, mocked transport) ----------------------------------------------------------

def client_for(handler, **config):
    cfg = SP1ModelConfig(base_url="http://model.invalid:8001", **config)
    return SP1ModelClient(cfg, httpx.Client(transport=httpx.MockTransport(handler)))


CLASSIFY_PROMPT = "# prompt: sp1_classify_v2 1.0.0\nbody"


def test_model_client_sends_the_batch_request_and_reports_the_served_model():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content), url=str(request.url), auth=request.headers.get("authorization"))
        return httpx.Response(200, json={"model": BATCH_MODEL_ID, "choices": [{"message": {"content": "{}"}}]})

    completion = client_for(handler, api_key="secret-token").complete(CLASSIFY_PROMPT)
    assert completion.served_model == BATCH_MODEL_ID and completion.text == "{}"
    assert seen["url"].endswith("/v1/chat/completions") and seen["model"] == BATCH_MODEL_ID
    assert seen["temperature"] == 0 and seen["max_tokens"] == 256
    assert seen["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["auth"] == "Bearer secret-token"


def test_model_client_roles_budget_and_ollama_shape():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"model": "qwen3.5:4b", "message": {"content": "{}"}})

    client = client_for(handler, provider="ollama", model="qwen3.5:4b")
    client.complete("# prompt: sp1_roles_v2 1.0.0\nbody")
    assert seen["options"] == {"temperature": 0, "num_predict": 768} and seen["think"] is False


@pytest.mark.parametrize("handler,code", [
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("t")), "MODEL_TIMEOUT"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("c")), "MODEL_UNAVAILABLE"),
    (lambda r: httpx.Response(500), "MODEL_UPSTREAM_ERROR"),
    (lambda r: httpx.Response(404), "MODEL_NOT_FOUND"),
    (lambda r: httpx.Response(401), "MODEL_AUTH_FAILED"),
    (lambda r: httpx.Response(200, text="not json"), "MODEL_BAD_RESPONSE"),
    (lambda r: httpx.Response(200, json={"model": "other/model", "choices": [{"message": {"content": "{}"}}]}), "MODEL_MISMATCH"),
    (lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}), "MODEL_BAD_RESPONSE"),
])
def test_model_client_failures_have_stable_codes(handler, code):
    with pytest.raises(SP1ModelError) as caught:
        client_for(handler).complete(CLASSIFY_PROMPT)
    assert caught.value.code == code and "secret" not in caught.value.message


def test_model_health_lists_served_models_and_never_leaks_the_key():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "Qwen/Qwen3.5-4B"}, {"id": "other"}]})

    health = client_for(handler, api_key="secret-token").health()
    assert health["available"] is True and health["is_batch_model"] is True
    assert "secret-token" not in json.dumps(health) and health["api_key_configured"] is True
    missing = client_for(handler, model="Qwen/Qwen3-8B").health()
    assert missing["available"] is False and missing["code"] == "MODEL_NOT_FOUND"
    down = client_for(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))).health()
    assert down["code"] == "MODEL_UNAVAILABLE"


def test_model_config_from_env_and_validation():
    config = SP1ModelConfig.from_env({"SP1_LLM_BASE_URL": "http://user:pw@host:9/v1/?k=1", "SP1_LLM_TIMEOUT_SECONDS": "7"})
    assert config.model == BATCH_MODEL_ID and config.timeout_seconds == 7
    assert "pw" not in json.dumps(config.public()) and "k=1" not in json.dumps(config.public())
    for env in ({"SP1_LLM_TIMEOUT_SECONDS": "0"}, {"SP1_LLM_TIMEOUT_SECONDS": "x"}, {"SP1_LLM_PROVIDER": "nope"}):
        with pytest.raises(SP1ModelError):
            SP1ModelConfig.from_env(env)


def test_prompt_kind_rejects_other_prompts():
    with pytest.raises(SP1ModelError):
        prompt_kind("hello")
