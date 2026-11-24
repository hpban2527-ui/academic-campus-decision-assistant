"""Benchmark list_swap_alternatives (the "Thay doi" panel) with the review fast paths off and on.

Usage (from the repo root, project venv):
    .venv\\Scripts\\python.exe scripts\\bench_review_alternatives.py [--json artifacts/bench_review.json]
        [--sources synthetic real] [--limit 10] [--repeat 1]

Every distinct plan option x every selected activity x every preference is run twice,
once with sp3_service._REVIEW_FAST_PATHS = False (today's behaviour) and once with True.
The two responses must be equal apart from the planner's ``search`` block; any other
difference is reported and fails the run.
Standard library only; the service functions are called directly (no server).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api import sp3_service  # noqa: E402
from api.sp3_real import real_plan_options  # noqa: E402
from personalization.models import StudentPreference  # noqa: E402

BASE_PREFERENCE = {
    "topic_preferences": [],
    "category_priorities": [],
    "campus_preferences": [],
    "mode_preferences": [],
    "time_preferences": [],
    "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None},
    "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
    "strategy": "BALANCED",
}

PREFERENCES = {
    "topic-only": {
        **BASE_PREFERENCE,
        "topic_preferences": [{"topic_id": "artificial_intelligence", "weight": 5}],
    },
    "categories+online+campus": {
        **BASE_PREFERENCE,
        "topic_preferences": [{"topic_id": "mathematics", "weight": 4}],
        "category_priorities": [{"category_id": "C4", "weight": 5}, {"category_id": "C1", "weight": 3}],
        "mode_preferences": [{"mode": "online", "weight": 5}],
        "campus_preferences": [{"campus_id": "NVC", "weight": 5}],
    },
    "min-effort+time": {
        **BASE_PREFERENCE,
        "topic_preferences": [{"topic_id": "mathematics", "weight": 3}],
        "time_preferences": [{"time_slot": "weekday_evening", "weight": 4}],
        "strategy": "MINIMUM_EFFORT",
    },
}


def synthetic_options(preference: StudentPreference) -> list[dict]:
    return sp3_service.personalized_plan_options(preference, target_total=80)["options"]


def real_options(preference: StudentPreference) -> list[dict]:
    return real_plan_options(preference, target_total=80)["options"]


SOURCES = {
    "synthetic": (synthetic_options, {"source": "synthetic"}),
    "real": (real_options, {"source": "real"}),
}


def comparable(response: dict) -> dict:
    """The response minus the planner search block (evaluated_subsets, limit_reason, ...)."""
    copy = deepcopy(response)
    for item in copy["items"]:
        item["preview"]["result"]["plan"].pop("search", None)
    return copy


def first_difference(left, right, path="$"):
    if type(left) is not type(right):
        return path
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{path}.{key}"
            found = first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}[len {len(left)} != {len(right)}]"
        for index, (a, b) in enumerate(zip(left, right)):
            found = first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if left == right else path


class Counter:
    """Counts fast-path attempts, accepted fast plans and full build_plan calls."""

    def __init__(self) -> None:
        self.fast_accepted = 0
        self.fast_declined = 0
        self.full_builds = 0

    def install(self) -> None:
        original_fast, original_build = sp3_service._review_fast_plan, sp3_service.build_plan
        counter = self

        def fast(*args, **kwargs):
            plan = original_fast(*args, **kwargs)
            counter.fast_accepted += plan is not None
            counter.fast_declined += plan is None
            return plan

        def build(*args, **kwargs):
            if "max_evaluations" not in kwargs:
                counter.full_builds += 1
            return original_build(*args, **kwargs)

        sp3_service._review_fast_plan, sp3_service.build_plan = fast, build
        self._restore = (original_fast, original_build)

    def uninstall(self) -> None:
        sp3_service._review_fast_plan, sp3_service.build_plan = self._restore


def run(preference, base, remove_id, limit, source_kwargs, fast: bool):
    sp3_service._REVIEW_FAST_PATHS = fast
    counter = Counter()
    counter.install()
    started = time.perf_counter()
    try:
        response = sp3_service.list_swap_alternatives(preference, base, remove_id, limit, **source_kwargs)
    finally:
        elapsed = time.perf_counter() - started
        counter.uninstall()
        sp3_service._REVIEW_FAST_PATHS = True
    return response, elapsed, counter


def summarize(values: list[float]) -> dict:
    return {
        "n": len(values),
        "median": statistics.median(values) if values else None,
        "max": max(values) if values else None,
        "min": min(values) if values else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sources", nargs="+", default=["synthetic", "real"], choices=sorted(SOURCES))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", metavar="PATH", help="save raw numbers (use a path under artifacts/)")
    args = parser.parse_args()

    rows: list[dict] = []
    mismatches: list[str] = []
    for source in args.sources:
        options_for, source_kwargs = SOURCES[source]
        for name, payload in PREFERENCES.items():
            preference = StudentPreference.model_validate(payload)
            options = [o for o in options_for(preference) if o.get("status") == "READY" and not o.get("duplicate_of")]
            for option in options:
                base = option["result"]
                for item in base["plan"]["selected_activities"]:
                    remove_id = item["activity_id"]
                    case = f"{source}/{name}/{option['strategy']}/{remove_id}"
                    # The client sends the preference with the strategy of the option it reviews.
                    preference = StudentPreference.model_validate({**payload, "strategy": option["strategy"]})
                    reference, t_off, c_off = run(preference, base, remove_id, args.limit, source_kwargs, False)
                    fast, t_on, c_on = run(preference, base, remove_id, args.limit, source_kwargs, True)
                    difference = first_difference(comparable(reference), comparable(fast))
                    if difference:
                        mismatches.append(f"{case}: first difference at {difference}")
                    rows.append({
                        "source": source, "preference": name, "strategy": option["strategy"], "remove": remove_id,
                        "off_seconds": t_off, "on_seconds": t_on, "equal": difference is None,
                        "previews": reference["total_valid"] + len(reference["filtered_out"]),
                        "fast_accepted": c_on.fast_accepted, "fast_declined": c_on.fast_declined,
                        "full_builds_on": c_on.full_builds, "full_builds_off": c_off.full_builds,
                    })
                    print(f"{case:60s} off {t_off:6.2f}s  on {t_on:6.2f}s  "
                          f"fast {c_on.fast_accepted:2d}/{c_on.fast_accepted + c_on.fast_declined:2d}  "
                          f"{'equal' if difference is None else 'DIFFERENT ' + difference}", flush=True)

    print("\nsource     mode  n    median     max     min   fast-path hits / full searches")
    summary = {}
    for source in args.sources:
        mine = [row for row in rows if row["source"] == source]
        for mode, key in (("off", "off_seconds"), ("on", "on_seconds")):
            stats = summarize([row[key] for row in mine])
            summary[f"{source}/{mode}"] = stats
            if not stats["n"]:
                continue
            hits = sum(row["fast_accepted"] for row in mine) if mode == "on" else 0
            full = sum(row["full_builds_" + mode] for row in mine)
            print(f"{source:10s} {mode:4s} {stats['n']:3d} {stats['median']:8.3f}s {stats['max']:7.3f}s {stats['min']:7.3f}s"
                  f"   {hits} / {full}")
    if mismatches:
        print("\nOUTPUT MISMATCHES (fast paths on vs off):")
        print("\n".join(mismatches))
    else:
        print("\nAll compared responses are equal (planner search block excluded).")
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"summary": summary, "rows": rows, "mismatches": mismatches}, indent=2), encoding="utf-8")
        print(f"raw numbers saved to {path}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
