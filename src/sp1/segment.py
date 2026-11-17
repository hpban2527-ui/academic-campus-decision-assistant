"""Segment preprocessed announcements into lossless text spans."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .preprocess import Preprocessed

LABELS = {
    "time": ("thời gian", "thời gian diễn ra", "thời gian tổ chức", "ngày diễn ra", "ngày", "lịch", "lịch trình"),
    "place": ("địa điểm", "địa điểm tổ chức", "nơi tổ chức", "địa chỉ"),
    "audience": ("đối tượng", "đối tượng tham gia", "đối tượng tham dự"),
    "mode": ("hình thức", "hình thức tham gia", "hình thức tổ chức"),
    "registration": ("đăng ký", "đăng kí", "đăng ký tham gia", "link đăng ký", "cách thức đăng ký", "form đăng ký"),
    "deadline": ("hạn đăng ký", "hạn đăng kí", "thời gian đăng ký", "thời hạn đăng ký", "hạn chót", "deadline"),
    "fee": ("lệ phí", "phí tham gia", "chi phí", "phí"),
    "recognition": ("quyền lợi", "ghi nhận", "ghi nhận hoạt động"),
    "requirement": ("yêu cầu", "điều kiện", "điều kiện tham gia", "cách thức tham gia"),
    "contact": ("liên hệ", "thông tin liên hệ", "hotline"),
}
_KEY = {name: key for key, names in LABELS.items() for name in names}
_LABEL = rf"(?P<label>{'|'.join(re.escape(name) for name in sorted(_KEY, key=len, reverse=True))})[^\S\n]*[:：]"
_LEADING = r"(?:[^\w\n]|(?:\d+[.)])|_)*"
_FIRST_LABEL = re.compile(_LEADING + _LABEL, re.IGNORECASE)
_INLINE_LABEL = re.compile(r"\s+[-–—•+*>]\s+" + _LEADING + _LABEL, re.IGNORECASE)
_HASHTAG = re.compile(r"#\w+")
_HASHTAGS_ONLY = re.compile(r"\s*(?:#\w+\s*)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_BRACKET_TAG = re.compile(r"\[[^\[\]\n]+\]")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class LabelField:
    key: str
    label: Span
    value: Span
    line_no: int


@dataclass(frozen=True)
class Segments:
    title_candidates: tuple[Span, ...]
    fields: tuple[LabelField, ...]
    body: tuple[Span, ...]
    hashtags: tuple[Span, ...]
    urls: tuple[Span, ...]
    emails: tuple[Span, ...]


def _span(text: str, start: int, end: int) -> Span:
    return Span(start, end, text[start:end])


def _trim(text: str, start: int, end: int) -> Span:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return _span(text, start, end)


def _decorative(character: str) -> bool:
    return character.isspace() or character in "\ufe0e\ufe0f" or unicodedata.category(character)[0] in "PS"


def _title(text: str, line: Span) -> Span:
    start, end = line.start, line.end
    while start < end and text[start] != "[" and _decorative(text[start]):
        start += 1
    while end > start and text[end - 1] != "]" and _decorative(text[end - 1]):
        end -= 1
    return _span(text, start, end)


def _uppercase_title(span: Span) -> bool:
    letters = [character for character in span.text if character.isalpha()]
    return bool(letters) and 5 * sum(character.isupper() for character in letters) >= 3 * len(letters)


def _titles(text: str, lines: list[Span]) -> list[tuple[Span, tuple[int, ...]]]:
    candidates = []
    for line in lines:
        title = _title(text, line)
        if title.text:
            candidates.append((title, (line.start,)))
    if not candidates:
        return []
    first, *rest = candidates
    ranked = [first]
    if rest and _BRACKET_TAG.fullmatch(first[0].text):
        following = rest[0]
        ranked.append((_span(text, first[0].start, following[0].end), first[1] + following[1]))
    ranked.extend(sorted(rest, key=lambda candidate: not _uppercase_title(candidate[0])))
    return ranked[:3]


def segment(pre: Preprocessed) -> Segments:
    text = pre.text
    lines = []
    offset = 0
    for line in text.split("\n"):
        lines.append(_span(text, offset, offset + len(line)))
        offset += len(line) + 1

    fields = []
    body = []
    before_labels = []
    index = 0
    while index < len(lines):
        line = lines[index]
        first = _FIRST_LABEL.match(line.text)
        inline = list(_INLINE_LABEL.finditer(line.text, first.end() if first else 0))
        matches = ([first] if first else []) + inline
        if not line.text.strip() or _HASHTAGS_ONLY.fullmatch(line.text):
            index += 1
            continue
        if not matches:
            body.append(line)
            if not fields:
                before_labels.append(line)
            index += 1
            continue

        if first is None:
            prefix = _trim(text, line.start, line.start + matches[0].start())
            if prefix.text:
                body.append(prefix)
                if not fields:
                    before_labels.append(prefix)
        line_no = index + 1
        index += 1
        last_end = line.end
        while index < len(lines):
            following = lines[index]
            if (not following.text.strip() or _HASHTAGS_ONLY.fullmatch(following.text)
                    or _FIRST_LABEL.match(following.text) or _INLINE_LABEL.search(following.text)):
                break
            last_end = following.end
            index += 1

        for position, match in enumerate(matches):
            label = _span(text, line.start + match.start("label"), line.start + match.end("label"))
            value_end = line.start + matches[position + 1].start() if position + 1 < len(matches) else last_end
            value = _trim(text, line.start + match.end(), value_end)
            fields.append(LabelField(_KEY[label.text.lower()], label, value, line_no))

    titles = _titles(text, before_labels)
    title_lines = {start for _, starts in titles for start in starts}
    return Segments(
        title_candidates=tuple(title for title, _ in titles),
        fields=tuple(fields),
        body=tuple(_trim(text, line.start, line.end) for line in body if line.start not in title_lines),
        hashtags=tuple(_span(text, *match.span()) for match in _HASHTAG.finditer(text)),
        urls=tuple(_span(text, match.start(), match.start() + len(match[0].rstrip(").,;!?")))
                   for match in _URL.finditer(text)),
        emails=tuple(_span(text, *match.span()) for match in _EMAIL.finditer(text)),
    )
