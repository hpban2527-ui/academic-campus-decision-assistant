# HƯỚNG DẪN KHỞI CHẠY VÀ NGHIỆM THU WEB DEMO (RUN GUIDE)
**Hệ Thống Hỗ Trợ Đánh Giá Hoạt Động & Điểm Rèn Luyện (SP1 &rarr; SP2)**
*Môn học: CSC10014 - Tư Duy Tính Toán | Nhóm E*  
*Thành viên phụ trách Giao diện & Web Demo: **Lưu Minh Tiến (25127242)** | Nhánh: `Minh_Tien`*

---

## 1. TỔNG QUAN CÁC TÍNH NĂNG TRÊN WEB DEMO

Giao diện Web (`web/index.html`) kết nối trực tiếp với máy chủ **FastAPI (`src/api/server.py`)**, tích hợp đầy đủ các thành phần của cả nhóm:

1. **Gọi API Thật 100%, Không Hardcode / Không Giả Lập Trên Client**:
   - Mọi dữ liệu hồ sơ sinh viên (`/api/students`, `/api/profile`), 5 kịch bản kiểm thử (`/api/e2e-cases`), kho hoạt động (`/api/activities`), kiểm toán dữ liệu (`/api/lead/audit`), và tính điểm ĐRL (`/api/evaluate`, `/api/pipeline/demo`, `/api/sp2/evaluate`) đều được xử lý tại Backend.
   - Đã loại bỏ hoàn toàn cơ chế tính điểm giả trên trình duyệt (`runClientFallback`).
2. **Hỗ Trợ Chế Độ Kép (Dual-Mode Evaluation)**:
   - **Chế độ 1 — Mô Phỏng ĐRL Demo (`simulate_demo=true`, mặc định trên UI)**: Chạy xuyên suốt `SP1 (extract)` $\rightarrow$ `prepare_publication (14 trường)` $\rightarrow$ `evaluate_reviewed_activity` $\rightarrow$ `sp2.drl_engine.evaluate_progress`. Hiển thị đầy đủ điểm theo mục (`C1..C5`), điểm thiếu, điểm dự kiến tách biệt với điểm xác nhận Demo, chặn trần `CALC_02`, lý do và nguồn quy chế kèm nhãn `DEMO_ONLY` (`official_award_verified=false`).
   - **Chế độ 2 — Cổng Tiếp Nhận Nghiêm Ngặt (`simulate_demo=false`, theo PR #3)**: Chuẩn hóa 14 trường, kiểm tra trùng lặp và đẩy vào `review_queue` (`publication_status="REVIEW_REQUIRED"`), trả về `+0đ` và xử lý an toàn toàn bộ các trường `null`.
3. **Tách Biệt Rõ Ràng Điểm Dự Kiến (`PROJECTED`) Và Điểm Xác Nhận Demo (`DEMO_CONFIRMED`)**:
   - Khi hoạt động chưa có minh chứng (như Ca 1 PCCC), hệ thống chỉ cộng vào **Điểm dự kiến (+5đ)** và giữ nguyên **Điểm xác nhận (20/30đ)** trên thanh tiến độ, hiển thị đồng thời cả hai dải màu trên biểu đồ nhóm tiêu chí.
4. **Tích Hợp Mô Phỏng Snapshot Học Vụ (`POST /api/sp2/evaluate`)**:
   - Cho phép nhập GPA học kỳ, số lần vi phạm quy chế thi, tỷ lệ đánh giá môn học và thử kích hoạt quy tắc khảo sát `R23` để kiểm chứng trực tiếp hàm `evaluate_rules_progress()` của SP2.
5. **Tích Hợp Kiểm Toán Dữ Liệu & Quy Chế (`GET /api/lead/audit`)**:
   - Hiển thị trực tiếp số bài thiếu `mode` (5 bài), thiếu `completion_requirements` (18 bài), quy tắc tạm khóa (`R23`), và cụm bài đăng trùng nguồn (`possible_duplicates`).

---

## 2. HƯỚNG DẪN CÀI ĐẶT & KHỞI CHẠY

### Bước 1: Cài đặt thư viện phụ thuộc
Yêu cầu Python >= 3.10. Chạy lệnh sau tại thư mục gốc của dự án:
```bash
python -m pip install -r requirements.txt
```

### Bước 2: Khởi động máy chủ FastAPI & Web UI
```bash
python run_server.py
```
Server sẽ lắng nghe tại địa chỉ: `http://localhost:8000`

### Bước 3: Mở giao diện Web trên trình duyệt
Truy cập: **[http://localhost:8000](http://localhost:8000)**

---

## 3. CHI TIẾT 5 KỊCH BẢN KIỂM THỬ E2E TRÊN GIAO DIỆN

Trên giao diện Web, bấm nút **`⚡ 5 Ca E2E Mẫu`** (góc trên bên phải) hoặc chuyển sang Tab **`2. Kịch Bản Kiểm Thử (5 Ca E2E)`** và bấm **`▶ Chạy Kiểm Thử Tự Động Cả 5 Ca (Kiểm Tra Assertions)`**:

| Ca | Tên kịch bản | Hành vi SP1 & Cổng 14 trường (`lead_contract`) | Hành vi SP2 (`sp2.drl_engine`) ở Chế độ Demo | Kết quả hiển thị trên UI |
|---|---|---|---|---|
| **Ca 1** | **Tập huấn PCCC 2026** | Trích xuất đủ 14 trường offline, `status="valid"`, `mandatory=false`, `fee=0`. | Khớp `R19` (Mục 1.9, C1 `+5đ`). Chưa có minh chứng (`evidence=false`). | `PROJECTED`: **+5đ dự kiến**, `+0đ xác nhận`. Mục C1 giữ `20/30đ` xác nhận (gộp dự kiến `25/30đ`, thiếu `5đ`). |
| **Ca 2** | **Hiến máu tình nguyện** | Trích xuất đủ 14 trường offline, `status="valid"`, có điều kiện giấy chứng nhận. | Khớp `R42` (Mục 4.2, C4 `+10đ`). Có minh chứng mô phỏng (`evidence=true`). | `DEMO_CONFIRMED`: **+10đ xác nhận Demo**. Mục C4 tăng từ `10` $\rightarrow$ `20/25đ` (thiếu `5đ`). |
| **Ca 3** | **Webinar Trực tuyến thiếu ĐK** | Bài đăng `online` có công nhận ĐRL nhưng thiếu điều kiện hoàn thành $\rightarrow$ gắn cờ D16 `needs_review:completion_requirements`. | Quy tắc `CALC_05`: bản ghi có cờ `needs_review` bị chặn tính điểm, chuyển vào `review_queue`. | `NEEDS_REVIEW`: **+0đ dự kiến, +0đ xác nhận**. Hiển thị rõ cờ lỗi `needs_review:completion_requirements`. |
| **Ca 4** | **Hội thi Olympic Mác-Lênin (Chạm trần C3)** | Trích xuất đủ 14 trường offline, `status="valid"`. | Khớp `R3101` (Mục 3.1, quy chế `+10đ`). Do nhóm C3 đang ở mức `22/25đ`, `evaluate_progress` áp trần `CALC_02`. | `DEMO_CONFIRMED`: **Chỉ cộng +3đ** (thay vì `+10đ`). Mục C3 đạt tối đa `25/25đ` (thiếu `0đ`). |
| **Ca 5** | **Bài đăng trùng lặp (Deduplicator)** | Trùng `post_id` và tương đồng MinHash-LSH $\ge 75\%$ với bài đăng gốc trong `source_posts.json`. | Chặn cộng điểm lặp lần 2, phân luồng `discarded_duplicate`. | `REJECTED_DUPLICATE`: **+0đ**. Hiển thị cảnh báo trùng nguồn và mã bài gốc. |

---

## 4. HƯỚNG DẪN CHẠY BỘ TEST TỰ ĐỘNG (`pytest`)

Để kiểm tra toàn bộ các bài test tích hợp (cả chế độ Strict Intake của PR #3, chế độ Demo 5 ca E2E, và 10 test cases quy chế SP2):

```powershell
$env:PYTHONPATH = "src"
python scripts/check_sp2_cases.py
python -m pytest -v tests/integration tests/test_e2e_pipeline.py
```
