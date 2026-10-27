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
    from sp2.drl_engine import audit_rules_config
    rule_issues = audit_rules_config(DRL_RULES_CONFIG)
    return {
        "status": "degraded" if any(x["severity"] == "error" for x in rule_issues) else "healthy",
        "rule_audit_issues": rule_issues,
        "rule_audit_count": len(rule_issues),
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
        "demo_only": True,
        "official_score_verified": False,
        "score_source": "SYNTHETIC_DEMO_BASELINE",
        "grade_label": "DEMO - " + get_grade_label(total_confirmed),
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
    """Real SP1 extraction; no score is awarded from a post or checkbox alone."""
    from api.lead_contract import canonical_url, prepare_publication

    source = {"publisher": req.publisher, "platform": req.platform, "URL_post": req.url}
    try:
        drafts = extract(req.raw_content, source, posted_date=req.date_posted)
        if not drafts:
            raise HTTPException(status_code=422, detail="No activity detected in announcement")
        draft = prepare_publication(drafts[0])
    except HTTPException:
        raise
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"SP1 input/contract error: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"SP1 extraction error: {exc}")

    rec, meta = draft["record"], draft["meta"]
    normalized = canonical_url(req.url)
    dup_match_id, dup_sim = None, 0.0
    # Re-analysis of an already collected post is a duplicate, including the
    # same post_id: never count identical content twice.
    for post in SOURCE_POSTS:
        try:
            same_url = canonical_url(post.get("url", "")) == normalized
        except ValueError:
            same_url = False
        if (req.post_id and req.post_id == post.get("post_id")) or same_url:
            dup_match_id, dup_sim = post.get("post_id"), 1.0
            break
    if dup_match_id is None:
        match = deduplicator.find_duplicate(req.raw_content)
        if match and match[1] >= 0.75:
            dup_match_id, dup_sim = match
    is_duplicate = dup_match_id is not None
    meta["is_duplicate"] = is_duplicate
    meta["routed_to"] = "discarded_duplicate" if is_duplicate else "review_queue"
    if is_duplicate:
        decision = "REJECTED_DUPLICATE"
        explanation = "Bài đăng trùng dữ liệu đã thu thập; không cộng điểm."
    elif meta.get("status") != "valid" or meta.get("flags"):
        decision = "NEEDS_REVIEW"
        explanation = "Trích xuất chưa đủ tin cậy: cần kiểm tra nguồn và trường bị gắn cờ."
    else:
        decision = "PENDING_REVIEW"
        explanation = "Đã trích xuất. Cần người duyệt nguồn, điều kiện, quy tắc ĐRL và minh chứng hoàn thành trước khi tính điểm."
    if req.has_evidence:
        explanation += " Ô chọn 'có minh chứng' chỉ là khai báo của người dùng, chưa phải chứng thực."

    # An arbitrary dropdown rule ID is not verified eligibility evidence.
    # Only the separate student-snapshot endpoint invokes the real SP2 rules
    # engine and clearly labels its result as a demo until externally verified.
    suggestion = None
    if req.rule_override and req.rule_override != "auto":
        suggestion = next((r for r in DRL_RULES_CONFIG.get("rules", [])
                           if r.get("rule_id") == req.rule_override), None)
        if suggestion is not None:
            explanation += f" Quy tắc {req.rule_override} do người dùng chọn, chưa được xác nhận áp dụng."
    if not is_duplicate and not any(x.get("activity_id") == rec["activity_id"] for x in review_queue):
        review_queue.append({
            "activity_id": rec["activity_id"], "title": rec["title"],
            "flags": meta.get("flags", []) + ["source_review_required"],
            "url": rec["source"]["URL_post"], "date_posted": req.date_posted,
        })
    score_cap = None
    rule_category = suggestion.get("category_id") if suggestion else None
    if rule_category:
        score_cap = next((c.get("max_score") for c in DRL_RULES_CONFIG.get("scoring_model", {}).get("category_caps", [])
                          if c.get("category_id") == rule_category), None)
    return {
        "success": True,
        "sp1": draft,
        "sp2": {
            "decision": decision,
            "badge_text": {
                "REJECTED_DUPLICATE": "BÀI ĐĂNG TRÙNG",
                "NEEDS_REVIEW": "CẦN KIỂM TRA DỮ LIỆU",
                "PENDING_REVIEW": "CHỜ DUYỆT / CHƯA CỘNG ĐIỂM",
            }[decision],
            "badge_class": "badge-warning",
            "rule": suggestion,
            "category_id": rule_category,
            "category_name": "Chưa xác minh" if not rule_category else rule_category,
            "announced_points": rec.get("points"),
            "rule_points": None,
            "projected_added": 0,
            "confirmed_added": 0,
            "category_before": None,
            "category_after": None,
            "category_cap": score_cap,
            "category_missing": None,
            "total_score_after": None,
            "grade_label": "Chưa xác minh",
            "explanation": explanation,
            "citation": "Nguồn ĐRL cần được kiểm chứng độc lập; không có điểm được xác nhận tại bước này.",
        },
        "dedup": {"is_duplicate": is_duplicate, "match_id": dup_match_id, "similarity": round(float(dup_sim), 4)},
    }


class VerifiedSnapshotRequest(BaseModel):
    student_profile: dict[str, Any]
    student_snapshot: dict[str, Any]
    scope: dict[str, Any]
    personal_targets: Optional[dict[str, float]] = None
    required_fields: list[str] = Field(default_factory=list)
    demo: bool = True


@app.post("/api/sp2/evaluate")
def evaluate_verified_snapshot(req: VerifiedSnapshotRequest):
    """SP2 rule-to-progress bridge on an explicitly marked demo snapshot.

    Client-supplied evidence_status=VERIFIED is not independent proof of actual
    student performance, so real awards cannot be certified by this endpoint.
    """
    from sp2.drl_engine import DRLEngineError, evaluate_rules_progress
    if not req.demo:
        raise HTTPException(status_code=422, detail="Only demo snapshots are supported; official proof is not connected")
    try:
        report = evaluate_rules_progress(
            DRL_RULES_CONFIG, req.student_profile, req.student_snapshot,
            scope=req.scope, personal_targets=req.personal_targets,
            required_fields=req.required_fields,
        )
    except (DRLEngineError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "disclaimer": "Calculated from submitted example. Not an official DRL award or verified academic record.",
        "sp2": report,
    }



class DemoPipelineRequest(BaseModel):
    case_id: int = 1
    with_demo_confirmation: bool = False


@app.post("/api/pipeline/demo")
def evaluate_end_to_end_demo(req: DemoPipelineRequest):
    """SP1 post -> reviewed 14-field candidate -> SP2, for a labeled fixture.

    This deliberately accepts no client-provided reviewer, approval or proof.
    Real school-awarded points cannot be authorized through this endpoint.
    """
    from api.lead_contract import prepare_publication
    from api.reviewed_pipeline import fingerprint, evaluate_reviewed_activity
    from jsonschema import ValidationError

    if req.case_id != 1:
        raise HTTPException(status_code=422, detail="Only reviewed demo fixture 1 is available")
    case = E2E_SCENARIOS[1]
    source = {"publisher": case["publisher"], "platform": case["platform"], "URL_post": case["url"]}
    drafts = extract(case["raw_content"], source, posted_date=case["date_posted"])
    if not drafts:
        raise HTTPException(status_code=422, detail="Demo extraction returned no records")
    candidate = prepare_publication(drafts[0])
    activity = candidate["record"]
    schema = load_json(SCHEMAS_DIR / "activity.schema.json", {})
    # Demo fixture approval follows the extracted deterministic record; it is
    # NOT evidence of a real reviewer or university award.
    simulated_approval = {
        "decision": "APPROVED", "activity_id": activity["activity_id"],
        "fingerprint": fingerprint(activity),
        "source_url": activity["source"]["URL_post"],
        "reviewer_id": "SYNTHETIC_REVIEWER_FIXTURE",
        "reviewed_at": "2026-10-27T12:00:00+07:00",
        "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
        "rule_id": "R19",
    }
    student_profile = {"student_id": "demo-student-001", "university": "HCMUS"}
    baseline = {
        "student_id": student_profile["student_id"],
        "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
        "category_scores": {"C1": 20, "C2": 0, "C3": 0, "C4": 0, "C5": 0},
        "included_activity_ids": [],
    }
    participation = None
    if req.with_demo_confirmation:
        participation = {
            "student_id": student_profile["student_id"],
            "activity_id": activity["activity_id"],
            "status": "CONFIRMED", "evidence_status": "VERIFIED",
            "verifier_id": "SYNTHETIC_EVIDENCE_FIXTURE",
            "verified_at": "2026-10-27T12:00:00+07:00",
            "evidence_ref": "synthetic://fixture/checkin-01",
        }
    try:
        result = evaluate_reviewed_activity(
            record=activity, metadata=candidate["meta"],
            approval=simulated_approval, participation=participation,
            baseline=baseline, student_profile=student_profile,
            rules_config=DRL_RULES_CONFIG, schema=schema,
        )
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "mode": "DEMO_ONLY", "source": "SYNTHETIC_SCENARIO_1",
        "official_award_verified": False,
        "activity": candidate,
        "sp2": result,
    }


@app.get("/api/lead/audit")
def lead_data_audit():
    """Quick read-only audit. Audits are not official rule certification."""
    from api.lead_contract import audit_dataset
    from sp2.drl_engine import audit_rules_config
    return {
        "mode": "DEMO_ONLY",
        "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
        "applicability_current_semester": "NEEDS_SCHOOL_CONFIRMATION",
        "regulation_issues": audit_rules_config(DRL_RULES_CONFIG),
        "rules_needing_review": [r["rule_id"] for r in DRL_RULES_CONFIG.get("rules", [])
                               if r.get("status") != "verified"],
        "dataset": audit_dataset(ACTIVITIES_DATA),
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
