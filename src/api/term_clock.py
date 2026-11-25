"""Configured semester bounds and effective simulation clocks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEMESTERS_PATH = ROOT / "data" / "config" / "semesters.json"
TIMEZONE = "Asia/Ho_Chi_Minh"
# Labels live in code (the JSON has ids and dates only). U+00B7 and U+2013 are written as escapes.
TERM_LABELS = {
    "HK3_2025_2026": "HK3 · 2025–2026",
    "HK1_2026_2027": "HK1 · 2026–2027",
}
# The synthetic test scenario (tests/sp3/fixtures/main_flow_integration.json) is not a semester: it has its
# own id and its own clock, and it must never be labelled HK3 or HK1.
SYNTHETIC_TERM_ID = "SYNTHETIC-DEMO"
SYNTHETIC_FIXTURE = ROOT / "tests" / "sp3" / "fixtures" / "main_flow_integration.json"
# Scoreboards and confirmed plans without any stored evidence of their term are kept under this key.
UNASSIGNED_TERM_ID = "_unassigned"


class UnknownTermError(ValueError):
    """The term_id is not one of the configured terms."""


@dataclass(frozen=True)
class TermClock:
    term_id: str
    term_label: str
    term_start: str
    term_end: str
    as_of: str
    window_start: str
    window_end: str
    timezone: str
    clock_version: str

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def utc_offset(self) -> str:
        return self.as_of[-6:]


def _version(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return "clk-" + hashlib.sha256(canonical.encode("ascii")).hexdigest()[:12]


def _build(term_id: str, start: str, end: str, offset: str, as_of: str | None = None) -> TermClock:
    as_of = as_of or f"{start}T00:00:00{offset}"
    # Planning window = [max(term_start, as_of), term_end + 1 day 00:00).
    first = max(datetime.fromisoformat(f"{start}T00:00:00{offset}"), datetime.fromisoformat(as_of))
    last = datetime.fromisoformat(f"{end}T00:00:00{offset}") + timedelta(days=1)
    fields = {
        "term_id": term_id, "term_label": TERM_LABELS.get(term_id, term_id), "term_start": start, "term_end": end,
        "as_of": as_of, "window_start": first.isoformat(), "window_end": last.isoformat(), "timezone": TIMEZONE,
    }
    return TermClock(**fields, clock_version=_version(fields))


@lru_cache(maxsize=1)
def _terms() -> dict[str, TermClock]:
    config = json.loads(SEMESTERS_PATH.read_text(encoding="utf-8"))
    offset = config["timezone"]
    terms = {}
    for item in config["semesters"]:
        start, end = item["programs"]["standard"]  # standard and high_quality share the dates
        date.fromisoformat(start), date.fromisoformat(end)
        terms[item["id"]] = _build(item["id"], start, end, offset)
    return terms


def list_terms() -> list[TermClock]:
    return sorted(_terms().values(), key=lambda clock: clock.term_start)


def get_term(term_id: str | None) -> TermClock:
    clock = _terms().get(term_id) if isinstance(term_id, str) else None
    if clock is None:
        raise UnknownTermError(f"unknown term_id {term_id!r}; expected one of {sorted(_terms())}")
    return clock


def clock_at_date(term: TermClock, value: str) -> TermClock:
    try:
        day = date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("Ngày phải là một ngày hợp lệ theo định dạng YYYY-MM-DD.") from exc
    if day != value:
        raise ValueError("Ngày phải có định dạng YYYY-MM-DD.")
    if not term.term_start <= day <= term.term_end:
        raise ValueError("Ngày phải nằm trong học kỳ đã chọn.")
    return _build(term.term_id, term.term_start, term.term_end, term.utc_offset,
                  f"{day}T23:59:59{term.utc_offset}")


def term_for_date(value: str | None) -> str | None:
    """The term whose bounds contain the date of an ISO timestamp (None when no term does)."""
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    for clock in list_terms():
        if date.fromisoformat(clock.term_start) <= day <= date.fromisoformat(clock.term_end):
            return clock.term_id
    return None


def state_term(term_id: str | None) -> str:
    """The key of term-scoped state: a configured term, or the synthetic test scenario."""
    if term_id == SYNTHETIC_TERM_ID:
        return term_id
    return get_term(term_id).term_id


def synthetic_as_of() -> str:
    fixture = json.loads(SYNTHETIC_FIXTURE.read_text(encoding="utf-8"))
    return fixture["steps"]["step1"]["feasibility_request"]["context"]["as_of"]


def as_of_of(term_id: str) -> str:
    """The simulated now of a state key (a configured term or the synthetic scenario)."""
    return synthetic_as_of() if term_id == SYNTHETIC_TERM_ID else get_term(term_id).as_of
