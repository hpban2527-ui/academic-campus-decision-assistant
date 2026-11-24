"""The review fast paths must not change what a student sees.

Every case runs list_swap_alternatives twice: with ``sp3_service._REVIEW_FAST_PATHS`` off (the
original code path: one rebuilt review context and one full build_plan per candidate) and on
(shared review context + target-met fast path). The full responses must be equal; only the
planner's ``search`` block may differ (the fast plan reports 1 evaluation and a budget stop).
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from api import sp3_service
from api.sp3_real import real_plan_options
from api.sp3_service import list_swap_alternatives, personalized_plan_options, preview_personalized_swap
from personalization.models import StudentPreference

REAL_BASE = {
    "topic_preferences": [], "category_priorities": [], "campus_preferences": [], "mode_preferences": [],
    "time_preferences": [], "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
    "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None},  # max_fee must stay None
    "strategy": "BALANCED",
}
REAL_PREFERENCES = {
    "topic-only": {**REAL_BASE, "topic_preferences": [{"topic_id": "artificial_intelligence", "weight": 5}]},
    "categories+online+campus": {
        **REAL_BASE,
        "topic_preferences": [{"topic_id": "mathematics", "weight": 4}],
        "category_priorities": [{"category_id": "C4", "weight": 5}, {"category_id": "C1", "weight": 3}],
        "mode_preferences": [{"mode": "online", "weight": 5}],
        "campus_preferences": [{"campus_id": "NVC", "weight": 5}],
    },
}


def _preference(payload: dict, **changes) -> StudentPreference:
    return StudentPreference.model_validate({**deepcopy(payload), **changes})


def _distinct(options: list[dict]) -> list[dict]:
    return [item for item in options if item.get("status") == "READY" and not item.get("duplicate_of")]


def _normalised(response: dict) -> dict:
    """The response without the planner search block."""
    copy = deepcopy(response)
    for item in copy["items"]:
        item["preview"]["result"]["plan"].pop("search")
    return copy


def _both(monkeypatch, call):
    """(reference, fast) results of ``call`` with the fast paths off and on."""
    monkeypatch.setattr(sp3_service, "_REVIEW_FAST_PATHS", False)
    reference = call()
    monkeypatch.setattr(sp3_service, "_REVIEW_FAST_PATHS", True)
    return reference, call()


def _assert_same_alternatives(reference: dict, fast: dict) -> None:
    assert [i["activity_id"] for i in fast["items"]] == [i["activity_id"] for i in reference["items"]]
    for key in ("total_valid", "filtered_out", "required_projected_total", "target_rule", "limit"):
        assert fast[key] == reference[key], key
    for ref_item, fast_item in zip(reference["items"], fast["items"]):
        ref_preview, fast_preview = ref_item["preview"], fast_item["preview"]
        ref_plan, fast_plan = ref_preview["result"]["plan"], fast_preview["result"]["plan"]
        assert fast_plan["selected_activities"] == ref_plan["selected_activities"]
        assert [r["scheduled_blocks"] for r in fast_plan["selected_activities"]] == [
            r["scheduled_blocks"] for r in ref_plan["selected_activities"]]
        assert fast_plan["score_summary"] == ref_plan["score_summary"]
        assert fast_plan["plan_version"] == ref_plan["plan_version"]
        for key in ("added_activity_ids", "dropped_activity_ids", "extra_added_activity_ids", "preview_id"):
            assert fast_item[key] == ref_item[key], key
    assert _normalised(fast) == _normalised(reference)


# Synthetic source: every selected activity of every distinct option --------------------

@pytest.mark.parametrize("limit", [3, 10])
def test_synthetic_alternatives_are_identical_for_every_option_and_activity(
    monkeypatch, valid_preference_payload, limit,
):
    preference = _preference(valid_preference_payload)
    options = _distinct(personalized_plan_options(preference, target_total=80)["options"])
    assert options
    checked = 0
    for option in options:
        base = option["result"]
        for row in base["plan"]["selected_activities"]:
            reference, fast = _both(
                monkeypatch,
                lambda: list_swap_alternatives(preference, base, row["activity_id"], limit),
            )
            _assert_same_alternatives(reference, fast)
            checked += 1
    assert checked >= 6


def test_synthetic_below_target_base_uses_the_no_regression_rule(monkeypatch, valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = next(o for o in personalized_plan_options(preference, target_total=80)["options"]
                if o["strategy"] == "BALANCED")["result"]
    reduced = sp3_service.remove_planned_activity(preference, base, "QUIZ-L")["result"]  # below target
    assert reduced["plan"]["score_summary"]["remaining_total"] > 0
    remove_id = reduced["plan"]["selected_activities"][0]["activity_id"]

    reference, fast = _both(monkeypatch, lambda: list_swap_alternatives(preference, reduced, remove_id, 10))

    assert reference["target_rule"] == "NO_REGRESSION"
    _assert_same_alternatives(reference, fast)


def test_synthetic_student_busy_availability_is_identical(monkeypatch, valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = next(o for o in personalized_plan_options(preference, target_total=80)["options"]
                if o["strategy"] == "BALANCED")["result"]
    busy = {
        "availability_version": "sp3-availability/0.2", "timezone": "Asia/Ho_Chi_Minh", "week_start": "2026-11-09",
        "apply_scope": "SEMESTER_WEEKLY",
        "weekly_blocks": [
            {"day_of_week": day, "start_time": "07:00", "end_time": "21:00"}
            for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
        ],
        "effective_from": "2026-11-09", "effective_until": "2027-03-31", "exceptions": [],
        "busy_intervals": [{"start": "2026-11-12T14:00:00+07:00", "end": "2026-11-12T15:00:00+07:00"}],
    }

    reference, fast = _both(
        monkeypatch, lambda: list_swap_alternatives(preference, base, "SEM-A", 10, availability_request=busy),
    )

    assert {"SEM-C": "NOT_FEASIBLE"}.items() <= {i["activity_id"]: i["code"] for i in reference["filtered_out"]}.items()
    _assert_same_alternatives(reference, fast)


def test_preference_first_never_takes_the_fast_path(monkeypatch, valid_preference_payload):
    preference = _preference(valid_preference_payload, strategy="PREFERENCE_FIRST")
    base = next(o for o in personalized_plan_options(preference, target_total=80)["options"]
                if o["strategy"] == "PREFERENCE_FIRST")["result"]
    remove_id = base["plan"]["selected_activities"][0]["activity_id"]
    monkeypatch.setattr(sp3_service, "_GUIDED_SEARCH_MIN_EXTRAS", 0)  # make the catalog-size gate pass
    scored_with_budget_one = []
    original = sp3_service.build_plan

    def spy(planner_input, score, **kwargs):
        scored_with_budget_one.append(kwargs.get("max_evaluations"))
        return original(planner_input, score, **kwargs)

    monkeypatch.setattr(sp3_service, "build_plan", spy)
    list_swap_alternatives(preference, base, remove_id, 10)
    assert scored_with_budget_one and 1 not in scored_with_budget_one

    # The same gate lets BALANCED through, so the spy above proves the strategy check, not the catalog gate.
    balanced = _preference(valid_preference_payload, strategy="BALANCED")
    base = next(o for o in personalized_plan_options(balanced, target_total=80)["options"]
                if o["strategy"] == "BALANCED")["result"]
    scored_with_budget_one.clear()
    list_swap_alternatives(balanced, base, "SEM-A", 10)
    assert 1 in scored_with_budget_one


# Direct previews keep the original path ---------------------------------------------

def test_direct_swap_previews_do_not_depend_on_the_fast_paths(monkeypatch, valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = next(o for o in personalized_plan_options(preference, target_total=80)["options"]
                if o["strategy"] == "BALANCED")["result"]

    for add_id in (None, "SEM-C"):
        reference, fast = _both(
            monkeypatch, lambda: preview_personalized_swap(preference, base, "SEM-A", add_id),
        )
        assert fast == reference


# Real source ----------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(REAL_PREFERENCES))
def test_real_source_alternatives_are_identical(monkeypatch, name):
    preference = _preference(REAL_PREFERENCES[name])
    option = _distinct(real_plan_options(preference, term_id="HK1_2026_2027", target_total=80)["options"])[0]
    base = option["result"]
    remove_id = base["plan"]["selected_activities"][0]["activity_id"]
    kwargs = {"source": "real", "term_id": "HK1_2026_2027"}

    reference, fast = _both(monkeypatch, lambda: list_swap_alternatives(preference, base, remove_id, 10, **kwargs))

    assert reference["items"], "the real source should offer alternatives for this case"
    _assert_same_alternatives(reference, fast)

    # A direct swap-preview (no shared context) equals the alternative's preview.
    first = fast["items"][0]
    monkeypatch.setattr(sp3_service, "_REVIEW_FAST_PATHS", False)
    direct = preview_personalized_swap(preference, base, remove_id, first["activity_id"], **kwargs)
    direct_plan, listed_plan = direct["result"]["plan"], first["preview"]["result"]["plan"]
    for plan in (direct_plan, listed_plan):
        plan.pop("search")
    assert direct == first["preview"]
    removed = preview_personalized_swap(preference, base, remove_id, None, **kwargs)
    assert removed["kind"] == "REMOVE"
