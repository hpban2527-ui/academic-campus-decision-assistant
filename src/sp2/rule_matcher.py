"""Estimate an activity-to-rule binding from SP1 text and the SP2 rule catalog.

This module only proposes a rule for a DEMO/PROJECTED score.  It never creates
official evidence or a confirmed award.  Point values and category metadata
always come from ``drl_rules.json`` through the supplied ``rules_config``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata
from typing import Any, Mapping, Optional


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _contains(text: str, *phrases: str) -> bool:
    return any(_normalize(phrase) in text for phrase in phrases)


def _has_token(text: str, *tokens: str) -> bool:
    words = set(text.split())
    return any(_normalize(token) in words for token in tokens)


@dataclass(frozen=True)
class RuleMatch:
    rule: Optional[dict[str, Any]]
    confidence: float
    method: str
    reasons: tuple[str, ...] = ()
    candidates: tuple[dict[str, Any], ...] = ()
    ambiguous: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule.get("rule_id") if self.rule else None,
            "category_id": self.rule.get("category_id") if self.rule else None,
            "points": self.rule.get("points") if self.rule else None,
            "confidence": round(self.confidence, 2),
            "method": self.method,
            "reasons": list(self.reasons),
            "candidates": list(self.candidates),
            "ambiguous": self.ambiguous,
            "point_source": "drl_rules.json" if self.rule else None,
        }


def _candidate(rule: Mapping[str, Any], confidence: float) -> dict[str, Any]:
    return {
        "rule_id": rule.get("rule_id"),
        "category_id": rule.get("category_id"),
        "points": rule.get("points"),
        "confidence": round(confidence, 2),
    }


def _duration_hours(record: Mapping[str, Any]) -> Optional[float]:
    try:
        start = datetime.fromisoformat(str(record.get("start")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(record.get("end")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max(0.0, (end - start).total_seconds() / 3600)


def match_activity_to_rule(
    record: Mapping[str, Any],
    raw_content: str,
    rules_config: Mapping[str, Any],
    *,
    rule_override: str = "auto",
) -> RuleMatch:
    """Return the most plausible positive activity rule from the real catalog.

    High-precision activity signals are evaluated first.  A conservative
    token-overlap fallback compares the announcement with verified rule names.
    The matcher deliberately excludes GPA, discipline and personal-status
    rules because those cannot be inferred from an event announcement.
    """

    rules = {
        str(rule.get("rule_id")): dict(rule)
        for rule in rules_config.get("rules", [])
        if rule.get("status") == "verified"
        and type(rule.get("points")) in (int, float)
        and rule.get("points", 0) > 0
        and rule.get("category_id") in {"C1", "C2", "C3", "C4", "C5"}
    }

    if rule_override and rule_override != "auto":
        rule = rules.get(rule_override)
        if rule is None:
            return RuleMatch(None, 0.0, "invalid_override", (f"Không tồn tại rule {rule_override} đã xác minh.",))
        return RuleMatch(rule, 1.0, "manual_override", ("Rule được chọn thủ công trong chế độ Developer.",))

    text = _normalize(
        " ".join(
            str(x or "")
            for x in (
                record.get("title"),
                record.get("domain"),
                record.get("mode"),
                record.get("completion_requirements"),
                raw_content,
            )
        )
    )

    def choose(rule_id: str, confidence: float, reason: str, alternatives: tuple[str, ...] = ()) -> RuleMatch:
        rule = rules.get(rule_id)
        if rule is None:
            return RuleMatch(None, 0.0, "missing_catalog_rule", (f"Rule {rule_id} không khả dụng.",))
        candidate_rows = [_candidate(rule, confidence)]
        candidate_rows.extend(_candidate(rules[rid], max(0.0, confidence - 0.2)) for rid in alternatives if rid in rules)
        return RuleMatch(rule, confidence, "catalog_signal_match", (reason,), tuple(candidate_rows), bool(alternatives))

    # Specific signals must run before broad words such as "kỹ năng" or "chương trình".
    # A periodic health examination is an administrative/medical service.  It is
    # not, by itself, evidence of the legal/health communication activity in R46
    # or of a physical-training award in R32.  Keep it in review unless a
    # developer/reviewer deliberately supplies a rule override.
    if _contains(text, "khám sức khỏe", "khám sức khoẻ", "kiểm tra sức khỏe định kỳ"):
        return RuleMatch(
            None,
            0.0,
            "uncertain_health_exam",
            ("Khám sức khỏe không mặc nhiên được tính điểm rèn luyện; cần nguồn hoặc quy định xác nhận.",),
        )

    if _contains(text, "hiến máu", "hiến máu tình nguyện", "giọt hồng"):
        return choose("R42", 0.98, "Nội dung xác định hoạt động hiến máu tình nguyện.")

    if _contains(text, "quyên góp", "ủng hộ", "gây quỹ"):
        return choose("R45", 0.9, "Nội dung mô tả hoạt động quyên góp/gây quỹ.")

    if _contains(text, "tình nguyện", "thiện nguyện", "mùa hè xanh", "suất cơm từ thiện"):
        hours = _duration_hours(record)
        if hours is not None and hours >= 24 * 7:
            return choose("R4303", 0.92, "Hoạt động tình nguyện kéo dài từ một tuần trở lên.")
        if hours is not None and hours >= 24:
            return choose("R4302", 0.92, "Hoạt động tình nguyện kéo dài từ 24 giờ đến dưới một tuần.")
        return choose("R4301", 0.84, "Nội dung mô tả hoạt động tình nguyện; tạm ước lượng theo mức ngắn hạn.", ("R4302", "R4303"))

    is_contest = _contains(text, "cuộc thi", "hội thi", "kỳ thi", "olympic", "hackathon", "giải đấu", "vòng thi")
    if is_contest:
        if _contains(text, "mác lênin", "tư tưởng hồ chí minh", "lịch sử", "văn hóa", "văn nghệ", "thể thao", "bóng đá"):
            if _contains(text, "cấp trường", "toàn trường"):
                return choose("R3101", 0.91, "Cuộc thi văn hóa/chính trị/thể thao được tổ chức ở cấp Trường.", ("R3102",))
            return choose("R3102", 0.78, "Cuộc thi văn hóa/chính trị/thể thao; chưa đủ dữ liệu để xác nhận cấp Trường.", ("R3101",))
        if (
            _contains(text, "học thuật", "nghiên cứu", "khoa học", "tin học", "công nghệ", "lập trình", "kỹ năng", "bản lĩnh it")
            or _has_token(text, "ai", "hackathon", "olympic")
        ):
            return choose("R16", 0.86, "Nội dung mô tả cuộc thi học thuật/kỹ năng từ cấp Khoa trở lên.", ("R19",))
        return choose("R16", 0.65, "Nhận diện được cuộc thi nhưng chưa rõ lĩnh vực và cấp tổ chức.", ("R3102",))

    if _contains(text, "tư vấn tuyển sinh", "ngày hội việc làm", "hội chợ việc làm"):
        return choose("R38", 0.94, "Nội dung là hoạt động tư vấn tuyển sinh/việc làm.")

    if _contains(text, "chạy bộ", "thanh niên khỏe", "thử thách sức khỏe", "ngày hội thể dục thể thao"):
        return choose("R32", 0.9, "Nội dung là hoạt động/chứng nhận về sức khỏe thể chất.")

    if _contains(text, "pháp luật", "hiến pháp", "phòng chống tệ nạn", "phòng chống dịch"):
        return choose("R46", 0.88, "Nội dung tuyên truyền pháp luật hoặc phòng chống tệ nạn/dịch bệnh.")

    if _contains(text, "hội thảo", "chuyên đề", "workshop", "tập huấn", "kỹ năng", "hướng nghiệp", "pccc", "phòng cháy"):
        return choose("R19", 0.9, "Nội dung là hội thảo/chuyên đề/tập huấn học thuật hoặc kỹ năng.")

    # Data-driven fallback: compare meaningful tokens in the announcement with
    # the verified rule names.  Only activity-like rules are considered.
    stop = {
        "tham", "gia", "hoat", "dong", "sinh", "vien", "duoc", "cac", "cua", "va", "hoac",
        "cap", "tu", "tro", "len", "trong", "mot", "co", "the", "thanh", "vien", "nha", "truong",
    }
    text_tokens = set(text.split()) - stop
    allowed_units = {"per_activity", "per_activity_period", "per_event", "per_competition"}
    scored: list[tuple[float, dict[str, Any]]] = []
    for rule in rules.values():
        if rule.get("unit") not in allowed_units:
            continue
        name_tokens = set(_normalize(rule.get("name")).split()) - stop
        overlap = text_tokens & name_tokens
        if len(overlap) < 2 or not name_tokens:
            continue
        score = len(overlap) / max(4, len(name_tokens))
        scored.append((score, rule))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("rule_id"))))
    if scored and scored[0][0] >= 0.3:
        best_score, best = scored[0]
        confidence = min(0.74, 0.5 + best_score / 2)
        close = [rule for score, rule in scored[1:3] if best_score - score < 0.08]
        rows = [_candidate(best, confidence)] + [_candidate(rule, max(0.45, confidence - 0.12)) for rule in close]
        return RuleMatch(
            best,
            confidence,
            "rule_name_token_overlap",
            ("Từ khóa của bài đăng trùng với mô tả rule trong drl_rules.json.",),
            tuple(rows),
            bool(close),
        )

    return RuleMatch(None, 0.0, "no_match", ("Chưa đủ tín hiệu để ghép hoạt động với một rule ĐRL.",))


__all__ = ["RuleMatch", "match_activity_to_rule"]
