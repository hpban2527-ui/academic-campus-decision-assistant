"""Static checks of the confirmed-plan dashboard in web/index.html (REVIEW-DASH blocks).

Behaviour in a real browser is covered by scripts/verify_review_dashboard_e2e.py; run it from pytest
with RUN_BROWSER_E2E=1. These checks keep the shared-file edits findable and the data contract intact.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _blocks(text: str) -> list[str]:
    pattern = re.compile(r"(?:<!--|//)\s*REVIEW-DASH START\s*(?:-->)?(.*?)(?:<!--|//)\s*REVIEW-DASH END", re.S)
    return pattern.findall(text)


def test_every_edit_is_marked_and_balanced() -> None:
    starts = len(re.findall(r"REVIEW-DASH START", HTML))
    ends = len(re.findall(r"REVIEW-DASH END", HTML))
    assert starts == ends >= 8
    # The big script block nests its own JS markers inside the HTML ones; every start still has an end.
    assert len(_blocks(HTML)) >= 7


def test_default_local_data_has_the_confirmed_plan_keys() -> None:
    body = HTML.split("function createDefaultLocalUserData", 1)[1].split("function migrateLocalUserData", 1)[0]
    for key in ("confirmed_plan: null", "pending_plan_notice: false", "invalidated:", "confirmed_plan_basis: null"):
        assert key in body
    # The keys owned by others are not redefined here.
    assert body.count("canonical_availability:") == 1 and body.count("confirmed_preference:") == 1


def test_confirmed_plan_is_written_only_from_an_engine_result() -> None:
    check = HTML.split("function cpdIsEngineResult", 1)[1].split("function cpdActivitiesFromResult", 1)[0]
    assert "sp3plan-[0-9a-f]{16}" in check and "CPD_ACTIVE_STATUSES" in check
    mapping = HTML.split("function cpdActivitiesFromResult", 1)[1].split("function confirmConfirmedPlan", 1)[0]
    body = HTML.split("function confirmConfirmedPlan", 1)[1].split("// ---- review hook", 1)[0]
    assert "if (!cpdIsEngineResult(result)) throw" in body and "cpdActivitiesFromResult(result)" in body
    for field in ("plan_version", "based_on", "confirmed_at", "source", "option_label", "target_total",
                  "score_summary", "activities"):
        assert field in body, field
    for field in ("activity_id", "criterion", "effective_gain", "mode", "campus", "location",
                  "registration_deadline", "completion_requirements", "scheduled_blocks", "source_url"):
        assert field in mapping, field
    assert "pending_plan_notice = false" in body


def test_planner_rerun_sets_a_notice_and_never_writes_the_confirmed_plan() -> None:
    note = HTML.split("function reviewDashNotePlannerResult", 1)[1].split("// Writes confirmed_plan", 1)[0]
    assert "pending_plan_notice = true" in note and "confirmed_plan =" not in note
    run = HTML.split("async function runSp3Planner", 1)[1].split("// Steps 2 & 3", 1)[0]
    assert "reviewDashNotePlannerResult();" in run
    persist = HTML.split("function persistCurrentUserData", 1)[1].split("function normalizeStoredScores", 1)[0]
    assert "reviewDashSyncInvalidation(saved);" in persist
    assert "confirmed_plan =" not in persist


def test_dashboard_ui_elements_and_texts() -> None:
    for text in ("Xác nhận kế hoạch", "Có kế hoạch mới chưa chốt", "Kế hoạch bị ảnh hưởng", "Đến Lập lịch",
                 "Hôm nay", "Tuần", "Tháng", "TIẾN ĐỘ THEO KẾ HOẠCH", "Bạn chưa chốt kế hoạch nào"):
        assert text in HTML, text
    for element in ("confirmedPlanDashboard", "cpdBannerPending", "cpdBannerInvalid", "cpdEmpty", "cpdContent",
                    "confirmPlanBar", "btnConfirmPlan", "cpdDetail"):
        assert f'id="{element}"' in HTML, element
    assert "setConfirmedPlanView" in HTML and "cpdView = 'today'" in HTML  # default view


def test_dashboard_uses_the_planner_clock_and_computes_no_scores() -> None:
    block = HTML.split("var cpdView", 1)[1].split("</script>", 1)[0]
    assert "cpdVn(plan.as_of).date" in block
    # No system-date based "today": the only `new Date()` calls stamp storage times.
    assert block.count("new Date()") == block.count("new Date().toISOString()") == 2
    assert "Date.now" not in block
    progress = block.split("function cpdRenderProgress", 1)[1].split("function cpdOpenActivity", 1)[0]
    # Every number comes from score_summary / target_total; the only arithmetic scales bar widths.
    for key in ("baseline_total", "gain_total", "projected_total", "remaining_total", "target_total"):
        assert key in progress
    assert "reduce(" not in block and ".reduce" not in block


def test_dashboard_reads_the_busy_schedule_without_writing_it() -> None:
    block = HTML.split("function cpdBusyBlocks", 1)[1].split("function cpdRenderMonth", 1)[0]
    assert "busy_intervals" in block and "Lịch bận của bạn" in block
    assert "canonical_availability =" not in HTML.split("var cpdView", 1)[1].split("</script>", 1)[0]


def test_legacy_overview_numbers_are_hidden_by_the_dashboard() -> None:
    body = HTML.split("function cpdRender()", 1)[1]
    assert "overviewDrlScore" in body and "overviewSemesterBar" in body and "classList.add('hidden')" in body


def _review_script() -> str:
    return HTML.split("function openPlanReview(", 1)[1].split("function openPlanReviewFromUi", 1)[0]


def test_review_screen_entry_and_layout() -> None:
    assert "function openPlanReview(result, optionLabel)" in HTML
    assert 'id="planReviewScreen"' in HTML and 'id="prvList"' in HTML and 'id="prvPanel"' in HTML
    assert "Review kế hoạch" in HTML and 'onclick="openPlanReviewFromUi()"' in HTML
    # Side panel: stacks under the list below the lg breakpoint, two columns above it.
    assert "lg:grid-cols-[minmax(0,1fr)_380px]" in HTML
    body = _review_script()
    for text in ("Đổi", "Nếu bỏ", "Bỏ", "Nhiệm vụ hoàn thành", "Hạn đăng ký", "Đã đổi", "Hoàn tác",
                 "Khôi phục phương án gốc", "Xác nhận kế hoạch", "Đạt mục tiêu", "Chưa đạt mục tiêu",
                 "Xem thêm", "Không có hoạt động thay thế giữ được mục tiêu", "Đang thay", "Thử lại"):
        assert text in body, text


def test_review_calls_use_the_student_availability_and_the_review_endpoints() -> None:
    body = _review_script()
    assert "availability: plannerAvailabilityPayload()" in body
    for path in ("/api/sp3/personalized/alternatives", "/api/sp3/personalized/what-if-skip",
                 "/api/sp3/personalized/swap-preview"):
        assert path in body
    assert "add_activity_id: null" in body  # remove-only


def test_review_confirm_is_blocked_only_by_checker_violations() -> None:
    body = _review_script()
    assert "summary.violations > 0 || prvDraft.busy" in body
    # Below target only changes the wording; it never disables the button.
    assert "!summary.met" in body and "disabled' : ''} onclick=\"prvConfirm()\"" in body
    assert "cpdRequestConfirm(prvDraft.result" in body  # goes through the diff when a plan is confirmed


def test_review_screen_computes_no_scores() -> None:
    body = _review_script()
    assert ".reduce(" not in body and "Math.round" not in body
    # Bar widths scale engine values by the criterion cap; totals are never added up in the UI.
    assert "projected - base" in body and "summary.byProjected" in body


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to drive a real browser")
def test_browser_end_to_end() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_review_dashboard_e2e.py")],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
