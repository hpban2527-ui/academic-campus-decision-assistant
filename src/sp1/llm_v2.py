"""Closed-enum LLM decisions with candidate-grounded deterministic values."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Callable

from .activity_type import KEYWORDS
from .candidates import Candidate, build_candidates
from dataclasses import replace

from .dates import DateParseError, day_range_spans, parse_point
from .extract_v2 import BANNERS, precision
from .preprocess import original_span, preprocess
from .segment import segment

PROMPT_VERSIONS = {"classify": "sp1_classify_v2 1.0.0", "roles": "sp1_roles_v2 1.0.0"}
LLMClient = Callable[[str], str]
ROOT = Path(__file__).resolve().parents[2]
ACTIVITY_TYPES = {key for key, _ in KEYWORDS} | {"other"}
CLASS_KEYS = {"post_type", "post_type_evidence", "activity_type", "domain", "mode", "mode_evidence"}
ROLE_ENUMS = {
    "dates": {"first_start", "first_end", "registration_deadline", "later_session", "earlier_notice", "other"},
    "times": {"first_start", "first_end", "registration_deadline", "other"},
    "urls": {"registration", "join", "read_more", "other"},
}


class LLMReplyError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def clean_reply(reply):
    return re.sub(r"^\s*<think>.*?</think>\s*", "", reply, count=1, flags=re.S)


def _safe(text):
    text = re.sub(r"</?\s*announcement\b[^>]*>", "[removed-delimiter]", str(text), flags=re.I)
    # Additional outbound guard for the documented N0 parenthesised-area-code gap.
    return re.sub(r"\(\d{2,3}\)[ .-]*\d(?:[ .-]?\d){6,8}", "[phone removed]", text)


def _prompt(kind, pre, cands, post):
    template = (ROOT / "prompts" / f"sp1_{kind}_v2.txt").read_text(encoding="utf-8")
    announcement = "\n".join(f"L{i}: {_safe(line)}" for i, line in enumerate(pre.text.split("\n"), 1))
    candidates = "\n".join(
        f'{c.id} {json.dumps(_safe(c.text), ensure_ascii=False)} L{c.line_no} '
        f'[label: {c.label_key or "none"}] context: {json.dumps(_safe(c.context), ensure_ascii=False)}'
        for c in cands)
    replacements = {"ANNOUNCEMENT": announcement, "CANDIDATES": candidates,
                    "POSTED_DATE": _safe(post.get("date_posted", "unknown"))}
    # One substitution pass prevents text containing a placeholder from expanding another field.
    return re.sub(r"\{\{(ANNOUNCEMENT|CANDIDATES|POSTED_DATE)\}\}",
                  lambda m: replacements[m[1]], template)


def build_classify_prompt(pre, seg, post):
    return _prompt("classify", pre, [c for c in build_candidates(pre, seg) if c.kind == "title"], post)


def build_roles_prompt(pre, seg, cands, post):
    return _prompt("roles", pre, cands, post)


def _json(reply):
    if not isinstance(reply, str):
        raise LLMReplyError("bad_json")
    reply = clean_reply(reply)
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        raise LLMReplyError("no_json")

    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise LLMReplyError("bad_json")
            obj[key] = value
        return obj

    try:
        obj = json.loads(reply[start:end + 1], object_pairs_hook=unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(LLMReplyError("bad_json")))
    except (ValueError, TypeError) as exc:
        if isinstance(exc, LLMReplyError):
            raise
        raise LLMReplyError("bad_json") from exc
    if not isinstance(obj, dict):
        raise LLMReplyError("bad_json")
    return obj


def _keys(obj, keys, strict=True, warnings=None):
    if not keys <= obj.keys():
        raise LLMReplyError("missing_key")
    if obj.keys() != keys:
        if strict:
            raise LLMReplyError("bad_json")
        # Lenient replay: extra keys carry no value the pipeline uses, so they are dropped.
        for extra in sorted(obj.keys() - keys):
            _warn(warnings, f"extra_key:{extra}")
            del obj[extra]


def _warn(warnings, code):
    if warnings is not None:
        warnings.append(code)


def _enum(value, choices):
    if not (value is None or isinstance(value, str)) or value not in choices:
        raise LLMReplyError("bad_enum")


def parse_classify(reply: str, n_lines: int, strict: bool = True, warnings: list | None = None) -> dict:
    """Validate a classify reply.

    strict=True (default) rejects any deviation. strict=False is the lenient replay mode used by
    decide(): extra keys are dropped; an invalid activity_type or domain becomes null (no decision);
    an invalid mode or mode evidence makes mode null. A wrong post_type, missing keys or broken JSON
    still reject the reply. Every relaxation is recorded in `warnings`. Lenient mode never creates a
    value: it only removes decisions.
    """
    obj = _json(reply)
    _keys(obj, CLASS_KEYS, strict, warnings)
    _enum(obj["post_type"], {"activity", "info_only", "insufficient"})
    for field, choices in (
        ("activity_type", ACTIVITY_TYPES),
        ("domain", {"academic", "volunteer", "culture_sports", "skills", "career", "other", None}),
        ("mode", {"online", "offline", "hybrid", None}),
    ):
        try:
            _enum(obj[field], choices)
        except LLMReplyError:
            if strict:
                raise
            _warn(warnings, f"bad_enum_dropped:{field}")
            obj[field] = None
    for field in ("post_type_evidence", "mode_evidence"):
        value = obj[field]
        if field == "mode_evidence" and value is None:
            continue
        if field == "post_type_evidence" and value == "H1":
            continue  # Candidate existence is checked by decide, which has the candidate list.
        if not isinstance(value, str) or not re.fullmatch(r"L[1-9]\d*", value) or int(value[1:]) > n_lines:
            if strict or field == "post_type_evidence":
                raise LLMReplyError("bad_line")
            _warn(warnings, "bad_line_dropped:mode_evidence")
            obj["mode_evidence"], obj["mode"] = None, None
    return obj


def _id_for_text(text, cands, kind):
    """ID of the single candidate of this kind whose text equals `text` exactly, else None."""
    if not isinstance(text, str) or not text.strip():
        return None
    hits = [c.id for c in cands if c.kind == kind and c.text.strip() == text.strip()]
    return hits[0] if len(hits) == 1 else None


def parse_roles(reply: str, cands: list[Candidate], strict: bool = True, warnings: list | None = None) -> dict:
    """Validate a roles reply.

    strict=True (default) rejects any deviation. strict=False (lenient replay, used by decide())
    drops unknown candidate IDs, gives missing IDs and invalid roles the role "other" (not chosen),
    turns an unknown title ID into "none" and an invalid multi_session into null. Broken JSON or
    missing top-level keys still reject the reply. Lenient mode can only remove choices, never add
    a value, so every value is still built from an existing candidate.
    One recovery is allowed: when the model writes a candidate's text instead of its ID (for
    example "06/11/2026" instead of "D1"), the key is mapped to that ID if the text equals exactly
    one candidate of that kind and the ID is not already in the reply. The value still comes from
    the existing candidate, so grounding is unchanged.
    """
    obj = _json(reply)
    _keys(obj, {"title", "multi_session", "dates", "times", "urls"}, strict, warnings)
    titles = {c.id for c in cands if c.kind == "title"}
    if not strict and isinstance(obj["title"], str) and obj["title"] not in titles | {"none"}:
        recovered = _id_for_text(obj["title"], cands, "title")
        if recovered:
            _warn(warnings, "title_text_mapped_to_id")
            obj["title"] = recovered
    if not isinstance(obj["title"], str) or obj["title"] not in titles | {"none"}:
        if strict:
            raise LLMReplyError("unknown_id")
        _warn(warnings, "unknown_title_dropped")
        obj["title"] = "none"
    if obj["multi_session"] is not None and type(obj["multi_session"]) is not bool:
        if strict:
            raise LLMReplyError("bad_enum")
        _warn(warnings, "bad_multi_session_dropped")
        obj["multi_session"] = None
    for key, kind in (("dates", "date"), ("times", "time"), ("urls", "url")):
        mapping = obj[key]
        if not isinstance(mapping, dict):
            raise LLMReplyError("bad_json")
        expected = {c.id for c in cands if c.kind == kind}
        if strict:
            if mapping.keys() - expected:
                raise LLMReplyError("unknown_id")
            if expected - mapping.keys():
                raise LLMReplyError("missing_id")
            for role in mapping.values():
                _enum(role, ROLE_ENUMS[key])
            continue
        cleaned = {}
        mapping = dict(mapping)
        for cid in sorted(mapping.keys() - expected):
            recovered = _id_for_text(cid, cands, kind)
            if recovered and recovered not in mapping:
                _warn(warnings, f"text_mapped_to_id:{recovered}")
                mapping[recovered] = mapping.pop(cid)
            else:
                _warn(warnings, f"unknown_id_dropped:{cid}")
        for cid in sorted(expected, key=lambda x: int(x[1:])):
            if cid not in mapping:
                _warn(warnings, f"missing_id_as_other:{cid}")
                cleaned[cid] = "other"
                continue
            role = mapping[cid]
            try:
                _enum(role, ROLE_ENUMS[key])
            except LLMReplyError:
                _warn(warnings, f"bad_role_as_other:{cid}")
                role = "other"
            cleaned[cid] = role
        obj[key] = cleaned
    return obj


def evidence_span(pre, start, end):
    """Exact original slices, excluding masked contact regions."""
    ranges = [(start, end)]
    for left, right, _ in pre.masked:
        ranges = [(a, b) for x, y in ranges for a, b in
                  ((x, min(y, left)), (max(x, right), y)) if a < b]
    result = []
    for a, b in ranges:
        left, right = original_span(pre, a, b)
        if left < right:
            result.append({"start": left, "end": right, "text": pre.original[left:right]})
    return result


def _clean_title(text):
    text = re.sub(r"(?:\s*#\w+)+\s*$", "", text).strip()
    text = re.sub(r"^[^\w\[]+|[^\w\]]+$", "", text)
    if re.fullmatch(r"\[[^\[\]\n]+\]", text):
        text = text[1:-1].strip()
    if len(text) < 4 or text.split("\n")[0].strip("[] ").casefold() in BANNERS:
        return None
    return text


def values_from_roles(roles, cands, pre, posted):
    """Return record values plus evidence/flags. Failed construction omits that field."""
    roles = parse_roles(json.dumps(roles), cands)
    if isinstance(posted, str):
        try:
            posted = date.fromisoformat(posted[:10])
        except ValueError:
            posted = None
    record = {"multi_session": roles["multi_session"]}
    evidence, flags, inferred = {}, list(getattr(cands, "flags", [])), []
    by_id = {c.id: c for c in cands}

    def choose(group, role, field):
        selected = sorted((by_id[cid] for cid, value in roles[group].items() if value == role),
                          key=lambda c: c.start)
        if len(selected) > 1:
            flags.append(f"needs_review:{field}")
        return selected[0] if selected else None

    def put(field, value, selected):
        record[field] = value
        evidence[field] = [span for c in selected if c for span in evidence_span(pre, c.start, c.end)]

    title = by_id.get(roles["title"])
    put("title", _clean_title(title.text) if title else None, [title])
    ranges = day_range_spans(pre.text)
    first = choose("dates", "first_start", "window_open")
    for field, role in (("window_open", "first_start"), ("window_close", "first_end"),
                        ("registration_deadline", "registration_deadline")):
        d = first if field == "window_open" else choose("dates", role, field)
        t = choose("times", role, field)
        if d is None and t is not None and field == "window_close":
            d = first
        if d is None:
            if t:
                flags.append(f"needs_review:{field}")
            else:
                put(field, None, [])
            continue
        # Candidate IDs are frozen with the recorded replies, so a date candidate inside a
        # same-month day range ("06-08/11/2026" seen as "06-08") is read through the whole range.
        for left, right in ranges:
            if d.start < right and left < d.end:
                d = replace(d, text=pre.text[left:right], start=left, end=right)
                break
        try:
            point = parse_point(d.text + (" " + t.text if t else ""), posted,
                                pick="first" if field == "window_open" else "last")
        except DateParseError:
            flags.append(f"needs_review:{field}")
            continue
        put(field, precision(point.value, point.defaulted), [d, t])
        if point.year_from_posted:
            inferred.append(field)
    for field, role in (("registration_url", "registration"), ("join_url", "join")):
        c = choose("urls", role, field)
        put(field, c.text if c else None, [c])
    # multi_session is a closed label supported by the selected schedule mentions.
    evidence["multi_session"] = [s for c in cands if c.kind == "date"
                                 for s in evidence_span(pre, c.start, c.end)]
    return {"record": record, "evidence": evidence, "flags": list(dict.fromkeys(flags)),
            "year_inferred": inferred}


def decide(post, client_or_replies):
    pre = preprocess(post["raw_content"])
    seg = segment(pre)
    cands = build_candidates(pre, seg)
    prompts = {"classify": build_classify_prompt(pre, seg, post),
               "roles": build_roles_prompt(pre, seg, cands, post)}
    result = {"classify": None, "roles": None, "errors": [], "warnings": [], "prompt_versions": dict(PROMPT_VERSIONS),
              "attempts": {}, "values": {"record": {}, "evidence": {}, "flags": [], "year_inferred": []}}
    for kind in prompts:
        recorded = not callable(client_or_replies)
        raw = client_or_replies.get(kind) if recorded else None
        attempts = raw if isinstance(raw, list) else [raw]
        for attempt in range(min(2, len(attempts)) if recorded else 2):
            result["attempts"][kind] = attempt + 1
            try:
                reply = attempts[attempt] if recorded else client_or_replies(prompts[kind] + (
                    "\nReturn only the JSON object with the required keys, enums and every candidate ID exactly once."
                    if attempt else ""))
                warn: list = []
                value = (parse_classify(reply, len(pre.text.split("\n")), strict=False, warnings=warn)
                         if kind == "classify" else parse_roles(reply, cands, strict=False, warnings=warn))
                if kind == "classify" and value["post_type_evidence"] == "H1" and not any(c.id == "H1" for c in cands):
                    raise LLMReplyError("unknown_id")
                result[kind] = value
                result["warnings"].extend({"call": kind, "attempt": attempt + 1, "code": w} for w in warn)
                break
            except Exception as exc:
                result["errors"].append({"call": kind, "attempt": attempt + 1,
                                         "code": exc.code if isinstance(exc, LLMReplyError) else "client_error"})
    if result["roles"] is not None:
        result["values"] = values_from_roles(result["roles"], cands, pre, post.get("date_posted"))
        for field in ("registration_url", "join_url"):
            if result["values"]["record"].get(field) == post.get("url"):
                result["values"]["record"].pop(field)
                result["values"]["evidence"].pop(field, None)
                result["values"]["flags"].append(f"needs_review:{field}")
    result["values"]["flags"] = list(dict.fromkeys(
        result["values"]["flags"] + list(pre.flags) + list(getattr(cands, "flags", []))))
    if result["classify"] is not None:
        classification = result["classify"]
        offsets = []
        start = 0
        for line in pre.text.split("\n"):
            offsets.append((start, start + len(line)))
            start += len(line) + 1

        def support(ref):
            if ref is None:
                return []
            if ref == "H1":
                c = next(c for c in cands if c.id == ref)
                return evidence_span(pre, c.start, c.end)
            return evidence_span(pre, *offsets[int(ref[1:]) - 1])

        for field in ("post_type", "activity_type", "domain", "mode"):
            ref = classification["mode_evidence" if field == "mode" else "post_type_evidence"]
            result["values"]["record"][field] = classification[field] if field != "mode" or ref else None
            result["values"]["evidence"][field] = support(ref)
    return result
