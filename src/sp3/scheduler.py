from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from enum import Enum
from itertools import combinations
from types import MappingProxyType

from sp3.contract import (
    Interval,
    Schedule,
    ScheduleType,
    inside_one,
    merge_intervals,
    same_instants,
    usable_window,
    valid_flexible_blocks,
)

__all__ = ["MAX_FLEXIBLE_PER_SET", "ScheduleResult", "ScheduleStatus", "schedule_set"]

MAX_FLEXIBLE_PER_SET = 16

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)


class ScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    UNSCHEDULABLE = "UNSCHEDULABLE"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class ScheduleResult:
    """Outcome for one activity set.

    ``blocks`` maps every activity of the set to its blocks when SCHEDULED and
    is empty otherwise. ``time_changes`` counts retained activities whose
    blocks differ from their previous blocks. ``time_changes_minimal`` is
    False only when the bounded replan enumeration stopped early.
    """

    status: ScheduleStatus
    blocks: Mapping[str, tuple[Interval, ...]] = field(default_factory=lambda: MappingProxyType({}))
    time_changes: int = 0
    time_changes_minimal: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class _Flexible:
    """One flexible activity in integer microseconds since the epoch."""

    activity_id: str
    start: int
    end: int
    duration: int


def schedule_set(
    activities: Mapping[str, Schedule],
    available_intervals: Iterable[Interval],
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    previous_blocks: Mapping[str, Sequence[Interval]] | None = None,
    keep: Iterable[str] = (),
    max_flexible_per_set: int = MAX_FLEXIBLE_PER_SET,
) -> ScheduleResult:
    """Schedule every activity of ``activities`` together, or prove it impossible.

    ``previous_blocks`` holds the previous-plan blocks of retained activities;
    entries for activities outside the set are ignored. ``keep`` names the
    KEEP_TIME activities, which must be in the set and have previous blocks.
    Computed flexible blocks are expressed in the offset of ``window_start``.
    """
    if type(max_flexible_per_set) is not int or max_flexible_per_set < 0:
        raise ValueError("max_flexible_per_set must be a non-negative integer")
    previous = {
        activity_id: tuple(blocks)
        for activity_id, blocks in (previous_blocks or {}).items()
        if activity_id in activities
    }
    kept = frozenset(keep)
    if not kept <= previous.keys():
        raise ValueError("keep must name activities of the set that have previous blocks")
    ids = sorted(activities)
    available = merge_intervals(available_intervals)

    occupied: list[Interval] = []
    for activity_id in ids:
        schedule = activities[activity_id]
        if activity_id in kept:
            blocks = previous[activity_id]
            if schedule.type is ScheduleType.FIXED:
                if not same_instants(blocks, schedule.fixed_blocks):
                    return _unschedulable("A kept FIXED activity no longer matches its sessions.")
            elif not valid_flexible_blocks(schedule, blocks, available, window_start, window_end, as_of):
                return _unschedulable("A kept flexible block is no longer a valid sitting.")
            occupied.extend(blocks)
        elif schedule.type is ScheduleType.FIXED:
            occupied.extend(schedule.fixed_blocks)
    occupied.sort()
    if not all(inside_one(block, available) for block in occupied):
        return _unschedulable("A fixed or kept block lies outside available time.")
    if any(left[1] > right[0] for left, right in zip(occupied, occupied[1:])):
        return _unschedulable("Fixed or kept blocks overlap.")
    free = _subtract([(_us(s), _us(e)) for s, e in available], [(_us(s), _us(e)) for s, e in occupied])

    items: list[_Flexible] = []
    for activity_id in ids:
        schedule = activities[activity_id]
        if activity_id in kept or schedule.type is not ScheduleType.FLEXIBLE_WINDOW:
            continue
        usable = usable_window(schedule, window_start, window_end, as_of)
        if usable is None:
            return _unschedulable("A flexible activity has no usable window.")
        item = _Flexible(activity_id, _us(usable[0]), _us(usable[1]), (schedule.duration_minutes or 0) * 60_000_000)
        if _earliest_fit(item, item.start, free) is None:
            return _unschedulable("A flexible activity fits in no free interval on its own.")
        items.append(item)
    if len(items) > max_flexible_per_set:
        return ScheduleResult(ScheduleStatus.UNDETERMINED, reason="More flexible activities than the scheduling limit.")

    placement = _place(items, free)
    if placement is None:
        return _unschedulable("No non-overlapping placement exists for the flexible activities.")
    held: tuple[_Flexible, ...] = ()
    minimal = True
    keepable = [item for item in items if item.activity_id in previous and _fits_previous(item, previous[item.activity_id], free)]
    if keepable:
        outcome = _keep_most(items, keepable, previous, free, max_flexible_per_set * (1 << max_flexible_per_set))
        if outcome is None:
            minimal = False
        elif outcome[0]:
            held, placement = outcome

    zone = window_start.tzinfo
    held_ids = {item.activity_id for item in held}
    blocks: dict[str, tuple[Interval, ...]] = {}
    for activity_id in ids:
        schedule = activities[activity_id]
        if activity_id in kept or activity_id in held_ids:
            blocks[activity_id] = previous[activity_id]
        elif schedule.type is ScheduleType.FIXED:
            blocks[activity_id] = schedule.fixed_blocks
        else:
            begin, end = placement[activity_id]
            blocks[activity_id] = ((_moment(begin, zone), _moment(end, zone)),)
    changes = sum(1 for activity_id in previous if not same_instants(blocks[activity_id], previous[activity_id]))
    return ScheduleResult(ScheduleStatus.SCHEDULED, MappingProxyType(blocks), changes, minimal)


def _unschedulable(reason: str) -> ScheduleResult:
    return ScheduleResult(ScheduleStatus.UNSCHEDULABLE, reason=reason)


def _us(moment: datetime) -> int:
    return (moment - _EPOCH) // _MICROSECOND


def _moment(value: int, zone: tzinfo | None) -> datetime:
    return (_EPOCH + value * _MICROSECOND).astimezone(zone)


def _subtract(available: Sequence[tuple[int, int]], busy: Sequence[tuple[int, int]]) -> tuple[list[int], list[int]]:
    """Free intervals (sorted, disjoint) as parallel start and end lists."""
    starts: list[int] = []
    ends: list[int] = []
    busy = sorted(busy)
    for free_start, free_end in available:
        cursor = free_start
        for busy_start, busy_end in busy:
            if busy_end <= cursor or busy_start >= free_end:
                continue
            if busy_start > cursor:
                starts.append(cursor)
                ends.append(busy_start)
            cursor = max(cursor, busy_end)
        if cursor < free_end:
            starts.append(cursor)
            ends.append(free_end)
    return starts, ends


def _earliest_fit(item: _Flexible, lower: int, free: tuple[list[int], list[int]]) -> int | None:
    """Earliest start >= ``lower`` inside the usable window and one free interval."""
    starts, ends = free
    lower = max(lower, item.start)
    for position in range(bisect_left(ends, lower + item.duration), len(starts)):
        begin = max(lower, starts[position])
        finish = begin + item.duration
        if finish > item.end:
            return None
        if finish <= ends[position]:
            return begin
    return None


def _place(items: Sequence[_Flexible], free: tuple[list[int], list[int]]) -> dict[str, tuple[int, int]] | None:
    """Exact subset DP over left-shifted sequences; None when no placement exists."""
    count = len(items)
    if count == 0:
        return {}
    size = 1 << count
    finish = [0] * size
    last = [-1] * size
    reachable = bytearray(size)
    reachable[0] = 1
    finish[0] = min(item.start for item in items)  # earliest_fit clamps to each usable window
    for mask in range(1, size):
        best: int | None = None
        best_index = -1
        remaining = mask
        while remaining:
            low = remaining & -remaining
            remaining ^= low
            rest = mask ^ low
            if not reachable[rest]:
                continue
            index = low.bit_length() - 1
            begin = _earliest_fit(items[index], finish[rest], free)
            if begin is None:
                continue
            end = begin + items[index].duration
            # Indices follow activity_id order; strict < keeps the smaller ID on ties.
            if best is None or end < best:
                best, best_index = end, index
        if best is not None:
            reachable[mask] = 1
            finish[mask] = best
            last[mask] = best_index
    if not reachable[size - 1]:
        return None
    placement: dict[str, tuple[int, int]] = {}
    mask = size - 1
    while mask:
        index = last[mask]
        rest = mask ^ (1 << index)
        begin = _earliest_fit(items[index], finish[rest], free)
        assert begin is not None
        placement[items[index].activity_id] = (begin, begin + items[index].duration)
        mask = rest
    return placement


def _fits_previous(item: _Flexible, blocks: Sequence[Interval], free: tuple[list[int], list[int]]) -> bool:
    """Whether the previous block is still a valid sitting inside free time."""
    if len(blocks) != 1:
        return False
    begin, end = _us(blocks[0][0]), _us(blocks[0][1])
    if end - begin != item.duration or begin < item.start or end > item.end:
        return False
    starts, ends = free
    position = bisect_left(ends, end)
    return position < len(starts) and starts[position] <= begin


def _keep_most(
    items: Sequence[_Flexible],
    keepable: Sequence[_Flexible],
    previous: Mapping[str, tuple[Interval, ...]],
    free: tuple[list[int], list[int]],
    budget: int,
) -> tuple[tuple[_Flexible, ...], dict[str, tuple[int, int]]] | None:
    """Hold the largest subset of ``keepable`` at its previous blocks.

    Returns the held subset and the placement of the others, or None when the
    work budget stops the enumeration before a success. An empty held subset
    means that only the caller's base placement (nothing held) succeeds.
    """
    held_blocks = {item.activity_id: (_us(previous[item.activity_id][0][0]), _us(previous[item.activity_id][0][1])) for item in keepable}
    for size in range(len(keepable), 0, -1):
        for group in combinations(keepable, size):
            spans = sorted(held_blocks[item.activity_id] for item in group)
            if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
                continue
            rest = [item for item in items if item not in group]
            cost = len(rest) * (1 << len(rest))
            if cost > budget:
                return None
            budget -= cost
            starts, ends = free
            placement = _place(rest, _subtract(list(zip(starts, ends)), spans))
            if placement is not None:
                return group, placement
    return (), {}
