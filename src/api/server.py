"""FastAPI Server for Academic Campus Decision Assistant (SP1 -> SP2).

Integrates:
- SP1 Extractor (14/15 fields extraction draft with metadata & grounding)
- MinHash-LSH Post Deduplicator
- SP2 DRL Rule Engine (Quy chế 1028/QĐ-KHTN-CTSV, caps, confirmed vs projected)
- REST API and Static Web UI serving
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure src is on sys.path
import sys
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from sp1.extractor import extract
from sp1.deduplication import PostDeduplicator
from sp2.drl_engine import evaluate_progress, evaluate_rule_conditions

DATA_DIR = ROOT_DIR / "data"
WEB_DIR = ROOT_DIR / "web"
SCHEMAS_DIR = ROOT_DIR / "schemas"

app = FastAPI(
    title="HCMUS Academic Campus Decision Assistant API",
    description="Backend API integrating SP1 (Information Extraction) -> SP2 (DRL Evaluation)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load data files safely
def load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default

DRL_RULES_CONFIG = load_json(DATA_DIR / "drl_rules.json", {})
STUDENT_PROFILES = load_json(DATA_DIR / "student_profile.json", [])
ACTIVITIES_DATA = load_json(DATA_DIR / "activities.json", [])
SOURCE_POSTS = load_json(DATA_DIR / "source_posts.json", [])

# Initialize MinHash LSH Deduplicator
deduplicator = PostDeduplicator(threshold=0.75, num_perm=128)
for item in SOURCE_POSTS:
    pid = item.get("post_id") or item.get("id")
    txt = item.get("raw_content") or item.get("content") or item.get("text")
    if pid and txt:
        deduplicator.index_post(pid, txt)

# Default Student Baseline State for Demo (Lưu Minh Tiến)
DEFAULT_STUDENT_ID = "25127242"
STUDENT_BASELINE = {
    "student_id": "25127242",
    "full_name": "Lưu Minh Tiến",
    "class": "25C09",
    "major": "Khoa học Máy tính / CNTT",
    "term": "HK1/2026-2027",
    "category_scores": {
        "C1": {"current": 20, "max": 30, "name": "Học tập & NCKH"},
        "C2": {"current": 15, "max": 20, "name": "Chấp hành quy chế & nội quy"},
        "C3": {"current": 22, "max": 25, "name": "Chính trị - Xã hội, VH-VN, TDTT"},
        "C4": {"current": 10, "max": 25, "name": "Hoạt động vì cộng đồng"},
        "C5": {"current": 0, "max": 30, "name": "Khuyến khích cộng thêm"},
    },
    "verified_activities_count": 8,
}

# In-memory session activities and review queue
session_activities: list[dict[str, Any]] = list(ACTIVITIES_DATA)
review_queue: list[dict[str, Any]] = []

# 5 Standardized E2E Test Scenarios (Shared between API and Frontend)
E2E_SCENARIOS = {
    1: {
        "id": 1,
        "name": "Ca 1: Tập huấn PCCC 2026 (Mục 1.9, C1 +5đ)",
        "badge": "Điểm dự kiến",
        "description": "Bài đăng offline đầy đủ thông tin. Chưa nộp minh chứng điểm danh check-in nên ghi nhận Điểm dự kiến.",
        "post_id": "pfbid01_pccc_new_2026",
        "publisher": "Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/osa.hcmus/posts/pccc_training_2026",
        "evidence": False,
        "rule_override": "auto",
        "raw_content": """CHUYÊN ĐỀ TẬP HUẤN KIẾN THỨC, KỸ NĂNG VÀ THỰC TẬP PHƯƠNG ÁN PHÒNG CHÁY CHỮA CHÁY NĂM 2026
Thời gian: 14:00 - 16:30 ngày 28/10/2026
Thời hạn đăng ký: từ 25/10 đến 27/10/2026
Địa điểm: Giảng đường 1, Cơ sở 227 Nguyễn Văn Cừ
Đối tượng tham gia: Sinh viên hệ chính quy toàn trường
Lệ phí: Miễn phí tham gia. Đây là hoạt động không bắt buộc.
Quyền lợi: Sinh viên được ghi nhận điểm rèn luyện (cộng 5 điểm rèn luyện) khi tham gia đầy đủ và điểm danh check-in/check-out cuối buổi.
Link đăng ký: https://forms.gle/pccc2026hcmus""",
    },
    2: {
        "id": 2,
        "name": "Ca 2: Hiến máu tình nguyện (Mục 4.2, C4 +10đ)",
        "badge": "Đã xác nhận",
        "description": "Hoạt động vì cộng đồng có giấy chứng nhận hợp lệ. Cộng thẳng vào điểm chính thức Đã xác nhận.",
        "post_id": "pfbid09bloodDonation2026hcmus",
        "publisher": "Hội Sinh Viên Trường ĐH Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/hsv.hcmus/posts/blood2026",
        "evidence": True,
        "rule_override": "auto",
        "raw_content": """NGÀY HỘI HIẾN MÁU TÌNH NGUYỆN - GIỌT HỒNG TỰ NHIÊN ĐỢT 2 NĂM 2026
Thời gian: 07:30 - 11:30 ngày 30/10/2026
Hạn chót đăng ký: 29/10/2026
Hình thức: Trực tiếp
Địa điểm: Sảnh nhà điều hành Cơ sở Linh Trung
Đối tượng tham dự: Toàn thể sinh viên và cán bộ giảng viên
Chi phí: Không thu phí. Hoạt động không bắt buộc.
Quyền lợi: Cộng 10 điểm rèn luyện theo quy chế khi hoàn thành hiến máu và nộp minh chứng giấy chứng nhận.
Đường dẫn đăng ký: https://forms.gle/giothong2026""",
    },
    3: {
        "id": 3,
        "name": "Ca 3: Webinar trực tuyến thiếu ĐK (Quy tắc D16)",
        "badge": "Cần xác minh",
        "description": "Bài đăng Online có công nhận ĐRL nhưng KHÔNG nêu điều kiện hoàn thành. SP1 gắn cờ needs_review:completion_requirements chuyển review_queue.json, 0 điểm cộng.",
        "post_id": "pfbid03onlineMissingReqD16",
        "publisher": "Trung tâm Hướng nghiệp & Tư vấn việc làm HCMUS",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/career.hcmus/posts/webinar303",
        "evidence": False,
        "rule_override": "auto",
        "raw_content": """WEBINAR HƯỚNG NGHIỆP: KỸ NĂNG VIẾT CV VÀ PHỎNG VẤN NGÀNH CNTT
Thời gian: 19:00 - 21:00 ngày 02/11/2026
Hạn đăng ký: 01/11/2026
Hình thức: Trực tuyến
Link tham gia: https://zoom.us/j/9988776655
Đối tượng: Sinh viên Khoa CNTT
Sinh viên tham gia sẽ được ghi nhận vào điểm rèn luyện học kỳ 1.
Lệ phí: Miễn phí. Không bắt buộc.""",
    },
    4: {
        "id": 4,
        "name": "Ca 4: Chạm trần nhóm C3 (Quy tắc CALC_02)",
        "badge": "Áp trần nhóm",
        "description": "Cuộc thi cấp trường R3101 quy chế thưởng +10đ. Nhưng nhóm C3 đang đạt 22/25đ nên bị chặn trần, chỉ cộng tối đa +3đ.",
        "post_id": "pfbid04capLimitTestC3",
        "publisher": "Đoàn Trường ĐH Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/doantruong.hcmus/posts/olympicmaclenin",
        "evidence": True,
        "rule_override": "R3101",
        "raw_content": """HỘI THI OLYMPIC CÁC MÔN KHOA HỌC MÁC - LÊNIN VÀ TƯ TƯỞNG HỒ CHÍ MINH CẤP TRƯỜNG 2026
Thời gian: 08:00 - 11:30 ngày 05/11/2026
Thời hạn đăng ký: từ 25/10 đến 03/11/2026
Hình thức: Offline
Địa điểm: Giảng đường 1, Cơ sở 227 Nguyễn Văn Cừ
Đối tượng: Sinh viên toàn trường
Lệ phí: Miễn phí. Không bắt buộc.
Quyền lợi: Cộng 10 điểm rèn luyện cho thí sinh tham gia đầy đủ và hoàn thành bài thi vòng loại trực tiếp.
Link đăng ký: https://forms.gle/olympic2026""",
    },
    5: {
        "id": 5,
        "name": "Ca 5: Bài đăng trùng lặp (MinHash LSH Deduplicator)",
        "badge": "Chặn trùng",
        "description": "Bài đăng có nội dung tương đồng >= 75% hoặc trùng URL/post_id với sự kiện đã được lưu. Hệ thống phát hiện trùng lặp và từ chối ghi nhận.",
        "post_id": "pfbid02buJY8Rrn2XezSWbCNxpUnfSHX4yDYWi5EgXbngmL1FKiEE47XQarhqVqb4WjERECl",
        "publisher": "Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/osa.hcmus/posts/pfbid02buJY8Rrn2XezSWbCNxpUnfSH",
        "evidence": True,
        "rule_override": "auto",
        "raw_content": """CHUYÊN ĐỀ TẬP HUẤN KIẾN THỨC, KỸ NĂNG VÀ THỰC TẬP PHƯƠNG ÁN PHÒNG CHÁY CHỮA CHÁY NĂM 2026
Thời gian: 14:00 - 16:30 ngày 28/10/2026
Thời hạn đăng ký: từ 25/10 đến 27/10/2026
Địa điểm: Giảng đường 1, Cơ sở 227 Nguyễn Văn Cừ
Đối tượng tham gia: Sinh viên hệ chính quy toàn trường
Lệ phí: Miễn phí tham gia.
Quyền lợi: Sinh viên được ghi nhận 5 điểm rèn luyện khi hoàn thành.""",
    },
}

class EvaluationRequest(BaseModel):
    post_id: str = Field(default="")
    publisher: str = Field(default="P.CTSV ĐH KHTN")
    platform: str = Field(default="facebook")
    date_posted: str = Field(default="2026-10-25")
    url: str = Field(default="https://www.facebook.com/osa.hcmus/posts/example")
    raw_content: str = Field(...)
    has_evidence: bool = Field(default=False)
    rule_override: str = Field(default="auto")
    student_id: Optional[str] = Field(default=DEFAULT_STUDENT_ID)
    current_category_scores: Optional[dict[str, Any]] = Field(default=None)

def get_grade_label(score: float) -> str:
    if score >= 90:
        return "Xuất sắc (90-100)"
    if score >= 80:
        return "Tốt (80-89)"
    if score >= 65:
        return "Khá (65-79)"
    if score >= 50:
        return "Trung bình (50-64)"
    return "Yếu / Kém (<50)"

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "regulation": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id", "1028/QD-KHTN-CTSV"),
        "total_rules": len(DRL_RULES_CONFIG.get("rules", [])),
        "total_activities": len(session_activities),
        "total_review_queue": len(review_queue),
        "indexed_posts_in_lsh": len(deduplicator.minhashes),
    }

@app.get("/api/students")
def get_students_list():
    """Return available student profiles for login/switching."""
    return [
        {
            "student_id": s.get("student_id"),
            "full_name": s.get("full_name"),
            "class": s.get("class", "25C09"),
            "major": s.get("major", "Information Technology"),
            "gpa": s.get("gpa", 4.0),
        }
        for s in STUDENT_PROFILES
    ]

@app.get("/api/profile")
def get_student_profile(student_id: Optional[str] = None):
    target_id = student_id or DEFAULT_STUDENT_ID
    matched_student = next(
        (s for s in STUDENT_PROFILES if s.get("student_id") == target_id),
        None,
    )
    
    if matched_student:
        full_name = matched_student.get("full_name")
        class_name = matched_student.get("class", "25C09")
        major = matched_student.get("major", "Khoa học Máy tính / CNTT")
    else:
        full_name = f"Sinh viên {target_id}"
        class_name = "25C09"
        major = "Công nghệ Thông tin"

    base = {
        "student_id": target_id,
        "full_name": full_name,
        "class": class_name,
        "major": major,
        "term": "HK1/2026-2027",
        "category_scores": {
            "C1": {"current": 20, "max": 30, "name": "Học tập & NCKH"},
            "C2": {"current": 15, "max": 20, "name": "Chấp hành quy chế & nội quy"},
            "C3": {"current": 22, "max": 25, "name": "Chính trị - Xã hội, VH-VN, TDTT"},
            "C4": {"current": 10, "max": 25, "name": "Hoạt động vì cộng đồng"},
            "C5": {"current": 0, "max": 30, "name": "Khuyến khích cộng thêm"},
        },
        "verified_activities_count": 8,
    }
    total_confirmed = sum(c["current"] for c in base["category_scores"].values())
    total_confirmed = min(100, total_confirmed)
    return {
        **base,
        "total_confirmed_score": total_confirmed,
        "grade_label": get_grade_label(total_confirmed),
    }

@app.get("/api/rules")
def get_rules():
    return {
        "regulation": DRL_RULES_CONFIG.get("regulation", {}),
        "scoring_model": DRL_RULES_CONFIG.get("scoring_model", {}),
        "rules": DRL_RULES_CONFIG.get("rules", []),
    }

@app.get("/api/activities")
def get_activities():
    return {
        "activities": session_activities[:30],
        "review_queue": review_queue,
        "total_activities": len(session_activities),
        "total_review_queue": len(review_queue),
    }

@app.get("/api/e2e-cases")
def get_e2e_cases():
    return E2E_SCENARIOS

@app.post("/api/reset")
def reset_session_state():
    """Reset session activities, review queue and deduplicator back to baseline."""
    global session_activities, review_queue, deduplicator
    session_activities = list(ACTIVITIES_DATA)
    review_queue.clear()
    deduplicator = PostDeduplicator(threshold=0.75, num_perm=128)
    for item in SOURCE_POSTS:
        pid = item.get("post_id") or item.get("id")
        txt = item.get("raw_content") or item.get("content") or item.get("text")
        if pid and txt:
            deduplicator.index_post(pid, txt)
    return {"status": "success", "message": "Session reset to initial catalog"}

@app.post("/api/evaluate")
def evaluate_announcement(req: EvaluationRequest):
    source = {
        "publisher": req.publisher,
        "platform": req.platform,
        "URL_post": req.url,
    }

    # 1. Run SP1 Deterministic Extractor first to obtain normalized activity_id & title
    try:
        drafts = extract(req.raw_content, source, posted_date=req.date_posted)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SP1 Extractor error: {str(e)}")

    if not drafts:
        raise HTTPException(status_code=400, detail="Không tìm thấy hoạt động nào trong văn bản thông báo.")

    draft = drafts[0]
    rec = draft["record"]
    meta = draft["meta"]
    current_activity_id = rec.get("activity_id")

    # 2. Deduplication Check (MinHash LSH + Catalog Exact Match)
    # Important: Do not match a post against itself if re-analyzing the same form
    is_duplicate = False
    dup_match_id = None
    dup_sim = 0.0

    # Check exact URL or post_id match against existing catalog (excluding itself)
    for act in session_activities:
        act_id = act.get("activity_id")
        act_src = act.get("source", {})
        # If this post was created in the current request or shares the exact ID of current form
        if act_id and act_id == current_activity_id and req.post_id == act_id:
            continue
        if (req.url and act_src.get("URL_post") == req.url and act_id != req.post_id and act_id != current_activity_id) or \
           (req.post_id and act_id == req.post_id and act_id in [s.get("post_id") for s in SOURCE_POSTS]):
            is_duplicate = True
            dup_match_id = act_id
            dup_sim = 1.0
            break

    # LSH match against existing indexed posts (excluding itself)
    if not is_duplicate and req.raw_content:
        match = deduplicator.find_duplicate(req.raw_content)
        if match:
            cand_id, sim = match
            # Ensure it is matching a DIFFERENT existing post in the database, not itself!
            if sim >= 0.75 and cand_id != req.post_id and cand_id != current_activity_id:
                is_duplicate = True
                dup_match_id = cand_id
                dup_sim = round(float(sim), 3)

    meta["is_duplicate"] = is_duplicate
    if is_duplicate:
        meta["routed_to"] = f"discarded_duplicate (MinHash LSH sim: {dup_sim}, match: {dup_match_id})"
    else:
        meta["routed_to"] = "activities.json" if meta["status"] == "valid" else "review_queue.json"

    # 3. SP2 Rule Engine Mapping
    rules_list = DRL_RULES_CONFIG.get("rules", [])
    rule_map = {r["rule_id"]: r for r in rules_list if "rule_id" in r}

    matched_rule = None
    if req.rule_override != "auto" and req.rule_override in rule_map:
        matched_rule = rule_map[req.rule_override]
    else:
        title_lower = (rec.get("title") or "").lower()
        content_lower = req.raw_content.lower()

        if "hiến máu" in title_lower or "hiến máu" in content_lower:
            matched_rule = rule_map.get("R42")
        elif any(k in title_lower or k in content_lower for k in ["pccc", "phòng cháy", "kỹ năng", "tập huấn", "chuyên đề"]):
            matched_rule = rule_map.get("R19")
        elif any(k in title_lower or k in content_lower for k in ["olympic", "mác - lênin", "mác-lênin"]):
            matched_rule = rule_map.get("R3101")
        elif any(k in title_lower or k in content_lower for k in ["chạy bộ", "thể thao", "thanh niên khỏe"]):
            matched_rule = rule_map.get("R32")
        elif any(k in title_lower or k in content_lower for k in ["tuyển sinh", "ngày hội việc làm", "hội chợ việc làm"]):
            matched_rule = rule_map.get("R38")
        elif rec.get("domain") == "volunteer" or "tình nguyện" in content_lower:
            matched_rule = rule_map.get("R4301")
        elif any(k in content_lower for k in ["khảo sát", "điều tra xã hội"]):
            matched_rule = rule_map.get("R23")
        elif rec.get("domain") in ["academic", "skills", "career"]:
            matched_rule = rule_map.get("R19")
        else:
            matched_rule = rule_map.get("R19")

    if not matched_rule:
        matched_rule = {
            "rule_id": "R19",
            "criterion_id": "1.9",
            "category_id": "C1",
            "name": "Tham gia hội thảo, chuyên đề kỹ năng hoặc học thuật",
            "points": 5,
            "unit": "per_activity",
            "source": {"document_id": "1028/QD-KHTN-CTSV", "location": "Phụ lục, mục 1.9"},
        }

    category_id = matched_rule.get("category_id", "C1")
    cat_cfg = STUDENT_BASELINE["category_scores"].get(
        category_id, {"current": 0, "max": 25, "name": "Chung"}
    )
    if req.current_category_scores and category_id in req.current_category_scores:
        custom_score = req.current_category_scores[category_id]
        if isinstance(custom_score, dict):
            current_cat_score = custom_score.get("current", cat_cfg["current"])
            cat_cap = custom_score.get("max", cat_cfg["max"])
        elif isinstance(custom_score, (int, float)):
            current_cat_score = custom_score
            cat_cap = cat_cfg["max"]
        else:
            current_cat_score = cat_cfg["current"]
            cat_cap = cat_cfg["max"]
    else:
        current_cat_score = cat_cfg["current"]
        cat_cap = cat_cfg["max"]

    announced_points = rec.get("points")
    rule_points = matched_rule.get("points", 5)

    # 4. Compute SP2 Evaluation Decision
    if is_duplicate:
        decision = "REJECTED_DUPLICATE"
        badge_text = "BỊ TỪ CHỐI: TRÙNG LẶP (DEDUPLICATOR)"
        badge_class = "badge-danger"
        projected_added = 0
        confirmed_added = 0
        cat_after = current_cat_score
        explanation = (
            f"Bài đăng đã được ghi nhận trước đó (trùng lặp với {dup_match_id}, "
            f"độ tương đồng MinHash-LSH đạt {dup_sim * 100:.1f}% >= 75%). "
            f"Hệ thống từ chối cộng điểm lần 2 để đảm bảo tính trung thực theo quy định."
        )
    elif meta["status"] != "valid":
        decision = "NEEDS_REVIEW_CALC_05"
        badge_text = "CHỜ XÁC MINH (CALC_05 / REVIEW QUEUE)"
        badge_class = "badge-warning"
        projected_added = 0
        confirmed_added = 0
        cat_after = current_cat_score
        explanation = (
            f"Theo quy tắc CALC_05 (drl_rules.json) và D16 (sp1_extractor): "
            f"Bản nháp SP1 ở trạng thái '{meta['status']}' do thiếu dữ liệu hoặc cần rà soát "
            f"({', '.join(meta.get('flags', []))}). Hoạt động được lưu vào review_queue.json, "
            f"chưa được cộng điểm dự kiến hoặc xác nhận khi chưa có đủ căn cứ minh chứng."
        )
        # Add to review queue
        if not any(r.get("activity_id") == rec.get("activity_id") for r in review_queue):
            review_queue.append({
                "activity_id": rec.get("activity_id"),
                "title": rec.get("title") or "Thông báo cần rà soát",
                "flags": meta.get("flags", []),
                "date_posted": req.date_posted,
                "url": req.url,
            })
    else:
        # Valid activity -> Apply category cap CALC_02 & Evidence CALC_05
        room = max(0, cat_cap - current_cat_score)
        effective_points = min(rule_points, room)
        is_capped = effective_points < rule_points

        projected_added = 0 if req.has_evidence else effective_points
        confirmed_added = effective_points if req.has_evidence else 0
        cat_after = current_cat_score + effective_points

        if req.has_evidence:
            decision = "CONFIRMED"
            badge_text = "ĐÃ XÁC NHẬN (+ĐIỂM CHÍNH THỨC)"
            badge_class = "badge-success"
            exp_core = f"Sinh viên đã nộp minh chứng xác thực hoàn thành ('{rec.get('completion_requirements') or 'Giấy chứng nhận/Điểm danh'}'). "
        else:
            decision = "PROJECTED"
            badge_text = "ĐIỂM DỰ KIẾN (CHỜ MINH CHỨNG)"
            badge_class = "badge-primary"
            exp_core = f"Chưa có minh chứng hoàn thành. Ghi nhận vào Điểm dự kiến (+{projected_added}đ), chưa cộng vào điểm chính thức. "

        if is_capped:
            exp_cap = (
                f"[Áp trần CALC_02]: Quy chế {matched_rule.get('rule_id')} ban hành mức +{rule_points}đ, "
                f"nhưng nhóm {category_id} ({cat_cfg['name']}) của bạn đang đạt {current_cat_score}/{cat_cap}đ "
                f"(chỉ còn thiếu {room}đ để đạt tối đa). Do đó điểm được ghi nhận tối đa là +{effective_points}đ."
            )
        else:
            exp_cap = f"Áp dụng nguyên vẹn mức +{effective_points}đ theo tiêu chí {matched_rule.get('criterion_id')} ({matched_rule.get('rule_id')})."

        explanation = exp_core + exp_cap

        # Add to valid activities
        if not any(a.get("activity_id") == rec.get("activity_id") for a in session_activities):
            session_activities.insert(0, {
                "activity_id": rec.get("activity_id"),
                "source": rec.get("source"),
                "title": rec.get("title"),
                "domain": rec.get("domain"),
                "start": rec.get("start"),
                "end": rec.get("end"),
                "mode": rec.get("mode"),
                "location": rec.get("location"),
                "points": rec.get("points"),
                "mandatory": rec.get("mandatory"),
                "audience": rec.get("audience"),
                "fee": rec.get("fee"),
                "completion_requirements": rec.get("completion_requirements"),
                "rule_id": matched_rule.get("rule_id"),
                "points_awarded": f"+{confirmed_added if req.has_evidence else projected_added}đ ({'Đã xác nhận' if req.has_evidence else 'Dự kiến'})",
            })
            # Also index in deduplicator
            deduplicator.index_post(rec.get("activity_id"), req.raw_content)

    cat_missing_after = max(0, cat_cap - cat_after)
    total_confirmed_after = min(100, sum(
        (cat_after if cid == category_id else c["current"])
        for cid, c in STUDENT_BASELINE["category_scores"].items()
    ))

    source_info = matched_rule.get("source", {})
    citation = f"Quyết định {source_info.get('document_id', '1028/QD-KHTN-CTSV')}, {source_info.get('location', 'Phụ lục')}"

    return {
        "success": True,
        "sp1": draft,
        "sp2": {
            "decision": decision,
            "badge_text": badge_text,
            "badge_class": badge_class,
            "rule": matched_rule,
            "category_id": category_id,
            "category_name": cat_cfg["name"],
            "announced_points": announced_points,
            "rule_points": rule_points,
            "projected_added": projected_added,
            "confirmed_added": confirmed_added,
            "category_before": current_cat_score,
            "category_after": cat_after,
            "category_cap": cat_cap,
            "category_missing": cat_missing_after,
            "total_score_after": total_confirmed_after,
            "grade_label": get_grade_label(total_confirmed_after),
            "explanation": explanation,
            "citation": citation,
        },
        "dedup": {
            "is_duplicate": is_duplicate,
            "match_id": dup_match_id,
            "similarity": dup_sim,
        },
    }

# Serve Frontend static files if web directory exists
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def serve_index():
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"message": "Web UI index.html not found"}, status_code=404)
