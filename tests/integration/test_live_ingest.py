"""Developer CLI for single-post ingestion (sp1.live_ingest) with a FAKE model provider.

This is a developer tool, not part of the app: the API has no /api/sp1/posts router and no real_live source
(see tests/integration/test_no_runtime_ingestion.py). The model here is a controlled fake: it proves the
workflow and failure handling, NOT Qwen's accuracy.
"""
import json
import sqlite3
import threading
from pathlib import Path

import httpx
import pytest

from sp1.live_ingest import DEMO_PROFILE, DEMO_TERM, IngestError, LiveIngestService, LiveStore
from sp1.model_client import (BATCH_MODEL_ID, Completion, SP1ModelClient, SP1ModelConfig, SP1ModelError,
                              prompt_kind)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/sp1/fixtures/live/post_190_seminar.json").read_text(encoding="utf-8"))
POST = FIXTURE["post"]
CLASSIFY = {"post_type": "activity", "post_type_evidence": "H1", "activity_type": "seminar_workshop",
            "domain": "academic", "mode": "offline", "mode_evidence": "L5"}
ROLES = {"title": "H1", "multi_session": False,
         "dates": {"D1": "first_start", "D2": "registration_deadline"},
         "times": {"T1": "first_start", "T2": "first_end", "T3": "registration_deadline"},
         "urls": {"U1": "registration"}}


class FakeModel:
    """complete(prompt) like SP1ModelClient; scripted failures; records every prompt it answers."""

    def __init__(self, served=BATCH_MODEL_ID, failures=(), roles=None):
        self.served, self.failures, self.roles = served, list(failures), roles or ROLES
        self.prompts, self.lock = [], threading.Lock()
        self.config = SP1ModelConfig(provider="openai_compatible", base_url="http://fake.invalid:1", model=served)

    def complete(self, prompt):
        with self.lock:
            self.prompts.append(prompt)
            failure = self.failures.pop(0) if self.failures else None
        if failure == "timeout":
            raise SP1ModelError("MODEL_TIMEOUT", "The model did not answer within 1 s.")
        if failure == "garbage":
            return Completion("sorry, I cannot do that", self.served, 0.0)
        reply = CLASSIFY if prompt_kind(prompt) == "classify" else self.roles
        return Completion(json.dumps(reply), self.served, 0.01)

    @property
    def calls(self):
        return len(self.prompts)


@pytest.fixture
def env(tmp_path):
    model = FakeModel()
    return LiveIngestService(LiveStore(tmp_path / "live.db"), lambda: model), model


def submit(service, raw_content=POST["raw_content"], process=True):
    return service.submit(raw_content, url=POST["url"], publisher=POST.get("publisher"),
                          platform=POST.get("platform"), date_posted=POST.get("date_posted"), post_id="post-190",
                          process=process)


def refused(call, *args):
    with pytest.raises(IngestError) as caught:
        call(*args)
    return caught.value


def published_start(service):
    return service.store.published("post-190")[0]["activity"]["start"]


def test_post_190_saved_processed_and_valid_sp1_record(env):
    service, model = env
    body = submit(service)
    revision = body["revisions"][0]
    assert body["ui_state"] == "awaiting_review" and revision["raw_content"] == POST["raw_content"]
    record = revision["extraction"]["record"]["activity"]
    assert record["source"]["post_id"] == "post-190" and record["post_type"] == "activity"
    assert record["window"] == {"open": "2026-11-05T14:00:00+07:00", "close": "2026-11-05T16:00:00+07:00"}
    assert record["mode"] == "offline" and record["meta"]["status"] == "valid"
    extraction = revision["extraction"]
    assert extraction["extraction_method"] == "llm_hybrid_v2"
    assert extraction["prompt_versions"] == {"classify": "sp1_classify_v2 1.0.0", "roles": "sp1_roles_v2 1.0.0"}
    assert extraction["model"]["served_model_ids"] == [BATCH_MODEL_ID] and extraction["model"]["successful_calls"] == 2
    assert model.calls == 2
    assert [prompt_kind(p) for p in model.prompts] == ["classify", "roles"]


def test_draft_is_not_published_until_an_explicit_publish(env):
    service, _ = env
    submit(service)
    assert service.store.published() == []
    published = service.publish("post-190", 1, "admin")
    assert published["ui_state"] == "published" and published["published_revision"] == 1
    activity = service.store.published("post-190")[0]["activity"]
    assert (activity["start"], activity["end"], activity["mode"]) == (
        "2026-11-05T14:00:00+07:00", "2026-11-05T16:00:00+07:00", "offline")
    binding = service.store.published("post-190")[0]["binding"]
    assert binding["binding_ref"] == "auto-R19-post-190"
    assert (binding["rule_id"], binding["field"], binding["operation"]) == ("R19", "eligible_academic_seminars", "INCREMENT")


def test_model_failure_keeps_the_post_and_retry_fixes_the_same_revision(tmp_path):
    model = FakeModel(failures=["timeout"])
    service = LiveIngestService(LiveStore(tmp_path / "live.db"), lambda: model)
    first = submit(service)
    assert first["ui_state"] == "retryable_failure"
    revision = first["revisions"][0]
    assert revision["raw_content"] == POST["raw_content"] and revision["extraction"] is None
    assert revision["error"]["code"] == "MODEL_TIMEOUT" and revision["error"]["retryable"] is True
    assert refused(service.publish, "post-190", 1, "a").http_status == 409
    retried = service.retry("post-190", 1)
    assert retried["ui_state"] == "awaiting_review" and len(retried["revisions"]) == 1
    assert retried["revisions"][0]["attempts"] == 2 and retried["revisions"][0]["error"] is None
    assert len(service.list()) == 1
    # Resubmitting the failed text again must not create a second revision either.
    assert len(submit(service)["revisions"]) == 1


def test_invalid_model_output_is_a_retryable_failure_not_a_fake_success(tmp_path):
    model = FakeModel(failures=["garbage"] * 2)   # classify fails twice: decide() makes two attempts
    service = LiveIngestService(LiveStore(tmp_path / "live.db"), lambda: model)
    body = service.submit(POST["raw_content"], url=POST["url"], date_posted=POST["date_posted"], post_id="post-190")
    assert body["ui_state"] == "retryable_failure"
    assert body["revisions"][0]["error"]["code"] == "INVALID_MODEL_OUTPUT"
    assert body["revisions"][0]["extraction"] is None


def test_rules_only_fallback_is_explicit_and_labelled(tmp_path):
    model = FakeModel(failures=["timeout"])
    service = LiveIngestService(LiveStore(tmp_path / "live.db"), lambda: model, allow_rules_fallback=True)
    body = service.submit(POST["raw_content"], url=POST["url"], date_posted=POST["date_posted"], post_id="post-190")
    extraction = body["revisions"][0]["extraction"]
    assert extraction["extraction_method"] == "rules_only_fallback"
    assert extraction["model"] is None and extraction["prompt_versions"] is None
    assert extraction["model_failure"]["code"] == "MODEL_TIMEOUT"
    assert "rules_only_fallback_no_model_verification" in extraction["review_flags"]


def test_unreadable_model_config_is_reported_per_revision(tmp_path):
    def broken():
        raise SP1ModelError("MODEL_CONFIG_INVALID", "SP1_LLM_TIMEOUT_SECONDS must be a positive number.", False)

    service = LiveIngestService(LiveStore(tmp_path / "live.db"), broken)
    body = service.submit(POST["raw_content"], url=POST["url"], post_id="post-190")
    assert body["revisions"][0]["error"] == {"code": "MODEL_CONFIG_INVALID", "retryable": False,
                                             "message": "SP1_LLM_TIMEOUT_SECONDS must be a positive number."}


def test_unchanged_resubmission_reuses_result_and_edit_calls_model_once_per_revision(env):
    service, model = env
    submit(service)
    submit(service)
    assert model.calls == 2 and len(service.get("post-190")["revisions"]) == 1
    service.publish("post-190", 1, "admin")
    service.publish("post-190", 1, "admin")                  # repeated publish
    assert len(service.store.published()) == 1

    edited = submit(service, FIXTURE["edited_raw_content"])
    assert model.calls == 4                                   # only the new revision called the model
    assert [r["revision"] for r in edited["revisions"]] == [1, 2]
    assert edited["ui_state"] == "awaiting_review" and edited["has_unpublished_edit"] is True
    assert edited["published_revision"] == 1

    # Revision 1 stays published until revision 2 publishes.
    assert published_start(service) == "2026-11-05T14:00:00+07:00"
    service.publish("post-190", 2, "admin")
    assert published_start(service) == "2026-11-06T08:00:00+07:00"
    final = service.get("post-190")
    assert [r["status"] for r in final["revisions"]] == ["SUPERSEDED", "PUBLISHED"]
    assert len(service.store.published()) == 1


def test_old_revision_cannot_be_published_after_a_newer_one_exists(env):
    service, _ = env
    submit(service, process=False)
    submit(service, FIXTURE["edited_raw_content"], process=False)
    assert refused(service.retry, "post-190", 1).http_status == 409    # superseded
    service.retry("post-190", 2)
    assert refused(service.publish, "post-190", 1, "a").http_status == 409


def test_slow_old_request_finishing_late_is_bound_to_its_own_revision(tmp_path):
    release = threading.Event()
    started = threading.Event()

    class SlowFirst(FakeModel):
        def complete(self, prompt):
            if not started.is_set() and "2026" in prompt:      # first call ever = revision 1's classify
                started.set()
                release.wait(5)
            return super().complete(prompt)

    model = SlowFirst()
    service = LiveIngestService(LiveStore(tmp_path / "live.db"), lambda: model)
    kwargs = dict(url=POST["url"], publisher=POST["publisher"], date_posted=POST["date_posted"], post_id="post-190")
    worker = threading.Thread(target=lambda: service.submit(POST["raw_content"], **kwargs))
    worker.start()
    assert started.wait(5)
    service.submit(FIXTURE["edited_raw_content"], **kwargs)       # revision 2 finishes first
    release.set()
    worker.join(10)
    revisions = {r["revision"]: r for r in service.get("post-190")["revisions"]}
    assert revisions[2]["status"] == "AWAITING_REVIEW"
    assert revisions[1]["status"] == "SUPERSEDED"                 # late result stays on revision 1
    assert "14:00" in revisions[1]["extraction"]["record"]["activity"]["window"]["open"]
    assert "08:00" in revisions[2]["extraction"]["record"]["activity"]["window"]["open"]
    with pytest.raises(Exception):
        service.publish("post-190", 1, "admin")
    assert service.publish("post-190", 2, "admin")["published_revision"] == 2


def test_failed_publication_keeps_the_previous_published_state(env, monkeypatch):
    service, _ = env
    submit(service)
    service.publish("post-190", 1, "admin")
    submit(service, FIXTURE["edited_raw_content"])

    def boom(*args, **kwargs):
        raise RuntimeError("binding failed")

    monkeypatch.setattr(service, "_build_publication", boom)
    with pytest.raises(RuntimeError):
        service.publish("post-190", 2, "admin")
    state = service.get("post-190")
    assert state["published_revision"] == 1 and state["ui_state"] == "awaiting_review"
    assert published_start(service) == "2026-11-05T14:00:00+07:00"


def test_publication_artifacts_refer_to_one_revision(env):
    service, _ = env
    submit(service)
    service.publish("post-190", 1, "admin")
    record = service.store.published("post-190")[0]
    revision = service.store.revision("post-190", 1)
    assert record["revision"] == record["sidecar"]["live_revision"] == 1
    assert record["text_sha256"] == revision["text_sha256"]
    assert record["activity"]["activity_id"] == record["binding"]["activity_id"] == "post-190"
    assert record["features"]["campus_id"] == "NVC" and record["features"]["topics"]
    assert record["binding_explanation"]["label"] == "auto_proposed_not_human_reviewed"


def test_not_plannable_draft_cannot_be_published(tmp_path):
    model = FakeModel(roles={**ROLES, "dates": {"D1": "other", "D2": "other"}, "times": {"T1": "other", "T2": "other", "T3": "other"}})
    service = LiveIngestService(LiveStore(tmp_path / "live.db"), lambda: model)
    text = "Thông báo chung về hoạt động sắp tới của Khoa, sinh viên theo dõi thêm thông tin tại website."
    service.submit(text, url="https://example.invalid/x", post_id="post-191")
    body = service.get("post-191")
    assert body["ui_state"] == "awaiting_review"
    with pytest.raises(Exception) as caught:
        service.publish("post-191", 1, "admin")
    assert getattr(caught.value, "code", None) == "PUBLISH_BLOCKED"
    assert service.store.published() == []


def test_live_store_is_separate_from_the_frozen_dataset(env):
    service, _ = env
    submit(service)
    assert service.store.path.name == "live.db" and "gold" not in str(service.store.path)
    with sqlite3.connect(service.store.path) as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {"posts", "revisions", "published"} <= tables


@pytest.mark.parametrize("payload,code", [
    ({"raw_content": "  "}, "EMPTY_TEXT"),
    ({"raw_content": "x", "url": "ftp://a"}, "BAD_URL"),
    ({"raw_content": "x", "post_id": "bad id!"}, "BAD_POST_ID"),
    ({"raw_content": "x", "date_posted": "yesterday"}, "BAD_DATE"),
])
def test_invalid_submissions_are_rejected(env, payload, code):
    service, _ = env
    fields = dict(payload)
    text = fields.pop("raw_content")
    error = refused(lambda: service.submit(text, **fields))
    assert error.http_status == 422 and error.code == code


def test_unknown_post_is_404(env):
    assert refused(env[0].get, "nope").http_status == 404


def test_demo_profile_matches_the_handover_sidecar():
    sidecar = json.loads((ROOT / "data/handover/sidecar.json").read_text(encoding="utf-8"))
    assert (sidecar["demo_profile"], sidecar["demo_term"]) == (DEMO_PROFILE, DEMO_TERM)


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
