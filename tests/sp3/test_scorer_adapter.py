"""Adapter contract tests with static doubles, NOT real SP2 scoring tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sp3.scorer_adapter import ScorerAdapter, ScorerContractError


@pytest.fixture
def request_data():
    return {
        "contract_version": "sp3-planner/0.1",
        "request_id": "synthetic-request",
        "context": {
            "student_id": "synthetic-student",
            "term_id": "SYNTHETIC-DEMO",
            "window_start": "2026-11-01T00:00:00+07:00",
            "window_end": "2026-11-04T00:00:00+07:00",
            "as_of": "2026-11-01T08:00:00+07:00",
            "timezone": "Asia/Ho_Chi_Minh",
            "baseline_ref": "baseline-v1",
            "dataset_version": "dataset-v1",
            "ruleset_version": "rules-v1",
            "calendar_version": "calendar-v1",
        },
        "baseline": {
            "category_scores": {"C1": 20, "C2": 10},
            "category_caps": {"C1": 30, "C2": 20},
            "total_score": 30,
            "max_total_score": 100,
            "included_activity_ids": ["OLD"],
        },
        "selected_activity_ids": ["A"],
    }


def contribution(activity_id, category, points):
    return {
        "activity_id": activity_id, "category_id": category,
        "rule_id": "MOCK_RULE", "projected_added": points,
    }


def response_for(request, *, result=None, status="OK", errors=None):
    if result is None and status == "OK":
        # Fixed single-A example. This helper does not compute arbitrary plans.
        result = {
            "category_after": {"C1": 25, "C2": 10},
            "category_gain": {"C1": 5, "C2": 0},
            "total_after": 35, "total_gain": 5,
            "contributions": [contribution("A", "C1", 5)],
        }
    return {
        **{key: deepcopy(request[key]) for key in ("contract_version", "request_id", "context", "selected_activity_ids")},
        "evaluation_status": status, "result": result,
        "errors": [] if errors is None else deepcopy(errors),
        "mode": "DEMO_ONLY", "official_award_verified": False,
    }


def assign(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


def assert_failure(response, code):
    assert response["evaluation_status"] == "ERROR"
    assert response["result"] is None
    assert response["errors"][0]["code"] == code
    assert response["mode"] == "DEMO_ONLY"
    assert response["official_award_verified"] is False


def test_single_activity_delegates_once_and_preserves_envelope(request_data):
    original = deepcopy(request_data)
    expected = response_for(request_data)
    backend = Mock(return_value=expected)
    result = ScorerAdapter(backend).score_plan(request_data)
    assert result == expected
    assert result is not expected
    assert request_data == original
    backend.assert_called_once_with(original)
    sent = backend.call_args.args[0]
    assert sent is not request_data
    assert sent["baseline"] is not request_data["baseline"]


def test_empty_set_is_still_validated_by_the_backend(request_data):
    request_data["selected_activity_ids"] = []
    expected = response_for(request_data, result={
        "category_after": {"C1": 20, "C2": 10},
        "category_gain": {"C1": 0, "C2": 0},
        "total_after": 30, "total_gain": 0, "contributions": [],
    })
    backend = Mock(return_value=expected)
    assert ScorerAdapter(backend).score_plan(request_data) == expected
    backend.assert_called_once_with(request_data)


def test_whole_set_capped_result_is_preserved_without_rescoring(request_data):
    request_data["selected_activity_ids"] = ["A", "B"]
    # Nominal +8 each; the backend allocates only +10 after the category cap.
    expected = response_for(request_data, result={
        "category_after": {"C1": 30, "C2": 10},
        "category_gain": {"C1": 10, "C2": 0},
        "total_after": 40, "total_gain": 10,
        "contributions": [contribution("A", "C1", 8), contribution("B", "C1", 2)],
    })
    backend = Mock(return_value=expected)
    result = ScorerAdapter(backend).score_plan(request_data)
    assert result == expected
    backend.assert_called_once_with(request_data)
    assert backend.call_args.args[0]["selected_activity_ids"] == ["A", "B"]


def test_overall_cap_can_make_total_gain_less_than_category_gains(request_data):
    request_data["selected_activity_ids"] = ["A", "B"]
    request_data["baseline"].update(
        category_scores={"C1": 28, "C2": 18}, total_score=46, max_total_score=47,
    )
    expected = response_for(request_data, result={
        "category_after": {"C1": 30, "C2": 20},
        "category_gain": {"C1": 2, "C2": 2},
        "total_after": 47, "total_gain": 1,
        "contributions": [contribution("A", "C1", 2), contribution("B", "C2", 2)],
    })
    result = ScorerAdapter(Mock(return_value=expected)).score_plan(request_data)
    assert result == expected
    assert sum(item["projected_added"] for item in result["result"]["contributions"]) == 4
    assert result["result"]["total_gain"] == 1


def test_zero_gain_activity_and_backend_attribution_order_are_retained(request_data):
    request_data["selected_activity_ids"] = ["A", "B"]
    # Backend may know B starts before A; IDs alone do not encode that order.
    expected = response_for(request_data)
    expected["result"]["contributions"] = [
        contribution("B", "C1", 5), contribution("A", "C1", 0),
    ]
    assert ScorerAdapter(Mock(return_value=expected)).score_plan(request_data) == expected


@pytest.mark.parametrize("path,value", [
    (("contract_version",), "sp3-planner/0.2"),
    (("request_id",), " "),
    (("context", "student_id"), None),
    (("context", "baseline_ref"), ""),
    (("context", "timezone"), "UTC"),
    (("context", "window_start"), "2026-11-04T00:00:00+07:00"),
    (("context", "window_end"), "2026-10-31T00:00:00+07:00"),
    (("context", "as_of"), "2026-11-05T00:00:00+07:00"),
    (("context", "as_of"), "2026-11-01T08:00:00"),
    (("context", "as_of"), "2026-02-30T08:00:00+07:00"),
    (("selected_activity_ids",), ["A", "A"]),
    (("selected_activity_ids",), ["B", "A"]),
    (("selected_activity_ids",), ["OLD"]),
    (("selected_activity_ids",), [""]),
    (("selected_activity_ids",), [1]),
    (("selected_activity_ids",), "A"),
    (("baseline", "included_activity_ids"), None),
    (("baseline", "included_activity_ids"), ["OLD", "OLD"]),
    (("baseline", "category_scores"), {}),
    (("baseline", "category_caps"), {"C1": 30}),
    (("baseline", "category_scores", "C1"), 31),
    (("baseline", "total_score"), 31),
    (("baseline", "max_total_score"), 25),
    (("baseline", "criterion_scores"), []),
    (("unexpected",), True),
])
def test_bad_requests_fail_before_backend_call(request_data, path, value):
    assign(request_data, path, value)
    backend = Mock()
    with pytest.raises(ScorerContractError):
        ScorerAdapter(backend).score_plan(request_data)
    backend.assert_not_called()


@pytest.mark.parametrize("field", ["context", "baseline", "selected_activity_ids"])
def test_missing_request_fields_are_not_invented(request_data, field):
    del request_data[field]
    backend = Mock()
    with pytest.raises(ScorerContractError, match="required"):
        ScorerAdapter(backend).score_plan(request_data)
    backend.assert_not_called()


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"), -1, "20", 10**400])
def test_non_numeric_or_non_finite_baseline_is_rejected(request_data, value):
    request_data["baseline"]["category_scores"]["C1"] = value
    backend = Mock()
    with pytest.raises(ScorerContractError):
        ScorerAdapter(backend).score_plan(request_data)
    backend.assert_not_called()


def test_aggregate_overflow_is_a_controlled_request_error(request_data):
    request_data["baseline"].update(
        category_scores={"C1": 1e308, "C2": 1e308},
        category_caps={"C1": 1e308, "C2": 1e308}, total_score=100,
    )
    backend = Mock()
    with pytest.raises(ScorerContractError, match="aggregate"):
        ScorerAdapter(backend).score_plan(request_data)
    backend.assert_not_called()


@pytest.mark.parametrize("status", ["NEEDS_REVIEW", "NEEDS_DATA", "ERROR"])
def test_structured_backend_failures_preserve_reasons_and_normalize_needs_data(request_data, status):
    issue = {"code": "MISSING_BASELINE_HISTORY", "message": "Criterion and rule history is required.", "activity_id": None}
    backend_response = response_for(request_data, status=status, errors=[issue])
    result = ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data)
    assert result["evaluation_status"] == ("NEEDS_REVIEW" if status == "NEEDS_DATA" else status)
    assert result["result"] is None
    assert issue in result["errors"]
    assert backend_response["evaluation_status"] == status
    assert backend_response["errors"] == [issue]
    if status == "NEEDS_DATA":
        assert result["errors"][0]["code"] == "SP2_NEEDS_DATA"


def test_unresolved_binding_is_not_converted_into_a_score(request_data):
    error = {"code": "MISSING_SCORE_BINDING", "message": "The selected binding cannot be resolved.", "activity_id": "A"}
    expected = response_for(request_data, status="NEEDS_REVIEW", errors=[error])
    assert ScorerAdapter(Mock(return_value=expected)).score_plan(request_data) == expected


@pytest.mark.parametrize("path,value", [
    (("contract_version",), "sp3-planner/0.2"),
    (("request_id",), "another-request"),
    (("context", "student_id"), "another-student"),
    (("context", "term_id"), "another-term"),
    (("context", "baseline_ref"), "another-baseline"),
    (("context", "dataset_version"), "another-dataset"),
    (("context", "ruleset_version"), "another-ruleset"),
    (("context", "calendar_version"), "another-calendar"),
    (("selected_activity_ids",), ["B"]),
    (("evaluation_status",), "CONFIRMED"),
    (("evaluation_status",), None),
    (("mode",), "OFFICIAL"),
    (("official_award_verified",), True),
    (("official_award_verified",), 0),
    (("result", "confirmed_added"), 5),
    (("result", "category_after"), {"C1": 25}),
    (("result", "category_gain"), {"C1": 5, "C2": 0, "C3": 0}),
    (("result", "category_after", "C1"), 31),
    (("result", "category_after", "C1"), 19),
    (("result", "category_gain", "C1"), 5.001),
    (("result", "total_after"), 101),
    (("result", "total_after"), 36),
    (("result", "total_gain"), 6),
    (("result", "contributions"), []),
    (("result", "contributions", 0, "activity_id"), "B"),
    (("result", "contributions", 0, "category_id"), "C9"),
    (("result", "contributions", 0, "rule_id"), ""),
    (("result", "contributions", 0, "projected_added"), 8),
    (("result", "contributions", 0, "status"), "VERIFIED"),
    (("errors",), [{"code": "REVIEW", "message": "Still needs review.", "activity_id": "A"}]),
])
def test_inconsistent_backend_responses_are_rejected(request_data, path, value):
    backend_response = response_for(request_data)
    assign(backend_response, path, value)
    result = ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data)
    assert_failure(result, "SP2_INVALID_RESPONSE")
    assert result["context"] == request_data["context"]
    assert result["selected_activity_ids"] == ["A"]


@pytest.mark.parametrize("path", [
    ("result", "category_after", "C1"),
    ("result", "category_gain", "C1"),
    ("result", "total_after"),
    ("result", "total_gain"),
    ("result", "contributions", 0, "projected_added"),
])
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1])
def test_response_numeric_fields_must_be_real_finite_nonnegative_scores(request_data, path, value):
    backend_response = response_for(request_data)
    assign(backend_response, path, value)
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


def test_duplicate_attribution_is_rejected_even_when_sum_is_correct(request_data):
    backend_response = response_for(request_data)
    backend_response["result"]["contributions"] = [
        contribution("A", "C1", 3), contribution("A", "C1", 2),
    ]
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


@pytest.mark.parametrize("field", ["mode", "official_award_verified", "errors"])
def test_missing_backend_envelope_fields_are_rejected(request_data, field):
    backend_response = response_for(request_data)
    del backend_response[field]
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


@pytest.mark.parametrize("backend_response", [None, [], 0, "not a response"])
def test_unstructured_backend_result_fails_closed(request_data, backend_response):
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


def test_non_ok_response_cannot_contain_scores(request_data):
    backend_response = response_for(request_data)
    backend_response["evaluation_status"] = "NEEDS_DATA"
    backend_response["errors"] = [{"code": "MISSING_HISTORY", "message": "Missing baseline history.", "activity_id": None}]
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


@pytest.mark.parametrize("errors", [
    [],
    [{"code": "BAD", "message": "", "activity_id": None}],
    [{"code": "BAD", "message": "Review needed.", "activity_id": "UNRELATED"}],
    [{"code": "BAD", "message": "Review needed."}],
])
def test_review_response_requires_well_formed_relevant_errors(request_data, errors):
    backend_response = response_for(request_data, status="NEEDS_REVIEW", errors=errors)
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


def test_backend_exception_is_not_leaked_or_retried(request_data):
    backend = Mock(side_effect=RuntimeError("private-token=secret; confidential student record"))
    result = ScorerAdapter(backend).score_plan(request_data)
    assert_failure(result, "SP2_BACKEND_FAILURE")
    assert "private-token" not in str(result)
    assert "confidential" not in str(result)
    backend.assert_called_once()


def test_backend_mutation_cannot_change_the_caller_or_validation_snapshot(request_data):
    original = deepcopy(request_data)
    expected = response_for(request_data)

    def mutating_backend(payload):
        payload["baseline"]["category_scores"]["C1"] = 29
        payload["baseline"]["included_activity_ids"].append("A")
        payload["selected_activity_ids"].append("B")
        return expected

    assert ScorerAdapter(mutating_backend).score_plan(request_data) == expected
    assert request_data == original


def test_backend_cannot_change_context_and_validate_against_its_mutated_input(request_data):
    original = deepcopy(request_data)

    def mutating_backend(payload):
        payload["context"]["student_id"] = "different-student"
        return response_for(payload)

    result = ScorerAdapter(mutating_backend).score_plan(request_data)
    assert_failure(result, "SP2_INVALID_RESPONSE")
    assert request_data == original
    assert result["context"] == original["context"]


def test_mutation_before_backend_exception_also_leaves_inputs_unchanged(request_data):
    original = deepcopy(request_data)

    def mutating_backend(payload):
        payload["baseline"].clear()
        raise ValueError("sensitive internal failure")

    result = ScorerAdapter(mutating_backend).score_plan(request_data)
    assert_failure(result, "SP2_BACKEND_FAILURE")
    assert request_data == original


def test_returned_result_does_not_alias_backend_or_caller_and_is_not_cached(request_data):
    original = deepcopy(request_data)
    backend_response = response_for(request_data)
    backend = Mock(return_value=backend_response)
    adapter = ScorerAdapter(backend)
    first = adapter.score_plan(request_data)
    first["context"]["student_id"] = "changed"
    first["result"]["category_after"]["C1"] = 999
    second = adapter.score_plan(request_data)
    assert second == backend_response == response_for(original)
    assert request_data == original
    assert backend.call_count == 2


def test_float_roundoff_is_allowed_without_rounding_or_repairing(request_data):
    request_data["baseline"].update(category_scores={"C1": 0.1, "C2": 0.2}, total_score=0.3)
    backend_response = response_for(request_data, result={
        "category_after": {"C1": 0.3, "C2": 0.2},
        "category_gain": {"C1": 0.2, "C2": 0},
        "total_after": 0.5, "total_gain": 0.2,
        "contributions": [contribution("A", "C1", 0.2)],
    })
    assert ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data) == backend_response


def test_large_scores_do_not_enable_large_relative_tolerance(request_data):
    request_data["baseline"].update(
        category_scores={"C1": 1e12, "C2": 0},
        category_caps={"C1": 2e12, "C2": 20}, total_score=1e12, max_total_score=2e12,
    )
    backend_response = response_for(request_data, result={
        "category_after": {"C1": 1e12 + 5, "C2": 0},
        "category_gain": {"C1": 5, "C2": 0},
        "total_after": 1e12 + 5.01, "total_gain": 5.01,
        "contributions": [contribution("A", "C1", 5)],
    })
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


def test_empty_plan_cannot_invent_even_a_tiny_gain(request_data):
    request_data["selected_activity_ids"] = []
    backend_response = response_for(request_data, result={
        "category_after": {"C1": 20 + 5e-10, "C2": 10},
        "category_gain": {"C1": 5e-10, "C2": 0},
        "total_after": 30 + 5e-10, "total_gain": 5e-10,
        "contributions": [],
    })
    assert_failure(ScorerAdapter(Mock(return_value=backend_response)).score_plan(request_data), "SP2_INVALID_RESPONSE")


def test_backend_must_be_explicitly_injected():
    with pytest.raises(TypeError, match="callable"):
        ScorerAdapter(None)
