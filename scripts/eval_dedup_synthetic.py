"""Evaluate dedup_v2 on synthetic reposts built from non-test posts (rules-only extraction).

Positives: for each sampled post with a stated opening time, three reposts on another channel:
  exact  - same text, other publisher and post_id
  shared - "[CHIA SẺ]" prefix, hashtags removed, a source line appended
  edited - line order of the body kept, one non-schedule line dropped, emoji/spacing changes
  summary - only the first line and the lines with a date, time or place label (a short repost)
Negatives: every pair of real non-test posts (should never merge).
Writes reports/sp1_dedup_eval.md.
"""

import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.dedup_v2 import group_duplicates
from sp1.devdata import get_post, non_test_ids
from sp1.evaluate import wilson
from sp1.extract_v2 import run_pipeline
from sp1.normalize import load_config

SEED = 20261114
N = 20


def variants(post):
    text = post["raw_content"]
    no_tags = "\n".join(line for line in text.split("\n") if not line.strip().startswith("#"))
    lines = text.split("\n")
    keep = [i for i, line in enumerate(lines) if line.strip() and not re.search(r"\d", line)]
    drop = keep[len(keep) // 2] if keep else None
    edited = "\n".join(re.sub(r"\s+", " ", line).strip() for i, line in enumerate(lines) if i != drop)
    summary = "\n".join([lines[0]] + [line for line in lines[1:] if re.search(
        r"thời gian|địa điểm|ngày|\d{1,2}\s*[gh:]\s*\d{0,2}", line, re.I)])
    return {"exact": text, "shared": "[CHIA SẺ] " + no_tags + "\nNguồn: fanpage đơn vị tổ chức",
            "edited": edited, "summary": summary}


def record(post, config):
    return {"activity": run_pipeline(post, config)["activity"]}


def main():
    config = load_config()
    posts = [get_post(pid) for pid in non_test_ids()]
    real = [record(p, config) for p in posts]
    texts = {p["post_id"]: p["raw_content"] for p in posts}
    # Negatives: the real corpus alone must produce no merge.
    real_result = group_duplicates(real, texts)
    eligible = [(p, r) for p, r in zip(posts, real)
                if r["activity"]["window"]["open"] and "window_open" not in r["activity"]["meta"]["time_defaults"]]
    sample = random.Random(SEED).sample(eligible, min(N, len(eligible)))
    found = Counter()
    misses = []
    for post, original in sample:
        for kind, text in variants(post).items():
            copy = dict(post, post_id=f"{post['post_id']}-synthetic-{kind}", raw_content=text,
                        publisher="Synthetic repost channel", url=f"https://example.invalid/{kind}")
            dup = record(copy, config)
            result = group_duplicates([original, dup], {post["post_id"]: post["raw_content"], copy["post_id"]: text})
            hit = any(copy["post_id"] in g for g in result["groups"])
            found[kind] += hit
            if not hit:
                misses.append((kind, post["post_id"][:16], original["activity"]["window"]["open"],
                               dup["activity"]["window"]["open"]))
    n = len(sample)
    lines = ["# SP1 duplicate grouping evaluation (synthetic reposts)", "",
             f"Rules-only extraction on non-test posts. Seed {SEED}. Intervals are Wilson 95%.",
             f"Synthetic positives use {n} sampled posts with a stated opening time; each gets 4 reposts.", "",
             "| Repost kind | Grouped with original |", "| --- | --- |"]
    for kind in ("exact", "shared", "edited", "summary"):
        low, high = wilson(found[kind], n)
        lines.append(f"| {kind} | {found[kind]}/{n} [{low:.0%}, {high:.0%}] |")
    pairs = len(real) * (len(real) - 1) // 2
    merged = sum(len(g) - 1 for g in real_result["groups"])
    lines += ["", f"Real non-test corpus: {len(real)} posts, {pairs} pairs. Merges: {merged} "
              f"(expected 0: the corpus was compiled with one post per activity; not independently labelled). "
              f"Possible-duplicate flags: {len(real_result['possible'])}.", ""]
    lines += ["Limitation: reposts are generated from the original text, so they share wording. A repost rewritten",
              "in other words with a different title is not grouped; at most it is flagged when titles overlap.", ""]
    if misses:
        lines += ["Misses (kind, post, original opening, repost opening):", ""]
        lines += [f"- {m}" for m in misses]
    (ROOT / "reports/sp1_dedup_eval.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
