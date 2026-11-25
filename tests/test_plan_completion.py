from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from api import server
from api.plan_completion import CompletionCatalog, completion_catalog, timestamp

SYNTHETIC = "SYNTHETIC-DEMO"  # the synthetic scenario has its own id and clock, it is not a semester
HK1 = "HK1_2026_2027"


@pytest.fixture
def session(tmp_path, monkeypatch):
    for name, value in (
        ("SESSION_FILE", tmp_path / "session.json"),
        ("session_scores", {}),
        ("session_committed", []),
        ("session_confirmed_plans", {}),
        ("session_preferences", {}),
        ("session_simulation_dates", {}),
        ("review_queue", []),
        ("student_dedupers", {}),
    ):
        monkeypatch.setattr(server, name, value)
    monkeypatch.setenv("UNILIFE_COMPLETION_AS_OF", "2026-11-16T08:00:00+07:00")
    return server


def plan_for(session, student="TEST-A", source="synthetic", target=80, term=HK1):
    return session.run_sp3_demo_plan(session.SP3DemoPlanRequest(total_target=target), source, student, term)


def confirm(session, result, student="TEST-A", term=None):
    return session.save_confirmed_plan(session.ConfirmPlanRequest(
        student_id=student, term_id=term or result["plan"]["context"]["term_id"], offer=result["completion_offer"],
    ))


def complete(session, version, activity_id, student="TEST-A", term=SYNTHETIC):
    return session.complete_plan_activity(session.CompletePlanActivityRequest(
        student_id=student, term_id=term, plan_version=version, activity_id=activity_id, affirmed=True,
    ))


def test_offline_boundary_and_quiz_deadlines(session, monkeypatch):
    result = plan_for(session)
    version = result["plan"]["plan_version"]
    monkeypatch.setenv("UNILIFE_COMPLETION_AS_OF", "2026-11-09T09:59:59+07:00")
    progress = confirm(session, result)
    assert progress["activities"]["SEM-A"]["status"] == "NOT_DUE"
    with pytest.raises(HTTPException) as too_early:
        complete(session, version, "SEM-A")
    assert too_early.value.detail["status"] == "NOT_DUE"
    assert session.session_committed == []

    monkeypatch.setenv("UNILIFE_COMPLETION_AS_OF", "2026-11-09T10:00:00+07:00")
    assert complete(session, version, "SEM-A")["progress"]["activities"]["SEM-A"]["status"] == "COMPLETED"
    monkeypatch.setenv("UNILIFE_COMPLETION_AS_OF", "2026-11-11T12:30:00+07:00")
    progress = session.get_confirmed_plan_progress("TEST-A", version, SYNTHETIC)
    assert progress["activities"]["QUIZ-M"]["status"] == "NOT_DUE"
    assert "8/10 câu" in progress["activities"]["QUIZ-M"]["question"]
    assert progress["activities"]["QUIZ-L"]["question"] == "Bạn đã tham gia làm quiz chưa?"
    assert progress["activities"]["QUIZ-L"]["status"] == "READY"
    monkeypatch.setenv("UNILIFE_COMPLETION_AS_OF", "2026-11-11T13:00:00+07:00")
    assert complete(session, version, "QUIZ-M")["progress"]["activities"]["QUIZ-M"]["status"] == "COMPLETED"


def test_catalog_all_sessions_review_and_missing_deadline():
    catalog = completion_catalog("synthetic")
    assert catalog.eligibility("MOB-W", timestamp("2026-11-12T14:00:00+07:00"))["status"] == "NOT_DUE"
    assert catalog.eligibility("MOB-W", timestamp("2026-11-14T09:00:00+07:00"))["status"] == "READY"
    metadata = deepcopy(catalog.metadata)
    metadata["SEM-A"] = {"time_defaults": {"window_close": "date_only_2359"}}
    metadata["SEM-B"] = {"flags": ["needs_review:completion_requirements"]}
    metadata["QUIZ-M"]["derived"] = {"end": "start_plus_duration:default_quiz_30m"}
    incomplete = CompletionCatalog(catalog.scoring, catalog.planner, catalog.evidence, metadata)
    now = timestamp("2026-11-16T08:00:00+07:00")
    assert incomplete.eligibility("SEM-A", now)["status"] == "MISSING_END"
    assert incomplete.eligibility("SEM-B", now)["status"] == "NEEDS_REVIEW"
    assert incomplete.eligibility("QUIZ-M", now)["status"] == "MISSING_END"
    assert incomplete.eligibility("NEWS-X", now)["status"] == "READY"


def test_activity_without_a_score_binding_still_cannot_be_awarded():
    source = completion_catalog("synthetic")
    scoring = deepcopy(source.scoring)
    scoring["bindings"] = [b for b in scoring["bindings"] if b["activity_id"] != "SEM-A"]
    catalog = CompletionCatalog(scoring, source.planner, source.evidence, source.metadata)
    assert catalog.eligibility("SEM-A", timestamp("2026-11-16T08:00:00+07:00"))["status"] == "NEEDS_REVIEW"


@pytest.mark.parametrize("mode,requirements", [
    ("online", []),
    ("online", [{"type": "survey"}]),
    ("online", [{"type": "proof_upload"}]),
    ("hybrid", []),
    ("online", [{"type": "quiz", "threshold": 8}]),
])
def test_completion_accepts_student_affirmation_for_scored_activity_types(mode, requirements):
    source = completion_catalog("synthetic")
    scoring, metadata = deepcopy(source.scoring), deepcopy(source.metadata)
    activity = next(a for a in scoring["activities"] if a["activity_id"] == "SEM-A")
    activity["mode"] = mode
    metadata["SEM-A"] = {"completion_requirements": requirements}
    catalog = CompletionCatalog(scoring, source.planner, source.evidence, metadata)
    assert catalog.eligibility("SEM-A", timestamp("2026-11-09T09:59:59+07:00"))["status"] == "NOT_DUE"
    assert catalog.eligibility("SEM-A", timestamp("2026-11-09T10:00:00+07:00"))["status"] == "READY"


def test_fixed_activity_requires_the_last_session_to_finish():
    source = completion_catalog("synthetic")
    evidence = deepcopy(source.evidence)
    evidence.setdefault("schedule_by_activity", {})["SEM-A"] = {
        "type": "FIXED", "fixed_blocks": [
            {"start": "2026-11-09T08:00:00+07:00", "end": "2026-11-09T10:00:00+07:00"},
            {"start": "2026-11-10T08:00:00+07:00", "end": "2026-11-10T10:00:00+07:00"},
        ],
    }
    catalog = CompletionCatalog(source.scoring, source.planner, evidence, source.metadata)
    assert catalog.eligibility("SEM-A", timestamp("2026-11-09T10:00:00+07:00"))["status"] == "NOT_DUE"
    assert catalog.eligibility("SEM-A", timestamp("2026-11-10T10:00:00+07:00"))["status"] == "READY"


def test_real_webinar_awards_points_after_advancing_without_changing_the_plan(session, monkeypatch):
    monkeypatch.delenv("UNILIFE_COMPLETION_AS_OF")
    catalog = completion_catalog("real", HK1)
    aid = next(aid for aid, a in catalog.activities.items() if "EZ-Check" in a["title"] and "Salmonella" in a["title"])
    activity = catalog.activities[aid]
    assert catalog.metadata[aid]["completion_requirements"] == []
    initial = plan_for(session, source="real")
    # Isolate the reported webinar in a trusted server-issued confirmation offer.
    initial["plan"]["selected_activities"] = [{
        "activity_id": aid, "scheduled_blocks": [{"start": activity["start"], "end": activity["end"]}],
    }]
    session._offer_plan(initial, "real", session._account_planning("TEST-A", "real", HK1))
    progress = confirm(session, initial)
    version = progress["plan_version"]
    before = progress["score_summary"]["baseline_total"]
    saved = deepcopy(session.session_confirmed_plans["TEST-A"][HK1])
    with pytest.raises(HTTPException) as early:
        complete(session, version, aid, term=HK1)
    assert early.value.detail["status"] == "NOT_DUE"
    session.advance_term_clock(session.AdvanceClockRequest(student_id="TEST-A", term_id=HK1, date="2026-09-29"))
    assert session.session_confirmed_plans["TEST-A"][HK1] == saved
    first = complete(session, version, aid, term=HK1)
    assert first["scores"]["total_confirmed"] == before + 5
    assert first["progress"]["activities"][aid]["status"] == "COMPLETED"
    assert aid not in first["progress"]["projected_by_activity"]
    session._clear_session_state()
    session._load_session_from_disk()
    again = complete(session, version, aid, term=HK1)
    assert again["scores"]["total_confirmed"] == before + 5
    assert session.session_confirmed_plans["TEST-A"][HK1] == saved
    assert len(session.session_committed) == 1


def test_confirmation_requires_saved_membership_and_correct_account(session):
    result = plan_for(session)
    version = result["plan"]["plan_version"]
    with pytest.raises(HTTPException) as unconfirmed:
        complete(session, version, "SEM-A")
    assert unconfirmed.value.status_code == 404
    with pytest.raises(HTTPException) as wrong_owner:
        confirm(session, result, "TEST-B")
    assert wrong_owner.value.status_code == 403
    altered = {**result, "completion_offer": "A" + result["completion_offer"][1:]}
    with pytest.raises(HTTPException) as tampered:
        confirm(session, altered)
    assert tampered.value.status_code == 409
    confirm(session, result)
    for activity, student in (("not-in-plan", "TEST-A"), ("SEM-A", "TEST-B")):
        with pytest.raises(HTTPException) as missing:
            complete(session, version, activity, student)
        assert missing.value.status_code == 404
    assert not session.session_committed


def test_cap_concurrent_retry_reload_and_replan(session):
    state = session._default_student_scores()
    state["current"]["C1"] = 22
    session.session_scores["TEST-A"] = {SYNTHETIC: state}
    initial = plan_for(session)
    version = initial["plan"]["plan_version"]
    assert confirm(session, initial)["projected_by_activity"]["SEM-A"] == 5

    # The later quiz earns its full value first, leaving three points for SEM-A.
    assert complete(session, version, "QUIZ-M")["scores"]["category_scores"]["C1"]["current"] == 27
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: complete(session, version, "SEM-A"), range(2)))
    for result in results:
        progress = result["progress"]
        assert progress["activities"]["SEM-A"]["confirmed_added"] == 3
        assert "SEM-A" not in progress["projected_by_activity"]
        assert result["scores"]["category_scores"]["C1"]["current"] == 30
        assert result["scores"]["total_confirmed"] == progress["score_summary"]["baseline_total"]
    assert len(session.session_committed) == 2
    assert session.get_student_scores("TEST-B", SYNTHETIC)["category_scores"]["C1"]["current"] == 15

    persisted = json.loads(session.SESSION_FILE.read_text(encoding="utf-8"))
    assert persisted["confirmed_plans"]["TEST-A"][SYNTHETIC]["plan_version"] == version
    session._clear_session_state()
    session._load_session_from_disk()
    assert session.get_confirmed_plan_progress("TEST-A", version, SYNTHETIC)["activities"]["SEM-A"]["confirmed_added"] == 3
    next_plan = plan_for(session)
    assert next_plan["plan"]["score_summary"]["baseline_by_category"]["C1"] == 30
    assert not {"SEM-A", "QUIZ-M"}.intersection(row["activity_id"] for row in next_plan["plan"]["selected_activities"])
    history = confirm(session, next_plan)["past_completions"]
    assert {item["activity_id"]: item["confirmed_added"] for item in history} == {"SEM-A": 3, "QUIZ-M": 5}


def test_zero_points_is_persisted_as_completed_and_rollback_is_retryable(session, monkeypatch):
    initial = plan_for(session)
    version = confirm(session, initial)["plan_version"]
    session._get_student_scores("TEST-A", SYNTHETIC)["current"]["C1"] = 30
    with monkeypatch.context() as failure:
        def unavailable(**kwargs):
            raise OSError("test disk unavailable")
        failure.setattr(session, "_save_session_to_disk", unavailable)
        with pytest.raises(HTTPException) as error:
            complete(session, version, "SEM-A")
        assert error.value.status_code == 503
        assert session.session_committed == []
    status = complete(session, version, "SEM-A")["progress"]["activities"]["SEM-A"]
    assert status["status"] == "COMPLETED" and status["confirmed_added"] == 0
    assert complete(session, version, "SEM-A")["scores"]["saved_activities"][0]["completion_status"] == "COMPLETED"
    assert len(session.session_committed) == 1


def test_real_source_and_existing_calculator_award_use_same_scoreboard(session):
    initial = plan_for(session, source="real")
    progress = confirm(session, initial)
    activity_id, activity = next(
        (aid, data) for aid, data in progress["activities"].items()
        if data["status"] == "READY" and "quiz" in data["question"]
    )
    requirements = completion_catalog("real", HK1).metadata[activity_id]["completion_requirements"]
    thresholds = [row["threshold"] for row in requirements if row.get("type") == "quiz" and row.get("threshold") is not None]
    if thresholds:
        assert all(str(value) in activity["question"] for value in thresholds)
    else:
        assert "đạt" not in activity["question"]  # Do not invent a threshold absent from the current dataset.
    result = complete(session, progress["plan_version"], activity_id, term=HK1)
    assert result["scores"]["total_confirmed"] == result["progress"]["score_summary"]["baseline_total"]
    assert result["progress"]["official_award_verified"] is False
    record = completion_catalog("real", HK1).activities[activity_id]
    found = session._check_post_duplicate("manually-entered", record["source"]["URL_post"], "Raw text", "TEST-A", HK1)
    assert found[0] and found[3] == "saved"

    # A legacy calculator record may have its own extracted ID for the same URL.
    legacy = deepcopy(session.session_committed[0])
    legacy["student_id"] = "TEST-B"
    legacy["activity_id"] = "legacy-extractor-id"
    legacy.pop("completion_status")
    session.session_committed.append(legacy)
    session._get_student_scores("TEST-B", HK1)["current"][legacy["category_id"]] += legacy["confirmed_added"]
    plan_b = plan_for(session, student="TEST-B", source="real")
    assert activity_id not in {row["activity_id"] for row in plan_b["plan"]["selected_activities"]}


def test_same_post_saved_as_projected_is_upgraded_in_place(session):
    catalog = completion_catalog("synthetic")
    activity = catalog.activities["SEM-A"]
    session.session_committed.append({
        "kind": "score", "commit_id": "legacy-commit", "student_id": "TEST-A",
        "activity_id": "legacy-extractor-id", "title": activity["title"], "category_id": "C1", "term_id": SYNTHETIC,
        "confirmed_added": 0, "projected_added": 5, "committed_at": "2026-11-08T12:00:00+07:00",
        "catalog_entry": {**activity, "rule_id": "R19"},
    })
    session._get_student_scores("TEST-A", SYNTHETIC)["projected"]["C1"] = 5
    progress = confirm(session, plan_for(session))
    scores = complete(session, progress["plan_version"], "SEM-A")["scores"]
    assert scores["category_scores"]["C1"]["current"] == 20
    assert scores["category_scores"]["C1"]["projected"] == 0
    assert len(scores["saved_activities"]) == 1
    assert scores["saved_activities"][0]["commit_id"] == "legacy-commit"
