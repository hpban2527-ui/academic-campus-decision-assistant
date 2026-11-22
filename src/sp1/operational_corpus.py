"""The operational announcement corpus: the frozen 189 posts plus admin updates.

The frozen corpus (data/raw/source.json, ordered by data/gold/split_v2.json) stays the evaluation
corpus and is never edited for operations. Admins add new announcements, or a revised text of an
existing announcement, to data/raw/operational_updates.json:

  {"schema": "unilife-operational-posts/1.0",
   "posts": [{"post_id": "...", "url": "https://...", "share_url": null, "publisher": "...",
              "platform": "Facebook", "date_posted": "2026-11-28T08:00:00", "raw_content": "..."}]}

* A post_id that is not in the frozen corpus is a new post. It gets the next position (190, 191, ...)
  in file order and the split label "operational_new": it is not part of any evaluation split.
* A post_id that is in the frozen corpus is a revision: its text and metadata replace the frozen
  values for operational processing only. Evaluation keeps reading the frozen text. Every cached
  model reply and human decision is tied to a text/prompt fingerprint, so a revision invalidates them.

Reading the frozen corpus includes the held-out test posts, so it goes through
devdata.final_run_posts() and is logged with a reason.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .devdata import ROOT, final_run_posts, load_split
from .review import text_fingerprint

OVERLAY_SCHEMA = "unilife-operational-posts/1.0"
DEFAULT_OVERLAY = ROOT / "data/raw/operational_updates.json"
REQUIRED = ("post_id", "url", "publisher", "platform", "date_posted", "raw_content")
NEW_SPLIT = "operational_new"


class CorpusError(ValueError):
    """The operational update file is malformed."""


def load_overlay(path: Path | None = None) -> list[dict]:
    path = DEFAULT_OVERLAY if path is None else Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema") != OVERLAY_SCHEMA or not isinstance(data.get("posts"), list):
        raise CorpusError(f"{path.name}: expected schema {OVERLAY_SCHEMA} with a 'posts' list")
    seen = set()
    for number, post in enumerate(data["posts"], 1):
        where = f"{path.name} post #{number}"
        if not isinstance(post, dict):
            raise CorpusError(f"{where}: not an object")
        for key in REQUIRED:
            if not isinstance(post.get(key), str) or not post[key].strip():
                raise CorpusError(f"{where}: missing {key}")
        if post["post_id"] in seen:
            raise CorpusError(f"{where}: duplicate post_id {post['post_id']}")
        seen.add(post["post_id"])
    return data["posts"]


def load_operational_corpus(reason: str, *, overlay_path: Path | None = None,
                            log_path: Path | None = None) -> list[dict]:
    """All posts for an operational build, each with position, split, corpus and revision fields."""
    split_rows = load_split()["posts"]
    frozen = final_run_posts(reason, log_path=log_path)
    overlay = {post["post_id"]: post for post in load_overlay(overlay_path)}
    result = []
    for row, post in zip(split_rows, frozen):
        item = deepcopy(post)
        item.update(position=row["position"], split=row["split"], corpus="frozen_v2", revision=None)
        update = overlay.pop(post["post_id"], None)
        if update is not None:
            frozen_sha = text_fingerprint(post["raw_content"])
            for key in ("url", "share_url", "publisher", "platform", "date_posted", "raw_content"):
                if key in update:
                    item[key] = update[key]
            new_sha = text_fingerprint(item["raw_content"])
            item["revision"] = {"frozen_text_sha256": frozen_sha, "text_sha256": new_sha,
                                "text_changed": frozen_sha != new_sha, "source": "operational_updates"}
        result.append(item)
    position = max(row["position"] for row in split_rows)
    for post in overlay.values():          # dict keeps file order
        position += 1
        item = deepcopy(post)
        item.setdefault("share_url", None)
        item.update(position=position, split=NEW_SPLIT, corpus="operational_updates", revision=None)
        result.append(item)
    return result
