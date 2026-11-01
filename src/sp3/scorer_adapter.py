"""Planner-side boundary for the sp3-planner/0.1 projected scorer.

Usage: ``score_plan = ScorerAdapter(projected_backend).score_plan``.
The synchronous backend receives the complete score_request and returns the
complete score_response from section 5 of SP3_PLANNER_CONTRACT_V0_1.md.
It must resolve trusted snapshots/bindings, verify student/ruleset scope and
baseline history, and score the whole set without persistent writes. This
module checks consistency, NOT the authenticity of references or rule math.

Malformed requests raise ScorerContractError before calling the backend.
Backend failures/malformed responses become ERROR envelopes without exception
text. Structured backend error messages must already be safe for display.
NEEDS_DATA is the only extra backend status accepted: it becomes NEEDS_REVIEW.

Contribution attribution (start time, then ID) belongs to SP2: this request
contains no activity schedules. The adapter preserves that ordering and checks
coverage and sums. No search, caching, single-activity scoring, or score writes
occur here. Requests and responses are detached copies; the injected backend
must itself honor the read-only contract for any external state it accesses.

JSON numbers only (int/float, never bool), finite and non-negative. Bounds are
strict; arithmetic equalities allow only an absolute 1e-9-point float error
(no relative tolerance). Values are never rounded, clamped, or repaired.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
import re
from typing import Any, Protocol

CONTRACT_VERSION = "sp3-planner/0.1"
_ABS_TOLERANCE = 1e-9
_REQUEST_FIELDS = {
    "contract_version", "request_id", "context", "baseline", "selected_activity_ids",
}
_CONTEXT_FIELDS = {
    "student_id", "term_id", "window_start", "window_end", "as_of", "timezone",
    "baseline_ref", "dataset_version", "ruleset_version", "calendar_version",
}
_BASELINE_FIELDS = {
    "category_scores", "category_caps", "total_score", "max_total_score",
    "included_activity_ids",
}
_RESPONSE_FIELDS = (_REQUEST_FIELDS - {"baseline"}) | {
    "evaluation_status", "result", "errors", "mode", "official_award_verified",
}
_RESULT_FIELDS = {
    "category_after", "category_gain", "total_after", "total_gain", "contributions",
}


class ScorerContractError(ValueError):
    """Invalid score_request; path/message describe structure, never raw data."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


class ProjectedScorer(Protocol):
    """Trusted, read-only whole-set backend; not a snapshot/single-event API."""

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]: ...


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ScorerContractError(path, message)


def _object(value: Any, fields: set[str], path: str) -> dict[str, Any]:
    _require(isinstance(value, dict), path, "must be an object")
    _require(set(value) == fields, path, "missing required or unexpected fields")
    return value


def _string(value: Any, path: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), path, "must be a non-empty string")
    return value


def _number(value: Any, path: str) -> int | float:
    _require(type(value) in (int, float), path, "must be a JSON number, not a boolean")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite and value >= 0, path, "must be finite and non-negative")
    return value


def _sum(values, path: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError):
        raise ScorerContractError(path, "aggregate exceeds finite numeric range") from None
    _require(math.isfinite(result), path, "aggregate must be finite")
    return result


def _equal(actual: int | float, expected: int | float, path: str) -> None:
    _require(
        math.isclose(actual, expected, rel_tol=0, abs_tol=_ABS_TOLERANCE),
        path, "inconsistent arithmetic",
    )


def _score_map(value: Any, path: str) -> dict[str, int | float]:
    _require(isinstance(value, dict) and bool(value), path, "must be a non-empty score map")
    for key, score in value.items():
        _string(key, path + ".category_id")
        _number(score, path + ".score")
    return value


def _ids(value: Any, path: str, *, ordered: bool = False) -> list[str]:
    _require(isinstance(value, list), path, "must be an array")
    for identifier in value:
        _string(identifier, path + "[]")
    _require(len(value) == len(set(value)), path, "IDs must be unique")
    if ordered:
        _require(value == sorted(value), path, "IDs must be lexicographically sorted")
    return value


def _timestamp(value: Any, path: str) -> datetime:
    _string(value, path)
    _require(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value) is not None,
        path, "must be an ISO 8601 timestamp with an explicit offset",
    )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ScorerContractError(path, "invalid timestamp") from None


def _validate_request(request: Any) -> None:
    _object(request, _REQUEST_FIELDS, "request")
    _require(request["contract_version"] == CONTRACT_VERSION, "request.contract_version", "unsupported version")
    _string(request["request_id"], "request.request_id")
    context = _object(request["context"], _CONTEXT_FIELDS, "request.context")
    for name, value in context.items():
        _string(value, "request.context." + name)
    _require(context["timezone"] == "Asia/Ho_Chi_Minh", "request.context.timezone", "unsupported timezone")
    start, end, as_of = (
        _timestamp(context[key], "request.context." + key)
        for key in ("window_start", "window_end", "as_of")
    )
    _require(start < end and as_of <= end, "request.context", "invalid planning window or as_of")
    baseline = _object(request["baseline"], _BASELINE_FIELDS, "request.baseline")
    scores = _score_map(baseline["category_scores"], "request.baseline.category_scores")
    caps = _score_map(baseline["category_caps"], "request.baseline.category_caps")
    _require(scores.keys() == caps.keys(), "request.baseline", "score and cap categories must match")
    _require(all(scores[key] <= caps[key] for key in scores), "request.baseline", "category score exceeds its cap")
    total = _number(baseline["total_score"], "request.baseline.total_score")
    cap = _number(baseline["max_total_score"], "request.baseline.max_total_score")
    _require(total <= cap, "request.baseline.total_score", "exceeds total cap")
    _equal(total, min(_sum(scores.values(), "request.baseline"), cap), "request.baseline.total_score")
    included = _ids(baseline["included_activity_ids"], "request.baseline.included_activity_ids")
    selected = _ids(request["selected_activity_ids"], "request.selected_activity_ids", ordered=True)
    _require(set(included).isdisjoint(selected), "request.selected_activity_ids", "contains an already-counted activity")


def _validate_response(response: Any, request: dict[str, Any]) -> None:
    _object(response, _RESPONSE_FIELDS, "response")
    for key in ("contract_version", "request_id", "context", "selected_activity_ids"):
        _require(response[key] == request[key], "response." + key, "does not match the request")
    _require(response["mode"] == "DEMO_ONLY", "response.mode", "must remain DEMO_ONLY")
    _require(response["official_award_verified"] is False, "response.official_award_verified", "must be false")
    status = response["evaluation_status"]
    _require(isinstance(status, str) and status in ("OK", "NEEDS_REVIEW", "NEEDS_DATA", "ERROR"), "response.evaluation_status", "unsupported status")
    errors = response["errors"]
    _require(isinstance(errors, list), "response.errors", "must be an array")
    selected = request["selected_activity_ids"]
    for issue in errors:
        _object(issue, {"code", "message", "activity_id"}, "response.errors[]")
        _string(issue["code"], "response.errors[].code")
        _require(re.fullmatch(r"[A-Z][A-Z0-9_]*", issue["code"]) is not None, "response.errors[].code", "must be an uppercase reason code")
        _string(issue["message"], "response.errors[].message")
        activity_id = issue["activity_id"]
        _require(activity_id is None or (isinstance(activity_id, str) and activity_id in selected), "response.errors[].activity_id", "must reference a selected activity or be null")
    if status != "OK":
        _require(response["result"] is None and bool(errors), "response", "non-OK results require null result and at least one error")
        return
    _require(not errors, "response.errors", "OK responses must not contain errors")
    result = _object(response["result"], _RESULT_FIELDS, "response.result")
    after = _score_map(result["category_after"], "response.result.category_after")
    gain = _score_map(result["category_gain"], "response.result.category_gain")
    baseline = request["baseline"]
    before, caps = baseline["category_scores"], baseline["category_caps"]
    _require(after.keys() == gain.keys() == before.keys(), "response.result", "categories must exactly match the baseline")
    for category in before:
        _require(before[category] <= after[category] <= caps[category], "response.result.category_after", "category score decreased or exceeds its cap")
        _equal(gain[category], after[category] - before[category], "response.result.category_gain")
    total_after = _number(result["total_after"], "response.result.total_after")
    total_gain = _number(result["total_gain"], "response.result.total_gain")
    _require(baseline["total_score"] <= total_after <= baseline["max_total_score"], "response.result.total_after", "total decreased or exceeds its cap")
    _equal(total_after, min(_sum(after.values(), "response.result"), baseline["max_total_score"]), "response.result.total_after")
    _equal(total_gain, total_after - baseline["total_score"], "response.result.total_gain")
    contributions = result["contributions"]
    _require(isinstance(contributions, list), "response.result.contributions", "must be an array")
    seen: set[str] = set()
    per_category: dict[str, list[int | float]] = {category: [] for category in before}
    for item in contributions:
        _object(item, {"activity_id", "category_id", "rule_id", "projected_added"}, "response.result.contributions[]")
        activity_id = _string(item["activity_id"], "response.result.contributions[].activity_id")
        _require(activity_id in selected and activity_id not in seen, "response.result.contributions", "must cover each selected activity exactly once")
        seen.add(activity_id)
        category = _string(item["category_id"], "response.result.contributions[].category_id")
        _require(category in before, "response.result.contributions[].category_id", "unknown category")
        _string(item["rule_id"], "response.result.contributions[].rule_id")
        per_category[category].append(_number(item["projected_added"], "response.result.contributions[].projected_added"))
    _require(seen == set(selected), "response.result.contributions", "missing selected activities")
    for category in before:
        _equal(_sum(per_category[category], "response.result.contributions"), gain[category], "response.result.contributions")
    if not selected:
        _require(
            after == before and all(value == 0 for value in gain.values())
            and total_after == baseline["total_score"] and total_gain == 0,
            "response.result", "the empty set must leave the baseline unchanged",
        )


def _failure(request: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        **{key: deepcopy(request[key]) for key in ("contract_version", "request_id", "context", "selected_activity_ids")},
        "evaluation_status": "ERROR",
        "result": None,
        "errors": [{"code": code, "message": message, "activity_id": None}],
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
    }


class ScorerAdapter:
    """Inject a trusted synchronous projected backend; no default/fake scorer.

    ``adapter.score_plan`` is the callback for the future planner. The backend
    must resolve baseline_ref and selected IDs to trusted state, enforce scope,
    and return the section-5 envelope, including attribution. A match of echoed
    version strings does not establish the validity of a baseline or binding.
    """

    def __init__(self, projected_backend: ProjectedScorer) -> None:
        if not callable(projected_backend):
            raise TypeError("projected_backend must be callable")
        self._backend = projected_backend

    def score_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate, delegate once, and validate the detached projected result.

        Invalid requests raise ScorerContractError; backend failures return an
        ERROR response. All backend errors must use safe, structured messages.
        Backend mutation affects only its copy; validation uses the original
        snapshot, and returned objects do not alias the backend or the caller.
        """
        _validate_request(request)
        snapshot = deepcopy(request)
        try:
            raw_response = self._backend(deepcopy(snapshot))
        except Exception:
            # Exception text may contain credentials, URLs, or private records.
            return _failure(snapshot, "SP2_BACKEND_FAILURE", "Projected scorer failed; check backend diagnostics.")
        try:
            response = deepcopy(raw_response)
            _validate_response(response, snapshot)
        except ScorerContractError as error:
            return _failure(snapshot, "SP2_INVALID_RESPONSE", str(error))
        except Exception:
            return _failure(snapshot, "SP2_INVALID_RESPONSE", "Projected scorer returned an unreadable response.")
        if response["evaluation_status"] == "NEEDS_DATA":
            response["evaluation_status"] = "NEEDS_REVIEW"
            if not any(issue["code"] == "SP2_NEEDS_DATA" for issue in response["errors"]):
                response["errors"].insert(0, {
                    "code": "SP2_NEEDS_DATA",
                    "message": "Projected scoring requires additional trusted data.",
                    "activity_id": None,
                })
        return response
