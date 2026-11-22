"""Publication banners are not activity names; candidate identities stay frozen."""
import pytest

from sp1.extract_v2 import clean_title_candidate, extract_v2
from sp1.llm_v2 import _clean_title


@pytest.mark.parametrize("cleaner", [clean_title_candidate, _clean_title])
@pytest.mark.parametrize(("text", "expected"), [
    ("[HTTT]", None),
    ("[HTTT}", None),
    ("HTTT", None),
    ("[HTTT] -", None),
    ("[HTTT]\nHỘI THẢO KHOA HỌC", "HỘI THẢO KHOA HỌC"),
    ("[HTTT} - HỘI THẢO KHOA HỌC", "HỘI THẢO KHOA HỌC"),
    ("[httt] [WORKSHOP KỸ NĂNG SỐ]", "WORKSHOP KỸ NĂNG SỐ"),
    ("[Hỗ trợ truyền thông] - HỘI THẢO KHOA HỌC", "HỘI THẢO KHOA HỌC"),
    ("[HTTT] - [HƯỞNG ỨNG TUẦN LỄ SINH VIÊN]\n[HOẠT ĐỘNG WORKSHOP] - KỸ NĂNG SỐ",
     "[HOẠT ĐỘNG WORKSHOP] - KỸ NĂNG SỐ"),
    ("[HTTN26] - HỘI NHẬP", "[HTTN26] - HỘI NHẬP"),
    ("[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ", "[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ"),
    ("HỘI THẢO HỆ THỐNG THÔNG TIN HTTT", "HỘI THẢO HỆ THỐNG THÔNG TIN HTTT"),
])
def test_only_known_leading_publication_labels_are_removed(cleaner, text, expected):
    assert cleaner(text) == expected


@pytest.mark.parametrize("banner", ["[HTTT]", "[HTTT}", "[HỖ TRỢ TRUYỀN THÔNG]"])
def test_rules_extract_actual_name_with_original_evidence(banner):
    raw = banner + "\n[WORKSHOP KỸ NĂNG SỐ]\nĐăng ký tham gia tại văn phòng."
    result = extract_v2({"post_id": "synthetic-title", "url": "https://example.org/post",
                         "date_posted": "2026-11-18", "raw_content": raw})
    layer = result["layer_a"]
    assert layer["record"]["title"] == "WORKSHOP KỸ NĂNG SỐ"
    for span in layer["evidence"]["title"]:
        assert raw[span["start"]:span["end"]] == span["text"]


def test_media_support_and_campaign_context_do_not_hide_workshop_title():
    raw = ("[HTTT] - [HƯỞNG ỨNG TUẦN LỄ SINH VIÊN THỜI ĐẠI SỐ]\n"
           "[HOẠT ĐỘNG WORKSHOP] - KỸ NĂNG SỐ TRONG QUẢN LÝ THỜI GIAN\n"
           "Đăng ký tham gia tại văn phòng.")
    result = extract_v2({"post_id": "synthetic-campaign", "url": "https://example.org/post",
                         "date_posted": "2026-11-18", "raw_content": raw})
    assert result["layer_a"]["record"]["title"] == (
        "[HOẠT ĐỘNG WORKSHOP] - KỸ NĂNG SỐ TRONG QUẢN LÝ THỜI GIAN")
