r"""Verify a 65 -> 100 projected-point case, optionally serve it on an isolated demo port.

    .venv\Scripts\python.exe scripts\demo_100_points.py
    .venv\Scripts\python.exe scripts\demo_100_points.py --serve

The opening 65 points are an explicit synthetic test fixture, not earned or verified
university credit. Activity data, rules, category caps and planner code are unchanged.
The account and all API writes use a temporary session file, separate from the usual app.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STUDENT_ID = "DEMO100"
TERM_ID = "HK1_2026_2027"  # the term is explicit; its clock and window come from data/config/semesters.json
BASELINE = {"C1": 15, "C2": 20, "C3": 10, "C4": 10, "C5": 10}
EXPECTED = {"C1": 30, "C2": 20, "C3": 15, "C4": 25, "C5": 10}


def request_body() -> dict:
    from datetime import date, timedelta

    from api.term_clock import get_term

    clock = get_term(TERM_ID)
    first = date.fromisoformat(clock.window_start[:10])
    monday = first + timedelta(days=(7 - first.weekday()) % 7)  # the availability contract needs a Monday in range
    return {
        "scenario": "first_plan", "confirmed": True, "total_target": 100,
        "busy_intervals": [],
        "preference": {
            "topic_preferences": [], "category_priorities": [], "campus_preferences": [],
            "mode_preferences": [], "time_preferences": [],
            "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
            "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None},
            "strategy": "BALANCED",
        },
        "availability": {
            "availability_version": "sp3-availability/0.2", "timezone": "Asia/Ho_Chi_Minh",
            "week_start": monday.isoformat(), "apply_scope": "SEMESTER_WEEKLY",
            "effective_from": first.isoformat(), "effective_until": clock.term_end,
            "weekly_blocks": [
                {"day_of_week": day, "start_time": "07:00", "end_time": "21:00"}
                for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
            ],
            "exceptions": [], "busy_intervals": [],
        },
    }


def seed_account(server) -> None:
    server.session_scores[STUDENT_ID] = {TERM_ID: {
        "current": deepcopy(BASELINE), "projected": {category: 0 for category in BASELINE},
    }}


def verify_case(server) -> dict:
    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        seed_account(server)
        response = client.post(
            "/api/sp3/personalized/options", params={"source": "real", "student_id": STUDENT_ID, "term_id": TERM_ID},
            json=request_body(),
        )
        assert response.status_code == 200, response.text
        options = response.json()["options"]
        assert {option["strategy"] for option in options} == {"MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"}
        for option in options:
            assert option["status"] == "READY", option
            result = option["result"]
            assert result["data_source"] == "OPERATIONAL-DATASET"
            assert result["official_award_verified"] is False
            assert result["plan"]["status"] == "TARGET_MET"
            summary = result["plan"]["score_summary"]
            assert summary["baseline_by_category"] == BASELINE
            assert summary["projected_by_category"] == EXPECTED
            assert (summary["baseline_total"], summary["gain_total"], summary["projected_total"], summary["remaining_total"]) == (65, 35, 100, 0)
        result = next(option["result"] for option in options if option["strategy"] == "BALANCED")
        confirmed = client.post("/api/sp3/confirmed-plan", json={
            "student_id": STUDENT_ID, "term_id": TERM_ID, "offer": result["completion_offer"],
        })
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["score_summary"]["projected_total"] == 100
        # Saving the plan does not award points for future attendance.
        scores = client.get("/api/scores", params={"student_id": STUDENT_ID, "term_id": TERM_ID}).json()
        assert scores["total_confirmed"] == 65
        summary = result["plan"]["score_summary"]
        print("PASS: all three strategies reach 100 projected points; confirmation preserves the 65-point opening balance.")
        print(json.dumps({"student_id": STUDENT_ID, "fixture": "SYNTHETIC_OPENING_BALANCE", "summary": summary,
                          "activities": len(result["plan"]["selected_activities"])}, ensure_ascii=True), flush=True)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="serve a fresh test account after verification")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="unilife-demo100-") as directory:
        os.environ["UNILIFE_SESSION_FILE"] = str(Path(directory) / "session.json")
        os.environ["UNILIFE_PERSIST_SESSION"] = "1"
        from api import server

        verify_case(server)
        if args.serve:
            import uvicorn

            server._clear_session_state()
            seed_account(server)
            server._save_session_to_disk(strict=True)
            print(f"Isolated demo: http://localhost:{args.port}/", flush=True)
            print(f"Register student ID {STUDENT_ID}; choose target 100, no busy times and no budget/activity limits.", flush=True)
            print("Opening balance: SYNTHETIC 65 points. Real activity catalog; 100 is projected, not awarded.", flush=True)
            uvicorn.run(server.app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
