import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "sp2_binding_under_test", Path(__file__).resolve().parents[2] / "src/sp2/binding.py")
binding = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = binding
_SPEC.loader.exec_module(binding)

RULES = {
    "R19": {"rule_id": "R19", "category_id": "C1", "points": 5, "status": "verified",
            "condition": {"field": "eligible_academic_seminars", "operator": "count_greater_than", "value": 0}},
    "R3102": {"rule_id": "R3102", "category_id": "C3", "points": 5, "status": "verified",
              "condition": {"field": "culture_competition_level", "operator": "equals", "value": "faculty"}},
    "R4301": {"rule_id": "R4301", "category_id": "C4", "points": 5, "status": "verified",
              "condition": {"field": "volunteer_hours_per_activity", "operator": "less_than", "value": 24}},
    "R4303": {"rule_id": "R4303", "category_id": "C4", "points": 15, "status": "verified",
              "condition": {"field": "volunteer_days", "operator": "greater_than_or_equal", "value": 7}},
    "R16": {"rule_id": "R16", "category_id": "C1", "points": 5, "status": "needs_review",
            "condition": {"field": "academic_competitions_completed_first_round", "operator": "count_greater_than"}},
}


def run(activity_type, rule_id, method="catalog_signal_match"):
    return binding.propose_binding("A1", activity_type, {"rule_id": rule_id, "method": method}, RULES)


def test_agreement_creates_a_labelled_increment_binding_with_points_from_rules():
    out = run("seminar_workshop", "R19")
    assert out["reason"] == "sources_agree" and out["points_from_rules"] == 5 and out["category_id"] == "C1"
    assert out["binding"] == {"activity_id": "A1", "binding_ref": "auto-R19-A1", "rule_id": "R19",
                              "field": "eligible_academic_seminars", "operation": "INCREMENT", "value": 1}


def test_disagreement_never_binds_even_when_the_matcher_is_confident():
    # A seminar that the matcher reads as long-term volunteering (15 points) must go to review.
    out = run("seminar_workshop", "R4303")
    assert out["binding"] is None and out["reason"] == "sources_disagree"


def test_unlisted_types_unverified_rules_and_unsupported_operators_go_to_review():
    assert run("other", "R19")["reason"] == "activity_type_not_auto_bound"
    assert run(None, "R19")["binding"] is None
    assert run("academic_competition", "R16")["reason"] == "rule_not_verified"
    assert run("volunteer", "R4301")["reason"] == "operator_unsupported_by_sp3:less_than"
    assert run("volunteer", "R4303")["reason"] == "operator_unsupported_by_sp3:greater_than_or_equal"


def test_equals_rule_becomes_a_set_binding():
    out = run("culture_sports_competition", "R3102")
    assert out["binding"]["operation"] == "SET" and out["binding"]["value"] == "faculty"
