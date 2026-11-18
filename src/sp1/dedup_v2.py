"""Activity-level duplicate grouping for the SP1 v2 store (deterministic).

A duplicate is the same activity announced more than once (repost, share, another channel).
Rules, from strong to weak:

* merge: same opening (date and time, time stated) and either near-identical text
  (MinHash Jaccard >= TEXT_THRESHOLD) or the same normalised title.
* possible duplicate (flag only, kept separate, for review): same opening and title token
  Jaccard >= TITLE_FLAG_THRESHOLD.
* never: different opening day, or an unknown opening. A shared registration link or template text
  alone is not evidence (monthly seminars of one faculty share both).

The canonical record of a group is the most complete one: status valid > partial > failed, then more
non-null fields, then the earliest posting date, then post_id. Other members point to it with
duplicate_of, and the canonical record lists every member's source.
"""

from __future__ import annotations

import re
import unicodedata

from .deduplication import compute_minhash

TEXT_THRESHOLD = 0.75
TITLE_FLAG_THRESHOLD = 0.6
_STATUS_RANK = {"valid": 0, "partial": 1, "failed": 2}
_FIELDS = ("title", "mode", "location", "registration_deadline", "registration_url", "join_url", "fee")


def _title_key(title: str | None) -> str:
    text = unicodedata.normalize("NFC", title or "").lower()
    return " ".join(re.findall(r"\w+", text))


def _tokens(title: str | None) -> set[str]:
    return set(_title_key(title).split())


def _opening(activity: dict) -> str | None:
    opening = activity["window"]["open"]
    defaults = activity["meta"].get("time_defaults") or {}
    if not opening or "window_open" in defaults or (isinstance(defaults, list) and "window_open" in defaults):
        return None  # an unstated time is too weak to tie two announcements together
    return opening


def _completeness(record: dict) -> tuple:
    a = record["activity"]
    filled = sum(a.get(field) not in (None, [], "") for field in _FIELDS)
    return (_STATUS_RANK.get(a["meta"]["status"], 3), -filled, a["source"].get("date_posted") or "9999",
            a["source"]["post_id"])


def group_duplicates(records: list[dict], texts: dict[str, str]) -> dict:
    """Return {"groups": [[post_id, ...]], "possible": [(post_id, post_id, reason)]}.

    records are store records ({"activity": ...}); texts maps post_id to the raw announcement text.
    """
    by_opening: dict[str, list[dict]] = {}
    for record in records:
        opening = _opening(record["activity"])
        if opening:
            by_opening.setdefault(opening, []).append(record)
    parent = {r["activity"]["source"]["post_id"]: r["activity"]["source"]["post_id"] for r in records}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    possible = []
    hashes = {}
    for bucket in by_opening.values():
        for i, left in enumerate(bucket):
            for right in bucket[i + 1:]:
                a, b = left["activity"], right["activity"]
                ia, ib = a["source"]["post_id"], b["source"]["post_id"]
                for pid in (ia, ib):
                    if pid not in hashes:
                        hashes[pid] = compute_minhash(texts.get(pid, ""))
                ha, hb = hashes[ia], hashes[ib]
                text_sim = ha.jaccard(hb) if ha and hb else 0.0
                same_title = bool(_title_key(a["title"])) and _title_key(a["title"]) == _title_key(b["title"])
                if text_sim >= TEXT_THRESHOLD or same_title:
                    parent[find(ib)] = find(ia)
                    continue
                ta, tb = _tokens(a["title"]), _tokens(b["title"])
                title_sim = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
                if title_sim >= TITLE_FLAG_THRESHOLD:
                    possible.append((ia, ib, f"same_opening_title_{title_sim:.2f}_text_{text_sim:.2f}"))
    groups: dict[str, list[str]] = {}
    for pid in parent:
        groups.setdefault(find(pid), []).append(pid)
    return {"groups": [sorted(g) for g in groups.values() if len(g) > 1], "possible": possible}


def apply_duplicates(records: list[dict], texts: dict[str, str]) -> dict:
    """Annotate store records in place: duplicate_of, sources, possible_duplicates. Returns the grouping."""
    result = group_duplicates(records, texts)
    by_id = {r["activity"]["source"]["post_id"]: r for r in records}
    for record in records:
        record["duplicate_of"] = None
        record["sources"] = [record["activity"]["source"]]
        record["possible_duplicates"] = []
    for group in result["groups"]:
        members = sorted((by_id[pid] for pid in group), key=_completeness)
        canonical = members[0]
        canonical["sources"] = [m["activity"]["source"] for m in members]
        for member in members[1:]:
            member["duplicate_of"] = canonical["activity"]["source"]["post_id"]
    for left, right, reason in result["possible"]:
        by_id[left]["possible_duplicates"].append({"post_id": right, "reason": reason})
        by_id[right]["possible_duplicates"].append({"post_id": left, "reason": reason})
    return result
