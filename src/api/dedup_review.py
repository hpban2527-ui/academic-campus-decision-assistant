"""Read-only cross-post audit. Duplicates are proposals, not automatic deletes."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from api.lead_contract import canonical_url
from sp1.deduplication import compute_minhash


def possible_duplicates(posts: list[dict[str, Any]], similarity_cutoff: float = 0.75) -> list[dict]:
    """Return all source references in clusters and require a human source choice."""
    if not 0 < similarity_cutoff <= 1:
        raise ValueError("Invalid similarity cutoff")
    if not isinstance(posts, list):
        raise ValueError("Expected posts list")
    parent = list(range(len(posts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        a, b = root(i), root(j)
        if a != b:
            parent[max(a, b)] = min(a, b)

    refs = []
    for i, p in enumerate(posts):
        try:
            url = canonical_url(p.get("url") or p.get("source", {}).get("URL_post") or "")
        except (ValueError, TypeError):
            url = None
        refs.append({
            "post_id": str(p.get("post_id") or p.get("activity_id") or f"row-{i}"),
            "url": url, "publisher": p.get("publisher") or (p.get("source") or {}).get("publisher"),
            "raw_content": p.get("raw_content") or "",
        })
    hashes = [compute_minhash(x["raw_content"]) if x["raw_content"] else None for x in refs]
    reasons: dict[tuple[int, int], dict] = {}
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            same_url = refs[i]["url"] is not None and refs[i]["url"] == refs[j]["url"]
            same_post_id = refs[i]["post_id"] == refs[j]["post_id"]
            similarity = hashes[i].jaccard(hashes[j]) if hashes[i] is not None and hashes[j] is not None else 0
            if same_url or same_post_id or similarity >= similarity_cutoff:
                union(i, j)
                reasons[(i, j)] = {
                    "first": refs[i]["post_id"], "second": refs[j]["post_id"],
                    "reason": "same_url" if same_url else ("same_post_id" if same_post_id else "similar_text"),
                    "similarity": round(float(similarity), 3),
                }
    clusters: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(posts)):
        clusters[root(idx)].append(idx)
    return [
        {
            "source_candidates": [
                {"post_id": refs[k]["post_id"], "url": refs[k]["url"], "publisher": refs[k]["publisher"]}
                for k in members
            ],
            "matches": [
                r for (i, j), r in reasons.items() if i in members and j in members
            ],
            "chosen_source": None,
            "status": "REVIEW_REQUIRED",
        }
        for members in clusters.values() if len(members) > 1
    ]
