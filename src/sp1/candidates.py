"""Lossless, deterministic candidates. IDs identify mentions, not invented values."""

from dataclasses import dataclass

from . import dates
from .preprocess import Preprocessed
from .regex_baseline import is_noise_link
from .segment import Segments


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: str
    text: str
    start: int
    end: int
    line_no: int
    label_key: str | None
    context: str


class CandidateList(list):
    """A list with explicit cap diagnostics, without mutating frozen N0 data."""

    def __init__(self):
        super().__init__()
        self.flags = []


def build_candidates(pre: Preprocessed, seg: Segments) -> list[Candidate]:
    text = pre.text
    masked = dates.mask_non_dates(text)
    # URL paths can contain date-shaped numbers but are not calendar mentions.
    for span in seg.urls:
        masked = masked[:span.start] + " " * (span.end - span.start) + masked[span.end:]
    spans = []
    for rx in (dates._DATE_WORDS, dates._DATE_DOT, dates._DATE_SLASH):
        for match in rx.finditer(masked):
            if not any(match.start() < b and a < match.end() for a, b in spans):
                spans.append(match.span())
    groups = (
        ("date", "D", sorted(spans), 25),
        ("time", "T", [m.span() for m in dates._TIME.finditer(masked)
                       if not any(a <= m.start() < b for a, b in spans)], 15),
        ("url", "U", [(s.start, s.end) for s in seg.urls if not is_noise_link(s.text)], 10),
        ("title", "H", [(s.start, s.end) for s in seg.title_candidates], 3),
    )
    result = CandidateList()
    for kind, prefix, ranges, limit in groups:
        if len(ranges) > limit:
            result.flags.append(f"candidates_truncated:{kind}")
        for number, (start, end) in enumerate(ranges[:limit], 1):
            line_no = text.count("\n", 0, start) + 1
            left = text.rfind("\n", 0, start) + 1
            right = text.find("\n", start)
            right = len(text) if right < 0 else right
            left = max(left, min(start - 60, right - 160))
            context = text[left:min(right, left + 160)]
            label = next((f.key for f in seg.fields
                          if f.label.start <= start < f.value.end), None)
            result.append(Candidate(f"{prefix}{number}", kind, text[start:end], start, end,
                                    line_no, label, context))
    return result
