from __future__ import annotations

import json
from pathlib import Path

from personalization.evaluation import evaluate_prediction
from personalization.fast_interpreter import interpret_explicit_preference


ROOT = Path(__file__).resolve().parents[2]


def test_reviewed_explicit_cases_are_exact_without_ai():
    dataset = json.loads((ROOT / "data" / "personalization_eval_cases.json").read_text(encoding="utf-8"))

    for case in dataset["cases"]:
        preference = interpret_explicit_preference(case["text"])
        assert preference is not None, case["case_id"]
        metrics = evaluate_prediction(case["expected"], preference)
        assert metrics["precision"] == 1.0, (case["case_id"], metrics)
        assert metrics["recall"] == 1.0, (case["case_id"], metrics)
        assert metrics["weight_accuracy"] == 1.0, (case["case_id"], metrics)
        assert metrics["hard_exclusions"]["correct"] is True, (case["case_id"], metrics)
        assert all(item["correct"] for item in metrics["limit_checks"]), (case["case_id"], metrics)
        assert metrics["strategy"]["correct"] is True, (case["case_id"], metrics)


def test_comparative_wording_uses_ai_fallback():
    assert interpret_explicit_preference("Em thích online hơn offline") is None


def test_unknown_number_uses_ai_fallback():
    assert interpret_explicit_preference("Em thích Toán và cần đạt 80 điểm") is None
