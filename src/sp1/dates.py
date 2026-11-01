"""Deterministic parsing of Vietnamese date/time spans into ISO 8601 (+07:00).

The extractor (regex or LLM) only finds the span of text that states a time,
e.g. "14h00 - 16h00 ngày 27/10/2026". This module turns that span into
datetimes. Conventions (ADR 0001, D4):
- date without time: start -> 00:00 (trace "date_only_0000"),
  end and registration deadline -> 23:59 (trace "date_only_2359");
- a year missing from one date may be taken from another date in the SAME span
  ("từ 28/10 đến 30/10/2026"); never from outside the span. If the year comes
  from a later date and would put the earlier date after it, the earlier date
  gets the previous year ("từ 30/12 đến 02/01/2027" -> 30/12/2026);
- end is set only when the span states a range (two dates or two times);
- if NO date in the span has a year and the posting date is known, the year is
  taken from the posting date: the posted year, or the next year if the date
  would fall more than 60 days before the post (a January event announced in
  December). This is traced (year_from_posted) so it is never silent;
- money ("3.000.000 đồng", "30k") and score ratios ("20/40 câu", "đạt 8/10")
  are never dates (mask_non_dates, also used by regex_baseline);
- an activity in several rounds, one span per round (parse_rounds): start from
  the chronologically first round alone, end from the last round alone.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

TZ_SUFFIX = "+07:00"
DEFAULT_START = (0, 0)
DEFAULT_END = (23, 59)

# dd/mm[/yyyy] or dd-mm[-yyyy]; not glued to digits, "h" or ":" (avoids "14h00-16h00").
_DATE_SLASH = re.compile(
    r"(?<![\d:hH])(\d{1,2})\s*([/-])\s*(\d{1,2})(?:\s*\2\s*(\d{4}|\d{2}))?(?![\d:hH])"
)
# dd.mm.yyyy only with a year (avoids "1.5 điểm").
_DATE_DOT = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?![\d.])")
# "ngày 27 tháng 10 năm 2026"
_DATE_WORDS = re.compile(
    r"(\d{1,2})\s+tháng\s+(\d{1,2})(?:\s*(?:năm|,)\s*(\d{4}))?", re.IGNORECASE
)

# 14h00, 14h, 14:00, 8g30, "14 giờ 30 (phút)"; optionally followed by "sáng" / "trưa" / "chiều" / "tối".
_TIME = re.compile(
    r"(?<![\d:])(\d{1,2})\s*(?:h(\d{2})?(?![a-zA-ZÀ-ỹ])|:(\d{2})(?!\d)|g(\d{2})(?!\d)"
    r"|giờ(?:\s*(\d{1,2})(?:\s*phút)?)?)"
    r"(?:\s*(sáng|trưa|chiều|tối))?",
    re.IGNORECASE,
)

# Number groups that look like dates but are not (D15): money with thousand separators or a currency,
# and score ratios followed by "câu" / "điểm" or preceded by "đúng" / "đạt". "câu lạc bộ" (club) and "điểm danh"
# (attendance) after a real date are not scores.
_NOT_A_DATE = re.compile(
    r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?!\d)"
    r"|(?<![\d.,])\d+(?:[.,]\d+)?\s*(?:đồng|đ|vnđ|vnd|k|nghìn|ngàn)(?!\w)"
    r"|(?<!\w)(?:đúng|đạt)(?:\s+(?:từ|tối\s+thiểu|ít\s+nhất))?\s+\d+\s*/\s*\d+"
    r"|(?<![\d/])\d+\s*/\s*\d+(?![\d/])(?=\s*(?:câu(?!\s+lạc\s+bộ)|điểm(?!\s+danh)))",
    re.IGNORECASE,
)


class DateParseError(ValueError):
    """Span has no usable date, a missing year, or an impossible date/time."""


@dataclass(frozen=True)
class _Date:
    pos: int
    day: int
    month: int
    year: int | None


@dataclass(frozen=True)
class _Time:
    pos: int
    hour: int
    minute: int


@dataclass(frozen=True)
class RangeResult:
    start: str
    start_defaulted: bool
    end: str | None
    end_defaulted: bool
    year_from_posted: bool = False


@dataclass(frozen=True)
class PointResult:
    value: str
    defaulted: bool
    year_from_posted: bool = False


def mask_non_dates(text: str) -> str:
    """Blank out money and score ratios, keeping every other character at its position."""
    return _NOT_A_DATE.sub(lambda m: " " * len(m.group(0)), text)


def _year(raw: str | None) -> int | None:
    if raw is None:
        return None
    y = int(raw)
    return 2000 + y if y < 100 else y


def _find_dates(span: str) -> list[_Date]:
    found: list[_Date] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return all(m.end() <= a or m.start() >= b for a, b in taken)

    for m in _DATE_WORDS.finditer(span):
        found.append(_Date(m.start(), int(m.group(1)), int(m.group(2)), _year(m.group(3))))
        taken.append((m.start(), m.end()))
    for m in _DATE_DOT.finditer(span):
        if free(m):
            found.append(_Date(m.start(), int(m.group(1)), int(m.group(2)), _year(m.group(3))))
            taken.append((m.start(), m.end()))
    for m in _DATE_SLASH.finditer(span):
        if free(m):
            found.append(_Date(m.start(), int(m.group(1)), int(m.group(3)), _year(m.group(4))))
            taken.append((m.start(), m.end()))
    found.sort(key=lambda d: d.pos)
    return found


def _find_times(span: str, date_ranges: list[tuple[int, int]]) -> list[_Time]:
    times: list[_Time] = []
    for m in _TIME.finditer(span):
        if any(a <= m.start() < b for a, b in date_ranges):
            continue
        hour = int(m.group(1))
        minute_raw = m.group(2) or m.group(3) or m.group(4) or m.group(5)
        minute = int(minute_raw) if minute_raw else 0
        part = (m.group(6) or "").lower()
        if part in ("chiều", "tối") and hour < 12:
            hour += 12
        elif part == "trưa" and hour < 6:
            hour += 12
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise DateParseError(f"impossible time in span: {m.group(0)!r}")
        times.append(_Time(m.start(), hour, minute))
    return times


def _date_spans(span: str) -> list[tuple[int, int]]:
    spans = []
    for rx in (_DATE_WORDS, _DATE_DOT, _DATE_SLASH):
        spans += [(m.start(), m.end()) for m in rx.finditer(span)]
    return spans


POSTED_LOOKBACK_DAYS = 60


def _copy_year(d: _Date, src: _Date) -> _Date:
    """Give d the year of src (another date in the span), one year earlier across New Year."""
    year = src.year
    try:
        if d.pos < src.pos and dt.date(year, d.month, d.day) > dt.date(year, src.month, src.day):  # type: ignore[arg-type]
            year -= 1  # type: ignore[operator]
    except ValueError as e:
        raise DateParseError(f"impossible date {d.day}/{d.month}") from e
    return _Date(d.pos, d.day, d.month, year)


def _fill_years(dates: list[_Date], posted: dt.date | None) -> tuple[list[_Date], bool]:
    known = [d for d in dates if d.year is not None]
    if known:
        return [d if d.year is not None else _copy_year(d, known[-1]) for d in dates], False
    if posted is None:
        raise DateParseError("no year stated in the span and no posting date")
    out = []
    for d in dates:
        year = posted.year
        try:
            if dt.date(year, d.month, d.day) < posted - dt.timedelta(days=POSTED_LOOKBACK_DAYS):
                year += 1
        except ValueError as e:
            raise DateParseError(f"impossible date {d.day}/{d.month}") from e
        out.append(_Date(d.pos, d.day, d.month, year))
    return out, True


def _iso(d: _Date, hm: tuple[int, int]) -> str:
    try:
        dt.date(d.year, d.month, d.day)  # type: ignore[arg-type]
    except ValueError as e:
        raise DateParseError(f"impossible date {d.day}/{d.month}/{d.year}") from e
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}T{hm[0]:02d}:{hm[1]:02d}:00{TZ_SUFFIX}"


def parse_range(span: str, posted: dt.date | None = None) -> RangeResult:
    """Parse an activity time span into start (and end if a range is stated)."""
    span = mask_non_dates(span)
    dates = _find_dates(span)
    if not dates:
        raise DateParseError("no date in the span")
    dates, from_posted = _fill_years(dates, posted)
    times = _find_times(span, _date_spans(span))

    start_hm = (times[0].hour, times[0].minute) if times else DEFAULT_START
    start = _iso(dates[0], start_hm)

    has_end_date = len(dates) > 1
    has_end_time = len(times) > 1
    if not (has_end_date or has_end_time):
        return RangeResult(start, not times, None, False, from_posted)

    end_date = dates[-1] if has_end_date else dates[0]
    end_hm = (times[-1].hour, times[-1].minute) if has_end_time else DEFAULT_END
    # Two dates and one time: the time belongs to the start ("14h ngày 27/10 đến 30/10").
    return RangeResult(start, not times, _iso(end_date, end_hm), not has_end_time, from_posted)


def parse_point(span: str, posted: dt.date | None = None) -> PointResult:
    """Parse a single moment such as a registration deadline (last date/time in the span)."""
    span = mask_non_dates(span)
    dates = _find_dates(span)
    if not dates:
        raise DateParseError("no date in the span")
    dates, from_posted = _fill_years(dates, posted)
    times = _find_times(span, _date_spans(span))
    hm = (times[-1].hour, times[-1].minute) if times else DEFAULT_END
    return PointResult(_iso(dates[-1], hm), not times, from_posted)


def parse_rounds(spans: list[str], posted: dt.date | None = None) -> RangeResult:
    """One activity held in several rounds, one span per round (D16). Start = the chronologically first
    round parsed alone; end = the last round parsed alone (its end time, else its time or date with the
    end default). Times are never merged across spans; any round that does not parse fails the whole."""
    rounds = sorted(((parse_range(s, posted), s) for s in spans), key=lambda rs: rs[0].start)
    first, last_span = rounds[0][0], rounds[-1][1]
    end = parse_point(last_span, posted)
    return RangeResult(first.start, first.start_defaulted, end.value, end.defaulted,
                       first.year_from_posted or end.year_from_posted)
