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
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.dedup_v2 import apply_duplicates
from sp1.devdata import final_run_posts, load_split
from sp1.evaluate import wilson
from sp1.extract_v2 import extract_v2
from sp1.hybrid import merge
from sp1.llm_v2 import PROMPT_VERSIONS, decide
from sp1.normalize import load_config, normalize
from sp1.preprocess import original_span, preprocess

MASKS = {"phone": "[phone removed]", "account": "[account removed]"}
SAMPLE_SEED = 20261114
GROUPS = {"dev": {"dev_gold", "dev_extra"}, "pool": {"pool"}, "test": {"test"}}


def redact(value):
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        pre = preprocess(value)
        for start, end, kind in reversed(pre.masked):
            left, right = original_span(pre, start, end)
            value = value[:left] + MASKS[kind] + value[right:]
    return value


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


def plannability(activity, config):
    start = activity["window"]["open"]
    day = date.fromisoformat(start[:10]) if start else None
    semester = next((key for left, right, key in config.semesters["standard"] if day and left <= day <= right),
                    "out_of_scope_semester" if day else "insufficient_data")
    fails = [key for key, fail in (("post_type", activity["post_type"] != "activity"), ("window_open", not start),
             ("mode", activity["mode"] is None),
             ("semester", semester in {"out_of_scope_semester", "insufficient_data"}),
             ("failed_status", activity["meta"]["status"] == "failed")) if fail]
    return fails, semester


def ci(k, n):
    if not n:
        return "n/a"
    low, high = wilson(k, n)
    return f"{k}/{n} = {k / n:.1%} [{low:.1%}, {high:.1%}]"


def build(llm_path, policy_path, reason, out_dir, allow_partial=False, access_log=None):
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
    store, rows = [], []
    for post in posts:
        pid = post["post_id"]
        source = {key: post.get(key) for key in ("post_id", "publisher", "platform", "date_posted")}
        source["URL_post"] = post["url"]
        rules = extract_v2(post)
        decision = decide(post, llm[pid]["replies"]) if pid in llm else None
        hybrid = merge(rules, decision, policy)
        per_method = {}
        for method, output in (("rules", rules), ("hybrid", hybrid)):
            activity = normalize(output["layer_a"], source, config)
            per_method[method] = (activity, *plannability(activity, config))
        activity, fails, semester = per_method["hybrid"]
        store.append({"position": split[pid]["position"], "split": split[pid]["split"], "activity": activity,
                      "activity_type": hybrid["classification"]["activity_type"],
                      "semester": semester, "plannable": not fails, "not_plannable_reasons": fails,
                      "field_methods": hybrid.get("field_methods", {}),
                      "llm_warnings": (decision or {}).get("warnings", []),
                      "llm_available": decision is not None})
        rows.append((split[pid]["split"], per_method))
    dedup = apply_duplicates(store, {p["post_id"]: p["raw_content"] for p in posts})
    out_dir = Path(out_dir)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)
    meta = {"schema": "sp1-activity-store/2.0", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_id": model_id, "prompt_versions": PROMPT_VERSIONS, "merge_policy": policy,
            "llm_file": Path(llm_path).name, "n_posts": len(store), "n_without_llm": len(missing),
            "n_duplicate_groups": len(dedup["groups"]), "n_possible_duplicate_pairs": len(dedup["possible"]),
            "n_canonical": sum(r["duplicate_of"] is None for r in store)}
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
    parser.add_argument("--access-log", type=Path, help="Override the test-access log (dry runs only)")
    parser.add_argument("--allow-partial", action="store_true", help="Dry run only: posts without LLM output use rules")
    args = parser.parse_args(argv)
    store, meta = build(args.llm, args.policy, args.reason, args.out_dir, args.allow_partial, args.access_log)
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
