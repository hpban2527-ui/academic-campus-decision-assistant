"""Build the SP3 handover from the SP1 v2 store: 14-field activities, sidecar, rule-based evidence, report.

Outputs:
  data/handover/activities_sp3.json    activities accepted by the SP3 v0.2 activity contract
  data/handover/sidecar.json           per activity: provenance, team defaults used, warnings, schedule evidence
  data/handover/blocked.json           records not handed over, with reasons
  reports/sp1_handover_readiness.md    counts
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.handover import AUTO_CHECK_LABEL, auto_evidence, project

DEMO_PROFILE = {"cohort": "K24", "program": "standard"}   # synthetic, no real student
DEMO_TERM = "HK1_2026_2027"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def main():
    store = json.loads((ROOT / "data/activity_store_v2.json").read_text(encoding="utf-8"))
    items = [(record, project(record)) for record in store["records"]]
    passed = [p for _, p in items if p["activity"]]
    evidence = auto_evidence(passed, DEMO_PROFILE, DEMO_TERM)
    write(ROOT / "data/handover/activities_sp3.json", [p["activity"] for p in passed])
    write(ROOT / "data/handover/sidecar.json", {
        "schema": "sp1-handover-sidecar/1.0", "store_generated_at": store["generated_at"],
        "evidence_label": AUTO_CHECK_LABEL, "demo_profile": DEMO_PROFILE, "demo_term": DEMO_TERM,
        "demo_evidence": evidence,
        "activities": {p["activity"]["activity_id"]: {**p["sidecar"], "derived": p["derived"],
                                                      "warnings": p["warnings"]} for p in passed}})
    write(ROOT / "data/handover/blocked.json", [
        {"position": r["position"], "post_id": r["activity"]["source"]["post_id"], "reasons": p["blocked"]}
        for r, p in items if not p["activity"]])
    blocked = Counter(reason for _, p in items for reason in p["blocked"])
    derived = Counter(key for p in passed for key in p["derived"])
    warnings = Counter(w for p in passed for w in p["warnings"])
    n = len(items)
    lines = ["# SP1 -> SP3 handover readiness", "",
             f"Store records: {n}. Handed over (accepted by the 14-field SP3 v0.2 activity contract): {len(passed)}/{n}.",
             "Structural counts, not accuracy. Evidence below is rule-based and labelled "
             f"`{AUTO_CHECK_LABEL}`; it is not human review.", "",
             "| Not handed over: reason (may overlap) | Records |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in sorted(blocked.items())]
    lines += ["", "| Team default or convention applied | Activities |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in sorted(derived.items())]
    lines += ["", "| Warning kept in the sidecar | Activities |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in sorted(warnings.items())]
    lines += ["", f"## Rule-based evidence for the demo profile {DEMO_PROFILE} and term {DEMO_TERM}", ""]
    for key in ("eligibility_by_activity", "term_scope_by_activity", "source_review_by_activity"):
        lines.append(f"- {key}: {dict(Counter(str(v) for v in evidence[key].values()))}")
    lines.append(f"- schedule evidence (online flexible window): {len(evidence['schedule_by_activity'])}")
    (ROOT / "reports/sp1_handover_readiness.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
