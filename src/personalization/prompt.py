"""Prompt construction for the preference interpreter."""

from __future__ import annotations

from personalization.models import (
    CampusId,
    CategoryId,
    ModeId,
    PlanningStrategy,
    TimeSlotId,
    TopicId,
)


def build_system_prompt() -> str:
    topics = _values(TopicId)
    categories = _values(CategoryId)
    campuses = _values(CampusId)
    modes = _values(ModeId)
    time_slots = _values(TimeSlotId)
    strategies = _values(PlanningStrategy)
    return f"""Bạn là bộ chuyển đổi sở thích sinh viên thành dữ liệu có cấu trúc.

NHIỆM VỤ DUY NHẤT
- Đọc mô tả tiếng Việt của sinh viên.
- Trả về đúng JSON Schema được cung cấp.
- Không lập lịch, không tính điểm rèn luyện, không quyết định eligibility và không tạo hoạt động.

GIÁ TRỊ ĐƯỢC PHÉP
- topic_id: {topics}
- category_id: {categories}
- campus_id: {campuses}
- mode: {modes}
- time_slot: {time_slots}
- strategy: {strategies}

QUY TẮC TRỌNG SỐ
- 5: rất ưu tiên / rất thích / ưu tiên hàng đầu.
- 4: ưu tiên / thích.
- 3: có quan tâm nhưng không nhấn mạnh.
- 2: ít ưu tiên.
- 1: không thích nhưng vẫn có thể tham gia.
- Không được tự thêm sở thích mà sinh viên không nói hoặc không suy ra hợp lý.

HARD EXCLUSION
- Chỉ đưa vào hard_exclusions khi sinh viên nói rõ "không thể", "không tham gia được",
  "tuyệt đối không", hoặc một giới hạn tương đương.
- "Không thích offline" là preference thấp, không mặc nhiên là hard exclusion.
- "Ưu tiên online" không có nghĩa là cấm offline.
- "Nếu đi trực tiếp thì thích NVC" không có nghĩa là cấm offline hoặc cấm cơ sở khác.
- Trong câu "ưu tiên online; nếu đi trực tiếp thì thích NVC", online có weight 5 và NVC có weight 4;
  điều kiện "nếu đi trực tiếp" không làm giảm NVC xuống weight 1.
- Một giá trị không được vừa là preference vừa là hard exclusion.

CHUẨN HÓA
- "Nguyễn Văn Cừ", "NVC", "227 Nguyễn Văn Cừ" -> NVC.
- "Đông Hòa", "Dĩ An", "khu đô thị ĐHQG" -> DONG_HOA.
- "trực tuyến", "học từ xa" -> online.
- "mục 1" đến "mục 5" -> C1 đến C5.
- Nếu không có giới hạn thì các field trong limits phải là null.
- Nếu không đề cập một nhóm preference thì trả về mảng rỗng.
- Tuyệt đối không điền tất cả lựa chọn với weight 1 để thay cho một nhóm không được đề cập.
- Không đề cập thời gian thì time_preferences phải là mảng rỗng.
- Nếu không xác định chiến lược, dùng BALANCED.
- Luôn trả đủ mọi field của schema, không kèm văn bản giải thích ngoài JSON.
"""


def _values(enum_type: type) -> str:
    return ", ".join(item.value for item in enum_type)
