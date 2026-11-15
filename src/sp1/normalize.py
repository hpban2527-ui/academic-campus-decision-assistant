"""Apply SP1 v2 team rules to an already structured layer-A record."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .dates import DEFAULT_END, DEFAULT_START, TZ_SUFFIX

NORMALIZER_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = ("standard", "high_quality")
CAMPUSES = ("CS1", "CS2")
INFORMATIONAL_FLAGS = {"location_dropped_online", "campus_unknown"}


class ConfigError(ValueError):
    """A normaliser configuration is invalid or ambiguous."""


@dataclass(frozen=True)
class Config:
    semesters: dict[str, tuple[tuple[date, date, str], ...]]
    campuses: dict[str, tuple[str, ...]]
    semester_version: str
    campus_version: str


def _has_token(text: str, pattern: str) -> bool:
    """Pattern occurs as whole tokens: "cơ sở 2" must not match inside "cơ sở 227"."""
    return re.search(r"(?<!\w)" + re.escape(pattern) + r"(?!\w)", text) is not None


def _location_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def load_config(root: Path | None = None) -> Config:
    """Load repository configuration and reject overlapping inclusive bounds."""
    directory = (ROOT if root is None else Path(root)) / "data" / "config"
    try:
        semesters = json.loads((directory / "semesters.json").read_text(encoding="utf-8"))
        campus = json.loads((directory / "campus_dictionary.json").read_text(encoding="utf-8"))
        if semesters["timezone"] != TZ_SUFFIX or semesters["bounds"] != "inclusive":
            raise ConfigError("Semester config requires inclusive +07:00 bounds")
        windows = {}
        for program in PROGRAMS:
            periods = []
            for semester in semesters["semesters"]:
                start, end = map(date.fromisoformat, semester["programs"][program])
                if start > end:
                    raise ConfigError(f"Reversed semester bounds for {program}: {semester['id']}")
                periods.append((start, end, semester["id"]))
            periods.sort()
            for (_, previous_end, previous_id), (start, _, next_id) in zip(periods, periods[1:]):
                if start <= previous_end:
                    raise ConfigError(f"Overlapping semesters for {program}: {previous_id}, {next_id}")
            windows[program] = tuple(periods)
        patterns = {
            key: tuple(_location_key(pattern) for pattern in campus["patterns"][key])
            for key in (*CAMPUSES, "both")
        }
        return Config(windows, patterns, semesters["version"], campus["version"])
    except ConfigError:
        raise
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as error:
        raise ConfigError(f"Invalid SP1 normaliser config: {error}") from error


def _recognition(record: dict, flags: list[str], derived: dict[str, str]) -> bool | None:
    post_type = record["post_type"]
    if post_type == "activity":
        if (
            record["mandatory_stated"] is True
            and record["registration_url"] is None
            and record["join_url"] is None
            and record["recognition_stated"] is not True
        ):
            flags.append("needs_review:drl_recognized")
            derived["drl_recognized"] = "rule:mandatory_no_participation_cue"
            return None
        derived["drl_recognized"] = "rule:post_type_activity"
        return True
    if post_type == "info_only":
        derived["drl_recognized"] = "rule:post_type_info_only"
        return False
    flags.append("needs_review:post_type")
    return None


def _datetime_value(
    value: str | None, field: str, time_defaults: dict[str, str], *, opening: bool = False,
) -> datetime | None:
    if value is None:
        return None
    if "T" not in value:
        hour, minute = DEFAULT_START if opening else DEFAULT_END
        time_defaults[field] = f"date_only_{hour:02d}{minute:02d}"
        value = f"{value}T{hour:02d}:{minute:02d}{TZ_SUFFIX}"
    return datetime.fromisoformat(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def _duration(record: dict, opening: datetime | None, closing: datetime | None) -> tuple[int | None, str]:
    if record["duration_minutes_stated"] is not None:
        return record["duration_minutes_stated"], "stated"
    mode = record["mode"]
    if mode is None:
        return None, "unknown"
    if mode == "hybrid":
        return None, "unsupported"
    if mode == "offline":
        if opening is None or "T" not in record["window_open"]:
            return None, "unsupported"
        if closing is None or "T" not in record["window_close"] or closing.date() != opening.date():
            return 120, "default_offline_2h"
        if closing > opening:
            return int((closing - opening).total_seconds() // 60), "window_span"
        return None, "unsupported"
    if any(item["type"] == "quiz" for item in record["completion_requirements"]):
        return 30, "default_quiz_30m"
    if record["multi_session"] is True:
        return None, "unsupported"
    return 30, "default_online_30m"


def _place(
    record: dict, config: Config, flags: list[str], derived: dict[str, str],
) -> tuple[str | None, list[str]]:
    location, mode = record["location"], record["mode"]
    if mode == "online":
        derived["campus"] = "rule:online_campus_empty"
        if location is not None:
            flags.append("location_dropped_online")
            derived["location"] = "rule:online_location_null"
        return None, []
    if location is None:
        derived["campus"] = "rule:location_missing"
        if mode in ("offline", "hybrid"):
            flags.append("campus_unknown")
        return None, []
    text = _location_key(location)
    codes = [code for code in CAMPUSES if any(_has_token(text, pattern) for pattern in config.campuses[code])]
    if any(_has_token(text, pattern) for pattern in config.campuses["both"]):
        codes = list(CAMPUSES)
    derived["campus"] = f"dict:campus_v{config.campus_version}"
    return location, codes or ["Other"]


def _team_defaults(record: dict, derived: dict[str, str]) -> tuple[dict, bool, int | dict]:
    audience = {"text": record["audience_text"], **record["audience_scope"]}
    audience["all_students"] = not (audience["cohorts"] or audience["programs"])
    if audience["all_students"]:
        derived["audience"] = "team_default:audience_all"
    mandatory = record["mandatory_stated"]
    if mandatory is None:
        mandatory = False
        derived["mandatory"] = "team_default:mandatory_false"
    fee = record["fee"]
    if fee is None:
        fee = 0
        derived["fee"] = "team_default:fee_not_stated_free"
    return audience, mandatory, fee


def _semester(day: date | None, periods: tuple[tuple[date, date, str], ...]) -> str:
    if day is None:
        return "insufficient_data"
    return next((key for start, end, key in periods if start <= day <= end), "out_of_scope_semester")


def _status(flags: list[str]) -> str:
    actionable = [flag for flag in flags if flag not in INFORMATIONAL_FLAGS]
    if not actionable:
        return "valid"
    return "partial" if all(flag.startswith("needs_review:") for flag in actionable) else "failed"


def normalize(layer_a: dict, source: dict, config: Config | None = None) -> dict:
    """Return a fresh v2 activity from validated layer-A input and source metadata."""
    if config is None:
        config = load_config()
    record = deepcopy(layer_a["record"])
    flags = list(layer_a["flags"])
    derived: dict[str, str] = {"activity_id": "rule:temp_id_url_sha1"}
    unsupported: list[str] = []
    time_defaults: dict[str, str] = {}

    recognized = _recognition(record, flags, derived)
    opening = _datetime_value(record["window_open"], "window_open", time_defaults, opening=True)
    closing = _datetime_value(record["window_close"], "window_close", time_defaults)
    if opening is not None and closing is not None and closing < opening:
        flags.append("end_before_start")
    minutes, duration_source = _duration(record, opening, closing)
    if duration_source == "unsupported":
        unsupported.append("duration_minutes")
    if duration_source not in ("stated", "unsupported", "unknown"):
        prefix = "rule" if duration_source == "window_span" else "team_default"
        derived["duration_minutes"] = f"{prefix}:{duration_source}"

    deadline = _datetime_value(record["registration_deadline"], "registration_deadline", time_defaults)
    if deadline is None:
        unsupported.append("registration_deadline")
    for index, item in enumerate(record["completion_requirements"]):
        item["deadline"] = _iso(_datetime_value(
            item["deadline"], f"completion_requirements[{index}].deadline", time_defaults,
        ))
    for field, rule in time_defaults.items():
        derived[field] = f"rule:{rule}"

    location, campus = _place(record, config, flags, derived)
    audience, mandatory, fee = _team_defaults(record, derived)
    day = opening.date() if opening is not None else None
    semesters = {program: _semester(day, config.semesters[program]) for program in PROGRAMS}
    derived["semester_by_program"] = "rule:semester_from_window_open"

    for field in ("title", "mode"):
        if record[field] is None:
            flags.append(f"needs_review:{field}")
    flags = list(dict.fromkeys(flags))
    digest = hashlib.sha1(source["URL_post"].encode("utf-8")).hexdigest()[:8]
    return {
        "activity_id": f"TMP-{digest}-01",
        "source": deepcopy(source),
        "post_type": record["post_type"],
        "drl_recognized": recognized,
        "title": record["title"],
        "domain": record["domain"],
        "multi_session": record["multi_session"],
        "mode": record["mode"],
        "window": {"open": _iso(opening), "close": _iso(closing)},
        "duration_minutes": minutes,
        "duration_source": duration_source,
        "registration_deadline": _iso(deadline),
        "location": location,
        "campus": campus,
        "audience": audience,
        "mandatory": mandatory,
        "recognition_stated": record["recognition_stated"],
        "points_announced": record["points_stated"],
        "fee": fee,
        "registration_url": record["registration_url"],
        "join_url": record["join_url"],
        "completion_requirements": record["completion_requirements"],
        "semester_by_program": semesters,
        "meta": {
            "status": _status(flags),
            "flags": flags,
            "derived": derived,
            "unsupported": unsupported,
            "time_defaults": time_defaults,
            "year_inferred": list(layer_a["year_inferred"]),
            "normalizer_version": NORMALIZER_VERSION,
            "config_versions": {"semesters": config.semester_version, "campus": config.campus_version},
        },
    }
