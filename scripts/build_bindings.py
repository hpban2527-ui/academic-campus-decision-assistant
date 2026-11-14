"""Propose SP2 score bindings for the handed-over activities (policy: two sources agree, else review).

Needs the SP2 rule matcher and the verified rule catalog. Until the branches are integrated, pass the
files from the SP2/SP3 branch with --matcher and --rules.

Outputs data/handover/bindings.json and reports/sp2_binding_readiness.md.
"""

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.devdata import final_run_posts


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matcher", type=Path, default=ROOT / "src/sp2/rule_matcher.py")
    parser.add_argument("--rules", type=Path, default=ROOT / "data/drl_rules.json")
    parser.add_argument("--reason", required=True, help="Logged: announcement text of all posts is read")
    args = parser.parse_args(argv)
    if not args.matcher.exists():
        parser.error(f"{args.matcher} not found: pass --matcher from the SP2 branch")
    matcher = load_module("sp2_rule_matcher_loaded", args.matcher)
    binding = load_module("sp2_binding_loaded", ROOT / "src/sp2/binding.py")
    rules_config = json.loads(args.rules.read_text(encoding="utf-8"))
    rules = {r["rule_id"]: r for r in rules_config["rules"]}
    activities = json.loads((ROOT / "data/handover/activities_sp3.json").read_text(encoding="utf-8"))
    sidecar = json.loads((ROOT / "data/handover/sidecar.json").read_text(encoding="utf-8"))["activities"]
    texts = {p["post_id"]: p["raw_content"] for p in final_run_posts(args.reason)}
    results = []
    for activity in activities:
        side = sidecar[activity["activity_id"]]
        match = matcher.match_activity_to_rule(activity, texts[side["post_id"]], rules_config).as_dict()
        results.append(binding.propose_binding(activity["activity_id"], side.get("activity_type"), match, rules))
    bound = [r for r in results if r["binding"]]
    out = {"schema": "sp2-bindings/1.0", "label": binding.LABEL, "policy": binding.POLICY,
           "type_rules": {k: list(v) for k, v in binding.TYPE_RULES.items()},
           "ruleset_file": args.rules.name, "n_activities": len(results),
           "bindings": [r["binding"] for r in bound],
           "explanations": {r["activity_id"]: {k: r[k] for k in ("activity_type", "matcher_rule", "matcher_method",
                                                                 "reason", "category_id", "points_from_rules")
                                               if k in r} for r in results}}
    path = ROOT / "data/handover/bindings.json"
    path.write_bytes((json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    by_rule = Counter(r["binding"]["rule_id"] for r in bound)
    reasons = Counter(r["reason"] for r in results if not r["binding"])
    lines = ["# SP2 binding readiness", "",
             f"Activities handed over: {len(results)}. Bindings proposed: {len(bound)}/{len(results)}.",
             f"Policy: {binding.POLICY} (SP1 activity type and the SP2 rule matcher must name the same rule).",
             f"Label: `{binding.LABEL}`. Points come from the rule catalog only. Not a measure of correctness:",
             "no labelled activity-to-rule data exists yet.", "",
             "| Rule | Category | Points per rule catalog | Bindings |", "| --- | --- | ---: | ---: |"]
    lines += [f"| {rid} | {rules[rid]['category_id']} | {rules[rid]['points']} | {n} |" for rid, n in sorted(by_rule.items())]
    lines += ["", "| Sent to review: reason | Activities |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in sorted(reasons.items())]
    (ROOT / "reports/sp2_binding_readiness.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
