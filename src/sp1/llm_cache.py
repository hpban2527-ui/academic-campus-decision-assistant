"""Recorded SP1 model replies, replayed only when the exact prompt input still matches.

A recorded reply refers to candidate IDs (D1, T2, U1, ...) of the prompt it answered. When the post
text or the candidate builder changes, the same ID can name a different span, so a reply is reused
only when all of these match the current post:

* the model ID (the merge policy's model) and the prompt versions, and
* input_sha256: SHA-256 of the two rendered prompts (classify and roles), as the Kaggle notebook
  records it (notebooks/sp1_llm_v2_kaggle.ipynb, input_digest()).

Otherwise the post has no usable reply: state "stale" (a reply exists for an older input) or
"missing". Callers must treat both as "extraction pending", never as an empty or rules-only success.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .candidates import build_candidates
from .llm_v2 import PROMPT_VERSIONS, build_classify_prompt, build_roles_prompt
from .preprocess import preprocess
from .segment import segment

RUN_STATS = ("seconds", "peak_vram_gb", "tokens", "thinking_stripped")


class CacheError(ValueError):
    """A recorded reply file is inconsistent."""


def prompts_for(post: dict) -> dict[str, str]:
    """The two prompts exactly as scripts/export_llm_inputs.py renders them."""
    pre = preprocess(post["raw_content"])
    seg = segment(pre)
    cands = build_candidates(pre, seg)
    return {"classify": build_classify_prompt(pre, seg, post), "roles": build_roles_prompt(pre, seg, cands, post)}


def input_digest(prompts: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(prompts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_replies(paths, model_id: str) -> dict[tuple[str, str], dict]:
    """Index recorded rows by (post_id, input_sha256). Rows of another model or prompt version are skipped
    (they cannot be replayed under the current policy); conflicting rows for the same key are an error."""
    index: dict[tuple[str, str], dict] = {}
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("model_id") != model_id or row.get("prompt_versions") != PROMPT_VERSIONS:
                continue
            digest = row.get("input_sha256")
            if not isinstance(digest, str) or not isinstance(row.get("replies"), dict):
                raise CacheError(f"{path.name}:{number}: missing input_sha256 or replies")
            if set(row["replies"]) != set(PROMPT_VERSIONS):
                raise CacheError(f"{path.name}:{number}: incomplete replies")
            key = (row["post_id"], digest)
            content = {k: v for k, v in row.items() if k not in RUN_STATS}
            if key in index:
                previous = {k: v for k, v in index[key].items() if k not in RUN_STATS and k != "_file"}
                if previous != content:
                    raise CacheError(f"Post {row['post_id']}: two different replies for the same input "
                                     f"({index[key]['_file']} and {path.name})")
                continue
            index[key] = {**row, "_file": path.name}
    return index


def lookup(index: dict, post: dict, prompts: dict[str, str] | None = None) -> tuple[dict | None, str, str]:
    """(row or None, state, digest). state: "cached", "stale" (only older inputs recorded) or "missing"."""
    digest = input_digest(prompts or prompts_for(post))
    row = index.get((post["post_id"], digest))
    if row is not None:
        return row, "cached", digest
    stale = any(pid == post["post_id"] for pid, _ in index)
    return None, ("stale" if stale else "missing"), digest
