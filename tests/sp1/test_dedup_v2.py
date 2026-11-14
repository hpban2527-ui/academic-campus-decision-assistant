from sp1.dedup_v2 import apply_duplicates, group_duplicates


def rec(pid, title, opening, status="valid", posted="2026-10-01", defaults=None):
    return {"activity": {"source": {"post_id": pid, "date_posted": posted}, "title": title,
                         "window": {"open": opening, "close": None}, "mode": "offline", "location": "Room A",
                         "registration_deadline": None, "registration_url": None, "join_url": None, "fee": None,
                         "meta": {"status": status, "time_defaults": defaults or {}}}}


TEXT = "Hội thảo kỹ năng số. Thời gian: 08g00 ngày 18/10/2026. Địa điểm: phòng A. Đăng ký tại form."


def test_same_opening_and_text_merge_and_canonical_keeps_all_sources():
    a = rec("a", "Hội thảo kỹ năng số", "2026-10-18T08:00:00+07:00", status="partial", posted="2026-10-02")
    b = rec("b", "[CHIA SẺ] Hội thảo kỹ năng số", "2026-10-18T08:00:00+07:00", status="valid", posted="2026-10-03")
    result = apply_duplicates([a, b], {"a": TEXT, "b": TEXT})
    assert result["groups"] == [["a", "b"]]
    assert b["duplicate_of"] is None and a["duplicate_of"] == "b"          # valid record is canonical
    assert [s["post_id"] for s in b["sources"]] == ["b", "a"]


def test_same_template_on_another_day_never_merges():
    a = rec("a", "Seminar khoa học tháng 7", "2026-07-09T14:00:00+07:00")
    b = rec("b", "Seminar khoa học tháng 8", "2026-08-25T09:00:00+07:00")
    assert group_duplicates([a, b], {"a": TEXT, "b": TEXT}) == {"groups": [], "possible": []}


def test_similar_titles_same_opening_are_flagged_not_merged():
    a = rec("a", "Giải cờ vua sinh viên thành phố năm 2026", "2026-09-26T08:00:00+07:00")
    b = rec("b", "Giải cờ tướng sinh viên thành phố năm 2026", "2026-09-26T08:00:00+07:00")
    result = group_duplicates([a, b], {"a": "cờ vua " * 30, "b": "cờ tướng khác hẳn " * 30})
    assert result["groups"] == [] and len(result["possible"]) == 1


def test_unstated_opening_time_is_too_weak_to_merge():
    defaults = {"window_open": "date_only_0000"}
    a = rec("a", "Hội thảo", "2026-10-18T00:00:00+07:00", defaults=defaults)
    b = rec("b", "Hội thảo", "2026-10-18T00:00:00+07:00", defaults=defaults)
    assert group_duplicates([a, b], {"a": TEXT, "b": TEXT})["groups"] == []
