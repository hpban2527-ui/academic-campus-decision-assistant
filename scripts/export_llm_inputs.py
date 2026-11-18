"""Export model-ready inputs without giving the notebook any corpus access.

--only-missing drops every post that already has a record for its current prompts (same input_sha256) in the given LLM output files (--llm, repeatable;
default data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl), so the notebook only runs on new posts.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.candidates import build_candidates
from sp1.devdata import (ALL_SPLITS, TestSetAccessError, dev_ids, final_run_posts, get_post, load_split,
                         non_test_ids)
from sp1.llm_v2 import PROMPT_VERSIONS, _safe, build_classify_prompt, build_roles_prompt
from sp1.preprocess import preprocess
from sp1.segment import segment

DEFAULT_LLM = ROOT / "data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl"


def _row(post, position):
    pre = preprocess(post["raw_content"])
    seg = segment(pre)
    cands = build_candidates(pre, seg)
    return {"post_id": post["post_id"], "position": position, "posted_date": post.get("date_posted"),
            "classify_prompt": build_classify_prompt(pre, seg, post),
            "roles_prompt": build_roles_prompt(pre, seg, cands, post),
            "n_lines": len(pre.text.split("\n")), "prompt_versions": PROMPT_VERSIONS,
            "flags": list(pre.flags) + cands.flags,
            "candidates": [{k: _safe(v) if isinstance(v, str) else v for k, v in asdict(c).items()
                            if k != "context"} for c in cands]}


def export_rows(split, final_run_include_test=False, reason=None, log_path=None):
    positions = {r["post_id"]: r["position"] for r in load_split()["posts"]}
    if split in {"test", "all"}:
        if not final_run_include_test:
            raise TestSetAccessError("Test export requires --final-run-include-test")
        if not reason:
            raise TestSetAccessError("Final-run export requires --reason")
        splits = ("test",) if split == "test" else ALL_SPLITS
        for post in final_run_posts(reason, splits, log_path):
            yield _row(post, positions[post["post_id"]])
        return
    if split not in {"dev", "non_test"}:
        raise ValueError("Unknown split")
    for post_id in dev_ids() if split == "dev" else non_test_ids():
        yield _row(get_post(post_id), positions[post_id])


def synthetic_rows(paths):
    """Rows for synthetic posts (red-team sets); never touches the corpus."""
    posts = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        posts += data["posts"] if isinstance(data, dict) else data
    if len({p["post_id"] for p in posts}) != len(posts):
        raise ValueError("Duplicate synthetic post IDs")
    return [_row(post, number) for number, post in enumerate(posts, 1)]


def llm_output_ids(paths):
    """(post_id, input_sha256) of every record in the LLM output files (.jsonl). A post counts as done only
    if a record answers its current prompts: an edited post or a changed candidate builder needs a new run."""
    ids = set()
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                ids.add((row["post_id"], row.get("input_sha256")))
    return ids


def _digest(row):
    prompts = {"classify": row["classify_prompt"], "roles": row["roles_prompt"]}
    return hashlib.sha256(json.dumps(prompts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def export(split, out, final_run_include_test=False, reason=None, log_path=None, posts=None, skip_ids=None):
    """Write the rows; skip_ids (posts that already have LLM output) are left out. Nothing is written when
    no row is left."""
    # Materialise first: refused exports must not create an empty file or directory.
    rows = synthetic_rows(posts) if posts else list(export_rows(split, final_run_include_test, reason, log_path))
    if skip_ids is not None:
        rows = [row for row in rows if (row["post_id"], _digest(row)) not in skip_ids]
        if not rows:
            return rows
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--split", choices=("dev", "non_test", "test", "all"))
    source.add_argument("--posts", type=Path, nargs="+", help="Synthetic post files (red-team), not the corpus")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--final-run-include-test", action="store_true")
    parser.add_argument("--reason", help="Required with --final-run-include-test; logged in data/gold/final_run_access_log.jsonl")
    parser.add_argument("--only-missing", action="store_true",
                        help="Export only posts that have no record in the --llm files yet")
    parser.add_argument("--llm", type=Path, action="append",
                        help=f"With --only-missing: existing LLM output (repeatable; default {DEFAULT_LLM.relative_to(ROOT)})")
    parser.add_argument("--access-log", type=Path, help="Override the test-access log (dry runs only)")
    args = parser.parse_args(argv)
    if args.only_missing and args.posts:
        parser.error("--only-missing applies to the corpus (--split), not to synthetic --posts")
    if args.llm and not args.only_missing:
        parser.error("--llm is only used with --only-missing")
    skip = llm_output_ids(args.llm or [DEFAULT_LLM]) if args.only_missing else None
    try:
        rows = export(args.split, args.out, args.final_run_include_test, args.reason, args.access_log,
                      posts=args.posts, skip_ids=skip)
    except TestSetAccessError as exc:
        parser.error(str(exc))
    if not rows and skip is not None:
        print(f"Nothing to export: every post already has LLM output ({len(skip)} posts). {args.out} not written.")
        return 0
    print(f"Exported {len(rows)} posts, {args.out.stat().st_size} bytes.")
    for kind in ("classify", "roles"):
        print(f"Longest {kind} prompt: {max(len(r[kind + '_prompt']) for r in rows)} characters.")
    if skip is not None:
        print("Posts without LLM output: " + ", ".join(f"{r['position']} ({r['post_id']})" for r in rows))
    return 0


if __name__ == "__main__":
    main()
