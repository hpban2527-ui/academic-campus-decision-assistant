"""One simulated clock per semester: clocks, planning, review, state, completion and legacy data by term.

The expected values are hand-checked against data/config/semesters.json (HK3 2026-05-17..2026-08-28, HK1
2026-08-29..2026-11-15, as_of = first day 00:00 +07:00) and the committed operational dataset.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

import pytest

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from api import plan_completion, server, sp3_real, term_clock
from personalization.models import StudentPreference

HK3, HK1 = "HK3_2025_2026", "HK1_2026_2027"
SYNTHETIC = "SYNTHETIC-DEMO"
CLOCKS = {
    HK3: {"term_start": "2026-05-17", "term_end": "2026-08-28", "as_of": "2026-05-17T00:00:00+07:00",
          "window_start": "2026-05-17T00:00:00+07:00", "window_end": "2026-08-29T00:00:00+07:00"},
    HK1: {"term_start": "2026-08-29", "term_end": "2026-11-15", "as_of": "2026-08-29T00:00:00+07:00",
          "window_start": "2026-08-29T00:00:00+07:00", "window_end": "2026-11-16T00:00:00+07:00"},
}
PREFERENCE = {
    "topic_preferences": [], "category_priorities": [], "campus_preferences": [], "mode_preferences": [],
    "time_preferences": [], "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
    "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None}, "strategy": "BALANCED",
}
DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


@pytest.fixture
def session(tmp_path, monkeypatch):
    for name, value in (
        ("SESSION_FILE", tmp_path / "session.json"), ("session_scores", {}), ("session_committed", []),
        ("session_confirmed_plans", {}), ("session_preferences", {}), ("review_queue", []), ("student_dedupers", {}),
        ("session_simulation_dates", {}),
    ):
        monkeypatch.setattr(server, name, value)
    monkeypatch.delenv("UNILIFE_COMPLETION_AS_OF", raising=False)
    return TestClient(server.app)


def day(value: str) -> date:
    return datetime.fromisoformat(value).date()


def weekly(blocks: list[dict], week_start: str, start: str, until: str) -> dict:
    return {
        "availability_version": "sp3-availability/0.2", "timezone": "Asia/Ho_Chi_Minh", "week_start": week_start,
        "apply_scope": "SEMESTER_WEEKLY", "effective_from": start, "effective_until": until,
        "weekly_blocks": blocks, "exceptions": [], "busy_intervals": [],
    }


def options_body(**extra) -> dict:
    return {"confirmed": True, "preference": PREFERENCE, "scenario": "first_plan", "total_target": 80,
            "busy_intervals": [], **extra}


def plan_of(client, term, student="TERM-A", target=80, **extra) -> dict:
    response = client.post(f"/api/sp3/demo/plan?source=real&term_id={term}&student_id={student}",
                           json={"scenario": "first_plan", "total_target": target, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, result, student="TERM-A", term=None):
    return client.post("/api/sp3/confirmed-plan", json={
        "student_id": student, "term_id": term or result["plan"]["context"]["term_id"], "offer": result["completion_offer"]})


def advance(client, value, *, student="TERM-A", term=HK1):
    return client.post("/api/clock/advance", json={"student_id": student, "term_id": term, "date": value})


def test_advance_is_forward_only_idempotent_and_scoped(session, monkeypatch):
    def read(student=None, term=HK1):
        params = {"term_id": term, **({"student_id": student} if student else {})}
        return session.get("/api/clock", params=params).json()

    default = read("TERM-A")
    assert default == read()
    first = advance(session, default["term_start"]).json()
    assert first["as_of"] == "2026-08-29T23:59:59+07:00"
    assert first["window_start"] == first["as_of"] and first["clock_version"] != default["clock_version"]
    assert first["window_end"] == default["window_end"]
    current = advance(session, "2026-09-10").json()
    assert current == read("TERM-A") and current["clock_version"] != first["clock_version"]
    assert read() == read("TERM-B") == default
    assert read("TERM-A", HK3) == read(term=HK3)
    before = server.SESSION_FILE.read_bytes()
    assert advance(session, "2026-09-10").json() == current
    backward = advance(session, "2026-08-29")
    assert backward.status_code == 409 and backward.json()["detail"]["clock"] == current
    for invalid in ("2026-9-10", "20260910", "2026-02-30", "2026-08-28", "2026-11-16", current["as_of"]):
        assert advance(session, invalid).status_code == 422
    assert advance(session, "2026-09-10", student=" ").status_code == 422
    assert advance(session, "2026-09-10", term=SYNTHETIC).status_code == 422
    assert advance(session, "2026-09-10", term="UNKNOWN").status_code == 422
    assert server.SESSION_FILE.read_bytes() == before

    server._clear_session_state()
    server._load_session_from_disk()
    assert read("TERM-A") == current
    with monkeypatch.context() as patch:
        def fail(*, strict):
            raise OSError("Write failed")

        patch.setattr(server, "_save_session_to_disk", fail)
        assert advance(session, "2026-09-11").status_code == 503
    assert read("TERM-A") == current
    assert advance(session, default["term_end"]).status_code == 200


def test_advanced_clock_is_used_by_real_options_review_catalog_and_availability(session):
    params = {"source": "real", "term_id": HK3, "student_id": "TERM-A"}
    route = "/api/sp3/personalized/"
    old = plan_of(session, HK3)
    prepared = sp3_real._load_base(HK3)
    clock = advance(session, "2026-05-18", term=HK3).json()
    expected = {key: clock[key] for key in ("term_id", "as_of", "clock_version")}

    def check(data):
        assert {key: data[key] for key in expected} == expected

    assert sp3_real._load_base(HK3) is prepared
    check(session.get("/api/sp3/catalog", params=params).json())
    availability = weekly([{"day_of_week": "MONDAY", "start_time": "07:00", "end_time": "21:00"}],
                          "2026-05-18", clock["term_start"], clock["term_end"])
    resolved = session.post("/api/sp3/availability/resolve", json={**params, "availability": availability}).json()
    check(resolved)
    assert resolved["available_intervals"][0]["start"] == "2026-05-25T07:00:00+07:00"
    check(plan_of(session, HK3))
    options = session.post(route + "options", params=params, json=options_body()).json()
    check(options)
    result = next(item["result"] for item in options["options"] if item["status"] == "READY")
    check(result)
    assert result["clock_version"] != old["clock_version"]
    assert result["plan"]["context"]["as_of"] == clock["as_of"]
    assert all(datetime.fromisoformat(block["start"]) >= datetime.fromisoformat(clock["as_of"])
               for item in result["plan"]["selected_activities"] for block in item["scheduled_blocks"])
    for endpoint, extra in (("alternatives", {}), ("what-if-skip", {}), ("swap-preview", {"add_activity_id": None})):
        for base, status in ((old, 422), (result, 200)):
            body = {"confirmed_profile": True, "preference": PREFERENCE, "base_result": base,
                    "remove_activity_id": base["plan"]["selected_activities"][0]["activity_id"], **extra}
            response = session.post(route + endpoint, params=params, json=body)
            assert response.status_code == status, response.text
            if status == 200:
                check(response.json())
            else:
                assert "Ngày mô phỏng" in response.json()["detail"]


# ---------------------------------------------------------------- 1. the clock endpoints
def test_clock_endpoints_match_the_configured_terms(session):
    listed = session.get("/api/terms").json()["terms"]
    assert [item["term_id"] for item in listed] == [HK3, HK1]
    versions = set()
    for item in listed:
        expected = CLOCKS[item["term_id"]]
        assert {key: item[key] for key in expected} == expected
        assert item["timezone"] == "Asia/Ho_Chi_Minh"
        assert item == session.get("/api/clock", params={"term_id": item["term_id"]}).json()
        assert item["clock_version"].startswith("clk-") and len(item["clock_version"]) == 16
        versions.add(item["clock_version"])
    assert len(versions) == 2
    assert session.get("/api/clock", params={"term_id": HK3}).json()["term_label"] == "HK3 · 2025–2026"
    assert session.get("/api/clock", params={"term_id": HK1}).json()["term_label"] == "HK1 · 2026–2027"
    for params in ({"term_id": "HK2_2025_2026"}, {"term_id": SYNTHETIC}, {}):
        assert session.get("/api/clock", params=params).status_code == 422


def test_dates_come_only_from_the_semester_config(tmp_path, monkeypatch):
    config = tmp_path / "semesters.json"
    config.write_text(json.dumps({"timezone": "+07:00", "semesters": [
        {"id": HK1, "programs": {"standard": ["2030-01-02", "2030-01-31"], "high_quality": ["2030-01-02", "2030-01-31"]}},
    ]}), encoding="utf-8")
    monkeypatch.setattr(term_clock, "SEMESTERS_PATH", config)
    term_clock._terms.cache_clear()
    try:
        clock = term_clock.get_term(HK1)
        assert (clock.as_of, clock.window_end) == ("2030-01-02T00:00:00+07:00", "2030-02-01T00:00:00+07:00")
        with pytest.raises(term_clock.UnknownTermError):
            term_clock.get_term(HK3)
    finally:
        term_clock._terms.cache_clear()


# ---------------------------------------------------------------- 2. term scope, 3. registration, 10. cache
def test_an_activity_outside_the_selected_term_is_never_planned(session):
    selected = {}
    for term in (HK3, HK1):
        result = plan_of(session, term, target=100)
        catalog = session.get(f"/api/sp3/catalog?source=real&term_id={term}").json()
        in_scope = {row["activity"]["activity_id"] for row in catalog["activities"] if row["term_scope"] == "IN_SCOPE"}
        starts = {row["activity"]["activity_id"]: row["activity"]["start"] for row in catalog["activities"]}
        selected[term] = {row["activity_id"] for row in result["plan"]["selected_activities"]}
        assert selected[term] and selected[term] <= in_scope
        for activity_id in selected[term]:
            assert CLOCKS[term]["term_start"] <= starts[activity_id][:10] <= CLOCKS[term]["term_end"]
        for item in result["plan"]["selected_activities"]:
            for block in item["scheduled_blocks"]:
                assert CLOCKS[term]["window_start"] <= block["start"] and block["end"] <= CLOCKS[term]["window_end"]
    assert selected[HK3].isdisjoint(selected[HK1])  # an activity belongs to exactly one term, by its own start date
    assert 0 < len(in_scope) < len(catalog["activities"])  # the HK1 store view is filtered, not the whole dataset


def test_registration_is_open_or_closed_against_the_term_clock(session):
    closed_counts = {}
    for term in (HK3, HK1):
        result = plan_of(session, term)
        as_of = datetime.fromisoformat(CLOCKS[term]["as_of"])
        closed = 0
        for row in result["feasibility"]["candidates"]:
            deadline = row["activity"].get("registration_deadline")
            if deadline is None:
                continue
            passed = as_of >= datetime.fromisoformat(deadline)
            assert ("DEADLINE_PASSED" in row["feasibility"]["reason_codes"]) == passed, (term, row["activity"]["activity_id"])
            closed += passed
        closed_counts[term] = closed
    # Hand-checked in data/operational/activity_dataset.json: one deadline (2026-04-10) precedes 2026-05-17 and
    # seventeen deadlines precede 2026-08-29; the same posts are judged against a different clock in each term.
    assert closed_counts == {HK3: 1, HK1: 17}


def test_planning_hk3_hk1_hk3_returns_each_terms_own_result(session):
    first = plan_of(session, HK3)
    other = plan_of(session, HK1)
    again = plan_of(session, HK3)
    assert first["plan"]["plan_version"] == again["plan"]["plan_version"] != other["plan"]["plan_version"]
    for result, term in ((first, HK3), (other, HK1), (again, HK3)):
        assert (result["term_id"], result["as_of"]) == (term, CLOCKS[term]["as_of"])
        assert result["plan"]["context"]["term_id"] == term and result["plan"]["context"]["as_of"] == CLOCKS[term]["as_of"]
    clocks = {term_clock.get_term(term).clock_version for term in (HK3, HK1)}
    assert {key[2] for key in sp3_real._cache["terms"]} >= clocks
    assert {first["clock_version"], other["clock_version"]} == clocks


# ---------------------------------------------------------------- 4. weekly busy blocks keep weekday and hours
@pytest.mark.parametrize("term, week_start, mondays", [(HK3, "2026-05-18", 15), (HK1, "2026-08-31", 11)])
def test_a_weekly_block_keeps_weekday_and_hours_in_every_week_of_the_term(session, term, week_start, mondays):
    clock = CLOCKS[term]
    body = {"term_id": term, "availability": weekly(
        [{"day_of_week": "MONDAY", "start_time": "08:00", "end_time": "10:00"}], week_start, clock["term_start"], clock["term_end"])}
    resolved = session.post("/api/sp3/availability/resolve", json=body).json()
    intervals = resolved["available_intervals"]
    assert (resolved["term_id"], resolved["as_of"]) == (term, clock["as_of"])
    assert len(intervals) == mondays
    for item in intervals:
        assert day(item["start"]).weekday() == 0 and item["start"][11:] == "08:00:00+07:00" and item["end"][11:] == "10:00:00+07:00"
        assert clock["term_start"] <= item["start"][:10] <= clock["term_end"]
    assert session.post("/api/sp3/availability/resolve", json={**body, "term_id": "HK2_2025_2026"}).status_code == 422
    assert session.post("/api/sp3/availability/resolve", json={"availability": body["availability"]}).status_code == 422


# ---------------------------------------------------------------- 5. review, alternatives and what-if use the term
def test_review_alternatives_and_what_if_use_the_current_term_clock_and_busy_schedule(session):
    clock = CLOCKS[HK3]
    busy_day = "2026-06-05"
    availability = weekly([{"day_of_week": name, "start_time": "07:00", "end_time": "21:00"} for name in DAYS],
                          "2026-05-18", clock["term_start"], clock["term_end"])
    availability["busy_intervals"] = [{"start": f"{busy_day}T00:00:00+07:00", "end": f"{busy_day}T23:59:00+07:00"}]
    response = session.post(f"/api/sp3/personalized/options?source=real&term_id={HK3}&student_id=TERM-A",
                            json=options_body(availability=availability))
    assert response.status_code == 200, response.text
    base = next(option["result"] for option in response.json()["options"] if option["status"] == "READY")
    assert base["term_id"] == HK3 and base["as_of"] == clock["as_of"]
    assert all(not block["start"].startswith(busy_day)
               for item in base["plan"]["selected_activities"] for block in item["scheduled_blocks"])
    removed = base["plan"]["selected_activities"][0]["activity_id"]
    common = {"confirmed_profile": True, "preference": PREFERENCE, "base_result": base,
              "remove_activity_id": removed, "availability": availability}
    for path, extra in (("what-if-skip", {}), ("alternatives", {"limit": 3}), ("swap-preview", {"add_activity_id": None})):
        reply = session.post(f"/api/sp3/personalized/{path}?source=real&term_id={HK3}&student_id=TERM-A", json={**common, **extra})
        assert reply.status_code == 200, (path, reply.text)
        body = reply.json()
        results = [item["preview"]["result"] for item in body["items"]] if path == "alternatives" else [body["result"]]
        for result in results:
            assert (result["term_id"], result["as_of"]) == (HK3, clock["as_of"]), path
            assert result["plan"]["context"]["as_of"] == clock["as_of"]
            assert all(not block["start"].startswith(busy_day)
                       for item in result["plan"]["selected_activities"] for block in item["scheduled_blocks"]), path
    # A plan made in HK3 is not reviewed on the HK1 clock.
    wrong = session.post(f"/api/sp3/personalized/what-if-skip?source=real&term_id={HK1}&student_id=TERM-A", json=common)
    assert wrong.status_code == 422 and "another term" in wrong.json()["detail"]
    assert session.post("/api/sp3/personalized/what-if-skip?source=real&student_id=TERM-A", json=common).status_code == 422


def test_the_synthetic_scenario_has_its_own_id_and_clock(session):
    result = session.post("/api/sp3/demo/plan", json={"scenario": "first_plan"}).json()
    assert result["term"] == SYNTHETIC and result["plan"]["context"]["as_of"] == "2026-11-08T20:00:00+07:00"
    assert session.get("/api/sp3/catalog").json()["term"] == {"id": SYNTHETIC, "label": "Synthetic test scenario"}
    assert term_clock.as_of_of(SYNTHETIC) == "2026-11-08T20:00:00+07:00"
    assert SYNTHETIC not in [item.term_id for item in term_clock.list_terms()]


# ---------------------------------------------------------------- 6-9. state, completion and mismatched terms
def test_switching_terms_keeps_each_terms_state_and_plan(session, monkeypatch):
    plans = {term: plan_of(session, term) for term in (HK3, HK1)}
    for term in (HK3, HK1):
        progress = confirm(session, plans[term]).json()
        assert (progress["term_id"], progress["as_of"]) == (term, CLOCKS[term]["as_of"])
    assert set(server.session_confirmed_plans["TERM-A"]) == {HK3, HK1}
    monkeypatch.setenv("UNILIFE_COMPLETION_AS_OF", "2026-12-01T00:00:00+07:00")  # tests only: let activities have ended
    version3 = plans[HK3]["plan"]["plan_version"]
    ready = next(aid for aid, status in session.get(
        "/api/sp3/confirmed-plan/progress", params={"student_id": "TERM-A", "term_id": HK3, "plan_version": version3}
    ).json()["activities"].items() if status["status"] == "READY")
    done = session.post("/api/sp3/confirmed-plan/complete", json={
        "student_id": "TERM-A", "term_id": HK3, "plan_version": version3, "activity_id": ready, "affirmed": True})
    assert done.status_code == 200, done.text
    hk3_scores = session.get("/api/scores", params={"student_id": "TERM-A", "term_id": HK3}).json()
    hk1_scores = session.get("/api/scores", params={"student_id": "TERM-A", "term_id": HK1}).json()
    assert hk3_scores["saved_activities"][0]["completion_status"] == "COMPLETED"
    assert hk1_scores["saved_activities"] == [] and hk1_scores["is_baseline"] is True
    assert (hk3_scores["term_id"], hk1_scores["term_id"]) == (HK3, HK1)
    # HK3 -> HK1 -> HK3: each term still has its own confirmed plan and scoreboard.
    for term in (HK1, HK3, HK1, HK3):
        version = plans[term]["plan"]["plan_version"]
        progress = session.get("/api/sp3/confirmed-plan/progress",
                               params={"student_id": "TERM-A", "term_id": term, "plan_version": version}).json()
        assert progress["term_id"] == term and progress["scores"]["term_id"] == term
        assert [row["term_id"] for row in server.session_committed] == [HK3]


def test_reload_restores_the_term_and_its_confirmed_plan(session):
    plans = {term: plan_of(session, term) for term in (HK3, HK1)}
    for term in (HK3, HK1):
        confirm(session, plans[term])
    on_disk = json.loads(server.SESSION_FILE.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 4 and set(on_disk["confirmed_plans"]["TERM-A"]) == {HK3, HK1}
    server._clear_session_state()
    server._load_session_from_disk()
    for term in (HK3, HK1):
        progress = session.get("/api/sp3/confirmed-plan/progress", params={
            "student_id": "TERM-A", "term_id": term, "plan_version": plans[term]["plan"]["plan_version"]})
        assert progress.status_code == 200 and progress.json()["term_id"] == term


def test_a_future_activity_cannot_be_completed_and_completing_twice_adds_points_once(session):
    result = plan_of(session, HK1, target=100)
    version = result["plan"]["plan_version"]
    progress = confirm(session, result).json()
    snapshot = json.loads(server.SESSION_FILE.read_text(encoding="utf-8"))["confirmed_plans"]["TERM-A"][HK1]
    stale_offer = plan_of(session, HK1, target=95)
    # At the simulated start of the term nothing has happened yet: no points are earned by confirming.
    assert progress["score_summary"]["baseline_total"] == session.get(
        "/api/scores", params={"student_id": "TERM-A", "term_id": HK1}).json()["total_confirmed"]
    assert server.session_committed == []
    not_due = next(aid for aid, status in progress["activities"].items() if status["status"] == "NOT_DUE")
    body = {"student_id": "TERM-A", "term_id": HK1, "plan_version": version, "activity_id": not_due, "affirmed": True}
    blocked = session.post("/api/sp3/confirmed-plan/complete", json=body)
    assert blocked.status_code == 409 and blocked.json()["detail"]["status"] == "NOT_DUE"
    assert datetime.fromisoformat(blocked.json()["detail"]["available_at"]) > datetime.fromisoformat(CLOCKS[HK1]["as_of"])
    assert server.session_committed == []
    clock = advance(session, blocked.json()["detail"]["available_at"][:10]).json()
    current = session.get("/api/sp3/confirmed-plan/progress", params={
        key: body[key] for key in ("student_id", "term_id", "plan_version")
    }).json()
    assert current["as_of"] == clock["as_of"] and current["clock_version"] == clock["clock_version"]
    assert current["activities"][not_due]["status"] == "READY"
    assert current["score_summary"]["baseline_total"] == progress["score_summary"]["baseline_total"]
    assert server.session_committed == []
    assert server.session_confirmed_plans["TERM-A"][HK1] == snapshot
    assert snapshot["context"]["as_of"] == result["as_of"] and snapshot["schedule"]
    assert confirm(session, stale_offer).status_code == 409
    assert confirm(session, result).status_code == 200
    first = session.post("/api/sp3/confirmed-plan/complete", json=body)
    server._clear_session_state()
    server._load_session_from_disk()
    again = session.post("/api/sp3/confirmed-plan/complete", json=body)
    assert first.status_code == again.status_code == 200
    assert first.json()["scores"]["total_confirmed"] > progress["score_summary"]["baseline_total"]
    assert first.json()["scores"]["total_confirmed"] == again.json()["scores"]["total_confirmed"]
    assert again.json()["progress"]["activities"][not_due]["status"] == "COMPLETED"
    assert server.session_confirmed_plans["TERM-A"][HK1] == snapshot
    assert len(server.session_committed) == 1 and server.session_committed[0]["term_id"] == HK1


def test_a_mismatched_term_id_is_rejected_with_409(session):
    hk1, hk3 = plan_of(session, HK1), plan_of(session, HK3)
    wrong = confirm(session, hk1, term=HK3)
    assert wrong.status_code == 409 and "học kỳ khác" in wrong.json()["detail"]
    assert server.session_confirmed_plans == {}
    assert confirm(session, hk3).status_code == 200 and confirm(session, hk1).status_code == 200
    version = hk1["plan"]["plan_version"]
    complete = session.post("/api/sp3/confirmed-plan/complete", json={
        "student_id": "TERM-A", "term_id": HK3, "plan_version": version, "activity_id": "x", "affirmed": True})
    assert complete.status_code == 409 and "học kỳ khác" in complete.json()["detail"]
    progress = session.get("/api/sp3/confirmed-plan/progress",
                           params={"student_id": "TERM-A", "term_id": HK3, "plan_version": version})
    assert progress.status_code == 409
    unknown = session.get("/api/sp3/confirmed-plan/progress",
                          params={"student_id": "TERM-A", "term_id": "NOPE", "plan_version": version})
    assert unknown.status_code == 422
    assert session.post("/api/sp3/demo/plan?source=real", json={"scenario": "first_plan"}).status_code == 422


# ---------------------------------------------------------------- 11. legacy session files
def legacy_file(path: Path, **overrides) -> None:
    entry = {"kind": "score", "student_id": "OLD-A", "confirmed_added": 5, "projected_added": 0, "category_id": "C1"}
    data = {
        "schema_version": 3,
        "session_scores": {
            "OLD-A": {"current": {"C1": 20}, "projected": {"C1": 0}},   # every entry names HK1
            "OLD-B": {"current": {"C1": 19}, "projected": {"C1": 0}},   # no entry at all: no evidence
        },
        "confirmed_preferences": {"OLD-A": {"preference": {}}},
        "confirmed_plans": {
            "OLD-A": {"student_id": "OLD-A", "plan_version": "p-old", "context": {"term_id": HK1}},
            "OLD-B": {"student_id": "OLD-B", "plan_version": "p-synth", "context": {"term_id": SYNTHETIC}},
            "OLD-E": {"student_id": "OLD-E", "plan_version": "p-none", "context": {}},
        },
        "committed": [
            {**entry, "commit_id": "c1", "term_id": HK1, "catalog_entry": {}},
            {**entry, "commit_id": "c2", "student_id": "OLD-C", "catalog_entry": {"start": "2026-06-01T09:00:00+07:00"}},
            {**entry, "commit_id": "c3", "student_id": "OLD-D", "catalog_entry": {}},
        ],
        **overrides,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_legacy_session_file_is_assigned_only_by_stored_evidence(session):
    legacy_file(server.SESSION_FILE)
    server._load_session_from_disk()
    assert set(server.session_scores["OLD-A"]) == {HK1} and set(server.session_scores["OLD-B"]) == {term_clock.UNASSIGNED_TERM_ID}
    assert set(server.session_confirmed_plans["OLD-A"]) == {HK1}
    assert set(server.session_confirmed_plans["OLD-B"]) == {SYNTHETIC}  # the synthetic scenario keeps its own key
    assert set(server.session_confirmed_plans["OLD-E"]) == {term_clock.UNASSIGNED_TERM_ID}  # no term evidence: set aside
    by_id = {entry["commit_id"]: entry["term_id"] for entry in server.session_committed}
    assert by_id == {"c1": HK1, "c2": HK3, "c3": term_clock.UNASSIGNED_TERM_ID}  # c2: its activity date is in HK3
    assert server.session_preferences == {"OLD-A": {"preference": {}}}  # general preferences stay per student
    # What is set aside is never shown for a real term.
    assert session.get("/api/scores", params={"student_id": "OLD-B", "term_id": HK1}).json()["total_confirmed"] == 50
    assert session.get("/api/scores", params={"student_id": "OLD-D", "term_id": HK1}).json()["saved_activities"] == []
    assert [row["commit_id"] for row in session.get(
        "/api/scores", params={"student_id": "OLD-A", "term_id": HK1}).json()["saved_activities"]] == ["c1"]
    assert session.get("/api/scores", params={"student_id": "OLD-A", "term_id": HK3}).json()["saved_activities"] == []
    # Planning with such an account does not crash and ignores the unassigned history.
    assert plan_of(session, HK1, student="OLD-D")["plan"]["status"] in {"TARGET_MET", "PARTIAL"}
    assert advance(session, "2026-09-10", student="OLD-A").status_code == 200
    server._clear_session_state()
    server._load_session_from_disk()
    assert server.session_preferences == {"OLD-A": {"preference": {}}}
    assert server.session_scores["OLD-B"][term_clock.UNASSIGNED_TERM_ID]["current"]["C1"] == 19
    assert server.session_confirmed_plans["OLD-E"][term_clock.UNASSIGNED_TERM_ID]["plan_version"] == "p-none"
    assert {entry["commit_id"]: entry["term_id"] for entry in server.session_committed} == by_id


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"schema_version": 99}', '{"schema_version": 3, "committed": ["x", 7],'
                                     ' "session_scores": {"A": 5}, "confirmed_plans": {"A": "oops"}}'])
def test_an_unreadable_or_odd_session_file_never_breaks_loading(session, content):
    server.SESSION_FILE.write_text(content, encoding="utf-8")
    server._load_session_from_disk()
    assert session.get("/api/health").status_code == 200
    assert session.get("/api/scores", params={"student_id": "A", "term_id": HK1}).status_code == 200


def test_missing_or_unknown_term_is_rejected_on_state_endpoints(session):
    assert session.get("/api/scores", params={"student_id": "A"}).status_code == 422
    assert session.get("/api/scores", params={"student_id": "A", "term_id": "NOPE"}).status_code == 422
    assert session.get("/api/scores", params={"student_id": "A", "term_id": SYNTHETIC}).status_code == 200
    with pytest.raises(term_clock.UnknownTermError):
        plan_completion.completion_clock("NOPE")
