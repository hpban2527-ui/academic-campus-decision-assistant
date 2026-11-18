"""End-to-end checks of the operational data pipeline (SP1 -> SP2 -> SP3 -> API).

The acceptance behaviours of docs/ACTIVITY_DATA_ACCEPTANCE_V1.md, checked on the real
corpus and dataset, plus the update path for a new post (190) and an edited post. Nothing here writes
to the repository: builds go to tmp_path and the test-access log is redirected.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sp1 import operational as op  # noqa: E402
from sp1.acceptance import assess_activity, load_policy  # noqa: E402
from sp1.llm_cache import input_digest, prompts_for  # noqa: E402
from sp1.operational_corpus import load_operational_corpus  # noqa: E402
from sp1.preprocess import preprocess  # noqa: E402

REASON = "pytest: operational pipeline acceptance checks"
FINAL = ROOT / "data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl"
FIXTURE_190 = json.loads((ROOT / "tests/sp1/fixtures/live/post_190_seminar.json").read_text(encoding="utf-8"))


def _load_script(name):
    spec = importlib.util.spec_from_file_location(f"test_op_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


updater = _load_script("update_activity_data")


@pytest.fixture(scope="module")
def access_log(tmp_path_factory):
    return tmp_path_factory.mktemp("log") / "access.jsonl"


@pytest.fixture(scope="module")
def corpus(access_log):
    return load_operational_corpus(REASON, overlay_path=ROOT / "no-such-overlay.json", log_path=access_log)


@pytest.fixture(scope="module")
def dataset(corpus):
    return op.build_dataset(corpus)


@pytest.fixture(scope="module")
def by_position(dataset):
    return {r["position"]: r for r in dataset["records"]}


def ready(dataset):
    return [r for r in dataset["records"] if r["status"] in op.READY_STATUSES]


# ---------------------------------------------------------------- dataset as committed and as built

def test_committed_runtime_dataset_is_reproducible(dataset):
    committed = op.load_dataset()
    assert committed["dataset_version"] == dataset["dataset_version"]
    assert committed["summary"] == dataset["summary"]


def test_every_post_is_accounted_for_once_with_an_explicit_status(dataset, corpus):        # behaviour 10
    ids = [p["post_id"] for p in corpus]
    assert [r["post_id"] for r in dataset["records"]] == ids and len(ids) == 189
    assert all(r["status"] in op.STATUSES for r in dataset["records"])
    assert all(r["reasons"] for r in dataset["records"] if r["status"] not in op.READY_STATUSES | {"NOT_AN_ACTIVITY"})
    assert sum(dataset["summary"]["by_status"].values()) == 189
    assert dataset["summary"] == op.summarize(dataset["records"])
    assert op.validate_dataset(dataset, ids) == []


def test_test_posts_never_use_ai_annotations(dataset):
    test_records = [r for r in dataset["records"] if r["split"] == "test"]
    assert len(test_records) == 60
    assert {r["extraction"]["method"] for r in test_records} <= {"sp1_v2_model_replay", None}


# ---------------------------------------------------------------- 1. date without a clock time

def test_fixed_event_without_start_time_is_kept_with_a_reason_and_never_scheduled(dataset):
    from api import sp3_real
    blocked = [r for r in dataset["records"] if "missing_fixed_start_time" in r["reasons"]]
    assert blocked, "the corpus contains date-only events"
    catalog = sp3_real.real_catalog()
    usable = {row["activity"]["activity_id"] for row in catalog["activities"]}
    excluded = {e["post_id"]: e for e in catalog["excluded"]}
    plan = sp3_real.real_plan("first_plan", target_total=80)
    candidates = {c["activity"]["activity_id"] for c in plan["feasibility"]["candidates"]}
    for record in blocked:
        assert record["sp3_activity"] is None and record["sp3_schedule"] is None
        assert record["post_id"] not in usable and record["post_id"] not in candidates
        assert "missing_fixed_start_time" in [r["code"] for r in excluded[record["post_id"]]["reasons"]]


# ---------------------------------------------------------------- 2. quiz window vs live session

def _row(record, text):
    return {"record": record, "unsure": [], "source_text": text, "review": {}}


def _base_record(**values):
    record = {"post_type": "activity", "title": "Cuộc thi", "domain": None, "multi_session": False,
              "window_open": None, "window_close": None, "duration_minutes_stated": None,
              "registration_deadline": None, "mode": "online", "location": None, "audience_text": None,
              "audience_scope": {"cohorts": [], "programs": []}, "mandatory_stated": None,
              "recognition_stated": None, "points_stated": None, "fee": None, "registration_url": None,
              "join_url": None, "completion_requirements": [], "activity_type": "academic_competition"}
    record.update(values)
    return record


def test_quiz_window_is_flexible_and_a_live_webinar_is_not():
    policy = load_policy()
    quiz = assess_activity(_row(_base_record(window_open="2026-11-02", window_close="2026-11-08"),
                                "Cuộc thi trắc nghiệm trực tuyến từ 02/11 đến 08/11"), policy)
    assert quiz["schedule"]["type"] == "FLEXIBLE_WINDOW" and quiz["schedule"]["duration_minutes"] == 30
    assert quiz["schedule"]["bounds_precision"] == "date_only"
    webinar = assess_activity(_row(_base_record(window_open="2026-11-02", window_close="2026-11-08"),
                                   "Webinar qua Zoom, có phần trắc nghiệm cuối buổi"), policy)
    assert webinar["schedule"] is None and "missing_fixed_start_time" in webinar["reasons"]
    timed = assess_activity(_row(_base_record(window_open="2026-11-02T19:00+07:00"),
                                 "Webinar qua Zoom, có phần trắc nghiệm"), policy)
    assert timed["schedule"]["type"] == "FIXED" and timed["schedule"]["duration_source"] == "team_default"


def test_a_planned_quiz_gets_a_full_sitting_inside_its_window(dataset):
    from api import sp3_real
    flexible = {r["post_id"]: r for r in ready(dataset) if r["sp3_schedule"]["type"] == "FLEXIBLE_WINDOW"}
    assert flexible
    plan = sp3_real.real_plan("first_plan", target_total=100)["plan"]
    planned = [a for a in plan["selected_activities"] if a["activity_id"] in flexible]
    assert planned, "the demo plan uses at least one flexible quiz"
    for item in planned:
        record = flexible[item["activity_id"]]
        block = item["scheduled_blocks"][0]
        minutes = (op.datetime.fromisoformat(block["end"]) - op.datetime.fromisoformat(block["start"])).total_seconds() / 60
        assert minutes == record["sp3_schedule"]["duration_minutes"]
        assert record["sp3_activity"]["start"] <= block["start"] and block["end"] <= record["sp3_activity"]["end"]


def test_live_webinars_in_the_corpus_are_fixed(dataset, corpus):
    texts = {p["post_id"]: p["raw_content"] for p in corpus}
    webinars = [r for r in ready(dataset) if re.search(r"webinar|zoom", texts[r["post_id"]], re.I)
                and r["acceptance"]["accepted_record"]["mode"] == "online"]
    assert webinars and all(r["sp3_schedule"]["type"] == "FIXED" for r in webinars)


# ---------------------------------------------------------------- 3. unknown fee and domain

def test_unknown_fee_and_domain_stay_unknown_without_a_review_gate(dataset):
    unknown_fee = [r for r in ready(dataset) if r["acceptance"]["accepted_record"]["fee"] is None]
    unknown_domain = [r for r in ready(dataset) if r["sp3_activity"]["domain"] is None]
    assert unknown_fee and unknown_domain
    for record in unknown_fee:
        assert record["sp3_activity"]["fee"] is None            # never 0
        assert "fee_unknown" in record["warnings"] and record["status"] == "READY_WITH_WARNINGS"
    for record in unknown_domain:
        assert record["status"] in op.READY_STATUSES


# ---------------------------------------------------------------- 4. missing signup link and deadline

def test_missing_signup_link_does_not_discard_and_deadline_is_not_invented(dataset):
    no_link = [r for r in ready(dataset) if "registration_link_missing" in r["warnings"]]
    assert no_link and all(r["sp3_activity"]["source"]["URL_registration"] is None for r in no_link)
    for record in ready(dataset):
        stated = record["acceptance"]["accepted_record"]["registration_deadline"]
        if not stated:
            assert record["sp3_activity"]["registration_deadline"] is None
            assert record["sp3_activity"]["registration_deadline"] != record["sp3_activity"]["start"]


# ---------------------------------------------------------------- 5. unbound activities

def test_unbound_activity_does_not_count_toward_the_target(dataset):
    from api import sp3_real
    unbound = {r["post_id"] for r in ready(dataset) if r["binding"] is None}
    assert unbound
    result = sp3_real.real_plan("first_plan", target_total=100)
    for candidate in result["feasibility"]["candidates"]:
        if candidate["activity"]["activity_id"] in unbound:
            assert candidate["score_binding_ref"] is None
            assert "MISSING_SCORE_BINDING" in candidate["feasibility"]["reason_codes"]
    assert not {a["activity_id"] for a in result["plan"]["selected_activities"]} & unbound


# ---------------------------------------------------------------- 6. titles and publication labels

def test_publication_labels_are_not_titles_and_official_prefixes_survive(dataset):
    titles = [r["acceptance"]["accepted_record"]["title"] or "" for r in dataset["records"] if r["acceptance"]]
    assert not [t for t in titles if re.match(r"^\[\s*(HTTT|Hỗ trợ truyền thông)\s*[\]}]", t, re.I)]
    assert not [t for t in titles if t.strip().upper() in {"HTTT", "[HTTT]"}]
    assert any(t.startswith("[HTTN26]") for t in titles)


# ---------------------------------------------------------------- 7. post 190 and edited posts

def _fixture_replies(post):
    """Deterministic test double of the model for the synthetic post 190 (not a model output)."""
    classify = {"post_type": "activity", "post_type_evidence": "H1", "activity_type": "seminar_workshop",
                "domain": "academic", "mode": "offline", "mode_evidence": "L6", "domain_evidence": None}
    roles = {"title": "H1", "multi_session": False,
             "dates": {"D1": "first_start", "D2": "registration_deadline"},
             "times": {"T1": "first_start", "T2": "first_end", "T3": "registration_deadline"},
             "urls": {"U1": "registration"}}
    return {"classify": json.dumps(classify), "roles": json.dumps(roles)}


def _reply_row(post, model_id):
    return {"post_id": post["post_id"], "model_id": model_id, "prompt_versions": op.PROMPT_VERSIONS,
            "input_sha256": input_digest(prompts_for(post)), "replies": _fixture_replies(post)}


def _post_190(raw=None):
    post = {**FIXTURE_190["post"], "post_id": "unilife-test-post-190", "share_url": None}
    if raw is not None:
        post["raw_content"] = raw
    return post


def _run_update(tmp_path, overlay_posts, extra_rows=(), extra_args=()):
    overlay = tmp_path / "operational_updates.json"
    overlay.write_text(json.dumps({"schema": "unilife-operational-posts/1.0", "posts": overlay_posts},
                                  ensure_ascii=False), encoding="utf-8")
    llm = tmp_path / "operational.jsonl"
    llm.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in extra_rows), encoding="utf-8")
    out = tmp_path / "activity_dataset.json"
    code = updater.main(["--reason", REASON, "--overlay", str(overlay), "--llm", str(FINAL), "--llm", str(llm),
                         "--out", str(out), "--report", str(tmp_path / "report.md"),
                         "--pending-inputs", str(tmp_path / "pending.jsonl"),
                         "--access-log", str(tmp_path / "access.jsonl"), *extra_args])
    return code, out


def test_post_190_goes_through_the_real_update_path_to_the_api(tmp_path, monkeypatch):
    model_id = json.loads((ROOT / "data/config/merge_policy.json").read_text(encoding="utf-8"))["_model_id"]
    post = _post_190()
    code, out = _run_update(tmp_path, [post], [_reply_row(post, model_id)])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    record = data["records"][-1]
    assert record["post_id"] == post["post_id"] and record["position"] == 190 and record["split"] == "operational_new"
    assert record["extraction"]["method"] == "sp1_v2_model_replay"
    assert record["status"] in op.READY_STATUSES
    assert record["sp3_activity"]["start"] == "2026-11-05T14:00:00+07:00"
    assert record["sp3_activity"]["end"] == "2026-11-05T16:00:00+07:00"
    assert record["sp3_activity"]["registration_deadline"] == "2026-11-03T23:59:00+07:00"
    assert record["binding_decision"]["reason"] in {"sources_agree", "sources_disagree", "activity_type_not_auto_bound"}
    assert record["acceptance"]["evidence"]["window_open"]
    from api import sp3_real
    monkeypatch.setenv("UNILIFE_ACTIVITY_DATASET", str(out))
    catalog = sp3_real.real_catalog()
    assert catalog["dataset"]["dataset_version"] == data["dataset_version"]
    assert post["post_id"] in {row["activity"]["activity_id"] for row in catalog["activities"]}
    plan = sp3_real.real_plan("first_plan", target_total=80)
    assert plan["dataset"]["dataset_version"] == data["dataset_version"]
    assert post["post_id"] in {c["activity"]["activity_id"] for c in plan["feasibility"]["candidates"]}


def test_post_190_without_model_output_is_pending_not_invented(tmp_path):
    code, out = _run_update(tmp_path, [_post_190()])
    data = json.loads(out.read_text(encoding="utf-8"))
    record = data["records"][-1]
    assert code == 0 and record["status"] == "EXTRACTION_PENDING" and record["reasons"] == ["model_output_missing"]
    assert record["sp3_activity"] is None and record["acceptance"] is None
    pending = [json.loads(line) for line in (tmp_path / "pending.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["post_id"] for row in pending] == [record["post_id"]] or record["post_id"] in [r["post_id"] for r in pending]


def test_edited_post_cannot_reuse_the_old_candidate_role_mapping(tmp_path):
    model_id = json.loads((ROOT / "data/config/merge_policy.json").read_text(encoding="utf-8"))["_model_id"]
    original = _post_190()
    edited = _post_190(FIXTURE_190["edited_raw_content"])
    # Same post_id, same candidate IDs (D1, T1, ...), different dates: the old reply must not be replayed.
    code, out = _run_update(tmp_path, [edited], [_reply_row(original, model_id)])
    record = json.loads(out.read_text(encoding="utf-8"))["records"][-1]
    assert code == 0 and record["status"] == "EXTRACTION_PENDING" and record["reasons"] == ["model_output_stale"]
    assert record["sp3_activity"] is None


def test_edited_frozen_post_invalidates_annotation_and_human_decision(tmp_path, corpus):
    decisions = {line.split(",")[0] for line in (ROOT / "data/review/decisions.csv").read_text(encoding="utf-8-sig").splitlines()[1:]}
    target = next(p for p in corpus if p["post_id"] in decisions and p["split"] != "test")
    edited = {k: target[k] for k in ("post_id", "url", "publisher", "platform", "date_posted")}
    edited["raw_content"] = target["raw_content"] + "\nCập nhật: đổi sang ngày 30/11/2026."
    code, out = _run_update(tmp_path, [edited])
    record = next(r for r in json.loads(out.read_text(encoding="utf-8"))["records"] if r["post_id"] == target["post_id"])
    assert code == 0 and record["revision"]["text_changed"] is True
    assert "ai_annotation_stale" in record["extraction"]["notes"]
    assert record["status"] == "EXTRACTION_PENDING" and record["human_decision"] is None


def test_call_model_records_replies_with_their_input_digest(tmp_path, monkeypatch):
    model_id = json.loads((ROOT / "data/config/merge_policy.json").read_text(encoding="utf-8"))["_model_id"]
    post = _post_190()

    class FakeClient:                                   # stands in for a served Qwen backend
        def complete(self, prompt):
            from sp1.model_client import Completion, SP1ModelError, prompt_kind
            if "ỨNG DỤNG TRÍ TUỆ NHÂN TẠO" not in prompt:   # any other pending post: backend "unavailable"
                raise SP1ModelError("MODEL_UNAVAILABLE", "fake backend only knows post 190")
            return Completion(text=_fixture_replies(post)[prompt_kind(prompt)], served_model=model_id, seconds=0.0)

    monkeypatch.setattr(updater, "OPERATIONAL_LLM_DIR", tmp_path / "llm_operational")
    real_call = updater.call_model
    monkeypatch.setattr(updater, "call_model", lambda posts, pending, mid: real_call(posts, pending, mid, client=FakeClient()))
    monkeypatch.setattr(updater, "default_llm_files", lambda: [FINAL, *sorted((tmp_path / "llm_operational").glob("*.jsonl"))])
    overlay = tmp_path / "updates.json"
    overlay.write_text(json.dumps({"schema": "unilife-operational-posts/1.0", "posts": [post]}), encoding="utf-8")
    out = tmp_path / "ds.json"
    code = updater.main(["--reason", REASON, "--overlay", str(overlay), "--call-model", "--out", str(out),
                         "--report", str(tmp_path / "r.md"), "--pending-inputs", str(tmp_path / "p.jsonl"),
                         "--access-log", str(tmp_path / "a.jsonl")])
    record = json.loads(out.read_text(encoding="utf-8"))["records"][-1]
    assert code == 0 and record["status"] in op.READY_STATUSES
    rows = [json.loads(line) for line in (tmp_path / "llm_operational" / (model_id.replace("/", "__") + ".jsonl"))
            .read_text(encoding="utf-8").splitlines()]
    assert [r["post_id"] for r in rows] == [post["post_id"]]
    assert rows[0]["input_sha256"] == input_digest(prompts_for(post))


# ---------------------------------------------------------------- 8. idempotence, duplicates, atomic publish

def test_rebuild_is_idempotent(corpus, dataset):
    assert op.build_dataset(corpus)["dataset_version"] == dataset["dataset_version"]


def test_a_repost_is_a_duplicate_with_an_alias_and_no_double_credit(tmp_path, dataset, corpus):
    model_id = json.loads((ROOT / "data/config/merge_policy.json").read_text(encoding="utf-8"))["_model_id"]
    rows = {json.loads(line)["post_id"]: json.loads(line) for line in FINAL.read_text(encoding="utf-8").splitlines()}
    original = next(r for r in ready(dataset) if r["split"] == "test" and r["binding"] is not None)
    source = next(p for p in corpus if p["post_id"] == original["post_id"])
    repost = {k: source[k] for k in ("url", "publisher", "platform", "date_posted", "raw_content")}
    repost.update(post_id="unilife-test-repost", url=source["url"] + "&repost=1")
    reply = {**rows[original["post_id"]], "post_id": repost["post_id"]}
    code, out = _run_update(tmp_path, [repost], [reply])
    data = json.loads(out.read_text(encoding="utf-8"))
    by_id = {r["post_id"]: r for r in data["records"]}
    assert code == 0 and by_id[repost["post_id"]]["status"] == "DUPLICATE"
    assert by_id[repost["post_id"]]["duplicate_of"] == original["post_id"]
    assert repost["post_id"] in [a["post_id"] for a in by_id[original["post_id"]]["aliases"]]
    assert data["summary"]["schedulable_canonical"] == dataset["summary"]["schedulable_canonical"]
    assert data["summary"]["with_supported_score_binding"] == dataset["summary"]["with_supported_score_binding"]


def test_an_invalid_build_is_not_published(tmp_path, dataset):
    target = tmp_path / "activity_dataset.json"
    op.publish(dataset, target)
    before = target.read_bytes()
    broken = deepcopy(dataset)
    first_ready = next(r for r in broken["records"] if r["status"] in op.READY_STATUSES)
    first_ready["sp3_activity"]["fee"] = -1
    with pytest.raises(op.DatasetInvalid):
        op.publish(broken, target)
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".*staging*"))


# ---------------------------------------------------------------- 9. provenance and labels

def test_labels_never_claim_human_review_gold_or_official_credit(dataset):
    for record in dataset["records"]:
        label = record["extraction"]["label"]
        assert label is None or "NOT_GOLD" in label or "NOT_BLIND_GOLD" in label
        assert record["dimensions"]["official_award_verified"] is False
        human = record["human_decision"]
        assert record["dimensions"]["human_reviewed"] == bool(human and not human["stale"])
    assert dataset["inputs"]["source_json_sha256"] == op.sha256_file(ROOT / "data/raw/source.json")


def test_evidence_of_effective_values_is_grounded_in_the_source(dataset, corpus):
    texts = {p["post_id"]: preprocess(p["raw_content"]).text for p in corpus}
    checked = 0
    for record in ready(dataset):
        human_fields = set((record["human_decision"] or {}).get("fields_set") or [])
        ungrounded = {n.split(":", 1)[1] for n in record["extraction"]["notes"] if n.startswith("evidence_not_grounded:")}
        for field, spans in record["acceptance"]["evidence"].items():
            if field in human_fields or field in ungrounded:
                assert field in human_fields or record["acceptance"]["accepted_record"].get(field) in (None, [])
                continue
            if record["acceptance"]["accepted_record"].get(field) in (None, [], False):
                continue
            for span in spans:
                if "removed]" in span["text"]:
                    continue                        # contact detail masked in the stored copy
                assert texts[record["post_id"]][span["start"]:span["end"]] == span["text"], (record["position"], field)
                checked += 1
    assert checked > 500


def test_api_catalog_and_plan_read_the_same_dataset_version(dataset):
    from api import sp3_real
    catalog = sp3_real.real_catalog()
    plan = sp3_real.real_plan("first_plan", target_total=80)
    assert catalog["dataset"]["dataset_version"] == plan["dataset"]["dataset_version"] == op.load_dataset()["dataset_version"]
    assert catalog["activity_count"] + len(catalog["excluded"]) == dataset["summary"]["posts"]
    assert plan["clock"]["label"] == "historical_demo_clock"
