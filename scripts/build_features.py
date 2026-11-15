"""Generate personalization features for the handed-over activities (ADR-0002 D19).

Writes data/handover/activity_features_sp1.json (schema personalization-features/0.1, keyed by post_id, so
personalization.scoring.load_activity_features reads it) and data/handover/features_provenance.json.

Decided 2026-11-14 (D19): the documented rules decide every value, so a value in data/activity_features.json
does not override the rule. That file is still never written here: its own test requires exactly the 20
reviewed activities of data/activities.json, a non-empty topic list and a non-null campus_id. Differences
between the rule and that file are reported in full so its owner can update it.
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.features import LABEL, features

REVIEWED = ROOT / "data/activity_features.json"
OUT = ROOT / "data/handover/activity_features_sp1.json"


def main():
    payload = json.loads(REVIEWED.read_text(encoding="utf-8"))
    catalog, existing = payload["catalog"], payload["activities"]
    store = {r["activity"]["source"]["post_id"]: r
             for r in json.loads((ROOT / "data/activity_store_v2.json").read_text(encoding="utf-8"))["records"]}
    handed = json.loads((ROOT / "data/handover/activities_sp3.json").read_text(encoding="utf-8"))
    generated, differs, counts = {}, [], Counter()
    for activity in handed:
        post_id = activity["activity_id"]                      # D19: the handed-over id is the post_id
        record = store[post_id]
        value = features(record["activity"], record.get("activity_type"))
        for field in ("topics", "time_tags"):
            counts[f"{field}_empty"] += not value[field]
        counts["campus_unknown"] += value["campus_id"] is None
        if post_id in existing and existing[post_id] != value:
            differs.append({"post_id": post_id, "in_activity_features_json": existing[post_id],
                            "rule_value_used": value})
        generated[post_id] = value
    merged = generated                                      # the rules decide (D19)
    for value in merged.values():
        unknown = (set(value["topics"]) - set(catalog["topics"])) | (set(value["time_tags"]) - set(catalog["time_slots"]))
        if unknown or (value["campus_id"] is not None and value["campus_id"] not in catalog["campuses"]):
            raise ValueError(f"value outside the catalog: {value}")
    out = {"schema_version": payload["schema_version"], "catalog": catalog, "label": LABEL,
           "source": "data/activity_store_v2.json via scripts/build_features.py; reviewed entries from "
                     "data/activity_features.json are copied unchanged",
           "activities": {key: merged[key] for key in sorted(merged)}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    (ROOT / "data/handover/features_provenance.json").write_bytes((json.dumps({
        "schema": "sp1-features-provenance/1.0", "label": LABEL,
        "note": "Every value in the output file is derived by the documented rules (D19), including for the "
                "activities that also appear in data/activity_features.json. The differences list shows where "
                "that file says something else, for its owner to reconcile. That file is never written here, "
                "and no value here is human reviewed.",
        "output_file": str(OUT.relative_to(ROOT)),
        "policy": "rules_decide",
        "also_in_activity_features_json": sorted(set(existing) & set(generated)),
        "reviewed_not_handed_over": sorted(set(existing) - set(generated)),
        "generated_by_sp1": sorted(set(generated) - set(existing)),
        "needs_review": {"no_topic": sorted(k for k, v in merged.items() if not v["topics"]),
                         "campus_not_determined": sorted(k for k, v in merged.items() if v["campus_id"] is None)},
        "differences_vs_activity_features_json": differs}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"{OUT.relative_to(ROOT)}: {len(merged)} activities, all derived by rule; "
          f"{len(set(existing) & set(generated))} of them also appear in data/activity_features.json.")
    print(f"Generated values with no topic: {counts['topics_empty']}; no time tag: {counts['time_tags_empty']}; "
          f"campus not determined: {counts['campus_unknown']}.")
    if differs:
        print(f"Kept entries that differ from the generated value: {len(differs)} (see features_provenance.json)")


if __name__ == "__main__":
    main()
