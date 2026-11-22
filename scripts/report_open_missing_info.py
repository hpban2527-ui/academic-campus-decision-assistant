"""List store activities that are open in the demo window but hidden from planning for missing information.

Read-only: it reads data/activity_store_v2.json, data/handover/blocked.json and the real-store feasibility
result, and writes reports/sp1_open_missing_info.md. It fills no value and never edits data/review/decisions.csv;
the report is meant for a manual review.

  python scripts/report_open_missing_info.py

"Open in the demo window": the registration deadline or the start lies between the real demo date
(api.sp3_real.AS_OF) and the end of the semester (api.sp3_real.TERM["end"]). Activities with neither date are
listed in their own section because the window cannot be judged.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api import sp3_real  # noqa: E402

STORE = ROOT / "data" / "activity_store_v2.json"
BLOCKED = ROOT / "data" / "handover" / "blocked.json"
REPORT = ROOT / "reports" / "sp1_open_missing_info.md"

# Reasons that mean information is missing (the rest, e.g. not_an_activity, are not "missing info").
BLOCKED_MISSING = {"missing_mode"}
FEASIBILITY_MISSING = {
    "MISSING_SCHEDULE_TYPE": "schedule type (fixed sessions or flexible window)",
    "MISSING_SCHEDULE": "schedule (start and end)",
    "MISSING_DEADLINE": "registration deadline",
    "MISSING_ELIGIBILITY": "eligibility / audience",
    "MISSING_SCORE_BINDING": "score binding (criterion and points rule)",
}


def day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def missing_fields(activity: dict, has_binding: bool | None) -> list[str]:
    missing = []
    mode = activity.get("mode")
    window = activity.get("window") or {}
    if not mode:
        missing.append("mode (online / offline / hybrid)")
    if not window.get("open"):
        missing.append("start time (window.open)")
    if mode != "online" and not window.get("close") and not activity.get("duration_minutes"):
        missing.append("end time or duration")
    if not activity.get("registration_deadline"):
        missing.append("registration deadline")
    if mode in ("offline", "hybrid") and not activity.get("location"):
        missing.append("location")
    if mode in ("offline", "hybrid") and not activity.get("campus"):
        missing.append("campus")
    if not activity.get("domain"):
        missing.append("domain")
    if has_binding is False:
        missing.append("score binding (criterion and points rule)")
    return missing


def main() -> int:
    records = json.loads(STORE.read_text(encoding="utf-8"))["records"]
    blocked = {item["post_id"]: item["reasons"] for item in json.loads(BLOCKED.read_text(encoding="utf-8"))}
    plan = sp3_real.real_plan("first_plan", target_total=80)
    feasibility = {
        entry["activity"]["activity_id"]: entry["feasibility"]["reason_codes"]
        for entry in plan["feasibility"]["candidates"]
    }
    bound = set(sp3_real._load_base()["binding_by_id"])
    start, end = day(sp3_real.AS_OF), day(sp3_real.TERM["end"])

    in_window: list[dict] = []
    undated: list[dict] = []
    for record in records:
        activity = record["activity"]
        post_id = activity["source"]["post_id"]
        reasons: list[str] = []
        if post_id in blocked:
            reasons = [f"not handed over: {reason}" for reason in blocked[post_id]]
            hidden_for_missing = bool(BLOCKED_MISSING & set(blocked[post_id]))
        else:
            codes = feasibility.get(post_id, [])
            reasons = [f"{code}" for code in codes if code in FEASIBILITY_MISSING]
            hidden_for_missing = bool(reasons)
        if not hidden_for_missing:
            continue
        window = activity.get("window") or {}
        opens, deadline = day(window.get("open")), day(activity.get("registration_deadline"))
        row = {
            "activity_id": post_id,
            "title": activity.get("title") or "(no title)",
            "url": (activity.get("source") or {}).get("URL_post") or "(no URL)",
            "missing": missing_fields(activity, None if post_id in blocked else post_id in bound),
            "reasons": reasons,
            "start": window.get("open"),
            "deadline": activity.get("registration_deadline"),
        }
        dates = [d for d in (opens, deadline) if d is not None]
        if not dates:
            undated.append(row)
        elif any(start <= d <= end for d in dates):
            in_window.append(row)
    in_window.sort(key=lambda row: (row["deadline"] or "9999", row["start"] or "9999", row["activity_id"]))
    undated.sort(key=lambda row: row["activity_id"])

    lines = [
        "# SP1 activities open in the demo window but hidden for missing planning info",
        "",
        "For manual review. Nothing was filled in and `data/review/decisions.csv` was not touched.",
        f"Generated by `scripts/report_open_missing_info.py` from `data/activity_store_v2.json` ({len(records)} records),",
        "`data/handover/blocked.json` and the real-store feasibility check.",
        "",
        f"- Demo window: {start.isoformat()} (demo date `AS_OF`) to {end.isoformat()} (end of {sp3_real.TERM['id']}).",
        "- Open = the registration deadline or the start lies inside that window.",
        "- Hidden = not handed over to SP3, or handed over but `NEEDS_REVIEW` / `INFEASIBLE` with a `MISSING_*` reason.",
        "- \"Missing\" lists fields that are empty in the store record; the reasons column is what the pipeline reported.",
        "- Records hidden only because they are not activities (`not_an_activity`) or fail another check are not listed.",
        "",
        f"## Open in the window ({len(in_window)})",
        "",
    ]

    def block(rows: list[dict]) -> list[str]:
        out: list[str] = []
        for index, row in enumerate(rows, 1):
            out += [
                f"### {index}. {row['title']}",
                "",
                f"- activity_id: `{row['activity_id']}`",
                f"- source URL: {row['url']}",
                f"- start: {row['start'] or 'not stated'} | registration deadline: {row['deadline'] or 'not stated'}",
                f"- missing fields: {', '.join(row['missing']) or 'no empty field in the store; the pipeline cannot use what is there (see reasons)'}",
                f"- reported reasons: {', '.join(row['reasons'])}"
                + "".join(f" ({FEASIBILITY_MISSING[r]})" for r in row["reasons"] if r in FEASIBILITY_MISSING and len(row["reasons"]) == 1),
                "",
            ]
        return out

    lines += block(in_window) or ["None.", ""]
    lines += [
        f"## Window cannot be judged: no start and no registration deadline ({len(undated)})",
        "",
    ]
    lines += block(undated) or ["None.", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_bytes(("\n".join(lines)).encode("utf-8"))
    print(f"wrote {REPORT.relative_to(ROOT)}: {len(in_window)} open in window, {len(undated)} without dates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
