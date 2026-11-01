"""Retain source evidence when posts share URL/content."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from api.dedup_review import possible_duplicates


def item(post_id, url, content, publisher):
    return {"post_id": post_id, "url": url, "raw_content": content, "publisher": publisher}


def test_tracking_urls_become_one_review_group_not_deleted():
    posts = [
        item("1", "https://facebook.com/page/posts/1?rdid=a", "Hello students", "Repost"),
        item("2", "https://facebook.com/page/posts/1?rdid=b", "Hello students", "Organiser"),
    ]
    groups = possible_duplicates(posts)
    assert len(groups) == 1
    assert [x["post_id"] for x in groups[0]["source_candidates"]] == ["1", "2"]
    assert groups[0]["status"] == "REVIEW_REQUIRED"
    assert groups[0]["chosen_source"] is None


def test_unrelated_posts_do_not_match():
    posts = [
        item("1", "https://example.org/a", "Learning graph neural networks workshop", "Dept A"),
        item("2", "https://example.org/b", "Donate blood this Friday with certificate", "Dept B"),
    ]
    assert possible_duplicates(posts) == []


def test_same_content_with_different_urls_requires_manual_choice():
    content = "Tập huấn học thuật và kỹ năng ngày 26 tháng 10, sinh viên đăng ký trực tiếp"
    groups = possible_duplicates([
        item("1", "https://example.org/repost", content, "Repost page"),
        item("2", "https://example.org/official", content, "Original organiser"),
    ])
    assert len(groups) == 1
    assert len(groups[0]["source_candidates"]) == 2
    assert groups[0]["chosen_source"] is None
