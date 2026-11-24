"""Real-source snapshots must survive the browser quota and reload without losing data."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from api.sp3_real import real_plan_options
from api.term_clock import list_terms
from personalization.models import StudentPreference

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_options():
    preference = {
        "topic_preferences": [], "category_priorities": [], "campus_preferences": [],
        "mode_preferences": [], "time_preferences": [],
        "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
        "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None},
        "strategy": "BALANCED",
    }
    options = real_plan_options(StudentPreference.model_validate(preference), term_id="HK1_2026_2027", target_total=85)["options"]
    assert all(option.get("result") for option in options)
    return preference, options


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for page controllers")
@pytest.mark.parametrize("scenario,mobile", [
    ("storage", False), ("onboarding_quota", False), ("onboarding_quota", True),
    ("onboarding_quota_blocked", False),
])
def test_quota_recovery_preserves_accounts_and_planner_snapshots(real_options, scenario, mobile):
    preference, options = real_options
    result = subprocess.run(
        ["node", "tests/review_dashboard_runtime.cjs"], cwd=ROOT,
        input=json.dumps({"scenario": scenario, "mobile": mobile, "preference": preference, "options": options,
                          "clocks": [clock.as_dict() for clock in list_terms()]}),
        text=True, encoding="utf-8", capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["passed"] is True
