"""Regression tests for the preview -> save user flow of the web demo.

Rule under test: POST /api/evaluate ("Kiểm tra điểm") is a pure preview and must never
record anything. Only POST /api/commit ("Lưu vào bảng điểm" / "Gửi duyệt") changes state.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from api.server import (  # noqa: E402
    CommitRequest,
    EvaluationRequest,
    commit_evaluation,
    evaluate_announcement,
    get_activities,
    get_student_scores,
    reset_session_state,
)

STUDENT = "25127242"

POST_A = """HỘI THẢO SINH HOẠT CHUYÊN ĐỀ KỸ NĂNG VÀ NCKH NĂM 2026
Thời gian: 13:00 - 15:00 ngày 12/11/2026
Hình thức: Trực tiếp
Địa điểm: Hội trường I, Cơ sở 227 Nguyễn Văn Cừ
Đối tượng tham gia: Sinh viên hệ chính quy toàn trường
Lệ phí: Miễn phí. Hoạt động không bắt buộc.
Quyền lợi: Sinh viên được cộng 5 điểm rèn luyện khi tham gia đầy đủ và điểm danh cuối buổi."""

POST_B = """HỘI NGHỊ KHOA HỌC TRẺ VÀ TẬP HUẤN PHƯƠNG PHÁP NGHIÊN CỨU KHOA HỌC CHO TÂN SINH VIÊN
Thời gian: 08:30 - 11:30 ngày 18/11/2026
Hình thức: Trực tiếp
Địa điểm: Giảng đường 2, Cơ sở Linh Trung, Thủ Đức
Đối tượng: Tân sinh viên khóa 2026 các ngành
Chi phí: Không thu phí, đăng ký tự nguyện.
Quyền lợi: Cộng 5 điểm rèn luyện khi tham gia đầy đủ và điểm danh check-in cuối buổi."""


@pytest.fixture(autouse=True)
def fresh_session():
    assert reset_session_state()["status"] == "success"


def body(raw: str, *, evidence: bool = True, post_id: str = "custom_post_1") -> dict:
    return {
        "post_id": post_id,
        "url": f"https://www.facebook.com/ctsv.hcmus/posts/{post_id}",
        "raw_content": raw,
        "has_evidence": evidence,
        "student_id": STUDENT,
        "simulate_demo": True,
    }


def scores() -> dict:
    return get_student_scores(student_id=STUDENT)


def test_preview_twice_is_not_a_duplicate_and_records_nothing():
    before_catalog = get_activities()["total_activities"]
    first = evaluate_announcement(EvaluationRequest(**body(POST_A, post_id="p1")))
    # User withdraws, clears the input box, and pastes the same text again (new post_id).
    second = evaluate_announcement(EvaluationRequest(**body(POST_A, post_id="p2")))

    assert first["sp2"]["decision"] == "DEMO_CONFIRMED"
    assert second["sp2"]["decision"] == "DEMO_CONFIRMED"
    assert second["dedup"]["is_duplicate"] is False
    assert second["commit"]["kind"] == "score"
    assert get_activities()["total_activities"] == before_catalog
    assert scores()["total_confirmed"] == 69


def test_save_accumulates_and_blocks_double_save():
    a = commit_evaluation(CommitRequest(**body(POST_A, post_id="p1")))
    assert a["status"] == "saved"
    assert scores()["total_confirmed"] == 74

    preview_b = evaluate_announcement(EvaluationRequest(**body(POST_B, post_id="p2")))
    assert preview_b["sp2"]["category_before"] == 25
    assert preview_b["sp2"]["category_after"] == 30

    b = commit_evaluation(CommitRequest(**body(POST_B, post_id="p3")))
    assert b["status"] == "saved"
    assert scores()["total_confirmed"] == 79
    assert scores()["category_scores"]["C1"]["current"] == 30

    again = evaluate_announcement(EvaluationRequest(**body(POST_A, post_id="p4")))
    assert again["sp2"]["decision"] == "REJECTED_DUPLICATE"
    assert again["dedup"]["source"] == "saved"
    with pytest.raises(HTTPException) as exc:
        commit_evaluation(CommitRequest(**body(POST_A, post_id="p5")))
    assert exc.value.status_code == 409
    assert scores()["total_confirmed"] == 79


def test_projected_then_upgrade_with_evidence_does_not_double_count():
    res1 = commit_evaluation(CommitRequest(**body(POST_A, evidence=False)))
    assert res1["status"] == "saved"
    s = scores()
    assert s["total_confirmed"] == 69 and s["category_scores"]["C1"]["projected"] == 5

    # Same post without evidence again -> duplicate.
    dup = evaluate_announcement(EvaluationRequest(**body(POST_A, evidence=False, post_id="x")))
    assert dup["sp2"]["decision"] == "REJECTED_DUPLICATE"

    # Same post WITH evidence -> upgrade projected to confirmed.
    up = commit_evaluation(CommitRequest(**body(POST_A, evidence=True, post_id="y")))
    assert up["status"] == "upgraded"
    s = scores()
    assert s["category_scores"]["C1"]["current"] == 25
    assert s["category_scores"]["C1"]["projected"] == 0
    assert len(s["saved_activities"]) == 1


def test_review_queue_only_on_explicit_submit():
    webinar = """WEBINAR HƯỚNG NGHIỆP: KỸ NĂNG VIẾT CV VÀ PHỎNG VẤN NGÀNH CNTT
Thời gian: 19:00 - 21:00 ngày 02/11/2026
Hình thức: Trực tuyến
Địa điểm: https://zoom.us/j/99887766
Quyền lợi: Sinh viên được cộng 5 điểm rèn luyện."""
    preview = evaluate_announcement(EvaluationRequest(**body(webinar, evidence=False)))
    assert preview["sp2"]["decision"] == "NEEDS_REVIEW"
    assert preview["commit"]["kind"] == "review"
    assert get_activities()["total_review_queue"] == 0

    queued = commit_evaluation(CommitRequest(**body(webinar, evidence=False)))
    assert queued["status"] == "queued"
    assert get_activities()["total_review_queue"] == 1
    with pytest.raises(HTTPException) as exc:
        commit_evaluation(CommitRequest(**body(webinar, evidence=False)))
    assert exc.value.status_code == 409


def test_commit_rejects_client_supplied_scores():
    payload = body(POST_A) | {"current_category_scores": {"C1": 0}}
    with pytest.raises(HTTPException) as exc:
        commit_evaluation(CommitRequest(**payload))
    assert exc.value.status_code == 422
