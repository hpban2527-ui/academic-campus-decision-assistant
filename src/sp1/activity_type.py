"""Closed activity taxonomy, independent of recognition and participation."""

import re

from .preprocess import original_span

ACTIVITY_TYPE_VERSION = "1.0.0"
KEYWORDS = (
    ("blood_donation", ("hiến máu",)),
    ("survey", ("khảo sát", "lấy ý kiến", "đánh giá chất lượng đào tạo")),
    ("legal_health_campaign", ("pháp luật", "an toàn giao thông", "phòng chống", "ma túy", "ma tuý",
                              "tệ nạn", "lừa đảo", "phòng cháy", "PCCC", "sức khỏe sinh sản")),
    ("volunteer", ("tình nguyện", "mùa hè xanh", "xuân tình nguyện", "tiếp sức mùa thi", "chiến dịch")),
    ("fundraising", ("quyên góp", "gây quỹ", "ủng hộ", "thiện nguyện")),
    ("career_admissions_event", ("ngày hội việc làm", "tuyển dụng", "hướng nghiệp", "tư vấn tuyển sinh", "job fair", "career")),
    ("club_membership", ("tuyển thành viên", "recruitment", "tuyển cộng tác viên", "tuyển CTV", "gia nhập")),
    ("culture_sports_competition", ("giải bóng", "giải cờ", "cờ vua", "cờ tướng", "cầu lông", "giải chạy",
                                   "hội thao", "văn nghệ", "giải đấu", "cuộc thi ảnh", "tiktok", "clip", "nhảy", "hát")),
    ("academic_competition", ("cuộc thi", "olympic", "hackathon", "kỳ thi", "contest", "challenge")),
    ("seminar_workshop", ("hội thảo", "chuyên đề", "workshop", "seminar", "tọa đàm", "toạ đàm", "talkshow",
                         "webinar", "tập huấn", "hội nghị", "khóa học", "khoá học")),
    ("mobilization", ("huy động", "lực lượng")),
    ("university_history", ("lịch sử trường", "truyền thống", "tìm hiểu về trường")),
)


def classify(pre, title=None):
    regions = [(0, min(600, len(pre.text)))]
    if title and title in pre.text:
        start = pre.text.index(title)
        regions.append((start, start + len(title)))
    for kind, words in KEYWORDS:
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, words)) + r")(?!\w)", re.I)
        for start, end in regions:
            match = pattern.search(pre.text, start, end)
            if match:
                left, right = original_span(pre, *match.span())
                return {"activity_type": kind, "activity_type_version": ACTIVITY_TYPE_VERSION,
                        "evidence": [{"start": left, "end": right, "text": pre.original[left:right]}]}
    return {"activity_type": "other", "activity_type_version": ACTIVITY_TYPE_VERSION, "evidence": []}
