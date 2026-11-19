"""SP3 integration: real SP1 catalog and a clearly synthetic planning preview."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from api.lead_contract import prepare_publication
from personalization.models import PlanningStrategy, StudentPreference
from personalization.planner_adapter import prepare_personalized_planner_input
from personalization.scoring import ActivityFeatures, load_activity_features
from sp1.extractor import extract_post
from sp3.availability import resolve_availability
from sp3.feasibility import FeasibilityEvidence, assess_feasibility
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip
from sp3.contract import plan_version
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
) -> dict:
    """Exercise the full pipeline on synthetic data with optional UI constraints."""
    if scenario not in {"first_plan", "replan", "what_if_skip"}:
        raise ValueError("scenario must be first_plan, replan, or what_if_skip")
    if target_total is not None and (
        type(target_total) is not int or not 0 <= target_total <= 100
    ):
        raise ValueError("target_total must be an integer from 0 to 100")
    if busy_intervals and scenario != "first_plan":
        raise ValueError("busy_intervals can only be customized in first_plan")
    fixture = _json(DEMO)
    first = _step(fixture, "step1", target_total=target_total, busy_intervals=busy_intervals)
    if scenario == "first_plan":
        output = first
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
    }


def personalized_demo_plan(
    preference: StudentPreference,
    *,
    scenario: str = "first_plan",
    target_total: int = 80,
    busy_intervals: list[dict[str, str]] | None = None,
    skip_activity_id: str = "QUIZ-L",
    availability_request: dict | None = None,
    include_internal: bool = False,
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
        if (
            isinstance(availability_request, dict)
            and "available_intervals" in availability_request
            and "calendar_version" in availability_request
            and "weekly_blocks" not in availability_request
        ):
            availability = deepcopy(availability_request)
        else:
            active_availability_request = deepcopy(
                availability_request if availability_request is not None else stored["availability_request"]
            )
            active_availability_request["busy_intervals"].extend(custom_busy or [])
            availability = resolve_availability(
                active_availability_request,
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
                if candidate["activity"]["activity_id"] == skip_activity_id:
                    candidate["participation"]["progress"] = "CANCELLED"
            preview = what_if_skip(
                second["planner_input"],
                skip_activity_id,
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
    candidate_ids = [
        item["activity"]["activity_id"]
        for item in output["feasibility"].get("candidates", [])
        if isinstance(item, dict) and isinstance(item.get("activity"), dict)
    ]
    candidate_breakdown = output["engine"].selected_breakdown({}, candidate_ids)
    unknown_fee_ids = []
    if requested_limits.max_fee is not None:
        unknown_fee_ids = sorted(
            activity_id for activity_id, activity in output["activities"].items()
            if activity.get("fee") is None
        )

    load_activity_features(DATA / "activity_features.json")
    response = {
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
            "candidate_breakdown": candidate_breakdown,
            "hard_excluded": output["hard_excluded"],
            "unknown_fee_activity_ids": unknown_fee_ids,
            "limits_applied": preference.limits.model_dump(mode="json"),
        },
    }
    if include_internal:
        response["_planner_input"] = deepcopy(output["planner_input"])
        response["_engine"] = output["engine"]
        response["_score_callback"] = score_callback
    return response


def _plan_signature(result: dict) -> str:
    selected = [
        {
            "activity_id": item["activity_id"],
            "scheduled_blocks": item.get("scheduled_blocks", []),
        }
        for item in result["plan"].get("selected_activities", [])
    ]
    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _plan_minutes(plan: dict) -> int:
    total = 0
    for item in plan.get("selected_activities", []):
        for block in item.get("scheduled_blocks", []):
            start = datetime.fromisoformat(block["start"])
            end = datetime.fromisoformat(block["end"])
            total += round((end - start).total_seconds() / 60)
    return total


def personalized_plan_options(
    preference: StudentPreference,
    *,
    target_total: int = 80,
    busy_intervals: list[dict[str, str]] | None = None,
    availability_request: dict | None = None,
) -> dict:
    """Compute each supported strategy independently and retain all three cards."""

    attempted = []
    options = []
    seen: dict[str, str] = {}
    for strategy in ("MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"):
        try:
            candidate_preference = preference.model_copy(update={"strategy": PlanningStrategy(strategy)})
            # Revalidate because model_copy intentionally skips Pydantic validation.
            candidate_preference = StudentPreference.model_validate(candidate_preference.model_dump())
            result = personalized_demo_plan(
                candidate_preference,
                target_total=target_total,
                busy_intervals=busy_intervals,
                availability_request=availability_request,
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            attempted.append({"strategy": strategy, "status": "FAILED", "error": str(exc)})
            options.append({"strategy": strategy, "status": "FAILED", "error": str(exc), "result": None})
            continue
        signature = _plan_signature(result)
        duplicate_of = seen.get(signature)
        seen.setdefault(signature, strategy)
        attempted.append({"strategy": strategy, "status": "READY", "signature": signature})
        plan = result["plan"]
        score = plan.get("score_summary") or {}
        options.append(
            {
                "strategy": strategy,
                "status": "READY",
                "signature": signature,
                "duplicate_of": duplicate_of,
                "projected_total": score.get("projected_total"),
                "target_shortfall": score.get("remaining_total"),
                "target_met": score.get("remaining_total") == 0 if score else False,
                "activity_count": len(plan.get("selected_activities", [])),
                "duration_minutes": _plan_minutes(plan),
                "utility": result["personalization"]["total_utility"],
                "plan": plan,
                "result": result,
            }
        )
    ready_count = sum(1 for item in options if item.get("status") == "READY")
    return {
        "options": options,
        "attempted": attempted,
        "deduplicated": 0,
        "message": (
            None
            if ready_count
            else "Không có chiến lược nào tạo được lịch hợp lệ với dữ liệu hiện tại."
        ),
    }


def preview_personalized_swap(
    preference: StudentPreference,
    base_result: dict,
    remove_activity_id: str | None,
    add_activity_id: str | None = None,
    *,
    source: str = "synthetic",
    availability_request: dict | None = None,
) -> dict:
    """Preview a safe replacement through SP3 whole-plan scoring."""
    return _preview_personalized_change(preference, base_result, remove_activity_id, add_activity_id, source=source, availability_request=availability_request)


def preview_personalized_addition(
    preference: StudentPreference, base_result: dict, add_activity_id: str, *, source: str = "synthetic",
    availability_request: dict | None = None,
) -> dict:
    """Preview adding one fixed-time activity while keeping unaffected selections."""
    return _preview_personalized_change(preference, base_result, None, add_activity_id, source=source, availability_request=availability_request)


def preview_personalized_removal(
    preference: StudentPreference, base_result: dict, remove_activity_id: str, *, source: str = "synthetic",
    availability_request: dict | None = None,
) -> dict:
    """Preview removing one activity only; never add compensation."""
    return _preview_personalized_change(preference, base_result, remove_activity_id, None, source=source, availability_request=availability_request)


def _preview_personalized_change(
    preference: StudentPreference,
    base_result: dict,
    remove_activity_id: str | None,
    add_activity_id: str | None,
    *,
    source: str = "synthetic",
    availability_request: dict | None = None,
) -> dict:
    """Validate a calendar edit by rebuilding and independently checking the whole plan.

    Fixed additions use KEEP_TIME; flexible additions use FORCE_INCLUDE (revision 0.2.1).
    Every other selected block stays fixed, and remove-only uses the shared removal path.
    """

    if add_activity_id is None and remove_activity_id is not None:
        return remove_planned_activity(
            preference, base_result, remove_activity_id,
            availability_request=availability_request, source=source,
        )

    if not isinstance(base_result, dict):
        raise ValueError("base_result must be an object")
    base_plan = base_result.get("plan")
    feasibility_payload = base_result.get("feasibility")
    if not isinstance(base_plan, dict) or not isinstance(feasibility_payload, dict):
        raise ValueError("base_result must contain plan and feasibility objects")
    selected_rows = base_plan.get("selected_activities")
    candidate_rows = feasibility_payload.get("candidates")
    if (
        not isinstance(selected_rows, list)
        or len(selected_rows) > 20
        or not all(isinstance(item, dict) for item in selected_rows)
        or not isinstance(candidate_rows, list)
        or len(candidate_rows) > 500
        or not all(isinstance(item, dict) for item in candidate_rows)
    ):
        raise ValueError("base_result plan rows are invalid or too large")

    if remove_activity_id is None and add_activity_id is None:
        raise ValueError("calendar change must add or remove an activity")
    if remove_activity_id is not None and remove_activity_id == add_activity_id:
        raise ValueError("replacement activity must be different")
    selected = {
        item.get("activity_id")
        for item in base_result.get("plan", {}).get("selected_activities", [])
    }
    if remove_activity_id is not None and remove_activity_id not in selected:
        raise ValueError("activity to remove is not selected")
    if add_activity_id is not None and add_activity_id in selected:
        raise ValueError("replacement activity is already selected")
    candidates = {
        item.get("activity", {}).get("activity_id"): item
        for item in base_result.get("feasibility", {}).get("candidates", [])
    }
    candidate = candidates.get(add_activity_id) if add_activity_id is not None else None
    if add_activity_id is not None:
        if not candidate:
            raise ValueError("replacement activity is not in the eligible catalog")
        feasibility = candidate.get("feasibility", {})
        if feasibility.get("status") != "FEASIBLE":
            raise ValueError("replacement activity is not feasible")
    target_total = base_result.get("requested_total_target", 80)
    if isinstance(target_total, bool) or not isinstance(target_total, int) or not 0 <= target_total <= 100:
        raise ValueError("base_result requested_total_target is invalid")
    internal = _review_internal(preference, base_result, target_total, availability_request, source)
    planner_input = internal.pop("_planner_input")
    engine = internal.pop("_engine")
    score_callback = internal.pop("_score_callback")
    by_id = {
        item["activity"]["activity_id"]: item
        for item in planner_input["candidates"]
    }
    if not selected <= set(by_id):
        raise ValueError("base_result contains activities outside the eligible catalog")
    schedule = None
    force_include = False
    if add_activity_id is not None:
        replacement = by_id.get(add_activity_id)
        if replacement is None:
            raise ValueError("replacement activity is outside the eligible catalog")
        schedule = replacement.get("schedule") or {}
        force_include = schedule.get("type") == "FLEXIBLE_WINDOW"
        if not force_include and (schedule.get("type") != "FIXED" or not schedule.get("fixed_blocks")):
            raise ValueError("replacement activity has no usable schedule")

    seeded = [
        {"activity_id": item["activity_id"], "scheduled_blocks": deepcopy(item.get("scheduled_blocks", []))}
        for item in base_result["plan"].get("selected_activities", [])
        if remove_activity_id is None or item["activity_id"] != remove_activity_id
    ]
    if add_activity_id is not None and schedule is not None and not force_include:
        seeded.append({"activity_id": add_activity_id, "scheduled_blocks": deepcopy(schedule["fixed_blocks"])})
    seeded.sort(key=lambda item: item["activity_id"])
    # build_based_on fields come from the fresh plan output and are safer than
    # reconstructing the upstream version tuple here.
    based_on = deepcopy(internal["plan"]["based_on"])
    planner_input["previous_plan"] = {
        "plan_version": plan_version(based_on, [(item["activity_id"], item["scheduled_blocks"]) for item in seeded]),
        "based_on": based_on,
        "selected_activities": seeded,
    }
    planner_input["keep_requests"] = [
        {"activity_id": item["activity_id"], "mode": "KEEP_TIME"}
        for item in seeded
    ]
    if force_include:
        planner_input["keep_requests"].append({"activity_id": add_activity_id, "mode": "FORCE_INCLUDE"})
    for candidate_row in planner_input["candidates"]:
        activity_id = candidate_row["activity"]["activity_id"]
        original_candidate = candidates.get(activity_id)
        originally_feasible = original_candidate and original_candidate.get("feasibility", {}).get("status") == "FEASIBLE"
        if (remove_activity_id is not None and activity_id == remove_activity_id) or not originally_feasible:
            candidate_row["participation"]["progress"] = "CANCELLED"
    preview_plan = build_plan(
        planner_input,
        score_callback,
        preference_utility=engine.score_set,
        personalization_strategy=preference.strategy.value,
    )
    violations = check_plan(planner_input, preview_plan, score_callback, input_snapshot=deepcopy(planner_input))
    if violations:
        raise ValueError("calendar change failed SP3 independent validation")
    if preview_plan.get("keep_conflicts"):
        raise ValueError("calendar change conflicts with an unaffected activity or hard limit")
    preview = _review_result(internal, preview_plan, engine, "personalized_calendar_change")
    after_ids = {item["activity_id"] for item in preview_plan.get("selected_activities", [])}
    if add_activity_id is not None and add_activity_id not in after_ids:
        raise ValueError(
            "SP3 cannot safely force this replacement; choose an alternative selected by the validated replan"
        )
    before_summary = base_result.get("plan", {}).get("score_summary") or {}
    after_summary = preview.get("plan", {}).get("score_summary") or {}
    before_ids = selected
    return {
        "status": "PREVIEW",
        "requires_confirmation": True,
        "remove_activity_id": remove_activity_id,
        "add_activity_id": add_activity_id,
        "before": {
            "projected_total": before_summary.get("projected_total"),
            "target_shortfall": before_summary.get("remaining_total"),
            "activity_count": len(before_ids),
            "duration_minutes": _plan_minutes(base_result["plan"]),
        },
        "after": {
            "projected_total": after_summary.get("projected_total"),
            "target_shortfall": after_summary.get("remaining_total"),
            "activity_count": len(after_ids),
            "duration_minutes": _plan_minutes(preview["plan"]),
        },
        "dropped_activity_ids": sorted(before_ids - after_ids),
        "added_activity_ids": sorted(after_ids - before_ids),
        "result": preview,
    }


# REVIEW-DASH START
# --- Plan review: alternatives, remove-only and what-if ------------------------------
#
# These functions sit on top of ``preview_personalized_swap``; they never score or
# check a plan themselves. Every number they return comes from SP2/SP3 output.

REVIEW_DEFAULT_LIMIT = 3
REVIEW_MAX_LIMIT = 10
_TARGET_TOLERANCE = 1e-9


def _review_internal(preference, base_result, target_total, availability_request, source):
    if source not in {"synthetic", "real"}:
        raise ValueError("source must be 'synthetic' or 'real'")
    if source == "real":
        from api.sp3_real import real_plan
        return real_plan(
            "first_plan", target_total=target_total, preference=preference,
            availability_request=availability_request, include_internal=True,
        )
    if base_result.get("data_source") == "SP1-STORE-V2":
        raise ValueError("a real-source plan requires source=real")
    return personalized_demo_plan(
        preference, target_total=target_total,
        availability_request=availability_request, include_internal=True,
    )


def _review_result(internal, plan, engine, scenario):
    """Refresh preference explanations from the final plan, using the preference engine."""
    result = {**internal, "plan": plan, "scenario": scenario, "checker_violations": 0}
    contributions = [
        {"activity_id": item["activity_id"], "category_id": reason["category_id"]}
        for item in plan.get("selected_activities", [])
        for reason in item.get("reasons", [])
        if reason["code"] == "GOAL_CONTRIBUTION" and reason.get("category_id")
    ]
    ids = [item["activity_id"] for item in plan.get("selected_activities", [])]
    breakdown = engine.selected_breakdown({"contributions": contributions}, ids)
    result["personalization"] = {
        **internal.get("personalization", {}),
        "selected_breakdown": breakdown,
        "total_utility": engine.score_set(tuple(ids), {"contributions": contributions}),
    }
    return result


@dataclass(frozen=True)
class _ReviewContext:
    selected_rows: list
    selected_ids: frozenset
    target_total: int
    base_summary: dict
    planner_input: dict
    engine: object
    score_callback: object
    internal: dict


def _review_context(
    preference: StudentPreference,
    base_result: dict,
    remove_activity_id: str,
    availability_request: dict | None = None,
    *, source: str = "synthetic",
) -> _ReviewContext:
    """Validate a client-held base result and rebuild trusted planner state for it."""
    if not isinstance(base_result, dict):
        raise ValueError("base_result must be an object")
    base_plan = base_result.get("plan")
    feasibility_payload = base_result.get("feasibility")
    if not isinstance(base_plan, dict) or not isinstance(feasibility_payload, dict):
        raise ValueError("base_result must contain plan and feasibility objects")
    rows = base_plan.get("selected_activities")
    candidates = feasibility_payload.get("candidates")
    if (
        not isinstance(rows, list)
        or len(rows) > 20
        or not all(isinstance(item, dict) and isinstance(item.get("activity_id"), str) for item in rows)
        or not isinstance(candidates, list)
        or len(candidates) > 500
        or not all(isinstance(item, dict) for item in candidates)
    ):
        raise ValueError("base_result plan rows are invalid or too large")
    selected_ids = frozenset(item["activity_id"] for item in rows)
    if remove_activity_id not in selected_ids:
        raise ValueError("activity to remove is not selected")
    target_total = base_result.get("requested_total_target", 80)
    if isinstance(target_total, bool) or not isinstance(target_total, int) or not 0 <= target_total <= 100:
        raise ValueError("base_result requested_total_target is invalid")
    # The student's own availability (same schema as /personalized/plan); None = the fixture default.
    internal = _review_internal(preference, base_result, target_total, availability_request, source)
    planner_input = internal.pop("_planner_input")
    engine = internal.pop("_engine")
    score_callback = internal.pop("_score_callback")
    if not selected_ids <= {item["activity"]["activity_id"] for item in planner_input["candidates"]}:
        raise ValueError("base_result contains activities outside the eligible catalog")
    return _ReviewContext(
        selected_rows=rows,
        selected_ids=selected_ids,
        target_total=target_total,
        base_summary=base_plan.get("score_summary") or {},
        planner_input=planner_input,
        engine=engine,
        score_callback=score_callback,
        internal=internal,
    )


def _seed_previous_plan(context: _ReviewContext, kept_rows: list) -> dict:
    """Make ``kept_rows`` the previous plan and KEEP_TIME them all (never reshuffled)."""
    planner_input = context.planner_input
    seeded = sorted(
        (
            {"activity_id": item["activity_id"], "scheduled_blocks": deepcopy(item.get("scheduled_blocks", []))}
            for item in kept_rows
        ),
        key=lambda item: item["activity_id"],
    )
    based_on = deepcopy(context.internal["plan"]["based_on"])
    planner_input["previous_plan"] = {
        "plan_version": plan_version(based_on, [(item["activity_id"], item["scheduled_blocks"]) for item in seeded]),
        "based_on": based_on,
        "selected_activities": seeded,
    }
    planner_input["keep_requests"] = [{"activity_id": item["activity_id"], "mode": "KEEP_TIME"} for item in seeded]
    return planner_input


def _cancel(planner_input: dict, activity_id: str) -> None:
    for row in planner_input["candidates"]:
        if row["activity"]["activity_id"] == activity_id:
            row["participation"]["progress"] = "CANCELLED"


def _target_state(summary: dict, target_total: int) -> dict:
    projected = summary.get("projected_total")
    met = isinstance(projected, (int, float)) and projected >= target_total - _TARGET_TOLERANCE
    return {
        "target_total": target_total,
        "projected_total": projected,
        "remaining_total": summary.get("remaining_total"),
        "remaining_by_category": deepcopy(summary.get("remaining_by_category") or {}),
        "target_met": bool(met),
    }


def _review_preview(
    kind: str,
    context: _ReviewContext,
    plan: dict,
    *,
    remove_activity_id: str,
    scenario: str,
) -> dict:
    after_ids = {item["activity_id"] for item in plan.get("selected_activities", [])}
    state = _target_state(plan.get("score_summary") or {}, context.target_total)
    return {
        "status": "PREVIEW",
        "kind": kind,
        "requires_confirmation": True,
        "remove_activity_id": remove_activity_id,
        "add_activity_id": None,
        "before": {
            "projected_total": context.base_summary.get("projected_total"),
            "target_shortfall": context.base_summary.get("remaining_total"),
            "activity_count": len(context.selected_ids),
            "duration_minutes": _plan_minutes({"selected_activities": context.selected_rows}),
        },
        "after": {
            "projected_total": state["projected_total"],
            "target_shortfall": state["remaining_total"],
            "activity_count": len(after_ids),
            "duration_minutes": _plan_minutes(plan),
        },
        **state,
        "warnings": [] if state["target_met"] else ["BELOW_TARGET"],
        "dropped_activity_ids": sorted(context.selected_ids - after_ids),
        "added_activity_ids": sorted(after_ids - context.selected_ids),
        # Every plan reaching this point passed check_plan (a violation raises), so the count is 0.
        "result": _review_result(context.internal, plan, context.engine, scenario),
    }


def remove_planned_activity(
    preference: StudentPreference,
    base_result: dict,
    remove_activity_id: str,
    availability_request: dict | None = None,
    *, source: str = "synthetic",
) -> dict:
    """Remove one activity and re-score the rest; nothing replaces it.

    Every remaining activity is KEEP_TIME and the activity count is capped at the
    number of remaining activities, so SP3 only re-scores and cannot add a
    compensating activity. The result may be below the target: that is reported
    through ``target_met=False`` and ``warnings=["BELOW_TARGET"]``, not as an error.
    """
    context = _review_context(preference, base_result, remove_activity_id, availability_request, source=source)
    remaining = [item for item in context.selected_rows if item["activity_id"] != remove_activity_id]
    planner_input = _seed_previous_plan(context, remaining)
    _cancel(planner_input, remove_activity_id)
    limits = planner_input["limits"]
    cap = len(remaining) if limits.get("max_activities") is None else min(limits["max_activities"], len(remaining))
    limits["max_activities"] = cap
    plan = build_plan(
        planner_input, context.score_callback,
        preference_utility=context.engine.score_set,
        personalization_strategy=preference.strategy.value,
    )
    _require_valid_review_plan(planner_input, plan, context)
    return _review_preview(
        "REMOVE", context, plan,
        remove_activity_id=remove_activity_id, scenario="personalized_remove_only",
    )


def what_if_skip_planned_activity(
    preference: StudentPreference,
    base_result: dict,
    skip_activity_id: str,
    availability_request: dict | None = None,
    *, source: str = "synthetic",
) -> dict:
    """Preview the plan if ``skip_activity_id`` is skipped; nothing is applied.

    ``what_if_skip`` runs with a KEEP_TIME request for every remaining selected
    activity, so SP3 only adds compensating activities and never moves the others.
    """
    context = _review_context(preference, base_result, skip_activity_id, availability_request, source=source)
    planner_input = _seed_previous_plan(context, context.selected_rows)
    # The skipped activity keeps its previous block but is no longer a keep request.
    planner_input["keep_requests"] = [
        item for item in planner_input["keep_requests"] if item["activity_id"] != skip_activity_id
    ]
    cancelled = deepcopy(planner_input)
    _cancel(cancelled, skip_activity_id)
    plan = what_if_skip(
        planner_input, skip_activity_id, context.score_callback,
        preference_utility=context.engine.score_set,
        personalization_strategy=preference.strategy.value,
    )
    _require_valid_review_plan(cancelled, plan, context)
    kept_blocks = {
        item["activity_id"]: item.get("scheduled_blocks", [])
        for item in context.selected_rows if item["activity_id"] != skip_activity_id
    }
    moved = sorted(
        item["activity_id"] for item in plan.get("selected_activities", [])
        if item["activity_id"] in kept_blocks and item["scheduled_blocks"] != kept_blocks[item["activity_id"]]
    )
    if moved:
        raise ValueError("what-if moved an unaffected activity")
    return _review_preview(
        "WHAT_IF_SKIP", context, plan,
        remove_activity_id=skip_activity_id, scenario="personalized_what_if_skip",
    )


def _require_valid_review_plan(planner_input: dict, plan: dict, context: _ReviewContext) -> None:
    if plan.get("status") in {"ERROR", "NEEDS_DATA"}:
        raise ValueError("SP3 could not score the review plan")
    if plan.get("keep_conflicts"):
        raise ValueError("review plan conflicts with an unaffected activity or hard limit")
    if check_plan(planner_input, plan, context.score_callback):
        raise ValueError("review plan failed SP3 independent validation")


def _incomplete_planning_info(context: _ReviewContext, row: dict) -> str | None:
    """Why an activity lacks the planning data a replacement needs, or None when complete."""
    activity = row["activity"]
    schedule = row.get("schedule") or {}
    if not row.get("score_binding_ref"):
        return "missing criterion/points binding"
    if schedule.get("type") not in {"FIXED", "FLEXIBLE_WINDOW"} or not activity.get("start") or not activity.get("end"):
        return "missing start or end"
    mode = activity.get("mode")
    if mode not in {"online", "offline", "hybrid"}:
        return "missing participation mode"
    if mode in {"offline", "hybrid"}:
        feature = context.engine.features.get(activity["activity_id"])
        if not activity.get("location") and (feature is None or not feature.campus_id):
            return "missing campus"
    return None


def _deadline_sort_key(value: str | None) -> tuple:
    """Later registration deadline first; a missing deadline sorts last."""
    if not value:
        return (1, 0.0)
    return (0, -datetime.fromisoformat(value).timestamp())


def list_swap_alternatives(
    preference: StudentPreference,
    base_result: dict,
    remove_activity_id: str,
    limit: int = REVIEW_DEFAULT_LIMIT,
    availability_request: dict | None = None,
    *, source: str = "synthetic",
) -> dict:
    """List valid replacements for ``remove_activity_id``, best first.

    Each candidate is tried with ``preview_personalized_swap``. It is kept only
    when SP3 validates the plan (0 checker violations, no keep conflicts), the
    candidate has complete planning data, hard exclusions do not apply, and the
    plan still reaches the target. If the base plan was already below the target,
    the replacement must not lower the projected total instead.
    Ranking: preference utility (higher), total plan duration (shorter),
    registration deadline (later), activity_id.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= REVIEW_MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {REVIEW_MAX_LIMIT}")
    context = _review_context(preference, base_result, remove_activity_id, availability_request, source=source)
    base_projected = context.base_summary.get("projected_total")
    if isinstance(base_projected, bool) or not isinstance(base_projected, (int, float)):
        raise ValueError("base_result has no projected total")
    base_reached_target = base_projected >= context.target_total - _TARGET_TOLERANCE
    floor = context.target_total if base_reached_target else base_projected

    valid: list[dict] = []
    filtered: list[dict] = []

    def reject(activity_id: str, code: str, message: str) -> None:
        filtered.append({"activity_id": activity_id, "code": code, "message": message})

    for row in sorted(context.planner_input["candidates"], key=lambda item: item["activity"]["activity_id"]):
        activity_id = row["activity"]["activity_id"]
        if activity_id in context.selected_ids:
            continue
        hard = context.engine.hard_exclusion_reasons(activity_id)
        if hard:
            reject(activity_id, "HARD_EXCLUDED", "Excluded by the confirmed preference: " + ", ".join(hard) + ".")
            continue
        if row["feasibility"]["status"] != "FEASIBLE" or row["participation"]["progress"] != "NOT_STARTED":
            reject(activity_id, "NOT_FEASIBLE", "Not feasible for this student.")
            continue
        missing = _incomplete_planning_info(context, row)
        if missing is not None:
            reject(activity_id, "INCOMPLETE_INFO", "Incomplete planning information: " + missing + ".")
            continue
        try:
            preview = preview_personalized_swap(
                preference, base_result, remove_activity_id, activity_id,
                availability_request=availability_request, source=source,
            )
        except ValueError as exc:
            reject(activity_id, "SWAP_REJECTED", str(exc))
            continue
        plan = preview["result"]["plan"]
        projected = (plan.get("score_summary") or {}).get("projected_total")
        if not isinstance(projected, (int, float)) or projected < floor - _TARGET_TOLERANCE:
            reject(
                activity_id, "BELOW_TARGET",
                "The plan would not reach the target." if base_reached_target
                else "The plan would score lower than the current plan.",
            )
            continue
        entry = next((item for item in plan["selected_activities"] if item["activity_id"] == activity_id), None)
        goal = next((r for r in (entry or {}).get("reasons", []) if r["code"] == "GOAL_CONTRIBUTION"), None)
        if entry is None or goal is None or not goal.get("category_id"):
            reject(activity_id, "INCOMPLETE_INFO", "Incomplete planning information: no scored criterion.")
            continue
        preview["result"]["checker_violations"] = 0  # preview_personalized_swap raises on any violation
        valid.append(_alternative_item(context, row, entry, goal, preview, remove_activity_id))

    valid.sort(key=lambda item: (
        -item["preference"]["utility"],
        item["plan_duration_minutes"],
        _deadline_sort_key(item["registration_deadline"]),
        item["activity_id"],
    ))
    return {
        "status": "ALTERNATIVES",
        "remove_activity_id": remove_activity_id,
        "target_total": context.target_total,
        "base_projected_total": base_projected,
        "required_projected_total": floor,
        "target_rule": "REACH_TARGET" if base_reached_target else "NO_REGRESSION",
        "total_valid": len(valid),
        "limit": limit,
        "items": valid[:limit],
        "filtered_out": filtered,
    }


def _alternative_item(
    context: _ReviewContext,
    row: dict,
    entry: dict,
    goal: dict,
    preview: dict,
    remove_activity_id: str,
) -> dict:
    activity = row["activity"]
    activity_id = activity["activity_id"]
    plan = preview["result"]["plan"]
    scored = context.engine.selected_breakdown(
        {"contributions": [{"activity_id": activity_id, "category_id": goal["category_id"]}]}, [activity_id],
    )[0]
    feature = context.engine.features.get(activity_id)
    summary = plan.get("score_summary") or {}
    return {
        "activity_id": activity_id,
        "title": entry["title"],
        "schedule_type": entry["schedule_type"],
        "scheduled_blocks": deepcopy(entry["scheduled_blocks"]),
        "criterion": goal["category_id"],
        "effective_gain": goal["projected_added"],
        "projected_total": summary.get("projected_total"),
        "remaining_total": summary.get("remaining_total"),
        "target_met": summary.get("remaining_total") == 0,
        "duration_minutes": _plan_minutes({"selected_activities": [entry]}),
        "plan_duration_minutes": preview["after"]["duration_minutes"],
        "mode": activity.get("mode"),
        "campus": None if feature is None else feature.campus_id,
        "location": activity.get("location"),
        "registration_deadline": activity.get("registration_deadline"),
        "preference": {"utility": scored["utility"], "matches": scored["matches"]},
        "added_activity_ids": preview["added_activity_ids"],
        "dropped_activity_ids": preview["dropped_activity_ids"],
        "extra_added_activity_ids": sorted(set(preview["added_activity_ids"]) - {activity_id}),
        "preview_id": _preview_id(remove_activity_id, activity_id, preview["result"]),
        "preview": preview,
    }


def _preview_id(remove_activity_id: str, add_activity_id: str, result: dict) -> str:
    """Stateless id of a preview: the same swap on the same plan gives the same id."""
    canonical = json.dumps(
        [remove_activity_id, add_activity_id, _plan_signature(result)], separators=(",", ":"),
    )
    return "swap-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
# REVIEW-DASH END
