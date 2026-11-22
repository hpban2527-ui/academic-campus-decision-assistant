"""Conservative audience classification for the operational dataset (no model, no guessing).

An announcement either states nothing about its audience, opens the activity to students in general,
restricts it in a way the data can check (cohorts/programs extracted into audience_scope), or restricts
it in free text that this project cannot verify for a given student (another faculty, one class, a team,
a gender, final-year students, ...). Only the first two and checkable restrictions can be decided by
rule; a free-text restriction stays NEEDS_REVIEW, which keeps the activity out of automatic plans.

All lines of the audience text are kept and examined: exclusions and scoped requirements are often on
later lines.
"""

from __future__ import annotations

import re
import unicodedata

BASIS_NOT_STATED = "NOT_STATED"
BASIS_OPEN = "OPEN_TO_STUDENTS"
BASIS_FIT = "RESTRICTED_TO_FIT"
BASIS_STRUCTURED = "STRUCTURED_SCOPE"
BASIS_FREE_TEXT = "RESTRICTED_FREE_TEXT"
BASIS_UNCLEAR = "UNCLEAR"

_PRIORITY = re.compile(r"ưu tiên[^.;\n]*", re.IGNORECASE)
_FIT = re.compile(r"công nghệ thông tin|\bcntt\b|\bfit\b|khoa học máy tính", re.IGNORECASE)
# "ngành liên quan", "các ngành khác": a vague reference to other fields, not a named programme.
# "trở thành giáo viên": the goal the activity is about, not who may attend.
_NOT_A_RESTRICTION = re.compile(r"ngành\s+(?:có\s+)?liên quan|ngành\s+(?:khác|phù hợp)|trở thành\s+(?:một\s+)?(?:giáo viên|chiến sĩ)")
# An explicit all-students marker, and staff named with their faculty ("giảng viên Khoa CNTT"): the faculty then
# describes the lecturers invited, not a restriction on students.
_ALL_STUDENTS = re.compile(r"toàn trường|toàn thể sinh viên|tất cả sinh viên|mọi sinh viên|toàn bộ sinh viên")
_STAFF_CLAUSE = re.compile(r"(?:giảng viên|cán bộ|nhân viên|thầy cô|giáo sư)\b(?:(?!\s(?:và|hoặc)\s)[^,;\n])*")
_RESTRICTIVE = re.compile(
    r"\bkhoa\s+(?!học\b|các\b)\w|\bngành\s+\w|\blớp\s+\w*\d|\bsinh viên (nam|nữ)\b|năm cuối|tân sinh viên|tân binh"
    r"|chiến sĩ|thành viên (đội|clb|câu lạc bộ|ban)\b|thiếu nhi|sư phạm|giáo viên|chưa đủ 18|dưới 18"
    r"|không (thuộc|khám|được)|đối tượng không|chương trình đề án|chất lượng cao|tài năng(?![^;\n]*còn lại)",
    re.IGNORECASE)
_OPEN = re.compile(r"sinh viên|người học|học viên|tất cả|toàn thể|mọi người|những ai|quan tâm", re.IGNORECASE)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def classify(audience_text: str | None, scope: dict | None) -> dict:
    """{"basis": ..., "lines": [...], "matched": str | None} for the full audience text."""
    scope = scope or {}
    lines = [line.strip() for line in (audience_text or "").splitlines() if line.strip()]
    if scope.get("cohorts") or scope.get("programs"):
        return {"basis": BASIS_STRUCTURED, "lines": lines, "matched": None}
    if not lines:
        return {"basis": BASIS_NOT_STATED, "lines": [], "matched": None}
    text = _NOT_A_RESTRICTION.sub(" ", _PRIORITY.sub(" ", _fold(" \n".join(lines))))
    if _ALL_STUDENTS.search(text):
        text = _STAFF_CLAUSE.sub(" ", text)
    restriction = _RESTRICTIVE.search(text)
    if restriction:
        basis = BASIS_FIT if _FIT.search(text) and not re.search(r"\bkhoa\s+(?!học\b|các\b|công nghệ thông tin)\w",
                                                                  text) else BASIS_FREE_TEXT
        return {"basis": basis, "lines": lines, "matched": restriction.group(0)}
    if _OPEN.search(text):
        return {"basis": BASIS_OPEN, "lines": lines, "matched": None}
    return {"basis": BASIS_UNCLEAR, "lines": lines, "matched": None}


def eligibility(audience: dict, profile: dict) -> str:
    """ELIGIBLE / INELIGIBLE / NEEDS_REVIEW for one synthetic student profile.

    audience is {"basis", "cohorts", "programs"}; profile is {"cohort", "program", "faculty"}.
    """
    basis = audience.get("basis")
    if basis == BASIS_STRUCTURED:
        cohorts, programs = audience.get("cohorts") or [], audience.get("programs") or []
        if cohorts and profile.get("cohort") is None or programs and profile.get("program") is None:
            return "NEEDS_REVIEW"
        if cohorts and profile["cohort"] not in cohorts or programs and profile["program"] not in programs:
            return "INELIGIBLE"
        return "ELIGIBLE"
    if basis in (BASIS_NOT_STATED, BASIS_OPEN):
        return "ELIGIBLE"
    if basis == BASIS_FIT:
        return "ELIGIBLE" if profile.get("faculty") == "FIT" else "INELIGIBLE"
    return "NEEDS_REVIEW"
