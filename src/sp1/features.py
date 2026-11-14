"""Derive personalization features (topics, campus, time tags) from SP1 activities (ADR-0002 D19).

Deterministic and keyword-based; no model. The enums are Ngoc's personalization module
(`personalization.models`: TopicId, CampusId, TimeSlotId), so the output loads with
`personalization.scoring.load_activity_features`. Features are a ranking aid, never a claim about points,
eligibility or the regulation: a wrong topic can only change the order of suggestions.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

LABEL = "auto_derived_not_human_reviewed"
MAX_TOPICS = 3
CAMPUS_BY_SP1 = {"CS1": "NVC", "CS2": "DONG_HOA"}
# activity_type -> topic that always applies. Only types whose topic is beyond doubt are listed:
# legal_health_campaign covers legal, safety and health alike, so its topic comes from the title.
TYPE_TOPICS = {
    "blood_donation": ("health",), "volunteer": ("volunteer",), "fundraising": ("volunteer",),
    "career_admissions_event": ("career",), "academic_competition": ("research",),
    "culture_sports_competition": ("culture",), "mobilization": ("civic_education",),
    "university_history": ("civic_education",),
}
# domain -> topic.
DOMAIN_TOPICS = {"academic": ("research",), "career": ("career",), "skills": ("soft_skills",),
                 "volunteer": ("volunteer",), "culture_sports": ("culture",)}
# Title keywords -> topic: (topic, phrases matched anywhere, words matched whole). A short word such as
# "ai" must be whole, otherwise it matches inside "dai loan" or "tai chinh".
TITLE_TOPICS = (
    ("mathematics", ("toan hoc", "toan tin", "xac suat", "thong ke", "giai tich", "dai so", "olympic toan",
                     "mathematic", "statistic"), ("math",)),
    ("artificial_intelligence", ("tri tue nhan tao", "machine learning", "deep learning", "hoc may",
                                 "generative", "chatgpt"), ("ai",)),
    ("technology", ("cong nghe", "lap trinh", "tin hoc", "chuyen doi so", "nang luc so", "ky nang so", "web3",
                    "du lieu", "data", "software", "digital", "engineering", "quantum")),
    ("research", ("nghien cuu", "seminar", "hoi nghi khoa hoc", "hoi thao khoa hoc", "khoa hoc", "hoc thuat",
                  "research", "conference", "mini-course", "mini course")),
    ("environment", ("moi truong", "song xanh", "da dang sinh hoc", "khi nha kinh", "tai che", "bao ve rung")),
    ("health", ("suc khoe", "hien mau", "dinh duong", "tam ly", "y te")),
    ("safety", ("an toan", "phong chay", "chua chay", "cuu ho", "ma tuy", "lua dao", "an toan giao thong",
                "phong chong te nan", "bao mat")),
    ("sports", ("the thao", "bong da", "bong ro", "co vua", "co tuong", "chay bo", "giai dau")),
    ("culture", ("van hoa", "van nghe", "am nhac", "nghe thuat", "trung thu", "le hoi")),
    ("civic_education", ("phap luat", "phap ly", "hien phap", "cong dan", "doan tncs", "chinh tri",
                         "mac lenin", "ho chi minh", "nghia vu")),
    ("career", ("viec lam", "huong nghiep", "tuyen dung", "nghe nghiep", "thuc tap sinh", "doanh nghiep"), ("cv",)),
    ("soft_skills", ("ky nang", "giao tiep", "thuyet trinh", "lam viec nhom", "quan ly thoi gian", "tu duy")),
)


def fold(text: str | None) -> str:
    """Lower case, no diacritics, single spaces, padded so " ai " can be matched at the edges."""
    folded = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " " + re.sub(r"[^a-z0-9]+", " ", folded).strip() + " "


def topics(activity: dict, activity_type: str | None) -> list[str]:
    """Up to MAX_TOPICS topic ids: the activity type's topic, then title keywords, then the domain's topic.

    The title is a stronger signal than the broad domain label, so it is read first; the domain only fills
    the remaining places.
    """
    found: list[str] = []
    title = fold(activity.get("title"))
    words = set(title.split())
    ordered = [TYPE_TOPICS.get(activity_type or "", ())]
    ordered += [(topic,) for topic, phrases, *whole in TITLE_TOPICS
                if any(phrase in title for phrase in phrases) or (whole and words & set(whole[0]))]
    for group in ordered:
        for topic in group:
            if topic not in found:
                found.append(topic)
    if len(found) < 2:
        for topic in DOMAIN_TOPICS.get(activity["domain"] or "", ()):
            if topic not in found:
                found.append(topic)
    return found[:MAX_TOPICS]


def campus_id(activity: dict) -> str | None:
    """CampusId, or None when the announcement does not determine one campus."""
    if activity["mode"] == "online":
        return "ONLINE"
    codes = activity.get("campus") or []
    if len(codes) != 1:
        return None                      # several campuses, or none: not determined
    return CAMPUS_BY_SP1.get(codes[0], "OTHER" if codes[0] == "Other" else None)


def time_tags(activity: dict) -> list[str]:
    """One TimeSlotId from the stated opening time; empty when the time is not stated."""
    opening = activity["window"]["open"]
    defaults = activity["meta"].get("time_defaults") or {}
    if not opening or "window_open" in defaults:
        return []
    moment = datetime.fromisoformat(opening)
    day = "weekend" if moment.weekday() >= 5 else "weekday"
    part = "morning" if moment.hour < 12 else "afternoon" if moment.hour < 17 else "evening"
    return [f"{day}_{part}"]


def features(activity: dict, activity_type: str | None) -> dict:
    """The three reviewed-sidecar fields for one activity, in the personalization-features/0.1 shape."""
    return {"topics": topics(activity, activity_type), "campus_id": campus_id(activity),
            "time_tags": time_tags(activity)}
