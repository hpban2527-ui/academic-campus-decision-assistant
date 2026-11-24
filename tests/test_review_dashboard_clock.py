"""The dashboard's "today" is the simulated clock of the selected term, never the system date."""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re

import pytest

from api import plan_completion, sp3_real, sp3_service, term_clock

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
TERMS = {"HK3_2025_2026": date(2026, 5, 17), "HK1_2026_2027": date(2026, 8, 29)}


def _day(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp).date()


def _synthetic_clock() -> str:
    fixture = json.loads(sp3_service.DEMO.read_text(encoding="utf-8"))
    return fixture["steps"]["step1"]["feasibility_request"]["context"]["as_of"]


def test_synthetic_scenario_and_each_term_use_different_dates() -> None:
    assert _day(_synthetic_clock()) == date(2026, 11, 8)
    assert {term: _day(term_clock.get_term(term).as_of) for term in TERMS} == TERMS


@pytest.mark.parametrize("term", list(TERMS))
def test_plan_results_carry_the_clock_the_dashboard_reads(term: str) -> None:
    synthetic = sp3_service.demo_plan("first_plan")
    real = sp3_real.real_plan("first_plan", term_id=term, target_total=80)
    assert synthetic["plan"]["context"]["as_of"] == _synthetic_clock()
    assert real["plan"]["context"]["as_of"] == real["as_of"] == term_clock.get_term(term).as_of


def test_synthetic_demo_student_has_nothing_today_but_everything_ahead() -> None:
    """Documents what "Hom nay" shows for the synthetic demo student (no data was changed to hide it)."""
    today = _day(_synthetic_clock())
    blocks = [
        _day(block["start"])
        for item in sp3_service.demo_plan("first_plan")["plan"]["selected_activities"]
        for block in item["scheduled_blocks"]
    ]
    assert blocks and today not in blocks
    assert all(today < day for day in blocks), "every synthetic activity is in the future"
    assert min(blocks) == date(2026, 11, 9) and (min(blocks) - today).days <= 6  # inside the 7-day agenda


@pytest.mark.parametrize("term", list(TERMS))
def test_real_demo_plan_starts_on_or_after_the_first_day_of_the_term(term: str) -> None:
    """Nothing is planned before the term's simulated day; both terms start on a weekend, so "today" may be empty."""
    today = TERMS[term]
    blocks = [
        _day(block["start"])
        for item in sp3_real.real_plan("first_plan", term_id=term, target_total=80)["plan"]["selected_activities"]
        for block in item["scheduled_blocks"]
    ]
    assert blocks and min(blocks) >= today
    assert term_clock.get_term(term).window_start[:10] == today.isoformat()
    assert today.weekday() >= 5


def test_one_clock_per_term_everywhere(monkeypatch) -> None:
    """Planner, planning window, completion clock and the UI all read the same term clock."""
    monkeypatch.delenv("UNILIFE_COMPLETION_AS_OF", raising=False)
    for term in TERMS:
        clock = term_clock.get_term(term)
        assert sp3_real.real_plan("first_plan", term_id=term, target_total=80)["as_of"] == clock.as_of
        assert plan_completion.completion_clock(term).isoformat() == clock.as_of
    assert plan_completion.completion_clock(term_clock.SYNTHETIC_TERM_ID).isoformat() == _synthetic_clock()
    # The page embeds no date: it loads the clock of the selected term from the server.
    assert "const DEMO_TODAY_ISO" not in HTML and "2026-10-25" not in HTML
    assert "/api/clock?term_id=" in HTML and "/api/terms" in HTML
    assert "let TERM_TODAY_ISO = null;" in HTML


def test_dashboard_code_never_reads_the_system_date() -> None:
    block = HTML.split("var cpdView", 1)[1].split("</script>", 1)[0]
    assert "cpdSimulationToday(plan)" in block and "cpdSimulationToday(state.plan)" in block
    assert "termClock.as_of : plan.as_of" in block
    assert not re.search(r"new Date\(\)\.(getFullYear|getMonth|getDate|toLocaleDateString)", block)
    assert "Date.now" not in block
