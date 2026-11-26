"""Static checks of screen 05 "Plan options" in web/index.html (REVIEW-DASH blocks).

Behaviour in a real browser (cards, Esc, choose -> review -> swap -> confirm, "Xac nhan luon", mobile) is
covered by scripts/verify_review_dashboard_e2e.py; run it from pytest with RUN_BROWSER_E2E=1
(tests/test_review_dashboard_ui.py). These checks keep the shared-file edits inside the markers and the
engine-only-numbers rule visible.
"""
from __future__ import annotations

from pathlib import Path
import re

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
MARK = re.compile(r"(?:<!--|//)\s*REVIEW-DASH (START|END)")


def _inside_marker(position: int) -> bool:
    """True when the nearest REVIEW-DASH marker before `position` is a START."""
    before = [match.group(1) for match in MARK.finditer(HTML, 0, position)]
    return bool(before) and before[-1] == "START"


def _function(name: str) -> str:
    start = HTML.index(f"function {name}(")
    return HTML[start:HTML.index("\n    }\n", start) + 7]


def _screen_script() -> str:
    return HTML.split("var rdPosSuggested", 1)[1].split("// REVIEW-DASH END", 1)[0]


def test_screen_markup_is_an_accessible_dialog_inside_markers() -> None:
    position = HTML.index('id="planOptionsScreen"')
    assert _inside_marker(position)
    tag = HTML[HTML.rindex("<div", 0, position):HTML.index(">", position)]
    assert 'role="dialog"' in tag and 'aria-modal="true"' in tag and 'aria-labelledby="posTitle"' in tag
    assert 'id="posTitle"' in HTML and "Chọn phương án" in HTML
    review_tag = HTML[HTML.rindex("<div", 0, HTML.index('id="planReviewScreen"')):HTML.index('id="planReviewScreen"')]
    assert "z-[105]" in tag and "z-[105]" in HTML[HTML.index('id="planReviewScreen"'):HTML.index('id="planReviewScreen"') + 200]
    assert review_tag is not None
    for text in ("✕ Đóng", "Điểm là ước tính để lập kế hoạch; điểm rèn luyện chính thức do trường công nhận."):
        assert text in HTML[position:position + 2500], text


def test_card_texts_and_states() -> None:
    body = _screen_script()
    for text in ("Ít thời gian", "Cân bằng", "Theo sở thích",
                 "Ít giờ tham gia nhất mà vẫn hướng tới mục tiêu",
                 "Cân bằng giữa số giờ và mức hợp sở thích",
                 "Ưu tiên hoạt động hợp sở thích của bạn",
                 "Gợi ý", "Đạt mục tiêu", "Chưa đạt mục tiêu", "Chọn &amp; review", "Xác nhận luôn",
                 "Độ hợp sở thích", "hoạt động khác", "Kế hoạch đề xuất",
                 "Xác nhận nguyện vọng để so sánh 3 phương án.",
                 "Một số chiến lược cho ra cùng một lịch nên đã được gộp.",
                 "Không phương án nào đạt mục tiêu", "với lịch và ràng buộc hiện tại.",
                 "/ mục tiêu ${", "Dữ liệu giả lập", "Kho bài thật"):
        assert text in body, text
    # The preference utility is shown only when a preference was stated.
    assert "hasPreference && model.utility !== null" in body
    # No invented maximum: the engine payload has no such field, so none is shown.
    assert "max_achievable" not in body and "tối đa" not in body


def test_screen_computes_no_scores_and_escapes_dynamic_text() -> None:
    body = _screen_script()
    assert ".reduce(" not in body and "remaining_total -" not in body and "projected_total -" not in body
    # The only arithmetic is a display conversion: minutes -> hours and the utility rounded to 2 decimals.
    assert "model.minutes / 60 * 10" in body and "model.utility * 100" in body
    for field in ("projected_total", "target_met", "activity_count", "duration_minutes", "utility"):
        assert f"option.{field}" in body, field
    assert "escapeHTML(activity.title)" in body and "escapeHTML(name)" in body
    # Switching cards never calls the API.
    assert "fetch(" not in body


def test_planner_result_opens_screen_05_only_for_the_first_stage() -> None:
    hook = HTML.split("function reviewDashNotePlannerResult", 1)[1].split("// True for the object", 1)[0]
    assert "currentPlanStage === 'first' && planStages.first" in hook
    assert "reviewDashOpenPlanOptions(true)" in hook
    assert "confirmed_plan =" not in hook  # the hook still never writes the confirmed plan
    run = HTML.split("async function runSp3Planner", 1)[1].split("// Steps 2 & 3", 1)[0]
    assert run.count("reviewDashNotePlannerResult();") == 1
    # Replan / what-if stages go through gotoPlanStage, which never calls the hook.
    stage = HTML.split("async function gotoPlanStage", 1)[1].split("\n    }\n", 1)[0]
    assert "reviewDashNotePlannerResult" not in stage and "reviewDashOpenPlanOptions" not in stage


def test_choose_and_review_selects_then_opens_the_review() -> None:
    body = _function("reviewDashChoosePlanOption")
    assert body.index("selectCachedPlanOption(idx)") < body.index("openPlanReview(data, label)")
    assert "cpdOptionLabel(data)" in body and "reviewDashClosePlanOptions();" in body
    assert "fetch(" not in body  # cached options: no recomputation


def test_confirm_now_goes_through_cpd_request_confirm() -> None:
    body = _function("reviewDashChoosePlanOption")
    assert "mode === 'confirm' && !rdOnboardingActive()" in body
    assert "cpdRequestConfirm(data, label, () => {" in body
    assert "reviewDashClosePlanOptions();" in body and "switchTab('dashboard')" in body
    assert "confirmConfirmedPlan(" not in body  # never bypasses the diff modal


def test_review_header_can_return_to_the_options_without_recomputing() -> None:
    assert 'id="prvBackToOptions"' in HTML and "Quay lại phương án" in HTML
    assert _inside_marker(HTML.index('id="prvBackToOptions"'))
    body = _function("reviewDashBackToPlanOptions")
    assert "closePlanReview(true);" in body and "reviewDashOpenPlanOptions();" in body and "fetch(" not in body


def test_reopen_entry_in_the_confirm_bar() -> None:
    bar = HTML[HTML.index('id="confirmPlanBar"'):HTML.index('id="btnConfirmPlan"')]
    assert 'id="btnReviewPlanOptions"' in bar and "reviewDashOpenPlanOptions()" in bar and "Xem các phương án" in bar
    assert _inside_marker(HTML.index('id="btnReviewPlanOptions"'))


def test_esc_and_focus_handling() -> None:
    body = _screen_script()
    assert "event.key === 'Escape'" in body and "reviewDashClosePlanOptions();" in body
    assert "rdPosReturnFocus" in body and ".focus()" in body
    assert "event.key !== 'Tab'" in body  # focus stays inside the dialog


def test_onboarding_options_and_review_are_steps_in_the_same_dialog() -> None:
    assert "function reviewDashAfterOnboarding()" in HTML
    assert "drl_target" in _function("rdOnboardingBuildPlan")
    assert "Bạn muốn đạt bao nhiêu điểm rèn luyện học kỳ này?" in HTML
    onboarding = _function("completeOnboarding")
    call = "return reviewDashAfterOnboarding();"
    assert call in onboarding and _inside_marker(HTML.index(call))
    assert onboarding.index("syncConfirmedPreferenceFromProfile") < onboarding.index(call)
    assert onboarding.index(call) < onboarding.index('showWorkspace("dashboard")')
    assert "window.clearTimeout(welcomeTimeout)" in onboarding
    assert "Lập lịch & review" in _function("renderOnboardingStep")
    assert 'id="onboardingOptionsHost"' in HTML and 'id="onboardingReviewHost"' in HTML
    for step in range(1, 6):
        assert f'id="onboardingStepMarker{step}"' in HTML
    assert "host.appendChild(screen)" in _function("rdOnboardingBegin")
    assert "screen.removeAttribute('aria-modal')" in _function("rdOnboardingBegin")
    assert "onboardingStep !== 5" in _function("cpdStoreConfirmedPlan")
    assert "data.onboarding_status = 'COMPLETED'" in _function("cpdStoreConfirmedPlan")
    assert "'IN_PROGRESS'" in onboarding and "!withPlanReview" in onboarding
    assert "rdOnboardingReset()" in _function("rdOnboardingFinish")


def test_friendly_error_mapping_covers_the_source_real_422() -> None:
    body = _function("reviewDashFriendlyError")
    assert "source=real" in body and "not yet (available|supported)" in body
    # The page has no data-source selector any more, so the message must not send the student to one.
    assert "Máy chủ đang chạy chưa hỗ trợ chức năng này với kho bài thật. Hãy khởi động lại server bằng phiên bản mới rồi thử lại." in body
    assert "Dữ liệu giả lập (MVP)" not in body
    assert "Không kết nối được máy chủ. Hãy kiểm tra server rồi thử lại." in body
    assert "failed to fetch" in body
    assert "Không thể lập kế hoạch: ${text}" in body
    # Keep the legacy error mapping for older servers; integrated routes now accept the real source.
    server = (Path(__file__).resolve().parents[1] / "src" / "api" / "server.py").read_text(encoding="utf-8")
    for detail in ("multi-strategy options are not yet available for source=real",
                   "smart swap is not yet available for source=real",
                   "plan review is not yet available for source=real"):
        assert detail not in server
        assert re.search(r"source=real", detail)


def test_review_and_planner_errors_go_through_the_friendly_helper() -> None:
    post = _function("prvPost")
    assert "reviewDashFriendlyError(error && error.message, prvDraft?.source || SP3_SOURCE, false)" in post
    run = HTML.split("async function runSp3Planner", 1)[1].split("// Steps 2 & 3", 1)[0]
    line = "err.message = reviewDashFriendlyError(err.message, SP3_SOURCE, false);"
    assert run.count(line) == 1
    assert _inside_marker(HTML.index(line))
    assert run.index(line) < run.index("showPlanError(err.message)")


def test_no_new_text_mentions_an_hour_limit() -> None:
    body = _screen_script() + HTML[HTML.index('id="planOptionsScreen"'):HTML.index('id="planDiffModal"')]
    lowered = body.lower()
    for phrase in ("tối đa", "giới hạn giờ", "quá nhiều giờ", "vượt quá", "hour limit", "max_hours", "weekly_participation_hours"):
        assert phrase not in lowered, phrase
    # Hours appear only as a display of the engine's duration.
    assert len(re.findall(r"giờ", body)) <= 3
