import pytest
from sp1.activity_type import KEYWORDS, classify
from sp1.preprocess import preprocess


@pytest.mark.parametrize(("kind", "words"), KEYWORDS)
def test_each_type(kind, words):
    pre = preprocess(words[0])
    result = classify(pre)
    assert result["activity_type"] == kind
    for evidence in result["evidence"]:
        assert evidence["text"] == pre.original[evidence["start"]:evidence["end"]]


@pytest.mark.parametrize(("text", "expected"), [
    ("Hội thảo pháp luật", "legal_health_campaign"),
    ("Cuộc thi hiến máu tình nguyện", "blood_donation"),
    ("Workshop tuyển thành viên", "club_membership"),
    ("Không có từ khóa", "other"),
])
def test_priority(text, expected):
    assert classify(preprocess(text))["activity_type"] == expected


def test_title_beyond_prefix():
    assert classify(preprocess("x" * 601 + " hội thảo"), "hội thảo")["activity_type"] == "seminar_workshop"
