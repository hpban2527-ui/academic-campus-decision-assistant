import pytest

from sp1.dates import DateParseError, parse_point, parse_range


@pytest.mark.parametrize("span, start, end, start_def, end_def", [
    ("14h00 - 16h00 ngày 27/10/2026", "2026-10-27T14:00:00+07:00", "2026-10-27T16:00:00+07:00", False, False),
    ("14:00-16:00, 27-10-2026", "2026-10-27T14:00:00+07:00", "2026-10-27T16:00:00+07:00", False, False),
    ("8h-10h, 27/10/2026", "2026-10-27T08:00:00+07:00", "2026-10-27T10:00:00+07:00", False, False),
    ("8g30 sáng thứ Hai, 27.10.2026", "2026-10-27T08:30:00+07:00", None, False, False),
    ("2 giờ chiều ngày 27 tháng 10 năm 2026", "2026-10-27T14:00:00+07:00", None, False, False),
    ("ngày 27/10/2026", "2026-10-27T00:00:00+07:00", None, True, False),
    ("ngày 28/10/2026 đến ngày 30/10/2026", "2026-10-28T00:00:00+07:00", "2026-10-30T23:59:00+07:00", True, True),
    ("từ 28/10 đến 30/10/2026", "2026-10-28T00:00:00+07:00", "2026-10-30T23:59:00+07:00", True, True),
    ("14h ngày 27/10/2026 đến 30/10/2026", "2026-10-27T14:00:00+07:00", "2026-10-30T23:59:00+07:00", False, True),
])
def test_parse_range(span, start, end, start_def, end_def):
    r = parse_range(span)
    assert (r.start, r.end, r.start_defaulted, r.end_defaulted) == (start, end, start_def, end_def)


@pytest.mark.parametrize("span", [
    "14h00 - 16h00 ngày 27/10",   # no year anywhere in the span
    "31/02/2026",                  # impossible date
    "25h ngày 1/1/2026",           # impossible time
    "chiều thứ Năm",               # no date
])
def test_parse_range_errors(span):
    with pytest.raises(DateParseError):
        parse_range(span)


def test_decimal_points_are_not_dates():
    with pytest.raises(DateParseError):
        parse_range("cộng 1.5 điểm rèn luyện")


def test_parse_point_with_and_without_time():
    p = parse_point("Hạn đăng ký: 23h59 ngày 26/10/2026")
    assert (p.value, p.defaulted) == ("2026-10-26T23:59:00+07:00", False)
    p = parse_point("Hạn đăng ký: 26/10/2026")
    assert (p.value, p.defaulted) == ("2026-10-26T23:59:00+07:00", True)
    p = parse_point("đăng ký trước 17h00 ngày 25/10/2026")
    assert (p.value, p.defaulted) == ("2026-10-25T17:00:00+07:00", False)


def test_year_from_posted_date():
    import datetime as dt
    r = parse_range("14h00 ngày 27/10", posted=dt.date(2026, 10, 20))
    assert r.start == "2026-10-27T14:00:00+07:00" and r.year_from_posted
    r = parse_range("14h00 ngày 27/10/2026", posted=dt.date(2020, 1, 1))
    assert not r.year_from_posted


def test_range_across_new_year():
    r = parse_range("từ 30/12 đến 02/01/2027")
    assert (r.start, r.end) == ("2026-12-30T00:00:00+07:00", "2027-01-02T23:59:00+07:00")


# Synthetic regression cases for same-month day ranges (bug found in the 2026-11-14 manual check).
@pytest.mark.parametrize(("span", "start", "end"), [
    ("Hội nghị diễn ra 3 ngày (06-08/11/2026) tại trường", "2026-11-06T00:00:00+07:00", "2026-11-08T23:59:00+07:00"),
    ("Nộp hồ sơ: 05–08/10/2026.", "2026-10-05T00:00:00+07:00", "2026-10-08T23:59:00+07:00"),
    ("Tập huấn dự kiến 15 - 20/10/2026", "2026-10-15T00:00:00+07:00", "2026-10-20T23:59:00+07:00"),
])
def test_same_month_day_range(span, start, end):
    result = parse_range(span)
    assert (result.start, result.end) == (start, end)


def test_day_range_point_first_and_last():
    assert parse_point("06-08/11/2026", pick="first").value == "2026-11-06T00:00:00+07:00"
    assert parse_point("06-08/11/2026").value == "2026-11-08T23:59:00+07:00"


def test_non_ranges_unchanged():
    # A time range before a date and a dd-mm-yyyy date are not day ranges.
    result = parse_range("14h00-16h00, 06/11/2026")
    assert (result.start, result.end) == ("2026-11-06T14:00:00+07:00", "2026-11-06T16:00:00+07:00")
    assert parse_range("ngày 06-08-2026").start == "2026-08-06T00:00:00+07:00"
    assert parse_range("from 08/11 to 06/12/2026").start.startswith("2026-11-08")


def test_g_time_range_is_not_a_date():
    # "7g30 - 11g00" was read as 30/11 (bug found in the 2026-11-14 after-fix check, pool post).
    result = parse_range("7g30 - 11g00 (Sáng), Thứ Tư, Ngày 28/10/2026")
    assert (result.start, result.end) == ("2026-10-28T07:30:00+07:00", "2026-10-28T11:00:00+07:00")
