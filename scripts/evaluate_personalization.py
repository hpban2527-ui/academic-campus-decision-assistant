"""Run the reviewed Vietnamese preference benchmark against configured Ollama."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personalization.evaluation import aggregate_evaluations, evaluate_prediction
from personalization.providers import PreferenceProviderError, preference_provider_from_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "data" / "personalization_eval_cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "personalization_ai_eval.json")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only this case ID; repeatable")
    parser.add_argument("--fail-below", type=float, default=None, help="Exit 1 if overall score is below this value")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != "personalization-eval/0.1":
        raise ValueError("unsupported personalization evaluation schema")
    cases = fixture.get("cases")
    if not isinstance(cases, list):
        raise ValueError("evaluation cases must be an array")
    if args.case_ids:
        wanted = set(args.case_ids)
        cases = [case for case in cases if case.get("case_id") in wanted]
        missing = wanted - {case.get("case_id") for case in cases}
        if missing:
            raise ValueError("unknown case IDs: " + ", ".join(sorted(missing)))

    provider = preference_provider_from_env()
    health = provider.health()
    if not health.available:
        raise RuntimeError(health.message or "preference provider is unavailable")
    results = []
    for index, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        print(f"[{index}/{len(cases)}] {case_id}", flush=True)
        try:
            prediction = provider.interpret(case["text"])
            results.append({
                "case_id": case_id,
                "text": case["text"],
                "status": "OK",
                "prediction": prediction.model_dump(mode="json"),
                "metrics": evaluate_prediction(case["expected"], prediction),
            })
        except PreferenceProviderError as exc:
            results.append({
                "case_id": case_id,
                "text": case["text"],
                "status": "ERROR",
                "error": {"code": exc.code, "message": exc.public_message},
            })

    report = {
        "schema_version": "personalization-eval-report/0.1",
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "provider": provider.provider_name,
        "model": provider.model,
        "source_fixture": str(args.cases),
        "summary": aggregate_evaluations(results),
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {args.output}")
    if args.fail_below is not None and report["summary"]["overall_score"] < args.fail_below:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
