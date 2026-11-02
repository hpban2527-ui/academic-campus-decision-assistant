"""Resolve a UI weekly availability template into absolute SP3 intervals.

The UI may apply one entered week only once or repeat it weekly for a semester.
This adapter expands that recurrence inside the requested planning window.  The
feasibility engine continues to receive the simple ``available_intervals``
contract and remains unaware of UI recurrence rules.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence


AVAILABILITY_VERSION = "sp3-availability/0.2"
TIMEZONE = "Asia/Ho_Chi_Minh"

_REQUEST_FIELDS = {
    "availability_version",
    "timezone",
    "week_start",
    "apply_scope",
    "weekly_blocks",
    "effective_from",
    "effective_until",
    "exceptions",
    "busy_intervals",
}
_BLOCK_FIELDS = {"day_of_week", "start_time", "end_time"}
_EXCEPTION_FIELDS = {"date", "blocks"}
_EXCEPTION_BLOCK_FIELDS = {"start_time", "end_time"}
_INTERVAL_FIELDS = {"start", "end"}
_DAY_INDEX = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}
_VIETNAM_OFFSET = timedelta(hours=7)


class AvailabilityContractError(ValueError):
    """Raised when the UI availability payload is invalid or ambiguous."""


class ApplyScope(str, Enum):
    WEEK_ONLY = "WEEK_ONLY"
    SEMESTER_WEEKLY = "SEMESTER_WEEKLY"


def _fail(path: str, message: str) -> None:
    raise AvailabilityContractError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], path: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        _fail(path, f"missing fields: {', '.join(missing)}")
    if unknown:
        _fail(path, f"unexpected fields: {', '.join(unknown)}")


def _parse_date(value: Any, path: str, *, nullable: bool = False) -> date | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        _fail(path, "must be an ISO date (YYYY-MM-DD)")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(path, "must be an ISO date (YYYY-MM-DD)")
    return parsed


def _parse_clock(value: Any, path: str) -> time:
    if not isinstance(value, str) or len(value) != 5:
        _fail(path, "must use 24-hour HH:MM format")
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        _fail(path, "must use 24-hour HH:MM format")
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        _fail(path, "must use local HH:MM without seconds or an offset")
    return parsed


def _parse_timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be an ISO 8601 timestamp with an explicit offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(path, "must be an ISO 8601 timestamp with an explicit offset")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(path, "must include an explicit UTC offset")
    return parsed


def _vietnam_datetime(day: date, clock: time) -> datetime:
    # Vietnam has no daylight-saving transition; use the contract's fixed +07.
    return datetime.combine(day, clock, tzinfo=timezone(_VIETNAM_OFFSET))


def _parse_time_pair(
    value: Mapping[str, Any],
    path: str,
    *,
    include_day: bool,
) -> tuple[int | None, time, time]:
    expected = _BLOCK_FIELDS if include_day else _EXCEPTION_BLOCK_FIELDS
    _exact_fields(value, expected, path)
    day_index: int | None = None
    if include_day:
        raw_day = value["day_of_week"]
        if not isinstance(raw_day, str) or raw_day not in _DAY_INDEX:
            _fail(f"{path}.day_of_week", f"must be one of {list(_DAY_INDEX)}")
        day_index = _DAY_INDEX[raw_day]
    start = _parse_clock(value["start_time"], f"{path}.start_time")
    end = _parse_clock(value["end_time"], f"{path}.end_time")
    if start >= end:
        _fail(path, "start_time must be earlier than end_time; overnight blocks are unsupported")
    return day_index, start, end


def _merge_intervals(
    intervals: Sequence[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals, key=lambda item: (item[0], item[1])):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _subtract_intervals(
    free_intervals: Sequence[tuple[datetime, datetime]],
    busy_intervals: Sequence[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Subtract merged busy intervals without affecting unrelated free time."""

    remaining: list[tuple[datetime, datetime]] = []
    merged_busy = _merge_intervals(busy_intervals)
    for free_start, free_end in free_intervals:
        cursor = free_start
        for busy_start, busy_end in merged_busy:
            if busy_end <= cursor:
                continue
            if busy_start >= free_end:
                break
            if cursor < busy_start:
                remaining.append((cursor, min(busy_start, free_end)))
            cursor = max(cursor, busy_end)
            if cursor >= free_end:
                break
        if cursor < free_end:
            remaining.append((cursor, free_end))
    return remaining


def _calendar_version(
    payload: Mapping[str, Any],
    *,
    planning_start: datetime,
    planning_end: datetime,
) -> str:
    # The planning window is part of the resolved calendar even though the API
    # keeps it outside the availability object.
    version_input = {
        "availability": payload,
        "planning_window": {
            "start": planning_start.isoformat(),
            "end": planning_end.isoformat(),
        },
    }
    canonical = json.dumps(
        version_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"availability-{digest}"


def resolve_availability(
    request: Mapping[str, Any],
    *,
    window_start: str,
    window_end: str,
) -> dict[str, Any]:
    """Expand a week-only or semester-weekly UI schedule for one plan window."""

    payload = _mapping(request, "availability")
    _exact_fields(payload, _REQUEST_FIELDS, "availability")
    if payload["availability_version"] != AVAILABILITY_VERSION:
        _fail(
            "availability.availability_version",
            f"must equal {AVAILABILITY_VERSION!r}",
        )
    if payload["timezone"] != TIMEZONE:
        _fail("availability.timezone", f"must equal {TIMEZONE!r}")

    week_start = _parse_date(payload["week_start"], "availability.week_start")
    assert week_start is not None
    if week_start.weekday() != 0:
        _fail("availability.week_start", "must be a Monday")
    try:
        apply_scope = ApplyScope(payload["apply_scope"])
    except (TypeError, ValueError):
        _fail(
            "availability.apply_scope",
            f"must be one of {[scope.value for scope in ApplyScope]}",
        )

    raw_blocks = payload["weekly_blocks"]
    if not isinstance(raw_blocks, list):
        _fail("availability.weekly_blocks", "must be an array")
    weekly_blocks: list[tuple[int, time, time]] = []
    for index, raw_block in enumerate(raw_blocks):
        path = f"availability.weekly_blocks[{index}]"
        day_index, start, end = _parse_time_pair(
            _mapping(raw_block, path), path, include_day=True
        )
        assert day_index is not None
        weekly_blocks.append((day_index, start, end))

    configured_from = _parse_date(
        payload["effective_from"], "availability.effective_from", nullable=True
    )
    configured_until = _parse_date(
        payload["effective_until"], "availability.effective_until", nullable=True
    )
    if apply_scope is ApplyScope.WEEK_ONLY:
        if configured_from is not None or configured_until is not None:
            _fail(
                "availability",
                "effective_from/effective_until must be null for WEEK_ONLY",
            )
        effective_from = week_start
        effective_until = week_start + timedelta(days=6)
    else:
        if configured_from is None or configured_until is None:
            _fail(
                "availability",
                "effective_from and effective_until are required for SEMESTER_WEEKLY",
            )
        if configured_from > configured_until:
            _fail("availability", "effective_from must not be later than effective_until")
        if not configured_from <= week_start <= configured_until:
            _fail("availability.week_start", "must fall inside the semester effective range")
        effective_from = configured_from
        effective_until = configured_until

    raw_exceptions = payload["exceptions"]
    if not isinstance(raw_exceptions, list):
        _fail("availability.exceptions", "must be an array")
    exceptions: dict[date, list[tuple[time, time]]] = {}
    for index, raw_exception in enumerate(raw_exceptions):
        path = f"availability.exceptions[{index}]"
        exception = _mapping(raw_exception, path)
        _exact_fields(exception, _EXCEPTION_FIELDS, path)
        exception_date = _parse_date(exception["date"], f"{path}.date")
        assert exception_date is not None
        if not effective_from <= exception_date <= effective_until:
            _fail(f"{path}.date", "must fall inside the selected apply scope")
        if exception_date in exceptions:
            _fail(f"{path}.date", "duplicate exception date")
        raw_exception_blocks = exception["blocks"]
        if not isinstance(raw_exception_blocks, list):
            _fail(f"{path}.blocks", "must be an array")
        blocks: list[tuple[time, time]] = []
        for block_index, raw_block in enumerate(raw_exception_blocks):
            block_path = f"{path}.blocks[{block_index}]"
            _, start, end = _parse_time_pair(
                _mapping(raw_block, block_path),
                block_path,
                include_day=False,
            )
            blocks.append((start, end))
        exceptions[exception_date] = blocks

    raw_busy = payload["busy_intervals"]
    if not isinstance(raw_busy, list):
        _fail("availability.busy_intervals", "must be an array")
    busy_intervals: list[tuple[datetime, datetime]] = []
    for index, raw_interval in enumerate(raw_busy):
        path = f"availability.busy_intervals[{index}]"
        interval = _mapping(raw_interval, path)
        _exact_fields(interval, _INTERVAL_FIELDS, path)
        busy_start = _parse_timestamp(interval["start"], f"{path}.start")
        busy_end = _parse_timestamp(interval["end"], f"{path}.end")
        if busy_start >= busy_end:
            _fail(path, "start must be earlier than end")
        busy_intervals.append((busy_start, busy_end))

    planning_start = _parse_timestamp(window_start, "window_start")
    planning_end = _parse_timestamp(window_end, "window_end")
    if planning_start >= planning_end:
        _fail("planning_window", "window_start must be earlier than window_end")

    template_by_day: dict[int, list[tuple[time, time]]] = {
        index: [] for index in range(7)
    }
    for day_index, start, end in weekly_blocks:
        template_by_day[day_index].append((start, end))

    intervals: list[tuple[datetime, datetime]] = []
    day = effective_from
    while day <= effective_until:
        daily_blocks = exceptions.get(day, template_by_day[day.weekday()])
        for start_clock, end_clock in daily_blocks:
            start = _vietnam_datetime(day, start_clock)
            end = _vietnam_datetime(day, end_clock)
            clipped_start = max(start, planning_start)
            clipped_end = min(end, planning_end)
            if clipped_start < clipped_end:
                intervals.append((clipped_start, clipped_end))
        day += timedelta(days=1)

    merged = _subtract_intervals(_merge_intervals(intervals), busy_intervals)
    return {
        "availability_version": AVAILABILITY_VERSION,
        "calendar_version": _calendar_version(
            payload,
            planning_start=planning_start,
            planning_end=planning_end,
        ),
        "apply_scope": apply_scope.value,
        "timezone": TIMEZONE,
        "effective_from": effective_from.isoformat(),
        "effective_until": effective_until.isoformat(),
        "available_intervals": [
            {
                "start": start.isoformat(timespec="seconds"),
                "end": end.isoformat(timespec="seconds"),
            }
            for start, end in merged
        ],
    }
