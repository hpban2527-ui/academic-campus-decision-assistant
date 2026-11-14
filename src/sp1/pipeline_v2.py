"""Per-post SP1 v2 processing shared by the batch store build and incremental ingestion.

One announcement goes through the same steps everywhere: rules extraction, the LLM decision
(recorded replies or a live client), the hybrid merge under the merge policy, an optional human
review decision, normalisation and the plannability check. scripts/build_activity_store.py runs
this for the frozen 189-post dataset; sp1.live_ingest runs it for new posts one at a time.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from .extract_v2 import extract_v2
from .hybrid import merge
from .normalize import normalize
from .preprocess import original_span, preprocess
from .review import apply_decision, text_fingerprint

MASKS = {"phone": "[phone removed]", "account": "[account removed]"}
# Hashes and identifiers are not text: a hex digest such as "...0010671451..." looks like a phone number.
_NOT_TEXT = {"text_sha256", "post_id", "activity_id"}


def redact(value):
    """Mask contact details (phones, account numbers) in every text value, as the store writer does."""
    if isinstance(value, dict):
        return {key: item if key in _NOT_TEXT else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        pre = preprocess(value)
        for start, end, kind in reversed(pre.masked):
            left, right = original_span(pre, start, end)
            value = value[:left] + MASKS[kind] + value[right:]
    return value


def post_source(post: dict) -> dict:
    """Source metadata of a post in the store's shape."""
    source = {key: post.get(key) for key in ("post_id", "publisher", "platform", "date_posted")}
    source["URL_post"] = post["url"]
    return source


def plannability(activity: dict, config) -> tuple[list[str], str]:
    start = activity["window"]["open"]
    day = date.fromisoformat(start[:10]) if start else None
    semester = next((key for left, right, key in config.semesters["standard"] if day and left <= day <= right),
                    "out_of_scope_semester" if day else "insufficient_data")
    fails = [key for key, fail in (("post_type", activity["post_type"] != "activity"), ("window_open", not start),
             ("mode", activity["mode"] is None),
             ("semester", semester in {"out_of_scope_semester", "insufficient_data"}),
             ("failed_status", activity["meta"]["status"] == "failed")) if fail]
    return fails, semester


def process_post(post: dict, decision: dict | None, policy: dict, config, review_decision: dict | None = None) -> dict:
    """Build one store record (without position/split) for a post.

    decision is sp1.llm_v2.decide() output, or None when no LLM output exists (rules only).
    Returns {"record": ..., "per_method": {"rules"|"hybrid": (activity, fails, semester)}}; per_method
    is the pre-review extraction-only comparison used by the readiness report.
    """
    source = post_source(post)
    rules = extract_v2(post)
    hybrid = merge(rules, decision, policy)
    # The rules-vs-hybrid comparison must measure extraction only, so it uses the pre-review layer A.
    before_review = deepcopy(hybrid["layer_a"])
    review = apply_decision(hybrid["layer_a"], review_decision, post["raw_content"])   # review wins
    activity_type = hybrid["classification"]["activity_type"]
    if review and not review["stale"] and review["activity_type"]:
        activity_type = review["activity_type"]
    per_method = {}
    for method, layer_a in (("rules", rules["layer_a"]), ("hybrid", before_review)):
        activity = normalize(layer_a, source, config)
        per_method[method] = (activity, *plannability(activity, config))
    activity = normalize(hybrid["layer_a"], source, config)
    fails, semester = plannability(activity, config)
    record = {"activity": activity, "activity_type": activity_type, "review": review,
              "text_sha256": text_fingerprint(post["raw_content"]),
              "semester": semester, "plannable": not fails, "not_plannable_reasons": fails,
              "plannable_before_review": not per_method["hybrid"][1],
              "field_methods": hybrid.get("field_methods", {}),
              "llm_warnings": (decision or {}).get("warnings", []),
              "llm_available": decision is not None}
    return {"record": record, "per_method": per_method}
