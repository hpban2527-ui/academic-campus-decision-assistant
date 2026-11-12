"""Regex baseline for SP1 extraction.

Role: (1) comparison baseline for the LLM extractor (R8), (2) fallback when the
LLM is unavailable or its output cannot be parsed (R5), (3) live path for the
web demo (ADR 0001, D7).

Known limitation, by design: it returns ONE activity per announcement. Posts
that describe several activities will be merged or partly missed; this is
measured in the evaluation, not hidden.

Output format ("raw activity", shared with the LLM backend): field ->
{"value": ..., "evidence": str | list[str] | None}. Time fields carry only
evidence spans; dates.py turns them into ISO values.

The phrase helpers (drl_*, mandatory_*, completion_phrase, free_phrase,
venue_kind, meeting_link, ...) are also used by extractor.py to check LLM
output, so each keyword list below is defined once for both paths.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .dates import mask_non_dates

RawActivity = dict[str, dict[str, Any]]


def _words(phrases: Iterable[str]) -> str:
    """Whole-word alternation of phrases (longest first); a space in a phrase matches any whitespace."""
    alts = sorted(phrases, key=len, reverse=True)
    return r"(?<!\w)(?:" + "|".join(r"\s+".join(map(re.escape, p.split())) for p in alts) + r")(?!\w)"


# Keyword lists (whole-word, case-insensitive), team rules R1-R4 (ADR 0001, D9, D13).
PHYSICAL_VENUE = (
    "phòng", "giảng đường", "hội trường", "cơ sở", "sảnh", "sân", "nhà thi đấu", "thư viện",
    "tòa nhà", "khu", "nhà văn hóa",
)
ONLINE_PLATFORM = ("zoom", "google meet", "meet", "ms teams", "microsoft teams", "moodle")
MEETING_HOSTS = ("zoom.us", "meet.google.com", "teams.microsoft.com")
PARTICIPATION_PHRASES = (
    "link tham gia", "đường dẫn tham gia", "đường dẫn dự thi", "link dự thi", "link zoom", "link meet",
)
NOISE_HOSTS = ("facebook.com", "fb.com", "l.facebook.com", "m.facebook.com")

_LEAD = r"^[\W_]*"  # bullets, emoji, dashes before a label
_LABEL_TIME = re.compile(
    _LEAD + r"(?:thời gian|thời điểm|ngày giờ)(?:\s+(?:tổ chức|diễn ra|thực hiện|bắt đầu))?\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)
_LABEL_LOCATION = re.compile(
    _LEAD + r"(?:địa điểm(?:\s+tổ chức)?|nơi tổ chức|tại|địa chỉ)\s*[:：]\s*(.+)$", re.IGNORECASE
)
_LABEL_AUDIENCE = re.compile(
    _LEAD + r"đối tượng(?:\s+(?:tham gia|tham dự))?\s*[:：]\s*(.+)$", re.IGNORECASE
)
_LABEL_MODE = re.compile(_LEAD + r"hình thức(?:\s+(?:tổ chức|tham gia))?\s*[:：]\s*(.+)$", re.IGNORECASE)
_DEADLINE = re.compile(
    r"(?:hạn\s+(?:chót\s+)?đăng\s+k[ýí]|thời\s+hạn\s+đăng\s+k[ýí]|đăng\s+k[ýí]\s+trước|deadline)[^\n]*",
    re.IGNORECASE,
)
# Registration window ("Thời gian mở đơn: từ 19/10 đến 30/10/2026"): its end is the deadline (D15).
_LABEL_REG_WINDOW = re.compile(
    _LEAD + r"(?:thời gian\s+(?:mở đơn|nhận đơn|đăng k[ýí])|thời hạn\s+đăng k[ýí])\s*[:：]\s*(.+)$", re.IGNORECASE
)
_RANGE_END = re.compile(r"(?<!\w)từ\s+.+?\s+đến\s+(.+)$", re.IGNORECASE)
_ANY_DATE = re.compile(r"\d{1,2}\s*[/.-]\s*\d{1,2}|\d{1,2}\s+tháng\s+\d{1,2}", re.IGNORECASE)

_HYBRID = re.compile(r"kết hợp (?:trực tiếp và trực tuyến|trực tuyến và trực tiếp)|\bhybrid\b", re.IGNORECASE)
# A platform counts only as "qua <platform>"; a bare platform, venue or link is left to the
# reconciliation step in extractor.py ("livestream" is not a signal: a hall event may be streamed).
_ONLINE = re.compile(rf"trực tuyến|\bonline\b|qua\s+{_words(ONLINE_PLATFORM)}", re.IGNORECASE)
_OFFLINE_STRONG = re.compile(
    r"\boffline\b|(?:tổ chức|tham gia|tham dự|diễn ra|học)\s+trực tiếp", re.IGNORECASE
)
_OFFLINE_IN_MODE_LINE = re.compile(r"trực tiếp", re.IGNORECASE)
_VENUE = re.compile(_words(PHYSICAL_VENUE), re.IGNORECASE)
_PLATFORM = re.compile(_words(ONLINE_PLATFORM), re.IGNORECASE)
# "tại <venue>" up to the end of the line or a sentence-ending dot (not the dot inside "3.000").
_INLINE_VENUE = re.compile(rf"(?<!\w)tại\s+({_words(PHYSICAL_VENUE)}.*?)\s*(?=\.(?:\s|$)|$)", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<![\w&])#\w")

_POINTS = re.compile(
    r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:điểm\s*(?:rèn\s*luyện|RL|ĐRL)|ĐRL)", re.IGNORECASE
)
_POINTS_NOT_EXACT_BEFORE = re.compile(r"(?:tối đa|đến|từ|\d\s*[-–])\s*$", re.IGNORECASE)

# drl_recognized: one phrase definition, shared by the regex extractor and the LLM evidence check.
# "ghi nhận" may be followed only by these filler words before the object (no free gap, so
# "ghi nhận ý kiến đóng góp về hoạt động" does not count).
_DRL_FILLER = r"(?:tham\s+gia|là|vào|cho|thêm|01|1|một)"
_DRL_OBJECT = r"(?:hoạt\s+động|điểm\s+rèn\s+luyện|rèn\s+luyện|điểm\s+RL(?!\w)|ĐRL(?!\w))"
_DRL_PHRASE = (
    rf"(?<!\w)ghi\s+nhận(?:\s+{_DRL_FILLER})*\s+{_DRL_OBJECT}"
    r"|(?<!\w)(?:cộng|tính|quy\s+đổi)(?:\s+(?:vào|thêm))?(?:\s+\d+(?:[.,]\d+)?)?(?:\s+điểm)?"
    r"\s+(?:rèn\s+luyện|RL|ĐRL)(?!\w)"
    r"|(?<!\w)tích\s+(?:luỹ|lũy|luy)\s+hoạt\s+động"
)
_DRL_POS = re.compile(_DRL_PHRASE, re.IGNORECASE)
_DRL_NEG = re.compile(rf"(?<!\w)không\s+(?:được\s+)?(?:{_DRL_PHRASE})", re.IGNORECASE)
_DRL_NEGATED_BEFORE = re.compile(r"(?<!\w)không\s+(?:được\s+)?$", re.IGNORECASE)

_MANDATORY_POS = re.compile(r"(?<!\w)bắt\s+buộc(?!\w)", re.IGNORECASE)
_MANDATORY_NEG = re.compile(r"(?<!\w)không\s+bắt\s+buộc(?!\w)", re.IGNORECASE)
_MANDATORY_NEGATED_BEFORE = re.compile(r"(?<!\w)không\s+$", re.IGNORECASE)
_MANDATORY_CONTEXT = re.compile(r"tham gia|tham dự|hoàn thành|thực hiện|sinh viên", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[.;!?\n]+")

_FEE_FREE = re.compile(r"miễn\s+phí|không\s+(?:thu|mất)\s+phí|\bfree\b", re.IGNORECASE)
_FEE_PAID = re.compile(
    r"(?:lệ\s+phí|chi\s+phí|(?<!miễn\s)phí)(?:\s+(?:tham\s+gia|tham\s+dự|đăng\s+k[ýí]|vé))?\s*[:：]?\s*"
    r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(k|nghìn|ngàn|đ|đồng|vnđ|vnd)?"
    r"(\s*[-–]\s*\d)?",
    re.IGNORECASE,
)

_COMPLETION = re.compile(
    r"điểm\s+danh|check[\s-]?in|check[\s-]?out|nộp\s+minh\s+chứng|minh\s+chứng"
    r"|\bquiz\b|trả\s+lời\s+câu\s+hỏi|tham\s+(?:gia|dự)\s+đầy\s+đủ"
    r"|hoàn\s+thành\s+(?:bài\s+thi|khảo\s+sát|form|bài)"
    r"|(?:đạt|trả\s+lời\s+đúng|làm\s+đúng|đúng)(?:\s+(?:từ|tối\s+thiểu|ít\s+nhất))?"
    r"\s+\d+\s*/\s*\d+\s+(?:câu\s+hỏi|câu|điểm)"
    r"|(?:đạt|hoàn\s+thành|đúng)(?:\s+(?:từ|tối\s+thiểu|ít\s+nhất|trên))?\s+\d+\s*%"
    r"(?:\s+(?:bài\s+thi|bài|khảo\s+sát))?",
    re.IGNORECASE,
)
# A score threshold is a requirement only in an exam context ("đạt từ 5 điểm trở lên" in a test).
_COMPLETION_SCORE = re.compile(r"(?:đạt|từ|tối\s+thiểu)\s+\d+\s+điểm(?:\s+trở\s+lên)?", re.IGNORECASE)
_EXAM_CONTEXT = re.compile(r"bài\s+thi|câu(?!\s+lạc\s+bộ)|trắc\s+nghiệm|điểm\s+thi", re.IGNORECASE)

# Order matters: the first domain whose keyword appears wins.
_DOMAIN_KEYWORDS: list[tuple[str, re.Pattern]] = [
    ("volunteer", re.compile(r"tình nguyện|hiến máu|mùa hè xanh|xuân tình nguyện|từ thiện", re.IGNORECASE)),
    ("career", re.compile(r"tuyển dụng|việc làm|nghề nghiệp|thực tập|ngày hội doanh nghiệp", re.IGNORECASE)),
    ("skills", re.compile(r"kỹ năng|kĩ năng", re.IGNORECASE)),
    ("culture_sports", re.compile(r"văn nghệ|thể thao|giải bóng|chạy bộ|hội thao|văn hóa|văn hoá", re.IGNORECASE)),
    ("academic", re.compile(r"học thuật|chuyên đề|seminar|nghiên cứu khoa học|olympic|chương trình đào tạo", re.IGNORECASE)),
]

_TITLE_TAG = re.compile(r"^(?:[^\w\[]|_)*(?:\[[^\]]{1,40}\]\s*)*")


def _field(value: Any = None, evidence: Any = None) -> dict[str, Any]:
    return {"value": value, "evidence": evidence}


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(text) if c.strip()]


def _labelled(lines: list[str], rx: re.Pattern) -> str | None:
    for ln in lines:
        m = rx.search(ln)
        if m:
            return m.group(1).strip().rstrip(".;")
    return None


def _first(rx: re.Pattern, text: str) -> str | None:
    m = rx.search(text)
    return m.group(0) if m else None


def _first_not_negated(rx: re.Pattern, negated_before: re.Pattern, text: str) -> str | None:
    for m in rx.finditer(text):
        if not negated_before.search(text, 0, m.start()):
            return m.group(0)
    return None


def _title(lines: list[str]) -> dict[str, Any]:
    for ln in lines:
        cand = _TITLE_TAG.sub("", ln).strip()
        if cand:
            return _field(cand, cand)
    return _field()


def _has_date(text: str) -> bool:
    """A date written outside links, money and score ratios (D15)."""
    return bool(_ANY_DATE.search(mask_non_dates(_URL.sub(" ", text))))


def _is_registration_line(line: str) -> bool:
    return bool(_DEADLINE.search(line) or _LABEL_REG_WINDOW.search(line))


def _time(lines: list[str]) -> dict[str, Any]:
    span = _labelled(lines, _LABEL_TIME)
    if span is not None:
        return _field(None, span)
    # No labelled time line: every other dated line. Several = one activity in rounds (D16),
    # kept as one span per line so that extractor.py parses each round alone.
    dated = [ln for ln in lines if not _is_registration_line(ln) and _has_date(ln)]
    if not dated:
        return _field()
    return _field(None, dated[0] if len(dated) == 1 else dated)


def _deadline(lines: list[str], text: str) -> dict[str, Any]:
    for ln in lines:
        window = _LABEL_REG_WINDOW.search(ln)
        end = window and _RANGE_END.search(window.group(1))
        if end and _has_date(end.group(1)):
            return _field(None, end.group(1).strip().rstrip(".;"))
    m = _DEADLINE.search(text)
    if m and _has_date(m.group(0)):
        return _field(None, m.group(0).strip().rstrip(".;"))
    return _field()


def _mode(lines: list[str], text: str) -> dict[str, Any]:
    mode_line = _labelled(lines, _LABEL_MODE)
    if mode_line:
        if _HYBRID.search(mode_line):
            return _field("hybrid", mode_line)
        on, off = _ONLINE.search(mode_line), _OFFLINE_IN_MODE_LINE.search(mode_line)
        if on and not off:
            return _field("online", mode_line)
        if off and not on:
            return _field("offline", mode_line)
    hyb = _HYBRID.search(text)
    if hyb:
        return _field("hybrid", hyb.group(0))
    online = [  # "đăng ký online" is about registering, not about how the activity is held
        m for m in _ONLINE.finditer(text)
        if not _REGISTER_WORD.search(text[max(0, m.start() - 15): m.end() + 12])
    ]
    offline = list(_OFFLINE_STRONG.finditer(text))
    if online and not offline:
        return _field("online", online[0].group(0))
    if offline and not online:
        return _field("offline", offline[0].group(0))
    return _field()  # none or conflicting signals: leave for review


def _is_noise_line(line: str) -> bool:
    return bool(_HASHTAG.search(line)) or any(is_noise_link(u) for u in urls_in(line))


def _inline_venue(lines: list[str]) -> str | None:
    """First "tại <venue>" whose venue starts with a physical-venue word, outside noise lines (D15)."""
    for ln in lines:
        if _is_noise_line(ln):
            continue
        m = _INLINE_VENUE.search(ln)
        if m:
            return m.group(1)
    return None


def venue_kind(location: str) -> str | None:
    """"physical" (room, hall, campus...), "platform" (Zoom, Meet...), "both", or None."""
    physical, platform = bool(_VENUE.search(location)), bool(_PLATFORM.search(location))
    if physical and platform:
        return "both"
    if physical:
        return "physical"
    return "platform" if platform else None


def _points(text: str) -> dict[str, Any]:
    for m in _POINTS.finditer(text):
        if _POINTS_NOT_EXACT_BEFORE.search(text[max(0, m.start() - 12): m.start()]):
            continue
        return _field(float(m.group(1).replace(",", ".")), m.group(0))
    return _field()


def drl_positive(text: str) -> str | None:
    """First recognition phrase not preceded by "không (được)", else None."""
    return _first_not_negated(_DRL_POS, _DRL_NEGATED_BEFORE, text)


def drl_negative(text: str) -> str | None:
    """First "không (được)" + recognition phrase, else None."""
    return _first(_DRL_NEG, text)


def _drl(text: str) -> dict[str, Any]:
    # Positive first: "về sớm sẽ không được ghi nhận" is a completion condition, not a denial.
    pos = drl_positive(text)
    if pos:
        return _field(True, pos)
    neg = drl_negative(text)
    if neg:
        return _field(False, neg)
    return _field()


def mandatory_positive(text: str) -> str | None:
    """First "bắt buộc" not preceded by "không", else None."""
    return _first_not_negated(_MANDATORY_POS, _MANDATORY_NEGATED_BEFORE, text)


def mandatory_negative(text: str) -> str | None:
    """First "không bắt buộc", else None."""
    return _first(_MANDATORY_NEG, text)


def _mandatory(text: str) -> dict[str, Any]:
    # Per clause, positive first: "Không bắt buộc mặc đồng phục; sinh viên bắt buộc tham gia" -> true.
    clauses = _clauses(text)
    for c in clauses:
        if mandatory_positive(c) and _MANDATORY_CONTEXT.search(c):
            return _field(True, c)
    for c in clauses:
        neg = mandatory_negative(c)
        if neg:
            return _field(False, neg)
    return _field()


def free_phrase(text: str) -> str | None:
    """First explicit "free" statement ("miễn phí", "không thu phí", ...), else None."""
    return _first(_FEE_FREE, text)


def _fee(text: str) -> dict[str, Any]:
    free = _FEE_FREE.search(text)
    paid = [m for m in _FEE_PAID.finditer(text)]
    if free and not paid:
        return _field(0, free.group(0))
    if paid and not free:
        m = paid[0]
        if m.group(3):  # a range such as "50.000 - 100.000": not a single amount
            return _field()
        amount = int(re.sub(r"[.,]", "", m.group(1)))
        if (m.group(2) or "").lower() in ("k", "nghìn", "ngàn"):
            amount *= 1000
        return _field(amount, m.group(0).strip())
    return _field()  # not stated, or contradictory


def completion_phrase(text: str) -> str | None:
    """First completion keyword ("điểm danh", "check-in", "hoàn thành 70% bài thi", "đúng 20/40 câu", ...), else None."""
    found = _first(_COMPLETION, text)
    if found is None and _EXAM_CONTEXT.search(text):
        found = _first(_COMPLETION_SCORE, text)
    return found


def _completion(sentences: list[str]) -> dict[str, Any]:
    # Prefer the condition tied to recognition ("hoàn thành 70% bài thi: được ghi nhận ...").
    hits = [s for s in sentences if completion_phrase(s)]
    best = next((s for s in hits if drl_positive(s)), hits[0] if hits else None)
    if best is None:
        return _field()
    val = best.rstrip(".")
    return _field(val, val)


def _audience(lines: list[str]) -> dict[str, Any]:
    val = _labelled(lines, _LABEL_AUDIENCE)
    return _field([val], val) if val else _field()


def _domain(text: str) -> dict[str, Any]:
    for name, rx in _DOMAIN_KEYWORDS:
        m = rx.search(text)
        if m:
            return _field(name, m.group(0))
    return _field()  # regex cannot tell "other" from "not enough information"


# URLs with a scheme, "www.", or a bare link on a known form/shortener host ("forms.gle/abc").
_URL = re.compile(
    r"(?:https?://|www\.|(?<![\w.@/])(?=(?:forms\.gle|bit\.ly|tinyurl\.com|docs\.google\.com|forms\.office\.com)/))"
    r"[^\s<>\"'()\[\]{}]+",
    re.IGNORECASE,
)
URL_TRAILING = ".,;:!?…"
_REGISTER_WORDS = r"đăng\s*k[ýí]|\bregist(?:er|ration)\b|\bform\b|biểu\s+mẫu"
_REGISTER_WORD = re.compile(_REGISTER_WORDS, re.IGNORECASE)
_LINK_CUE = re.compile(_REGISTER_WORDS + "|" + _words(PARTICIPATION_PHRASES), re.IGNORECASE)
_FORM_HOST = re.compile(r"forms\.gle/|docs\.google\.com/forms|forms\.office\.com/", re.IGNORECASE)


def urls_in(text: str) -> list[str]:
    """Every URL written in the text, case kept, trailing punctuation removed."""
    return [m.group(0).rstrip(URL_TRAILING) for m in _URL.finditer(text)]


def strip_scheme(url: str) -> str:
    """The URL without a leading http:// or https://."""
    return re.sub(r"^https?://", "", url, flags=re.IGNORECASE)


def with_scheme(url: str) -> str:
    """The URL with https:// added if it has no scheme."""
    return url if re.match(r"https?://", url, re.IGNORECASE) else "https://" + url


def _on_hosts(url: str, hosts: Iterable[str]) -> bool:
    """True if the URL's host (without "www.") is one of hosts or a subdomain of one."""
    host = re.split(r"[/?#:]", strip_scheme(url), maxsplit=1)[0].lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == h or host.endswith("." + h) for h in hosts)


def is_noise_link(url: str) -> bool:
    """Facebook links are never the registration link (R3)."""
    return _on_hosts(url, NOISE_HOSTS)


def distinct_links(urls: Iterable[str]) -> list[str]:
    """One entry per link without scheme ("https://x/AbC" and "x/AbC" are one), keeping the form with
    the scheme. Case is kept: links differing only in case stay distinct."""
    by_bare: dict[str, str] = {}
    for u in urls:
        bare = strip_scheme(u)
        if bare not in by_bare or by_bare[bare] == bare:
            by_bare[bare] = u
    return list(by_bare.values())


def meeting_link(text: str) -> str | None:
    """First Zoom / Google Meet / Teams link written in the text, else None."""
    return next((u for u in urls_in(text) if _on_hosts(u, MEETING_HOSTS)), None)


def _cued_urls(lines: list[str]) -> list[str]:
    """URLs on a line with a registration word or participation phrase, or alone on the line after it."""
    found: list[str] = []
    for i, ln in enumerate(lines):
        if not _LINK_CUE.search(_URL.sub(" ", ln)):
            continue
        here = urls_in(ln)
        if here:
            found += here
        elif i + 1 < len(lines):
            nxt = lines[i + 1]
            if urls_in(nxt) and not _URL.sub("", nxt).strip(" -:•" + URL_TRAILING):
                found += urls_in(nxt)
    return found


def _registration_url(lines: list[str], text: str) -> dict[str, Any]:
    """Registration or participation link (R2, R3): a cued link or a meeting link, never a Facebook link.
    Fallback: the only form link in the post. Several distinct candidates -> null
    (ambiguous: left for review rather than guessed)."""
    all_urls = urls_in(text)
    cands = _cued_urls(lines) + [u for u in all_urls if _on_hosts(u, MEETING_HOSTS)]
    cands = [u for u in cands if not is_noise_link(u)]
    if not cands:
        cands = [u for u in all_urls if _FORM_HOST.search(u)]
    links = distinct_links(cands)
    if len(links) != 1:
        return _field()
    return _field(with_scheme(links[0]), links[0])


def extract_raw(text: str) -> list[RawActivity]:
    """Regex extraction of one announcement: a one-item list of raw activities {field: {value, evidence}}."""
    lines = _lines(text)
    sentences = _sentences(text)
    location = _labelled(lines, _LABEL_LOCATION) or _inline_venue(lines)
    return [{
        "URL_registration": _registration_url(lines, text),
        "title": _title(lines),
        "domain": _domain(text),
        "time": _time(lines),
        "registration_deadline": _deadline(lines, text),
        "mode": _mode(lines, text),
        "location": _field(location, location),
        "points": _points(text),
        "drl_recognized": _drl(text),
        "mandatory": _mandatory(text),
        "audience": _audience(lines),
        "fee": _fee(text),
        "completion_requirements": _completion(sentences),
    }]
