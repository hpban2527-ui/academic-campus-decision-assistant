# Project E — Biên bản nghiệm thu kỹ thuật H4/H5

**Ngày:** 29/10/2026  
**Nhóm:** E · SP1 + SP2 ĐRL  
**Lead:** Bình An  
**Nhánh nghiệm thu:** `integration/h4-h5-owner-review-20261029`  
**PR:** https://github.com/hpban2527-ui/academic-campus-decision-assistant/pull/5 (**Draft, chưa merge**)

## 1. Nội dung đã kiểm tra

- PR #4 của Tiến đã được đưa vào nền Lead từ PR #3 theo phương pháp chọn file, có Git merge commit lưu cả hai parent.
- Giữ nguyên module, dữ liệu, testcase và báo cáo của Trí, Duyên, Tuyền, Ngọc; không áp dụng các lệnh xóa file trên nhánh Tiến.
- API giao diện dùng: `/api/evaluate` xem trước; `/api/commit` ghi riêng; `/api/scores` xem điểm đã lưu; `/api/lead/audit` kiểm toán; `/api/sp2/evaluate` và `/api/pipeline/demo` dùng engine.
- Escape nội dung bài đăng và phản hồi API trước khi dùng `innerHTML`. Sửa tên hiển thị của Tiến.
- Bộ test session xác nhận preview không ghi điểm, commit ghi đúng, chặn lưu trùng, nâng cấp projected → confirmed không cộng hai lần và queue chỉ thay đổi khi gửi rõ ràng.

## 2. Kiểm thử máy thật trên GitHub Actions

Workflow: https://github.com/hpban2527-ui/academic-campus-decision-assistant/actions/runs/40857704270  
Commit được kiểm thử: `844b39a3a3a71eb014eb9c9eb0278a1ec3d92480`.

| Nhóm kiểm thử | Kết quả thật |
| --- | --- |
| SP1, SP2 và Lead backend integration | **269 passed**, 1 warning |
| Kiểm thử API/frontend và lưu điểm phiên | **23 passed**, 1 warning |
| 10 expected outputs quy tắc SP2 | **10/10 passed** |
| Chromium thật: 5 ca E2E qua giao diện → FastAPI | **5/5 passed** |
| XSS: API activity/review và evidence inspector | **2/2 không thực thi payload** |
| JavaScript errors trong lượt chạy browser | **0 lỗi được ghi nhận** |

Hai cảnh báo pytest không làm job thất bại. Không suy từ test PASS thành mức độ an toàn tuyệt đối.

### H4 — 5 ca đầu vào → đầu ra

| Ca | Dữ liệu | Expected/actual trên web |
| --- | --- | --- |
| 1 | Tập huấn PCCC, chưa có minh chứng | `PROJECTED` +5, C1 = 20/30 xác nhận, 25/30 giả định |
| 2 | Hiến máu, có minh chứng giả lập | `DEMO_CONFIRMED` +10, C4 = 10 → 20/25 |
| 3 | Webinar thiếu điều kiện hoàn thành | `NEEDS_REVIEW`, không cộng điểm |
| 4 | Olympic, nhóm C3 gần trần | `DEMO_CONFIRMED` +3 thay vì +10, C3 = 22 → 25/25 |
| 5 | Bài đăng trùng URL/nội dung | `REJECTED_DUPLICATE`, +0 |

Test trình duyệt bấm **Chạy tất cả 5 ca**, so sánh bản ghi 14 trường và các expected: `decision`, `rule_id`, `category_id`, `category_before/after`, `hypothetical_category_after`, `category_cap`, `projected_added`, `confirmed_added`, `DEMO_ONLY`. Ngoài batch còn bấm thử riêng ca 1 và kiểm tra kết quả dự kiến hiển thị ở dashboard. Lưu ý 5 kịch bản này là dữ liệu **demo**; không được hiểu là năm hoạt động đã được trường xác minh.

## 3. Ảnh và dữ liệu bằng chứng

GitHub Actions đã lưu ZIP artifact, gồm:

- `01_five_cases_pass.png`: màn hình kết quả chạy 5 ca;
- `02_single_post_pipeline.png`: kết quả một bài đăng trực tiếp;
- `03_xss_safe_rendering.png`: trang hoạt động khi bơm payload HTML;
- `evidence.json`: năm ca PASS, kết quả XSS và số lỗi JS.

Artifact: https://github.com/hpban2527-ui/academic-campus-decision-assistant/actions/runs/40857704270/artifacts/12890480714

Các ảnh được Chromium tạo trong CI; đây là bằng chứng kiểm thử chạy thực, không phải ảnh dựng thủ công. Artifact có thể bị GitHub xóa sau thời gian lưu trữ, nên lưu bản ZIP khi chốt hồ sơ môn học.

## 4. Giữ file và công sức các owner

Đối chiếu Git tree trước và sau commit hợp nhất hai nhánh:

- Nhánh Lead trước hợp nhất: **75 file blob**.
- Ngay sau bước hợp nhất và thêm browser test: **77 file blob**.
- **0 file của nhánh Lead bị xóa**.
- `Collecting_Data/`, `data/raw/`, `data/gold/`, `data/drl_test_cases*`, `tests/sp1/`, `tests/sp2/` và tài liệu quy chế giữ nguyên blob SHA.
- Phần mới từ Tiến chỉ thay các file cần thiết cho UI/API/session, không ghi đè rules/test đã khóa của owner khác.

Cách đối chiếu: Git REST `git/trees/<tree-sha>?recursive=1` (blob paths và SHA), không phải chỉ so tên file bằng mắt.

## 5. Giới hạn và quyết định

- SP1 trên 20 thông báo nguồn vẫn có lỗi trích xuất được ghi trong `reports/sp1_test_report.md`. Cơ chế review chặn bản ghi thiếu/chưa được duyệt nhưng **chưa thay thế việc nâng độ chính xác extractor**.
- Sổ tay ĐRL hiện hành 2026 cần được nhà trường xác nhận khi dùng ngoài demo; bộ QĐ1028 là bộ quy tắc mô phỏng đã đối chiếu một số mục (R11, R23, R4302).
- Checkbox minh chứng hoặc `SYNTHETIC_EVIDENCE_FIXTURE` không xác nhận điểm chính thức; `official_award_verified=false`.
- Browser automation là kiểm thử E2E ở một môi trường GitHub Actions và không bảo đảm mọi trình duyệt, mọi dữ liệu đều không lỗi.
- PR #5 đang **Draft** để nhóm review; chưa có approval và **không merge `main`**.

**Kết luận kỹ thuật H4/H5:** phần tích hợp/demo đạt các tiêu chí tự động đã kiểm thử. **Trạng thái release:** `READY_FOR_OWNER_REVIEW`, không phải `MERGED` hoặc `OFFICIAL_DRL_PRODUCTION`. Nhóm trưởng quyết định khi có review/approval thật.
