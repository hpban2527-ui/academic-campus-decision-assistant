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
