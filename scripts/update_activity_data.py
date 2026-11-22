"""Update the operational activity dataset after new or edited announcements (admin batch, offline).

  python scripts/update_activity_data.py --reason "batch 2026-12-01: post 190"

What it does, in one run:

1. Reads the operational corpus: the frozen 189 posts (logged access, test posts included) plus
   data/raw/operational_updates.json (new posts get positions 190, 191, ...; a known post_id is an
   edited text). No manual JSON/CSV annotation is needed.
2. Reuses every recorded model reply whose prompt digest still matches (model, prompt versions and the
   SHA-256 of both rendered prompts). Changed text invalidates the old reply and any human decision.
3. Posts that still need the model:
   * with --call-model and a configured backend (SP1_LLM_BASE_URL etc., see src/sp1/model_client.py),
     the two prompts are sent to the same model as the batch run and the replies are appended to
     data/llm_outputs/operational/<model>.jsonl with their input digest;
   * otherwise their prompts are written to data/llm_inputs/pending_operational.jsonl for the Kaggle
     notebook (notebooks/sp1_llm_v2_kaggle.ipynb); put the notebook's output .jsonl into
     data/llm_outputs/operational/ and run this command again.
   Until then the post is published as EXTRACTION_PENDING with its reason: nothing is invented.
4. Builds the whole dataset (extraction, human decisions, acceptance policy, duplicates, SP2 bindings,
   personalization features, SP3 activities), validates it, stages it and atomically replaces
   data/operational/activity_dataset.json. A failed build or validation leaves the previous file in place.
5. Writes reports/operational_dataset_report.md and prints the summary and the change against the
   previous version.

--dry-run writes nothing to the repository (pass --out to keep the built file elsewhere).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.llm_cache import input_digest, load_replies, lookup, prompts_for  # noqa: E402
from sp1.llm_v2 import PROMPT_VERSIONS  # noqa: E402
from sp1.operational import (DATASET_PATH, DatasetInvalid, READY_STATUSES, build_dataset,  # noqa: E402
                             default_llm_files, load_dataset, publish, sha256_file, validate_dataset)
from sp1.operational_corpus import DEFAULT_OVERLAY, load_operational_corpus  # noqa: E402

OPERATIONAL_LLM_DIR = ROOT / "data/llm_outputs/operational"
PENDING_INPUTS = ROOT / "data/llm_inputs/pending_operational.jsonl"
REPORT = ROOT / "reports/operational_dataset_report.md"


def _show(path: Path) -> str:
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if ROOT in path.parents else str(path)


def _needs_model(dataset: dict) -> list[str]:
    return [r["post_id"] for r in dataset["records"] if r["status"] == "EXTRACTION_PENDING"]


def call_model(posts: list[dict], pending: list[str], model_id: str, client=None) -> dict:
    """Ask the configured backend for the pending posts; append valid rows. Returns {post_id: error}."""
    from sp1.model_client import SP1ModelClient, SP1ModelConfig, SP1ModelError
    client = client or SP1ModelClient(SP1ModelConfig.from_env())
    OPERATIONAL_LLM_DIR.mkdir(parents=True, exist_ok=True)
    out = OPERATIONAL_LLM_DIR / (model_id.replace("/", "__") + ".jsonl")
    errors = {}
    by_id = {p["post_id"]: p for p in posts}
    for pid in pending:
        prompts = prompts_for(by_id[pid])
        try:
            replies, seconds = {}, {}
            for kind, prompt in prompts.items():
                completion = client.complete(prompt)
                if completion.served_model != model_id:
                    raise SP1ModelError("MODEL_MISMATCH", f"served {completion.served_model}", retryable=False)
                replies[kind], seconds[kind] = completion.text, completion.seconds
        except SP1ModelError as exc:
            errors[pid] = exc.code
            continue
        row = {"post_id": pid, "model_id": model_id, "prompt_versions": dict(PROMPT_VERSIONS),
               "input_sha256": input_digest(prompts), "replies": replies, "seconds": seconds,
               "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "update_activity_data"}
        with out.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return errors


def write_pending_inputs(posts: list[dict], pending: list[str], path: Path) -> None:
    rows = []
    by_id = {p["post_id"]: p for p in posts}
    for pid in pending:
        post = by_id[pid]
        prompts = prompts_for(post)
        rows.append({"post_id": pid, "position": post["position"], "posted_date": post.get("date_posted"),
                     "classify_prompt": prompts["classify"], "roles_prompt": prompts["roles"],
                     "prompt_versions": dict(PROMPT_VERSIONS), "input_sha256": input_digest(prompts)})
    if not rows:
        if path.exists():
            path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))


def change_report(before: dict | None, after: dict) -> dict:
    old = {r["post_id"]: r for r in (before or {}).get("records", [])}
    new = {r["post_id"]: r for r in after["records"]}
    changed = {}
    for pid in sorted(set(old) & set(new)):
        a, b = old[pid], new[pid]
        diffs = [k for k in ("status", "reasons", "sp3_activity", "binding", "features", "duplicate_of")
                 if a.get(k) != b.get(k)]
        if diffs:
            changed[pid] = {"fields": diffs, "status": [a["status"], b["status"]]}
    return {"previous_version": (before or {}).get("dataset_version"), "version": after["dataset_version"],
            "added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)), "changed": changed}


def markdown(dataset: dict, changes: dict) -> str:
    s = dataset["summary"]
    lines = ["# Operational activity dataset", "",
             f"Dataset `{dataset['dataset_version']}` ({dataset['schema']}, activity contract "
             f"{dataset['activity_contract']}), generated {dataset['generated_at']}. Counts are read from "
             "data/operational/activity_dataset.json; they describe data readiness, not extraction accuracy.", "",
             "| Status | Posts |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in s["by_status"].items()]
    lines += [f"| **total** | **{s['posts']}** |", "",
              f"Schedulable canonical activities: {s['schedulable_canonical']} "
              f"({', '.join(f'{k} {v}' for k, v in s['schedule_types'].items())}). "
              f"With a supported score binding: {s['with_supported_score_binding']}. "
              f"Mandatory items that cannot be scheduled: {s['mandatory_unscheduled']}.", "",
              "| Extraction method | Posts |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in s["by_extraction_method"].items()]
    lines += ["", "| Split | Posts |", "| --- | ---: |"] + [f"| {k} | {v} |" for k, v in s["by_split"].items()]
    lines += ["", "| Not schedulable: reason | Posts |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in s["not_schedulable_reasons"].items()]
    lines += ["", "| Warning on schedulable activities | Activities |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in s["warnings_on_schedulable"].items()]
    lines += ["", "| Student-eligibility basis (schedulable) | Activities |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in s["eligibility_basis_of_schedulable"].items()]
    lines += ["", "| Score rule | Bindings |", "| --- | ---: |"] + [f"| {k} | {v} |" for k, v in s["bindings_by_rule"].items()]
    lines += ["", f"Human decisions applied: {s['human_decisions_applied']} (stale: {s['human_decisions_stale']}). "
              f"Duplicate groups: {s['duplicate_groups']}.", "",
              "## Change against the previous version", "",
              f"Previous: {changes['previous_version']}. Added: {len(changes['added'])}. "
              f"Removed: {len(changes['removed'])}. Changed: {len(changes['changed'])}."]
    lines += [f"- {pid}: {', '.join(c['fields'])} ({c['status'][0]} -> {c['status'][1]})"
              for pid, c in list(changes["changed"].items())[:50]]
    lines += [f"- added {pid}" for pid in changes["added"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reason", required=True, help="Logged: the build reads all posts, test posts included")
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY, help="Operational updates file")
    parser.add_argument("--call-model", action="store_true", help="Send pending posts to the configured backend")
    parser.add_argument("--llm", type=Path, action="append", help="Recorded reply files (default: final + operational)")
    parser.add_argument("--out", type=Path, default=DATASET_PATH)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--pending-inputs", type=Path, default=PENDING_INPUTS)
    parser.add_argument("--access-log", type=Path, help="Override the test-access log (tests and dry runs)")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate only; write nothing")
    args = parser.parse_args(argv)

    posts = load_operational_corpus(args.reason, overlay_path=args.overlay, log_path=args.access_log)
    corpus_ids = [p["post_id"] for p in posts]
    overlay_sha = sha256_file(args.overlay)
    llm_files = args.llm or default_llm_files()
    dataset = build_dataset(posts, llm_files=llm_files, overlay_sha256=overlay_sha)
    pending = _needs_model(dataset)
    if pending and args.call_model and not args.dry_run:
        errors = call_model(posts, pending, dataset["inputs"]["model_id"])
        for pid, code in errors.items():
            print(f"model call failed for {pid}: {code} (kept as EXTRACTION_PENDING)", file=sys.stderr)
        dataset = build_dataset(posts, llm_files=args.llm or default_llm_files(), overlay_sha256=overlay_sha)
        pending = _needs_model(dataset)
    problems = validate_dataset(dataset, corpus_ids)
    if problems:
        print("Dataset NOT published: " + "; ".join(problems[:20]), file=sys.stderr)
        return 1
    before = load_dataset(args.out) if args.out.exists() else None
    changes = change_report(before, dataset)
    if not args.dry_run:
        try:
            publish(dataset, args.out, corpus_ids)
        except DatasetInvalid as exc:
            print(f"Dataset NOT published: {exc}", file=sys.stderr)
            return 1
        write_pending_inputs(posts, pending, args.pending_inputs)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(markdown(dataset, changes).encode("utf-8"))
    s = dataset["summary"]
    print(f"{'Validated (dry run)' if args.dry_run else 'Published'} dataset {dataset['dataset_version']}: "
          f"{s['posts']} posts -> " + ", ".join(f"{k} {v}" for k, v in s["by_status"].items()))
    print(f"Schedulable canonical activities: {s['schedulable_canonical']}; with supported score binding: "
          f"{s['with_supported_score_binding']}")
    if pending:
        print(f"{len(pending)} post(s) await model output: " + ", ".join(pending) +
              (f"; prompts written to {_show(args.pending_inputs)}" if not args.dry_run else ""))
    print(f"Change: +{len(changes['added'])} -{len(changes['removed'])} ~{len(changes['changed'])} "
          f"(previous {changes['previous_version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
