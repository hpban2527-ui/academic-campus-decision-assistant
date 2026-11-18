from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from personalization.models import StudentPreference
from personalization.planner_adapter import prepare_personalized_planner_input
from personalization.scoring import ActivityFeatures
from sp3.planner import build_plan


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "sp3"))

from planner_doubles import (  # noqa: E402
    CappedAdditiveScorer,
    at,
    make_activity,
    make_candidate,
    make_planner_input,
)


def test_adapter_prepares_any_upstream_planner_input_without_mutation(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["mode_preferences"] = []
    payload["hard_exclusions"]["modes"] = ["offline"]
    preference = StudentPreference.model_validate(payload)
    online = make_candidate(make_activity("REAL-A", at(2, 9), at(2, 10), mode="online"))
    offline = make_candidate(make_activity("REAL-B", at(2, 11), at(2, 12), mode="offline"))
    upstream = make_planner_input(
        [online, offline],
        scores={"C1": 0},
        caps={"C1": 30},
        total_target=5,
        preferred_domains=["academic"],
        preferred_modes=["offline"],
        max_activities=10,
    )
    original = deepcopy(upstream)

    prepared = prepare_personalized_planner_input(
        upstream,
        preference,
        {
            "REAL-A": ActivityFeatures(frozenset({"mathematics"}), "NVC", frozenset()),
            "REAL-B": ActivityFeatures(frozenset(), "DONG_HOA", frozenset()),
        },
    )

    assert upstream == original
    assert prepared.planner_input["preferences"] == {
        "preferred_domains": [],
        "preferred_modes": [],
    }
    assert prepared.planner_input["limits"]["max_activities"] == 4
    by_id = {
        item["activity"]["activity_id"]: item
        for item in prepared.planner_input["candidates"]
    }
    assert by_id["REAL-A"]["feasibility"]["status"] == "FEASIBLE"
    assert by_id["REAL-B"]["feasibility"] == {
        "status": "INFEASIBLE",
        "reason_codes": ["PERSONALIZATION_HARD_EXCLUSION"],
    }
    assert prepared.hard_excluded == (
        {"activity_id": "REAL-B", "reasons": ["mode:offline"]},
    )


def test_adapter_options_run_directly_with_duyen_sp3_planner(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)
    candidate = make_candidate(make_activity("UPSTREAM-POST-ID", at(2, 9), at(2, 10), mode="online"))
    planner_input = make_planner_input(
        [candidate],
        scores={"C1": 0},
        caps={"C1": 30},
        total_target=5,
    )
    prepared = prepare_personalized_planner_input(
        planner_input,
        preference,
        {
            "UPSTREAM-POST-ID": ActivityFeatures(
                frozenset({"mathematics"}),
                "NVC",
                frozenset({"weekday_evening"}),
            )
        },
    )

    plan = build_plan(
        prepared.planner_input,
        CappedAdditiveScorer({"UPSTREAM-POST-ID": ("C1", 5)}),
        **prepared.build_plan_options,
    )

    assert [item["activity_id"] for item in plan["selected_activities"]] == ["UPSTREAM-POST-ID"]
    utility = prepared.engine.score_activity("UPSTREAM-POST-ID", "C4")
    assert utility.utility > 0


def test_unknown_upstream_activity_uses_only_reviewed_planner_fields(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)
    candidate = make_candidate(make_activity("NOT-YET-ENRICHED", at(2, 9), at(2, 10)))
    planner_input = make_planner_input(
        [candidate],
        scores={"C1": 0},
        caps={"C1": 30},
        total_target=5,
    )

    prepared = prepare_personalized_planner_input(planner_input, preference, {})

    utility = prepared.engine.score_activity("NOT-YET-ENRICHED", "C1")
    assert utility.utility == 5
    assert [(item.dimension, item.value) for item in utility.matches] == [("mode", "online")]
