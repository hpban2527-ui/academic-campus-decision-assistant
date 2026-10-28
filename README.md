# PROJECT E — Academic Campus Decision Assistant (SP1 → SP2)

Hệ thống hỗ trợ trích xuất thông báo hoạt động ngoại khóa (**SP1**) và tư vấn/tính điểm rèn luyện (**SP2**) cho sinh viên Trường ĐH Khoa học Tự nhiên, ĐHQG-HCM (**HCMUS**).

- **Môn học**: CSC10014 — Tư Duy Tính Toán (Computational Thinking)
- **Phân công nhóm E**:
  - **Lead & Integration**: Huỳnh Phương Bình An
  - **SP1 (Data & Extractor)**: Nguyễn Minh Trí (Dataset), Bùi Thảo Duyên (Extractor)
  - **SP2 (Rules & Engine)**: Nguyễn Thị Ngọc Tuyền (Rules), Lâm Như Ngọc (DRL Engine)
  - **Frontend & Web Demo**: Lưu Minh Tiến (`Minh_Tien`)

---

## 1. Khởi chạy nhanh (Quick Start)

```bash
python -m pip install -r requirements.txt
python run_server.py
```

Mở trình duyệt tại: **[http://localhost:8000](http://localhost:8000)**

> **Lưu ý:** Toàn bộ giao diện gọi trực tiếp REST API trên máy chủ FastAPI (`sp1.extractor` $\rightarrow$ `lead_contract.prepare_publication` $\rightarrow$ `reviewed_pipeline.evaluate_reviewed_activity` $\rightarrow$ `sp2.drl_engine`). Cơ chế tính điểm giả trên trình duyệt (`runClientFallback`) đã được vô hiệu hóa hoàn toàn.

---

## 2. Kiến trúc Chế độ Kép (Dual-Mode Evaluation) & Các Endpoint API

| Endpoint | Phương thức | Chức năng chính |
|---|---|---|
| `/api/health` | `GET` | Kiểm tra trạng thái máy chủ, 75 quy tắc ĐRL, kết quả kiểm toán cấu hình quy chế (`audit_rules_config`). |
| `/api/students` | `GET` | Danh sách hồ sơ sinh viên từ `data/student_profile.json`. |
| `/api/profile` | `GET` | Hồ sơ điểm rèn luyện cơ sở (`DEMO_ONLY`, `official_score_verified=false`) với trần điểm chuẩn từ `data/drl_rules.json`. |
| `/api/e2e-cases` | `GET` | Danh sách 5 kịch bản kiểm thử E2E chuẩn kèm các kỳ vọng (assertions). |
| `/api/evaluate` | `POST` | **Chế độ Kép (Dual-Mode)**:<br>• `simulate_demo=false` *(Mặc định - Cổng Tiếp Nhận Nghiêm Ngặt PR#3)*: Chuẩn hóa đúng 14 trường (`schemas/activity.schema.json`), kiểm tra trùng lặp MinHash-LSH & URL, gắn `publication_status="REVIEW_REQUIRED"`, đẩy vào `review_queue` và trả `+0đ`.<br>• `simulate_demo=true` *(Chế độ Mô Phỏng ĐRL Demo)*: Thực thi trọn vẹn luồng `SP1 -> prepare_publication -> simulated_approval -> evaluate_reviewed_activity -> sp2.drl_engine.evaluate_progress` với nhãn `DEMO_ONLY` (`official_award_verified=false`). |
| `/api/pipeline/demo` | `POST` | Chạy kịch bản mẫu E2E (`case_id: 1..5`) qua `evaluate_reviewed_activity` và `evaluate_progress`. |
| `/api/sp2/evaluate` | `POST` | Chạy `evaluate_rules_progress` trên Snapshot học vụ (`semester_gpa`, `academic_exam_violations`, `course_evaluation_completion_rate`), tự động bỏ qua quy tắc đang tạm khóa (`R23`). |
| `/api/lead/audit` | `GET` | Kiểm toán chất lượng bộ 20 hoạt động thu thập (`activities.json`), danh sách quy tắc `needs_review` và các cụm bài đăng trùng nguồn (`possible_duplicates`). |

---

## 3. Hợp đồng Dữ liệu & Quy chế ĐRL đã khóa

1. **Hợp đồng 14 trường công bố (`schemas/activity.schema.json`)**:
   - Bộ trích xuất SP1 tạo bản nháp 15 trường; cổng `prepare_publication()` chuyển `drl_recognized` vào `meta.drl_recognized` để bản ghi `record` có đúng **14 trường**.
   - Áp dụng quy ước mặc định của nhóm khi bài đăng không nêu: `mandatory = false`, `fee = 0` (lưu vết tại `meta.derived`).
   - Chuẩn hóa URL (`canonical_url`) loại bỏ các tham số tracking (`rdid`, `fbclid`, `utm_*`) để tạo định danh `ACT-<sha256[:12]>` ổn định.
2. **Đối chiếu Quy chế ĐRL (`data/drl_rules.json` - QĐ 1028/QĐ-KHTN-CTSV)**:
   - `R11`: `+10đ` khi không vi phạm quy chế học vụ/khảo thí (theo Phụ lục QĐ 1028 trang 8).
   - `R1202`: Đã sửa mã lỗi chính tả từ `RR1202` thành `R1202`.
   - `R23`: Đặt `status = "needs_review"` để không tự động cộng trùng với `R22`.
   - `R4302`: Sử dụng phân nhóm thời lượng `volunteer_duration_bucket = "24_hours_to_under_one_week"`.
   - Mọi kết quả tính điểm đều gắn cờ `mode = "DEMO_ONLY"`, `official_award_verified = false`.

---

## 4. Chạy Kiểm Thử Tự Động (Automated Tests)

Trên PowerShell:
```powershell
$env:PYTHONPATH = "src"
python scripts/check_sp2_cases.py
python -m pytest -v tests/integration tests/test_e2e_pipeline.py
python -m compileall -q src tests scripts run_server.py
```

Chi tiết hướng dẫn vận hành giao diện và 5 kịch bản E2E xem tại **[`RUN_GUIDE.md`](RUN_GUIDE.md)**.

