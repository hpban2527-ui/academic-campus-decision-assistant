"""Freeze SP1 evaluation IDs and write blank labelling templates."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = "data/raw/source.json"
GOLD_FILE = "data/gold/source_gold.json"
SOURCE_SHA256 = "c6bca5873981bd1c70a7b2f82e2a258fdfaec5471313df35cf2250c4b754dd0e"
GOLD_SHA256 = "a5d88aee2ef2635fac1392e6c6593d218a9cc95a7fa0f510cd86ee906121644d"
CREATED = "2026-11-13"
SEED = 20261113
STRATA = ("mandatory", "quiz_threshold", "info_candidate", "multi_date", "online", "other")
SPLITS = ("dev_gold", "dev_extra", "test", "pool")
FIXED_GROUPS = ((45, 46), (55, 56), (81, 88, 93, 101, 103))
SIMILARITY_RULE = "exact Jaccard on NFC-lowercased char 5-shingles >= 0.60, plus CS-1..CS-3"
DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
SESSION = re.compile(
    r"\b(?:vòng|buổi)\s+(?:thứ\s+)?"
    r"(?:\d+|i{1,3}|iv|vi{0,3}|ix|x|nhất|một|hai|ba|tư|bốn|năm|sáu|bảy|tám|chín|mười|đầu|cuối)\b"
)
RECORD_FIELDS = (
    "post_type", "title", "domain", "multi_session", "window_open", "window_close",
    "duration_minutes_stated", "registration_deadline", "mode", "location", "audience_text",
    "audience_scope", "mandatory_stated", "recognition_stated", "points_stated", "fee",
    "registration_url", "join_url", "completion_requirements",
)
TEMPLATES = {
    "test": "test_gold_v2_template.json",
    "overlap": "overlap_gold_v2_template.json",
    "dev_extra": "dev_extra_gold_v2_template.json",
}


def lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_input(root: Path, filename: str, expected_hash: str, count: int) -> list[dict]:
    data = lf_bytes(root / filename)
    actual_hash = sha256(data)
    if actual_hash != expected_hash:
        raise ValueError(f"{filename}: LF-normalised SHA-256 {actual_hash}, expected {expected_hash}")
    records = json.loads(data)
    if not isinstance(records, list) or len(records) != count:
        raise ValueError(f"{filename}: expected an array of {count} entries")
    return records


def primary_stratum(text: str) -> str:
    if re.search(r"bắt buộc|bị trừ điểm|trừ điểm", text):
        return "mandatory"
    if re.search(r"\d{1,3}\s*%|\d+\s*/\s*\d+\s*câu", text) and re.search(
        r"quiz|bài thi|trắc nghiệm|câu hỏi", text
    ):
        return "quiz_threshold"
    if re.search(r"kết quả|tổng kết|vinh danh|chúc mừng", text):
        return "info_candidate"
    if len(set(DATE.findall(text))) >= 3 or SESSION.search(text):
        return "multi_date"
    if re.search(r"online|trực tuyến|zoom|google meet|meet\.google", text):
        return "online"
    return "other"


def related_groups(texts: Sequence[str]) -> list[tuple[int, ...]]:
    """Return connected components as 1-based positions, ordered by first member."""
    parents = list(range(len(texts) + 1))

    def find(position: int) -> int:
        while position != parents[position]:
            parents[position] = parents[parents[position]]
            position = parents[position]
        return position

    def union(first: int, second: int) -> None:
        first, second = sorted((find(first), find(second)))
        parents[second] = first

    for group in FIXED_GROUPS:
        for member in group[1:]:
            union(group[0], member)

    shingles = []
    for text in texts:
        text = " ".join(text.split())
        shingles.append({text[i:i + 5] for i in range(len(text) - 4)})
    for (first, a), (second, b) in combinations(enumerate(shingles, 1), 2):
        intersection = len(a & b)
        union_size = len(a) + len(b) - intersection
        if union_size and 5 * intersection >= 3 * union_size:
            union(first, second)

    by_root: dict[int, list[int]] = {}
    for position in range(1, len(parents)):
        by_root.setdefault(find(position), []).append(position)
    return [tuple(positions) for positions in by_root.values()]


def quotas(sizes: list[int], target: int) -> list[int]:
    """Give rare strata half their posts, then apply largest remainder."""
    result = [(size + 1) // 2 if size <= 10 else 0 for size in sizes]
    common = [index for index, size in enumerate(sizes) if size > 10]
    remaining = target - sum(result)
    common_size = sum(sizes[index] for index in common)
    if not 0 <= remaining <= common_size:
        raise ValueError("Rare strata and proportional allocation cannot reach the target")
    if common_size:
        for index in common:
            result[index] = remaining * sizes[index] // common_size
        by_remainder = sorted(common, key=lambda i: (-(remaining * sizes[i] % common_size), i))
        for index in by_remainder[:target - sum(result)]:
            result[index] += 1
    return result


def select_groups(
    buckets: list[list[tuple[int, ...]]],
    ids: list[str],
    target: int,
    seed: int,
    tolerance: int = 0,
) -> set[tuple[int, ...]]:
    """Sample whole groups, meeting quotas as closely as the group sizes allow."""
    sizes = [sum(map(len, bucket)) for bucket in buckets]
    desired = quotas(sizes, target)
    rng = random.Random(seed)
    limit = target + tolerance
    choices: dict[int, tuple[tuple[int, int, int], tuple[tuple[int, ...], ...]]] = {0: ((0, 0, 0), ())}
    for bucket, size, quota in zip(buckets, sizes, desired):
        groups = sorted(bucket, key=lambda group: tuple(sorted(ids[pos] for pos in group)))
        rng.shuffle(groups)

        # Keep the first subset in seeded order that reaches each attainable post count.
        by_count: dict[int, tuple[tuple[int, ...], ...]] = {0: ()}
        for group in groups:
            for count, selected in list(by_count.items()):
                if count + len(group) <= limit:
                    by_count.setdefault(count + len(group), selected + (group,))

        updated = {}
        for total, (cost, selected) in choices.items():
            for count, subset in by_count.items():
                if total + count > limit:
                    continue
                delta = abs(count - quota)
                score = (cost[0] + (delta if size <= 10 else 0), cost[1] + delta,
                         cost[2] + (max(0, quota - count) if size <= 10 else 0))
                previous = updated.get(total + count)
                if previous is None or score < previous[0]:
                    updated[total + count] = (score, selected + subset)
        choices = updated

    feasible = [count for count in choices if abs(count - target) <= tolerance]
    if not feasible:
        raise ValueError(f"Whole groups cannot supply {target} posts within tolerance {tolerance}")
    count = min(feasible, key=lambda count: (abs(count - target), choices[count][0], count))
    return set(choices[count][1])


def select_overlap(test_rows: list[dict]) -> set[str]:
    rng = random.Random(SEED + 1)
    all_ids = sorted(row["post_id"] for row in test_rows)
    by_stratum = {stratum: [] for stratum in STRATA}
    for row in sorted(test_rows, key=lambda row: row["post_id"]):
        by_stratum[row["stratum"]].append(row["post_id"])
    chosen = {rng.choice(candidates) for candidates in by_stratum.values() if candidates}
    return chosen.union(rng.sample([post_id for post_id in all_ids if post_id not in chosen], 20 - len(chosen)))


def build_split(root: Path = ROOT) -> dict:
    raw = checked_input(root, SOURCE_FILE, SOURCE_SHA256, 189)
    gold = checked_input(root, GOLD_FILE, GOLD_SHA256, 20)
    ids = [""] + [post["post_id"] for post in raw]
    gold_ids = {entry["post_id"] for entry in gold}
    if len(set(ids[1:])) != 189 or len(gold_ids) != 20 or gold_ids.intersection(ids[1:]) != set(ids[1:17]):
        raise ValueError("Only positions 1–16 must be shared with v1 gold, with unique source and gold IDs")

    texts = [unicodedata.normalize("NFC", post["raw_content"]).lower() for post in raw]
    strata = [""] + [primary_stratum(text) for text in texts]
    groups = related_groups(texts)
    buckets: list[list[tuple[int, ...]]] = [[] for _ in STRATA]
    for group in groups:
        if group[0] > 16:
            index = min(STRATA.index(strata[pos]) for pos in group)
            buckets[index].append(group)
    test = select_groups(buckets, ids, 60, SEED, tolerance=2)
    remaining = [[group for group in bucket if group not in test] for bucket in buckets]
    dev_extra = select_groups(remaining, ids, 24, SEED + 2)

    group_splits = dict.fromkeys(test, "test") | dict.fromkeys(dev_extra, "dev_extra")
    rows = []
    for number, group in enumerate(groups, 1):
        split = "dev_gold" if group[0] <= 16 else group_splits.get(group, "pool")
        for pos in group:
            rows.append({"position": pos, "post_id": ids[pos], "split": split,
                         "stratum": strata[pos], "group": f"G{number:03d}", "in_overlap": False})
    rows.sort(key=lambda row: row["position"])
    test_rows = [row for row in rows if row["split"] == "test"]
    overlap = select_overlap(test_rows)
    strata_by_split = {split: dict.fromkeys(STRATA, 0) for split in SPLITS}
    for row in rows:
        row["in_overlap"] = row["post_id"] in overlap
        strata_by_split[row["split"]][row["stratum"]] += 1
    counts = {split: sum(totals.values()) for split, totals in strata_by_split.items()}
    counts["overlap"] = len(overlap)
    test_ids = sorted(row["post_id"] for row in test_rows)
    return {
        "split_version": "2.0.0", "created": CREATED, "seed": SEED,
        "source_file": SOURCE_FILE, "source_sha256": SOURCE_SHA256, "similarity_rule": SIMILARITY_RULE,
        "counts": counts, "test_ids_sha256": sha256("\n".join(test_ids).encode("utf-8")),
        "strata_by_split": strata_by_split, "posts": rows,
    }


def blank_entry(post_id: str) -> dict:
    record = dict.fromkeys(RECORD_FIELDS)
    record["audience_scope"] = {"cohorts": [], "programs": []}
    record["completion_requirements"] = []
    return {"post_id": post_id, "labeller": "", "labelled_at": "", "minutes_spent": None,
            "record": record, "year_inferred": [], "unsure": [], "notes_codes": [], "notes": ""}


def json_bytes(data: dict | list) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def output_files(split: dict) -> dict[str, bytes]:
    rows = split["posts"]
    return {
        "split_v2.json": json_bytes(split),
        TEMPLATES["test"]: json_bytes([blank_entry(row["post_id"]) for row in rows if row["split"] == "test"]),
        TEMPLATES["overlap"]: json_bytes([blank_entry(row["post_id"]) for row in rows if row["in_overlap"]]),
        TEMPLATES["dev_extra"]: json_bytes([blank_entry(row["post_id"]) for row in rows if row["split"] == "dev_extra"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/gold",
                        help="Existing directory for the split and three blank templates")
    output_dir = parser.parse_args().output_dir
    try:
        split = build_split()
        files = {output_dir / name: data for name, data in output_files(split).items()}
        for path, data in files.items():
            if path.exists() and lf_bytes(path) != data:
                raise ValueError(f"Refusing to overwrite differing file: {path}")
        for path, data in files.items():
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(data)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(split["counts"]))


if __name__ == "__main__":
    main()
