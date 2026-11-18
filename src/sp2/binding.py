"""Propose activity-to-rule score bindings for SP3 (ADR-0002 D17). Deterministic, no model.

A binding is proposed only when two independent sources agree on the rule:
  1. the SP1 activity type, through TYPE_RULES below;
  2. the SP2 rule matcher (catalog signals over the announcement text).
Anything else goes to review. Points and categories always come from drl_rules.json; nothing is read
from the announcement. Every binding is labelled LABEL: it is a projection aid, not an award.
"""

from __future__ import annotations

LABEL = "auto_proposed_not_human_reviewed"
POLICY = "agree_else_review"
# SP1 activity_type -> rules it may bind to (approved 2026-11-14). Types not listed are never auto-bound.
TYPE_RULES = {
    "seminar_workshop": ("R19",),
    "academic_competition": ("R16",),
    "culture_sports_competition": ("R3102", "R3101"),
    # Content decides (D21): legal or social-evil wording -> R46; a safety talk (fire, traffic, scams) -> R19.
    "legal_health_campaign": ("R46", "R19"),
    # A career fair is R38; a CV or career-skills workshop is R19 ("tu van huong nghiep" is in R19's name).
    "career_admissions_event": ("R38", "R19"),
    "volunteer": ("R4301", "R4302", "R4303"),
    "fundraising": ("R45",),
    "blood_donation": ("R42",),
    "survey": ("R2301",),
}
REVIEWED_LABEL = "reviewed"
_COUNT_OPERATORS = {"count_greater_than"}
_SET_OPERATORS = {"equals"}


def propose_binding(activity_id: str, activity_type: str | None, match: dict, rules: dict,
                    reviewed_rule: str | None = None) -> dict:
    """Return {"binding": {...} or None, "reason": str, ...} for one activity.

    match is RuleMatch.as_dict() from the SP2 rule matcher; rules maps rule_id to the rule object.
    """
    matched = match.get("rule_id")
    allowed = TYPE_RULES.get(activity_type or "")
    info = {"activity_id": activity_id, "activity_type": activity_type, "matcher_rule": matched,
            "matcher_method": match.get("method"), "binding": None, "label": LABEL}
    if reviewed_rule:                     # a reviewer chose the rule: no agreement needed
        matched, info = reviewed_rule, {**info, "label": REVIEWED_LABEL}
    elif not allowed:
        return {**info, "reason": "activity_type_not_auto_bound"}
    elif matched not in allowed:
        return {**info, "reason": "sources_disagree"}
    rule = rules.get(matched)
    if rule is None or rule.get("status") != "verified":
        return {**info, "reason": "rule_not_verified"}
    condition = rule.get("condition") or {}
    operator, field = condition.get("operator"), condition.get("field")
    if not field:
        return {**info, "reason": "rule_has_no_fact_field"}
    if operator in _COUNT_OPERATORS:
        operation, value = "INCREMENT", 1
    elif operator in _SET_OPERATORS and type(condition.get("value")) in (str, int, float, bool):
        operation, value = "SET", condition["value"]
    else:
        return {**info, "reason": f"operator_unsupported_by_sp3:{operator}"}
    prefix = "reviewed" if reviewed_rule else "auto"
    binding = {"activity_id": activity_id, "binding_ref": f"{prefix}-{matched}-{activity_id}", "rule_id": matched,
               "field": field, "operation": operation, "value": value}
    return {**info, "binding": binding, "reason": "reviewer_decision" if reviewed_rule else "sources_agree",
            "category_id": rule.get("category_id"),
            "points_from_rules": rule.get("points")}
