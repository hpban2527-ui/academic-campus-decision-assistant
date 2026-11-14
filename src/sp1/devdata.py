"""Development access to the frozen SP1 corpus."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_STRUCTURAL_TOKEN = re.compile(rb'"(?:[^"\\]|\\.)*"|[{}\[\],:]')


class TestSetAccessError(RuntimeError):
    """The requested post is reserved for test evaluation."""


@lru_cache(maxsize=1)
def _split(root: Path) -> dict:
    return json.loads((root / "data/gold/split_v2.json").read_bytes())


def load_split(root: Path | None = None) -> dict:
    """Return the split manifest independently of the cached copy."""
    return deepcopy(_split(ROOT if root is None else Path(root).resolve()))


def dev_ids(include_extra: bool = True) -> list[str]:
    splits = {"dev_gold", "dev_extra"} if include_extra else {"dev_gold"}
    return [row["post_id"] for row in _split(ROOT)["posts"] if row["split"] in splits]


def non_test_ids() -> list[str]:
    splits = {"dev_gold", "dev_extra", "pool"}
    return [row["post_id"] for row in _split(ROOT)["posts"] if row["split"] in splits]


def _object_ranges(data: bytes):
    """Scan JSON structure and yield object bounds and IDs, without decoding post text."""
    depth = 0
    start = 0
    post_id = None
    expecting_id = False
    expecting_key = False
    for match in _STRUCTURAL_TOKEN.finditer(data):
        # A string value may be held-out content. Inspect its boundaries only.
        token = data[match.start():match.start() + 1]
        if token == b"{" and depth == 1:
            start = match.start()
            post_id = None
            expecting_key = True
        elif depth == 2 and token == b"}":
            if not isinstance(post_id, str):
                raise ValueError("Source post is missing its string post_id")
            yield start, match.end(), post_id
        elif depth == 2:
            if expecting_key and token.startswith(b'"'):
                expecting_id = data[match.start():match.end()] == b'"post_id"'
                expecting_key = False
            elif expecting_id and token.startswith(b'"'):
                post_id = json.loads(data[match.start():match.end()])
                expecting_id = False
            elif token == b",":
                expecting_key = True
                expecting_id = False
        if token in (b"{", b"["):
            depth += 1
        elif token in (b"}", b"]"):
            depth -= 1
    if depth:
        raise ValueError("Unbalanced source JSON")


@lru_cache(maxsize=1)
def _posts(root: Path) -> dict[str, dict]:
    rows = _split(root)["posts"]
    data = (root / "data/raw/source.json").read_bytes()
    ranges = list(_object_ranges(data))
    if [post_id for _, _, post_id in ranges] != [row["post_id"] for row in rows]:
        raise ValueError("Source post IDs or order differ from the frozen split")
    return {
        post_id: json.loads(data[start:end])
        for (start, end, post_id), row in zip(ranges, rows)
        if row["split"] in {"dev_gold", "dev_extra", "pool"}
    }


def get_post(post_id: str) -> dict:
    """Return a copy of an allowed post, or reject a held-out ID before loading source."""
    row = next((row for row in _split(ROOT)["posts"] if row["post_id"] == post_id), None)
    if row is not None and row["split"] == "test":
        raise TestSetAccessError("Post is in the held-out test split")
    if row is None:
        raise KeyError(post_id)
    return deepcopy(_posts(ROOT)[post_id])


def dev_posts(include_extra: bool = True) -> list[dict]:
    return [get_post(post_id) for post_id in dev_ids(include_extra)]


FINAL_RUN_LOG = ROOT / "data/gold/final_run_access_log.jsonl"
ALL_SPLITS = ("dev_gold", "dev_extra", "pool", "test")


def final_run_posts(reason: str, splits=ALL_SPLITS, log_path: Path | None = None) -> list[dict]:
    """Return posts of the given splits, test included, for the final batch run only.

    This is the only reader that can return held-out test posts. It requires an explicit reason
    (at least 10 characters) and appends one line per call to the access log
    (`data/gold/final_run_access_log.jsonl` by default), so every use is visible in git history.
    Development code must keep using get_post()/dev_posts(), which still refuse test posts.
    """
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise TestSetAccessError("A final-run reason of at least 10 characters is required")
    unknown = set(splits) - set(ALL_SPLITS)
    if unknown:
        raise ValueError(f"Unknown splits: {sorted(unknown)}")
    rows = _split(ROOT)["posts"]
    data = (ROOT / "data/raw/source.json").read_bytes()
    ranges = list(_object_ranges(data))
    if [post_id for _, _, post_id in ranges] != [row["post_id"] for row in rows]:
        raise ValueError("Source post IDs or order differ from the frozen split")
    posts = [json.loads(data[start:end]) for (start, end, _), row in zip(ranges, rows)
             if row["split"] in splits]
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "reason": reason.strip(),
             "splits": sorted(splits), "n_posts": len(posts)}
    log = FINAL_RUN_LOG if log_path is None else Path(log_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return posts
