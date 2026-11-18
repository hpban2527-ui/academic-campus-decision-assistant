"""Normalise Vietnamese announcements and preserve original text offsets."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass

_REMOVED = "\u200b\u200c\u200d\ufeff"
_SPACES = "\u00a0" + "".join(map(chr, range(0x2000, 0x200B))) + "\u202f\u3000"
_TRANSLATE = str.maketrans({**dict.fromkeys(_REMOVED), **dict.fromkeys(_SPACES, " ")})
_PHONE = re.compile(r"(?<![\d/.])(?:\+84|84|0)(?:[ .\-]?\d){8,10}(?![\d/])")
_NON_PHONE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?<!\d)(?:0?[1-9]|[12]\d|3[01])([./-])(?:0?[1-9]|1[0-2])\1\d{4}(?!\d)"
    r"|(?<!\d)\d{1,2}(?::|h|g)\d{2}(?!\d)"
    r"|(?<![\d.,])\d[\d.,]*[ ]*(?:đ(?:ồng)?|vnd|vnđ)(?!\w)"
    r"|\b(?:mssv|mã số sinh viên)[ ]*:?[ ]*\d+\b"
    r"|(?<!\d)\d{1,3}(?:[.,]\d{3})*[ ]+(?:sinh viên|người|đội)\b",
    re.IGNORECASE,
)
_MASK = "[phone removed]"
# Bank account numbers (organisation or personal) are not needed by SP1-SP3 and are removed like phones.
_ACCOUNT = re.compile(r"(?:số tài khoản|\bstk)[ ]*:?[ ]*(\d(?:[ .\-]?\d){5,19})(?!\d)", re.IGNORECASE)
_ACCOUNT_MASK = "[account removed]"
_INJECTION = {
    "ignore_instructions": re.compile(
        r"\b(?:ignore|disregard|forget)\s+(?:(?:all|any|the|your)\s+)?(?:previous|prior|above|earlier)\s+"
        r"(?:instructions|rules|prompts?)\b"
        r"|\bbỏ qua\s+(?:(?:mọi|các|tất cả)\s+)?(?:hướng dẫn|chỉ dẫn|yêu cầu)\b",
        re.IGNORECASE,
    ),
    # Only a role label followed by an instruction; "Assistant: ThS. ..." (a teaching assistant) is not one.
    "role_marker": re.compile(
        r"^\s*(?:system|developer)\s*:"
        r"|^\s*(?:assistant|user)\s*:\s*(?:ignore|you|please|output|set|change|update|replace|classify|return|label|mark)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    "prompt_terms": re.compile(r"\b(?:system prompt|you are (?:now )?(?:an?|the) )", re.IGNORECASE),
    "delimiter": re.compile(r"</?\s*announcement\s*>", re.IGNORECASE),
    "code_fence": re.compile(r"\x60{3}"),
}
# Patterns run on a folded copy (NFKC, lower case, no Vietnamese diacritics, "_" as space), so
# full-width letters, missing diacritics and hashtags do not hide them. The folded copy is used for
# detection only; extraction keeps the original text.
_INJECTION_FOLDED = {
    "ignore_instructions": re.compile(
        r"\b(?:ignore|disregard|forget)\s+(?:(?:all|any|the|your)\s+)?(?:previous|prior|above|earlier)\s+"
        r"(?:instructions|rules|prompts?)\b"
        r"|\bbo qua\s+(?:(?:moi|cac|tat ca|toan bo)\s+)?(?:huong dan|chi dan|yeu cau|lenh)\b"
    ),
    "address_to_model": re.compile(
        # No bare verbs such as "nhắn": folded "vòng tay nhân ái" reads "nhan ai".
        r"\b(?:ghi chu|luu y|chu y|note)\s*(?:cho|danh cho|gui|to|for)?\s*(?:he thong\s*|the\s+)?"
        r"(?:ai|mo hinh|model|llm|chatbot|tro ly ao)\b"
    ),
    "override_context": re.compile(
        r"\b(?:dung|khong)\s+(?:su\s+)?dung\s+(?:cac\s+)?thong tin\s+(?:o\s+)?(?:tren|phia tren)\b"
        r"|\bdo not use the (?:information|text) above\b"
    ),
    "field_command": re.compile(
        r"\b(?:set|mark|label|classify|output)\b[^.\n]{0,40}\b(?:mode|online|offline|post_type|info_only|json)\b"
        r"|\b(?:mode|diem|post_type|window_open)\s*="
    ),
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("đ", "d").replace("_", " ")
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", text)


def injection_flags(text: str) -> tuple[str, ...]:
    """injection_suspected:<kind> flags from the original and the folded text (deduplicated, stable order)."""
    folded = _fold(text)
    kinds = [key for key, pattern in _INJECTION.items() if pattern.search(text)]
    kinds += [key for key, pattern in _INJECTION_FOLDED.items() if pattern.search(folded)]
    return tuple(f"injection_suspected:{key}" for key in dict.fromkeys(kinds))


@dataclass(frozen=True)
class Preprocessed:
    original: str
    text: str
    to_original: tuple[int, ...]
    masked: tuple[tuple[int, int, str], ...]
    flags: tuple[str, ...]


def _normalise(raw: str) -> tuple[str, list[int]]:
    chunks = []
    mapping = []
    index = 0
    while index < len(raw):
        start = index
        index += 1
        if raw[start] == "\r" and raw[index:index + 1] == "\n":
            index += 1
        while index < len(raw) and unicodedata.combining(raw[index]):
            index += 1
        cluster = raw[start:index].replace("\r\n", "\n").replace("\r", "\n")
        normalised = unicodedata.normalize("NFC", cluster).translate(_TRANSLATE)
        chunks.append(normalised)
        mapping.extend([start] * len(normalised))
    return "".join(chunks), mapping


def _phone_matches(text: str):
    protected = [match.span() for match in _NON_PHONE.finditer(text)]
    for match in _PHONE.finditer(text):
        if not any(match.start() < end and start < match.end() for start, end in protected):
            yield match


def _mask_spans(text: str):
    accounts = [(m.start(1), m.end(1), "account", _ACCOUNT_MASK) for m in _ACCOUNT.finditer(text)]
    phones = [(m.start(), m.end(), "phone", _MASK) for m in _phone_matches(text)
              if not any(m.start() < end and start < m.end() for start, end, _, _ in accounts)]
    return sorted(accounts + phones)


def preprocess(raw: str) -> Preprocessed:
    text, source_offsets = _normalise(raw)
    chunks = []
    offsets = []
    masked = []
    previous = 0
    for start, end, kind, mask in _mask_spans(text):
        chunks.extend((text[previous:start], mask))
        offsets.extend(source_offsets[previous:start])
        masked.append((len(offsets), len(offsets) + len(mask), kind))
        offsets.extend([source_offsets[start]] * len(mask))
        previous = end
    chunks.append(text[previous:])
    offsets.extend(source_offsets[previous:])
    offsets.append(len(raw))
    text = "".join(chunks)
    flags = injection_flags(text)
    return Preprocessed(raw, text, tuple(offsets), tuple(masked), flags)


def original_span(pre: Preprocessed, start: int, end: int) -> tuple[int, int]:
    """Map a half-open span back to its covering original clusters."""
    if not 0 <= start <= end <= len(pre.text):
        raise ValueError("Span is outside the preprocessed text")
    left = pre.to_original[start]
    if start == end:
        return left, left
    # A cluster or a phone placeholder can occupy multiple normalised characters.
    last = pre.to_original[end - 1]
    boundary = bisect_right(pre.to_original, last)
    right = pre.to_original[boundary]
    while right > left and pre.original[right - 1] in _REMOVED:
        right -= 1
    return left, right
