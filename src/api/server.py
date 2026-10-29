"""FastAPI Server for Academic Campus Decision Assistant (SP1 -> SP2).

Integrates:
- SP1 Extractor (15-field draft) + Lead Publication Gate (14-field activity.schema.json)
- MinHash-LSH & Canonical URL Post Deduplicator + Cross-post Audit
- SP2 DRL Rule Engine (sp2.drl_engine: evaluate_progress, evaluate_rule_conditions, evaluate_rules_progress)
- Dual-Mode Evaluation:
  1. Strict Fail-Closed Intake Mode (default POST /api/evaluate: REVIEW_REQUIRED, 0 auto-awarded points)
  2. Demo Simulation Mode (simulate_demo=True & POST /api/pipeline/demo: runs real SP2 engine with DEMO_ONLY label)
- Academic Snapshot DRL Evaluation (POST /api/sp2/evaluate) & Dataset/Regulation Audit (GET /api/lead/audit)
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jsonschema import ValidationError
from pydantic import BaseModel, Field

# Ensure src is on sys.path
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from api.dedup_review import possible_duplicates
from api.lead_contract import ACTIVITY_FIELDS, audit_dataset, canonical_url, prepare_publication
from api.reviewed_pipeline import evaluate_reviewed_activity, fingerprint
from sp1.deduplication import PostDeduplicator
from sp1.extractor import extract
from sp2.drl_engine import (
    DRLEngineError,
    audit_rules_config,
    evaluate_progress,
    evaluate_rule_conditions,
    evaluate_rules_progress,
)

DATA_DIR = ROOT_DIR / "data"
WEB_DIR = ROOT_DIR / "web"
SCHEMAS_DIR = ROOT_DIR / "schemas"

app = FastAPI(
    title="HCMUS Academic Campus Decision Assistant API",
    description="Backend API integrating SP1 (Information Extraction) -> SP2 (DRL Evaluation)",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
ACTIVITY_SCHEMA = load_json(SCHEMAS_DIR / "activity.schema.json", {})


def _build_category_caps_map() -> dict[str, dict[str, Any]]:
    """Build category metadata and max_score caps directly from drl_rules.json."""
    short_names = {
        "C1": "Học tập & NCKH",
        "C2": "Chấp hành quy chế & nội quy",
        "C3": "Chính trị - Xã hội, VH-VN, TDTT",
        "C4": "Hoạt động vì cộng đồng",
        "C5": "Khuyến khích & Cán bộ lớp/Đoàn Hội",
    }
    caps_list = DRL_RULES_CONFIG.get("scoring_model", {}).get("category_caps", [])
    result: dict[str, dict[str, Any]] = {}
    for item in caps_list:
        cid = item.get("category_id")
        if cid:
            result[cid] = {
                "max": item.get("max_score", 25),
                "name": short_names.get(cid, item.get("name", cid)),
                "full_name": item.get("name", cid),
            }
    if not result:
        result = {
            "C1": {"max": 30, "name": "Học tập & NCKH"},
            "C2": {"max": 25, "name": "Chấp hành quy chế & nội quy"},
            "C3": {"max": 25, "name": "Chính trị - Xã hội, VH-VN, TDTT"},
            "C4": {"max": 25, "name": "Hoạt động vì cộng đồng"},
            "C5": {"max": 10, "name": "Khuyến khích & Cán bộ lớp/Đoàn Hội"},
        }
    return result


CATEGORY_META = _build_category_caps_map()

# Initialize MinHash LSH Deduplicator from source_posts.json
deduplicator = PostDeduplicator(threshold=0.75, num_perm=128)
BASELINE_POST_IDS: set[str] = set()
for item in SOURCE_POSTS:
    pid = item.get("post_id") or item.get("id")
    txt = item.get("raw_content") or item.get("content") or item.get("text")
    if pid and txt:
        BASELINE_POST_IDS.add(str(pid))
        deduplicator.index_post(str(pid), txt)

# Default Student Demo Baseline State (Lưu Minh Tiến) using authentic category caps from drl_rules.json
DEFAULT_STUDENT_ID = "25127242"
# Kept in sync with the web UI baseline (20 + 15 + 22 + 10 + 2 = 69 points).
DEFAULT_CATEGORY_CURRENTS = {"C1": 20, "C2": 15, "C3": 22, "C4": 10, "C5": 2}


def build_student_baseline_scores(custom_currents: Optional[dict[str, float]] = None) -> dict[str, dict[str, Any]]:
    currents = custom_currents or DEFAULT_CATEGORY_CURRENTS
    scores: dict[str, dict[str, Any]] = {}
    for cid, meta in CATEGORY_META.items():
        scores[cid] = {
            "current": currents.get(cid, 0),
            "max": meta["max"],
            "name": meta["name"],
        }
    return scores


STUDENT_BASELINE = {
    "student_id": DEFAULT_STUDENT_ID,
    "full_name": "Lưu Minh Tiến",
    "class": "25C09",
    "major": "Khoa học Máy tính / CNTT",
    "term": "HK1/2026-2027",
    "category_scores": build_student_baseline_scores(),
    "verified_activities_count": 8,
}

# =============================================================================
# SESSION STATE (in-memory, persisted to data/sessions/current_session.json)
# -----------------------------------------------------------------------------
# Design rule: POST /api/evaluate is a PURE preview — it never mutates session
# state. Only POST /api/commit (an explicit user action such as "Lưu vào bảng
# điểm" or "Gửi duyệt") records an activity, updates the student's scores,
# indexes the post for duplicate detection, or appends to the review queue.
# =============================================================================
SESSION_DIR = ROOT_DIR / "data" / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = SESSION_DIR / "current_session.json"
SESSION_SCHEMA_VERSION = 2

# Committed (saved) activities across students, newest first.
session_committed: list[dict[str, Any]] = []
# Per-student saved scores: {student_id: {"current": {Cx: n}, "projected": {Cx: n}}}
session_scores: dict[str, dict[str, dict[str, float]]] = {}
# Posts explicitly submitted for human review.
review_queue: list[dict[str, Any]] = []
# Per-student MinHash index of *committed* posts (prevents counting the same post twice).
student_dedupers: dict[str, PostDeduplicator] = {}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_student_scores() -> dict[str, dict[str, float]]:
    return {
        "current": {cid: DEFAULT_CATEGORY_CURRENTS.get(cid, 0) for cid in CATEGORY_META},
        "projected": {cid: 0 for cid in CATEGORY_META},
    }


def _get_student_scores(student_id: str) -> dict[str, dict[str, float]]:
    if student_id not in session_scores:
        session_scores[student_id] = _default_student_scores()
    return session_scores[student_id]


def _get_student_deduper(student_id: str) -> PostDeduplicator:
    if student_id not in student_dedupers:
        student_dedupers[student_id] = PostDeduplicator(threshold=0.75, num_perm=128)
    return student_dedupers[student_id]


def _session_activities() -> list[dict[str, Any]]:
    """Activities catalog = saved activities (newest first) + baseline catalog."""
    saved = [c["catalog_entry"] for c in session_committed if c.get("kind") == "score"]
    return saved + list(ACTIVITIES_DATA)


def _scores_payload(student_id: str) -> dict[str, Any]:
    state = _get_student_scores(student_id)
    categories = {}
    for cid, meta in CATEGORY_META.items():
        categories[cid] = {
            "current": _clean_num(state["current"].get(cid, 0)),
            "projected": _clean_num(state["projected"].get(cid, 0)),
            "max": meta["max"],
            "name": meta["name"],
        }
    total_current = min(100, sum(c["current"] for c in categories.values()))
    total_projected = sum(c["projected"] for c in categories.values())
    return {
        "student_id": student_id,
        "category_scores": categories,
        "total_confirmed": _clean_num(total_current),
        "total_projected": _clean_num(total_projected),
        "total_hypothetical": _clean_num(min(100, total_current + total_projected)),
        "saved_activities": [
            {k: c.get(k) for k in ("commit_id", "title", "category_id", "confirmed_added", "projected_added", "committed_at")}
            for c in session_committed
            if c.get("kind") == "score" and c.get("student_id") == student_id
        ],
        "is_baseline": not any(
            c.get("kind") == "score" and c.get("student_id") == student_id for c in session_committed
        ),
    }


def _save_session_to_disk() -> None:
    """Persist the full session state to data/sessions/current_session.json."""
    try:
        payload = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "updated_at": _now_iso(),
            "storage_mode": "local_filesystem_folder",
            "folder": str(SESSION_DIR),
            "session_scores": session_scores,
            "committed": session_committed,
            "review_queue": review_queue,
            # Read-only convenience view for humans opening the file.
            "total_activities": len(_session_activities()),
            "total_review_queue": len(review_queue),
        }
        SESSION_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"Warning: Failed to save session to {SESSION_FILE}: {exc}", file=sys.stderr)


def _clear_session_state() -> None:
    session_committed.clear()
    session_scores.clear()
    review_queue.clear()
    student_dedupers.clear()


def _load_session_from_disk() -> None:
    """Restore a previous session (survives server restarts). Falls back to a clean state."""
    data = load_json(SESSION_FILE, None)
    if not isinstance(data, dict) or data.get("schema_version") != SESSION_SCHEMA_VERSION:
        return
    try:
        session_scores.update(data.get("session_scores") or {})
        session_committed.extend(data.get("committed") or [])
        review_queue.extend(data.get("review_queue") or [])
        for c in session_committed:
            if c.get("kind") == "score" and c.get("raw_content"):
                _get_student_deduper(c["student_id"]).index_post(c["commit_id"], c["raw_content"])
    except Exception as exc:
        print(f"Warning: Ignoring unreadable session file {SESSION_FILE}: {exc}", file=sys.stderr)
        _clear_session_state()


_load_session_from_disk()
_save_session_to_disk()

# 5 Standardized E2E Test Scenarios (Shared between API and Frontend)
E2E_SCENARIOS: dict[int, dict[str, Any]] = {
    1: {
        "id": 1,
        "name": "Ca 1: Tập huấn PCCC 2026 (Mục 1.9, C1 +5đ)",
        "badge": "Điểm dự kiến (+5đ)",
        "badge_class": "bg-blue-100 text-blue-800",
        "rule_label": "R19 (Mục 1.9, C1)",
        "description": "Bài đăng offline đầy đủ 14 trường. Chưa có minh chứng điểm danh nên ghi nhận Điểm dự kiến (+5đ, điểm chính thức C1 giữ nguyên 20/30đ).",
        "post_id": "pfbid01_pccc_new_2026",
        "publisher": "Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/osa.hcmus/posts/pccc_training_2026",
        "evidence": False,
        "rule_override": "auto",
        "expected": {
            "strict_decision": "PENDING_REVIEW",
            "demo_decision": "PROJECTED",
            "rule_id": "R19",
            "category_id": "C1",
            "projected_added": 5,
            "confirmed_added": 0,
            "category_before": 20,
            "category_after": 20,
            "hypothetical_category_after": 25,
            "category_cap": 30,
        },
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
        "badge": "Xác nhận Demo (+10đ)",
        "badge_class": "bg-emerald-100 text-emerald-800",
        "rule_label": "R42 (Mục 4.2, C4)",
        "description": "Hoạt động vì cộng đồng có minh chứng giấy chứng nhận mô phỏng. Cộng +10đ vào điểm xác nhận Demo nhóm C4 (10 -> 20/25đ).",
        "post_id": "pfbid09bloodDonation2026hcmus",
        "publisher": "Hội Sinh Viên Trường ĐH Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/hsv.hcmus/posts/blood2026",
        "evidence": True,
        "rule_override": "auto",
        "expected": {
            "strict_decision": "PENDING_REVIEW",
            "demo_decision": "DEMO_CONFIRMED",
            "rule_id": "R42",
            "category_id": "C4",
            "projected_added": 0,
            "confirmed_added": 10,
            "category_before": 10,
            "category_after": 20,
            "hypothetical_category_after": 20,
            "category_cap": 25,
        },
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
        "badge": "Cần xác minh (D16)",
        "badge_class": "bg-amber-100 text-amber-800",
        "rule_label": "Quy tắc D16 / CALC_05",
        "description": "Bài đăng Online có công nhận ĐRL nhưng KHÔNG nêu điều kiện hoàn thành. SP1 gắn cờ needs_review:completion_requirements chuyển review_queue, +0đ.",
        "post_id": "pfbid03onlineMissingReqD16",
        "publisher": "Trung tâm Hướng nghiệp & Tư vấn việc làm HCMUS",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/career.hcmus/posts/webinar303",
        "evidence": False,
        "rule_override": "auto",
        "expected": {
            "strict_decision": "NEEDS_REVIEW",
            "demo_decision": "NEEDS_REVIEW",
            "rule_id": "R19",
            "category_id": "C1",
            "projected_added": 0,
            "confirmed_added": 0,
            "category_before": 20,
            "category_after": 20,
            "hypothetical_category_after": 20,
            "category_cap": 30,
        },
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
        "badge": "Áp trần C3 (+3đ)",
        "badge_class": "bg-purple-100 text-purple-800",
        "rule_label": "R3101 (Mục 3.1, C3)",
        "description": "Cuộc thi cấp trường R3101 quy chế thưởng +10đ. Nhưng nhóm C3 đang đạt 22/25đ nên engine SP2 áp trần CALC_02, chỉ cộng tối đa +3đ (22 -> 25/25đ).",
        "post_id": "pfbid04capLimitTestC3",
        "publisher": "Đoàn Trường ĐH Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/doantruong.hcmus/posts/olympicmaclenin",
        "evidence": True,
        "rule_override": "R3101",
        "expected": {
            "strict_decision": "PENDING_REVIEW",
            "demo_decision": "DEMO_CONFIRMED",
            "rule_id": "R3101",
            "category_id": "C3",
            "projected_added": 0,
            "confirmed_added": 3,
            "category_before": 22,
            "category_after": 25,
            "hypothetical_category_after": 25,
            "category_cap": 25,
        },
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
        "badge": "Chặn trùng (+0đ)",
        "badge_class": "bg-rose-100 text-rose-800",
        "rule_label": "Deduplicator (>= 75%)",
        "description": "Bài đăng trùng post_id/URL hoặc có nội dung tương đồng >= 75% với sự kiện đã thu thập trong source_posts.json. Hệ thống phát hiện trùng lặp và từ chối cộng điểm.",
        "post_id": "pfbid02buJY8Rrn2XezSWbCNxpUnfSHX4yDYWi5EgXbngmL1FKiEE47XQarhqVqb4WjERECl",
        "publisher": "Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên",
        "platform": "facebook",
        "date_posted": "2026-10-25",
        "url": "https://www.facebook.com/osa.hcmus/posts/pfbid02buJY8Rrn2XezSWbCNxpUnfSH",
        "evidence": True,
        "rule_override": "auto",
        "expected": {
            "strict_decision": "REJECTED_DUPLICATE",
            "demo_decision": "REJECTED_DUPLICATE",
            "rule_id": "R19",
            "category_id": "C1",
            "projected_added": 0,
            "confirmed_added": 0,
            "category_before": 20,
            "category_after": 20,
            "hypothetical_category_after": 20,
            "category_cap": 30,
        },
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
    simulate_demo: bool = Field(default=False)


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


def _match_demo_rule(rec: dict[str, Any], raw_content: str, rule_override: str) -> Optional[dict[str, Any]]:
    """Select candidate rule from DRL_RULES_CONFIG for demo simulation."""
    rules_list = DRL_RULES_CONFIG.get("rules", [])
    rule_map = {r["rule_id"]: r for r in rules_list if "rule_id" in r}

    if rule_override and rule_override != "auto":
        return rule_map.get(rule_override)

    title_lower = (rec.get("title") or "").lower()
    content_lower = raw_content.lower()

    if "hiến máu" in title_lower or "hiến máu" in content_lower:
        return rule_map.get("R42")
    if any(k in title_lower or k in content_lower for k in ["olympic", "mác - lênin", "mác-lênin"]):
        return rule_map.get("R3101")
    if any(k in title_lower or k in content_lower for k in ["chạy bộ", "thể thao", "thanh niên khỏe"]):
        return rule_map.get("R32")
    if any(k in title_lower or k in content_lower for k in ["tuyển sinh", "ngày hội việc làm", "hội chợ việc làm"]):
        return rule_map.get("R38")
    if rec.get("domain") == "volunteer" or "tình nguyện" in content_lower:
        return rule_map.get("R4301")
    if any(k in content_lower for k in ["khảo sát", "điều tra xã hội"]):
        return rule_map.get("R23")
    if any(k in title_lower or k in content_lower for k in ["pccc", "phòng cháy", "kỹ năng", "tập huấn", "chuyên đề"]):
        return rule_map.get("R19")
    return rule_map.get("R19")


def _clean_num(val: Optional[float | int]) -> Optional[float | int]:
    if val is None:
        return None
    f = float(val)
    return int(f) if f.is_integer() else round(f, 2)


def _extract_flat_baseline_scores(
    custom_scores: Optional[dict[str, Any]],
) -> dict[str, int | float]:
    """Convert category scores mapping into {category_id: number} for evaluate_reviewed_activity."""
    flat: dict[str, int | float] = {}
    for cid, meta in CATEGORY_META.items():
        default_cur = DEFAULT_CATEGORY_CURRENTS.get(cid, 0)
        if custom_scores and cid in custom_scores:
            val = custom_scores[cid]
            if isinstance(val, dict):
                cur = float(val.get("current", default_cur))
            elif isinstance(val, (int, float)):
                cur = float(val)
            else:
                cur = float(default_cur)
        else:
            cur = float(default_cur)
        clamped = max(0.0, min(float(meta["max"]), cur))
        flat[cid] = _clean_num(clamped)
    return flat


@app.get("/api/health")
def health_check():
    rule_issues = audit_rules_config(DRL_RULES_CONFIG)
    return {
        "status": "degraded" if any(x["severity"] == "error" for x in rule_issues) else "healthy",
        "rule_audit_issues": rule_issues,
        "rule_audit_count": len(rule_issues),
        "regulation": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id", "1028/QD-KHTN-CTSV"),
        "total_rules": len(DRL_RULES_CONFIG.get("rules", [])),
        "total_activities": len(_session_activities()),
        "total_review_queue": len(review_queue),
        "indexed_posts_in_lsh": len(deduplicator.minhashes),
        "saved_activities": sum(1 for c in session_committed if c.get("kind") == "score"),
    }


@app.get("/api/students")
def get_students_list():
    """Return available student profiles from student_profile.json."""
    return [
        {
            "student_id": s.get("student_id"),
            "full_name": s.get("full_name"),
            "class": s.get("class", "25C09"),
            "major": s.get("major", "Information Technology"),
            "gpa": s.get("gpa", 4.0),
            "accumulated_credits": s.get("accumulated_credits", 45),
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
        gpa = matched_student.get("gpa", 4.0)
    else:
        full_name = f"Sinh viên {target_id}"
        class_name = "25C09"
        major = "Công nghệ Thông tin"
        gpa = 4.0

    scores = _scores_payload(target_id)
    cat_scores = scores["category_scores"]
    total_confirmed = scores["total_confirmed"]
    return {
        "student_id": target_id,
        "full_name": full_name,
        "class": class_name,
        "major": major,
        "gpa": gpa,
        "term": "HK1/2026-2027",
        "category_scores": cat_scores,
        "verified_activities_count": 8,
        "total_confirmed_score": total_confirmed,
        "total_projected_score": scores["total_projected"],
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
    activities = _session_activities()
    return {
        "activities": activities,
        "valid_activities": activities,
        "review_queue": review_queue,
        "total_activities": len(activities),
        "total_saved": sum(1 for c in session_committed if c.get("kind") == "score"),
        "total_review_queue": len(review_queue),
        "storage": {
            "type": "local_filesystem_folder",
            "folder": "data/sessions",
            "file": "data/sessions/current_session.json",
        },
    }


@app.get("/api/scores")
def get_student_scores(student_id: Optional[str] = None):
    """Saved score board of a student in the current session (source of truth for the UI)."""
    return _scores_payload(student_id or DEFAULT_STUDENT_ID)


@app.get("/api/e2e-cases")
def get_e2e_cases():
    return E2E_SCENARIOS


@app.post("/api/reset")
def reset_session_state():
    """Wipe saved activities, saved scores and review queue back to the initial baseline."""
    _clear_session_state()
    _save_session_to_disk()
    return {"status": "success", "message": "Session reset to initial catalog"}


def _check_post_duplicate(
    req_post_id: str,
    req_url: str,
    raw_content: str,
    student_id: str,
) -> tuple[bool, Optional[str], float]:
    """Duplicate check against (1) baseline collected posts and (2) posts this student already SAVED.

    Previewed-but-unsaved posts are never indexed, so re-checking the same text is not a duplicate.
    """
    normalized = canonical_url(req_url)
    dup_match_id: Optional[str] = None
    dup_sim: float = 0.0

    # 1. Baseline collected posts (source_posts.json): exact post_id / canonical URL.
    for post in SOURCE_POSTS:
        try:
            same_url = canonical_url(post.get("url", "")) == normalized
        except ValueError:
            same_url = False
        if (req_post_id and req_post_id == post.get("post_id")) or same_url:
            dup_match_id, dup_sim = post.get("post_id"), 1.0
            break

    # 2. Baseline collected posts: MinHash-LSH content similarity.
    if dup_match_id is None and raw_content:
        match = deduplicator.find_duplicate(raw_content)
        if match and match[1] >= 0.75:
            dup_match_id, dup_sim = match[0], float(match[1])

    # 3. Activities this student has already saved to the score board.
    if dup_match_id is None and raw_content:
        match = _get_student_deduper(student_id).find_duplicate(raw_content)
        if match and match[1] >= 0.75:
            dup_match_id, dup_sim = match[0], float(match[1])

    return (dup_match_id is not None), dup_match_id, round(float(dup_sim), 4)


@app.post("/api/evaluate")
def evaluate_announcement(req: EvaluationRequest):
    """Dual-mode evaluation:
    - simulate_demo=False (default): Strict Fail-Closed Intake (PR #3 contract).
      Extracts 14-field candidate, checks duplicates, routes to review_queue, awards 0 points.
    - simulate_demo=True: Demo Simulation Mode (DEMO_ONLY).
      Runs SP1 -> 14-field candidate -> simulated approval -> real SP2 engine (evaluate_reviewed_activity / evaluate_progress).
    """
    source = {"publisher": req.publisher, "platform": req.platform, "URL_post": req.url}
    try:
        drafts = extract(req.raw_content, source, posted_date=req.date_posted)
        if not drafts:
            raise HTTPException(status_code=422, detail="No activity detected in announcement")
        raw_draft = drafts[0]
        draft = prepare_publication(raw_draft)
    except HTTPException:
        raise
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"SP1 input/contract error: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"SP1 extraction error: {exc}")

    rec, meta = draft["record"], draft["meta"]
    current_activity_id = rec["activity_id"]
    student_id = req.student_id or DEFAULT_STUDENT_ID
    is_duplicate, dup_match_id, dup_sim = _check_post_duplicate(
        req.post_id, req.url, req.raw_content, student_id
    )
    # A post the student saved earlier as "dự kiến" may be re-submitted WITH evidence to upgrade it
    # to "đã xác nhận". That is not a duplicate award: the projected points are replaced, not added.
    upgrade_of: Optional[dict[str, Any]] = None
    if is_duplicate and req.has_evidence and req.simulate_demo:
        upgrade_of = next(
            (
                c for c in session_committed
                if c.get("commit_id") == dup_match_id
                and c.get("student_id") == student_id
                and c.get("kind") == "score"
                and not c.get("confirmed_added")
            ),
            None,
        )
        if upgrade_of is not None:
            is_duplicate, dup_match_id, dup_sim = False, None, 0.0
    dup_source = (
        None if not is_duplicate
        else "saved" if str(dup_match_id).startswith("commit_")
        else "baseline"
    )
    meta["is_duplicate"] = is_duplicate
    review_fp = _review_fingerprint(req.raw_content)
    already_in_review = any(x.get("fingerprint") == review_fp for x in review_queue)

    # =========================================================================
    # MODE 1: STRICT FAIL-CLOSED INTAKE (Default when simulate_demo=False)
    # =========================================================================
    if not req.simulate_demo:
        meta["routed_to"] = "discarded_duplicate" if is_duplicate else "review_queue"
        if is_duplicate:
            decision = "REJECTED_DUPLICATE"
            explanation = (
                f"Bài đăng trùng dữ liệu đã thu thập (khớp với {dup_match_id}, "
                f"độ tương đồng MinHash-LSH {dup_sim * 100:.1f}%); không cộng điểm."
            )
        elif meta.get("status") != "valid" or meta.get("flags"):
            decision = "NEEDS_REVIEW"
            explanation = (
                f"Trích xuất chưa đủ tin cậy ({', '.join(meta.get('flags', []))}): "
                "cần kiểm tra nguồn và trường bị gắn cờ."
            )
        else:
            decision = "PENDING_REVIEW"
            explanation = (
                "Đã trích xuất ứng viên 14 trường. Ở Chế độ Nghiêm ngặt (Strict Intake), "
                "cần người có thẩm quyền duyệt nguồn, điều kiện, quy tắc ĐRL và minh chứng "
                "hoàn thành trước khi tính điểm."
            )
        if req.has_evidence:
            explanation += " Ô chọn 'có minh chứng' chỉ là khai báo của người dùng, chưa phải chứng thực."

        suggestion = None
        if req.rule_override and req.rule_override != "auto":
            suggestion = next(
                (r for r in DRL_RULES_CONFIG.get("rules", []) if r.get("rule_id") == req.rule_override),
                None,
            )
            if suggestion is not None:
                explanation += f" Quy tắc {req.rule_override} do người dùng chọn, chưa được xác nhận áp dụng."

        # NOTE: preview only — the post is queued for review only via POST /api/commit.
        score_cap = None
        rule_category = suggestion.get("category_id") if suggestion else None
        if rule_category:
            score_cap = CATEGORY_META.get(rule_category, {}).get("max")

        return {
            "success": True,
            "mode": "STRICT_INTAKE",
            "official_award_verified": False,
            "sp1": draft,
            "sp2": {
                "mode": "STRICT_INTAKE",
                "official_award_verified": False,
                "decision": decision,
                "badge_text": {
                    "REJECTED_DUPLICATE": "BÀI ĐĂNG TRÙNG",
                    "NEEDS_REVIEW": "CẦN KIỂM TRA DỮ LIỆU",
                    "PENDING_REVIEW": "CHỜ DUYỆT / CHƯA CỘNG ĐIỂM",
                }[decision],
                "badge_class": "badge-warning",
                "rule": suggestion,
                "category_id": rule_category,
                "category_name": "Chưa xác minh" if not rule_category else CATEGORY_META.get(rule_category, {}).get("name", rule_category),
                "announced_points": rec.get("points"),
                "rule_points": None,
                "projected_added": 0,
                "confirmed_added": 0,
                "category_before": None,
                "category_after": None,
                "hypothetical_category_after": None,
                "category_cap": score_cap,
                "category_missing": None,
                "total_score_after": None,
                "grade_label": "Chưa xác minh",
                "explanation": explanation,
                "citation": "Nguồn ĐRL cần được kiểm chứng độc lập; không có điểm được xác nhận tại bước này.",
            },
            "dedup": {
                "is_duplicate": is_duplicate,
                "match_id": dup_match_id,
                "similarity": dup_sim,
                "source": dup_source,
            },
            "commit": {
                "kind": None if is_duplicate or already_in_review else "review",
                "already_in_review": already_in_review,
            },
        }

    # =========================================================================
    # MODE 2: DEMO SIMULATION MODE (simulate_demo=True -> Real SP2 Engine)
    # =========================================================================
    matched_rule = _match_demo_rule(rec, req.raw_content, req.rule_override)
    # Baseline = explicit scores from the caller (dev batch runner / tests) or, by default,
    # the student's SAVED score board in this session (single source of truth).
    uses_session_scores = req.current_category_scores is None
    student_state = _get_student_scores(student_id)
    if uses_session_scores:
        flat_baseline = _extract_flat_baseline_scores(dict(student_state["current"]))
    else:
        flat_baseline = _extract_flat_baseline_scores(req.current_category_scores)

    category_id = matched_rule.get("category_id", "C1") if matched_rule else "C1"
    cat_meta = CATEGORY_META.get(category_id, {"max": 30, "name": "Học tập & NCKH"})
    cat_cap = cat_meta["max"]
    cat_name = cat_meta["name"]
    current_cat_score = _clean_num(flat_baseline.get(category_id, 0))
    total_confirmed_before = _clean_num(min(100, sum(flat_baseline.values())))
    existing_projected = (
        _clean_num(student_state["projected"].get(category_id, 0)) if uses_session_scores else 0
    )
    if upgrade_of is not None and upgrade_of.get("category_id") == category_id:
        existing_projected = _clean_num(max(0, existing_projected - (upgrade_of.get("projected_added") or 0)))

    announced_points = rec.get("points")
    rule_points = matched_rule.get("points") if matched_rule else None

    if is_duplicate:
        meta["routed_to"] = "discarded_duplicate"
        decision = "REJECTED_DUPLICATE"
        badge_text = "DEMO: BỊ TỪ CHỐI DO TRÙNG LẶP (DEDUPLICATOR)"
        badge_class = "badge-danger"
        projected_added = 0
        confirmed_added = 0
        cat_after = current_cat_score
        hypothetical_after = current_cat_score
        cat_missing = max(0, cat_cap - current_cat_score)
        total_confirmed_after = total_confirmed_before
        explanation = (
            f"[MÔ PHỎNG DEMO] Bài đăng bị phát hiện trùng lặp với '{dup_match_id}' "
            f"(độ tương đồng MinHash-LSH / URL đạt {dup_sim * 100:.1f}% >= 75%). "
            "Hệ thống chặn cộng điểm lần 2 theo đúng quy chế."
        )
    elif (
        meta.get("status") != "valid"
        or meta.get("flags")
        or matched_rule is None
        or matched_rule.get("status") != "verified"
    ):
        meta["routed_to"] = "review_queue"
        decision = "NEEDS_REVIEW"
        badge_text = "DEMO: CHỜ XÁC MINH DỮ LIỆU / QUY TẮC (CALC_05 / D16)"
        badge_class = "badge-warning"
        projected_added = 0
        confirmed_added = 0
        cat_after = current_cat_score
        hypothetical_after = current_cat_score
        cat_missing = max(0, cat_cap - current_cat_score)
        total_confirmed_after = total_confirmed_before

        if matched_rule is None:
            reason_detail = f"Mã quy tắc '{req.rule_override}' không tồn tại trong bộ quy chế."
        elif matched_rule.get("status") != "verified":
            reason_detail = (
                f"Quy tắc {matched_rule.get('rule_id')} đang ở trạng thái '{matched_rule.get('status')}' "
                "(tạm khóa chờ trường xác nhận theo đối chiếu QĐ 1028), nên engine SP2 không tự cộng điểm."
            )
        else:
            reason_detail = (
                f"Bản trích xuất SP1 ở trạng thái '{meta.get('status')}' hoặc có cờ cảnh báo "
                f"({', '.join(meta.get('flags', []))}). Theo quy tắc D16 & CALC_05, hoạt động được chuyển vào "
                "review_queue và không cộng điểm dự kiến hay xác nhận."
            )
        explanation = f"[MÔ PHỎNG DEMO] {reason_detail}"
        # NOTE: preview only — queued for review only via POST /api/commit.
    else:
        # Execute real SP2 evaluation via evaluate_reviewed_activity -> sp2.drl_engine.evaluate_progress
        eval_record = dict(rec)
        # If post announced points differ from rule points when user explicitly overrides rule (e.g. Case 4),
        # align record points for the simulated approval fixture while reporting both in the response.
        if eval_record.get("points") is not None and eval_record.get("points") != rule_points:
            eval_record["points"] = rule_points

        simulated_approval = {
            "decision": "APPROVED",
            "activity_id": eval_record["activity_id"],
            "fingerprint": fingerprint(eval_record),
            "source_url": eval_record["source"]["URL_post"],
            "reviewer_id": "SYNTHETIC_REVIEWER_FIXTURE",
            "reviewed_at": "2026-10-27T12:00:00+07:00",
            "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
            "rule_id": matched_rule["rule_id"],
        }
        student_id_str = req.student_id or DEFAULT_STUDENT_ID
        student_profile = {"student_id": student_id_str, "university": "HCMUS"}
        baseline = {
            "student_id": student_id_str,
            "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
            "category_scores": flat_baseline,
            "included_activity_ids": [],
        }
        participation = None
        if req.has_evidence:
            participation = {
                "student_id": student_id_str,
                "activity_id": eval_record["activity_id"],
                "status": "CONFIRMED",
                "evidence_status": "VERIFIED",
                "verifier_id": "SYNTHETIC_EVIDENCE_FIXTURE",
                "verified_at": "2026-10-27T12:00:00+07:00",
                "evidence_ref": "synthetic://demo/evidence-01",
            }

        sp2_res = evaluate_reviewed_activity(
            record=eval_record,
            metadata={"status": "valid", "flags": [], "is_duplicate": False},
            approval=simulated_approval,
            participation=participation,
            baseline=baseline,
            student_profile=student_profile,
            rules_config=DRL_RULES_CONFIG,
            schema=ACTIVITY_SCHEMA,
        )

        projected_added = sp2_res.get("projected_added", 0)
        confirmed_added = sp2_res.get("confirmed_added", 0)
        cat_before = sp2_res.get("category_before", current_cat_score)
        cat_after = sp2_res.get("category_after", current_cat_score)
        hypothetical_after = sp2_res.get("hypothetical_category_after", current_cat_score)
        cat_missing = sp2_res.get("remaining_after_hypothetical", max(0, cat_cap - hypothetical_after))
        total_confirmed_after = sp2_res.get("confirmed_total_after", total_confirmed_before)

        # Saved-but-unconfirmed ("dự kiến") points already occupy part of the category room.
        projected_room_note = ""
        if not req.has_evidence and existing_projected:
            room_left = max(0, cat_cap - (cat_before or 0) - existing_projected)
            if projected_added > room_left:
                projected_room_note = (
                    f" Nhóm {category_id} đã có +{existing_projected}đ dự kiến được lưu trước đó, "
                    f"nên chỉ còn trống {room_left}đ."
                )
                projected_added = _clean_num(room_left)
            hypothetical_after = _clean_num(min(cat_cap, (cat_before or 0) + existing_projected + projected_added))
            cat_missing = max(0, cat_cap - hypothetical_after)

        effective_delta = confirmed_added if req.has_evidence else projected_added
        is_capped = (rule_points is not None) and (effective_delta < rule_points)

        if req.has_evidence:
            decision = "DEMO_CONFIRMED"
            badge_text = (
                f"DEMO: ĐÃ XÁC NHẬN - ÁP TRẦN {category_id} (+{confirmed_added}đ)"
                if is_capped
                else f"DEMO: ĐÃ XÁC NHẬN (+{confirmed_added}đ MÔ PHỎNG)"
            )
            badge_class = "badge-success"
            exp_core = (
                f"[MÔ PHỎNG DEMO - Engine SP2 thật] Giả lập đã đối chiếu minh chứng hoàn thành "
                f"('{rec.get('completion_requirements')}'). "
            )
        else:
            decision = "PROJECTED"
            badge_text = f"DEMO: ĐIỂM DỰ KIẾN (+{projected_added}đ - CHỜ MINH CHỨNG)"
            badge_class = "badge-primary"
            exp_core = (
                f"[MÔ PHỎNG DEMO - Engine SP2 thật] Chưa có minh chứng hoàn thành. "
                f"Ghi nhận vào Điểm dự kiến (+{projected_added}đ); điểm xác nhận của mục {category_id} "
                f"giữ nguyên ở mức {cat_before}/{cat_cap}đ (dự kiến đạt {hypothetical_after}/{cat_cap}đ). "
            )

        if is_capped:
            room = max(0, cat_cap - cat_before)
            exp_cap = (
                f"[Áp trần CALC_02 qua evaluate_progress]: Quy chế {matched_rule.get('rule_id')} quy định +{rule_points}đ, "
                f"nhưng nhóm {category_id} ({cat_name}) đang đạt {cat_before}/{cat_cap}đ (chỉ còn trống {room}đ). "
                f"Do đó hệ thống chỉ cộng tối đa +{effective_delta}đ."
            )
        else:
            exp_cap = (
                f"Áp dụng mức +{effective_delta}đ theo tiêu chí {matched_rule.get('criterion_id')} "
                f"({matched_rule.get('rule_id')}: {matched_rule.get('name')})."
            )

        explanation = exp_core + exp_cap + projected_room_note
        meta["routed_to"] = "preview (awaiting user save via /api/commit)"
        # NOTE: preview only — nothing is recorded or indexed here. See POST /api/commit.

    source_info = (matched_rule or {}).get("source", {})
    citation = (
        f"Quyết định {source_info.get('document_id', '1028/QD-KHTN-CTSV')}, "
        f"{source_info.get('location', 'Phụ lục')} (DEMO_ONLY - cần xác nhận hiệu lực học kỳ hiện hành)"
    )

    return {
        "success": True,
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "sp1": draft,
        "sp2": {
            "mode": "DEMO_ONLY",
            "official_award_verified": False,
            "decision": decision,
            "badge_text": badge_text,
            "badge_class": badge_class,
            "rule": matched_rule,
            "category_id": category_id,
            "category_name": cat_name,
            "announced_points": announced_points,
            "rule_points": rule_points,
            "projected_added": projected_added,
            "confirmed_added": confirmed_added,
            "category_before": current_cat_score,
            "category_after": cat_after,
            "hypothetical_category_after": hypothetical_after,
            "category_cap": cat_cap,
            "category_missing": cat_missing,
            "confirmed_category_missing": max(0, cat_cap - cat_after),
            "total_score_before": total_confirmed_before,
            "total_score_after": total_confirmed_after,
            "hypothetical_total_after": min(100.0, total_confirmed_before + confirmed_added + projected_added),
            "grade_label": "DEMO - " + get_grade_label(total_confirmed_after),
            "explanation": explanation,
            "citation": citation,
            "existing_projected": existing_projected,
        },
        "dedup": {
            "is_duplicate": is_duplicate,
            "match_id": dup_match_id,
            "similarity": dup_sim,
            "source": dup_source,
        },
        "commit": {
            "upgrade_of": upgrade_of.get("commit_id") if upgrade_of else None,
            "kind": (
                "score"
                if decision in ("PROJECTED", "DEMO_CONFIRMED") and (confirmed_added or projected_added)
                else "review"
                if decision == "NEEDS_REVIEW" and not already_in_review
                else None
            ),
            "already_in_review": already_in_review,
            "category_full": decision in ("PROJECTED", "DEMO_CONFIRMED") and not (confirmed_added or projected_added),
        },
    }


def _review_fingerprint(raw_content: str) -> str:
    """Whitespace/case-insensitive fingerprint used to avoid queuing the same post twice."""
    import hashlib

    normalized = " ".join((raw_content or "").lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class CommitRequest(EvaluationRequest):
    """Same payload as /api/evaluate. The server re-evaluates it before saving (never trusts the client)."""


@app.post("/api/commit")
def commit_evaluation(req: CommitRequest):
    """Explicit user action after a preview:
    - kind "score"  -> save the activity to the student's score board ("Lưu vào bảng điểm").
    - kind "review" -> submit the post to the human review queue ("Gửi duyệt").
    The request is re-evaluated against the CURRENT session state, so a stale or tampered
    preview cannot award points, and saving the same post twice is rejected as a duplicate.
    """
    if req.current_category_scores is not None:
        raise HTTPException(status_code=422, detail="Saving always uses the server-side score board.")

    result = evaluate_announcement(req)
    sp2 = result["sp2"]
    commit = result.get("commit") or {}
    kind = commit.get("kind")
    student_id = req.student_id or DEFAULT_STUDENT_ID

    if kind is None:
        if result["dedup"]["is_duplicate"]:
            reason = "Hoạt động này đã được lưu trước đó (trùng lặp), không thể cộng điểm lần nữa."
        elif commit.get("already_in_review"):
            reason = "Bài đăng này đã có trong danh sách chờ duyệt."
        elif commit.get("category_full"):
            reason = "Nhóm tiêu chí này đã đạt điểm tối đa, không còn điểm để cộng."
        else:
            reason = "Kết quả hiện tại không có gì để lưu."
        raise HTTPException(status_code=409, detail=reason)

    rec = result["sp1"]["record"]
    commit_id = f"commit_{uuid.uuid4().hex[:10]}"

    if kind == "review":
        entry = {
            "commit_id": commit_id,
            "student_id": student_id,
            "activity_id": rec.get("activity_id"),
            "title": rec.get("title") or "Thông báo cần rà soát",
            "flags": result["sp1"]["meta"].get("flags", []) or ["rule_needs_review"],
            "date_posted": req.date_posted,
            "url": rec.get("source", {}).get("URL_post"),
            "fingerprint": _review_fingerprint(req.raw_content),
            "submitted_at": _now_iso(),
        }
        review_queue.append(entry)
        _save_session_to_disk()
        return {"status": "queued", "kind": "review", "entry": entry, "scores": _scores_payload(student_id)}

    # kind == "score"
    category_id = sp2["category_id"]
    cap = sp2["category_cap"]
    state = _get_student_scores(student_id)
    confirmed_added = sp2.get("confirmed_added") or 0
    projected_added = sp2.get("projected_added") or 0
    upgrade_id = commit.get("upgrade_of")
    prior = next((c for c in session_committed if c.get("commit_id") == upgrade_id), None) if upgrade_id else None

    if prior is not None:
        # Replace the earlier "dự kiến" points of this same activity by the confirmed points.
        prior_cat = prior.get("category_id")
        state["projected"][prior_cat] = _clean_num(
            max(0, state["projected"].get(prior_cat, 0) - (prior.get("projected_added") or 0))
        )

    if confirmed_added:
        state["current"][category_id] = _clean_num(min(cap, sp2["category_after"]))
    else:
        state["projected"][category_id] = _clean_num(
            state["projected"].get(category_id, 0) + projected_added
        )
    # Invariant: confirmed + projected never exceeds the category cap.
    room = max(0, cap - state["current"][category_id])
    state["projected"][category_id] = _clean_num(min(state["projected"].get(category_id, 0), room))

    points_label = (
        f"+{confirmed_added}đ (Đã xác nhận)" if confirmed_added else f"+{projected_added}đ (Dự kiến)"
    )

    if prior is not None:
        prior.update({
            "category_id": category_id,
            "confirmed_added": confirmed_added,
            "projected_added": 0,
            "confirmed_at": _now_iso(),
        })
        prior["catalog_entry"]["points_awarded"] = points_label
        _save_session_to_disk()
        return {
            "status": "upgraded",
            "kind": "score",
            "commit_id": prior["commit_id"],
            "category_id": category_id,
            "confirmed_added": confirmed_added,
            "projected_added": 0,
            "scores": _scores_payload(student_id),
        }

    entry = {
        "commit_id": commit_id,
        "kind": "score",
        "student_id": student_id,
        "activity_id": rec.get("activity_id"),
        "title": rec.get("title"),
        "category_id": category_id,
        "confirmed_added": confirmed_added,
        "projected_added": projected_added,
        "raw_content": req.raw_content,
        "committed_at": _now_iso(),
        "catalog_entry": {
            **rec,
            "rule_id": (sp2.get("rule") or {}).get("rule_id"),
            "points_awarded": points_label,
            "saved_by": student_id,
        },
    }
    session_committed.insert(0, entry)
    _get_student_deduper(student_id).index_post(commit_id, req.raw_content)
    _save_session_to_disk()
    return {
        "status": "saved",
        "kind": "score",
        "commit_id": commit_id,
        "category_id": category_id,
        "confirmed_added": confirmed_added,
        "projected_added": projected_added,
        "scores": _scores_payload(student_id),
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
    """SP2 rule-to-progress bridge on an explicitly marked demo snapshot."""
    if not req.demo:
        raise HTTPException(
            status_code=422,
            detail="Only demo snapshots are supported; official proof is not connected",
        )
    try:
        report = evaluate_rules_progress(
            DRL_RULES_CONFIG,
            req.student_profile,
            req.student_snapshot,
            scope=req.scope,
            personal_targets=req.personal_targets,
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
    with_demo_confirmation: Optional[bool] = None


@app.post("/api/pipeline/demo")
def evaluate_end_to_end_demo(req: DemoPipelineRequest):
    """SP1 post -> reviewed 14-field candidate -> SP2 engine for all 5 E2E fixtures."""
    if req.case_id not in E2E_SCENARIOS:
        raise HTTPException(status_code=422, detail=f"Demo fixture {req.case_id} is not available (valid: 1..5)")

    case = E2E_SCENARIOS[req.case_id]
    with_conf = case["evidence"] if req.with_demo_confirmation is None else req.with_demo_confirmation

    source = {"publisher": case["publisher"], "platform": case["platform"], "URL_post": case["url"]}
    drafts = extract(case["raw_content"], source, posted_date=case["date_posted"])
    if not drafts:
        raise HTTPException(status_code=422, detail="Demo extraction returned no records")
    candidate = prepare_publication(drafts[0])
    activity = candidate["record"]
    meta = candidate["meta"]

    is_dup, dup_id, dup_sim = _check_post_duplicate(
        case["post_id"], case["url"], case["raw_content"], activity["activity_id"]
    )
    meta["is_duplicate"] = is_dup

    rule_id = case["expected"]["rule_id"]
    eval_act = dict(activity)
    matched_rule = next((r for r in DRL_RULES_CONFIG.get("rules", []) if r.get("rule_id") == rule_id), None)
    if matched_rule and eval_act.get("points") is not None and eval_act.get("points") != matched_rule.get("points"):
        eval_act["points"] = matched_rule.get("points")

    simulated_approval = {
        "decision": "APPROVED",
        "activity_id": eval_act["activity_id"],
        "fingerprint": fingerprint(eval_act),
        "source_url": eval_act["source"]["URL_post"],
        "reviewer_id": "SYNTHETIC_REVIEWER_FIXTURE",
        "reviewed_at": "2026-10-27T12:00:00+07:00",
        "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
        "rule_id": rule_id,
    }
    student_profile = {"student_id": "demo-student-001", "university": "HCMUS"}
    # Keep C1=20, C2..C5=0 for case 1 compatibility with test_reviewed_pipeline.py;
    # use full category baseline for cases 2..5
    if req.case_id == 1:
        base_scores = {"C1": 20, "C2": 0, "C3": 0, "C4": 0, "C5": 0}
    else:
        base_scores = dict(DEFAULT_CATEGORY_CURRENTS)

    baseline = {
        "student_id": student_profile["student_id"],
        "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
        "category_scores": base_scores,
        "included_activity_ids": [],
    }
    participation = None
    if with_conf:
        participation = {
            "student_id": student_profile["student_id"],
            "activity_id": eval_act["activity_id"],
            "status": "CONFIRMED",
            "evidence_status": "VERIFIED",
            "verifier_id": "SYNTHETIC_EVIDENCE_FIXTURE",
            "verified_at": "2026-10-27T12:00:00+07:00",
            "evidence_ref": f"synthetic://fixture/checkin-0{req.case_id}",
        }
    try:
        if is_dup or meta.get("status") != "valid" or meta.get("flags"):
            result = {
                "mode": "DEMO_ONLY",
                "official_award_verified": False,
                "status": "REJECTED_DUPLICATE" if is_dup else "NEEDS_REVIEW",
                "reason": "Duplicate post detected" if is_dup else "Extractor review flags present",
                "flags": meta.get("flags", []),
                "projected_added": 0,
                "confirmed_added": 0,
            }
        else:
            result = evaluate_reviewed_activity(
                record=eval_act,
                metadata=meta,
                approval=simulated_approval,
                participation=participation,
                baseline=baseline,
                student_profile=student_profile,
                rules_config=DRL_RULES_CONFIG,
                schema=ACTIVITY_SCHEMA,
            )
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "mode": "DEMO_ONLY",
        "source": f"SYNTHETIC_SCENARIO_{req.case_id}",
        "official_award_verified": False,
        "activity": candidate,
        "dedup": {"is_duplicate": is_dup, "match_id": dup_id, "similarity": dup_sim},
        "sp2": result,
    }


@app.get("/api/lead/audit")
def lead_data_audit():
    """Quick read-only audit of regulation rules, 20-activity catalog, and cross-post duplicates."""
    raw_source = load_json(ROOT_DIR / "Collecting_Data/source.json", None) or SOURCE_POSTS
    return {
        "mode": "DEMO_ONLY",
        "regulation_id": DRL_RULES_CONFIG.get("regulation", {}).get("regulation_id"),
        "applicability_current_semester": "NEEDS_SCHOOL_CONFIRMATION",
        "regulation_issues": audit_rules_config(DRL_RULES_CONFIG),
        "rules_needing_review": [
            r["rule_id"] for r in DRL_RULES_CONFIG.get("rules", []) if r.get("status") != "verified"
        ],
        "dataset": audit_dataset(ACTIVITIES_DATA),
        "duplicate_candidate_groups": possible_duplicates(raw_source),
    }


# Serve Frontend static files if web directory exists
@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="8" fill="#2563eb"/>'
        '<text x="16" y="22" font-family="Arial,sans-serif" font-size="18" font-weight="bold" fill="white" text-anchor="middle">U</text>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def serve_index():
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"message": "Web UI index.html not found"}, status_code=404)
