import pytest

from sp1.devdata import dev_posts
from sp1.preprocess import preprocess
from sp1.segment import LABELS, segment


@pytest.mark.parametrize(("key", "label"), [(key, label) for key, labels in LABELS.items() for label in labels])
def test_label_synonyms(key, label):
    result = segment(preprocess(f"Title\n2) 🌟 {label.upper()}： value"))
    [field] = result.fields
    assert field.key == key and field.line_no == 2
    assert field.label.text == label.upper()
    assert field.value.text == "value"


def test_multiline_values_and_stops():
    result = segment(preprocess(
        "Title\nThời gian: Monday\n   Tuesday\nĐịa điểm: Hall\n#footer #event\n"
        "Hình thức: Online\n\nAfter the break"
    ))
    assert [f.key for f in result.fields] == ["time", "place", "mode"]
    assert [f.value.text for f in result.fields] == ["Monday\n   Tuesday", "Hall", "Online"]
    assert [s.text for s in result.hashtags] == ["#footer", "#event"]
    assert [s.text for s in result.body] == ["After the break"]


def test_empty_label_and_inline_pair():
    result = segment(preprocess("Title\n  - Thời gian: 14:00 - Địa điểm: Hall\nLiên hệ:\n\n"))
    assert [(f.key, f.value.text, f.line_no) for f in result.fields] == [
        ("time", "14:00", 2), ("place", "Hall", 2), ("contact", "", 3),
    ]


def test_bracket_tag_and_joined_title():
    result = segment(preprocess("✨ [CAMPUS CLUB] ✨\n🌟 THÔNG BÁO HỘI THẢO!\nThời gian: Monday"))
    first, joined, third = result.title_candidates
    assert first.text == "[CAMPUS CLUB]"
    assert joined.text == "[CAMPUS CLUB] ✨\n🌟 THÔNG BÁO HỘI THẢO"
    assert third.text == "THÔNG BÁO HỘI THẢO"


def test_no_labels_and_title_ranking():
    result = segment(preprocess("✨ Opening ✨\nRegular line\nSECOND TITLE\nTHIRD TITLE\n#tag"))
    assert not result.fields
    assert [s.text for s in result.title_candidates] == ["Opening", "SECOND TITLE", "THIRD TITLE"]
    assert [s.text for s in result.body] == ["Regular line"]


def test_url_trimming_email_and_unicode_hashtag():
    result = segment(preprocess("Title\nLinks (https://example.org/path). www.example.org/a!? staff@example.org #ĐăngKý"))
    assert [s.text for s in result.urls] == ["https://example.org/path", "www.example.org/a"]
    assert [s.text for s in result.emails] == ["staff@example.org"]
    assert [s.text for s in result.hashtags] == ["#ĐăngKý"]


def test_dev_spans_match_their_source_slices():
    for post in dev_posts():
        pre = preprocess(post["raw_content"])
        result = segment(pre)
        spans = (*result.title_candidates, *result.body, *result.hashtags, *result.urls, *result.emails,
                 *(span for field in result.fields for span in (field.label, field.value)))
        assert len(result.title_candidates) <= 3
        assert list(result.fields) == sorted(result.fields, key=lambda field: field.label.start)
        for span in spans:
            assert 0 <= span.start <= span.end <= len(pre.text)
            assert pre.text[span.start:span.end] == span.text
