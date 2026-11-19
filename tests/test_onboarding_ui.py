from __future__ import annotations

from pathlib import Path


HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def test_dashboard_assistant_is_replaced_by_one_time_onboarding_and_profile_editor() -> None:
    assert 'id="unilifeAssistant"' not in HTML
    assert 'id="onboardingWizard"' in HTML
    assert "NOT_STARTED" in HTML and "IN_PROGRESS" in HTML and "COMPLETED" in HTML
    assert "AI chỉnh sửa hồ sơ" in HTML
    assert "/api/profile-assistant/interpret" in HTML
    assert 'id="onboardingScores"' not in HTML
    assert "Bước 1 / 3" in HTML
    assert "hydrateOnboardingFormFromDraft" in HTML
    assert "editProfileProposalInterval" in HTML
    assert 'id="onboardingAiChips"' in HTML
    assert "resetOnboardingAssistantState" in HTML
    assert "requestBody.onboarding_step = onboardingStep" in HTML
    assert "JSON.stringify(change.new)" not in HTML
    assert "renderProfileProposalChanges" in HTML


def test_profile_schedule_workspace_and_local_migration_are_present() -> None:
    assert "Hồ sơ & Lịch" in HTML
    for label in ("Hồ sơ sinh viên", "Lịch cá nhân", "Kế hoạch thông minh"):
        assert label in HTML
    assert "migrateLocalUserData" in HTML
    assert "onboarding_status" in HTML
    assert "canonical_availability" in HTML
    assert "customBusyIntervals.push(...expanded)" in HTML
    assert "assistantAvailableIntervals.push(...expanded)" in HTML
    assert "availableExceptionDays" in HTML
    assert "function logoutLocalAccount()" in HTML
    assert "manual_busy_intervals" in HTML and "unavailable_slots" in HTML
    assert "plannerRequestGeneration" in HTML


def test_plan_option_cache_and_swap_controls_are_real_handlers() -> None:
    assert "/api/sp3/personalized/options" in HTML
    assert "function plannerPreferencePayload(preference)" in HTML
    assert "weeklyHours * 60" in HTML
    assert "cachedPlanOptions" in HTML
    assert "selectCachedPlanOption" in HTML
    assert "Chi tiết và tùy chỉnh" in HTML
    assert "previewSmartSwap" in HTML
    assert "undoCustomPlan" in HTML
    assert "Smart Swap chưa được hỗ trợ an toàn cho nguồn hoạt động thật" in HTML
    for marker in ("PLANNED · đã xếp", "OPEN · rảnh đã xác nhận", "BUSY · bận", "UNKNOWN/OUTSIDE"):
        assert marker in HTML
    for handler in ("openPlannedActivityDetails", "openAvailableCalendarSlot", "openBusyCalendarSlot", "previewCalendarActivityChange"):
        assert f"function {handler}" in HTML
    assert "/api/sp3/personalized/${kind}-preview" in HTML
    assert "calendarPreviewChange" in HTML

