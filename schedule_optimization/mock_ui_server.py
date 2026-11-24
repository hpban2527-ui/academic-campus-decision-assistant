"""Lightweight standalone HTTP server for the SP3 Schedule Optimization Mock UI.

Zero external dependencies (Python stdlib only). Does NOT touch src/api/ or web/.

Run:
    python schedule_optimization/mock_ui_server.py --port 8765
Then open:
    http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from schedule_optimization.benchmark import (
    _pref_matches_count,
    _set_changes,
    _total_duration,
    run_planner_benchmarks,
    run_scheduler_benchmarks,
)
from schedule_optimization.scenarios import get_all_planner_scenarios
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip

HERE = Path(__file__).resolve().parent
HTML_PATH = HERE / "mock_ui.html"
SCENARIOS = {sc.id: sc for sc in get_all_planner_scenarios()}


def _scenario_metadata() -> list[dict[str, Any]]:
    items = []
    for sc in SCENARIOS.values():
        p = sc.planner_input
        items.append({
            "id": sc.id,
            "name": sc.name,
            "description": sc.description,
            "catalog_size": len(p["candidates"]),
            "default_strategy": sc.personalization_strategy,
            "default_total_target": p["goals"]["total_target"],
            "category_targets": p["goals"]["category_targets"],
            "baseline_scores": p["baseline"]["category_scores"],
            "baseline_total": p["baseline"]["total_score"],
            "exact_feasible": sc.exact_feasible,
            "has_previous_plan": p["previous_plan"] is not None,
            "candidates": [
                {
                    "activity_id": c["activity"]["activity_id"],
                    "title": c["activity"]["title"],
                    "domain": c["activity"]["domain"],
                    "mode": c["activity"]["mode"],
                    "schedule_type": c["schedule"]["type"],
                }
                for c in p["candidates"]
            ],
        })
    return items


def _compare_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    sc_id = payload.get("scenario_id", "small_exact")
    if sc_id not in SCENARIOS:
        raise ValueError(f"Unknown scenario_id: {sc_id}")
    sc = SCENARIOS[sc_id]
    p_input = deepcopy(sc.planner_input)

    if payload.get("total_target") is not None:
        p_input["goals"]["total_target"] = float(payload["total_target"])
    strategy = payload.get("strategy") or sc.personalization_strategy
    max_evals = int(payload.get("max_evaluations") or 400)
    skip_id = payload.get("skip_activity_id") or None

    methods = (["exact"] if sc.exact_feasible else []) + ["greedy", "beam_v1", "guided_v2"]
    results = []
    for method in methods:
        scorer = sc.scorer_factory()
        t0 = time.perf_counter()
        opts = {
            "max_evaluations": max_evals,
            "personalization_strategy": strategy,
            "preference_utility": sc.preference_utility,
            "search_method": method,
        }
        if skip_id:
            out = what_if_skip(p_input, skip_id, scorer, **opts)
        else:
            out = build_plan(p_input, scorer, **opts)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        checker_input = deepcopy(p_input)
        if skip_id:
            for c in checker_input["candidates"]:
                if c["activity"]["activity_id"] == skip_id:
                    c["participation"]["progress"] = "CANCELLED"
            checker_input["keep_requests"] = [
                kr for kr in checker_input["keep_requests"] if kr.get("activity_id") != skip_id
            ]
        violations = check_plan(checker_input, out, sc.scorer_factory())

        sel_ids = sorted(a["activity_id"] for a in out["selected_activities"])
        summary = out["score_summary"] or {}
        rem_cats = summary.get("remaining_by_category") or {}
        cat_gap = round(sum(float(v) for v in rem_cats.values()), 4)
        dur = _total_duration(p_input, sel_ids)
        pref_cnt = _pref_matches_count(p_input, sel_ids)
        util = round(float(sc.preference_utility(tuple(sel_ids), {})), 2) if sc.preference_utility else None
        changes = _set_changes(p_input, sel_ids)

        results.append({
            "method": method,
            "status": out["status"],
            "projected_total": summary.get("projected_total", 0.0),
            "baseline_total": summary.get("baseline_total", p_input["baseline"]["total_score"]),
            "projected_by_category": summary.get("projected_by_category", {}),
            "baseline_by_category": summary.get("baseline_by_category", p_input["baseline"]["category_scores"]),
            "category_gap": cat_gap,
            "total_gap": float(summary.get("remaining_total") or 0.0),
            "selected_count": len(sel_ids),
            "pref_matches": pref_cnt,
            "duration_min": dur,
            "utility": util,
            "set_changes": changes,
            "evaluated_subsets": out["search"]["evaluated_subsets"],
            "optimality_proven": out["search"]["optimality_proven"],
            "latency_ms": round(elapsed_ms, 2),
            "contract_valid": len(violations) == 0,
            "contract_violations": violations,
            "selected_activities": out["selected_activities"],
            "dropped_activities": out["dropped_activities"],
            "warnings": out["warnings"],
        })
    return {
        "scenario_id": sc_id,
        "scenario_name": sc.name,
        "strategy": strategy,
        "total_target": p_input["goals"]["total_target"],
        "category_targets": p_input["goals"]["category_targets"],
        "skip_activity_id": skip_id,
        "results": results,
    }


class MockUIHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_html(HTML_PATH.read_text(encoding="utf-8"))
        elif path == "/api/scenarios":
            self._send_json(200, {"scenarios": _scenario_metadata()})
        elif path == "/api/benchmark":
            self._send_json(200, {
                "planner": run_planner_benchmarks(),
                "scheduler": run_scheduler_benchmarks(),
            })
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/compare":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(raw)
                self._send_json(200, _compare_scenario(payload))
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
        else:
            self._send_json(404, {"error": "Not found"})

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="SP3 Schedule Optimization Mock UI Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), MockUIHandler)
    print(f"SP3 Optimization Mock UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
