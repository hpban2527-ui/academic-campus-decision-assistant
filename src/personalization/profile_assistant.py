"""Strict AI-to-profile patch contract shared by onboarding and profile editing."""

from __future__ import annotations

from copy import deepcopy
from datetime import date as DateValue, timedelta
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditableProfile(StrictModel):
    full_name: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=64)
    major: str | None = Field(default=None, max_length=100)


class WeeklyProfileInterval(StrictModel):
    kind: Literal["busy", "available"]
    weekday: int = Field(ge=0, le=6)
    start: str
    end: str
    recurrence: Literal["weekly"] = "weekly"
    source: Literal["ai", "manual"] = "ai"
    confirmed: bool = False

    @field_validator("start", "end")
    @classmethod
    def valid_clock(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("time must use HH:MM")
        return value

    @model_validator(mode="after")
    def valid_order(self) -> "WeeklyProfileInterval":
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class DateException(StrictModel):
    date: DateValue
    kind: Literal["busy", "available"]
    start: str
    end: str
    source: Literal["ai", "manual"] = "ai"
    confirmed: bool = False

    @field_validator("start", "end")
    @classmethod
    def valid_clock(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("time must use HH:MM")
        return value

    @model_validator(mode="after")
    def valid_order(self) -> "DateException":
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class PreferencePatch(StrictModel):
    preferred_topics: list[str] = Field(default_factory=list, max_length=20)
    preferred_categories: list[Literal["C1", "C2", "C3", "C4", "C5"]] = Field(default_factory=list)
    preferred_modes: list[Literal["online", "offline", "hybrid"]] = Field(default_factory=list)
    preferred_campuses: list[Literal["NVC", "DONG_HOA", "ONLINE", "OTHER"]] = Field(default_factory=list)
    max_activities: int | None = Field(default=None, ge=1, le=20)
    weekly_participation_hours: float | None = Field(default=None, ge=0.5, le=168)


class ProfileScore(StrictModel):
    value: float | None = Field(default=None, ge=0, le=100)
    source: Literal["confirmed", "self_reported", "unknown"] = "unknown"


class PreferenceUpdatePatch(StrictModel):
    preferred_topics: list[str] | None = Field(default=None, max_length=20)
    preferred_categories: list[Literal["C1", "C2", "C3", "C4", "C5"]] | None = None
    preferred_modes: list[Literal["online", "offline", "hybrid"]] | None = None
    preferred_campuses: list[Literal["NVC", "DONG_HOA", "ONLINE", "OTHER"]] | None = None
    max_activities: int | None = Field(default=None, ge=1, le=20)
    weekly_participation_hours: float | None = Field(default=None, ge=0.5, le=168)

    @model_validator(mode="after")
    def contains_patch(self) -> "PreferenceUpdatePatch":
        if not self.model_fields_set:
            raise ValueError("preference patch must contain at least one field")
        return self


class EditableProfileFieldPatch(StrictModel):
    full_name: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=64)
    major: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def contains_one_field(self) -> "EditableProfileFieldPatch":
        if len(self.model_fields_set) != 1:
            raise ValueError("profile patch must contain exactly one field")
        return self


class ScoreUpdatePatch(StrictModel):
    category_id: Literal["C1", "C2", "C3", "C4", "C5"]
    value: float | None = Field(default=None, ge=0, le=100)
    source: Literal["confirmed", "self_reported", "unknown"]


class WeeklyIntervalMatch(StrictModel):
    kind: Literal["busy", "available"] | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def contains_filter(self) -> "WeeklyIntervalMatch":
        if not self.model_fields_set:
            raise ValueError("weekly interval match must contain a filter")
        return self


class ExceptionMatch(StrictModel):
    date: DateValue | None = None
    kind: Literal["busy", "available"] | None = None
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def contains_filter(self) -> "ExceptionMatch":
        if not self.model_fields_set:
            raise ValueError("exception match must contain a filter")
        return self


class ProfileAssistantDraft(StrictModel):
    profile: EditableProfile = Field(default_factory=EditableProfile)
    drl_target: int | None = Field(default=None, ge=0, le=100)
    weekly_intervals: list[WeeklyProfileInterval] = Field(default_factory=list, max_length=100)
    exceptions: list[DateException] = Field(default_factory=list, max_length=100)
    preference_patch: PreferencePatch = Field(default_factory=PreferencePatch)
    scores: dict[Literal["C1", "C2", "C3", "C4", "C5"], ProfileScore] = Field(default_factory=dict)


ActionName = Literal[
    "update_drl_goal",
    "upsert_weekly_interval",
    "remove_weekly_interval",
    "upsert_exception",
    "remove_exception",
    "update_preferences",
    "update_profile_field",
    "update_score",
]

_SCORE_CAPS = {"C1": 30, "C2": 20, "C3": 25, "C4": 25, "C5": 30}


class ProfilePatchAction(StrictModel):
    action: ActionName
    operation: Literal["add", "replace", "remove", "set"]
    value: (
        int
        | WeeklyProfileInterval
        | DateException
        | PreferenceUpdatePatch
        | EditableProfileFieldPatch
        | ScoreUpdatePatch
        | None
    ) = None
    match: WeeklyIntervalMatch | ExceptionMatch | None = None
    source_text: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def compatible_operation(self) -> "ProfilePatchAction":
        if self.action.startswith("remove_") and self.operation != "remove":
            raise ValueError("remove actions require operation=remove")
        if self.action == "update_drl_goal" and type(self.value) is not int:
            raise ValueError("DRL goal must be an integer")
        expected_values = {
            "upsert_weekly_interval": WeeklyProfileInterval,
            "upsert_exception": DateException,
            "update_preferences": PreferenceUpdatePatch,
            "update_profile_field": EditableProfileFieldPatch,
            "update_score": ScoreUpdatePatch,
        }
        expected_value = expected_values.get(self.action)
        if expected_value is not None and not isinstance(self.value, expected_value):
            raise ValueError(f"{self.action} has an invalid value payload")
        if self.action == "remove_weekly_interval" and not isinstance(self.match, WeeklyIntervalMatch):
            raise ValueError("remove_weekly_interval requires a weekly interval match")
        if self.action == "remove_exception" and not isinstance(self.match, ExceptionMatch):
            raise ValueError("remove_exception requires an exception match")
        if self.action not in {"remove_weekly_interval", "remove_exception", "upsert_weekly_interval"} and self.match is not None:
            raise ValueError(f"{self.action} does not accept match")
        return self


class ProfileExtraction(StrictModel):
    actions: list[ProfilePatchAction] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def require_result(self) -> "ProfileExtraction":
        if not self.actions and not self.questions:
            raise ValueError("AI extraction must contain an action or a clarification question")
        return self


class ProfileChange(StrictModel):
    field: str
    operation: str
    old: Any = None
    new: Any = None
    source_text: str


def _matches(item: BaseModel, expected: dict[str, Any]) -> bool:
    payload = item.model_dump(mode="json")
    allowed = set(payload)
    if not expected or not set(expected) <= allowed:
        raise ValueError("remove match contains unsupported fields")
    return all(payload[key] == value for key, value in expected.items())


def _patch_dict(value: BaseModel | None) -> dict[str, Any]:
    if value is None:
        return {}
    return value.model_dump(mode="json", exclude_unset=True)


def _match_dict(value: BaseModel | None) -> dict[str, Any]:
    if value is None:
        return {}
    return value.model_dump(mode="json", exclude_none=True, exclude_unset=True)


def merge_profile_extraction(
    current: ProfileAssistantDraft | dict[str, Any],
    extraction: ProfileExtraction,
) -> tuple[ProfileAssistantDraft, list[ProfileChange]]:
    """Apply allowlisted PATCH actions to a copy and return an auditable diff."""

    draft = current if isinstance(current, ProfileAssistantDraft) else ProfileAssistantDraft.model_validate(current)
    merged = draft.model_copy(deep=True)
    changes: list[ProfileChange] = []
    for action in extraction.actions:
        old: Any = None
        new: Any = None
        field = action.action
        if action.action == "update_drl_goal":
            old, merged.drl_target = merged.drl_target, int(action.value)
            merged = ProfileAssistantDraft.model_validate(merged.model_dump())
            new, field = merged.drl_target, "drl_target"
        elif action.action == "upsert_weekly_interval":
            interval = WeeklyProfileInterval.model_validate(action.value)
            before = [item.model_dump(mode="json") for item in merged.weekly_intervals]
            replaced: list[dict[str, Any]] = []
            if action.operation == "replace":
                expected = _match_dict(action.match) or {"kind": interval.kind, "weekday": interval.weekday}
                replaced = [item.model_dump(mode="json") for item in merged.weekly_intervals if _matches(item, expected)]
                merged.weekly_intervals = [item for item in merged.weekly_intervals if not _matches(item, expected)]
            if interval not in merged.weekly_intervals:
                merged.weekly_intervals.append(interval)
            after = [item.model_dump(mode="json") for item in merged.weekly_intervals]
            old = replaced[0] if len(replaced) == 1 else (replaced or None)
            new = interval.model_dump(mode="json")
            if before == after:
                old = new
            field = "weekly_intervals"
        elif action.action == "remove_weekly_interval":
            expected = _match_dict(action.match)
            removed = [item.model_dump(mode="json") for item in merged.weekly_intervals if _matches(item, expected)]
            merged.weekly_intervals = [item for item in merged.weekly_intervals if not _matches(item, expected)]
            old = removed[0] if len(removed) == 1 else (removed or None)
            new, field = None, "weekly_intervals"
            if not removed:
                old = new
        elif action.action == "upsert_exception":
            exception = DateException.model_validate(action.value)
            before = [item.model_dump(mode="json") for item in merged.exceptions]
            replaced = []
            if action.operation == "replace":
                replaced = [item.model_dump(mode="json") for item in merged.exceptions if item.date == exception.date]
                merged.exceptions = [item for item in merged.exceptions if item.date != exception.date]
            if exception not in merged.exceptions:
                merged.exceptions.append(exception)
            after = [item.model_dump(mode="json") for item in merged.exceptions]
            old = replaced[0] if len(replaced) == 1 else (replaced or None)
            new, field = exception.model_dump(mode="json"), "exceptions"
            if before == after:
                old = new
        elif action.action == "remove_exception":
            expected = _match_dict(action.match)
            removed = [item.model_dump(mode="json") for item in merged.exceptions if _matches(item, expected)]
            merged.exceptions = [item for item in merged.exceptions if not _matches(item, expected)]
            old = removed[0] if len(removed) == 1 else (removed or None)
            new, field = None, "exceptions"
            if not removed:
                old = new
        elif action.action == "update_preferences":
            old = merged.preference_patch.model_dump(mode="json")
            patch = _patch_dict(action.value if isinstance(action.value, BaseModel) else None)
            unknown = set(patch) - set(PreferencePatch.model_fields)
            if unknown:
                raise ValueError("preference patch contains unsupported fields")
            updated = deepcopy(old)
            if action.operation == "add":
                for key, value in patch.items():
                    if isinstance(value, list):
                        updated[key] = list(dict.fromkeys([*updated.get(key, []), *value]))
                    else:
                        updated[key] = value
            elif action.operation == "remove":
                for key, value in patch.items():
                    if isinstance(value, list):
                        updated[key] = [item for item in updated.get(key, []) if item not in value]
                    else:
                        updated[key] = None
            else:
                updated.update(deepcopy(patch))
            merged.preference_patch = PreferencePatch.model_validate(updated)
            current_new = merged.preference_patch.model_dump(mode="json")
            changed_keys = [key for key in patch if old.get(key) != current_new.get(key)]
            old = {key: old.get(key) for key in changed_keys}
            new = {key: current_new.get(key) for key in changed_keys}
            field = "preference_patch"
        elif action.action == "update_profile_field":
            patch = _patch_dict(action.value if isinstance(action.value, BaseModel) else None)
            if len(patch) != 1 or not set(patch) <= set(EditableProfile.model_fields):
                raise ValueError("profile patch must contain one editable field")
            key, value = next(iter(patch.items()))
            old = getattr(merged.profile, key)
            merged.profile = EditableProfile.model_validate({**merged.profile.model_dump(), key: value})
            new, field = getattr(merged.profile, key), f"profile.{key}"
        elif action.action == "update_score":
            patch = _patch_dict(action.value if isinstance(action.value, BaseModel) else None)
            if set(patch) != {"category_id", "value", "source"} or patch["category_id"] not in {"C1", "C2", "C3", "C4", "C5"}:
                raise ValueError("score patch must identify one supported category and source")
            category = patch.pop("category_id")
            if patch["value"] is not None and patch["value"] > _SCORE_CAPS[category]:
                raise ValueError(f"score for {category} exceeds its configured cap")
            old = merged.scores.get(category)
            merged.scores[category] = ProfileScore.model_validate(patch)
            old = old.model_dump(mode="json") if old else None
            new, field = merged.scores[category].model_dump(mode="json"), f"scores.{category}"
        if old != new:
            changes.append(ProfileChange(field=field, operation=action.operation, old=old, new=new, source_text=action.source_text))
    return merged, changes


PROFILE_EXTRACTION_PROMPT = """You extract Vietnamese student profile PATCH operations only.
Return JSON matching the supplied schema. Never invent scores, dates, times or preferences.
Allowed actions are update_drl_goal, upsert_weekly_interval, remove_weekly_interval,
upsert_exception, remove_exception, update_preferences, update_profile_field and update_score.
Use weekday 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday,
5=Saturday and 6=Sunday, with HH:MM times. Distinguish 'khong ranh' as busy.
For a weekly busy interval, value must be exactly like
{"kind":"busy","weekday":0,"start":"08:00","end":"10:00","recurrence":"weekly","source":"ai","confirmed":false}.
Never use aliases such as day, from or to. Removal filters belong in match, not value.
For preferred_topics use only stable topic IDs from the current StudentPreference vocabulary,
for example volunteer, artificial_intelligence, computer_science, soft_skills or sports.
If recurrence or a specific date is ambiguous, emit no action and ask one concise question.
Preserve unrelated current values; do not calculate DRL points or schedules.
Understand common Vietnamese abbreviations (T2..T7, CN), accented or unaccented text,
informal clocks such as 7h, 7h30 and 19g, and explicit add/remove/replace/negation wording.
Return at most one clarification question, for the single missing fact needed next.
"""


SIMULATION_REFERENCE_MONDAY = DateValue(2026, 11, 9)

_TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "mathematics": ("toan hoc", "toan", "giai tich", "dai so", "xac suat", "thong ke"),
    "physics": ("vat ly", "vat li", "co hoc", "quang hoc"),
    "chemistry": ("hoa hoc", "mon hoa", "nganh hoa"),
    "biology": ("sinh hoc", "cong nghe sinh hoc", "vi sinh"),
    "computer_science": (
        "khoa hoc may tinh", "cong nghe thong tin", "lap trinh", "tin hoc", "cntt", "phan mem", "coding", "code",
    ),
    "foreign_language": (
        "ngoai ngu", "tieng anh", "tieng nhat", "tieng han", "tieng trung", "tieng phap", "tieng duc",
        "anh van", "nhat ngu", "han ngu", "ielts", "toeic", "jlpt",
    ),
    "economics_finance": ("kinh te", "tai chinh", "dau tu", "chung khoan", "ngan hang", "kinh doanh", "khoi nghiep"),
    "artificial_intelligence": ("tri tue nhan tao", "machine learning", "hoc may", "deep learning", "ai"),
    "technology": ("cong nghe", "robot", "robotics", "iot", "ky thuat", "dien tu", "phan cung"),
    "research": ("nghien cuu khoa hoc", "nghien cuu", "hoc thuat", "nckh", "seminar", "hoi thao khoa hoc"),
    "soft_skills": (
        "ky nang mem", "giao tiep", "thuyet trinh", "lam viec nhom", "lanh dao", "quan ly thoi gian", "phan bien",
    ),
    "career": ("nghe nghiep", "huong nghiep", "viec lam", "thuc tap", "tuyen dung", "viet cv", "phong van"),
    "volunteer": ("tinh nguyen", "cong dong", "thien nguyen", "mua he xanh", "xuan tinh nguyen", "hien mau"),
    "environment": ("moi truong", "song xanh", "bien doi khi hau", "tai che", "bao ve moi truong"),
    "culture": (
        "van hoa", "van nghe", "nghe thuat", "thiet ke", "ve tranh", "hoi hoa", "my thuat", "am nhac", "nhiep anh",
    ),
    "sports": ("the thao", "the duc", "bong da", "bong chuyen", "bong ro", "cau long", "boi loi", "chay bo", "co vua"),
    "health": ("suc khoe", "y te", "dinh duong", "tam ly", "cham soc suc khoe"),
    "safety": (
        "an toan", "phong chay", "chua chay", "pccc", "so cuu", "bao mat", "an ninh mang", "an toan thong tin",
    ),
    "civic_education": ("giao duc cong dan", "phap luat", "chinh tri", "doan hoi", "cong dan", "dao duc"),
}


def _topics_in(text: str, raw_text: str = "") -> list[str]:
    padded = f" {text} "
    found: list[str] = []
    for topic, terms in _TOPIC_TERMS.items():
        if any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", padded) for term in terms):
            found.append(topic)
    if "culture" not in found:
        if (raw_text and re.search(r"(?i)(?<!\w)vẽ(?!\w)", raw_text)) or re.search(
            r"\b(?:thich|hoc|mon|nghe\s+thuat)\s+ve\b(?!\s+(?:tai\s+chinh|kinh\s+te|cong\s+nghe|moi\s+truong|suc\s+khoe|an\s+toan|nghe\s+nghiep|tinh\s+nguyen|khoa\s+hoc))",
            padded,
        ):
            found.append("culture")
    if "chemistry" not in found and raw_text:
        if re.search(r"(?i)(?<!\w)(?<!văn\s)(?<!đông\s)hóa(?!\w)", raw_text):
            found.append("chemistry")
    return found


_KNOWN_NON_TOPIC_PATTERN = re.compile(
    r"\b(?:online|truc\s+tuyen|offline|truc\s+tiep|hybrid|ket\s+hop"
    r"|nvc|nguyen\s+van\s+cu|dong\s+hoa|di\s+an|khu\s+do\s+thi\s+dhqg|co\s+so"
    r"|(?:c|muc|nhom)\s*[1-5]"
    r"|(?:toi\s+da|khong\s+qua|gioi\s+han)\s*\d+(?:[.,]\d+)?\s*(?:hoat\s+dong|su\s+kien|gio|tieng)"
    r"|drl|diem\s+ren\s+luyen|muc\s+tieu)\b"
)


def _has_unresolved_interest(clause: str, raw_clause: str = "") -> bool:
    residue = _KNOWN_NON_TOPIC_PATTERN.sub(" ", clause)
    for terms in _TOPIC_TERMS.values():
        for term in terms:
            residue = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", " ", residue)
    if raw_clause and re.search(r"(?i)(?<!\w)vẽ(?!\w)", raw_clause):
        residue = re.sub(r"\bve\b", " ", residue)
    if raw_clause and re.search(r"(?i)(?<!\w)(?<!văn\s)(?<!đông\s)hóa(?!\w)", raw_clause):
        residue = re.sub(r"\bhoa\b", " ", residue)
    residue = re.sub(
        r"\b(?:toi|tui|minh|em|thich|uu|tien|quan|tam|muon|tham|gia|hoat|dong|su|kien|so|va|voi|cac|nhung"
        r"|mon|linh|vuc|chu|de|them|vao|bo|xoa|loai|khoi|danh|sach|khong|con|nua|it|the|doi|thay|tu|sang"
        r"|thanh|bang|chi|toan|cua|la|o|tai|ve|cuoc|thi|hinh|thuc|nhom|muc|diem|ren|luyen|drl|tieu"
        r"|neu|phai|thi|cung|duoc|hoac|hay|tuan|gio|tieng|moi|mot)\b",
        " ",
        residue,
    )
    return bool(re.search(r"\b[a-z]{2,}\b", residue))


def merge_profile_extractions(*extractions: ProfileExtraction | None) -> ProfileExtraction | None:
    """Combine complementary validated actions, keeping later grounded actions decisive."""

    actions: list[ProfilePatchAction] = []
    fingerprints: set[str] = set()
    questions: list[str] = []
    primary_seen = False
    for extraction in extractions:
        if extraction is None:
            continue
        if not primary_seen:
            questions = extraction.questions[:1]
            primary_seen = True
        for action in extraction.actions:
            fingerprint = repr(action.model_dump(mode="json", exclude_none=True, exclude_unset=True))
            if fingerprint not in fingerprints:
                actions.append(action)
                fingerprints.add(fingerprint)
    if not actions and not questions:
        return None
    return ProfileExtraction(actions=actions, questions=questions)


def deterministic_profile_extraction(
    text: str,
    conversation: list[dict[str, str]] | None = None,
    current: ProfileAssistantDraft | dict[str, Any] | None = None,
) -> ProfileExtraction | None:
    """Conservative fast path for explicit Vietnamese profile statements."""

    normalized = _fold_vi(text)
    if conversation and _fallback_weekday(normalized) is None and _fallback_date(normalized) is None:
        previous = next((turn.get("content", "") for turn in reversed(conversation) if turn.get("role") == "user"), "")
        if previous and (_fallback_times(normalized) or normalized in {"hang tuan", "moi tuan", "tuan nao cung vay"}):
            previous_folded = _fold_vi(previous)
            if _fallback_weekday(previous_folded) is not None or _fallback_date(previous_folded) is not None:
                text = f"{previous}; {text}"
                normalized = _fold_vi(text)
    actions: list[ProfilePatchAction] = []
    draft = (
        current if isinstance(current, ProfileAssistantDraft)
        else ProfileAssistantDraft.model_validate(current or {})
    )
    profile_patterns = {
        "full_name": r"(?i)\b(?:mình|minh|tôi|toi|em)\s+(?:tên|ten)\s+([^,;]+)",
        "class_name": r"(?i)\b(?:lớp|lop)\s+([\w.-]{2,32})",
        "major": r"(?i)\b(?:ngành|nganh)\s+([^,;]+)",
    }
    for field, pattern in profile_patterns.items():
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            actions.append(ProfilePatchAction(
                action="update_profile_field", operation="set",
                value={field: value}, source_text=text.strip(),
            ))

    clarification: str | None = None
    goal = re.search(
        r"\b(?:muon\s+dat|dat|nang|giam|ha|doi|can|phan\s+dau)\D{0,25}(-?\d{1,3})\s*(?:diem\s*)?(?:ren\s*luyen|drl)\b",
        normalized,
    )
    if goal is None:
        goal = re.search(
            r"(?:muc\s*tieu|drl|diem\s*ren\s*luyen)(?:[^\d,;-]|-(?!\d)){0,30}(-?\d{1,3})\b",
            normalized,
        )
    if goal is None and re.fullmatch(r"-?\d{1,3}", normalized) and conversation:
        previous_assistant = next((
            _fold_vi(turn.get("content", "")) for turn in reversed(conversation)
            if turn.get("role") == "assistant"
        ), "")
        if re.search(r"\b(?:drl|diem\s*ren\s*luyen|muc\s*tieu)\b", previous_assistant):
            goal = re.fullmatch(r"-?\d{1,3}", normalized)
    if goal:
        value = int(goal.group(1) if goal.lastindex else goal.group(0))
        if 0 <= value <= 100:
            actions.append(ProfilePatchAction(
                action="update_drl_goal", operation="set", value=value, source_text=text.strip()
            ))
        else:
            clarification = "Muc tieu DRL phai la so nguyen tu 0 den 100. Ban muon dat bao nhieu diem?"

    schedule_clauses = [item.strip() for item in re.split(r"[;\n]+|,\s*(?=(?:t[2-7]|thứ|thu|cn|chủ nhật|chu nhat|hôm nay|hom nay|ngày mai|ngay mai)\b)", text, flags=re.IGNORECASE) if item.strip()]
    for clause in schedule_clauses:
        folded_clause = _fold_vi(clause)
        exception_date = _fallback_date(folded_clause)
        weekday = None if exception_date is not None else _fallback_weekday(folded_clause)
        schedule_words = re.search(r"\b(?:ban|ranh|hoc|lich|t[2-7]|cn|thu|hang\s*tuan|hom\s*nay|ngay\s*mai|tuan\s*nay|tuan\s*sau)\b", folded_clause)
        if (weekday is None and exception_date is None) or not schedule_words:
            continue
        remove = bool(re.search(r"\b(?:xoa|bo|huy)\b", folded_clause))
        replace = bool(re.search(r"\b(?:thay|doi|chuyen)\b", folded_clause))
        kind = "busy" if re.search(r"\b(?:khong\s*ranh|ban|hoc|ket)\b", folded_clause) else "available"
        times = _fallback_times(folded_clause)
        if exception_date is not None:
            if remove:
                actions.append(ProfilePatchAction(
                    action="remove_exception", operation="remove",
                    match={"date": exception_date, "kind": kind}, source_text=clause,
                ))
                continue
            if len(times) < 2:
                clarification = clarification or "Ngoại lệ đó bắt đầu và kết thúc lúc mấy giờ?"
                continue
            if times[0] >= times[1]:
                clarification = clarification or "Giờ bắt đầu phải trước giờ kết thúc; bạn muốn khung giờ nào?"
                continue
            actions.append(ProfilePatchAction(
                action="upsert_exception", operation="replace" if replace else "add",
                value={
                    "date": exception_date, "kind": kind, "start": times[0], "end": times[1],
                    "source": "ai", "confirmed": False,
                }, source_text=clause,
            ))
            continue
        if remove:
            actions.append(ProfilePatchAction(
                action="remove_weekly_interval", operation="remove",
                match={"weekday": weekday, "kind": kind}, source_text=clause,
            ))
            continue
        if len(times) < 2:
            clarification = clarification or "Bạn bận hoặc rảnh từ mấy giờ đến mấy giờ?"
            continue
        if times[0] >= times[1]:
            clarification = clarification or "Giờ bắt đầu phải trước giờ kết thúc; bạn muốn khung giờ nào?"
            continue
        actions.append(ProfilePatchAction(
            action="upsert_weekly_interval", operation="replace" if replace else "add",
            value={
                "kind": kind, "weekday": weekday, "start": times[0], "end": times[1],
                "recurrence": "weekly", "source": "ai", "confirmed": False,
            },
            match={"weekday": weekday, "kind": kind} if replace else None,
            source_text=clause,
        ))

    preference_value: dict[str, Any] = {}
    removed_preference_value: dict[str, Any] = {}
    added_topics: list[str] = []
    removed_topics: list[str] = []
    replace_all_topics = bool(
        re.search(r"\b(?:thay|doi)\s+(?:toan\s+bo\s+|danh\s+sach\s+)?so\s+thich\s+(?:bang|thanh)\b", normalized)
        or re.search(r"\bchi\s+thich\b", normalized)
    )
    topic_list_mode: str | None = None
    clause_split_pattern = re.compile(
        r"[,;\n]+|\b(?:và|va|nhưng|nhung|mà|ma)\s+(?=(?:không|khong|ít|it|bỏ|bo|xóa|xoa|loại|loai|thêm|them|đổi|doi|thay|thích|thich|ưu\s*tiên|uu\s*tien|quan\s*tâm|quan\s*tam|muốn|muon)\b)",
        re.IGNORECASE,
    )
    for raw_clause in (item.strip() for item in clause_split_pattern.split(text) if item.strip()):
        clause = _fold_vi(raw_clause)
        if re.search(r"\bneu\s+.+?\s+thi\b", clause):
            clause = re.sub(r"^.*?\bneu\s+.+?\s+thi\s+", "", clause).strip()
            raw_clause = re.sub(r"(?i)^.*?\bnếu\s+.+?\s+thì\s+", "", raw_clause).strip()
        if re.search(r"\bcung\s+duoc\b", clause):
            continue
        is_schedule_or_profile = bool(
            re.search(r"\b(?:minh|toi|em)\s+ten\b|\b(?:lop|nganh)\s+\w", clause)
            or (
                (_fallback_weekday(clause) is not None or _fallback_date(clause) is not None)
                and re.search(r"\b(?:ban|ranh|hoc|lich|hang\s*tuan|hom\s*nay|ngay\s*mai)\b", clause)
            )
        )
        if is_schedule_or_profile:
            topic_list_mode = None
            continue
        clause_topics = _topics_in(clause, raw_clause)
        has_interest_verb = bool(re.search(
            r"\b(?:thich|quan\s*tam|muon\s*tham\s*gia|so\s*thich|them|bo|xoa|loai|it\s*uu\s*tien|khong\s*the\s*tham\s*gia)\b",
            clause,
        ))
        has_priority_verb = bool(re.search(r"\buu\s*tien\b", clause))
        has_non_topic_pref = bool(_KNOWN_NON_TOPIC_PATTERN.search(clause))

        replacement = re.search(r"\btu\s+(.+?)\s+sang\s+(.+)$", clause)
        if replacement:
            removed_topics.extend(_topics_in(replacement.group(1)))
            added_topics.extend(_topics_in(replacement.group(2)))
            topic_list_mode = "add"
            continue
        if re.search(r"\b(?:it\s*uu\s*tien|khong\s*the\s*tham\s*gia)\b", clause):
            if clause_topics or not has_non_topic_pref:
                clarification = clarification or "Ban muon bo so thich nay, hay chi de muc uu tien thap?"
            topic_list_mode = None
            continue
        if re.search(r"\b(?:khong\s*con\s*thich|khong\s*thich|khong\s*quan\s*tam|bo|xoa|loai)\b", clause):
            if clause_topics:
                removed_topics.extend(clause_topics)
                topic_list_mode = "remove"
            continue

        if has_interest_verb or (has_priority_verb and clause_topics):
            topic_list_mode = "add"

        if clause_topics and topic_list_mode == "add":
            added_topics.extend(clause_topics)
            if _has_unresolved_interest(clause, raw_clause):
                clarification = clarification or "Co mot so thich chua khop cac chu de hien co. Ban muon mo ta ro hon?"
        elif clause_topics and topic_list_mode == "remove":
            removed_topics.extend(clause_topics)
        elif not clause_topics and not has_non_topic_pref:
            if (has_interest_verb or topic_list_mode == "add") and _has_unresolved_interest(clause, raw_clause):
                clarification = clarification or "Co mot so thich chua khop cac chu de hien co. Ban muon mo ta ro hon?"
        elif has_non_topic_pref and not clause_topics:
            # A pure mode/campus/category/goal clause resets an implicit comma topic list unless it also had an interest verb.
            if not has_interest_verb:
                topic_list_mode = None

    if removed_topics:
        removed_preference_value["preferred_topics"] = list(dict.fromkeys(removed_topics))
    if added_topics and replace_all_topics and not removed_topics:
        actions.append(ProfilePatchAction(
            action="update_preferences", operation="replace",
            value={"preferred_topics": list(dict.fromkeys(added_topics))}, source_text=text.strip(),
        ))
    elif added_topics:
        preference_value["preferred_topics"] = list(dict.fromkeys(added_topics))

    effective_pref_text = re.sub(r"\bneu\s+[^,;.\n]+?\s+thi\b", " ", normalized)
    effective_pref_text = re.sub(r"\bnhung\s+[^,;.\n]+?\s+cung\s+duoc\b", " ", effective_pref_text)

    categories: list[str] = []
    removed_categories: list[str] = []
    for match in re.finditer(r"\b(?:c|muc|nhom)\s*([1-5])\b", effective_pref_text):
        cat = f"C{match.group(1)}"
        prefix = effective_pref_text[max(0, match.start() - 25):match.start()]
        if re.search(r"\b(?:khong\s*(?:con\s*)?(?:thich|uu\s*tien)|bo|xoa|loai)\s*$", prefix.strip()):
            removed_categories.append(cat)
        else:
            categories.append(cat)
    if categories:
        preference_value["preferred_categories"] = list(dict.fromkeys(categories))
    if removed_categories:
        removed_preference_value["preferred_categories"] = list(dict.fromkeys(removed_categories))

    ambiguous_mode = bool(re.search(
        r"\b(?:online|truc\s+tuyen|offline|truc\s+tiep|hybrid|ket\s+hop)\s+(?:hay|hoac)\s+(?:online|truc\s+tuyen|offline|truc\s+tiep|hybrid|ket\s+hop)\b",
        effective_pref_text,
    ))
    modes: list[str] = []
    removed_modes: list[str] = []
    for mode, terms in {
        "online": ("online", "truc tuyen"),
        "offline": ("offline", "truc tiep"),
        "hybrid": ("hybrid", "ket hop"),
    }.items():
        for term in terms:
            for match in re.finditer(rf"\b{re.escape(term)}\b", effective_pref_text):
                prefix = effective_pref_text[max(0, match.start() - 25):match.start()]
                if re.search(r"\b(?:khong\s*(?:con\s*)?(?:thich|uu\s*tien)|bo|xoa|loai)\s*$", prefix.strip()):
                    removed_modes.append(mode)
                else:
                    modes.append(mode)
    if modes and not ambiguous_mode:
        preference_value["preferred_modes"] = list(dict.fromkeys(modes))
    elif modes and ambiguous_mode:
        clarification = clarification or "Ban muon hinh thuc nao la uu tien chinh?"
    if removed_modes:
        removed_preference_value["preferred_modes"] = list(dict.fromkeys(removed_modes))

    campuses: list[str] = []
    removed_campuses: list[str] = []
    for campus_id, pattern in (
        ("NVC", r"\b(?:nvc|nguyen van cu)\b"),
        ("DONG_HOA", r"\b(?:dong hoa|di an|khu do thi dhqg)\b"),
    ):
        for match in re.finditer(pattern, effective_pref_text):
            prefix = effective_pref_text[max(0, match.start() - 25):match.start()]
            if re.search(r"\b(?:khong\s*(?:con\s*)?(?:thich|uu\s*tien)|bo|xoa|loai)\s*$", prefix.strip()):
                removed_campuses.append(campus_id)
            else:
                campuses.append(campus_id)
    if campuses:
        preference_value["preferred_campuses"] = list(dict.fromkeys(campuses))
    if removed_campuses:
        removed_preference_value["preferred_campuses"] = list(dict.fromkeys(removed_campuses))

    if removed_preference_value:
        actions.append(ProfilePatchAction(
            action="update_preferences", operation="remove",
            value=removed_preference_value, source_text=text.strip(),
        ))
    max_activities = re.search(r"\b(?:toi da|khong qua|gioi han)\D{0,20}(\d{1,2})\s*(?:hoat dong|su kien)\b", normalized)
    if max_activities and 1 <= int(max_activities.group(1)) <= 20:
        preference_value["max_activities"] = int(max_activities.group(1))
    weekly_hours = re.search(r"\b(?:toi da|khong qua|gioi han)\D{0,20}(\d+(?:[.,]\d+)?)\s*(?:gio|tieng)\s*(?:moi|mot|/)\s*tuan\b", normalized)
    if weekly_hours:
        value = float(weekly_hours.group(1).replace(",", "."))
        if 0.5 <= value <= 168:
            preference_value["weekly_participation_hours"] = value
    if preference_value:
        actions.append(ProfilePatchAction(
            action="update_preferences", operation="add",
            value=preference_value, source_text=text.strip(),
        ))

    if actions:
        return ProfileExtraction(actions=actions, questions=[clarification] if clarification else [])
    if clarification:
        return ProfileExtraction(actions=[], questions=[clarification])
    # A short recurrence answer may complete the preceding user statement.
    if normalized in {"hang tuan", "moi tuan", "tuan nao cung vay"} and conversation:
        previous = next((turn.get("content", "") for turn in reversed(conversation) if turn.get("role") == "user"), "")
        if previous:
            return deterministic_profile_extraction(f"{previous} hang tuan", [], draft)
    return None


def _fold_vi(value: str) -> str:
    value = value.casefold().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", value)
    return " ".join("".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").split())


def _fallback_weekday(text: str) -> int | None:
    patterns = {
        0: r"\b(?:t2|thu\s*(?:2|hai))\b", 1: r"\b(?:t3|thu\s*(?:3|ba))\b",
        2: r"\b(?:t4|thu\s*(?:4|tu))\b", 3: r"\b(?:t5|thu\s*(?:5|nam))\b",
        4: r"\b(?:t6|thu\s*(?:6|sau))\b", 5: r"\b(?:t7|thu\s*(?:7|bay))\b",
        6: r"\b(?:cn|chu\s*nhat)\b",
    }
    matches = [day for day, pattern in patterns.items() if re.search(pattern, text)]
    return matches[0] if len(matches) == 1 else None


def _fallback_times(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"(?<!\w)([01]?\d|2[0-3])\s*(?:h|g|:)([0-5]\d)?", text):
        values.append(f"{int(match.group(1)):02d}:{int(match.group(2) or 0):02d}")
    return values


def _fallback_date(text: str) -> str | None:
    iso = re.search(r"\b(20\d{2})-(0?[1-9]|1[0-2])-([0-2]?\d|3[01])\b", text)
    if iso:
        value = f"{int(iso.group(1)):04d}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
    else:
        local = re.search(r"\b([0-2]?\d|3[01])/(0?[1-9]|1[0-2])/(20\d{2})\b", text)
        if local:
            value = f"{int(local.group(3)):04d}-{int(local.group(2)):02d}-{int(local.group(1)):02d}"
        elif not re.search(r"\b(?:hang\s*tuan|moi\s*tuan)\b", text):
            if re.search(r"\bhom\s*nay\b", text):
                return SIMULATION_REFERENCE_MONDAY.isoformat()
            if re.search(r"\bngay\s*mai\b", text):
                return (SIMULATION_REFERENCE_MONDAY + timedelta(days=1)).isoformat()
            if re.search(r"\b(?:ngay\s*kia|ngay\s*mot)\b", text):
                return (SIMULATION_REFERENCE_MONDAY + timedelta(days=2)).isoformat()
            weekday = _fallback_weekday(text)
            if weekday is not None and re.search(r"\b(?:tuan\s*nay|tuan\s*sau|tuan\s*toi)\b", text):
                offset = weekday + (7 if re.search(r"\b(?:tuan\s*sau|tuan\s*toi)\b", text) else 0)
                return (SIMULATION_REFERENCE_MONDAY + timedelta(days=offset)).isoformat()
            return None
        else:
            return None
    try:
        return DateValue.fromisoformat(value).isoformat()
    except ValueError:
        return None


__all__ = [
    "PROFILE_EXTRACTION_PROMPT",
    "ProfileAssistantDraft",
    "ProfileChange",
    "ProfileExtraction",
    "ProfilePatchAction",
    "merge_profile_extraction",
    "merge_profile_extractions",
    "deterministic_profile_extraction",
]
