"""SP1 extractor: one announcement -> list of extraction drafts {record, meta}.

Contract: schemas/extraction_draft.schema.json (1.3.0), decisions in
docs/adr/0001-sp1-extraction-contract.md, field rules in docs/sp1_extractor.md.

Pipeline (everything after step 2 is deterministic code, never the model):
  1. validate input (text, source)
  2. raw extraction: regex baseline, or LLM with regex fallback
  3. per field: type/enum check, grounding check (evidence occurs in the text),
     evidence-states-the-value check, range check, date parsing with traced defaults
  4. mode/location reconciliation (D13), traced in meta.derived
  5. needs_review flags (title, mode; completion_requirements only for online recognised
     activities, D16), injection flag
  6. temporary ID, status, schema validation

Usage:
    from sp1.extractor import extract, extract_post
    drafts = extract(text, source, posted_date="2026-10-20")       # regex
    drafts = extract(text, source, method="llm", llm_client=client, model_name="qwen-4b-4bit")
    result = extract_post(post)        # one item of the collector's posts file (see POST_* below)

CLI (regex only; run the LLM path from a notebook with a client):
    python -m sp1.extractor --input data/raw/posts.json --output data/interim/drafts.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from . import llm_backend, regex_baseline
from .dates import DateParseError, parse_point, parse_range, parse_rounds

DRAFT_SCHEMA_VERSION = "1.3.0"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "extraction_draft.schema.json"

MAX_TEXT_CHARS = 20_000
MAX_POINTS = 100          # conduct score scale is 0-100
MAX_FEE_VND = 10_000_000
YEAR_MIN, YEAR_MAX = 2020, 2035

DOMAINS = {"academic", "volunteer", "culture_sports", "skills", "career", "other"}
MODES = {"online", "offline", "hybrid"}
REQUIRED_IN_FINAL = ("title", "mode")  # mandatory, fee: nullable (D10); completion_requirements: see D16

_INJECTION = re.compile(
    r"bỏ\s+qua\s+(?:mọi|tất\s+cả|các)?\s*(?:hướng\s+dẫn|chỉ\s+dẫn|yêu\s+cầu|quy\s+tắc)"
    r"|ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)?\s*instructions"
    r"|disregard\s+(?:all\s+|the\s+)?(?:previous|above)"
    r"|system\s+prompt|you\s+are\s+now|bạn\s+là\s+một\s+(?:trợ\s+lý|mô\s+hình|AI)"
    r"|(?:hãy|phải)\s+(?:ghi|điền|trả\s+về|xuất)\s+(?:là\s+)?\d+\s*điểm",
    re.IGNORECASE,
)


# Collector posts file (Minh Tri): a JSON array of these objects.
POST_REQUIRED = ("post_id", "url", "raw_content", "publisher", "platform")
POST_OPTIONAL = ("date_posted",)


class InputError(ValueError):
    """The announcement or its source metadata is not usable."""


class DraftSchemaError(RuntimeError):
    """A produced draft violates the draft schema (a bug in this module)."""



def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().casefold()


def _grounded(span: str, norm_text: str) -> bool:
    return bool(span) and _norm(span) in norm_text


def _as_spans(evidence: Any) -> list[str] | None:
    if evidence is None:
        return None
    if isinstance(evidence, str):
        return [evidence] if evidence.strip() else None
    if isinstance(evidence, list) and evidence and all(isinstance(e, str) and e.strip() for e in evidence):
        return list(evidence)
    return None


def _joined(evidence: Any) -> str:
    return " ".join(_as_spans(evidence) or [])


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _states_amount(evidence: str, amount: float) -> bool:
    """True if the evidence writes this VND amount ("500000", "500.000", "500,000", "500k", "500 nghìn", "500 ngàn")."""
    if amount != int(amount):
        return False
    n = int(amount)
    forms = "|".join(re.escape(f) for f in {str(n), f"{n:,}", f"{n:,}".replace(",", ".")})
    if n % 1000 == 0:
        forms += rf"|{n // 1000}\s*(?:k|nghìn|ngàn)(?!\w)"
    return bool(re.search(rf"(?<![\d.,])(?:{forms})(?![.,]?\d)", evidence, re.IGNORECASE))


def _temp_id(url_post: str, index: int) -> str:
    return f"TMP-{hashlib.sha1(url_post.encode('utf-8')).hexdigest()[:8]}-{index:02d}"


def _validate_input(text: Any, source: Any) -> None:
    if not isinstance(text, str) or not text.strip():
        raise InputError("text must be a non-empty string")
    if len(text) > MAX_TEXT_CHARS:
        raise InputError(f"text longer than {MAX_TEXT_CHARS} characters")
    if not isinstance(source, dict):
        raise InputError("source must be an object")
    # URL_registration is NOT input: the extractor finds it in the text (ADR 0001, D9).
    expected = {"publisher", "platform", "URL_post"}
    if set(source) != expected:
        raise InputError(f"source keys must be exactly {sorted(expected)}")
    for k in expected:
        if not isinstance(source[k], str) or not source[k].strip():
            raise InputError(f"source.{k} must be a non-empty string")
    if not source["URL_post"].startswith(("http://", "https://")):
        raise InputError("source.URL_post must be an http(s) URL")


# ---------- normalisation of one raw activity ----------

class _Builder:
    def __init__(self, text: str, norm_text: str, posted: dt.date | None):
        self.text = text              # NFC, original case: source of copied URLs
        self.norm_text = norm_text
        self.posted = posted
        self.year_from_posted: list[str] = []
        self.record: dict[str, Any] = {}
        self.flags: list[str] = []
        self.evidence: dict[str, Any] = {}
        self.time_defaults: dict[str, str] = {}
        self.derived: dict[str, str] = {}

    def flag(self, f: str) -> None:
        """Add flag f to meta.flags once."""
        if f not in self.flags:
            self.flags.append(f)

    def _drop(self, field: str) -> None:
        """The evidence does not state the value: set it to null, remove its evidence, flag ungrounded:<field>."""
        self.record[field] = None
        self.evidence.pop(field, None)
        self.flag(f"ungrounded:{field}")

    def _ground(self, field: str, evidence: Any) -> bool:
        """Store evidence (str or list) if every span occurs in the text; else flag ungrounded:<field>, return False."""
        spans = _as_spans(evidence)
        if spans is None or not all(_grounded(s, self.norm_text) for s in spans):
            self.flag(f"ungrounded:{field}")
            return False
        self.evidence[field] = spans[0] if len(spans) == 1 else spans
        return True

    def text_field(self, field: str, cell: dict[str, Any]) -> None:
        """Accept a non-empty string copied from the text; sets record[field]; flags invalid_value or ungrounded."""
        v = cell["value"]
        if v is None:
            self.record[field] = None
            return
        if not isinstance(v, str) or not v.strip():
            self.flag(f"invalid_value:{field}")
            self.record[field] = None
            return
        v = v.strip()
        self.record[field] = v
        if self._ground(field, cell["evidence"]) and _norm(v) not in self.norm_text:
            self.flag(f"ungrounded:{field}")  # value itself must be copied from the text

    def list_field(self, field: str, cell: dict[str, Any]) -> None:
        """Accept a list of non-empty strings each copied from the text; sets record[field] (null for []);
        flags invalid_value or ungrounded."""
        v = cell["value"]
        if v is None or v == []:
            self.record[field] = None
            return
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            self.flag(f"invalid_value:{field}")
            self.record[field] = None
            return
        v = [x.strip() for x in v]
        self.record[field] = v
        if self._ground(field, cell["evidence"]) and not all(_norm(x) in self.norm_text for x in v):
            self.flag(f"ungrounded:{field}")

    def enum_field(self, field: str, cell: dict[str, Any], allowed: set[str]) -> None:
        """Accept a value from allowed with grounded evidence; sets record[field]; flags invalid_value or ungrounded."""
        v = cell["value"]
        if v is None:
            self.record[field] = None
            return
        if v not in allowed:
            self.flag(f"invalid_value:{field}")
            self.record[field] = None
            return
        self.record[field] = v
        self._ground(field, cell["evidence"])

    def bool_field(self, field: str, cell: dict[str, Any]) -> None:
        """Accept a bool with grounded evidence; sets record[field]; flags invalid_value or ungrounded."""
        v = cell["value"]
        if v is None:
            self.record[field] = None
            return
        if not isinstance(v, bool):
            self.flag(f"invalid_value:{field}")
            self.record[field] = None
            return
        self.record[field] = v
        self._ground(field, cell["evidence"])

    def _stated_bool(self, field: str, cell: dict[str, Any], positive: Any, negative: Any) -> None:
        """bool_field, then the evidence must state the value (positive() for true, negative() for false),
        else null + ungrounded:<field>."""
        self.bool_field(field, cell)
        v = self.record[field]
        if v is not None and (positive if v else negative)(_joined(cell["evidence"])) is None:
            self._drop(field)

    def drl(self, cell: dict[str, Any]) -> None:
        """drl_recognized: the evidence must state (true) or deny (false) recognition, else null + ungrounded."""
        self._stated_bool("drl_recognized", cell, regex_baseline.drl_positive, regex_baseline.drl_negative)

    def mandatory(self, cell: dict[str, Any]) -> None:
        """mandatory: the evidence must say "bắt buộc" (true) or "không bắt buộc" (false), else null + ungrounded."""
        self._stated_bool("mandatory", cell, regex_baseline.mandatory_positive, regex_baseline.mandatory_negative)

    def completion(self, cell: dict[str, Any]) -> None:
        """completion_requirements: text_field, then the evidence must hold a completion keyword, else null + ungrounded."""
        self.text_field("completion_requirements", cell)
        if (self.record["completion_requirements"] is not None
                and regex_baseline.completion_phrase(_joined(cell["evidence"])) is None):
            self._drop("completion_requirements")

    def registration_url(self, cell: dict[str, Any]) -> None:
        """Accept a link found exactly once in the text, not a Facebook link; sets URL_registration copied from
        the text; flags invalid_value or ungrounded:URL_registration."""
        # The model only points at a link; the stored value is always the text's own spelling.
        v = cell["value"]
        self.record["URL_registration"] = None
        if v is None:
            return
        if not isinstance(v, str) or not v.strip():
            self.flag("invalid_value:URL_registration")
            return
        # Strip trailing punctuation and closing brackets: URLs found in the text never end with them.
        wanted = regex_baseline.strip_scheme(v.strip().rstrip(regex_baseline.URL_TRAILING + ")]}>\"'")).casefold()
        if not wanted or not re.fullmatch(r"\S+", wanted) or "." not in wanted.split("/")[0]:
            self.flag("invalid_value:URL_registration")      # e.g. "fanpage": not a link
            return
        if regex_baseline.is_noise_link(wanted):
            self.flag("invalid_value:URL_registration")      # a Facebook link is never the registration link (R3)
            return
        # Keyed without scheme, so "https://x/AbC" and "x/AbC" in one post count as one link.
        links = regex_baseline.distinct_links(regex_baseline.urls_in(self.text))
        matches = [u for u in links if regex_baseline.strip_scheme(u).casefold() == wanted]
        if len(matches) != 1:          # not in the text, or two links differing only in case
            self.flag("ungrounded:URL_registration")
            return
        self.record["URL_registration"] = regex_baseline.with_scheme(matches[0])
        self.evidence["URL_registration"] = matches[0]

    def points(self, cell: dict[str, Any]) -> None:
        """Accept a number in (0, MAX_POINTS] written in its evidence; sets points; flags invalid_value,
        out_of_range or ungrounded:points (value kept)."""
        v = cell["value"]
        self.record["points"] = None
        if v is None:
            return
        if not _is_number(v):
            self.flag("invalid_value:points")
            return
        if not (0 < v <= MAX_POINTS):
            self.flag("out_of_range:points")
            return
        self.record["points"] = v
        if self._ground("points", cell["evidence"]):
            joined = _joined(cell["evidence"])
            forms = {f"{v:g}", f"{v:g}".replace(".", ",")}
            if not any(re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d.,]*\d)", joined) for f in forms):
                self.flag("ungrounded:points")

    def fee(self, cell: dict[str, Any]) -> None:
        """Accept a VND amount in [0, MAX_FEE_VND] whose evidence says free (0) or writes it; sets fee;
        flags invalid_value, out_of_range or ungrounded:fee (value null)."""
        v = cell["value"]
        self.record["fee"] = None
        if v is None:
            return
        if not _is_number(v):
            self.flag("invalid_value:fee")
            return
        if not (0 <= v <= MAX_FEE_VND):
            self.flag("out_of_range:fee")
            return
        self.record["fee"] = v
        if self._ground("fee", cell["evidence"]):
            joined = _joined(cell["evidence"])
            ok = regex_baseline.free_phrase(joined) is not None if v == 0 else _states_amount(joined, v)
            if not ok:
                self._drop("fee")  # 0 needs an explicit "free"; > 0 needs the amount itself

    def _year_ok(self, field: str, iso: str) -> bool:
        """True if the year is in YEAR_MIN..YEAR_MAX; else flags out_of_range:<field>."""
        if not (YEAR_MIN <= int(iso[:4]) <= YEAR_MAX):
            self.flag(f"out_of_range:{field}")
            return False
        return True

    def time_range(self, cell: dict[str, Any], rounds: bool) -> None:
        """Parse the time evidence into start/end and their traces; flags ungrounded:start, invalid_value:start,
        out_of_range or end_before_start."""
        # rounds: several spans are separate rounds of one activity (D16), not fragments of one statement.
        self.record["start"] = self.record["end"] = None
        spans = _as_spans(cell["evidence"])
        if spans is None:
            return
        if not all(_grounded(s, self.norm_text) for s in spans):
            self.flag("ungrounded:start")
            return
        try:
            if rounds and len(spans) > 1:
                r = parse_rounds(spans, self.posted)
            else:
                r = parse_range(" ".join(spans), self.posted)
        except DateParseError:
            self.flag("invalid_value:start")
            return
        ev = spans[0] if len(spans) == 1 else spans
        if self._year_ok("start", r.start):
            self.record["start"] = r.start
            self.evidence["start"] = ev
            if r.start_defaulted:
                self.time_defaults["start"] = "date_only_0000"
        if r.end is not None and self._year_ok("end", r.end):
            self.record["end"] = r.end
            self.evidence["end"] = ev
            if r.end_defaulted:
                self.time_defaults["end"] = "date_only_2359"
        if r.year_from_posted:
            self.year_from_posted += [f for f in ("start", "end") if self.record[f]]
        if self.record["start"] and self.record["end"] and self.record["end"] <= self.record["start"]:
            self.flag("end_before_start")

    def deadline(self, cell: dict[str, Any]) -> None:
        """Parse the deadline evidence (last date/time) into registration_deadline and its traces; flags
        ungrounded, invalid_value or out_of_range:registration_deadline."""
        self.record["registration_deadline"] = None
        spans = _as_spans(cell["evidence"])
        if spans is None:
            return
        if not all(_grounded(s, self.norm_text) for s in spans):
            self.flag("ungrounded:registration_deadline")
            return
        try:
            p = parse_point(" ".join(spans), self.posted)
        except DateParseError:
            self.flag("invalid_value:registration_deadline")
            return
        if self._year_ok("registration_deadline", p.value):
            self.record["registration_deadline"] = p.value
            self.evidence["registration_deadline"] = spans[0] if len(spans) == 1 else spans
            if p.defaulted:
                self.time_defaults["registration_deadline"] = "date_only_2359"
            if p.year_from_posted:
                self.year_from_posted.append("registration_deadline")

    def _venue_kind(self) -> str | None:
        """Venue kind of the accepted location, or None when there is none or it is ungrounded."""
        location = self.record["location"]
        if location is None or "ungrounded:location" in self.flags:
            return None   # only a location copied from the text may decide the mode
        return regex_baseline.venue_kind(location)

    def _derive_mode(self, mode: str, how: str, evidence: Any) -> None:
        """Set mode from a venue or link instead of the text's own words; traced in meta.derived["mode"]."""
        self.record["mode"] = mode
        self.evidence["mode"] = evidence
        self.derived["mode"] = how

    def _clear_location(self) -> None:
        """Null the location of an online activity; traced in meta.derived["location"]."""
        if self.record["location"] is not None:
            self.record["location"] = None
            self.evidence.pop("location", None)
            self.derived["location"] = "cleared_for_online"

    def reconcile_mode_location(self) -> None:
        """Apply the D13 table: derive mode, null a conflicting mode (needs_review:mode follows), clear online locations."""
        # A physical venue means in person, a platform or meeting link means online, and online means
        # no location (R1-R4); on a conflict the mode is left null for review rather than guessed.
        mode, kind = self.record["mode"], self._venue_kind()
        if mode is None:
            if kind == "physical":
                self._derive_mode("offline", "venue_physical", self.evidence["location"])
            elif kind == "platform":
                self._derive_mode("online", "venue_platform", self.evidence["location"])
            elif self.record["location"] is None:
                link = regex_baseline.meeting_link(self.text)
                if link:
                    self._derive_mode("online", "meeting_link", link)
        elif (mode == "online" and kind in ("physical", "both")) or (mode == "offline" and kind == "platform"):
            self.record["mode"] = None
            self.evidence.pop("mode", None)
        if self.record["mode"] == "online" or (self.record["mode"] == "hybrid" and kind == "platform"):
            self._clear_location()
        assert not (self.record["mode"] == "online" and self.record["location"] is not None)


def _status(flags: list[str]) -> str:
    if not flags:
        return "valid"
    if all(f.startswith("needs_review:") for f in flags):
        return "partial"
    return "failed"


def _build_fields(b: _Builder, raw: dict[str, dict[str, Any]], method: str) -> None:
    """Check every raw field into b.record, b.evidence and b.flags."""
    b.registration_url(raw["URL_registration"])
    b.text_field("title", raw["title"])
    b.enum_field("domain", raw["domain"], DOMAINS)
    # The regex lists one line per round; an LLM list holds pieces of one time statement.
    b.time_range(raw["time"], rounds=method == "regex")
    b.deadline(raw["registration_deadline"])
    b.enum_field("mode", raw["mode"], MODES)
    b.text_field("location", raw["location"])
    b.points(raw["points"])
    b.drl(raw["drl_recognized"])
    b.mandatory(raw["mandatory"])
    b.list_field("audience", raw["audience"])
    b.fee(raw["fee"])
    b.completion(raw["completion_requirements"])


def _review_flags(b: _Builder, injection: bool) -> None:
    """Add needs_review flags for missing required values, and injection_suspected."""
    for field in REQUIRED_IN_FINAL:
        if b.record[field] is None:
            b.flag(f"needs_review:{field}")
    # Display-only field (D16): an online recognised activity always states how to be recognised,
    # so only there a missing value means the extractor missed it.
    if (b.record["completion_requirements"] is None and b.record["mode"] == "online"
            and b.record["drl_recognized"] is True):
        b.flag("needs_review:completion_requirements")
    if injection:
        b.flag("injection_suspected")


def _assemble(b: _Builder, index: int, source: dict[str, Any], method: str,
              model: str | None, fallback_from: str | None) -> dict[str, Any]:
    """Build the {record, meta} draft from a finished builder."""
    record = {
        "activity_id": _temp_id(source["URL_post"], index),
        "source": {**source, "URL_registration": b.record["URL_registration"]},
        "title": b.record["title"],
        "domain": b.record["domain"],
        "start": b.record["start"],
        "end": b.record["end"],
        "registration_deadline": b.record["registration_deadline"],
        "mode": b.record["mode"],
        "location": b.record["location"],
        "points": b.record["points"],
        "drl_recognized": b.record["drl_recognized"],
        "mandatory": b.record["mandatory"],
        "audience": b.record["audience"],
        "fee": b.record["fee"],
        "completion_requirements": b.record["completion_requirements"],
    }
    meta = {
        "status": _status(b.flags),
        "flags": b.flags,
        "evidence": b.evidence,
        "time_defaults": b.time_defaults,
        "year_from_posted": b.year_from_posted,
        "derived": b.derived,
        "method": method,
        "model": model,
        "fallback_from": fallback_from,
        "draft_schema_version": DRAFT_SCHEMA_VERSION,
    }
    return {"record": record, "meta": meta}


def _build_draft(raw: dict[str, dict[str, Any]], index: int, source: dict[str, Any],
                 text: str, norm_text: str, posted: dt.date | None, injection: bool, method: str,
                 model: str | None, fallback_from: str | None) -> dict[str, Any]:
    """One raw activity -> one checked draft: fields, then reconciliation, then review flags."""
    b = _Builder(text, norm_text, posted)
    _build_fields(b, raw, method)
    b.reconcile_mode_location()
    _review_flags(b, injection)
    return _assemble(b, index, source, method, model, fallback_from)


_validator = None


def _validate_drafts(drafts: list[dict[str, Any]]) -> None:
    global _validator
    if _validator is None:
        from jsonschema import Draft202012Validator
        _validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    errors = sorted(_validator.iter_errors(drafts), key=lambda e: list(e.path))
    if errors:
        raise DraftSchemaError("; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5]))


# ---------- public API ----------

def _parse_posted(value: Any) -> dt.date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError("posted date must be a YYYY-MM-DD string or null")
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError as e:
        raise InputError(f"posted date is not YYYY-MM-DD: {value!r}") from e


def extract(text: str, source: dict[str, Any], method: str = "regex",
            llm_client: llm_backend.LLMClient | None = None,
            model_name: str | None = None,
            posted_date: str | None = None) -> list[dict[str, Any]]:
    """Return one draft per activity found in the announcement (possibly empty).

    posted_date (YYYY-MM-DD) is used only to fill a year the text leaves out; traced in meta.year_from_posted.
    """
    _validate_input(text, source)
    posted = _parse_posted(posted_date)
    if method not in ("regex", "llm"):
        raise ValueError("method must be 'regex' or 'llm'")
    text = unicodedata.normalize("NFC", text)
    norm_text = _norm(text)
    injection = bool(_INJECTION.search(text)) or llm_backend.contains_delimiter(text)

    used_method, model, fallback_from = method, None, None
    if method == "llm":
        if llm_client is None:
            raise ValueError("method='llm' needs llm_client")
        model = f"{model_name or 'unknown-model'}/{llm_backend.PROMPT_VERSION}"
        try:
            raws = llm_backend.extract_raw(text, llm_client)
        except llm_backend.LLMOutputError:
            used_method, model, fallback_from = "regex", None, "llm:parse_error"
            raws = regex_baseline.extract_raw(text)
        except Exception:  # model crashed, timed out, ran out of memory...
            used_method, model, fallback_from = "regex", None, "llm:client_error"
            raws = regex_baseline.extract_raw(text)
    else:
        raws = regex_baseline.extract_raw(text)

    drafts = [
        _build_draft(raw, i, source, text, norm_text, posted, injection, used_method, model, fallback_from)
        for i, raw in enumerate(raws, start=1)
    ]
    _validate_drafts(drafts)
    return drafts


def extract_post(post: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the extractor on one item of the collector's posts file.

    Returns {post_id, drafts}; raises InputError for a malformed post. Every post is assumed to be a
    real post whose raw_content is the post text itself (ADR 0001, D11).
    """
    if not isinstance(post, dict):
        raise InputError("post must be an object")
    missing = [k for k in POST_REQUIRED if k not in post]
    if missing:
        raise InputError(f"post is missing {missing}")
    unknown = set(post) - set(POST_REQUIRED) - set(POST_OPTIONAL)
    if unknown:
        raise InputError(f"unknown post fields {sorted(unknown)}")
    if not isinstance(post["post_id"], str) or not post["post_id"].strip():
        raise InputError("post_id must be a non-empty string")
    source = {"publisher": post["publisher"], "platform": post["platform"], "URL_post": post["url"]}
    drafts = extract(post["raw_content"], source, posted_date=post.get("date_posted"), **kwargs)
    return {"post_id": post["post_id"], "drafts": drafts}


def run_posts(posts: list[Any], **kwargs: Any) -> list[dict[str, Any]]:
    """Extract every post; a bad post becomes an error entry instead of stopping the batch."""
    results = []
    for i, post in enumerate(posts):
        pid = post.get("post_id") if isinstance(post, dict) else None
        try:
            results.append(extract_post(post, **kwargs))
        except InputError as e:
            results.append({"post_id": pid, "index": i, "error": f"InputError: {e}"})
    return results


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SP1 regex extraction over the collector's posts file.")
    ap.add_argument("--input", required=True, help="JSON array of posts (post_id, url, raw_content, publisher, platform, ...)")
    ap.add_argument("--output", required=True, help="JSON array: {post_id, drafts} or {post_id, index, error}")
    args = ap.parse_args(argv)

    with open(args.input, encoding="utf-8") as f:
        posts = json.load(f)
    if not isinstance(posts, list):
        print("input must be a JSON array of posts", file=sys.stderr)
        return 2
    results = run_posts(posts)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")
    n_err = sum(1 for r in results if "error" in r)
    n_drafts = sum(len(r.get("drafts", [])) for r in results)
    print(f"{len(results) - n_err} posts extracted ({n_drafts} drafts), {n_err} input errors", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
