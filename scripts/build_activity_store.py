"""Build the SP1 v2 activity store for all posts from the final LLM run (rules + hybrid merge + normalize).

Outputs:
  data/activity_store_v2.json          hybrid activities, contact-redacted, with field methods and flags
  reports/sp1_final_readiness.md       plannable rate, rules vs hybrid, per split group, Wilson 95% CI
  --sample-out CSV                     optional: 20 seeded activities for a non-blind manual check

Reading test posts goes through devdata.final_run_posts(), so a --reason is required and logged.
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.dedup_v2 import apply_duplicates
from sp1.devdata import final_run_posts, load_split
from sp1.evaluate import wilson
from sp1.llm_v2 import PROMPT_VERSIONS, decide
from sp1.normalize import load_config
from sp1.activity_type import KEYWORDS
from sp1.pipeline_v2 import MASKS, plannability, process_post, redact  # noqa: F401  (re-exported)
from sp1.review import load_decisions

SAMPLE_SEED = 20261114
GROUPS = {"dev": {"dev_gold", "dev_extra"}, "pool": {"pool"}, "test": {"test"}}


def load_llm(path, model_id, allowed):
    rows = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        where = f"{Path(path).name}:{number}"
        if row.get("post_id") not in allowed:
            raise ValueError(f"Unknown post at {where}")
        if row.get("prompt_versions") != PROMPT_VERSIONS:
            raise ValueError(f"Prompt version mismatch at {where}")
        if row.get("model_id") != model_id:
            raise ValueError(f"Model {row.get('model_id')} at {where} is not the policy model {model_id}")
        if row["post_id"] in rows:
            raise ValueError(f"Duplicate post at {where}")
        if not isinstance(row.get("replies"), dict):
            raise ValueError(f"Missing replies at {where}")
        rows[row["post_id"]] = row
    return rows


def ci(k, n):
    if not n:
        return "n/a"
    low, high = wilson(k, n)
    return f"{k}/{n} = {k / n:.1%} [{low:.1%}, {high:.1%}]"


def build(llm_path, policy_path, reason, out_dir, allow_partial=False, access_log=None, decisions_path=None):
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    model_id = policy.get("_model_id")
    if not model_id:
        raise ValueError("Policy has no _model_id")
    split = {row["post_id"]: row for row in load_split()["posts"]}
    posts = final_run_posts(reason, log_path=access_log)
    llm = load_llm(llm_path, model_id, split.keys())
    missing = [p["post_id"] for p in posts if p["post_id"] not in llm]
    if missing and not allow_partial:
        raise ValueError(f"{len(missing)} posts have no LLM output; rerun or pass --allow-partial")
    config = load_config()
    rules_path = ROOT / "data/drl_rules.json"
    rule_ids = ({r["rule_id"] for r in json.loads(rules_path.read_text(encoding="utf-8"))["rules"]
                 if r.get("status") == "verified"} if rules_path.exists() else set())
    activity_types = {(k[0] if isinstance(k, tuple) else k) for k in KEYWORDS} | {"other"}
    decisions, decision_problems = load_decisions(decisions_path or ROOT / "data/review/decisions.csv",
                                                  activity_types, rule_ids)
    unknown = sorted(set(decisions) - set(split))
    decision_problems += [{"line": None, "post_id": pid, "problem": "unknown post_id"} for pid in unknown]
    store, rows = [], []
    for post in posts:
        pid = post["post_id"]
        decision = decide(post, llm[pid]["replies"]) if pid in llm else None
        result = process_post(post, decision, policy, config, decisions.get(pid))
        store.append({"position": split[pid]["position"], "split": split[pid]["split"], **result["record"]})
        rows.append((split[pid]["split"], result["per_method"]))
    dedup = apply_duplicates(store, {p["post_id"]: p["raw_content"] for p in posts})
    out_dir = Path(out_dir)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)
    meta = {"schema": "sp1-activity-store/2.0", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_id": model_id, "prompt_versions": PROMPT_VERSIONS, "merge_policy": policy,
            "llm_file": Path(llm_path).name, "n_posts": len(store), "n_without_llm": len(missing),
            "n_duplicate_groups": len(dedup["groups"]), "n_possible_duplicate_pairs": len(dedup["possible"]),
            "n_canonical": sum(r["duplicate_of"] is None for r in store),
            "n_human_reviewed": sum(bool(r["review"]) and not r["review"]["stale"] for r in store),
            "n_stale_decisions": sum(bool(r["review"]) and r["review"]["stale"] for r in store),
            "n_plannable_after_review": sum(r["plannable"] for r in store),
            "reviewers": sorted({r["review"]["reviewer"] for r in store
                                 if r["review"] and not r["review"]["stale"]}),
            "decision_problems": decision_problems}
    (out_dir / "data/activity_store_v2.json").write_bytes(
        (json.dumps(redact({**meta, "records": store}), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    (out_dir / "reports/sp1_final_readiness.md").write_bytes(report(rows, meta).encode("utf-8"))
    return store, meta


def report(rows, meta):
    lines = ["# SP1 final readiness (all posts)", "",
             f"Model: {meta['model_id']}. Posts: {meta['n_posts']}. Posts without LLM output: {meta['n_without_llm']}.",
             "Structural readiness, not gold accuracy: a post is plannable when it is an activity with an opening",
             "date in a configured semester, a known mode and a non-failed status. Intervals are Wilson 95%.",
             "Dev posts were used to choose the model and merge policy; pool and test posts were not.", "",
             "| Group | Rules plannable | Hybrid plannable |", "| --- | --- | --- |"]
    groups = {**GROUPS, "all": set().union(*GROUPS.values())}
    for name, splits in groups.items():
        part = [m for s, m in rows if s in splits]
        cells = [ci(sum(not m[method][1] for m in part), len(part)) for method in ("rules", "hybrid")]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    changed = Counter()
    for _, m in rows:
        changed[(not m["rules"][1], not m["hybrid"][1])] += 1
    lines += ["", "| Rules -> Hybrid | Posts |", "| --- | ---: |"]
    lines += [f"| {'plannable' if a else 'not'} -> {'plannable' if b else 'not'} | {n} |"
              for (a, b), n in sorted(changed.items())]
    lines += ["", "| Method | Not-plannable reason | Posts |", "| --- | --- | ---: |"]
    for method in ("rules", "hybrid"):
        counts = Counter(reason for _, m in rows for reason in m[method][1])
        lines += [f"| {method} | {reason} | {n} |" for reason, n in sorted(counts.items())]
    fields = Counter()
    for _, m in rows:
        a = m["hybrid"][0]
        fields["post_type:" + str(a["post_type"])] += 1
        fields["mode:" + str(a["mode"])] += 1
        fields["status:" + a["meta"]["status"]] += 1
    lines += ["", "## Duplicates", "",
              f"Merged groups: {meta['n_duplicate_groups']}. Canonical records: {meta['n_canonical']}/{meta['n_posts']}. "
              f"Possible-duplicate pairs flagged for review: {meta['n_possible_duplicate_pairs']}.",
              "Consumers (SP2/SP3) must use records with duplicate_of = null."]
    lines += ["", "## Human review", "",
              f"Records with an applied review decision: {meta['n_human_reviewed']}. Stale decisions (text changed): "
              f"{meta['n_stale_decisions']}. Rejected decision rows: {len(meta['decision_problems'])}.",
              f"Reviewers: {', '.join(meta['reviewers']) or 'none'}. A review decision is not verified by this",
              "project unless its reviewer is a person; the rules/hybrid table above excludes review decisions,",
              f"so the plannable figures there measure extraction only. Plannable after review: "
              f"{meta['n_plannable_after_review']}/{meta['n_posts']}."]
    lines += ["", "| Hybrid value | Posts |", "| --- | ---: |"]
    lines += [f"| {k} | {n} |" for k, n in sorted(fields.items())]
    return "\n".join(lines) + "\n"


def write_sample(store, path, seed=SAMPLE_SEED, exclude=(), n=20):
    pool = [r for r in store if r["split"] in {"pool", "test"} and r["activity"]["post_type"] == "activity"
            and r["position"] not in set(exclude)]
    sample = sorted(random.Random(seed).sample(pool, min(n, len(pool))), key=lambda r: r["position"])
    columns = ["position", "split", "post_id", "URL_post", "title", "window_open", "window_close", "mode",
               "location", "campus", "registration_deadline", "plannable",
               "ok_post_type", "ok_date", "ok_mode", "ok_place", "note"]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        for r in sample:
            a = redact(r["activity"])
            writer.writerow({"position": r["position"], "split": r["split"], "post_id": a["source"]["post_id"]
                             if isinstance(a.get("source"), dict) else "", "URL_post": (a.get("source") or {}).get("URL_post", ""),
                             "title": a.get("title"), "window_open": a["window"]["open"], "window_close": a["window"].get("close"),
                             "mode": a["mode"], "location": a.get("location"), "campus": "|".join(a.get("campus") or []),
                             "registration_deadline": a.get("registration_deadline"), "plannable": r["plannable"]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm", type=Path, default=ROOT / "data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl")
    parser.add_argument("--policy", type=Path, default=ROOT / "data/config/merge_policy.json")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT)
    parser.add_argument("--sample-out", type=Path, help="Also write a seeded manual-check sample to this CSV")
    parser.add_argument("--sample-seed", type=int, default=SAMPLE_SEED)
    parser.add_argument("--sample-exclude", type=Path, help="CSV of an earlier sample whose positions are excluded")
    parser.add_argument("--decisions", type=Path, help="Review decisions CSV (default data/review/decisions.csv)")
    parser.add_argument("--access-log", type=Path, help="Override the test-access log (dry runs only)")
    parser.add_argument("--allow-partial", action="store_true", help="Dry run only: posts without LLM output use rules")
    args = parser.parse_args(argv)
    store, meta = build(args.llm, args.policy, args.reason, args.out_dir, args.allow_partial, args.access_log,
                        args.decisions)
    if args.sample_out:
        exclude = []
        if args.sample_exclude:
            with open(args.sample_exclude, encoding="utf-8-sig") as handle:
                exclude = [int(row["position"]) for row in csv.DictReader(handle)]
        write_sample(store, args.sample_out, args.sample_seed, exclude)
        print(f"Sample written: {args.sample_out} (seed {args.sample_seed}, {len(exclude)} positions excluded)")
    print(f"{meta['n_posts']} posts, {sum(r['plannable'] for r in store)} plannable (hybrid), "
          f"{meta['n_without_llm']} without LLM output.")


if __name__ == "__main__":
    main()
