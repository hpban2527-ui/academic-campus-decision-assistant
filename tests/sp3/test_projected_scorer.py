"""Projected scorer tests with a FAKE engine; real-engine checks live elsewhere."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sp3.contract import ContractError
from sp3.projected_scorer import (
    BindingOperation,
    InMemoryScoringData,
    ProjectedScorer,
    Ruleset,
    ScoreBinding,
    ScorerUnavailableError,
)
from sp3.scorer_adapter import ScorerAdapter

RULESET = {
    "rules": [
        {"rule_id": "RA", "category_id": "C1", "condition": {"field": "a_count", "operator": "count_greater_than", "value": 0}, "points": 5, "status": "verified"},
        {"rule_id": "RB", "category_id": "C2", "condition": {"field": "b_count", "operator": "count_greater_than", "value": 0}, "points": 4, "status": "verified"},
        {"rule_id": "RS", "category_id": "C1", "condition": {"field": "flag", "operator": "equals", "value": True}, "points": 3, "status": "verified"},
        {"rule_id": "RU", "category_id": "C1", "condition": {"field": "u_count", "operator": "count_greater_than", "value": 0}, "points": 5, "status": "needs_review"},
        {"rule_id": "RD", "category_id": "DEDUCTION", "condition": {"field": "d_count", "operator": "count_greater_than", "value": 0}, "points": -5, "status": "verified"},
        {"rule_id": "RG", "category_id": "C2", "condition": {"field": "gpa", "operator": "range", "min_inclusive": 3, "max_exclusive": 4}, "points": 2, "status": "verified"},
    ],
    "scoring_model": {"category_caps": [{"category_id": "C1", "max_score": 30}, {"category_id": "C2", "max_score": 20}], "max_total_score": 100},
}
CONTEXT = {
    "student_id": "synthetic-student", "term_id": "SYNTHETIC-DEMO",
    "window_start": "2026-11-01T00:00:00+07:00", "window_end": "2026-11-08T00:00:00+07:00",
    "as_of": "2026-11-01T08:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
    "baseline_ref": "baseline-1", "dataset_version": "dataset-1",
    "ruleset_version": "rules-1", "calendar_version": "calendar-1",
}


class FakeEngine:
    """Tiny stand-in with the evaluate_rule_conditions result shape."""

    def __init__(self, *, extra=None, cross_category=False):
        self.calls = []
        self.extra = extra or {}
        self.cross_category = cross_category

    def __call__(self, config, record, *, required_fields=()):
        self.calls.append(deepcopy(record))
        caps = {c["category_id"]: c["max_score"] for c in config["scoring_model"]["category_caps"]}
        raw = {}
        for rule in config["rules"]:
            condition, value = rule["condition"], record.get(rule["condition"]["field"])
            if rule["status"] != "verified" or value is None:
                continue
            if condition["operator"] == "count_greater_than" and value > condition["value"]:
                raw[rule["category_id"]] = raw.get(rule["category_id"], 0) + rule["points"] * value
            elif condition["operator"] == "equals" and value == condition["value"]:
                raw[rule["category_id"]] = raw.get(rule["category_id"], 0) + rule["points"]
        if self.cross_category and record.get("a_count", 0) > 1:
            raw["C2"] = raw.get("C2", 0) + 1
        scores = [{"category_id": c, "raw_score": s, "cap": caps.get(c), "score": min(s, caps[c]) if c in caps else s} for c, s in raw.items()]
        total = record.get("current_confirmed_score", 0) + sum(item["score"] for item in scores)
        return {
            "matched_rules": [], "category_scores": scores,
            "final_score": min(100, max(0, total)),
            "needs_review": False, "missing_fields": [], "skipped_rules": [],
            "relevant_configuration_issues": [], **deepcopy(self.extra),
        }


def activity(activity_id, start="2026-11-02T09:00:00+07:00"):
    return {
        "activity_id": activity_id,
        "source": {"publisher": "Synthetic", "platform": "fixture", "URL_post": f"https://example.invalid/{activity_id}", "URL_registration": None},
        "title": f"Synthetic {activity_id}", "domain": "academic", "start": start, "end": "2026-11-05T10:00:00+07:00",
        "registration_deadline": "2026-11-01T18:00:00+07:00", "mode": "online", "location": None,
        "points": None, "mandatory": False, "audience": None, "fee": 0, "completion_requirements": "Synthetic.",
    }


def binding(activity_id, rule_id, field, operation="INCREMENT", value=1):
    return {"activity_id": activity_id, "binding_ref": f"binding-{activity_id}", "rule_id": rule_id, "field": field, "operation": operation, "value": value}


def payload(**overrides):
    data = {
        "label": "SYNTHETIC-DEMO",
        "dataset_version": "dataset-1",
        "ruleset_version": "rules-1",
        "ruleset": deepcopy(RULESET),
        "baselines": [{"student_id": "synthetic-student", "baseline_ref": "baseline-1", "facts": {"a_count": 1, "b_count": 0, "flag": False}}],
        "activities": [activity("X", "2026-11-03T09:00:00+07:00"), activity("Y", "2026-11-02T09:00:00+07:00"), activity("Z")],
        "bindings": [binding("X", "RA", "a_count"), binding("Y", "RB", "b_count"), binding("Z", "RS", "flag", "SET", True)],
    }
    data.update(overrides)
    return data


def request(selected, **baseline_overrides):
    baseline = {
        "category_scores": {"C1": 5, "C2": 0}, "category_caps": {"C1": 30, "C2": 20},
        "total_score": 5, "max_total_score": 100, "included_activity_ids": [],
    }
    baseline.update(baseline_overrides)
    return {
        "contract_version": "sp3-planner/0.1", "request_id": "synthetic-request",
        "context": deepcopy(CONTEXT), "baseline": baseline, "selected_activity_ids": sorted(selected),
    }


def scorer(engine=None, **overrides):
    return ProjectedScorer(InMemoryScoringData(payload(**overrides)), engine=engine or FakeEngine())


def error_codes(response):
    return [(issue["code"], issue["activity_id"]) for issue in response["errors"]]


def assert_status(response, status):
    assert response["evaluation_status"] == status
    assert response["mode"] == "DEMO_ONLY" and response["official_award_verified"] is False
    if status != "OK":
        assert response["result"] is None and response["errors"]


# Successful scoring ----------------------------------------------------------

def test_empty_set_returns_the_baseline():
    response = scorer()(request([]))
    assert_status(response, "OK")
    assert response["result"] == {
        "category_after": {"C1": 5, "C2": 0}, "category_gain": {"C1": 0, "C2": 0},
        "total_after": 5, "total_gain": 0, "contributions": [],
    }


def test_whole_set_is_scored_with_rule_categories():
    response = scorer()(request(["X", "Y", "Z"]))
    assert_status(response, "OK")
    result = response["result"]
    assert result["category_after"] == {"C1": 13, "C2": 4}
    assert result["category_gain"] == {"C1": 8, "C2": 4}
    assert (result["total_after"], result["total_gain"]) == (17, 12)
    # Start order: Y (Nov 2) and Z (Nov 2) before X (Nov 3); Y < Z by ID.
    assert result["contributions"] == [
        {"activity_id": "Y", "category_id": "C2", "rule_id": "RB", "projected_added": 4},
        {"activity_id": "Z", "category_id": "C1", "rule_id": "RS", "projected_added": 3},
        {"activity_id": "X", "category_id": "C1", "rule_id": "RA", "projected_added": 5},
    ]


def test_prefix_attribution_follows_start_time_not_id_under_a_cap():
    data = payload(
        baselines=[{"student_id": "synthetic-student", "baseline_ref": "baseline-1", "facts": {"a_count": 5}}],
        activities=[activity("A", "2026-11-04T09:00:00+07:00"), activity("B", "2026-11-02T09:00:00+07:00")],
        bindings=[binding("A", "RA", "a_count"), binding("B", "RA", "a_count")],
    )
    response = ProjectedScorer(InMemoryScoringData(data), engine=FakeEngine())(
        request(["A", "B"], category_scores={"C1": 25, "C2": 0}, total_score=25),
    )
    assert_status(response, "OK")
    assert response["result"]["contributions"] == [
        {"activity_id": "B", "category_id": "C1", "rule_id": "RA", "projected_added": 5},
        {"activity_id": "A", "category_id": "C1", "rule_id": "RA", "projected_added": 0},
    ]


def test_adapter_accepts_the_projected_envelope():
    adapter_response = ScorerAdapter(scorer()).score_plan(request(["X", "Y"]))
    assert_status(adapter_response, "OK")
    assert adapter_response["result"]["category_after"] == {"C1": 10, "C2": 4}


# Memoization, context binding and read-only behaviour --------------------------

def test_engine_runs_are_memoized_within_one_instance():
    engine = FakeEngine()
    instance = scorer(engine)
    instance(request(["X"]))
    assert instance.engine_calls == len(engine.calls) == 2  # baseline, +X
    instance(request(["X"]))
    instance(request(["X", "Y"]))
    # Start order Y then X: the prefix {Y} and the set {X, Y} are new states.
    assert instance.engine_calls == len(engine.calls) == 4


def test_memo_is_per_instance():
    engine = FakeEngine()
    scorer(engine)(request(["X"]))
    scorer(engine)(request(["X"]))
    assert len(engine.calls) == 4


def test_instance_rejects_a_second_context():
    instance = scorer()
    assert_status(instance(request(["X"])), "OK")
    other = request(["X"])
    other["context"]["calendar_version"] = "calendar-2"
    response = instance(other)
    assert_status(response, "ERROR")
    assert error_codes(response) == [("CONTEXT_MISMATCH", None)]


def test_scoring_does_not_mutate_requests_or_data():
    data = payload()
    original = deepcopy(data)
    source = InMemoryScoringData(data)
    engine = FakeEngine()
    instance = ProjectedScorer(source, engine=engine)
    sent = request(["X", "Y", "Z"])
    snapshot = deepcopy(sent)
    instance(sent)
    assert sent == snapshot
    assert data == original
    assert source.baseline_facts(CONTEXT) == original["baselines"][0]["facts"]
    assert engine.calls[0] == original["baselines"][0]["facts"]


def test_invalid_request_raises_before_any_engine_call():
    engine = FakeEngine()
    bad = request(["X"])
    bad["selected_activity_ids"] = ["Y", "X"]
    with pytest.raises(ContractError):
        scorer(engine)(bad)
    assert engine.calls == []


# NEEDS_REVIEW paths ---------------------------------------------------------------

def _without(items, activity_id):
    return [item for item in items if item["activity_id"] != activity_id]


@pytest.mark.parametrize("overrides,selected,expected", [
    ({"ruleset_version": "rules-other"}, ["X"], [("MISSING_RULESET", None)]),
    ({"baselines": []}, ["X"], [("MISSING_BASELINE_FACTS", None)]),
    ({"dataset_version": "dataset-other"}, ["X"], [("MISSING_ACTIVITY", "X")]),
    ({"activities": [activity("Y")]}, ["X"], [("MISSING_ACTIVITY", "X")]),
    ({"activities": [activity("X", None)]}, ["X"], [("MISSING_SCHEDULE", "X")]),
    ({"bindings": [binding("Y", "RB", "b_count")]}, ["X", "Z"], [("MISSING_BINDING", "X"), ("MISSING_BINDING", "Z")]),
    ({"bindings": [binding("X", "R404", "a_count")]}, ["X"], [("UNKNOWN_RULE", "X")]),
    ({"bindings": [binding("X", "RU", "u_count")]}, ["X"], [("UNVERIFIED_RULE", "X")]),
    ({"bindings": [binding("X", "RA", "b_count")]}, ["X"], [("BINDING_FIELD_MISMATCH", "X")]),
    ({"bindings": [binding("X", "RA", "a_count", "SET", 3)]}, ["X"], [("UNSUPPORTED_BINDING_OPERATION", "X")]),
    ({"bindings": [binding("X", "RS", "flag", "INCREMENT", 1)]}, ["X"], [("UNSUPPORTED_BINDING_OPERATION", "X")]),
    ({"bindings": [binding("X", "RG", "gpa", "INCREMENT", 1)]}, ["X"], [("UNSUPPORTED_BINDING_OPERATION", "X")]),
    ({"bindings": [binding("X", "RD", "d_count")]}, ["X"], [("UNSUPPORTED_CATEGORY", "X")]),
])
def test_missing_or_unverifiable_data_needs_review(overrides, selected, expected):
    response = scorer(**overrides)(request(selected))
    assert_status(response, "NEEDS_REVIEW")
    assert error_codes(response) == expected


def test_increment_on_an_absent_fact_is_not_assumed_zero():
    data = payload(baselines=[{"student_id": "synthetic-student", "baseline_ref": "baseline-1", "facts": {"a_count": 1, "flag": False}}])
    response = ProjectedScorer(InMemoryScoringData(data), engine=FakeEngine())(request(["Y"]))
    assert_status(response, "NEEDS_REVIEW")
    assert error_codes(response) == [("MISSING_BASELINE_FACT", "Y")]


def test_change_outside_the_rule_category_is_an_unsupported_interaction():
    response = scorer(FakeEngine(cross_category=True))(request(["X"]))
    assert_status(response, "NEEDS_REVIEW")
    assert error_codes(response) == [("UNSUPPORTED_RULE_INTERACTION", "X")]


def test_lowering_a_score_is_an_unsupported_interaction():
    data = payload(baselines=[{"student_id": "synthetic-student", "baseline_ref": "baseline-1", "facts": {"a_count": 0, "flag": True}}])
    data["bindings"] = [binding("Z", "RS", "flag", "SET", False)]
    response = ProjectedScorer(InMemoryScoringData(data), engine=FakeEngine())(
        request(["Z"], category_scores={"C1": 3, "C2": 0}, total_score=3),
    )
    assert_status(response, "NEEDS_REVIEW")
    assert error_codes(response) == [("UNSUPPORTED_RULE_INTERACTION", "Z")]


@pytest.mark.parametrize("extra,code", [
    ({"needs_review": True, "skipped_rules": [{"rule_id": "RU", "reason": "rule is not reviewer-verified"}]}, "SP2_RULE_SKIPPED"),
    ({"needs_review": True, "missing_fields": ["b_count"]}, "SP2_MISSING_FIELD"),
    ({"needs_review": True, "relevant_configuration_issues": [{"code": "RANGE_REVERSED", "path": "rules[5].condition"}]}, "SP2_RULE_CONFIGURATION"),
    ({"needs_review": True}, "SP2_NEEDS_REVIEW"),
])
def test_engine_review_reasons_are_passed_through(extra, code):
    response = scorer(FakeEngine(extra=extra))(request(["X"]))
    assert_status(response, "NEEDS_REVIEW")
    assert response["errors"][0]["code"] == code
    assert response["errors"][0]["activity_id"] is None


def test_engine_review_raised_by_one_prefix_is_attributed_to_that_activity():
    class ReviewOnTwo(FakeEngine):
        def __call__(self, config, record, **kwargs):
            result = super().__call__(config, record, **kwargs)
            if record.get("a_count") == 2:
                result.update(needs_review=True, missing_fields=["evidence"])
            return result

    response = scorer(ReviewOnTwo())(request(["X"]))
    assert error_codes(response) == [("SP2_MISSING_FIELD", "X")]


def test_non_zero_score_outside_baseline_categories_needs_review():
    data = payload(baselines=[{"student_id": "synthetic-student", "baseline_ref": "baseline-1", "facts": {"a_count": 1, "b_count": 0, "d_count": 1}}])
    response = ProjectedScorer(InMemoryScoringData(data), engine=FakeEngine())(request(["X"]))
    assert_status(response, "NEEDS_REVIEW")
    assert error_codes(response) == [("UNSUPPORTED_CATEGORY", None)]


def test_zero_score_outside_baseline_categories_is_ignored():
    zero_deduction = FakeEngine()
    original = zero_deduction.__call__

    def engine(config, record, **kwargs):
        result = original(config, record, **kwargs)
        result["category_scores"].append({"category_id": "DEDUCTION", "raw_score": 0, "cap": None, "score": 0})
        return result

    response = scorer(engine)(request(["X"]))
    assert_status(response, "OK")


# ERROR paths --------------------------------------------------------------------

def test_cap_mismatch_is_an_error():
    response = scorer()(request(["X"], category_caps={"C1": 25, "C2": 20}))
    assert_status(response, "ERROR")
    assert error_codes(response) == [("CAP_MISMATCH", None)]


def test_cap_category_set_must_match_the_ruleset():
    response = scorer()(request([], category_scores={"C1": 5}, category_caps={"C1": 30}))
    assert error_codes(response) == [("CAP_MISMATCH", None)]


def test_max_total_mismatch_is_an_error():
    response = scorer()(request(["X"], max_total_score=90))
    assert error_codes(response) == [("CAP_MISMATCH", None)]


def test_baseline_mismatch_is_an_error():
    response = scorer()(request(["X"], category_scores={"C1": 6, "C2": 0}, total_score=6))
    assert_status(response, "ERROR")
    assert error_codes(response) == [("BASELINE_MISMATCH", None)]


def test_engine_total_with_different_semantics_is_an_error():
    data = payload(baselines=[{"student_id": "synthetic-student", "baseline_ref": "baseline-1", "facts": {"a_count": 1, "b_count": 0, "current_confirmed_score": 40}}])
    response = ProjectedScorer(InMemoryScoringData(data), engine=FakeEngine())(request(["X"]))
    assert_status(response, "ERROR")
    assert error_codes(response) == [("TOTAL_SEMANTICS_MISMATCH", None)]


def test_engine_exception_is_an_error_without_leaking_text():
    def engine(config, record, **kwargs):
        raise RuntimeError("secret engine detail")

    response = scorer(engine)(request(["X"]))
    assert_status(response, "ERROR")
    assert error_codes(response) == [("SP2_ENGINE_FAILURE", None)]
    assert "secret" not in json.dumps(response)


@pytest.mark.parametrize("raw", [None, {}, {"category_scores": "C1", "final_score": 1}, {"category_scores": [], "final_score": float("nan"), "needs_review": False, "missing_fields": [], "skipped_rules": []}])
def test_unexpected_engine_output_is_an_error(raw):
    response = scorer(lambda config, record, **kwargs: raw)(request(["X"]))
    assert error_codes(response) == [("SP2_ENGINE_OUTPUT_INVALID", None)]


def test_data_source_returning_another_ruleset_version_is_an_error():
    class WrongVersion(InMemoryScoringData):
        def ruleset(self, context):
            return Ruleset("rules-other", deepcopy(RULESET))

    response = ProjectedScorer(WrongVersion(payload()), engine=FakeEngine())(request(["X"]))
    assert error_codes(response) == [("RULESET_VERSION_MISMATCH", None)]


# Construction and data validation -----------------------------------------------

def test_missing_sp2_engine_fails_at_construction(monkeypatch):
    monkeypatch.setitem(sys.modules, "sp2.drl_engine", None)
    with pytest.raises(ScorerUnavailableError):
        ProjectedScorer(InMemoryScoringData(payload()))


def test_engine_must_be_callable():
    with pytest.raises(TypeError):
        ProjectedScorer(InMemoryScoringData(payload()), engine=object())


@pytest.mark.parametrize("overrides", [
    {"label": ""},
    {"ruleset": {"rules": []}},
    {"activities": [activity("X"), activity("X")]},
    {"activities": [{**activity("X"), "extra": 1}]},
    {"bindings": [binding("X", "RA", "a_count"), binding("X", "RB", "b_count")]},
    {"bindings": [binding("X", "RA", "a_count", "ADD")]},
    {"bindings": [binding("X", "RA", "a_count", "INCREMENT", 0)]},
    {"bindings": [binding("X", "RA", "a_count", "INCREMENT", True)]},
    {"bindings": [binding("X", "RS", "flag", "SET", None)]},
    {"bindings": [binding("X", "", "a_count")]},
    {"baselines": [{"student_id": "s", "baseline_ref": "b", "facts": {"a_count": float("nan")}}]},
    {"baselines": [{"student_id": "s", "baseline_ref": "b", "facts": []}]},
])
def test_in_memory_data_rejects_invalid_payloads(overrides):
    with pytest.raises(ContractError):
        InMemoryScoringData(payload(**overrides))


def test_in_memory_data_scopes_lookups_by_context_and_detaches_copies():
    source = InMemoryScoringData(payload())
    other_student = {**CONTEXT, "student_id": "someone-else"}
    assert source.baseline_facts(other_student) is None
    assert source.ruleset({**CONTEXT, "ruleset_version": "rules-2"}) is None
    assert source.binding({**CONTEXT, "dataset_version": "dataset-2"}, "X") is None
    facts = source.baseline_facts(CONTEXT)
    facts["a_count"] = 99
    assert source.baseline_facts(CONTEXT)["a_count"] == 1
    assert source.binding(CONTEXT, "Z") == ScoreBinding("binding-Z", "RS", "flag", BindingOperation.SET, True)
