"""SP3 integration: real SP1 catalog and a clearly synthetic planning preview."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from api.lead_contract import prepare_publication
from personalization.models import StudentPreference
from personalization.planner_adapter import prepare_personalized_planner_input
from personalization.scoring import ActivityFeatures, load_activity_features
from sp1.extractor import extract_post
from sp3.availability import resolve_availability
from sp3.feasibility import FeasibilityEvidence, assess_feasibility
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QA = ROOT / "DataQA"
DEMO = ROOT / "tests" / "sp3" / "fixtures" / "main_flow_integration.json"

# The current SP3 screen intentionally uses a synthetic fixture.  These
# reviewed fixture-only features let the personalization flow be demonstrated
# without pretending that synthetic IDs belong to the production catalog.
DEMO_FEATURES = {
    "SEM-A": ActivityFeatures(frozenset({"mathematics", "research"}), "NVC", frozenset({"weekday_morning"})),
    "SEM-B": ActivityFeatures(frozenset({"artificial_intelligence", "technology"}), "DONG_HOA", frozenset({"weekday_morning"})),
    "SEM-C": ActivityFeatures(frozenset({"research", "technology"}), "NVC", frozenset({"weekday_afternoon"})),
    "QUIZ-M": ActivityFeatures(frozenset({"mathematics", "artificial_intelligence"}), "ONLINE", frozenset({"weekday_morning"})),
    "QUIZ-L": ActivityFeatures(frozenset({"civic_education", "soft_skills"}), "ONLINE", frozenset({"weekday_morning"})),
    "MOB-W": ActivityFeatures(frozenset({"volunteer", "culture"}), "NVC", frozenset({"weekday_afternoon"})),
    "REG-Z": ActivityFeatures(frozenset({"volunteer"}), "DONG_HOA", frozenset({"weekday_afternoon"})),
    "NEWS-X": ActivityFeatures(frozenset({"soft_skills"}), "ONLINE", frozenset()),
    "DONE-Y": ActivityFeatures(frozenset({"volunteer"}), "OTHER", frozenset()),
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sp1_catalog() -> dict:
    """Return source records with QA context; never promote them to verified points."""
    activities = _json(DATA / "activities.json")
    reviews = _json(QA / "QA20.json")
    # Minh Tri's collector is the authoritative raw-source feed.  Only the
    # reviewed 20-record activity catalog below is planning-eligible; every
    # additional real post remains an extraction draft until SP1/SP2 review.
    source_posts = _json(DATA / "raw" / "source.json")
    by_id = {item["activity_id"]: item for item in reviews}
    original_ids = {item["activity_id"] for item in activities}
    source_ids = {post["post_id"] for post in source_posts}
    missing_reviewed_ids = sorted(original_ids - source_ids)
    rows = [
        {
            "activity": item,
            "data_qa": by_id.get(item["activity_id"]),
            "publication_status": "REVIEW_REQUIRED",
            "score_binding_verified": False,
        }
        for item in activities
    ]
    extra = [post for post in source_posts if post["post_id"] not in original_ids]
    drafts = []
    errors = []
    for post in extra:
        try:
            for raw_draft in extract_post(post)["drafts"]:
                reviewed = prepare_publication(raw_draft)
                drafts.append({
                    "activity": reviewed["record"],
                    "review_flags": reviewed["meta"]["flags"],
                    "publication_status": "REVIEW_REQUIRED",
                    "score_binding_verified": False,
                })
        except (TypeError, ValueError, KeyError) as exc:
            errors.append({"post_id": post["post_id"], "reason": type(exc).__name__})
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "term": {"id": "HK3_2025_2026", "start": "2026-05-18", "end": "2026-08-17"},
        "source_dataset": {
            "path": "data/raw/source.json",
            "total_posts": len(source_posts),
            "status": "RAW_REVIEW_REQUIRED",
            "matched_reviewed_activities": len(original_ids & source_ids),
            "missing_reviewed_activity_ids": missing_reviewed_ids,
        },
        "activity_count": len(rows),
        "unstructured_new_posts": len(extra),
        "new_post_drafts": drafts,
        "new_post_errors": errors,
        "activities": rows,
        "note": "Real source posts need 14-field extraction, point/category binding, and human review before planning.",
    }


def _score_callback(fixture: dict):
    scoring_data = deepcopy(fixture["scoring_data"])
    scoring_data["ruleset"] = _json(DATA / "drl_rules.json")
    return ScorerAdapter(ProjectedScorer(InMemoryScoringData(scoring_data))).score_plan


def _step(
    fixture: dict,
    name: str,
    previous: dict | None = None,
    *,
    target_total: int | None = None,
    busy_intervals: list[dict[str, str]] | None = None,
) -> dict:
    stored = fixture["steps"][name]
    feasibility_request = deepcopy(stored["feasibility_request"])
    context = feasibility_request["context"]
    availability_request = deepcopy(stored["availability_request"])
    availability_request["busy_intervals"].extend(busy_intervals or [])
    availability = resolve_availability(
        availability_request,
        window_start=context["window_start"],
        window_end=context["window_end"],
    )
    feasibility_request["available_intervals"] = availability["available_intervals"]
    feasibility_request["context"]["calendar_version"] = availability["calendar_version"]
    feasibility = assess_feasibility(
        feasibility_request, evidence=FeasibilityEvidence(**deepcopy(fixture["evidence"]))
    )

    # A fixture is evidence of an interface, not a substitute for running upstream code.
    if not busy_intervals and (
        availability != stored["availability_response"] or feasibility != stored["feasibility_response"]
    ):
        raise RuntimeError("SP3 upstream contract drift; review the fixture before publishing a demo.")

    previous_plan = None
    if previous is not None:
        previous_plan = {
            "plan_version": previous["plan_version"],
            "based_on": deepcopy(previous["based_on"]),
            "selected_activities": [
                {"activity_id": item["activity_id"], "scheduled_blocks": deepcopy(item["scheduled_blocks"])}
                for item in previous["selected_activities"]
            ],
        }
    planning_options = deepcopy(fixture["planner"])
    if target_total is not None:
        planning_options["goals"]["total_target"] = target_total
    planner_input = {
        "contract_version": feasibility["contract_version"],
        "request_id": "api-demo-" + name,
        "context": deepcopy(feasibility["context"]),
        **planning_options,
        "candidates": deepcopy(feasibility["candidates"]),
        "conflict_pairs": deepcopy(feasibility["conflict_pairs"]),
        "available_intervals": deepcopy(availability["available_intervals"]),
        "previous_plan": previous_plan,
        "keep_requests": [],
    }
    plan = build_plan(planner_input, _score_callback(fixture))
    violations = check_plan(planner_input, plan, _score_callback(fixture), input_snapshot=deepcopy(planner_input))
    if violations:
        raise RuntimeError("SP3 independent plan check failed.")
    return {
        "availability": availability,
        "feasibility": feasibility,
        "plan": plan,
        "planner_input": planner_input,
    }


def demo_plan(
    scenario: str,
    *,
    target_total: int | None = None,
    busy_intervals: list[dict[str, str]] | None = None,
<<<<<<< HEAD
=======
    skip_activity_id: str | None = None,
>>>>>>> eeffe5b13de641b0ea8e4c92e5897f41c5fc9fa9
) -> dict:
    """Exercise the full pipeline on synthetic data with optional UI constraints."""
    if scenario not in {"first_plan", "replan", "what_if_skip"}:
        raise ValueError("scenario must be first_plan, replan, or what_if_skip")
    if target_total is not None and (
        type(target_total) is not int or not 0 <= target_total <= 100
    ):
        raise ValueError("target_total must be an integer from 0 to 100")
<<<<<<< HEAD
    if busy_intervals and scenario != "first_plan":
        raise ValueError("busy_intervals can only be customized in first_plan")
=======
    if busy_intervals and scenario not in {"first_plan", "what_if_skip"}:
        raise ValueError("busy_intervals can only be customized in first_plan or what_if_skip")
>>>>>>> eeffe5b13de641b0ea8e4c92e5897f41c5fc9fa9
    fixture = _json(DEMO)
    first = _step(fixture, "step1", target_total=target_total, busy_intervals=busy_intervals)
    if scenario == "first_plan":
        output = first
<<<<<<< HEAD
    else:
        second = _step(fixture, "step2", previous=first["plan"], target_total=target_total)
        if scenario == "replan":
            output = second
        else:
            preview = what_if_skip(second["planner_input"], "QUIZ-L", _score_callback(fixture))
            if check_plan(
                {**deepcopy(second["planner_input"]),
                 "candidates": [
                     {**deepcopy(item),
                      "participation": {
                          **item["participation"],
                          "progress": "CANCELLED" if item["activity"]["activity_id"] == "QUIZ-L"
                          else item["participation"]["progress"],
                      }}
                     for item in second["planner_input"]["candidates"]
                 ]},
                preview, _score_callback(fixture),
            ):
                raise RuntimeError("SP3 what-if plan check failed.")
            output = {**second, "plan": preview}
=======
    elif scenario == "replan":
        second = _step(fixture, "step2", previous=first["plan"], target_total=target_total)
        output = second
    else:
        skip_id = skip_activity_id or "QUIZ-L"
        base_step = first if not busy_intervals else _step(fixture, "step2", previous=first["plan"], target_total=target_total)
        base_input = base_step["planner_input"]
        preview = what_if_skip(base_input, skip_id, _score_callback(fixture))
        if check_plan(
            {**deepcopy(base_input),
             "candidates": [
                 {**deepcopy(item),
                  "participation": {
                      **item["participation"],
                      "progress": "CANCELLED" if item["activity"]["activity_id"] == skip_id
                      else item["participation"]["progress"],
                  }}
                 for item in base_input["candidates"]
             ]},
            preview, _score_callback(fixture),
        ):
            raise RuntimeError("SP3 what-if plan check failed.")
        output = {**base_step, "plan": preview}
>>>>>>> eeffe5b13de641b0ea8e4c92e5897f41c5fc9fa9
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "data_source": "SYNTHETIC-DEMO",
        "scenario": scenario,
        "term": output["feasibility"]["context"]["term_id"],
        "requested_total_target": target_total if target_total is not None else fixture["planner"]["goals"]["total_target"],
        "availability": output["availability"],
        "feasibility": output["feasibility"],
        "plan": output["plan"],
<<<<<<< HEAD
=======
        "dropped_activity_id": skip_id if scenario == "what_if_skip" else None,
>>>>>>> eeffe5b13de641b0ea8e4c92e5897f41c5fc9fa9
    }


def personalized_demo_plan(
    preference: StudentPreference,
    *,
    scenario: str = "first_plan",
    target_total: int = 80,
    busy_intervals: list[dict[str, str]] | None = None,
) -> dict:
    """Build a deterministic SP3 plan from a student-confirmed preference.

    This keeps the public SP3 v0.2 planner input/output contract unchanged.
    Personalization is supplied as a ranking callback, while confirmed hard
    exclusions and limits are translated into ordinary SP3 feasibility/limit
    inputs before the search starts.
    """

    if scenario not in {"first_plan", "replan", "what_if_skip"}:
        raise ValueError("scenario must be first_plan, replan, or what_if_skip")
    if busy_intervals and scenario != "first_plan":
        raise ValueError("busy_intervals can only be customized in first_plan")

    fixture = _json(DEMO)
    score_callback = _score_callback(fixture)
    requested_limits = preference.limits

    def run_step(name: str, previous: dict | None = None, custom_busy: list[dict[str, str]] | None = None) -> dict:
        stored = fixture["steps"][name]
        feasibility_request = deepcopy(stored["feasibility_request"])
        context = feasibility_request["context"]
        availability_request = deepcopy(stored["availability_request"])
        availability_request["busy_intervals"].extend(custom_busy or [])
        availability = resolve_availability(
            availability_request,
            window_start=context["window_start"],
            window_end=context["window_end"],
        )
        feasibility_request["available_intervals"] = availability["available_intervals"]
        feasibility_request["context"]["calendar_version"] = availability["calendar_version"]
        feasibility = assess_feasibility(
            feasibility_request,
            evidence=FeasibilityEvidence(**deepcopy(fixture["evidence"])),
        )

        planning_options = deepcopy(fixture["planner"])
        planning_options["goals"]["total_target"] = target_total

        previous_plan = None
        if previous is not None:
            previous_plan = {
                "plan_version": previous["plan_version"],
                "based_on": deepcopy(previous["based_on"]),
                "selected_activities": [
                    {"activity_id": item["activity_id"], "scheduled_blocks": deepcopy(item["scheduled_blocks"])}
                    for item in previous["selected_activities"]
                ],
            }
        planner_input = {
            "contract_version": feasibility["contract_version"],
            "request_id": "api-personalized-" + name,
            "context": deepcopy(feasibility["context"]),
            **planning_options,
            "candidates": deepcopy(feasibility["candidates"]),
            "conflict_pairs": deepcopy(feasibility["conflict_pairs"]),
            "available_intervals": deepcopy(availability["available_intervals"]),
            "previous_plan": previous_plan,
            "keep_requests": [],
        }
        personalized = prepare_personalized_planner_input(
            planner_input,
            preference,
            DEMO_FEATURES,
        )
        planner_input = personalized.planner_input
        # Keep the API's feasibility explanation aligned with the exact
        # candidates the planner receives after personalization exclusions.
        feasibility = {
            **feasibility,
            "candidates": deepcopy(planner_input["candidates"]),
        }
        snapshot = deepcopy(planner_input)
        plan = build_plan(
            planner_input,
            score_callback,
            **personalized.build_plan_options,
        )
        if check_plan(planner_input, plan, score_callback, input_snapshot=snapshot):
            raise RuntimeError("SP3 independent personalized-plan check failed.")
        return {
            "availability": availability,
            "feasibility": feasibility,
            "plan": plan,
            "planner_input": planner_input,
            "engine": personalized.engine,
            "activities": personalized.engine.activities,
            "hard_excluded": list(personalized.hard_excluded),
        }

    first = run_step("step1", custom_busy=busy_intervals if scenario == "first_plan" else None)
    if scenario == "first_plan":
        output = first
    else:
        second = run_step("step2", previous=first["plan"])
        if scenario == "replan":
            output = second
        else:
            preview_input = deepcopy(second["planner_input"])
            for candidate in preview_input["candidates"]:
                if candidate["activity"]["activity_id"] == "QUIZ-L":
                    candidate["participation"]["progress"] = "CANCELLED"
            preview = what_if_skip(
                second["planner_input"],
                "QUIZ-L",
                score_callback,
                preference_utility=second["engine"].score_set,
                personalization_strategy=preference.strategy.value,
            )
            if check_plan(preview_input, preview, score_callback):
                raise RuntimeError("SP3 personalized what-if plan check failed.")
            output = {**second, "plan": preview}

    selected_ids = [item["activity_id"] for item in output["plan"]["selected_activities"]]
    contribution_rows = []
    for item in output["plan"]["selected_activities"]:
        goal_reason = next((reason for reason in item["reasons"] if reason["code"] == "GOAL_CONTRIBUTION"), None)
        if goal_reason is not None:
            contribution_rows.append({"activity_id": item["activity_id"], "category_id": goal_reason["category_id"]})
    breakdown = output["engine"].selected_breakdown({"contributions": contribution_rows}, selected_ids)
    unknown_fee_ids = []
    if requested_limits.max_fee is not None:
        unknown_fee_ids = sorted(
            activity_id for activity_id, activity in output["activities"].items()
            if activity.get("fee") is None
        )

    load_activity_features(DATA / "activity_features.json")
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "data_source": "SYNTHETIC-DEMO",
        "integration": {
            "adapter": "personalization-planner-adapter/1.0",
            "planner_contract": output["feasibility"]["contract_version"],
            "candidate_source": "upstream_planner_input",
            "ready_for_external_planner_input": True,
            "fixture_used_for_demo": True,
        },
        "scenario": "personalized_" + scenario,
        "term": output["feasibility"]["context"]["term_id"],
        "requested_total_target": target_total,
        "preference_confirmed": True,
        "availability": output["availability"],
        "feasibility": output["feasibility"],
        "plan": output["plan"],
        "personalization": {
            "algorithm": "weighted-deterministic-v1",
            "strategy": preference.strategy.value,
            "total_utility": sum(item["utility"] for item in breakdown),
            "selected_breakdown": breakdown,
            "hard_excluded": output["hard_excluded"],
            "unknown_fee_activity_ids": unknown_fee_ids,
            "limits_applied": preference.limits.model_dump(mode="json"),
        },
    }
