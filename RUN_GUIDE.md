# HƯỚNG DẪN KHỞI CHẠY VÀ NGHIỆM THU (RUN GUIDE)
**Hệ Thống Hỗ Trợ Đánh Giá Hoạt Động & Điểm Rèn Luyện (SP1 &rarr; SP2)**
*Môn học: CSC10014 - Computational Thinking | Nhóm E*  
*Thành viên phụ trách: **Lưu Minh Tiến** (Gói: Frontend + Demo | Nhánh: `Minh_Tien`)*

---

## 1. TỔNG QUAN HỆ THỐNG
Hệ thống là ứng dụng Web hoàn chỉnh tích hợp luồng xử lý tự động từ **SP1** (Trích xuất thông tin bài đăng sự kiện theo hợp đồng 14/15 trường JSON) sang **SP2** (Phân loại tiêu chí và tính điểm rèn luyện theo Quyết định 1028/QĐ-KHTN-CTSV).

### Điểm nổi bật:
1. **Gọi API Thật (Real Backend API)**: Toàn bộ quá trình trích xuất (`sp1.extractor`), kiểm tra trùng lặp (`sp1.deduplication` với MinHash-LSH), và tính toán quy chế (`sp2.drl_engine`) được thực thi trên máy chủ FastAPI.
2. **Tính Năng Đăng Nhập Riêng & Lưu Trữ Cục Bộ (Local Storage)**: Không hardcode cố định tên sinh viên; người dùng có thể chọn nhanh bất kỳ sinh viên nào trong nhóm hoặc nhập MSSV/Họ tên bất kỳ để quản lý hồ sơ và tiến độ ĐRL riêng biệt lưu tại máy.
3. **Giao Diện Dashboard Sinh Viên Thoáng Đãng**: Toàn bộ 5 ca test đã được tách riêng khỏi màn hình chính; sinh viên có thể tự do nhập liệu, dán link, kiểm tra bài đăng sự kiện bất kỳ như ứng dụng thật.
4. **Thư Viện Kịch Bản Mẫu (5 Ca E2E) & Chạy Hàng Loạt (Batch Run)**: Có nút nạp mẫu test nhanh (`⚡ 5 Kịch Bản E2E`) và tab riêng cho phép chạy hàng loạt cả 5 ca kiểm thử tự động trực quan.
5. **Khung Nghiệm Thu Kỹ Thuật (Inspector Tab)**: Tra cứu toàn bộ 15 trường dữ liệu thô, bằng chứng trích xuất (grounding evidence), cờ kiểm tra (`meta.flags`), và phân luồng (`activities.json` vs `review_queue.json`).
6. **Bộ 5 Ca Kiểm Thử E2E Tự Động**: Đạt 100% PASS qua test suite `pytest`.

---

## 2. HƯỚNG DẪN CÀI ĐẶT & KHỞI CHẠY

### Bước 1: Yêu cầu môi trường
- Python >= 3.10
- Các thư viện phụ thuộc:
  ```bash
  pip install fastapi uvicorn pydantic pytest datasketch
  ```

### Bước 2: Khởi động Server
Chạy lệnh duy nhất tại thư mục gốc của repository:
```bash
python run_server.py
```
*Server sẽ khởi động tại địa chỉ: `http://localhost:8000`*

### Bước 3: Mở ứng dụng trên trình duyệt
Truy cập:
👉 **[http://localhost:8000](http://localhost:8000)**

*(Lưu ý: Ứng dụng cũng tích hợp sẵn cơ chế **Safe Fallback** - nếu server chưa bật, giao diện vẫn có thể mô phỏng chính xác thuật toán để trình diễn mượt mà).*

---

## 3. HƯỚNG DẪN CHẠY BỘ TEST E2E TỰ ĐỘNG
Để chạy toàn bộ các bài kiểm thử End-to-End kiểm tra tính toàn vẹn của API và 5 kịch bản quy chuẩn:
```bash
python -m pytest tests/test_e2e_pipeline.py -v
```

**Kết quả kiểm thử đạt 100% PASS:**
- `test_api_health_endpoint`: Kiểm tra trạng thái máy chủ và bộ 75 quy tắc ĐRL.
- `test_student_profile_endpoint`: Kiểm tra hồ sơ sinh viên Lưu Minh Tiến (25127242).
- `test_e2e_case_1_pccc_projected_points`: Ca 1 - Tập huấn PCCC ghi nhận Điểm dự kiến (+5đ Mục 1.9, C1: 20 &rarr; 25/30đ).
- `test_e2e_case_2_blood_donation_confirmed_points`: Ca 2 - Hiến máu có giấy chứng nhận ghi nhận Đã xác nhận (+10đ Mục 4.2, C4: 10 &rarr; 20/25đ).
- `test_e2e_case_3_online_missing_requirements_d16`: Ca 3 - Webinar online thiếu điều kiện hoàn thành kích hoạt cờ D16 `needs_review:completion_requirements`, chuyển `review_queue.json`.
- `test_e2e_case_4_category_cap_c3`: Ca 4 - Kiểm tra chặn trần CALC_02 (Nhóm C3 đang 22/25đ, cuộc thi 10đ chỉ được cộng tối đa +3đ).
- `test_e2e_case_5_duplicate_detection`: Ca 5 - MinHash-LSH phát hiện bài đăng trùng lặp &ge; 75%, từ chối ghi nhận điểm.

---

## 4. CHI TIẾT 5 KỊCH BẢN NGHIỆM THU TRÊN GIAO DIỆN

| Ca | Tên sự kiện | Hành vi SP1 | Hành vi SP2 (QĐ 1028/QĐ) | Kết quả hiển thị |
|---|---|---|---|---|
| **Ca 1** | **Tập huấn PCCC 2026** | Trích xuất đủ 14 trường offline, status `valid`. | Khớp Quy tắc R19 (Mục 1.9), chưa có minh chứng điểm danh. | `PROJECTED` (+5đ dự kiến, C1: 20 &rarr; 25/30đ). |
| **Ca 2** | **Hiến máu tình nguyện** | Trích xuất đủ 14 trường offline, status `valid`. | Khớp Quy tắc R42 (Mục 4.2), có giấy chứng nhận. | `CONFIRMED` (+10đ chính thức, C4: 10 &rarr; 20/25đ). |
| **Ca 3** | **Webinar Zoom** | Phát hiện bài Online có ĐRL nhưng thiếu ĐK hoàn thành &rarr; Cờ D16. | Quy tắc CALC_05: thiếu điều kiện thì không suy đoán điểm. | `NEEDS_REVIEW_CALC_05` (Chuyển `review_queue.json`, +0đ). |
| **Ca 4** | **Olympic Mác-Lênin** | Trích xuất đủ 14 trường, status `valid`. | Khớp Quy tắc R3101 (Mục 3.1: +10đ). C3 đang đạt 22/25đ &rarr; CALC_02 áp trần. | `CONFIRMED` (Chặn trần +3đ, C3 đạt tối đa 25/25đ). |
| **Ca 5** | **Bài đăng trùng lặp** | MinHash-LSH quét qua cơ sở dữ liệu `source_posts.json`. | Phát hiện trùng URL/nội dung &ge; 75%. | `REJECTED_DUPLICATE` (Từ chối ghi nhận điểm). |

---

## 5. CẤU TRÚC MÃ NGUỒN GÓI BÀN GIAO (`Minh_Tien`)
```text
academic-campus-decision-assistant/
├── run_server.py                      # File khởi động FastAPI server & Web UI
├── RUN_GUIDE.md                       # Tài liệu hướng dẫn khởi chạy chi tiết
├── web/
│   └── index.html                     # Giao diện Web Dashboard sinh viên & Inspector
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   └── server.py                  # FastAPI REST API kết nối SP1 -> SP2
│   ├── sp1/
│   │   ├── extractor.py               # Bộ trích xuất 14/15 trường deterministic
│   │   ├── deduplication.py           # MinHash-LSH Deduplicator
│   │   ├── dates.py                   # Parser thời gian ISO 8601
│   │   └── regex_baseline.py          # Baseline regex patterns
│   └── sp2/
│       └── drl_engine.py              # Engine tính điểm ĐRL theo 1028/QĐ
├── data/
│   ├── activities.json                # Bộ 20 hoạt động chuẩn 14 trường của nhóm
│   ├── source_posts.json              # Dữ liệu 20 bài đăng Facebook gốc
│   ├── drl_rules.json                 # 75 quy tắc ĐRL theo QĐ 1028/QĐ-KHTN-CTSV
│   ├── student_profile.json           # Hồ sơ sinh viên
│   └── sample_e2e_io.json             # File mẫu Input / Expected Output nghiệm thu
├── schemas/
│   └── extraction_draft.schema.json   # Hợp đồng JSON schema draft v1.3.0
└── tests/
    └── test_e2e_pipeline.py           # 7 unit & E2E tests đạt 100% PASS
```
