"""Compare the SP2 engine with the shared DRL test cases."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sp2 import evaluate_rule_conditions  # noqa: E402


def load_json(path: str, git_ref: str | None) -> Any:
    file_path = ROOT / path
    if file_path.exists():
        return json.loads(file_path.read_text(encoding="utf-8"))
    if git_ref:
        content = subprocess.check_output(
            ["git", "show", f"{git_ref}:{path}"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
        return json.loads(content)
    raise FileNotFoundError(file_path)


def matched_rules(result: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("rule_id", "criterion_id", "points")
    return [{key: item.get(key) for key in keys} for item in result["matched_rules"]]


def compare_case(config: dict[str, Any], case: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    expected = case["expected_output"]
    required = case["input"].get("required_fields", expected.get("missing_fields", []))
    actual = evaluate_rule_conditions(
        config,
        case["input"]["student_record"],
        required_fields=required,
    )
    differences: list[str] = []

    expected_rules = expected.get("matched_rules")
    if expected_rules is not None and matched_rules(actual) != expected_rules:
        differences.append(
            f"matched_rules: expected {expected_rules!r}, got {matched_rules(actual)!r}"
        )

    for key in (
        "rule_points_total",
        "raw_total_before_cap",
        "final_score",
        "needs_review",
        "missing_fields",
    ):
        if key in expected and actual.get(key) != expected[key]:
            differences.append(f"{key}: expected {expected[key]!r}, got {actual.get(key)!r}")
    return actual, differences


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", default="data/drl_rules.json")
    parser.add_argument("--cases", default="data/drl_test_cases.json")
    parser.add_argument("--git-ref")
    parser.add_argument("--show-output", action="store_true")
    args = parser.parse_args()

    config = load_json(args.rules, args.git_ref)
    cases = load_json(args.cases, args.git_ref)
    passed = 0

    for case in cases:
        actual, differences = compare_case(config, case)
        status = "PASS" if not differences else "FAIL"
        print(f"{case['test_id']}: {status}")
        for difference in differences:
            print(f"  - {difference}")
        if args.show_output:
            print(json.dumps(actual, ensure_ascii=False, indent=2))
        if not differences:
            passed += 1

    print(f"Result: {passed}/{len(cases)} cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
