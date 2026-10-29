"""Lead-owned SP1 publication contract and review gate.

Drafts are evidence-bearing 15-field extractor outputs. The published activity
contract has exactly 14 fields. No draft is approved automatically.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ACTIVITY_FIELDS = (
    "activity_id", "source", "title", "domain", "start", "end",
    "registration_deadline", "mode", "location", "points", "mandatory",
    "audience", "fee", "completion_requirements",
)
DOMAINS = {"academic", "volunteer", "culture_sports", "skills", "career", "other"}
MODES = {"online", "offline", "hybrid"}
TRACKING_KEYS = {"rdid", "fbclid", "gclid", "mibextid", "ref", "refsrc"}


def canonical_url(value: str) -> str:
    """Strip mutable tracking parameters without inventing a destination URL."""
    if not isinstance(value, str):
        raise ValueError("URL_post must be a string")
    u = urlsplit(value.strip())
    if u.scheme not in {"https", "http"} or not u.netloc:
        raise ValueError("URL_post must be a valid http(s) URL")
    query = [
        (key, val) for key, val in parse_qsl(u.query, keep_blank_values=True)
        if key.lower() not in TRACKING_KEYS and not key.lower().startswith("utm_")
    ]
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/") or "/", urlencode(query), ""))


def _iso_datetime(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def prepare_publication(draft: dict) -> dict:
    """Convert extractor draft to reviewable 14-field candidate.

    Group decision: absent mandatory -> false, absent fee -> 0. These are
    explicit policy defaults, never inferred factual claims from the post.
    An unapproved record always stays in the review queue.
    """
    if not isinstance(draft, dict) or not isinstance(draft.get("record"), dict):
        raise ValueError("Expected {record, meta} extractor draft")
    record = deepcopy(draft["record"])
    meta = deepcopy(draft.get("meta") or {})
    flags = list(meta.get("flags") or [])
    derived = dict(meta.get("derived") or {})
    source = record.get("source")
    if not isinstance(source, dict):
        raise ValueError("record.source must be an object")
    url = canonical_url(source.get("URL_post"))
    source["URL_post"] = url
    if not record.get("activity_id") or str(record["activity_id"]).startswith("TMP-"):
        record["activity_id"] = "ACT-" + sha256(url.encode("utf-8")).hexdigest()[:12].upper()
    if record.get("mandatory") is None:
        record["mandatory"] = False
        derived["mandatory"] = "group_default_false_when_unstated"
    if record.get("fee") is None:
        record["fee"] = 0
        derived["fee"] = "group_default_zero_when_unstated"
    drl_recognized = record.pop("drl_recognized", None)
    meta["drl_recognized"] = drl_recognized
    meta["derived"] = derived
    if record.get("mode") not in MODES:
        flags.append("needs_review:mode")
    if not isinstance(record.get("title"), str) or not record["title"].strip():
        flags.append("needs_review:title")
    if not isinstance(record.get("completion_requirements"), str):
        flags.append("needs_review:completion_requirements")
    if record.get("domain") not in DOMAINS | {None}:
        flags.append("invalid_value:domain")
    if type(record.get("mandatory")) is not bool:
        flags.append("invalid_value:mandatory")
    if type(record.get("fee")) not in (int, float) or record["fee"] < 0:
        flags.append("invalid_value:fee")
    if record.get("points") is not None and (
        type(record["points"]) not in (int, float) or record["points"] < 0
    ):
        flags.append("invalid_value:points")
    if record.get("audience") is not None and (
        not isinstance(record["audience"], list)
        or any(not isinstance(item, str) for item in record["audience"])
    ):
        flags.append("invalid_value:audience")
    for field in ("start", "end", "registration_deadline"):
        if not _iso_datetime(record.get(field)):
            flags.append("invalid_value:" + field)
    if _iso_datetime(record.get("start")) and _iso_datetime(record.get("end")):
        if record.get("start") and record.get("end"):
            if datetime.fromisoformat(record["end"].replace("Z", "+00:00")) <= datetime.fromisoformat(record["start"].replace("Z", "+00:00")):
                flags.append("invalid_value:end")
    if record.get("mode") == "online" and record.get("location"):
        flags.append("invalid_value:online_location")
    if record.get("location") is not None and not isinstance(record["location"], str):
        flags.append("invalid_value:location")
    if set(record) != set(ACTIVITY_FIELDS):
        flags.append("invalid_value:activity_contract")
    if set(source) != {"publisher", "platform", "URL_post", "URL_registration"}:
        flags.append("invalid_value:source")
    # Regex can accidentally treat quoted older notices, registration dates,
    # anniversaries or decision numbers as the actual event schedule (P08).
    # Flag unlabelled date evidence, even when the extractor returns "valid".
    evidence = meta.get("evidence") or {}
    if isinstance(evidence, dict):
        for key in ("start", "end"):
            proof = evidence.get(key)
            if isinstance(proof, list) and proof:
                flag_terms = ("theo thông báo ngày", "căn cứ nghị quyết", "căn cứ kế hoạch",
                              "đăng ký tham dự:", "đăng ký", "các mốc thời gian")
                joined = " ".join(str(v).casefold() for v in proof)
                if any(term in joined for term in flag_terms):
                    flags.append("needs_review:" + key + "_date_provenance")
    reg_url = source.get("URL_registration")
    if reg_url is not None:
        if not isinstance(reg_url, str) or "..." in reg_url:
            flags.append("needs_review:URL_registration")
        elif urlsplit(reg_url).scheme not in {"http", "https"} or not urlsplit(reg_url).netloc:
            flags.append("needs_review:URL_registration")
    meta["flags"] = sorted(set(flags))
    # The source extractor has known unflagged date errors on its validation set:
    # a "valid" draft must not bypass human review.
    meta["publication_status"] = "REVIEW_REQUIRED"
    meta["review_reason"] = "human source verification required before publication or DRL attribution"
    meta["routed_to"] = "review_queue"
    return {"record": {k: record.get(k) for k in ACTIVITY_FIELDS}, "meta": meta}


def audit_dataset(rows: list[dict]) -> dict:
    """Read-only lightweight quality audit for collector-labelled activities."""
    if not isinstance(rows, list):
        raise ValueError("activities must be a list")
    missing_mode = [r.get("activity_id") for r in rows if r.get("mode") not in MODES]
    missing_completion = [r.get("activity_id") for r in rows if not isinstance(r.get("completion_requirements"), str)]
    urls = [canonical_url(r["source"]["URL_post"]) for r in rows if isinstance(r.get("source"), dict) and r["source"].get("URL_post")]
    return {
        "total": len(rows),
        "missing_mode": len(missing_mode),
        "missing_completion_requirements": len(missing_completion),
        "unique_canonical_urls": len(set(urls)),
        "needs_review_ids": list(dict.fromkeys(missing_mode + missing_completion)),
    }
