# PROJECT E — Academic Campus Decision Assistant (SP1 → SP2)

Hệ thống hỗ trợ trích xuất thông báo hoạt động ngoại khóa (**SP1**) và tư vấn/tính điểm rèn luyện (**SP2**) cho sinh viên Trường ĐH Khoa học Tự nhiên, ĐHQG-HCM (**HCMUS**).

- **Môn học**: CSC10014 — Tư Duy Tính Toán (Computational Thinking)
- **Phân công nhóm E**:
  - **Lead & Integration**: Huỳnh Phương Bình An (`25127009`)
  - **SP1 (Data & Extractor)**: Nguyễn Minh Trí (`25127244`), Bùi Thảo Duyên (`25127316`)
  - **SP2 (Rules & Engine)**: Nguyễn Thị Ngọc Tuyền (`25127257`), Lâm Như Ngọc (`25127214`)
  - **Frontend & Web Demo**: Lưu Minh Tiến (`25127242`)

---

## 1. Cấu trúc thư mục dự án

```text
academic-campus-decision-assistant/
├── data/
│   ├── activities.json                 # 20 hoạt động gốc đã thu thập
│   ├── drl_rules.json                  # Bộ quy tắc ĐRL (QĐ 1028/QĐ-KHTN-CTSV)
│   ├── source_posts.json               # Dữ liệu bài đăng nguồn cho MinHash-LSH
│   └── student_profile.json            # Hồ sơ 6 sinh viên trong nhóm
├── prompts/
│   └── extraction_v1.txt               # Prompt chuẩn cho SP1 LLM backend
├── Report/
│   └── UniLife_Assistant_Product_Scouting_and_UX_Concept.pdf
├── schemas/
│   ├── activity.schema.json            # Schema 14 trường công bố (Lead contract)
│   └── extraction_draft.schema.json    # Schema 15 trường trích xuất nháp (SP1)
├── src/
│   ├── api/
│   │   ├── dedup_review.py             # Kiểm toán bài đăng trùng nguồn
│   │   ├── lead_contract.py            # Cổng chuẩn hóa 14 trường (prepare_publication)
│   │   ├── reviewed_pipeline.py        # Cầu nối SP1 -> SP2 đã duyệt
│   │   └── server.py                   # Máy chủ FastAPI chính
│   ├── sp1/
│   │   ├── dates.py                    # Chuẩn hóa thời gian tiếng Việt
│   │   ├── deduplication.py            # MinHash-LSH Deduplicator
│   │   ├── extractor.py                # Bộ trích xuất SP1 chính
│   │   ├── llm_backend.py              # Kết nối LLM (tùy chọn)
│   │   └── regex_baseline.py           # Bộ trích xuất Regex tiếng Việt
│   └── sp2/
│       └── drl_engine.py               # Engine tính điểm rèn luyện SP2
├── tests/
│   ├── test_e2e_pipeline.py            # Kiểm thử tích hợp E2E (SP1 -> SP2 & API)
│   └── test_session_flow.py            # Kiểm thử luồng người dùng (Preview & Lưu điểm)
├── web/
│   └── index.html                      # Giao diện Web UniLife ĐRL
├── requirements.txt
└── run_server.py                       # Điểm khởi chạy ứng dụng
```

---

## 2. Khởi chạy nhanh (Quick Start)

```powershell
python -m pip install -r requirements.txt
python run_server.py
```

Mở trình duyệt tại: **[http://localhost:8000](http://localhost:8000)**

---

## 3. Các Endpoint API chính

| Endpoint | Phương thức | Chức năng chính |
|---|---|---|
| `/api/health` | `GET` | Kiểm tra trạng thái máy chủ, 75 quy tắc ĐRL, kết quả kiểm toán quy chế (`audit_rules_config`). |
| `/api/students` | `GET` | Danh sách hồ sơ sinh viên từ `data/student_profile.json`. |
| `/api/profile` | `GET` | Hồ sơ sinh viên & bảng điểm rèn luyện hiện tại trong phiên (`DEMO_ONLY`). |
| `/api/scores` | `GET` | Điểm số hiện tại theo 5 nhóm tiêu chí (`C1..C5`) và danh sách hoạt động đã lưu của sinh viên. |
| `/api/evaluate` | `POST` | **Kiểm tra điểm (Pure Preview — Không ghi trạng thái)**: Chạy `SP1 -> prepare_publication -> SP2` để xem trước điểm cộng dự tính mà không tự động lưu hay đánh dấu trùng lặp. |
| `/api/commit` | `POST` | **Lưu vào bảng điểm / Gửi duyệt**: Chốt cộng điểm chính thức vào bảng điểm học kỳ hoặc gửi bài đăng vào hàng đợi rà soát, lưu tự động xuống `data/sessions/current_session.json`. |
| `/api/sp2/evaluate` | `POST` | Đánh giá Snapshot điểm học vụ (`semester_gpa`, `academic_exam_violations`, `academic_warning_count`) qua `evaluate_rules_progress`. |
| `/api/lead/audit` | `GET` | Kiểm toán chất lượng bộ 20 hoạt động thu thập (`activities.json`), quy tắc `needs_review` và cụm bài đăng trùng nguồn. |

---

## 4. Chạy Kiểm Thử Tự Động (Automated Tests)

```powershell
python -m pytest tests/test_session_flow.py tests/test_e2e_pipeline.py -q
```
