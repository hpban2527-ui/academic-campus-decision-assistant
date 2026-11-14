import json

import pytest

from sp1 import devdata


def test_test_post_is_rejected_before_loading_source(monkeypatch):
    test_id = next(row["post_id"] for row in devdata.load_split()["posts"] if row["split"] == "test")

    def should_not_load(root):
        pytest.fail("A held-out ID must be rejected before loading the source")

    monkeypatch.setattr(devdata, "_posts", should_not_load)
    with pytest.raises(devdata.TestSetAccessError):
        devdata.get_post(test_id)


def test_dev_and_pool_follow_frozen_split_order():
    rows = devdata.load_split()["posts"]
    expected_gold = [row["post_id"] for row in rows if row["split"] == "dev_gold"]
    expected_dev = [row["post_id"] for row in rows if row["split"] in ("dev_gold", "dev_extra")]
    expected_non_test = [row["post_id"] for row in rows if row["split"] != "test"]
    assert len(expected_gold) == 16 and len(expected_dev) == 40 and len(expected_non_test) == 129
    assert devdata.dev_ids(False) == expected_gold
    assert devdata.dev_ids() == expected_dev
    assert devdata.non_test_ids() == expected_non_test
    assert [post["post_id"] for post in devdata.dev_posts(False)] == expected_gold
    assert [post["post_id"] for post in devdata.dev_posts()] == expected_dev


def test_caller_cannot_mutate_cached_posts_or_split():
    split = devdata.load_split()
    post_id = devdata.dev_ids()[0]
    split["posts"].clear()
    assert devdata.dev_ids()[0] == post_id
    post = devdata.get_post(post_id)
    post.clear()
    assert devdata.get_post(post_id)["post_id"] == post_id
    with pytest.raises(KeyError):
        devdata.get_post("synthetic-missing-id")


def test_source_loader_does_not_decode_held_out_record(tmp_path, monkeypatch):
    raw_dir = tmp_path / "data/raw"
    gold_dir = tmp_path / "data/gold"
    raw_dir.mkdir(parents=True)
    gold_dir.mkdir()
    (raw_dir / "source.json").write_bytes(
        b'[{"post_id":"dev","raw_content":"text with \\"},]\\" punctuation"},'
        b'{"raw_content":"\xff","post_id":"held"}]'
    )
    manifest = {"posts": [{"post_id": "dev", "split": "dev_gold"}, {"post_id": "held", "split": "test"}]}
    (gold_dir / "split_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(devdata, "ROOT", tmp_path)
    assert list(devdata.dev_posts()[0]) == ["post_id", "raw_content"]
    with pytest.raises(devdata.TestSetAccessError):
        devdata.get_post("held")
