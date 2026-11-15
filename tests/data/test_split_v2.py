"""Verify the frozen SP1 split and blank templates without extracting any posts."""

import hashlib
import json
from collections import Counter, defaultdict

import pytest

from scripts.make_split_v2 import ROOT, build_split, json_bytes


GOLD_DIR = ROOT / "data/gold"
FIXED_GROUPS = ((45, 46), (55, 56), (81, 88, 93, 101, 103))
EXPECTED_BLANK_RECORD = {
    "post_type": None,
    "title": None,
    "domain": None,
    "multi_session": None,
    "window_open": None,
    "window_close": None,
    "duration_minutes_stated": None,
    "registration_deadline": None,
    "mode": None,
    "location": None,
    "audience_text": None,
    "audience_scope": {"cohorts": [], "programs": []},
    "mandatory_stated": None,
    "recognition_stated": None,
    "points_stated": None,
    "fee": None,
    "registration_url": None,
    "join_url": None,
    "completion_requirements": [],
}


@pytest.fixture(scope="module")
def stored():
    return json.loads((GOLD_DIR / "split_v2.json").read_bytes())


def test_source_hash_matches_after_lf_normalisation(stored):
    data = (ROOT / stored["source_file"]).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == stored["source_sha256"]


def test_rebuilt_split_matches_frozen_file():
    expected = (GOLD_DIR / "split_v2.json").read_bytes().replace(b"\r\n", b"\n")
    assert json_bytes(build_split()) == expected


def test_splits_cover_each_source_post_once(stored):
    posts = json.loads((ROOT / stored["source_file"]).read_bytes())
    expected = [(position, post["post_id"]) for position, post in enumerate(posts, 1)]
    actual = [(row["position"], row["post_id"]) for row in stored["posts"]]
    assert len(actual) == len({post_id for _, post_id in actual}) == len(expected) == 189
    assert actual == expected
    assert all(row["split"] == "dev_gold" for row in stored["posts"][:16])
    counts = Counter(row["split"] for row in stored["posts"])
    assert set(counts) == {"dev_gold", "dev_extra", "test", "pool"}
    assert counts == {split: count for split, count in stored["counts"].items() if split != "overlap"}
    for split, strata in stored["strata_by_split"].items():
        actual_strata = Counter(row["stratum"] for row in stored["posts"] if row["split"] == split)
        assert actual_strata == Counter(strata)


def test_related_groups_are_kept_in_one_split(stored):
    groups = defaultdict(set)
    for row in stored["posts"]:
        groups[row["group"]].add(row["split"])
    assert all(len(splits) == 1 for splits in groups.values())
    for positions in FIXED_GROUPS:
        assert len({stored["posts"][position - 1]["group"] for position in positions}) == 1


def test_test_overlap_and_dev_extra_sizes(stored):
    test = [row for row in stored["posts"] if row["split"] == "test"]
    overlap = [row for row in stored["posts"] if row["in_overlap"]]
    assert 58 <= len(test) <= 62
    assert len(overlap) == stored["counts"]["overlap"] == 20
    assert all(row["split"] == "test" for row in overlap)
    assert {row["stratum"] for row in overlap} == {row["stratum"] for row in test}
    assert sum(row["split"] == "dev_extra" for row in stored["posts"]) == 24


def test_test_ids_hash(stored):
    ids = sorted(row["post_id"] for row in stored["posts"] if row["split"] == "test")
    assert hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest() == stored["test_ids_sha256"]


@pytest.mark.parametrize("kind", ["test", "overlap", "dev_extra"])
def test_templates_contain_only_the_expected_ids_and_blank_values(stored, kind):
    rows = stored["posts"]
    if kind == "overlap":
        ids = [row["post_id"] for row in rows if row["in_overlap"]]
    else:
        ids = [row["post_id"] for row in rows if row["split"] == kind]
    template = json.loads((GOLD_DIR / f"{kind}_gold_v2_template.json").read_bytes())
    expected = [
        {"post_id": post_id, "labeller": "", "labelled_at": "", "minutes_spent": None,
         "record": EXPECTED_BLANK_RECORD, "year_inferred": [], "unsure": [], "notes_codes": [], "notes": ""}
        for post_id in ids
    ]
    assert template == expected
