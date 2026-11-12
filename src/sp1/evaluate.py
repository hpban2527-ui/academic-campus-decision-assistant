"""Evaluate SP1 drafts against hand-labelled gold activities, field by field.

Gold file: a JSON array of {"post_id": str, "activities": [activity, ...]}. An activity holds the record
fields except activity_id, with source reduced to {"URL_registration": ...}. A null value means the post
does not state it; a field left out means "not labelled" and is not scored. Format: docs/sp1_extractor.md.

Only the first gold activity and the first predicted draft of a post are compared (multi-activity
matching is out of scope); the report counts the posts that have more than one.

CLI (regex path):
    python -m sp1.evaluate --posts data/raw/posts.json --gold data/gold/gold.json --out reports/sp1_eval.md
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from typing import Any

from .extractor import run_posts

FIELDS = (
    "URL_registration", "title", "domain", "start", "end", "registration_deadline", "mode", "location",
    "points", "drl_recognized", "mandatory", "audience", "fee", "completion_requirements",
)
DATETIME_FIELDS = {"start", "end", "registration_deadline"}
OUTCOMES = ("correct", "wrong", "fabricated", "missed")
Z_95 = 1.96


class GoldError(ValueError):
    """The gold file does not follow the gold format."""


def _flat(activity: dict[str, Any]) -> dict[str, Any]:
    """Record or gold activity -> {field: value}, with URL_registration taken out of source."""
    out = {k: v for k, v in activity.items() if k not in ("activity_id", "source")}
    if "URL_registration" in activity.get("source", {}):
        out["URL_registration"] = activity["source"]["URL_registration"]
    return out


def load_gold(data: Any) -> dict[str, list[dict[str, Any]]]:
    """Check the gold format; return post_id -> flattened gold activities."""
    if not isinstance(data, list):
        raise GoldError("gold must be a JSON array")
    allowed = (set(FIELDS) - {"URL_registration"}) | {"source"}
    gold: dict[str, list[dict[str, Any]]] = {}
    for i, item in enumerate(data):
        if not isinstance(item, dict) or set(item) != {"post_id", "activities"}:
            raise GoldError(f"item {i}: expected exactly the keys post_id and activities")
        pid, acts = item["post_id"], item["activities"]
        if not isinstance(pid, str) or not pid.strip():
            raise GoldError(f"item {i}: post_id must be a non-empty string")
        if pid in gold:
            raise GoldError(f"duplicate post_id {pid!r}")
        if not isinstance(acts, list) or not all(isinstance(a, dict) for a in acts):
            raise GoldError(f"{pid}: activities must be a list of objects")
        for a in acts:
            if set(a) - allowed:
                raise GoldError(f"{pid}: unknown fields {sorted(set(a) - allowed)}")
            if not isinstance(a.get("source", {}), dict) or set(a.get("source", {})) - {"URL_registration"}:
                raise GoldError(f"{pid}: source may only hold URL_registration")
        gold[pid] = [_flat(a) for a in acts]
    return gold


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().casefold()


def _canon(field: str, v: Any) -> Any:
    if v is None or field in DATETIME_FIELDS:
        return v                                   # datetimes compared exactly
    if isinstance(v, bool):
        return ("bool", v)                         # so that True never equals 1
    if isinstance(v, str):
        return _norm_text(v)
    if isinstance(v, list):
        return frozenset(_norm_text(x) if isinstance(x, str) else x for x in v)
    return v                                       # numbers: 3 == 3.0


def outcome(field: str, predicted: Any, gold: Any) -> str:
    """One of correct / wrong / fabricated / missed for a predicted value against its gold value."""
    if predicted is None and gold is None:
        return "correct"
    if predicted is None:
        return "missed"
    if gold is None:
        return "fabricated"
    return "correct" if _canon(field, predicted) == _canon(field, gold) else "wrong"


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n (nan, nan when n = 0)."""
    if n == 0:
        return math.nan, math.nan
    p, d = k / n, 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def evaluate(posts: list[Any], gold: dict[str, list[dict[str, Any]]], **extract_kwargs: Any) -> dict[str, Any]:
    """Run the extractor on posts and score the first draft of every gold post."""
    results = {r["post_id"]: r for r in run_posts(posts, **extract_kwargs)}
    fields = {f: Counter() for f in FIELDS}
    status: Counter = Counter()
    errors: list[dict[str, Any]] = []
    multi_gold = multi_pred = 0
    scored = [pid for pid in gold if pid in results]
    for pid in scored:
        drafts = results[pid].get("drafts", [])
        multi_gold += len(gold[pid]) > 1
        multi_pred += len(drafts) > 1
        status[drafts[0]["meta"]["status"] if drafts else
               ("input_error" if "error" in results[pid] else "no_draft")] += 1
        pred = _flat(drafts[0]["record"]) if drafts else {}
        expected = gold[pid][0] if gold[pid] else dict.fromkeys(FIELDS)   # no activity: everything null
        for f in FIELDS:
            if f not in expected:
                continue                                                  # not labelled
            o = outcome(f, pred.get(f), expected[f])
            fields[f][o] += 1
            if o != "correct":
                errors.append({"post_id": pid, "field": f, "outcome": o,
                               "predicted": pred.get(f), "gold": expected[f]})
    return {
        "n_posts": len(scored),
        "gold_posts_missing": [pid for pid in gold if pid not in results],
        "posts_without_gold": sum(1 for pid in results if pid not in gold),
        "multi_gold": multi_gold,
        "multi_predicted": multi_pred,
        "fields": {f: dict(c) for f, c in fields.items()},
        "status": dict(status),
        "errors": errors,
    }


def _cell(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False).replace("|", "\\|")


def _field_rows(report: dict[str, Any]) -> list[str]:
    rows = []
    for f in FIELDS:
        c = report["fields"][f]
        n = sum(c.get(o, 0) for o in OUTCOMES)
        if n == 0:
            rows.append(f"| {f} | 0 | 0 | 0 | 0 | 0 | n/a | n/a |")
            continue
        lo, hi = wilson(c.get("correct", 0), n)
        counts = " | ".join(str(c.get(o, 0)) for o in OUTCOMES)
        rows.append(f"| {f} | {n} | {counts} | {c.get('correct', 0) / n:.2f} | {lo:.2f}–{hi:.2f} |")
    return rows


def summary(report: dict[str, Any]) -> str:
    """Markdown summary of a report: post counts and the per-field table."""
    lines = [
        f"Posts scored: {report['n_posts']}"
        f" (gold posts missing from the posts file: {len(report['gold_posts_missing'])};"
        f" posts without gold: {report['posts_without_gold']})",
        f"Posts with more than one gold activity: {report['multi_gold']};"
        f" with more than one predicted draft: {report['multi_predicted']} (only the first of each is compared)",
        "",
        "| field | n | correct | wrong | fabricated | missed | accuracy | 95% Wilson CI |",
        "|---|---|---|---|---|---|---|---|",
        *_field_rows(report),
    ]
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    """Full markdown report: summary, draft status counts, and every value that is not correct."""
    lines = ["# SP1 extraction evaluation", "", summary(report), "",
             "## Draft status (first draft per post)", "", "| status | posts |", "|---|---|"]
    lines += [f"| {s} | {n} |" for s, n in sorted(report["status"].items())]
    if report["gold_posts_missing"]:
        lines += ["", "Gold posts missing from the posts file: " + ", ".join(report["gold_posts_missing"])]
    lines += ["", "## Wrong, fabricated and missed values", ""]
    if report["errors"]:
        lines += ["| post_id | field | outcome | predicted | gold |", "|---|---|---|---|---|"]
        lines += [f"| {e['post_id']} | {e['field']} | {e['outcome']} | {_cell(e['predicted'])} | {_cell(e['gold'])} |"
                  for e in report["errors"]]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score SP1 regex extraction against gold activities.")
    ap.add_argument("--posts", required=True, help="collector posts file (JSON array of posts)")
    ap.add_argument("--gold", required=True, help="gold file (JSON array of {post_id, activities})")
    ap.add_argument("--out", required=True, help="markdown report to write")
    args = ap.parse_args(argv)

    with open(args.posts, encoding="utf-8") as f:
        posts = json.load(f)
    with open(args.gold, encoding="utf-8") as f:
        gold = load_gold(json.load(f))
    report = evaluate(posts, gold)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    print(summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
