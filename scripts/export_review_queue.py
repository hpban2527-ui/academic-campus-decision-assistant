"""Export the human review queue: every record that is not fully usable, with the reason and current values.

Output: data/review/queue.csv (opens in Excel). To record decisions, fill the decision columns
(reviewer, reviewed_at, set_*, approve, note) and save the rows as data/review/decisions.csv; then rebuild
the store, the handover and the bindings. Run after build_activity_store, build_handover and build_bindings.
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.normalize import _has_token, _location_key, load_config
from sp1.review import DECISION_COLUMNS

CURRENT = ("post_type", "mode", "window_open", "window_close", "registration_deadline", "location", "campus",
           "activity_type", "matcher_rule")
HINTS = {
    "missing_mode": "set_mode",
    "failed_status": "fix the wrong field with set_*, or approve=yes if the record is correct",
    "not_an_activity": "set_post_type=activity if it is an activity students can join",
    "fee_not_per_person": "not fixable in this file yet",
    "sources_disagree": "set_rule_id (or set_activity_type)",
    "activity_type_not_auto_bound": "set_rule_id (or set_activity_type)",
    "source_not_auto_verified": "approve=yes after checking the flagged fields",
    "start_time_not_stated": "set_window_open with a time if the post or organiser gives one",
    "schedule_type_unknown": "multi-day offline activity: not fixable in this file yet",
    "campus_unknown": "set_location with the venue as the post words it; the campus follows the dictionary",
    "campus_conflict": "set_location with the correct venue: one address matched both campuses",
    "audience_check": "the audience names school teachers: confirm students may join, else set_post_type=info_only",
}


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main():
    store = read("data/activity_store_v2.json")["records"]
    sidecar = read("data/handover/sidecar.json")["activities"]
    blocked = {b["post_id"]: b["reasons"] for b in read("data/handover/blocked.json")}
    bindings = read("data/handover/bindings.json")
    explanations = bindings["explanations"]
    config = load_config()
    rows, counts = [], Counter()
    for record in store:
        a = record["activity"]
        pid = aid = a["source"]["post_id"]        # D19: the handed-over id is the post_id
        reasons = [r for r in blocked.get(pid, []) if r != "duplicate"]
        if "not_an_activity" in reasons and a["post_type"] == "info_only":
            continue                                    # a plain notice: nothing to review
        explanation = explanations.get(aid, {})
        if aid in sidecar:
            if explanation.get("reason") not in ("sources_agree", "reviewer_decision"):
                reasons.append(explanation.get("reason", "no_binding"))
            if a["meta"]["status"] != "valid":
                reasons.append("source_not_auto_verified")
            if "window_open" in a["meta"]["time_defaults"] and a["mode"] != "online":
                reasons.append("start_time_not_stated")
            start, end = a["window"]["open"], a["window"]["close"]
            if a["mode"] in ("offline", "hybrid") and start and end and start[:10] != end[:10]:
                reasons.append("schedule_type_unknown")
        if aid in sidecar and re.search(r"giáo viên", a["audience"].get("text") or "", re.IGNORECASE):
            reasons.append("audience_check")
        campus = a["campus"] or []
        if not campus and a["mode"] in ("offline", "hybrid"):
            reasons.append("campus_unknown")
        elif len(campus) > 1 and not any(_has_token(_location_key(a["location"] or ""), pattern)
                                         for pattern in config.campuses["both"]):
            reasons.append("campus_conflict")        # one address matched CS1 and CS2
        if not reasons:
            continue
        counts.update(reasons)
        review = record.get("review") or {}
        row = dict.fromkeys(DECISION_COLUMNS, "")
        row.update({"post_id": pid, "text_sha256": record["text_sha256"]})
        rows.append({
            "position": record["position"], "URL_post": a["source"]["URL_post"], "title": a["title"] or "",
            "reasons": "; ".join(reasons),
            "how_to_fix": "; ".join(dict.fromkeys(HINTS.get(r.split(":")[0], "see reason") for r in reasons)),
            "flags": "; ".join(a["meta"]["flags"]),
            "already_reviewed_by": "" if not review or review.get("stale") else review.get("reviewer", ""),
            "current_post_type": a["post_type"], "current_mode": a["mode"] or "",
            "current_window_open": a["window"]["open"] or "", "current_window_close": a["window"]["close"] or "",
            "current_registration_deadline": a["registration_deadline"] or "",
            "current_location": (a["location"] or "")[:200], "current_campus": "|".join(campus),
            "current_activity_type": record.get("activity_type") or "",
            "current_matcher_rule": explanation.get("matcher_rule") or "", **row})
    path = ROOT / "data/review/queue.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["position", "URL_post", "title", "reasons", "how_to_fix", "flags", "already_reviewed_by",
               *(f"current_{c}" for c in CURRENT), *DECISION_COLUMNS]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Review queue: {len(rows)} of {len(store)} records -> {path.relative_to(ROOT)}")
    for reason, n in counts.most_common():
        print(f"  {n:3d}  {reason}")


if __name__ == "__main__":
    main()
