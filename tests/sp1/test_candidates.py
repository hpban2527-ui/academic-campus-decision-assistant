import pytest

from sp1.candidates import build_candidates
from sp1.preprocess import preprocess
from sp1.segment import segment


def candidates(text):
    pre = preprocess(text)
    return pre, build_candidates(pre, segment(pre))


def test_order_offsets_and_masks():
    pre, found = candidates("HỘI THẢO\nThời gian: 8 giờ 30 ngày 2 tháng 11 năm 2026, 14h30 03/11/2026\n"
                            "Hạn chót: 04.11.2026 14g00 14:00\nĐạt 8/10 điểm, 23/30 câu, 3.000.000 đồng\n"
                            "Đăng ký: https://forms.gle/example\nhttps://facebook.com/noise")
    assert [c.id for c in found if c.kind == "date"] == ["D1", "D2", "D3"]
    assert [c.id for c in found if c.kind == "time"] == ["T1", "T2", "T3", "T4"]
    assert [c.text for c in found if c.kind == "url"] == ["https://forms.gle/example"]
    assert next(c for c in found if c.id == "D1").label_key == "time"
    assert next(c for c in found if c.id == "D3").label_key == "deadline"
    for c in found:
        assert c.text == pre.text[c.start:c.end]
        assert c.line_no == pre.text.count("\n", 0, c.start) + 1
        assert len(c.context) <= 160


def test_caps_and_determinism():
    text = "TITLE\n" + "\n".join(f"01/11/2026 14h30 https://example.org/{i}" for i in range(30))
    pre, first = candidates(text)
    second = build_candidates(pre, segment(pre))
    assert first == second
    assert first.flags == second.flags == ["candidates_truncated:date", "candidates_truncated:time", "candidates_truncated:url"]
    assert sum(c.kind == "date" for c in first) == 25
    assert sum(c.kind == "time" for c in first) == 15
    assert sum(c.kind == "url" for c in first) == 10


@pytest.mark.parametrize("text", ["", "30k", "đạt 8/10", "20/40 câu", "https://example.org/20/10/2026",
                                  "MSSV: 24120001\nĐiện thoại: 0901234567"])
def test_non_dates(text):
    assert not any(c.kind == "date" for c in candidates(text)[1])
