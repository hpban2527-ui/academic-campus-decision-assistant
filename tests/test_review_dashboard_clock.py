"""The dashboard's "today" is the planner's demo clock of the confirmed plan's source, never the system date."""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re

from api import demo_clock, plan_completion, sp3_real, sp3_service

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def _day(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp).date()


def _synthetic_clock() -> str:
    fixture = json.loads(sp3_service.DEMO.read_text(encoding="utf-8"))
    return fixture["steps"]["step1"]["feasibility_request"]["context"]["as_of"]


def test_synthetic_and_real_sources_use_different_demo_dates() -> None:
    assert _day(_synthetic_clock()) == date(2026, 11, 8)
    assert _day(sp3_real.AS_OF) == date(2026, 10, 25)


def test_plan_results_carry_the_clock_the_dashboard_reads() -> None:
    synthetic = sp3_service.demo_plan("first_plan")
    real = sp3_real.real_plan("first_plan", target_total=80)
    assert synthetic["plan"]["context"]["as_of"] == _synthetic_clock()
    assert real["plan"]["context"]["as_of"] == sp3_real.AS_OF


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


def test_real_demo_plan_starts_on_or_after_the_demo_day() -> None:
    """The real store plans from the demo day: nothing before it, and "Hom nay" can show today's agenda."""
    today = _day(sp3_real.AS_OF)
    blocks = [
        _day(block["start"])
        for item in sp3_real.real_plan("first_plan", target_total=80)["plan"]["selected_activities"]
        for block in item["scheduled_blocks"]
    ]
    assert blocks and min(blocks) >= today
    assert sp3_real.WINDOW_START[:10] == today.isoformat()


def test_one_demo_clock_everywhere(monkeypatch) -> None:
    """Planner, planning window, completion clock and the UI all use the same demo day."""
    monkeypatch.delenv("UNILIFE_COMPLETION_AS_OF", raising=False)
    assert sp3_real.AS_OF == demo_clock.DEMO_AS_OF
    assert plan_completion.completion_clock().isoformat() == demo_clock.DEMO_AS_OF
    assert f"const DEMO_TODAY_ISO = '{demo_clock.DEMO_TODAY}';" in HTML


def test_dashboard_code_never_reads_the_system_date() -> None:
    block = HTML.split("var cpdView", 1)[1].split("</script>", 1)[0]
    assert "cpdVn(plan.as_of).date" in block and "cpdVn(state.plan.as_of).date" in block
    assert not re.search(r"new Date\(\)\.(getFullYear|getMonth|getDate|toLocaleDateString)", block)
    assert "Date.now" not in block
