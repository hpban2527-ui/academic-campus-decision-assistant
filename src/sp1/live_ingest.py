"""Incremental ingestion of single free-form announcements (post 190 onwards).

Flow: submit (text saved first) -> process (SP1 v2 classify + roles prompts through a served model, hybrid
merge, normalise) -> admin inspects the draft -> publish (explicit) -> the published activity, its SP2
binding, personalization features and planner evidence become visible to the planner.

State is kept in a separate SQLite file (default data/live/live_store.db, env UNILIFE_LIVE_DB), outside
the frozen 189-post dataset and its splits. Every result is bound to the (post_id, revision) it processed.
A published revision stays in place until a newer revision publishes successfully, in one transaction.

Revision status: SAVED -> PROCESSING -> AWAITING_REVIEW | FAILED_RETRYABLE -> PUBLISHED -> SUPERSEDED.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .handover import auto_evidence, project
from .features import features as derive_features
from .llm_v2 import PROMPT_VERSIONS, decide
from .model_client import SP1ModelError
from .normalize import load_config
from .pipeline_v2 import process_post, redact
from .review import text_fingerprint

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "live" / "live_store.db"
# Same synthetic student and term as scripts/build_handover.py (tests compare with the handover sidecar).
DEMO_PROFILE = {"cohort": "K24", "program": "standard"}
DEMO_TERM = "HK1_2026_2027"
MAX_TEXT = 20000
STALE_PROCESSING_SECONDS = 600
POST_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
UI_STATES = {"SAVED": "saved_draft", "PROCESSING": "processing", "AWAITING_REVIEW": "awaiting_review",
             "FAILED_RETRYABLE": "retryable_failure", "PUBLISHED": "published", "SUPERSEDED": "superseded"}
EXTRACTION_LLM = "llm_hybrid_v2"
EXTRACTION_RULES_FALLBACK = "rules_only_fallback"


class IngestError(Exception):
    """A request the service refuses; http_status is the suggested API status."""

    def __init__(self, code: str, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def revision_key(raw: str, meta: dict) -> str:
    return hashlib.sha256(_json({"text": raw.replace("\r\n", "\n"), **meta}).encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (post_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS revisions (
  post_id TEXT NOT NULL, revision INTEGER NOT NULL, revision_key TEXT NOT NULL, text_sha256 TEXT NOT NULL,
  raw_content TEXT NOT NULL, url TEXT NOT NULL, url_is_placeholder INTEGER NOT NULL, publisher TEXT,
  platform TEXT, date_posted TEXT, status TEXT NOT NULL, saved_at TEXT NOT NULL, processing_started_at TEXT,
  processed_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, extraction TEXT, error TEXT,
  PRIMARY KEY (post_id, revision));
CREATE TABLE IF NOT EXISTS published (
  post_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL, published_at TEXT NOT NULL,
  reviewer TEXT NOT NULL);
"""


class LiveStore:
    """SQLite persistence; one short connection per operation, one lock per process."""

    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _revision(row: sqlite3.Row) -> dict:
        data = dict(row)
        for key in ("extraction", "error"):
            data[key] = json.loads(data[key]) if data[key] else None
        data["url_is_placeholder"] = bool(data["url_is_placeholder"])
        return data

    def revisions(self, post_id: str) -> list[dict]:
        with self.lock, closing(self.connect()) as conn:
            rows = conn.execute("SELECT * FROM revisions WHERE post_id=? ORDER BY revision", (post_id,)).fetchall()
        return [self._revision(r) for r in rows]

    def revision(self, post_id: str, revision: int) -> dict | None:
        with self.lock, closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM revisions WHERE post_id=? AND revision=?", (post_id, revision)).fetchone()
        return self._revision(row) if row else None

    def post_ids(self) -> list[str]:
        with self.lock, closing(self.connect()) as conn:
            return [r[0] for r in conn.execute("SELECT post_id FROM posts ORDER BY created_at, post_id")]

    def save(self, post_id: str, raw: str, meta: dict, key: str) -> tuple[dict, bool]:
        """Save a revision. Returns (row, created); an unchanged latest revision is returned as it is."""
        with self.lock, closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("INSERT OR IGNORE INTO posts VALUES (?, ?)", (post_id, _now()))
                latest = conn.execute("SELECT * FROM revisions WHERE post_id=? ORDER BY revision DESC LIMIT 1",
                                      (post_id,)).fetchone()
                if latest and latest["revision_key"] == key:
                    conn.execute("COMMIT")
                    return self._revision(latest), False
                number = (latest["revision"] if latest else 0) + 1
                conn.execute(
                    "INSERT INTO revisions (post_id, revision, revision_key, text_sha256, raw_content, url, "
                    "url_is_placeholder, publisher, platform, date_posted, status, saved_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (post_id, number, key, text_fingerprint(raw), raw, meta["url"], int(meta["url_is_placeholder"]),
                     meta["publisher"], meta["platform"], meta["date_posted"], "SAVED", _now()))
                # An older draft can no longer be published once a newer revision exists.
                conn.execute("UPDATE revisions SET status='SUPERSEDED' WHERE post_id=? AND revision<? "
                             "AND status IN ('SAVED','AWAITING_REVIEW','FAILED_RETRYABLE')", (post_id, number))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.revision(post_id, number), True

    def claim(self, post_id: str, revision: int) -> bool:
        """Atomically move SAVED / FAILED_RETRYABLE (or a long-stuck PROCESSING) to PROCESSING."""
        cutoff = datetime.fromtimestamp(time.time() - STALE_PROCESSING_SECONDS, timezone.utc).isoformat(timespec="seconds")
        with self.lock, closing(self.connect()) as conn:
            cursor = conn.execute(
                "UPDATE revisions SET status='PROCESSING', processing_started_at=?, attempts=attempts+1 "
                "WHERE post_id=? AND revision=? AND (status IN ('SAVED','FAILED_RETRYABLE') "
                "OR (status='PROCESSING' AND processing_started_at<?))", (_now(), post_id, revision, cutoff))
            return cursor.rowcount == 1

    def finish(self, post_id: str, revision: int, extraction: dict | None, error: dict | None) -> None:
        """Write a result to its own revision only; a revision replaced meanwhile becomes SUPERSEDED."""
        with self.lock, closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            newer = conn.execute("SELECT 1 FROM revisions WHERE post_id=? AND revision>?", (post_id, revision)).fetchone()
            status = "SUPERSEDED" if newer else ("AWAITING_REVIEW" if error is None else "FAILED_RETRYABLE")
            conn.execute("UPDATE revisions SET status=?, extraction=?, error=?, processed_at=? "
                         "WHERE post_id=? AND revision=? AND status='PROCESSING'",
                         (status, _json(extraction) if extraction else None, _json(error) if error else None,
                          _now(), post_id, revision))
            conn.execute("COMMIT")

    def published(self, post_id: str | None = None) -> list[dict]:
        with self.lock, closing(self.connect()) as conn:
            rows = (conn.execute("SELECT * FROM published WHERE post_id=?", (post_id,)).fetchall() if post_id
                    else conn.execute("SELECT * FROM published ORDER BY published_at, post_id").fetchall())
        return [{**json.loads(r["payload"]), "published_at": r["published_at"], "reviewer": r["reviewer"]} for r in rows]

    def commit_publication(self, post_id: str, revision: int, payload: dict, reviewer: str) -> None:
        """Replace the published revision and update statuses in one transaction."""
        with self.lock, closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = conn.execute("SELECT status FROM revisions WHERE post_id=? AND revision=?",
                                       (post_id, revision)).fetchone()
                latest = conn.execute("SELECT MAX(revision) FROM revisions WHERE post_id=?", (post_id,)).fetchone()[0]
                if not current or current["status"] != "AWAITING_REVIEW" or latest != revision:
                    raise IngestError("STALE_REVISION", "This revision is no longer the reviewed latest revision.", 409)
                conn.execute("UPDATE revisions SET status='SUPERSEDED' WHERE post_id=? AND status='PUBLISHED'", (post_id,))
                conn.execute("UPDATE revisions SET status='PUBLISHED' WHERE post_id=? AND revision=?", (post_id, revision))
                conn.execute("INSERT OR REPLACE INTO published VALUES (?,?,?,?,?)",
                             (post_id, revision, _json(payload), _now(), reviewer))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise


class _Calls:
    """Wraps the model so decide() sees a plain client(prompt) -> str and failures are recorded."""

    def __init__(self, model) -> None:
        self.model, self.errors, self.served, self.calls, self.seconds = model, [], set(), 0, 0.0

    def __call__(self, prompt: str) -> str:
        try:
            completion = self.model.complete(prompt)
        except SP1ModelError as exc:
            self.errors.append(exc)
            raise
        self.calls += 1
        self.served.add(completion.served_model)
        self.seconds += completion.seconds
        return completion.text


class LiveIngestService:
    def __init__(self, store: LiveStore, model_factory: Callable[[], Any], policy: dict | None = None, config=None,
                 rules_config: dict | None = None, allow_rules_fallback: bool = False) -> None:
        self.store = store
        self.model_factory = model_factory
        self.policy = policy if policy is not None else json.loads(
            (ROOT / "data/config/merge_policy.json").read_text(encoding="utf-8"))
        self.config = config or load_config()
        self.rules_config = rules_config if rules_config is not None else json.loads(
            (ROOT / "data/drl_rules.json").read_text(encoding="utf-8"))
        self.allow_rules_fallback = allow_rules_fallback

    # -- submit / process ---------------------------------------------------------------
    def submit(self, raw_content: Any, *, url: str | None = None, publisher: str | None = None,
               platform: str | None = None, date_posted: str | None = None, post_id: str | None = None,
               process: bool = True) -> dict:
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise IngestError("EMPTY_TEXT", "raw_content must be a non-empty string.")
        if len(raw_content) > MAX_TEXT:
            raise IngestError("TEXT_TOO_LONG", f"raw_content is limited to {MAX_TEXT} characters.")
        if url is not None and (urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc):
            raise IngestError("BAD_URL", "url must be an absolute http(s) URL.")
        if date_posted is not None and not re.match(r"^\d{4}-\d{2}-\d{2}", str(date_posted)):
            raise IngestError("BAD_DATE", "date_posted must start with YYYY-MM-DD.")
        if post_id is not None and not POST_ID.match(post_id):
            raise IngestError("BAD_POST_ID", "post_id may contain letters, digits, '.', '_' and '-' (max 80).")
        if post_id is None:
            seed = url or text_fingerprint(raw_content)
            post_id = "live-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
        meta = {"url": url or f"https://unilife.invalid/live/{post_id}", "url_is_placeholder": url is None,
                "publisher": publisher, "platform": platform or "manual", "date_posted": date_posted}
        key = revision_key(raw_content, {k: meta[k] for k in ("url", "publisher", "platform", "date_posted")})
        row, _ = self.store.save(post_id, raw_content, meta, key)
        if process and row["status"] in ("SAVED", "FAILED_RETRYABLE"):
            self.process(post_id, row["revision"])
        return self.get(post_id)

    def retry(self, post_id: str, revision: int) -> dict:
        row = self._require(post_id, revision)
        if row["status"] not in ("SAVED", "FAILED_RETRYABLE", "PROCESSING"):
            raise IngestError("NOT_RETRYABLE", f"Revision {revision} is {row['status']}; only saved or failed "
                                               "revisions can be processed again.", 409)
        self.process(post_id, revision)
        return self.get(post_id)

    def process(self, post_id: str, revision: int) -> None:
        if not self.store.claim(post_id, revision):
            return                                     # already processed, or being processed elsewhere
        row = self.store.revision(post_id, revision)
        post = {"post_id": post_id, "url": row["url"], "publisher": row["publisher"], "platform": row["platform"],
                "raw_content": row["raw_content"]}
        if row["date_posted"]:
            post["date_posted"] = row["date_posted"]
        extraction = error = None
        try:
            extraction, error = self._extract(post)
        except Exception:                              # never leave a revision stuck in PROCESSING
            error = {"code": "INTERNAL_ERROR", "message": "Unexpected failure while processing.", "retryable": True}
        self.store.finish(post_id, revision, extraction, error)

    def _extract(self, post: dict) -> tuple[dict | None, dict | None]:
        calls = None
        try:
            calls = _Calls(self.model_factory())
            decision = decide(post, calls)
        except SP1ModelError as exc:
            decision, failure = None, {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
        else:
            failure = None
            if calls.errors:
                exc = calls.errors[0]
                failure = {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
            elif decision["classify"] is None or decision["roles"] is None:
                codes = sorted({f"{e['call']}:{e['code']}" for e in decision["errors"]})
                failure = {"code": "INVALID_MODEL_OUTPUT", "retryable": True,
                           "message": "The model reply failed validation: " + ", ".join(codes)}
        if failure is None:
            result = process_post(post, decision, self.policy, self.config)
            return self._extraction(result["record"], EXTRACTION_LLM, decision, calls), None
        if self.allow_rules_fallback:
            result = process_post(post, None, self.policy, self.config)
            extraction = self._extraction(result["record"], EXTRACTION_RULES_FALLBACK, None, None)
            extraction["model_failure"] = failure
            return extraction, None
        return None, failure

    def _extraction(self, record: dict, method: str, decision: dict | None, calls: _Calls | None) -> dict:
        record = redact(record)
        activity = record["activity"]
        flags = list(dict.fromkeys(list(activity["meta"]["flags"]) + [f"not_plannable:{r}" for r in record["not_plannable_reasons"]]))
        if method == EXTRACTION_RULES_FALLBACK:
            flags.insert(0, "rules_only_fallback_no_model_verification")
        model = None
        if calls is not None:
            config = getattr(calls.model, "config", None)
            model = {"served_model_ids": sorted(calls.served), "successful_calls": calls.calls,
                     "seconds": round(calls.seconds, 3),
                     "service": config.public() if config is not None else None}
        return {"extraction_method": method, "record": record, "review_flags": flags,
                "prompt_versions": dict(PROMPT_VERSIONS) if decision else None, "model": model,
                "llm_attempts": decision["attempts"] if decision else None,
                "llm_warnings": decision["warnings"] if decision else []}

    # -- publish ------------------------------------------------------------------------
    def publish(self, post_id: str, revision: int, reviewer: str) -> dict:
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise IngestError("REVIEWER_REQUIRED", "reviewer must name who reviewed the draft.")
        row = self._require(post_id, revision)
        current = self.store.published(post_id)
        if row["status"] == "PUBLISHED" and current and current[0]["revision"] == revision:
            return self.get(post_id)                   # repeated publish: nothing changes
        if row["status"] != "AWAITING_REVIEW":
            code = "STALE_REVISION" if row["status"] == "SUPERSEDED" else "PUBLISH_NOT_READY"
            raise IngestError(code, f"Revision {revision} is {row['status']} and cannot be published.", 409)
        payload = self._build_publication(post_id, row)
        self.store.commit_publication(post_id, revision, payload, reviewer.strip())
        return self.get(post_id)

    def _build_publication(self, post_id: str, row: dict) -> dict:
        """Everything the planner needs for one revision, built before anything is written."""
        from sp2.binding import propose_binding
        from sp2.rule_matcher import match_activity_to_rule

        extraction = row["extraction"]
        record = extraction["record"]
        projection = project(record)
        if projection["activity"] is None:
            raise IngestError("PUBLISH_BLOCKED", "Not publishable (SP3 activity contract): " + ", ".join(projection["blocked"])
                              + ". Fix the source metadata (for example publisher) and submit a new revision.")
        if not record["plannable"]:
            raise IngestError("PUBLISH_BLOCKED", "Not plannable: " + ", ".join(record["not_plannable_reasons"]))
        activity = projection["activity"]
        if activity["activity_id"] != post_id:
            raise IngestError("PUBLISH_BLOCKED", "The activity id does not match the post id.")
        evidence = auto_evidence([projection], DEMO_PROFILE, DEMO_TERM)
        rules = {r["rule_id"]: r for r in self.rules_config["rules"]}
        match = match_activity_to_rule(activity, row["raw_content"], self.rules_config).as_dict()
        proposal = propose_binding(post_id, record.get("activity_type"), match, rules)
        return {
            "post_id": post_id, "revision": row["revision"], "text_sha256": row["text_sha256"],
            "extraction_method": extraction["extraction_method"], "prompt_versions": extraction["prompt_versions"],
            "model": extraction["model"], "activity": activity, "activity_type": record.get("activity_type"),
            "binding": proposal["binding"],
            "binding_explanation": {k: proposal.get(k) for k in ("reason", "label", "matcher_rule", "matcher_method",
                                                                 "category_id", "points_from_rules")},
            "features": derive_features(record["activity"], record.get("activity_type")),
            "sidecar": {**projection["sidecar"], "derived": projection["derived"], "warnings": projection["warnings"],
                        "live_revision": row["revision"]},
            "evidence": {key: evidence[key].get(post_id) for key in (
                "eligibility_by_activity", "term_scope_by_activity", "source_review_by_activity",
                "schedule_by_activity")},
        }

    # -- read ---------------------------------------------------------------------------
    def _require(self, post_id: str, revision: int) -> dict:
        row = self.store.revision(post_id, revision)
        if row is None:
            raise IngestError("NOT_FOUND", "Unknown post or revision.", 404)
        return row

    def get(self, post_id: str) -> dict:
        revisions = self.store.revisions(post_id)
        if not revisions:
            raise IngestError("NOT_FOUND", "Unknown post.", 404)
        published = self.store.published(post_id)
        published_revision = published[0]["revision"] if published else None
        latest = revisions[-1]
        return {
            "post_id": post_id, "latest_revision": latest["revision"], "ui_state": UI_STATES[latest["status"]],
            "published_revision": published_revision,
            "has_unpublished_edit": published_revision is not None and latest["revision"] != published_revision,
            "revisions": [self._public(r) for r in revisions],
            "published": ({"revision": published[0]["revision"], "published_at": published[0]["published_at"],
                           "reviewer": published[0]["reviewer"], "binding": published[0]["binding"],
                           "activity": published[0]["activity"]} if published else None),
        }

    def list(self) -> list[dict]:
        out = []
        for post_id in self.store.post_ids():
            item = self.get(post_id)
            out.append({k: item[k] for k in ("post_id", "latest_revision", "ui_state", "published_revision",
                                             "has_unpublished_edit")})
        return out

    @staticmethod
    def _public(row: dict) -> dict:
        keys = ("revision", "status", "text_sha256", "raw_content", "url", "url_is_placeholder", "publisher", "platform",
                "date_posted", "saved_at", "processed_at", "attempts", "extraction", "error")
        data = {k: row[k] for k in keys}
        data["ui_state"] = UI_STATES[row["status"]]
        return data


def model_factory_from_env() -> Callable[[], Any]:
    from .model_client import SP1ModelClient, SP1ModelConfig

    def make():
        return SP1ModelClient(SP1ModelConfig.from_env())
    return make


def service_from_env() -> LiveIngestService:
    return LiveIngestService(LiveStore(os.environ.get("UNILIFE_LIVE_DB") or DEFAULT_DB), model_factory_from_env(),
                             allow_rules_fallback=os.environ.get("SP1_ALLOW_RULES_FALLBACK", "").lower() in {"1", "true", "yes"})
