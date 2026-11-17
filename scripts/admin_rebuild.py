"""Admin-only offline rebuild of the SP1 activity data. No network access and no model calls.

Runs the existing build scripts in order, each through its own main(argv):

  1. build_activity_store   data/activity_store_v2.json, reports/sp1_final_readiness.md
  2. build_handover         data/handover/{activities_sp3,sidecar,blocked}.json, reports/sp1_handover_readiness.md
  3. build_bindings         data/handover/bindings.json, reports/sp2_binding_readiness.md
  4. build_features         data/handover/{activity_features_sp1,features_provenance}.json
  5. export_review_queue    data/review/queue.csv

It stops at the first failing step with exit code 1 and names the step. Steps before it have already
written their outputs, so the data directory is then inconsistent: fix the cause and run again (or restore
with `git checkout -- data/ reports/`). On success it prints a summary read from the output files and the
difference between the previous and the new handover (activities added, removed, changed).

The LLM replies come from recorded .jsonl files (--llm, repeatable), produced offline on Kaggle. The running
app only reads the committed output files. See docs/admin_data_update.md.

  python scripts/admin_rebuild.py --reason "batch 2026-12: 6 new posts"
  python scripts/admin_rebuild.py --reason "..." --llm data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl \\
      --llm data/llm_outputs/final/Qwen__Qwen3.5-4B_batch_20261201.jsonl
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent

STEPS = ("build_activity_store", "build_handover", "build_bindings", "build_features", "export_review_queue")
STORE = "data/activity_store_v2.json"
ACTIVITIES = "data/handover/activities_sp3.json"
BLOCKED = "data/handover/blocked.json"
BINDINGS = "data/handover/bindings.json"
QUEUE = "data/review/queue.csv"

_modules: dict[str, object] = {}


class StepFailed(RuntimeError):
    """A build step returned a non-zero exit code."""


def load_script(name: str):
    """Import scripts/<name>.py once (the scripts are not a package)."""
    if name not in _modules:
        spec = importlib.util.spec_from_file_location(f"admin_rebuild_{name}", SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _modules[name] = module
    return _modules[name]


def run_step(name: str, argv: list[str]) -> None:
    """Call the script's main(argv). A non-zero return value or SystemExit code is a failure."""
    try:
        result = load_script(name).main(argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise StepFailed(f"exited with code {exc.code}") from exc
        return
    if result not in (None, 0):
        raise StepFailed(f"returned {result}")


def step_argv(name: str, args) -> list[str]:
    """Arguments for one step: --out-dir everywhere, --reason/--llm/--decisions/--access-log where used."""
    argv = ["--out-dir", str(args.out_dir)]
    if name in ("build_activity_store", "build_bindings"):
        argv += ["--reason", args.reason]
        if args.access_log:
            argv += ["--access-log", str(args.access_log)]
    if name == "build_activity_store":
        for path in args.llm or []:
            argv += ["--llm", str(path)]
        if args.decisions:
            argv += ["--decisions", str(args.decisions)]
    return argv


def _read_json(out_dir: Path, path: str):
    file = out_dir / path
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else None


def snapshot(out_dir: Path) -> dict | None:
    """The handover as it is now: {activity_id: 14-field record}, positions and post count; None if absent."""
    activities = _read_json(out_dir, ACTIVITIES)
    if activities is None:
        return None
    store = _read_json(out_dir, STORE) or {"records": []}
    return {"activities": {a["activity_id"]: a for a in activities},
            "positions": {r["activity"]["source"]["post_id"]: r["position"] for r in store["records"]},
            "n_posts": store.get("n_posts")}


def summary(out_dir: Path) -> dict:
    """Counts read from the output files (nothing is recomputed)."""
    store = _read_json(out_dir, STORE)
    bindings = _read_json(out_dir, BINDINGS)
    with open(out_dir / QUEUE, encoding="utf-8-sig", newline="") as handle:
        queue_rows = sum(1 for _ in csv.DictReader(handle))
    return {"n_posts": store["n_posts"], "n_without_llm": store["n_without_llm"],
            "plannable": store["n_plannable_after_review"],
            "handed_over": len(_read_json(out_dir, ACTIVITIES)), "blocked": len(_read_json(out_dir, BLOCKED)),
            "bindings_by_operation": dict(sorted(Counter(b["operation"] for b in bindings["bindings"]).items())),
            "review_queue_rows": queue_rows,
            "review_decisions": {"applied": store["n_human_reviewed"], "stale": store["n_stale_decisions"],
                                 "rejected": len(store["decision_problems"])}}


def diff(before: dict | None, after: dict) -> dict:
    """Activity ids added / removed / changed (any field of the handed-over record), with changed fields."""
    old = before["activities"] if before else {}
    new = after["activities"]
    changed = {aid: sorted(k for k in set(old[aid]) | set(new[aid]) if old[aid].get(k) != new[aid].get(k))
               for aid in sorted(set(old) & set(new)) if old[aid] != new[aid]}
    return {"previous": before is not None, "added": sorted(set(new) - set(old)),
            "removed": sorted(set(old) - set(new)), "changed": changed,
            "n_posts": (before["n_posts"] if before else None, after["n_posts"])}


def _label(aid: str, *snapshots) -> str:
    position = next((s["positions"][aid] for s in snapshots if s and aid in s["positions"]), None)
    return f"position {position} {aid}" if position is not None else aid


def print_report(counts: dict, changes: dict, before: dict | None, after: dict) -> None:
    ops = ", ".join(f"{op} {n}" for op, n in counts["bindings_by_operation"].items()) or "none"
    print("\n=== Summary (read from the output files) ===")
    for label, value in (("posts in store", counts["n_posts"]), ("posts without LLM output", counts["n_without_llm"]),
                         ("plannable after review", counts["plannable"]),
                         ("handed over to SP3", counts["handed_over"]),
                         ("blocked (not handed over)", counts["blocked"]),
                         ("score bindings", f"{sum(counts['bindings_by_operation'].values())} ({ops})"),
                         ("review queue rows", counts["review_queue_rows"]),
                         ("review decisions", "{applied} applied, {stale} stale, {rejected} rejected rows"
                          .format(**counts["review_decisions"]))):
        print(f"  {label + ':':<27}{value}")
    if counts["review_decisions"]["rejected"]:
        print(f"  rejected decision rows are listed under decision_problems in {STORE}")
    print("\n=== Handover diff against the previous build ===")
    if not changes["previous"]:
        print(f"no previous handover in this directory: all {len(changes['added'])} activities are new")
        return
    old_posts, new_posts = changes["n_posts"]
    print(f"posts in store: {old_posts} -> {new_posts}")
    print(f"added {len(changes['added'])}, removed {len(changes['removed'])}, changed {len(changes['changed'])}")
    for aid in changes["added"]:
        print(f"  + {_label(aid, after)}")
    for aid in changes["removed"]:
        print(f"  - {_label(aid, before, after)}")
    for aid, fields in changes["changed"].items():
        print(f"  ~ {_label(aid, after)}: {', '.join(fields)}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reason", required=True,
                        help="Why the corpus is read (test posts included); logged in the access log")
    parser.add_argument("--llm", type=Path, action="append",
                        help="Recorded LLM output .jsonl; repeat for each batch (default: the original final run)")
    parser.add_argument("--decisions", type=Path, help="Review decisions CSV (default data/review/decisions.csv)")
    parser.add_argument("--out-dir", type=Path, default=ROOT,
                        help="Where outputs are written and the previous build is read (default: the repo root)")
    parser.add_argument("--access-log", type=Path, help="Override the test-access log (dry runs and tests only)")
    return parser.parse_args(argv)


def main(argv=None, runner=run_step) -> int:
    args = parse_args(argv)
    args.out_dir = Path(args.out_dir)
    before = snapshot(args.out_dir)
    for number, name in enumerate(STEPS, 1):
        print(f"\n=== Step {number}/{len(STEPS)}: {name} ===", flush=True)
        try:
            runner(name, step_argv(name, args))
        except (Exception, SystemExit) as exc:     # SystemExit: a step's argparse error
            traceback.print_exc()
            print(f"\nFAILED at step {number}/{len(STEPS)} ({name}): {type(exc).__name__}: {exc}\n"
                  f"Earlier steps already wrote their outputs to {args.out_dir}; fix the cause and run again.",
                  file=sys.stderr)
            return 1
    after = snapshot(args.out_dir)
    print_report(summary(args.out_dir), diff(before, after), before, after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
