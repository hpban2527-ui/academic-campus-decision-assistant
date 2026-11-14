"""Deterministic stated-fact extraction with original-text evidence."""

from __future__ import annotations

import re
from datetime import date

from . import dates, regex_baseline as old
from .activity_type import classify
from .normalize import normalize
from .preprocess import preprocess, original_span
from .segment import segment

EXTRACTOR_VERSION = "2.0.0-rules"
FIELDS = (
    "post_type", "title", "domain", "multi_session", "window_open", "window_close",
    "duration_minutes_stated", "registration_deadline", "mode", "location", "audience_text",
    "audience_scope", "mandatory_stated", "recognition_stated", "points_stated", "fee",
    "registration_url", "join_url", "completion_requirements",
)
REGISTER = r"đăng k[ýí]|ghi danh|đóng form|mở đơn|nhận đơn|deadline"
OLD_NOTICE = r"theo thông báo|ngày.+đã|kết quả|vừa qua|đã diễn ra"
ROUND = r"\b(?:vòng\s*(?:1|một|loại|sơ khảo|sơ loại|bảng|chung kết|bán kết|2|hai|3)|buổi\s*(?:1|2|3|một|hai|thứ)|đợt\s*\d|ngày\s*[12]\b|chặng\s*\d|phần thi)"
FIRST = r"\b(?:vòng\s*(?:1|một|loại|sơ khảo|sơ loại)|sơ loại|buổi\s*(?:1|một)|đợt\s*1|ngày\s*1)\b"
ONLINE = r"trực tuyến|\bonline\b|zoom|google meet|ms teams|moodle"
VENUE = r"giảng đường|hội trường|\bphòng\b|\bsân\b|cơ sở|nhà văn hóa|\btòa\b|\btoà\b|\bkhu\b"
HYBRID = r"kết hợp|hybrid|trực tiếp và trực tuyến|trực tuyến và trực tiếp"
DATE = r"\d{1,2}\s*[/.-]\s*\d{1,2}|\d{1,2}\s+tháng\s+\d{1,2}"
BANNERS = {"hỗ trợ truyền thông", "chia sẻ", "repost", "thông báo", "tin tức", "cập nhật"}


def has(pattern, text):
    return re.search(pattern, text, re.I)


def precision(value, defaulted):
    if value is None:
        return None
    return value[:10] if defaulted else value[:16] + "+07:00"


class Reader:
    """One extraction's mutable accumulator, with grounded evidence writes."""

    def __init__(self, post):
        self.pre = preprocess(post["raw_content"])
        self.seg = segment(self.pre)
        self.text = self.pre.text
        self.lines = [line for line in self.text.splitlines() if line.strip()]
        self.record = dict.fromkeys(FIELDS)
        self.record["audience_scope"] = {"cohorts": [], "programs": []}
        self.record["completion_requirements"] = []
        self.methods = dict.fromkeys(FIELDS, "none")
        self.evidence = {}
        self.flags = list(self.pre.flags)
        self.years = []
        self.posted = None
        if post.get("date_posted"):
            try:
                self.posted = date.fromisoformat(post["date_posted"][:10])
            except ValueError:
                self.flags.append("invalid_value:date_posted")

    def put(self, field, value, span=None, method="rule"):
        self.record[field] = value
        self.methods[field] = method
        if span:
            start = self.text.find(span)
            if start < 0:
                raise ValueError(f"Ungrounded evidence for {field}")
            end = start + len(span)
            # Masked phones must not reappear when mapping evidence back to original.
            ranges = [(start, end)]
            for left, right, _ in self.pre.masked:
                ranges = [(a, b) for s, e in ranges for a, b in
                          ((s, min(e, left)), (max(s, right), e)) if a < b]
            evidence = []
            for left, right in ranges:
                a, b = original_span(self.pre, left, right)
                evidence.append({"start": a, "end": b, "text": self.pre.original[a:b]})
            self.evidence[field] = evidence

    def labelled(self, key):
        # A multi-line segment can contain narrative after its labelled value.
        return [field.value.text.split("\n")[0].strip() for field in self.seg.fields
                if field.key == key and field.value.text.strip()]

    def fallback(self, field, result):
        if result["value"] is not None and isinstance(result["evidence"], str):
            self.put(field, result["value"], result["evidence"], "fallback_v1")

    def registration(self, line):
        return bool(old._is_registration_line(line) or has(REGISTER, line))

    def dated(self, line):
        return bool(has(DATE, dates.mask_non_dates(re.sub(r"https?://\S+", "", line))))

    def calendar(self):
        eligible = [line for line in self.lines if not self.registration(line) and not has(OLD_NOTICE, line)]
        times = [value for value in self.labelled("time") if self.dated(value)
                 and not self.registration(value) and not has(OLD_NOTICE, value)]
        schedules = [line for line in eligible if self.dated(line)]
        cues = {m.group().lower() for line in eligible for m in re.finditer(ROUND, line, re.I)}
        multi = True if len(cues) >= 2 or len(set(times)) >= 2 else False if len(schedules) == 1 else None
        self.put("multi_session", multi, schedules[0] if schedules else None)
        span = next((line for line in schedules if has(FIRST, line)), None)
        method = "rule"
        if span is None and times:
            span, method = times[0], "segment"
        if span is None:
            span = next((line for line in schedules if has(
                r"diễn ra|tổ chức|vào lúc|vào ngày|thời gian|bắt đầu|khai mạc|từ ngày", line)), None)
        if span is None:
            candidate = old._time(eligible)["evidence"]
            span = candidate[0] if isinstance(candidate, list) else candidate
            method = "fallback_v1"
        if span:
            try:
                result = dates.parse_range(span, self.posted)
                for field, value, defaulted in (
                    ("window_open", result.start, result.start_defaulted),
                    ("window_close", result.end, result.end_defaulted),
                ):
                    self.put(field, precision(value, defaulted), span, method)
                    if value and result.year_from_posted:
                        self.years.append(field)
                if result.end and result.end < result.start:
                    self.flags.append("end_before_start")
            except dates.DateParseError:
                self.flags.extend(("invalid_value:window_open", "invalid_value:window_close"))
        candidates = self.labelled("deadline") + [
            line for line in self.lines if self.registration(line)
            and has(r"hạn|trước|đến|deadline|đóng form", line)]
        deadline = next((line for line in candidates if self.dated(line)), None)
        deadline_method = "rule"
        if deadline is None:
            deadline = old._deadline(self.lines, self.text)["evidence"]
            deadline_method = "fallback_v1"
        if deadline:
            try:
                if has(r"\btừ\b.+\bđến\b", deadline):
                    result = dates.parse_range(deadline, self.posted)
                    value = precision(result.end, result.end_defaulted)
                else:
                    result = dates.parse_point(deadline, self.posted)
                    value = precision(result.value, result.defaulted)
                self.put("registration_deadline", value, deadline, deadline_method)
                if value and result.year_from_posted:
                    self.years.append("registration_deadline")
            except dates.DateParseError:
                self.flags.append("invalid_value:registration_deadline")
        return span

    def mode_place(self, first):
        modes = self.labelled("mode")
        places = self.labelled("place")
        if places and first:
            anchor = self.text.find(first)
            places.sort(key=lambda p: (self.text.find(p) < anchor, abs(self.text.find(p) - anchor)))
        context = modes[0] if modes else first or ""
        on = bool(has(ONLINE, context))
        off = bool(has(VENUE + r"|trực tiếp|\boffline\b", context))
        if has(HYBRID, context):
            # The guide requires an attendance choice for the same session.
            if has(r"lựa chọn|tùy chọn|hoặc|hybrid", context):
                self.put("mode", "hybrid", context)
            else:
                self.flags.append("needs_review:mode")
        elif on and off:
            self.flags.append("needs_review:mode")
        elif on:
            self.put("mode", "online", context, "segment" if modes else "rule")
        elif off or (modes and has(r"\btại\b", context)):
            self.put("mode", "offline", context, "segment" if modes else "rule")
        else:
            inline = old._inline_venue(self.lines)
            online = old.meeting_link(self.text) or has(r"courses\.hcmus\.edu\.vn|moodle", self.text)
            if online and not places and not inline and not has(VENUE, self.text):
                self.put("mode", "online", online if isinstance(online, str) else online.group())
            elif (places or inline) and not has(ONLINE, self.text):
                self.put("mode", "offline", places[0] if places else inline)
            elif places and has(VENUE, places[0]) and not has(ONLINE, places[0]) and not online:
                # A labelled physical place outweighs an online word elsewhere in the text
                # ("đăng ký online", or injected text); the conflict is left for review.
                self.put("mode", "offline", places[0])
                self.flags.append("needs_review:mode")
            else:
                self.fallback("mode", old._mode(self.lines, self.text))
        if self.record["mode"] != "online":
            venue = places[0].rstrip(".") if places else old._inline_venue(self.lines)
            if venue:
                self.put("location", venue, venue, "segment" if places else "fallback_v1")

    def audience(self):
        values = [field.value.text for field in self.seg.fields if field.key == "audience" and field.value.text.strip()]
        value = values[0] if values else next((line.strip() for line in self.lines if has(
            r"^\s*(?:dành cho|đối tượng|chỉ dành cho)", line)), None)
        if value:
            self.put("audience_text", value, value, "segment" if values else "rule")
        scope_lines = [value] if value else [line for line in self.lines if has(r"\bchỉ\b|dành cho|áp dụng cho", line)]
        scope = {"cohorts": [], "programs": []}
        for line in scope_lines:
            for match in re.finditer(r"\b(?:K\s?(?:20)?|(?:khóa|khoá)\s*(?:20)?)(\d{2})\b", line, re.I):
                if not has("ưu tiên", line[max(0, match.start() - 20):match.start()]):
                    scope["cohorts"].append("K" + match[1])
            for match in re.finditer(r"\b(?:CLC|chất lượng cao|đại trà|chương trình chuẩn)\b", line, re.I):
                if not has("ưu tiên", line[max(0, match.start() - 20):match.start()]):
                    scope["programs"].append("high_quality" if has("CLC|chất lượng cao", match[0]) else "standard")
        scope = {key: list(dict.fromkeys(values)) for key, values in scope.items()}
        self.put("audience_scope", scope)
        if any(scope.values()):
            for line in scope_lines:
                self.put("audience_scope", scope, line)

    def fees(self):
        candidates = self.labelled("fee") + [line for line in self.lines if has(r"phí|đóng|cọc", line)]
        amounts = {}
        for line in candidates:
            for match in re.finditer(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(nghìn|ngàn|đồng|vnđ|vnd|k|đ)\b", line, re.I):
                number = int(re.sub("[.,]", "", match[1]))
                if match[2].lower() in ("k", "nghìn", "ngàn"):
                    number *= 1000
                per = "unknown"
                if has(r"/đội|mỗi đội|/nhóm|mỗi nhóm", line):
                    per = "team"
                elif has(r"/người|/sinh viên|/sv\b|mỗi người|mỗi bạn", line):
                    per = "person"
                amounts[number] = ({"amount_vnd": number, "per": per, "deposit": bool(has("cọc", line))}, line)
        if len(amounts) > 1:
            self.flags.append("needs_review:fee")
        elif old.free_phrase(self.text):
            self.put("fee", 0, old.free_phrase(self.text))
        elif amounts:
            value, evidence = next(iter(amounts.values()))
            self.put("fee", value, evidence)

    def links(self, post_url):
        registration, joining = [], []
        for span in self.seg.urls:
            url = span.text
            line = self.text[self.text.rfind("\n", 0, span.start) + 1:self.text.find("\n", span.end) if "\n" in self.text[span.end:] else len(self.text)]
            if old.is_noise_link(url) or old.strip_scheme(url) == old.strip_scheme(post_url) or has(
                r"xem thêm|chi tiết|tham khảo", line):
                continue
            if old.meeting_link(url) or has(r"courses\.hcmus\.edu\.vn|moodle", url):
                joining.append(url)
            elif has(REGISTER + r"|form|link đăng", line):
                registration.append(url)
            elif has(r"tham gia|tham dự|dự thi|làm bài|link thi|quiz|zoom|meet", line):
                joining.append(url)
        for field, values in (("join_url", joining), ("registration_url", registration)):
            values = old.distinct_links(values)
            if len(values) == 1:
                self.put(field, values[0], values[0])
            elif len(values) > 1:
                self.flags.append(f"needs_review:{field}")
        if not registration and self.record["registration_url"] is None:
            safe = [line for line in self.lines if not has(r"xem thêm|chi tiết|tham khảo", line)]
            candidate = old._registration_url(safe, "\n".join(safe))["evidence"]
            if candidate and candidate != self.record["join_url"] and old.strip_scheme(candidate) != old.strip_scheme(post_url):
                self.put("registration_url", candidate, candidate, "fallback_v1")

    def requirements(self):
        requirements, evidence = [], []
        for line in self.lines:
            if not (old.completion_phrase(line) or has(
                r"(?:ghi nhận|được tính).*(?:khi|nếu|đủ|ít nhất)|tham gia (?:đủ|ít nhất)|nộp ảnh|upload|nộp bài thu hoạch", line)):
                continue
            items = []
            for match in re.finditer(r"(\d{1,3})\s*%", line):
                items.append(("quiz", int(match[1]), "percent"))
            for match in re.finditer(r"(\d+)\s*/\s*(\d+)\s*câu", line):
                items.append(("quiz", int(match[1]), f"of {match[2]} questions"))
            for kind, pattern in (("check_in", r"điểm danh|check[- ]?in"),
                                  ("check_out", r"check[- ]?out"),
                                  ("form", r"khảo sát|biểu mẫu|form phản hồi|form feedback"),
                                  ("proof_upload", r"minh chứng|nộp ảnh|upload|nộp bài thu hoạch")):
                if has(pattern, line):
                    items.append((kind, None, None))
            match = has(r"tham gia (?:đủ|ít nhất)\s+(\d+)\s*(phút|giờ)", line)
            if match:
                items.append(("min_duration", int(match[1]), match[2]))
            deadline = None
            inferred = False
            if items and self.dated(line):
                try:
                    parsed = dates.parse_point(line, self.posted)
                    deadline = precision(parsed.value, parsed.defaulted)
                    inferred = parsed.year_from_posted
                except dates.DateParseError:
                    self.flags.append("invalid_value:completion_requirements")
            for kind, threshold, unit in items:
                item = dict(type=kind, threshold=threshold, unit=unit, deadline=deadline)
                if item not in requirements:
                    if inferred:
                        self.years.append(f"completion_requirements[{len(requirements)}].deadline")
                    requirements.append(item)
                    evidence.append(line)
        if requirements:
            spans = []
            for line in dict.fromkeys(evidence):
                self.put("completion_requirements", requirements, line)
                spans.extend(self.evidence["completion_requirements"])
            self.evidence["completion_requirements"] = spans


def extract_v2(post: dict) -> dict:
    reader = Reader(post)
    text, record = reader.text, reader.record
    for candidate in reader.seg.title_candidates:
        title = re.sub(r"(?:\s*#\w+)+\s*$", "", candidate.text).strip()
        title = re.sub(r"^[^\w\[]+|[^\w\]]+$", "", title)
        if re.fullmatch(r"\[[^\[\]\n]+\]", title):
            title = title[1:-1].strip()
        # A joined candidate beginning with a standalone media banner retains that banner.
        # Prefer the next candidate, which contains the event title itself.
        first_line = title.split("\n")[0].strip("[] ").casefold()
        if first_line in BANNERS:
            continue
        if len(title) >= 4 and title.casefold() not in BANNERS:
            reader.put("title", title, candidate.text, "segment")
            break
    first = reader.calendar()
    for line in reader.lines:
        if has(r"thời lượng|làm bài|kéo dài|trong vòng|trong thời gian", line):
            match = has(r"(?<!\d)(\d{1,3})\s*(phút|p)\b|(?<!\d)(\d{1,2})\s*(giờ|tiếng)\b(?!\s*\d)", line)
            if match:
                value = int(match[1]) if match[1] else int(match[3]) * 60
                reader.put("duration_minutes_stated", value, line)
                break
    reader.mode_place(first)
    reader.audience()
    negative, positive = old.mandatory_negative(text), old.mandatory_positive(text)
    if negative or positive:
        reader.put("mandatory_stated", not bool(negative), negative or positive)
    elif has(r"không tham gia.+(?:bị )?trừ điểm", text):
        reader.put("mandatory_stated", True, has(r"không tham gia.+(?:bị )?trừ điểm", text)[0])
    if old.drl_positive(text) and not old.drl_negative(text):
        reader.put("recognition_stated", True, old.drl_positive(text))
    reader.fallback("points_stated", old._points(text))
    reader.fees()
    reader.links(post["url"])
    reader.requirements()
    reader.fallback("domain", old._domain(text))
    info = has(r"kết quả|tổng kết|vinh danh|chúc mừng|danh sách.*(?:đạt|trúng tuyển|được chọn)|cảm ơn|nhìn lại|recap|khép lại|đã diễn ra",
               "\n".join(reader.lines[:3]))
    participation = (record["registration_url"] or record["join_url"] or reader.labelled("registration")
                     or has(REGISTER + r"|tham gia ngay|mời .{0,20}tham (?:gia|dự)|dự thi", text)
                     or record["recognition_stated"] or record["mandatory_stated"])
    kind = "activity" if participation else "info_only" if info else "insufficient"
    if len(text) < 300 and has(r"(?:\.\.\.\s*Xem thêm|…)\s*$", text):
        kind = "insufficient"
    reader.put("post_type", kind)
    for field in ("title", "mode"):
        if record[field] is None:
            reader.flags.append(f"needs_review:{field}")
    return {
        "post_id": post["post_id"], "method": "rules_v2", "extractor_version": EXTRACTOR_VERSION,
        "layer_a": {"record": record, "year_inferred": list(dict.fromkeys(reader.years)),
                    "flags": list(dict.fromkeys(reader.flags)), "evidence": reader.evidence},
        "classification": classify(reader.pre, record["title"]), "field_methods": reader.methods,
    }


def run_pipeline(post: dict, config=None) -> dict:
    extraction = extract_v2(post)
    source = {key: post.get(key) for key in ("post_id", "publisher", "platform", "date_posted")}
    source["URL_post"] = post["url"]
    return {"extraction": extraction, "activity": normalize(extraction["layer_a"], source, config)}
