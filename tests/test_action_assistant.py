from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api.server import app
from personalization.action_assistant import interpret_message


def test_parses_drl_target_and_recurring_monday_busy_time() -> None:
    result = interpret_message(
        "Mình muốn đạt 95 điểm rèn luyện. Thứ 2 hàng tuần mình học từ 7h30 đến 17h30."
    )

    assert result.status == "preview"
    assert result.draft.drl_target == 95
    interval = result.draft.intervals[0]
    assert (interval.kind, interval.weekday, interval.start, interval.end) == (
        "busy", 0, "07:30", "17:30"
    )
    assert interval.recurrence == "weekly"


def test_clarifies_incomplete_availability_and_preserves_prior_turn() -> None:
    first = interpret_message(
        "Mục tiêu 90 điểm. Thứ 3 hàng tuần mình rảnh từ 4h30 chiều."
    )
    assert first.status == "clarification"
    assert "kết thúc" in first.questions[0].lower()

    second = interpret_message("Đến 18h.", first.draft.model_dump())
    assert second.status == "preview"
    assert second.draft.drl_target == 90
    assert second.draft.intervals[0].kind == "available"
    assert second.draft.intervals[0].start == "16:30"
    assert second.draft.intervals[0].end == "18:00"


def test_does_not_invent_recurrence_and_rejects_conflicts() -> None:
    missing = interpret_message("Thứ 5 mình bận từ 8h đến 10h.")
    assert missing.status == "clarification"
    assert missing.draft.pending_interval.missing == "recurrence"

    conflict = interpret_message(
        "Thứ 2 hàng tuần mình học từ 8h đến 12h. "
        "Thứ 2 hàng tuần mình rảnh từ 10h đến 11h."
    )
    assert conflict.status == "error"
    assert conflict.errors


def test_khong_ranh_is_busy_not_available() -> None:
    result = interpret_message("Thu 2 hang tuan minh khong ranh tu 8h den 11h")

    assert result.status == "preview"
    assert result.draft.intervals[0].kind == "busy"


def test_rejects_invalid_values_and_keeps_preferences_unconfirmed() -> None:
    invalid = interpret_message("Mục tiêu 105 điểm rèn luyện.")
    assert invalid.status == "error"

    preference = interpret_message("Mình thích hoạt động online và ưu tiên buổi tối.")
    assert preference.status == "preview"
    assert preference.draft.preferred_modes == ["online"]
    assert preference.draft.soft_time_preferences == ["evening"]
    assert preference.draft.preferences_confirmed is False


def test_interpret_api_is_preview_only() -> None:
    response = TestClient(app).post(
        "/api/assistant/interpret",
        json={"message": "Mục tiêu 95 điểm. Mình thích hoạt động online."},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "preview"
    assert payload["requires_confirmation"] is True
    assert payload["draft"]["preferences_confirmed"] is False


def test_profile_editor_confirms_before_applying_existing_planner_state() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="unilifeAssistant"' not in html
    assert 'id="onboardingModal"' in html
    assert 'id="onboardingWizard"' not in html
    assert "function confirmProfileProposal" in html
    assert "/api/profile-assistant/interpret" in html
    assert "customBusyIntervals" in html
    assert "unavailableAvailabilitySlots" in html
    assert "collectBusyIntervals" in html
    assert "switchTab('plan')" in html

