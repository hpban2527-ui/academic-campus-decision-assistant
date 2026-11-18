"""Instant, deterministic interpretation for explicit Vietnamese preferences.

The supported preference vocabulary is finite.  Clear sentences should not
pay a local-LLM generation cost just to map "Toán", "online" or "mục 4" to
their enum values.  This module handles only high-confidence lexical cases;
ambiguous/comparative wording returns ``None`` so the validated AI provider
can handle it instead.
"""

from __future__ import annotations

import re
import unicodedata

from personalization.models import StudentPreference
from personalization.normalization import (
    _CAMPUS_TERMS,
    _CATEGORY_TERMS,
    _HARD_MARKERS,
    _MINIMUM_EFFORT_TERMS,
    _MODE_TERMS,
    _PREFERENCE_FIRST_TERMS,
    _TIME_TERMS,
    _TOPIC_TERMS,
)


_AMBIGUOUS_MARKERS = (" hơn ", " thay vì ", " so với ", " hoặc ", " tùy ")
_NEGATIVE_PREFERENCE_MARKERS = ("không thích", "không ưu tiên", "ít thích")


def interpret_explicit_preference(text: str) -> StudentPreference | None:
    """Return an immediate contract when every risky cue is explicit.

    ``None`` means "use AI fallback".  This is deliberately conservative for
    comparisons, unsupported numbers and hard constraints outside the known
    campus/mode/time vocabulary.
    """

    normalized = _fold(text)
    if not normalized or any(_contains(normalized, _fold(marker)) for marker in _AMBIGUOUS_MARKERS):
        return None

    hard_campuses = _hard_matches(normalized, _CAMPUS_TERMS, excluded_values={"ONLINE"})
    hard_modes = _hard_matches(normalized, _MODE_TERMS)
    hard_times = _hard_matches(normalized, _TIME_TERMS)

    topic_preferences = _preference_rows(normalized, _TOPIC_TERMS, "topic_id", set())
    category_priorities = _preference_rows(normalized, _CATEGORY_TERMS, "category_id", set())
    campus_preferences = _preference_rows(
        normalized,
        _CAMPUS_TERMS,
        "campus_id",
        hard_campuses,
        excluded_values={"ONLINE"},
    )
    mode_preferences = _preference_rows(normalized, _MODE_TERMS, "mode", hard_modes)
    time_preferences = _preference_rows(normalized, _TIME_TERMS, "time_slot", hard_times)

    max_activities = _numeric_limit(normalized, ("hoat dong", "su kien"))
    duration_value, duration_unit = _numeric_limit_with_unit(normalized, ("phut", "gio", "tieng"))
    max_duration = duration_value * 60 if duration_value is not None and duration_unit in {"gio", "tieng"} else duration_value
    max_fee = 0 if "mien phi" in normalized else _numeric_limit(normalized, ("dong", "vnd", "vnd"))

    strategy = "BALANCED"
    if _contains_any(normalized, _PREFERENCE_FIRST_TERMS):
        strategy = "PREFERENCE_FIRST"
    elif _contains_any(normalized, _MINIMUM_EFFORT_TERMS):
        strategy = "MINIMUM_EFFORT"

    recognized = any((
        topic_preferences,
        category_priorities,
        campus_preferences,
        mode_preferences,
        time_preferences,
        hard_campuses,
        hard_modes,
        hard_times,
        max_activities is not None,
        max_duration is not None,
        max_fee is not None,
        strategy != "BALANCED",
    ))
    if not recognized:
        return None

    # A number or hard-ban phrase that was not mapped is too risky to ignore.
    parsed_numeric = any(value is not None for value in (max_activities, max_duration, max_fee))
    numeric_residue = re.sub(r"\b(?:muc|nhom|c)\s*[1-5]\b", "", normalized)
    if re.search(r"\d", numeric_residue) and not parsed_numeric:
        return None
    has_hard_marker = _contains_any(normalized, _HARD_MARKERS)
    if has_hard_marker and not any((hard_campuses, hard_modes, hard_times)):
        return None

    payload = {
        "topic_preferences": topic_preferences,
        "category_priorities": category_priorities,
        "campus_preferences": campus_preferences,
        "mode_preferences": mode_preferences,
        "time_preferences": time_preferences,
        "limits": {
            "max_activities": max_activities,
            "max_duration_minutes": max_duration,
            "max_fee": max_fee,
        },
        "hard_exclusions": {
            "campus_ids": sorted(hard_campuses),
            "modes": sorted(hard_modes),
            "time_slots": sorted(hard_times),
        },
        "strategy": strategy,
    }
    return StudentPreference.model_validate(payload)


def _preference_rows(
    text: str,
    terms_by_value,
    key: str,
    hard_values: set[str],
    *,
    excluded_values: set[str] | None = None,
) -> list[dict[str, object]]:
    excluded_values = excluded_values or set()
    rows: list[dict[str, object]] = []
    for enum_value, terms in terms_by_value.items():
        value = enum_value.value
        if value in excluded_values or value in hard_values:
            continue
        matched_term = next((_fold(term) for term in terms if _contains(text, _fold(term))), None)
        if matched_term is None:
            continue
        clause = _clause_containing(text, matched_term)
        # "Nếu đi trực tiếp thì thích cơ sở NVC" qualifies the campus choice;
        # it does not state an offline-mode preference.
        if key == "mode" and "neu" in clause and any(
            _contains(clause, _fold(campus_term))
            for campus_terms in _CAMPUS_TERMS.values()
            for campus_term in campus_terms
        ):
            continue
        weight = 1 if any(_fold(marker) in clause for marker in _NEGATIVE_PREFERENCE_MARKERS) else 5
        rows.append({key: value, "weight": weight})
    return rows


def _hard_matches(text: str, terms_by_value, *, excluded_values: set[str] | None = None) -> set[str]:
    excluded_values = excluded_values or set()
    result: set[str] = set()
    clauses = _clauses(text)
    hard_markers = tuple(_fold(marker) for marker in _HARD_MARKERS)
    for enum_value, terms in terms_by_value.items():
        value = enum_value.value
        if value in excluded_values:
            continue
        folded_terms = tuple(_fold(term) for term in terms)
        if any(any(marker in clause for marker in hard_markers) and any(_contains(clause, term) for term in folded_terms) for clause in clauses):
            result.add(value)
    return result


def _numeric_limit(text: str, units: tuple[str, ...]) -> int | None:
    value, _ = _numeric_limit_with_unit(text, units)
    return value


def _numeric_limit_with_unit(text: str, units: tuple[str, ...]) -> tuple[int | None, str | None]:
    unit_pattern = "|".join(re.escape(_fold(unit)) for unit in units)
    marker_pattern = r"(?:toi da|khong qua|nhieu nhat|gioi han|chi)"
    match = re.search(rf"{marker_pattern}[^\d]{{0,40}}(\d[\d\s.,]*)\s*({unit_pattern})\b", text)
    if match is None:
        return None, None
    digits = re.sub(r"\D", "", match.group(1))
    return (int(digits), match.group(2)) if digits else (None, None)


def _clauses(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[.;,!\n]+|\bva\b|\bnhung\b", text) if item.strip()]


def _clause_containing(text: str, term: str) -> str:
    return next((clause for clause in _clauses(text) if _contains(clause, term)), text)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains(text, _fold(term)) for term in terms)


def _contains(text: str, term: str) -> bool:
    if term.isalnum() and len(term) <= 3:
        return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))
    return term in text


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    without_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(without_marks.split())
