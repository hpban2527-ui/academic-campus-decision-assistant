"""Calculate DRL scores and topic progress for SP2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any, Iterable, Mapping, Sequence


class DRLEngineError(ValueError):
    """Invalid input or rule configuration."""


@dataclass(frozen=True)
class AuditIssue:
    """A problem found while checking the rule file."""

    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


SUPPORTED_OPERATORS = {
    "equals",
    "range",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "in",
    "count_greater_than",
}

VERIFIED_EVIDENCE_STATUSES = {"APPROVED", "CONFIRMED", "VERIFIED"}
VERIFIED_CLAIM_STATUSES = {
    "CONFIRMED",
    "VERIFIED",
    "VERIFIED_BY_REVIEWER",
}
NON_CONFIRMED_RECORD_STATUSES = {"PENDING", "POTENTIAL"}


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _normalise_scalar(value: Any) -> str:
    return str(value).strip().casefold()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _jsonish(value: Any) -> Any:
    """Convert nested values so they can be compared in the audit."""

    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _jsonish(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_jsonish(item) for item in value)
    return value


def _condition_signature(rule: Mapping[str, Any]) -> tuple[Any, ...]:
    condition = rule.get("condition", {})
    if not isinstance(condition, Mapping):
        return (rule.get("criterion_id"), None, None, None)
    return (
        rule.get("criterion_id"),
        condition.get("field"),
        condition.get("operator"),
        _jsonish({key: value for key, value in condition.items() if key != "field"}),
    )


def audit_rules_config(config: Mapping[str, Any]) -> list[dict[str, str]]:
    """Check the rules file and return errors or warnings."""

    issues: list[AuditIssue] = []
    rules = config.get("rules")
    scoring = config.get("scoring_model")
    if not isinstance(rules, list):
        return [
            AuditIssue(
                "error", "RULES_NOT_LIST", "rules", "rules must be an array"
            ).to_dict()
        ]
    if not isinstance(scoring, Mapping):
        issues.append(
            AuditIssue(
                "error",
                "SCORING_MODEL_MISSING",
                "scoring_model",
                "scoring_model must be an object",
            )
        )

    known_categories = {"DEDUCTION"}
    if isinstance(scoring, Mapping):
        caps = scoring.get("category_caps", [])
        if isinstance(caps, list):
            for cap in caps:
                if isinstance(cap, Mapping) and cap.get("category_id"):
                    known_categories.add(str(cap["category_id"]))

    ids: set[str] = set()
    condition_signatures: dict[tuple[Any, ...], str] = {}
    for index, rule in enumerate(rules):
        path = f"rules[{index}]"
        if not isinstance(rule, Mapping):
            issues.append(
                AuditIssue("error", "RULE_NOT_OBJECT", path, "rule must be an object")
            )
            continue

        rule_id = rule.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            issues.append(
                AuditIssue("error", "RULE_ID_MISSING", f"{path}.rule_id", "rule_id is required")
            )
        elif rule_id in ids:
            issues.append(
                AuditIssue(
                    "error",
                    "DUPLICATE_RULE_ID",
                    f"{path}.rule_id",
                    f"duplicate rule_id {rule_id}",
                )
            )
        else:
            ids.add(rule_id)

        points = rule.get("points")
        if not _is_number(points):
            issues.append(
                AuditIssue(
                    "error", "POINTS_NOT_NUMERIC", f"{path}.points", "points must be numeric"
                )
            )

        category_id = rule.get("category_id")
        if category_id not in known_categories:
            issues.append(
                AuditIssue(
                    "warning",
                    "UNKNOWN_CATEGORY",
                    f"{path}.category_id",
                    f"category {category_id!r} has no configured cap",
                )
            )

        condition = rule.get("condition")
        if not isinstance(condition, Mapping):
            issues.append(
                AuditIssue(
                    "error",
                    "CONDITION_MISSING",
                    f"{path}.condition",
                    "condition must be an object",
                )
            )
            continue
        field = condition.get("field")
        operator = condition.get("operator")
        if not isinstance(field, str) or not field:
            issues.append(
                AuditIssue(
                    "error", "FIELD_MISSING", f"{path}.condition.field", "field is required"
                )
            )
        if operator not in SUPPORTED_OPERATORS:
            issues.append(
                AuditIssue(
                    "error",
                    "UNSUPPORTED_OPERATOR",
                    f"{path}.condition.operator",
                    f"unsupported operator {operator!r}",
                )
            )

        if operator == "range":
            lower = condition.get("min_inclusive")
            upper = condition.get("max_exclusive", condition.get("max_inclusive"))
            if not _is_number(lower) or not _is_number(upper):
                issues.append(
                    AuditIssue(
                        "error",
                        "RANGE_BOUND_NOT_NUMERIC",
                        f"{path}.condition",
                        "range bounds must both be numeric",
                    )
                )
            elif lower > upper:
                issues.append(
                    AuditIssue(
                        "error",
                        "RANGE_REVERSED",
                        f"{path}.condition",
                        "range lower bound exceeds upper bound",
                    )
                )

        signature = _condition_signature(rule)
        previous = condition_signatures.get(signature)
        if previous and isinstance(rule_id, str):
            issues.append(
                AuditIssue(
                    "warning",
                    "DUPLICATE_CONDITION",
                    f"{path}.condition",
                    f"same criterion and condition as {previous}; review double-counting",
                )
            )
        elif isinstance(rule_id, str):
            condition_signatures[signature] = rule_id

    return [issue.to_dict() for issue in issues]


def _condition_matches(condition: Mapping[str, Any], actual: Any) -> bool:
    operator = condition.get("operator")
    expected = condition.get("value")

    if operator == "equals":
        return actual == expected
    if operator == "in":
        return isinstance(expected, list) and actual in expected
    if operator in {
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "count_greater_than",
    }:
        if not _is_number(actual) or not _is_number(expected):
            return False
        if operator in {"greater_than", "count_greater_than"}:
            return actual > expected
        if operator == "greater_than_or_equal":
            return actual >= expected
        return actual < expected
    if operator == "range":
        lower = condition.get("min_inclusive")
        upper_exclusive = condition.get("max_exclusive")
        upper_inclusive = condition.get("max_inclusive")
        if not _is_number(actual) or not _is_number(lower):
            return False
        if upper_exclusive is not None:
            return _is_number(upper_exclusive) and lower <= actual < upper_exclusive
        return _is_number(upper_inclusive) and lower <= actual <= upper_inclusive
    return False


def _repeat_count(rule: Mapping[str, Any], actual: Any) -> int:
    """Get the multiplier for rules that can be counted more than once."""

    repeatable_units = {
        "per_activity",
        "per_award",
        "per_competition",
        "per_eligible_achievement",
        "per_project",
        "per_published_article",
    }
    condition = rule.get("condition", {})
    if (
        isinstance(condition, Mapping)
        and condition.get("operator") == "count_greater_than"
        and rule.get("unit") in repeatable_units
        and _is_number(actual)
    ):
        return max(1, int(actual))
    return 1


def evaluate_rule_conditions(
    config: Mapping[str, Any],
    student_record: Mapping[str, Any],
    *,
    required_fields: Iterable[str] = (),
) -> dict[str, Any]:
    """Match the flat rules against a confirmed student record."""

    configuration_issues = audit_rules_config(config)
    fatal_codes = {
        "RULES_NOT_LIST",
        "SCORING_MODEL_MISSING",
        "RULE_NOT_OBJECT",
        "RULE_ID_MISSING",
        "DUPLICATE_RULE_ID",
        "CONDITION_MISSING",
        "FIELD_MISSING",
        "POINTS_NOT_NUMERIC",
    }
    fatal_issues = [
        issue for issue in configuration_issues if issue["code"] in fatal_codes
    ]
    if fatal_issues:
        raise DRLEngineError(f"rule configuration has fatal errors: {fatal_issues}")

    invalid_rule_indexes = {
        int(issue["path"].split("[")[1].split("]")[0])
        for issue in configuration_issues
        if issue["severity"] == "error" and issue["path"].startswith("rules[")
    }

    rules = config["rules"]
    scoring = config["scoring_model"]
    matched: list[dict[str, Any]] = []
    skipped_rules: list[dict[str, str]] = []
    by_category_raw: dict[str, float] = {}
    seen_conditions: dict[tuple[Any, ...], str] = {}
    relevant_configuration_issues: list[dict[str, str]] = []

    for issue in configuration_issues:
        if issue["severity"] != "error" or not issue["path"].startswith("rules["):
            continue
        index = int(issue["path"].split("[")[1].split("]")[0])
        condition = rules[index].get("condition", {})
        field = condition.get("field") if isinstance(condition, Mapping) else None
        if field in student_record and student_record[field] is not None:
            relevant_configuration_issues.append(issue)

    for index, rule in enumerate(rules):
        # Skip the broken rule but keep checking the other rules.
        if index in invalid_rule_indexes:
            continue
        condition = rule["condition"]
        field = condition["field"]
        if field not in student_record or student_record[field] is None:
            continue
        actual = student_record[field]
        if not _condition_matches(condition, actual):
            continue
        signature = _condition_signature(rule)
        if signature in seen_conditions:
            skipped_rules.append(
                {
                    "rule_id": str(rule["rule_id"]),
                    "reason": f"same condition already matched by {seen_conditions[signature]}",
                }
            )
            continue
        seen_conditions[signature] = str(rule["rule_id"])
        multiplier = _repeat_count(rule, actual)
        awarded = rule["points"] * multiplier
        matched.append(
            {
                "rule_id": rule["rule_id"],
                "criterion_id": rule.get("criterion_id"),
                "category_id": rule.get("category_id"),
                "points": awarded,
                "base_points": rule["points"],
                "multiplier": multiplier,
                "source": rule.get("source"),
            }
        )
        category = str(rule.get("category_id"))
        by_category_raw[category] = by_category_raw.get(category, 0) + awarded

    caps = {
        str(item.get("category_id")): item.get("max_score")
        for item in scoring.get("category_caps", [])
        if isinstance(item, Mapping)
    }
    by_category: list[dict[str, Any]] = []
    rule_points_total = 0.0
    for category, raw_score in by_category_raw.items():
        cap = caps.get(category)
        score = min(raw_score, cap) if _is_number(cap) and raw_score > 0 else raw_score
        by_category.append(
            {"category_id": category, "raw_score": raw_score, "cap": cap, "score": score}
        )
        rule_points_total += score

    base = student_record.get("current_confirmed_score", 0)
    extras = student_record.get("eligible_extra_points", 0)
    if not _is_number(base) or not _is_number(extras):
        raise DRLEngineError("current_confirmed_score and eligible_extra_points must be numeric")
    raw_total = base + extras + rule_points_total
    maximum = scoring.get("max_total_score", 100)
    minimum = scoring.get("semester_score_min", 0)
    if not _is_number(maximum) or not _is_number(minimum):
        raise DRLEngineError("score minimum and maximum must be numeric")
    final_score = min(maximum, max(minimum, raw_total))
    missing = sorted(
        field
        for field in set(required_fields)
        if field not in student_record or student_record[field] is None
    )

    return {
        "matched_rules": matched,
        "rule_points_total": _clean_number(rule_points_total),
        "category_scores": by_category,
        "raw_total_before_cap": _clean_number(raw_total),
        "final_score": _clean_number(final_score),
        "needs_review": bool(missing or relevant_configuration_issues or skipped_rules),
        "missing_fields": missing,
        "skipped_rules": skipped_rules,
        "configuration_issues": configuration_issues,
        "relevant_configuration_issues": relevant_configuration_issues,
    }


def _clean_number(value: float | int) -> float | int:
    return int(value) if float(value).is_integer() else value


def _scope_value(profile: Mapping[str, Any], plural_key: str) -> Any:
    aliases = {
        "universities": ("university", "universities"),
        "faculties": ("faculty", "faculties"),
        "cohorts": ("cohort", "cohorts"),
        "programs": ("program", "programs"),
        "campuses": ("campus", "campuses"),
    }
    for key in aliases.get(plural_key, (plural_key,)):
        if key in profile:
            return profile[key]
    return None


def _resolve_scope(
    scope: Any, profile: Mapping[str, Any]
) -> tuple[str, list[str]]:
    if not isinstance(scope, Mapping) or not scope:
        return "NEEDS_VERIFICATION", ["Rule set has no explicit scope"]

    reasons: list[str] = []
    missing = False
    mismatch = False
    for scope_key in ("universities", "faculties", "cohorts", "programs", "campuses"):
        allowed = scope.get(scope_key)
        if allowed is None:
            continue
        allowed_values = _as_list(allowed)
        if not allowed_values:
            continue
        actual = _scope_value(profile, scope_key)
        if actual is None:
            missing = True
            reasons.append(f"Student profile is missing {scope_key}")
            continue
        actual_values = {_normalise_scalar(value) for value in _as_list(actual)}
        allowed_normalised = {_normalise_scalar(value) for value in allowed_values}
        if actual_values.isdisjoint(allowed_normalised):
            mismatch = True
            reasons.append(
                f"Student {scope_key} {sorted(actual_values)!r} is outside rule scope "
                f"{sorted(allowed_normalised)!r}"
            )
    if mismatch:
        return "NEEDS_VERIFICATION", reasons
    if missing:
        return "NEEDS_INFO", reasons
    return "APPLICABLE", reasons


def _evidence_is_verified(record: Mapping[str, Any]) -> bool:
    if record.get("evidence_verified") is True:
        return True
    status = record.get("evidence_status")
    if isinstance(status, str) and status.upper() in VERIFIED_EVIDENCE_STATUSES:
        return True
    evidence = record.get("evidence")
    if isinstance(evidence, Mapping):
        nested_status = evidence.get("status")
        if (
            isinstance(nested_status, str)
            and nested_status.upper() in VERIFIED_EVIDENCE_STATUSES
        ):
            return True
    return bool(
        record.get("evidence_id")
        and record.get("confirmed_by")
        and record.get("confirmed_at")
    )


def _activity_index(activities: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for activity in activities:
        activity_id = activity.get("activity_id")
        if isinstance(activity_id, str):
            result[activity_id] = activity
    return result


def _verified_claims(activity: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not activity:
        return []
    claims = activity.get("benefit_claims", [])
    if not isinstance(claims, list):
        return []
    return [
        claim
        for claim in claims
        if isinstance(claim, Mapping)
        and isinstance(claim.get("verification_status"), str)
        and claim["verification_status"].upper() in VERIFIED_CLAIM_STATUSES
    ]


def _criterion_and_points(
    record: Mapping[str, Any], activity: Mapping[str, Any] | None
) -> tuple[Any, Any, str | None]:
    criterion = record.get("criterion_code")
    points = record.get("points")
    if criterion is not None and _is_number(points):
        return criterion, points, None
    for claim in _verified_claims(activity):
        claim_type = str(claim.get("type", "")).upper()
        claim_criterion = claim.get("drl_criterion") or claim.get("criterion_code")
        claim_points = claim.get("points")
        if claim_type in {"DRL_POINTS", "DRL_SCORE"} and claim_criterion and _is_number(claim_points):
            if criterion is None or criterion == claim_criterion:
                return claim_criterion, claim_points, str(claim.get("claim_id") or "")
    return criterion, points, None


def _topic_code(
    record: Mapping[str, Any], activity: Mapping[str, Any] | None
) -> tuple[Any, str | None]:
    if record.get("topic_code") is not None:
        return record["topic_code"], None
    for claim in _verified_claims(activity):
        claim_type = str(claim.get("type", "")).upper()
        if (
            claim_type == "TOPIC_CREDIT"
            and claim.get("topic_code")
            and claim.get("counts_for_topic") is True
        ):
            return claim["topic_code"], str(claim.get("claim_id") or "")
    return None, None


def _empty_progress_report(
    rule_set: Mapping[str, Any], resolution: str, reasons: list[str]
) -> dict[str, Any]:
    return {
        "rule_set_id": rule_set.get("rule_set_id"),
        "rule_set_version": rule_set.get("version"),
        "rule_resolution": resolution,
        "confirmed_total": 0,
        "confirmed_by_criterion": [],
        "pending_items": [],
        "remaining_by_criterion": [],
        "topic_progress": [],
        "missing_requirements": [],
        "verification_flags": reasons,
        "applied_records": [],
    }


def evaluate_progress(
    rule_set: Mapping[str, Any],
    student_profile: Mapping[str, Any],
    student_records: Sequence[Mapping[str, Any]],
    *,
    activities: Sequence[Mapping[str, Any]] = (),
    personal_targets: Mapping[str, Real] | None = None,
    require_verified_rules: bool = False,
) -> dict[str, Any]:
    """Calculate confirmed scores, missing points and topic progress."""

    if not isinstance(rule_set, Mapping):
        raise DRLEngineError("rule_set must be an object")
    criteria = rule_set.get("criteria", [])
    topics = rule_set.get("topic_requirements", [])
    if not isinstance(criteria, list) or not isinstance(topics, list):
        raise DRLEngineError("criteria and topic_requirements must be arrays")
    if not isinstance(student_records, Sequence) or isinstance(student_records, (str, bytes)):
        raise DRLEngineError("student_records must be an array")

    resolution, scope_reasons = _resolve_scope(rule_set.get("scope"), student_profile)
    if require_verified_rules and rule_set.get("verified") is not True:
        resolution = "NEEDS_VERIFICATION"
        scope_reasons.append("Rule set is not reviewer-verified")
    if resolution != "APPLICABLE":
        return _empty_progress_report(rule_set, resolution, scope_reasons)

    flags = list(scope_reasons)
    if rule_set.get("verified") is not True:
        flags.append("DEMO_RULE_SET: calculated result is not official university recognition")

    criteria_by_code = {
        item.get("code"): item
        for item in criteria
        if isinstance(item, Mapping) and item.get("code") is not None
    }
    topic_by_code = {
        item.get("topic_code"): item
        for item in topics
        if isinstance(item, Mapping) and item.get("topic_code") is not None
    }
    activity_by_id = _activity_index(activities)
    pending_items: list[dict[str, Any]] = []
    applied_records: list[dict[str, Any]] = []
    score_records: dict[str, list[tuple[str, Real]]] = {
        str(code): [] for code in criteria_by_code
    }
    topic_records: dict[str, dict[str, str]] = {str(code): {} for code in topic_by_code}
    seen_score_keys: set[tuple[str, str]] = set()

    for index, record in enumerate(student_records):
        if not isinstance(record, Mapping):
            flags.append(f"records[{index}]: invalid record object")
            continue
        record_id = str(record.get("record_id") or record.get("id") or f"record-{index}")
        status = str(record.get("status", "")).upper()
        if status in NON_CONFIRMED_RECORD_STATUSES:
            pending_items.append(
                {
                    "record_id": record_id,
                    "status": status,
                    "activity_id": record.get("activity_id"),
                    "reason": "Not included in confirmed progress",
                }
            )
            continue
        if status != "CONFIRMED":
            flags.append(f"{record_id}: unsupported or missing record status")
            continue
        if not _evidence_is_verified(record):
            flags.append(f"{record_id}: CONFIRMED record has no verified evidence")
            pending_items.append(
                {
                    "record_id": record_id,
                    "status": "NEEDS_VERIFICATION",
                    "activity_id": record.get("activity_id"),
                    "reason": "Verified evidence is required before scoring",
                }
            )
            continue

        activity_id = record.get("activity_id")
        activity = activity_by_id.get(str(activity_id)) if activity_id is not None else None
        criterion, points, criterion_claim = _criterion_and_points(record, activity)
        topic_code, topic_claim = _topic_code(record, activity)
        contributions: list[str] = []

        if criterion is not None:
            criterion_key = str(criterion)
            if criterion_key not in score_records:
                flags.append(f"{record_id}: unknown criterion {criterion_key}")
            elif not _is_number(points):
                flags.append(f"{record_id}: criterion {criterion_key} has no verified numeric points")
            else:
                dedup_identity = str(activity_id or record_id)
                dedup_key = (criterion_key, dedup_identity)
                if dedup_key in seen_score_keys:
                    flags.append(
                        f"{record_id}: duplicate criterion contribution for {dedup_identity} ignored"
                    )
                else:
                    seen_score_keys.add(dedup_key)
                    score_records[criterion_key].append((record_id, points))
                    contributions.append(f"criterion:{criterion_key}")

        if topic_code is not None:
            topic_key = str(topic_code)
            if topic_key not in topic_records:
                flags.append(f"{record_id}: unknown topic {topic_key}")
            else:
                unique_activity = str(activity_id or record_id)
                if unique_activity in topic_records[topic_key]:
                    flags.append(
                        f"{record_id}: duplicate topic contribution for {unique_activity} ignored"
                    )
                else:
                    topic_records[topic_key][unique_activity] = record_id
                    contributions.append(f"topic:{topic_key}")

        if not contributions:
            flags.append(f"{record_id}: no recognised criterion or topic contribution")
            continue
        applied_records.append(
            {
                "record_id": record_id,
                "activity_id": activity_id,
                "contributions": contributions,
                "claim_ids": [value for value in (criterion_claim, topic_claim) if value],
            }
        )

    targets = personal_targets or {}
    confirmed_by_criterion: list[dict[str, Any]] = []
    remaining_by_criterion: list[dict[str, Any]] = []
    missing_requirements: list[dict[str, Any]] = []
    confirmed_total: Real = 0

    for raw_code, definition in criteria_by_code.items():
        code = str(raw_code)
        raw_score = sum(points for _, points in score_records[code])
        maximum = definition.get("max_score")
        minimum = definition.get("min_score")
        score: Real = raw_score
        if _is_number(maximum):
            score = min(score, maximum)
        if _is_number(minimum):
            score = max(score, minimum)
        confirmed_total += score

        target = targets.get(code, definition.get("default_target"))
        if target is not None and (not _is_number(target) or target < 0):
            flags.append(f"criterion {code}: target must be a non-negative number")
            target = None
        remaining = max(0, target - score) if _is_number(target) else None
        item = {
            "code": code,
            "raw_score": _clean_number(raw_score),
            "score": _clean_number(score),
            "max_score": maximum,
            "target": target,
            "remaining": _clean_number(remaining) if _is_number(remaining) else None,
            "record_ids": [record_id for record_id, _ in score_records[code]],
        }
        confirmed_by_criterion.append(item)
        remaining_by_criterion.append(
            {"code": code, "target": target, "remaining": item["remaining"]}
        )
        if _is_number(remaining) and remaining > 0:
            missing_requirements.append(
                {"type": "CRITERION_TARGET", "code": code, "remaining": item["remaining"]}
            )

    max_total = rule_set.get("max_total_score")
    min_total = rule_set.get("min_total_score")
    if _is_number(max_total):
        confirmed_total = min(confirmed_total, max_total)
    if _is_number(min_total):
        confirmed_total = max(confirmed_total, min_total)

    topic_progress: list[dict[str, Any]] = []
    for raw_code, definition in topic_by_code.items():
        code = str(raw_code)
        required = definition.get("required_confirmed_activities")
        if not isinstance(required, int) or isinstance(required, bool) or required < 0:
            flags.append(f"topic {code}: required_confirmed_activities must be a non-negative integer")
            required = None
        count = len(topic_records[code])
        remaining = max(0, required - count) if required is not None else None
        topic_progress.append(
            {
                "code": code,
                "confirmed_count": count,
                "required_count": required,
                "remaining": remaining,
                "record_ids": list(topic_records[code].values()),
            }
        )
        if remaining:
            missing_requirements.append(
                {"type": "TOPIC_COUNT", "code": code, "remaining": remaining}
            )

    return {
        "rule_set_id": rule_set.get("rule_set_id"),
        "rule_set_version": rule_set.get("version"),
        "rule_resolution": resolution,
        "confirmed_total": _clean_number(confirmed_total),
        "confirmed_by_criterion": confirmed_by_criterion,
        "pending_items": pending_items,
        "remaining_by_criterion": remaining_by_criterion,
        "topic_progress": topic_progress,
        "missing_requirements": missing_requirements,
        "verification_flags": flags,
        "applied_records": applied_records,
    }


def _progress_rule_set(
    config: Mapping[str, Any], scope: Mapping[str, Any]
) -> dict[str, Any]:
    scoring = config.get("scoring_model", {})
    regulation = config.get("regulation", {})
    if not isinstance(scoring, Mapping) or not isinstance(regulation, Mapping):
        raise DRLEngineError("regulation and scoring_model must be objects")

    criteria: list[dict[str, Any]] = []
    known: set[str] = set()
    for category in scoring.get("category_caps", []):
        if not isinstance(category, Mapping) or category.get("category_id") is None:
            continue
        code = str(category["category_id"])
        known.add(code)
        criteria.append(
            {
                "code": code,
                "name": category.get("name"),
                "max_score": category.get("max_score"),
                "default_target": None,
            }
        )

    for rule in config.get("rules", []):
        if not isinstance(rule, Mapping) or rule.get("category_id") is None:
            continue
        code = str(rule["category_id"])
        if code not in known:
            known.add(code)
            criteria.append(
                {"code": code, "name": code, "max_score": None, "default_target": None}
            )

    verified = (
        str(regulation.get("status", "")).lower() == "verified"
        and str(scoring.get("status", "")).lower() == "verified"
    )
    return {
        "rule_set_id": regulation.get("regulation_id"),
        "version": regulation.get("effective_from") or regulation.get("issued_date"),
        "scope": dict(scope),
        "verified": verified,
        "source_ids": [regulation.get("source")] if regulation.get("source") else [],
        "criteria": criteria,
        "topic_requirements": [],
        "min_total_score": scoring.get("semester_score_min"),
        "max_total_score": scoring.get("max_total_score"),
    }


def evaluate_rules_progress(
    config: Mapping[str, Any],
    student_profile: Mapping[str, Any],
    student_snapshot: Mapping[str, Any],
    *,
    scope: Mapping[str, Any],
    personal_targets: Mapping[str, Real] | None = None,
    required_fields: Iterable[str] = (),
) -> dict[str, Any]:
    """Run the flat rules, then build the normal SP2 progress report."""

    values = student_snapshot.get("values")
    if not isinstance(values, Mapping):
        raise DRLEngineError("student_snapshot.values must be an object")

    base = values.get("current_confirmed_score", 0)
    extras = values.get("eligible_extra_points", 0)
    if (_is_number(base) and base != 0) or (_is_number(extras) and extras != 0):
        raise DRLEngineError(
            "current_confirmed_score and eligible_extra_points need category allocation "
            "before progress calculation"
        )

    rule_set = _progress_rule_set(config, scope)
    status = str(student_snapshot.get("status", "")).upper()
    snapshot_record = {
        "record_id": str(student_snapshot.get("record_id") or "rule-snapshot"),
        "status": status,
        "evidence_status": student_snapshot.get("evidence_status"),
        "evidence_verified": student_snapshot.get("evidence_verified"),
        "evidence": student_snapshot.get("evidence"),
        "evidence_id": student_snapshot.get("evidence_id"),
        "confirmed_by": student_snapshot.get("confirmed_by"),
        "confirmed_at": student_snapshot.get("confirmed_at"),
    }

    if status != "CONFIRMED" or not _evidence_is_verified(snapshot_record):
        report = evaluate_progress(
            rule_set,
            student_profile,
            [snapshot_record],
            personal_targets=personal_targets,
            require_verified_rules=True,
        )
        report["rule_evaluation"] = None
        return report

    rule_result = evaluate_rule_conditions(
        config, values, required_fields=required_fields
    )
    records: list[dict[str, Any]] = []
    for category in rule_result["category_scores"]:
        if category["score"] == 0:
            continue
        records.append(
            {
                "record_id": f"rule-category-{category['category_id']}",
                "status": "CONFIRMED",
                "evidence_status": "VERIFIED",
                "criterion_code": category["category_id"],
                "points": category["score"],
            }
        )

    report = evaluate_progress(
        rule_set,
        student_profile,
        records,
        personal_targets=personal_targets,
        require_verified_rules=True,
    )
    if rule_result["needs_review"]:
        report["verification_flags"].extend(
            f"Missing field: {field}" for field in rule_result["missing_fields"]
        )
        report["verification_flags"].extend(
            f"Skipped rule {item['rule_id']}: {item['reason']}"
            for item in rule_result["skipped_rules"]
        )
        report["verification_flags"].extend(
            f"Rule config: {item['message']}"
            for item in rule_result["relevant_configuration_issues"]
        )
    report["rule_evaluation"] = rule_result
    return report
