"""Seeded property tests: the scheduler against an independent grid brute force.

Every instance lives on a 15-minute grid. The brute force tries every grid
start of every flexible activity, so on these instances it is exhaustive:
whenever a valid schedule exists, a left-shifted one on the grid exists too.
It shares no code with the scheduler apart from the Schedule data type.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import random
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sp3.contract import Schedule, ScheduleType
from sp3.scheduler import ScheduleStatus, schedule_set

INSTANCES = 100
REPLAN_INSTANCES = 100
SLOT = timedelta(minutes=15)
BASE = datetime.fromisoformat("2026-11-02T07:00:00+07:00")
SLOTS = 40  # 07:00-17:00


def moment(slot: int) -> datetime:
    return BASE + slot * SLOT


def slot_of(value: datetime) -> int:
    offset = value - BASE
    assert offset % SLOT == timedelta(0), "every scheduled time must stay on the grid"
    return offset // SLOT


def random_instance(rng: random.Random, *, replan: bool):
    # Free time: the day minus a few busy gaps, given as possibly overlapping pieces.
    busy = set()
    for _ in range(rng.randint(0, 3)):
        start = rng.randint(0, SLOTS - 1)
        busy |= set(range(start, start + rng.randint(1, 6)))
    free = [cell for cell in range(SLOTS) if cell not in busy]
    available = []
    for cell in free:
        if available and available[-1][1] == cell:
            available[-1] = (available[-1][0], cell + 1)
        else:
            available.append((cell, cell + 1))
    if len(available) > 1 and rng.random() < 0.5:
        # Split one piece into two overlapping pieces; the scheduler must merge them.
        start, end = available.pop(rng.randrange(len(available)))
        middle = (start + end) // 2
        available += [(start, max(middle + 1, start + 1)), (middle, end)]
        rng.shuffle(available)
    plan_start = rng.choice([-400, -400, -400, rng.randint(-2, 6)])
    plan_end = rng.choice([400, 400, 400, rng.randint(26, 42)])
    as_of = rng.choice([-400, -400, rng.randint(-4, 8)])
    activities: dict[str, tuple] = {}
    names = iter("ABCDEFGHJK")
    for _ in range(rng.randint(0, 2)):
        blocks, cursor = [], rng.choice(free) if free and rng.random() < 0.85 else rng.randint(0, 36)
        for _ in range(rng.choice([1, 1, 2])):
            length = rng.randint(1, 4)
            blocks.append((cursor, cursor + length))
            cursor += length + rng.randint(0, 10)
        activities[next(names)] = ("FIXED", tuple(blocks))
    for _ in range(rng.randint(1, 5)):
        window_start = rng.randint(-2, 32)
        length = rng.randint(3, 20)
        activities[next(names)] = ("FLEXIBLE", (window_start, window_start + length), rng.randint(1, min(length, 6)))
    previous: dict[str, tuple] = {}
    keep: set[str] = set()
    if replan:
        for name, spec in activities.items():
            if spec[0] == "FIXED" and rng.random() < 0.4:
                shift = rng.choice([0, 0, rng.randint(-3, 3)])
                previous[name] = tuple((start + shift, end + shift) for start, end in spec[1])
            elif spec[0] == "FLEXIBLE" and rng.random() < 0.8:
                (low, high), duration = spec[1], spec[2]
                start = rng.randint(low, high - duration) if rng.random() < 0.8 else rng.randint(low - 2, high)
                previous[name] = ((start, start + duration),)
        keep = {name for name in previous if rng.random() < 0.15}
    return {"available": available, "plan": (plan_start, plan_end), "as_of": as_of,
            "activities": activities, "previous": previous, "keep": keep}


def to_schedules(instance):
    schedules = {}
    for name, spec in instance["activities"].items():
        if spec[0] == "FIXED":
            schedules[name] = Schedule(ScheduleType.FIXED, fixed_blocks=tuple((moment(s), moment(e)) for s, e in spec[1]))
        else:
            (start, end), duration = spec[1], spec[2]
            schedules[name] = Schedule(ScheduleType.FLEXIBLE_WINDOW, window_start=moment(start), window_end=moment(end), duration_minutes=duration * 15)
    return schedules


def run_scheduler(instance):
    plan_start, plan_end = instance["plan"]
    return schedule_set(
        to_schedules(instance),
        [(moment(s), moment(e)) for s, e in instance["available"]],
        window_start=moment(plan_start),
        window_end=moment(plan_end),
        as_of=moment(instance["as_of"]),
        previous_blocks={name: [(moment(s), moment(e)) for s, e in blocks] for name, blocks in instance["previous"].items()},
        keep=instance["keep"],
    )


# Independent model in grid cells ------------------------------------------------------

def free_cells(instance) -> set[int]:
    return {cell for start, end in instance["available"] for cell in range(start, end)}


def usable(instance, spec) -> tuple[int, int]:
    (start, end), plan = spec[1], instance["plan"]
    return max(start, plan[0], instance["as_of"]), min(end, plan[1])


def cells(block) -> range:
    return range(block[0], block[1])


def brute_force(instance):
    """Return (schedulable, minimum time changes) by trying every grid start."""
    available = free_cells(instance)
    activities, previous, keep = instance["activities"], instance["previous"], instance["keep"]
    used: set[int] = set()
    forced = 0
    for name, spec in activities.items():
        if name in keep:
            blocks = previous[name]
            if spec[0] == "FIXED" and blocks != spec[1]:
                return False, None
            if spec[0] == "FLEXIBLE":
                low, high = usable(instance, spec)
                (start, end), = blocks if len(blocks) == 1 else ((None, None),)
                if start is None or end - start != spec[2] or start < low or end > high:
                    return False, None
        elif spec[0] == "FIXED":
            blocks = spec[1]
            forced += name in previous and previous[name] != blocks
        else:
            continue
        for block in blocks:
            if not set(cells(block)) <= available or used & set(cells(block)):
                return False, None
            used |= set(cells(block))
    flexible = sorted(name for name, spec in activities.items() if spec[0] == "FLEXIBLE" and name not in keep)
    options = {}
    for name in flexible:
        low, high = usable(instance, activities[name])
        duration = activities[name][2]
        starts = [s for s in range(low, high - duration + 1) if all(c in available and c not in used for c in range(s, s + duration))]
        own = previous.get(name)
        # Try the previous block first so good solutions are found early.
        starts.sort(key=lambda s: (own != ((s, s + duration),), s))
        options[name] = starts
    best = [None]

    def search(index: int, taken: set[int], changes: int) -> None:
        if best[0] is not None and changes >= best[0]:
            return
        if index == len(flexible):
            best[0] = changes
            return
        name = flexible[index]
        duration = activities[name][2]
        for start in options[name]:
            block = set(range(start, start + duration))
            if taken & block:
                continue
            moved = name in previous and previous[name] != ((start, start + duration),)
            search(index + 1, taken | block, changes + moved)

    search(0, set(used), forced)
    return best[0] is not None, best[0]


def check_valid(instance, result) -> None:
    """Independent validity check of a returned schedule."""
    activities, previous, keep = instance["activities"], instance["previous"], instance["keep"]
    available = free_cells(instance)
    assert set(result.blocks) == set(activities)
    taken: set[int] = set()
    for name, spec in activities.items():
        blocks = tuple((slot_of(s), slot_of(e)) for s, e in result.blocks[name])
        if name in keep:
            assert blocks == previous[name]
        if spec[0] == "FIXED":
            assert blocks == spec[1]
        else:
            assert len(blocks) == 1
            (start, end), = blocks
            low, high = usable(instance, spec)
            assert end - start == spec[2] and low <= start and end <= high
        for block in blocks:
            block_cells = set(cells(block))
            assert block_cells <= available, "every block lies in available time"
            assert not block_cells & taken, "no two blocks overlap"
            taken |= block_cells
    recount = sum(
        1 for name in previous
        if tuple((slot_of(s), slot_of(e)) for s, e in result.blocks[name]) != previous[name]
    )
    assert result.time_changes == recount


@pytest.mark.parametrize("seed", range(INSTANCES))
def test_feasibility_matches_brute_force(seed):
    instance = random_instance(random.Random(seed), replan=False)
    result = run_scheduler(instance)
    schedulable, _ = brute_force(instance)
    assert result.status is not ScheduleStatus.UNDETERMINED
    assert (result.status is ScheduleStatus.SCHEDULED) == schedulable, result.reason
    if schedulable:
        check_valid(instance, result)


@pytest.mark.parametrize("seed", range(REPLAN_INSTANCES))
def test_replan_minimal_time_changes_match_brute_force(seed):
    instance = random_instance(random.Random(50_000 + seed), replan=True)
    result = run_scheduler(instance)
    schedulable, minimum = brute_force(instance)
    assert (result.status is ScheduleStatus.SCHEDULED) == schedulable, result.reason
    if schedulable:
        check_valid(instance, result)
        assert result.time_changes_minimal is True
        assert result.time_changes == minimum


def test_generated_instances_cover_both_outcomes():
    outcomes = {brute_force(random_instance(random.Random(seed), replan=False))[0] for seed in range(INSTANCES)}
    assert outcomes == {True, False}
    changes = {brute_force(random_instance(random.Random(50_000 + seed), replan=True))[1] for seed in range(REPLAN_INSTANCES)}
    assert {0, 1, 2} <= changes
