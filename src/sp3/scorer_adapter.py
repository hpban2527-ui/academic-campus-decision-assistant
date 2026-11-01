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
from typing import Any, Protocol

from sp3.contract import (
    CONTRACT_VERSION,
    ContractError,
    validate_score_request,
    validate_score_response,
)

__all__ = ["CONTRACT_VERSION", "ProjectedScorer", "ScorerAdapter", "ScorerContractError"]

# NEEDS_DATA is accepted from the backend only to be normalized below.
_BACKEND_STATUSES = ("OK", "NEEDS_REVIEW", "NEEDS_DATA", "ERROR")


class ScorerContractError(ContractError):
    """Invalid score_request; path/message describe structure, never raw data."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(path, message)


class ProjectedScorer(Protocol):
    """Trusted, read-only whole-set backend; not a snapshot/single-event API."""

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]: ...


def _validate_request(request: Any) -> None:
    try:
        validate_score_request(request, "request")
    except ContractError as error:
        raise ScorerContractError(error.path, error.problem) from None


def _validate_response(response: Any, request: dict[str, Any]) -> None:
    validate_score_response(response, request, allowed_statuses=_BACKEND_STATUSES, path="response")


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
        except ContractError as error:
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
