"""Import the AI-assisted annotation packet (2026-11-18) into versioned project data.

The packet was produced outside the repository (artifacts/ai_review_20261118/, a delivery folder that is
not tracked). The operational build must not depend on that folder, so this script copies the facts it
needs into data/sp1_annotations/ai_annotations_20261118.json, with the packet's provenance:

  python scripts/import_ai_annotations.py --packet artifacts/ai_review_20261118

Only non-test posts are accepted, every record must be bound to the current source fingerprint, and the
label stays AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD: nothing here is human review or gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.devdata import get_post, load_split  # noqa: E402
from sp1.review import text_fingerprint  # noqa: E402

LABEL = "AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD"
OUT = ROOT / "data/sp1_annotations/ai_annotations_20261118.json"
KEEP = ("post_id", "position", "split", "source_sha256", "record", "evidence_spans", "unsure", "field_notes",
        "notes_codes", "year_inferred", "ai_record", "changed_fields", "ai_unsure")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(packet: Path) -> dict:
    drafts_path = packet / "deliverables/unilife_ai_drafts_129.json"
    drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
    if drafts.get("label") != LABEL or drafts.get("human_approved") is not False:
        raise ValueError("Unexpected packet label: refusing to import anything but unapproved AI drafts")
    split = {row["post_id"]: row for row in load_split()["posts"]}
    items = []
    for item in drafts["items"]:
        row = split.get(item["post_id"])
        if row is None or row["split"] == "test" or item.get("split") == "test":
            raise ValueError(f"{item['post_id']}: unknown or held-out post")
        if text_fingerprint(get_post(item["post_id"])["raw_content"]) != item["source_sha256"]:
            raise ValueError(f"{item['post_id']}: source fingerprint differs from the current corpus")
        if (item.get("review") or {}).get("status") not in (None, "pending"):
            raise ValueError(f"{item['post_id']}: review status is not pending; import human exports separately")
        items.append({key: item.get(key) for key in KEEP})
    return {
        "schema": "unilife-ai-annotations/1.0", "label": LABEL, "human_approved": False,
        "packet_id": drafts["packet_id"], "created_at": drafts["created_at"],
        "acceptance_policy_at_creation": drafts["acceptance_policy"]["version"],
        "description": ("AI-assisted extraction of the 129 non-test posts (19 stated-fact fields, activity type, "
                        "exact evidence spans in preprocessed-text offsets, uncertainty), with a second AI cross-check "
                        "pass (changed_fields). Operational input only: not human review, not gold."),
        "provenance": {"drafts_file": drafts_path.name, "drafts_sha256": sha(drafts_path),
                       "crosscheck_log": "provenance/ai_crosscheck_log.json",
                       "source_manifest": "provenance/source_manifest.json"},
        "items": items,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    data = build(args.packet)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    provenance = args.out.parent / "provenance"
    provenance.mkdir(exist_ok=True)
    for name in ("ai_crosscheck_log.json", "source_manifest.json"):
        shutil.copyfile(args.packet / name, provenance / name)
    print(f"Imported {len(data['items'])} AI annotations -> {args.out.relative_to(ROOT)} (packet {data['packet_id'][:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
