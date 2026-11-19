"""Plan review backend: alternatives, remove-only and what-if (synthetic source).

Every expectation below comes from the synthetic SP3 fixture and the real SP2 scorer;
nothing is scored by the review layer itself.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from fastapi.testclient import TestClient
import pytest

from api import server, sp3_service
from api.sp3_service import (
    _deadline_sort_key,
    _incomplete_planning_info,
    list_swap_alternatives,
    personalized_plan_options,
    preview_personalized_swap,
    remove_planned_activity,
    what_if_skip_planned_activity,
)
from personalization.models import StudentPreference

client = TestClient(server.app)


def _preference(payload: dict, **changes) -> StudentPreference:
    data = deepcopy(payload)
    data.update(changes)
    return StudentPreference.model_validate(data)


def _base(preference: StudentPreference, strategy: str, target_total: int = 80) -> dict:
    options = personalized_plan_options(preference, target_total=target_total)["options"]
    return next(option["result"] for option in options if option["strategy"] == strategy)


def _selected(result: dict) -> list[str]:
    return [item["activity_id"] for item in result["plan"]["selected_activities"]]


def _blocks(plan: dict) -> dict[str, list[dict]]:
    return {item["activity_id"]: item["scheduled_blocks"] for item in plan["selected_activities"]}


def _ids(response: dict) -> list[str]:
    return [item["activity_id"] for item in response["items"]]


def _filtered(response: dict) -> dict[str, str]:
    return {item["activity_id"]: item["code"] for item in response["filtered_out"]}


# Alternatives -------------------------------------------------------------------------

def test_alternatives_are_ranked_by_preference_then_duration_then_deadline_then_id(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")
    assert _selected(base) == ["SEM-A", "QUIZ-M", "QUIZ-L"]

    result = list_swap_alternatives(preference, base, "SEM-A", limit=10)

    assert result["total_valid"] == len(result["items"]) >= 3
    assert _ids(result) == ["SEM-C", "MOB-W", "SEM-B", "REG-Z"]
    keys = [
        (-item["preference"]["utility"], item["plan_duration_minutes"],
         _deadline_sort_key(item["registration_deadline"]), item["activity_id"])
        for item in result["items"]
    ]
    assert keys == sorted(keys)
    # SEM-C and MOB-W tie on preference; the shorter total plan comes first.
    by_id = {item["activity_id"]: item for item in result["items"]}
    assert by_id["SEM-C"]["preference"]["utility"] == by_id["MOB-W"]["preference"]["utility"]
    assert by_id["SEM-C"]["plan_duration_minutes"] < by_id["MOB-W"]["plan_duration_minutes"]


def test_alternatives_default_limit_is_three_and_total_valid_counts_all(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")

    result = list_swap_alternatives(preference, base, "SEM-A")

    assert result["limit"] == 3 and len(result["items"]) == 3 and result["total_valid"] == 4
    assert _ids(result) == ["SEM-C", "MOB-W", "SEM-B"]


def test_alternative_item_carries_engine_numbers_and_an_applicable_preview(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")

    item = list_swap_alternatives(preference, base, "SEM-A")["items"][0]

    assert item["activity_id"] == "SEM-C"
    for key in (
        "title", "schedule_type", "scheduled_blocks", "criterion", "effective_gain", "projected_total",
        "duration_minutes", "preference", "preview_id", "preview", "registration_deadline", "mode", "campus",
    ):
        assert key in item
    assert item["criterion"] == "C1" and item["effective_gain"] == 5
    # SEM-C has no topic in common with this preference; its utility of 5 is the NVC campus match.
    assert item["preference"]["matches"] == [{"dimension": "campus", "value": "NVC", "weight": 5}]
    assert item["preference"]["utility"] == 5
    preview = item["preview"]
    assert preview["status"] == "PREVIEW" and preview["requires_confirmation"] is True
    assert preview["add_activity_id"] == "SEM-C" and preview["remove_activity_id"] == "SEM-A"
    plan = preview["result"]["plan"]
    assert plan["score_summary"]["projected_total"] == item["projected_total"]
    assert _blocks(plan)["SEM-C"] == item["scheduled_blocks"]
    # The id is stable for the same swap on the same plan.
    again = list_swap_alternatives(preference, base, "SEM-A")["items"][0]
    assert again["preview_id"] == item["preview_id"]


def test_replacement_must_still_reach_the_target(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "MINIMUM_EFFORT", target_total=80)

    result = list_swap_alternatives(preference, base, "QUIZ-L", limit=10)

    assert result["target_rule"] == "REACH_TARGET" and result["required_projected_total"] == 80
    assert all(item["projected_total"] >= 80 and item["target_met"] for item in result["items"])
    # QUIZ-M can be placed (flexible) but the plan would drop below 80.
    assert _filtered(result)["QUIZ-M"] == "BELOW_TARGET"
    assert "QUIZ-M" not in _ids(result)


def test_when_the_base_plan_is_below_target_a_replacement_must_not_lower_the_total(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "MINIMUM_EFFORT", target_total=90)
    assert base["plan"]["score_summary"]["projected_total"] == 85 < 90

    result = list_swap_alternatives(preference, base, "QUIZ-L", limit=10)

    assert result["target_rule"] == "NO_REGRESSION" and result["required_projected_total"] == 85
    assert all(item["projected_total"] >= 85 for item in result["items"])
    assert set(_filtered(result).values()) >= {"BELOW_TARGET"}
    assert "lower" in next(f["message"] for f in result["filtered_out"] if f["code"] == "BELOW_TARGET")

    # A replacement that keeps the total is offered even though the target stays out of reach.
    kept = list_swap_alternatives(preference, base, "SEM-A", limit=10)
    assert kept["total_valid"] >= 1 and all(item["projected_total"] >= 85 for item in kept["items"])
    assert all(item["target_met"] is False for item in kept["items"])


def test_flexible_replacement_works_with_force_include(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "MINIMUM_EFFORT", target_total=70)
    assert _selected(base) == ["SEM-A", "QUIZ-L", "SEM-C"]

    preview = preview_personalized_swap(preference, base, "QUIZ-L", "QUIZ-M")

    assert preview["status"] == "PREVIEW" and "QUIZ-M" in preview["added_activity_ids"]
    blocks = _blocks(preview["result"]["plan"])
    assert len(blocks["QUIZ-M"]) == 1
    sitting = [datetime.fromisoformat(blocks["QUIZ-M"][0][key]) for key in ("start", "end")]
    assert (sitting[1] - sitting[0]).total_seconds() == 180 * 60
    for other, other_blocks in blocks.items():
        if other == "QUIZ-M":
            continue
        for block in other_blocks:
            start, end = datetime.fromisoformat(block["start"]), datetime.fromisoformat(block["end"])
            assert end <= sitting[0] or start >= sitting[1]
    # Unaffected activities keep their times.
    for activity_id in ("SEM-A", "SEM-C"):
        assert blocks[activity_id] == _blocks(base["plan"])[activity_id]

    result = list_swap_alternatives(preference, base, "QUIZ-L", limit=10)
    flexible = next(item for item in result["items"] if item["activity_id"] == "QUIZ-M")
    assert flexible["schedule_type"] == "FLEXIBLE_WINDOW"


def test_impossible_flexible_replacement_fails_closed(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "MINIMUM_EFFORT")
    # QUIZ-L stays frozen at 09:00-10:30, which leaves no 180-minute sitting for QUIZ-M.
    base_with_quiz_l = _base(preference, "BALANCED")
    assert "QUIZ-L" in _selected(base_with_quiz_l)

    with pytest.raises(ValueError, match="conflicts"):
        preview_personalized_swap(preference, base, "SEM-A", "QUIZ-M")
    result = list_swap_alternatives(preference, base, "SEM-A", limit=10)
    assert _filtered(result)["QUIZ-M"] == "SWAP_REJECTED"


def test_conflicting_candidate_is_filtered(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")

    result = list_swap_alternatives(preference, base, "QUIZ-L", limit=10)

    # SEM-B overlaps SEM-A, which stays in the plan.
    assert _filtered(result)["SEM-B"] == "SWAP_REJECTED"
    assert "SEM-B" not in _ids(result)


def test_hard_excluded_activity_is_never_offered(valid_preference_payload):
    preference = _preference(
        valid_preference_payload,
        hard_exclusions={"campus_ids": ["DONG_HOA"], "modes": [], "time_slots": []},
    )
    base = _base(preference, "BALANCED")
    assert not {"SEM-B", "REG-Z"} & set(_selected(base))

    result = list_swap_alternatives(preference, base, _selected(base)[0], limit=10)

    assert _filtered(result)["SEM-B"] == "HARD_EXCLUDED" and _filtered(result)["REG-Z"] == "HARD_EXCLUDED"
    assert not {"SEM-B", "REG-Z"} & set(_ids(result))
    # A client that relabels the candidate as feasible still cannot force it in.
    tampered = deepcopy(base)
    for row in tampered["feasibility"]["candidates"]:
        if row["activity"]["activity_id"] == "SEM-B":
            row["feasibility"] = {"status": "FEASIBLE", "reason_codes": []}
    with pytest.raises(ValueError):
        preview_personalized_swap(preference, tampered, _selected(base)[0], "SEM-B")


def test_candidate_with_missing_planning_info_is_filtered(valid_preference_payload, monkeypatch):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")
    original = sp3_service.personalized_demo_plan

    def without_end(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("include_internal"):
            for row in result["_planner_input"]["candidates"]:
                if row["activity"]["activity_id"] == "MOB-W":
                    row["activity"]["end"] = None
        return result

    monkeypatch.setattr(sp3_service, "personalized_demo_plan", without_end)

    result = list_swap_alternatives(preference, base, "SEM-A", limit=10)

    assert _filtered(result)["MOB-W"] == "INCOMPLETE_INFO"
    assert "MOB-W" not in _ids(result)


@pytest.mark.parametrize("change,expected", [
    ({}, None),
    ({"score_binding_ref": None}, "criterion"),
    ({"schedule": None}, "start or end"),
    ({"activity.end": None}, "start or end"),
    ({"activity.mode": None}, "mode"),
    ({"activity.location": None, "campus": False}, "campus"),
])
def test_incomplete_planning_info_rules(change, expected):
    row = {
        "score_binding_ref": "binding-X",
        "schedule": {"type": "FIXED", "fixed_blocks": []},
        "activity": {"activity_id": "X", "start": "2026-11-09T09:00:00+07:00", "end": "2026-11-09T10:00:00+07:00",
                     "mode": "offline", "location": "Hall"},
    }
    has_campus = change.pop("campus", False) is not False
    for key, value in change.items():
        if key.startswith("activity."):
            row["activity"][key.split(".", 1)[1]] = value
        else:
            row[key] = value

    class Engine:
        features = {"X": type("F", (), {"campus_id": "NVC" if has_campus else None})()}

    context = type("Context", (), {"engine": Engine()})()
    message = _incomplete_planning_info(context, row)
    if expected is None:
        assert message is None
    else:
        assert message is not None and expected in message


def test_deadline_sort_key_puts_later_deadlines_first_and_missing_last():
    values = ["2026-11-05T23:59:00+07:00", None, "2026-11-08T23:00:00+07:00"]
    assert sorted(values, key=_deadline_sort_key) == [
        "2026-11-08T23:00:00+07:00", "2026-11-05T23:59:00+07:00", None,
    ]


def test_alternatives_reject_bad_limit_and_unknown_activity(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")
    for bad in (0, 11, True, "3"):
        with pytest.raises(ValueError, match="limit"):
            list_swap_alternatives(preference, base, "SEM-A", limit=bad)
    with pytest.raises(ValueError, match="not selected"):
        list_swap_alternatives(preference, base, "SEM-B")


# Remove-only -------------------------------------------------------------------------

def test_remove_below_target_is_flagged_not_raised(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")

    result = remove_planned_activity(preference, base, "SEM-A")

    assert result["status"] == "PREVIEW" and result["kind"] == "REMOVE"
    assert result["target_met"] is False and result["warnings"] == ["BELOW_TARGET"]
    assert result["projected_total"] == 75 and result["remaining_total"] == 5 and result["target_total"] == 80
    assert result["added_activity_ids"] == [] and result["dropped_activity_ids"] == ["SEM-A"]
    assert result["add_activity_id"] is None and result["requires_confirmation"] is True
    # Nothing is reshuffled: the rest keeps its blocks.
    remaining = {k: v for k, v in _blocks(base["plan"]).items() if k != "SEM-A"}
    assert _blocks(result["result"]["plan"]) == remaining


def test_remove_that_keeps_the_target_is_not_flagged(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "MINIMUM_EFFORT", target_total=60)

    result = remove_planned_activity(preference, base, "SEM-C")

    assert result["target_met"] is True and result["warnings"] == []
    assert result["projected_total"] >= 60 and result["added_activity_ids"] == []


def test_removing_the_only_activity_leaves_an_empty_plan(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")
    only = deepcopy(base)
    only["plan"]["selected_activities"] = [
        item for item in only["plan"]["selected_activities"] if item["activity_id"] == "SEM-A"
    ]
    only["plan"]["score_summary"] = base["plan"]["score_summary"]

    result = remove_planned_activity(preference, only, "SEM-A")

    assert result["result"]["plan"]["selected_activities"] == []
    assert result["target_met"] is False and result["projected_total"] == 60


def test_swap_preview_with_null_add_is_remove_only(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")

    via_swap = preview_personalized_swap(preference, base, "SEM-A", None)

    assert via_swap == remove_planned_activity(preference, base, "SEM-A")


# What-if -----------------------------------------------------------------------------

def test_what_if_adds_compensation_without_moving_the_others(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")
    assert _selected(base) == ["SEM-A", "QUIZ-M", "QUIZ-L"]

    result = what_if_skip_planned_activity(preference, base, "QUIZ-L")

    assert result["kind"] == "WHAT_IF_SKIP" and result["dropped_activity_ids"] == ["QUIZ-L"]
    assert result["added_activity_ids"] and result["target_met"] is True
    after = _blocks(result["result"]["plan"])
    before = _blocks(base["plan"])
    for activity_id in ("SEM-A", "QUIZ-M"):
        assert after[activity_id] == before[activity_id]
    assert "QUIZ-L" not in after
    # Nothing is applied: the base result is untouched.
    assert _selected(base) == ["SEM-A", "QUIZ-M", "QUIZ-L"]


# HTTP --------------------------------------------------------------------------------

def _request(preference_payload: dict, base: dict, **extra) -> dict:
    return {
        "confirmed_profile": True, "preference": preference_payload, "base_result": base,
        "remove_activity_id": "SEM-A", **extra,
    }


def test_alternatives_endpoint(valid_preference_payload):
    base = _base(_preference(valid_preference_payload), "BALANCED")

    response = client.post("/api/sp3/personalized/alternatives", json=_request(valid_preference_payload, base, limit=2))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_valid"] == 4 and len(body["items"]) == 2 and body["limit"] == 2
    assert client.post(
        "/api/sp3/personalized/alternatives", json=_request(valid_preference_payload, base, limit=0)
    ).status_code == 422
    assert client.post(
        "/api/sp3/personalized/alternatives", json=_request(valid_preference_payload, base),
        params={"source": "real"},
    ).status_code == 422
    unconfirmed = _request(valid_preference_payload, base) | {"confirmed_profile": False}
    assert client.post("/api/sp3/personalized/alternatives", json=unconfirmed).status_code == 422
    bad = _request(valid_preference_payload, base) | {"remove_activity_id": "NOT-IN-PLAN"}
    assert client.post("/api/sp3/personalized/alternatives", json=bad).status_code == 422


def test_swap_preview_endpoint_accepts_explicit_null_but_not_a_missing_field(valid_preference_payload):
    base = _base(_preference(valid_preference_payload), "BALANCED")

    removed = client.post(
        "/api/sp3/personalized/swap-preview", json=_request(valid_preference_payload, base, add_activity_id=None)
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["target_met"] is False and removed.json()["kind"] == "REMOVE"

    swapped = client.post(
        "/api/sp3/personalized/swap-preview", json=_request(valid_preference_payload, base, add_activity_id="SEM-C")
    )
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["add_activity_id"] == "SEM-C"

    omitted = client.post("/api/sp3/personalized/swap-preview", json=_request(valid_preference_payload, base))
    assert omitted.status_code == 422


def test_what_if_endpoint(valid_preference_payload):
    base = _base(_preference(valid_preference_payload), "BALANCED")
    payload = _request(valid_preference_payload, base) | {"remove_activity_id": "QUIZ-L"}

    response = client.post("/api/sp3/personalized/what-if-skip", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "WHAT_IF_SKIP"
    assert client.post(
        "/api/sp3/personalized/what-if-skip", json=payload, params={"source": "real"}
    ).status_code == 422


# Student availability pass-through ---------------------------------------------------

def _availability(busy: list[dict]) -> dict:
    """Canonical availability, same schema the planner screen sends to /personalized/plan."""
    return {
        "availability_version": "sp3-availability/0.2",
        "timezone": "Asia/Ho_Chi_Minh",
        "week_start": "2026-11-09",
        "apply_scope": "SEMESTER_WEEKLY",
        "weekly_blocks": [
            {"day_of_week": day, "start_time": "07:00", "end_time": "21:00"}
            for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
        ],
        "effective_from": "2026-11-09",
        "effective_until": "2027-03-31",
        "exceptions": [],
        "busy_intervals": busy,
    }


# SEM-C is the fixed session Thursday 12/11 14:00-15:00.
BUSY_DURING_SEM_C = [{"start": "2026-11-12T14:00:00+07:00", "end": "2026-11-12T15:00:00+07:00"}]


def test_alternatives_never_offer_an_activity_in_busy_time(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")
    assert "SEM-C" in _ids(list_swap_alternatives(preference, base, "SEM-A", limit=10))

    busy = _availability(BUSY_DURING_SEM_C)
    result = list_swap_alternatives(preference, base, "SEM-A", limit=10, availability_request=busy)

    assert "SEM-C" not in _ids(result)
    assert _filtered(result)["SEM-C"] == "NOT_FEASIBLE"
    assert _ids(result)  # other alternatives remain


def test_swap_preview_and_remove_and_what_if_respect_student_busy_time(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    base = _base(preference, "BALANCED")
    busy = _availability(BUSY_DURING_SEM_C)

    # The client's base_result still lists SEM-C as feasible; the rebuilt plan with busy time wins.
    with pytest.raises(ValueError):
        preview_personalized_swap(preference, base, "SEM-A", "SEM-C", availability_request=busy)
    assert preview_personalized_swap(preference, base, "SEM-A", "SEM-C")["status"] == "PREVIEW"

    for result in (
        remove_planned_activity(preference, base, "QUIZ-L", availability_request=busy),
        what_if_skip_planned_activity(preference, base, "QUIZ-L", availability_request=busy),
    ):
        assert "SEM-C" not in _blocks(result["result"]["plan"])
        assert "SEM-C" not in result["added_activity_ids"]


def test_plan_built_with_busy_time_stays_clear_of_it_through_review(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    busy = _availability(BUSY_DURING_SEM_C)
    options = personalized_plan_options(preference, target_total=80, availability_request=busy)["options"]
    base = next(option["result"] for option in options if option["strategy"] == "PREFERENCE_FIRST")
    busy_start, busy_end = (datetime.fromisoformat(BUSY_DURING_SEM_C[0][key]) for key in ("start", "end"))

    def overlaps_busy(plan: dict) -> bool:
        return any(
            datetime.fromisoformat(block["start"]) < busy_end and busy_start < datetime.fromisoformat(block["end"])
            for blocks in _blocks(plan).values() for block in blocks
        )

    assert not overlaps_busy(base["plan"])
    for removed in _selected(base):
        result = list_swap_alternatives(preference, base, removed, limit=10, availability_request=busy)
        assert all(not overlaps_busy(item["preview"]["result"]["plan"]) for item in result["items"])
        assert not overlaps_busy(what_if_skip_planned_activity(preference, base, removed, availability_request=busy)["result"]["plan"])


def test_review_endpoints_accept_the_same_availability_field(valid_preference_payload):
    base = _base(_preference(valid_preference_payload), "BALANCED")
    busy = _availability(BUSY_DURING_SEM_C)

    alternatives = client.post(
        "/api/sp3/personalized/alternatives",
        json=_request(valid_preference_payload, base, limit=10, availability=busy),
    )
    assert alternatives.status_code == 200, alternatives.text
    assert "SEM-C" not in [item["activity_id"] for item in alternatives.json()["items"]]

    swap = client.post(
        "/api/sp3/personalized/swap-preview",
        json=_request(valid_preference_payload, base, add_activity_id="SEM-C", availability=busy),
    )
    assert swap.status_code == 422

    what_if = client.post(
        "/api/sp3/personalized/what-if-skip",
        json=_request(valid_preference_payload, base, availability=busy) | {"remove_activity_id": "QUIZ-L"},
    )
    assert what_if.status_code == 200, what_if.text
    assert "SEM-C" not in [item["activity_id"] for item in what_if.json()["result"]["plan"]["selected_activities"]]

    # Omitting the field keeps the previous behaviour.
    assert client.post(
        "/api/sp3/personalized/swap-preview", json=_request(valid_preference_payload, base, add_activity_id="SEM-C")
    ).status_code == 200


def test_remove_only_keeps_the_rest_of_the_plan_exactly(valid_preference_payload):
    preference = _preference(valid_preference_payload)
    for strategy in ("MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"):
        base = _base(preference, strategy)
        for removed in _selected(base):
            result = remove_planned_activity(preference, base, removed)
            plan = result["result"]["plan"]
            assert set(_selected(result["result"])) == set(_selected(base)) - {removed}
            before = _blocks(base["plan"])
            assert _blocks(plan) == {k: v for k, v in before.items() if k != removed}
