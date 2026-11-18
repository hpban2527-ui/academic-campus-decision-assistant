"""Validate a human-approved AI-assisted review export without changing app or gold data.

Usage: python scripts/validate_ai_review_export.py path/to/unilife_human_reviewed_N.json
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jsonschema import Draft202012Validator
from sp1.activity_type import KEYWORDS
from sp1.devdata import get_post, non_test_ids
from sp1.extract_v2 import FIELDS


def validate_export(path: Path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema") != "unilife-ai-assisted-review/1.0" or data.get("kind") != "human_reviewed_records":
        raise ValueError("Expected a human_reviewed_records export, not AI drafts or progress")
    if data.get("label") != "HUMAN_REVIEWED_AI_ASSISTED_NOT_BLIND_GOLD":
        raise ValueError("Missing explicit AI-assisted review label")
    rows = data.get("items")
    if not isinstance(rows, list) or not rows:
        raise ValueError("No approved records")
    schema = json.loads((ROOT / "schemas/layer_a_record_v2.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema["$defs"]["record"])
    allowed = set(non_test_ids())
    known_types = {name for name, _ in KEYWORDS} | {"other"}
    checked = set(FIELDS) | {"activity_type"}
    seen = set()
    for row in rows:
        pid = row["post_id"]
        if pid not in allowed or pid in seen or row.get("split") == "test":
            raise ValueError(f"Duplicate, unknown or test post ID: {pid}")
        seen.add(pid)
        post = get_post(pid)
        digest = hashlib.sha256(post["raw_content"].replace("\r\n", "\n").replace("\r", "\n").encode()).hexdigest()
        if row.get("source_sha256") != digest:
            raise ValueError(f"Source changed: {pid}")
        text = row.get("source_text", "")
        if hashlib.sha256(text.encode()).hexdigest() != row.get("review_text_sha256"):
            raise ValueError(f"Review source text changed: {pid}")
        record = dict(row["record"])
        if record.pop("activity_type", None) not in known_types:
            raise ValueError(f"Invalid activity type: {pid}")
        validator.validate(record)
        for field in ("window_open", "window_close", "registration_deadline"):
            if record[field]:
                datetime.fromisoformat(record[field])
        for item in record["completion_requirements"]:
            if item["deadline"]:
                datetime.fromisoformat(item["deadline"])
        review = row.get("review", {})
        if (review.get("status") != "approved" or not str(review.get("reviewer") or "").strip()
                or set(review.get("checked_fields", [])) != checked):
            raise ValueError(f"Human approval is incomplete: {pid}")
        moment = datetime.fromisoformat(review.get("reviewed_at", "").replace("Z", "+00:00"))
        if moment.utcoffset() is None:
            raise ValueError(f"Approval timestamp has no timezone: {pid}")
        for field, quotes in row.get("evidence", {}).items():
            if field not in checked or not isinstance(quotes, list) or any(not q or q not in text for q in quotes):
                raise ValueError(f"Invalid evidence: {pid}/{field}")
        for field, value in row["record"].items():
            present = value not in (None, "", [], {}) and value != {"cohorts": [], "programs": []}
            if present and not row.get("evidence", {}).get(field):
                raise ValueError(f"Missing evidence: {pid}/{field}")
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        count = validate_export(args.path)
    except (ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Invalid review export: {exc}\n")
    print(f"Validated {count} human-approved AI-assisted records; application and gold data unchanged.")
