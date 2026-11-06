"""Projected whole-set scorer backed by the SP2 rule engine (contract sections 5 and 10.1).

Usage::

    scorer = ProjectedScorer(InMemoryScoringData(payload))
    score_plan = ScorerAdapter(scorer).score_plan

Given a score_request, the scorer resolves trusted data by context (ruleset,
confirmed baseline facts, activity records and activity-to-rule bindings),
applies the selected bindings to a copy of the facts in the request's
``attribution_order``, and runs the SP2 engine on every prefix. Each
activity's contribution is the marginal change in its rule's category, so
per-category contributions sum to the category gains by construction.

Category and total results come from the engine run on the final fact set.
That set does not depend on the order: increments commute, and bindings that
would set one fact to different values (so that the last one wins) produce
NEEDS_REVIEW instead of an order-dependent result.

The scorer is read-only: it never writes to a ledger, session or review queue.
Missing or unverifiable data produce NEEDS_REVIEW; inconsistencies between the
request and the engine produce ERROR. Nothing is assumed to be zero, and the
result is always DEMO_ONLY and unverified.

One instance serves one planning context. Engine evaluations are memoized
inside the instance, keyed by ruleset version and canonical facts; there is
no module-level cache, and a request for another context is rejected. There
is no whole-response cache; one keyed by the selected set alone would be
wrong, because attribution depends on ``attribution_order``.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import json
import math
from typing import Any, Protocol

from sp3.contract import (
    ABS_TOLERANCE,
    ACTIVITY_FIELDS,
    DEMO_MODE,
    ContractError,
    EvaluationStatus,
    copy_json,
    exact_object,
    non_empty_string,
    require,
    validate_score_request,
    within_tolerance,
)

__all__ = [
    "BindingOperation",
    "Engine",
    "InMemoryScoringData",
    "ProjectedScorer",
    "Ruleset",
    "ScoreBinding",
    "ScorerUnavailableError",
    "ScoringDataSource",
]

Engine = Callable[..., Mapping[str, Any]]

# Operators for which adding to a count can only turn a rule on, never off.
_INCREMENT_OPERATORS = frozenset({"count_greater_than", "greater_than", "greater_than_or_equal"})
_SET_OPERATORS = frozenset({"equals", "in"})
_ECHO_FIELDS = ("contract_version", "request_id", "context", "selected_activity_ids")


class ScorerUnavailableError(RuntimeError):
    """The SP2 engine cannot be loaded, so projected scoring is impossible."""


class BindingOperation(str, Enum):
    INCREMENT = "INCREMENT"
    SET = "SET"


@dataclass(frozen=True)
class ScoreBinding:
    """How attending one activity changes one flat SP2 fact.

    The category always comes from the bound rule, never from the binding.
    """

    binding_ref: str
    rule_id: str
    field: str
    operation: BindingOperation
    value: Any

    def __post_init__(self) -> None:
        for name in ("binding_ref", "rule_id", "field"):
            non_empty_string(getattr(self, name), "binding." + name)
        require(isinstance(self.operation, BindingOperation), "binding.operation", "must be a BindingOperation")
        if self.operation is BindingOperation.INCREMENT:
            require(
                type(self.value) in (int, float) and math.isfinite(self.value) and self.value > 0,
                "binding.value", "INCREMENT requires a finite positive number",
            )
        else:
            require(type(self.value) in (str, int, float, bool), "binding.value", "SET requires a JSON scalar")


@dataclass(frozen=True)
class Ruleset:
    version: str
    config: Mapping[str, Any]


class ScoringDataSource(Protocol):
    """Trusted, read-only data resolved by context; None means unavailable."""

    def ruleset(self, context: Mapping[str, Any]) -> Ruleset | None: ...

    def baseline_facts(self, context: Mapping[str, Any]) -> Mapping[str, Any] | None: ...

    def activity(self, context: Mapping[str, Any], activity_id: str) -> Mapping[str, Any] | None: ...

    def binding(self, context: Mapping[str, Any], activity_id: str) -> ScoreBinding | None: ...


class InMemoryScoringData:
    """Validated, immutable ScoringDataSource built from a JSON-compatible dict.

    Intended for tests and the demo until a stored-data source exists. Keys:
    ``label``, ``dataset_version``, ``ruleset_version``, ``ruleset`` (the
    drl_rules.json object), ``baselines`` ([{student_id, baseline_ref,
    facts}]), ``activities`` (14-field records) and ``bindings``
    ([{activity_id, binding_ref, rule_id, field, operation, value}]).
    Lookups for another dataset/ruleset version, student or baseline return
    None. Every lookup returns a detached copy.
    """

    _FIELDS = frozenset({"label", "dataset_version", "ruleset_version", "ruleset", "baselines", "activities", "bindings"})
    _BASELINE_FIELDS = frozenset({"student_id", "baseline_ref", "facts"})
    _BINDING_FIELDS = frozenset({"activity_id", "binding_ref", "rule_id", "field", "operation", "value"})

    def __init__(self, payload: Mapping[str, Any]) -> None:
        data = exact_object(deepcopy(payload), self._FIELDS, "data")
        self.label = non_empty_string(data["label"], "data.label")
        self._dataset_version = non_empty_string(data["dataset_version"], "data.dataset_version")
        self._ruleset_version = non_empty_string(data["ruleset_version"], "data.ruleset_version")
        ruleset = data["ruleset"]
        require(isinstance(ruleset, dict) and isinstance(ruleset.get("rules"), list) and isinstance(ruleset.get("scoring_model"), dict), "data.ruleset", "must contain rules and scoring_model")
        self._ruleset = ruleset
        self._baselines = self._index(data["baselines"], "data.baselines", self._parse_baseline)
        self._activities = self._index(data["activities"], "data.activities", self._parse_activity)
        self._bindings = self._index(data["bindings"], "data.bindings", self._parse_binding)

    @staticmethod
    def _index(items: Any, path: str, parse: Callable[[Any, str], tuple[Any, Any]]) -> dict[Any, Any]:
        require(isinstance(items, list), path, "must be an array")
        index: dict[Any, Any] = {}
        for position, item in enumerate(items):
            key, value = parse(item, f"{path}[{position}]")
            require(key not in index, path, "keys must be unique")
            index[key] = value
        return index

    def _parse_baseline(self, item: Any, path: str) -> tuple[tuple[str, str], dict[str, Any]]:
        exact_object(item, self._BASELINE_FIELDS, path)
        key = (non_empty_string(item["student_id"], path + ".student_id"), non_empty_string(item["baseline_ref"], path + ".baseline_ref"))
        facts = item["facts"]
        require(isinstance(facts, dict), path + ".facts", "must be an object")
        require(_canonical(facts) is not None, path + ".facts", "must be JSON-compatible")
        return key, facts

    @staticmethod
    def _parse_activity(item: Any, path: str) -> tuple[str, dict[str, Any]]:
        exact_object(item, ACTIVITY_FIELDS, path)
        return non_empty_string(item["activity_id"], path + ".activity_id"), item

    def _parse_binding(self, item: Any, path: str) -> tuple[str, ScoreBinding]:
        exact_object(item, self._BINDING_FIELDS, path)
        activity_id = non_empty_string(item["activity_id"], path + ".activity_id")
        try:
            operation = BindingOperation(item["operation"])
        except (ValueError, TypeError):
            raise ContractError(path + ".operation", "unsupported binding operation") from None
        try:
            binding = ScoreBinding(item["binding_ref"], item["rule_id"], item["field"], operation, item["value"])
        except ContractError as error:
            raise ContractError(path + error.path.removeprefix("binding"), error.problem) from None
        return activity_id, binding

    def ruleset(self, context: Mapping[str, Any]) -> Ruleset | None:
        if context.get("ruleset_version") != self._ruleset_version:
            return None
        return Ruleset(self._ruleset_version, deepcopy(self._ruleset))

    def baseline_facts(self, context: Mapping[str, Any]) -> Mapping[str, Any] | None:
        facts = self._baselines.get((context.get("student_id"), context.get("baseline_ref")))
        return None if facts is None else deepcopy(facts)

    def activity(self, context: Mapping[str, Any], activity_id: str) -> Mapping[str, Any] | None:
        if context.get("dataset_version") != self._dataset_version:
            return None
        record = self._activities.get(activity_id)
        return None if record is None else deepcopy(record)

    def binding(self, context: Mapping[str, Any], activity_id: str) -> ScoreBinding | None:
        if context.get("dataset_version") != self._dataset_version:
            return None
        return self._bindings.get(activity_id)


@dataclass(frozen=True)
class _EngineRun:
    category_scores: Mapping[str, int | float]
    final_score: int | float
    issues: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _ContextData:
    ruleset: Ruleset
    rules: Mapping[str, Mapping[str, Any]]
    category_caps: Mapping[str, Any]
    max_total_score: Any
    facts: Mapping[str, Any]


@dataclass(frozen=True)
class _Selected:
    activity_id: str
    binding: ScoreBinding
    category_id: str


class _Outcome(Exception):
    """Internal control flow: stop scoring with a non-OK status."""

    def __init__(self, status: EvaluationStatus, issues: list[dict[str, Any]]) -> None:
        super().__init__(status.value)
        self.status = status
        self.issues = issues


def _issue(code: str, message: str, activity_id: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "activity_id": activity_id}


def _review(code: str, message: str, activity_id: str | None = None) -> _Outcome:
    return _Outcome(EvaluationStatus.NEEDS_REVIEW, [_issue(code, message, activity_id)])


def _error(code: str, message: str) -> _Outcome:
    return _Outcome(EvaluationStatus.ERROR, [_issue(code, message)])


def _canonical(facts: Mapping[str, Any]) -> str | None:
    try:
        return json.dumps(facts, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None


def _clean(value: int | float) -> int | float:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _default_engine() -> Engine:
    try:
        from sp2.drl_engine import evaluate_rule_conditions
    except ImportError as error:
        raise ScorerUnavailableError("sp2.drl_engine cannot be imported; projected scoring is unavailable.") from error
    return evaluate_rule_conditions


class ProjectedScorer:
    """Section-5 backend for ScorerAdapter using the SP2 engine and rules.

    ``engine`` has the signature of ``sp2.drl_engine.evaluate_rule_conditions``
    and defaults to it; if SP2 cannot be imported, construction fails rather
    than falling back to anything else.
    """

    def __init__(self, data: ScoringDataSource, *, engine: Engine | None = None) -> None:
        self._engine = _default_engine() if engine is None else engine
        if not callable(self._engine):
            raise TypeError("engine must be callable")
        self._data = data
        self._context: dict[str, Any] | None = None
        self._context_data: _ContextData | None = None
        self._memo: dict[tuple[str, str], _EngineRun] = {}
        self._selected: dict[str, _Selected] = {}
        self.engine_calls = 0

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        validate_score_request(request)
        try:
            result = self._score(request)
        except _Outcome as outcome:
            return self._envelope(request, outcome.status, None, outcome.issues)
        return self._envelope(request, EvaluationStatus.OK, result, [])

    @staticmethod
    def _envelope(request: Mapping[str, Any], status: EvaluationStatus, result: Any, errors: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            **{key: copy_json(request[key]) for key in _ECHO_FIELDS},
            "evaluation_status": status.value,
            "result": result,
            "errors": errors,
            "mode": DEMO_MODE,
            "official_award_verified": False,
        }

    # Orchestration

    def _score(self, request: Mapping[str, Any]) -> dict[str, Any]:
        self._bind_context(request["context"])
        data = self._resolve_context(request["context"])
        baseline = request["baseline"]
        self._check_caps(data, baseline)
        selected = self._resolve_selected(request, data)
        self._check_order_independent(selected)
        base_run = self._run(data.ruleset, dict(data.facts), activity_id=None)
        self._check_baseline(base_run, baseline)
        contributions, final_run = self._attribute(data, selected, base_run, baseline)
        return self._result(baseline, final_run, contributions)

    def _bind_context(self, context: Mapping[str, Any]) -> None:
        if self._context is None:
            self._context = deepcopy(dict(context))
        elif context != self._context:
            raise _error("CONTEXT_MISMATCH", "This scorer instance is bound to a different planning context.")

    def _resolve_context(self, context: Mapping[str, Any]) -> _ContextData:
        if self._context_data is not None:
            return self._context_data
        ruleset = self._data.ruleset(context)
        if ruleset is None:
            raise _review("MISSING_RULESET", "No trusted ruleset is available for this context.")
        if ruleset.version != context["ruleset_version"]:
            raise _error("RULESET_VERSION_MISMATCH", "The resolved ruleset version differs from the context.")
        facts = self._data.baseline_facts(context)
        if facts is None:
            raise _review("MISSING_BASELINE_FACTS", "No confirmed baseline facts are available for this baseline_ref.")
        facts = deepcopy(dict(facts))
        if _canonical(facts) is None:
            raise _error("INVALID_BASELINE_FACTS", "Baseline facts are not JSON-compatible.")
        config = deepcopy(dict(ruleset.config))
        scoring = config.get("scoring_model")
        rules = config.get("rules")
        if not isinstance(scoring, Mapping) or not isinstance(rules, list):
            raise _error("INVALID_RULESET", "The ruleset has no rules or scoring_model.")
        caps = {
            str(item.get("category_id")): item.get("max_score")
            for item in scoring.get("category_caps", [])
            if isinstance(item, Mapping)
        }
        self._context_data = _ContextData(
            ruleset=Ruleset(ruleset.version, config),
            rules={str(rule.get("rule_id")): rule for rule in rules if isinstance(rule, Mapping)},
            category_caps=caps,
            max_total_score=scoring.get("max_total_score"),
            facts=facts,
        )
        return self._context_data

    @staticmethod
    def _check_caps(data: _ContextData, baseline: Mapping[str, Any]) -> None:
        caps = baseline["category_caps"]
        consistent = (
            caps.keys() == data.category_caps.keys()
            and all(_is_number(data.category_caps[c]) and within_tolerance(data.category_caps[c], caps[c]) for c in caps)
            and _is_number(data.max_total_score)
            and within_tolerance(data.max_total_score, baseline["max_total_score"])
        )
        if not consistent:
            raise _error("CAP_MISMATCH", "Request caps differ from the ruleset's category caps or max total score.")

    # Selected activities and bindings

    def _resolve_selected(self, request: Mapping[str, Any], data: _ContextData) -> list[_Selected]:
        context, categories = request["context"], request["baseline"]["category_scores"]
        selected: list[_Selected] = []
        issues: list[dict[str, Any]] = []
        for activity_id in request["selected_activity_ids"]:
            # Resolved bindings depend only on the bound context, so they are reused.
            item = self._selected.get(activity_id)
            if item is None:
                try:
                    item = self._resolve_one(context, activity_id, data, categories)
                except _Outcome as outcome:
                    issues.extend(outcome.issues)
                    continue
                self._selected[activity_id] = item
            selected.append(item)
        if issues:
            raise _Outcome(EvaluationStatus.NEEDS_REVIEW, issues)
        by_id = {item.activity_id: item for item in selected}
        return [by_id[activity_id] for activity_id in request["attribution_order"]]

    def _resolve_one(self, context: Mapping[str, Any], activity_id: str, data: _ContextData, categories: Mapping[str, Any]) -> _Selected:
        # The record must exist, but its start/end are not used: the planner
        # supplies the order, and a multi-session activity may have no start.
        activity = self._data.activity(context, activity_id)
        if activity is None or activity.get("activity_id") != activity_id:
            raise _review("MISSING_ACTIVITY", "No trusted activity record is available.", activity_id)
        binding = self._data.binding(context, activity_id)
        if binding is None:
            raise _review("MISSING_BINDING", "No trusted activity-to-rule binding is available.", activity_id)
        rule = data.rules.get(binding.rule_id)
        if rule is None:
            raise _review("UNKNOWN_RULE", f"Rule {binding.rule_id} is not in the ruleset.", activity_id)
        if rule.get("status") != "verified":
            raise _review("UNVERIFIED_RULE", f"Rule {binding.rule_id} is not reviewer-verified.", activity_id)
        condition = rule.get("condition") if isinstance(rule.get("condition"), Mapping) else {}
        if condition.get("field") != binding.field:
            raise _review("BINDING_FIELD_MISMATCH", f"The binding field differs from rule {binding.rule_id}.", activity_id)
        allowed = _INCREMENT_OPERATORS if binding.operation is BindingOperation.INCREMENT else _SET_OPERATORS
        if condition.get("operator") not in allowed:
            raise _review("UNSUPPORTED_BINDING_OPERATION", f"{binding.operation.value} is not supported for rule {binding.rule_id}.", activity_id)
        category_id = str(rule.get("category_id"))
        if category_id not in categories:
            raise _review("UNSUPPORTED_CATEGORY", f"Rule {binding.rule_id} scores a category outside the baseline.", activity_id)
        if binding.operation is BindingOperation.INCREMENT and not _is_number(data.facts.get(binding.field)):
            raise _review("MISSING_BASELINE_FACT", f"Baseline fact {binding.field} is missing or not numeric.", activity_id)
        return _Selected(activity_id, binding, category_id)

    @staticmethod
    def _check_order_independent(selected: list[_Selected]) -> None:
        """Reject bindings whose final fact value would depend on the attribution order.

        Increments commute. A SET is order-independent only when every other
        binding on the same field is a SET to the same value.
        """
        by_field: dict[str, list[_Selected]] = {}
        for item in selected:
            by_field.setdefault(item.binding.field, []).append(item)
        issues = []
        for field, items in sorted(by_field.items()):
            operations = {item.binding.operation for item in items}
            if BindingOperation.SET not in operations or len(items) == 1:
                continue
            values = {_canonical({"value": item.binding.value}) for item in items}
            if operations != {BindingOperation.SET} or len(values) > 1:
                issues.extend(
                    _issue("ORDER_DEPENDENT_BINDINGS", f"Bindings on fact {field} conflict, so the result would depend on the attribution order.", item.activity_id)
                    for item in sorted(items, key=lambda item: item.activity_id)
                )
        if issues:
            raise _Outcome(EvaluationStatus.NEEDS_REVIEW, issues)

    # Engine runs

    def _run(self, ruleset: Ruleset, facts: dict[str, Any], *, activity_id: str | None) -> _EngineRun:
        canonical = _canonical(facts)
        if canonical is None:
            raise _error("INVALID_FACTS", "Projected facts are not JSON-compatible.")
        key = (ruleset.version, canonical)
        run = self._memo.get(key)
        if run is None:
            self.engine_calls += 1
            try:
                raw = self._engine(ruleset.config, deepcopy(facts))
            except Exception:
                # Engine messages may embed configuration or record details.
                raise _error("SP2_ENGINE_FAILURE", "The SP2 engine failed; check engine diagnostics.") from None
            run = self._summarize(raw)
            self._memo[key] = run
        if run.issues:
            raise _Outcome(EvaluationStatus.NEEDS_REVIEW, [_issue(code, message, activity_id) for code, message in run.issues])
        return run

    @staticmethod
    def _summarize(raw: Any) -> _EngineRun:
        try:
            scores: dict[str, int | float] = {}
            for item in raw["category_scores"]:
                category, score = str(item["category_id"]), item["score"]
                if category in scores or not _is_number(score):
                    raise ValueError
                scores[category] = score
            final_score = raw["final_score"]
            if not _is_number(final_score):
                raise ValueError
            issues = [("SP2_MISSING_FIELD", f"Required fact {field} is missing.") for field in raw["missing_fields"]]
            issues += [("SP2_RULE_SKIPPED", f"Rule {item['rule_id']} was skipped: {item['reason']}.") for item in raw["skipped_rules"]]
            issues += [
                ("SP2_RULE_CONFIGURATION", f"Rule configuration issue {item['code']} at {item['path']}.")
                for item in raw.get("relevant_configuration_issues", [])
            ]
            if raw["needs_review"] and not issues:
                issues.append(("SP2_NEEDS_REVIEW", "The SP2 engine flagged this evaluation for review."))
        except (KeyError, TypeError, ValueError):
            raise _error("SP2_ENGINE_OUTPUT_INVALID", "The SP2 engine returned an unexpected result shape.") from None
        return _EngineRun(scores, final_score, tuple(issues))

    # Consistency checks and attribution

    @staticmethod
    def _check_unsupported_categories(run: _EngineRun, categories: Iterable[str], activity_id: str | None) -> None:
        known = set(categories)
        if any(c not in known and abs(score) > ABS_TOLERANCE for c, score in run.category_scores.items()):
            raise _review("UNSUPPORTED_CATEGORY", "The engine produced a non-zero score in a category outside the baseline.", activity_id)

    def _check_baseline(self, run: _EngineRun, baseline: Mapping[str, Any]) -> None:
        scores = baseline["category_scores"]
        self._check_unsupported_categories(run, scores, None)
        if not all(within_tolerance(run.category_scores.get(c, 0), scores[c]) for c in scores):
            raise _error("BASELINE_MISMATCH", "Engine category scores for the baseline facts differ from the request baseline.")
        if not within_tolerance(run.final_score, baseline["total_score"]):
            raise _error("TOTAL_SEMANTICS_MISMATCH", "The engine total for the baseline differs from the contract total.")

    def _attribute(
        self,
        data: _ContextData,
        selected: list[_Selected],
        base_run: _EngineRun,
        baseline: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], _EngineRun]:
        """Apply bindings cumulatively and attribute each marginal change."""
        categories = baseline["category_scores"]
        facts = dict(data.facts)
        previous = base_run
        contributions = []
        for item in selected:
            facts = self._apply(facts, item)
            run = self._run(data.ruleset, facts, activity_id=item.activity_id)
            self._check_unsupported_categories(run, categories, item.activity_id)
            changed = set(run.category_scores) | set(previous.category_scores)
            deltas = {c: run.category_scores.get(c, 0) - previous.category_scores.get(c, 0) for c in changed}
            own = deltas.get(item.category_id, 0)
            if own < -ABS_TOLERANCE or any(abs(d) > ABS_TOLERANCE for c, d in deltas.items() if c != item.category_id):
                raise _review(
                    "UNSUPPORTED_RULE_INTERACTION",
                    "Adding this activity changes scores outside its rule's category or lowers a score.",
                    item.activity_id,
                )
            contributions.append({
                "activity_id": item.activity_id,
                "category_id": item.category_id,
                "rule_id": item.binding.rule_id,
                "projected_added": _clean(max(own, 0)),
            })
            previous = run
        return contributions, previous

    @staticmethod
    def _apply(facts: dict[str, Any], item: _Selected) -> dict[str, Any]:
        updated = dict(facts)
        binding = item.binding
        if binding.operation is BindingOperation.INCREMENT:
            current = updated.get(binding.field)
            if not _is_number(current):
                raise _review("MISSING_BASELINE_FACT", f"Fact {binding.field} is missing or not numeric.", item.activity_id)
            updated[binding.field] = current + binding.value
        else:
            updated[binding.field] = binding.value
        return updated

    @staticmethod
    def _result(baseline: Mapping[str, Any], final_run: _EngineRun, contributions: list[dict[str, Any]]) -> dict[str, Any]:
        before = baseline["category_scores"]
        after = {c: _clean(final_run.category_scores.get(c, 0)) for c in before}
        total_after = _clean(min(math.fsum(after.values()), baseline["max_total_score"]))
        if not within_tolerance(final_run.final_score, total_after):
            raise _error("TOTAL_SEMANTICS_MISMATCH", "The engine total differs from the contract total for this plan.")
        return {
            "category_after": after,
            "category_gain": {c: _clean(after[c] - before[c]) for c in before},
            "total_after": total_after,
            "total_gain": _clean(total_after - baseline["total_score"]),
            "contributions": contributions,
        }

