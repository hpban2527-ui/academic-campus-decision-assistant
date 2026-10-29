# PROJECT E — SP1 + SP2 (Điểm rèn luyện)

Lead & Integration: Bình An. SP1: Trí (data), Duyên (extractor). SP2: Tuyền (rules), Ngọc (engine). UI: Tiến. SP3 chưa triển khai.

## Chạy thử

~~~bash
python -m pip install -r requirements.txt
python run_server.py
~~~

Web: http://localhost:8000. Bật server trước khi mở trang. Giao diện do Tiến xây, dữ liệu và điểm đang ở chế độ **DEMO_ONLY** (không phải điểm ĐRL chính thức).

## API và đầu ra

- GET /api/health — trạng thái, số lượng rules, cảnh báo quy chế.
- GET /api/activities — dữ liệu hoạt động thu thập, **chưa được xác nhận ĐRL**.
- GET /api/rules — bộ 75 quy tắc của Tuyền và nguồn.
- POST /api/evaluate — văn bản + nguồn → SP1 → 14-field candidate → kiểm tra trùng/review. Mặc định là strict intake, không tự cộng điểm. Với `simulate_demo=true` sẽ chạy chấm điểm mô phỏng trên engine SP2.
- POST /api/commit — thao tác **Lưu** riêng sau bước xem trước; backend đánh giá lại, tránh cộng trùng; chỉ ghi bảng điểm demo hoặc đưa bài vào hàng đợi review.
- GET /api/scores?student_id=... — trả điểm đã lưu/dự kiến theo sinh viên (demo).
- POST /api/reset — đặt lại trạng thái phiên mẫu.
- GET /api/e2e-cases — trả 5 ca kiểm thử kèm expected output.
- POST /api/sp2/evaluate — chạy engine của Ngọc trên snapshot mẫu; trả `DEMO_ONLY`, không xác nhận điểm chính thức.
- POST /api/pipeline/demo — **bài đăng mẫu → SP1 → bước duyệt mô phỏng → rule R19 → engine SP2**; so sánh điểm dự kiến với minh chứng mô phỏng. Chỉ chấp nhận kịch bản mẫu phía server, không cho client tự duyệt.
- GET /api/lead/audit — kiểm tra chất lượng dataset, rules đang cần review và nhóm thông báo trùng có đầy đủ nguồn.

Ví dụ input POST /api/sp2/evaluate:

~~~json
{"demo":true,"student_profile":{"university":"HCMUS"},"scope":{"universities":["HCMUS"]},"student_snapshot":{"status":"CONFIRMED","evidence_status":"VERIFIED","values":{"semester_gpa":8.5,"academic_exam_violations":0}},"personal_targets":{"C1":30}}
~~~

Kết quả logic minh họa C1 = 20/30, còn thiếu 10; **không** phải kết quả ĐRL chính thức.

## Hợp đồng đã khóa

- schemas/activity.schema.json: output công bố **14 trường**.
- Extractor Duyên tạo draft **15 trường**; drl_recognized được lưu vào meta ở cổng công bố, không thêm vào 14 trường cuối.
- Theo quyết định nhóm: mandatory không nêu → false; fee không nêu → 0. Mọi giá trị mặc định lưu lý do trong meta.derived.
- Thiếu mode/completion_requirements và các lỗi chứng cứ phải review.
- Các bài regex dù được ghi valid vẫn **cần người duyệt** trước khi công bố, vì từng xảy ra false-positive về ngày.
- Chuẩn hóa URL bỏ các tham số theo dõi để ID bền vững. SP1 trích xuất không đồng nghĩa SV đủ điều kiện nhận điểm.

## Chạy kiểm thử

~~~bash
PYTHONPATH=src python -m pytest -q tests/sp1 tests/sp2 tests/integration tests/test_e2e_pipeline.py tests/test_session_flow.py
python -m compileall -q src tests scripts run_server.py
python scripts/check_team_source_integrity.py
~~~

Trên PowerShell, đặt $env:PYTHONPATH = "src" trước khi chạy lệnh pytest. CI: .github/workflows/integration.yml.

## Bàn giao H4–H5 – bản tích hợp cuối chờ duyệt

PR tổng hợp: https://github.com/hpban2527-ui/academic-campus-decision-assistant/pull/5

Nhánh `integration/h4-h5-owner-review-20261029` nhận giao diện và luồng lưu điểm từ PR #4 của Tiến vào nền code SP1/SP2/Lead trên PR #3. **Không có file nào của nhóm bị xóa.**

Để chạy thử đủ luồng: mở web, vào danh sách 5 ca demo, bấm chạy từng ca hoặc **Chạy tất cả 5 ca** trong chế độ developer. Mỗi ca so sánh bản ghi 14 trường, trạng thái, quy tắc, nhóm, trần và điểm với expected output. Hai bước **Xem trước** và **Lưu** là hai thao tác khác nhau.

Kiểm thử qua Chromium thật (cần Playwright):

~~~bash
python -m pip install playwright
python -m playwright install chromium
python scripts/verify_browser_e2e.py
~~~

Kết quả và ba hình ảnh demo tự động được tải lên GitHub Actions artifact:
https://github.com/hpban2527-ui/academic-campus-decision-assistant/actions/runs/40859734284/artifacts/12889804760

Kết quả nghiệm thu đã ghi trong `reports/H4_H5_ACCEPTANCE_20261029.md`. Review PR #4 và kiểm tra bảo toàn tài liệu nằm trong `docs/PR4_REVIEW_20261029.md`.

**Chưa merge `main`.** Đã yêu cầu Tiến và Như Ngọc review; cần ít nhất 1 approval hợp lệ theo ruleset trước khi nhóm trưởng quyết định. CI cuối: 269 backend + 25 frontend/session tests, 10/10 rules, 5/5 Chromium; 54/54 tệp nhóm giữ nguyên SHA.

## Kết quả đã kiểm thử

CI: [GitHub Actions](https://github.com/hpban2527-ui/academic-campus-decision-assistant/actions). Trên commit được ghi ở `reports/LEAD_INTEGRATION_CI_20261027.md`, backend và integration đã chạy qua GitHub Actions; số lượng test có thể tăng sau mỗi commit.

Kịch bản API mới:

~~~bash
curl -X POST http://localhost:8000/api/pipeline/demo -H "Content-Type: application/json" -d '{"case_id":1}'
curl -X POST http://localhost:8000/api/pipeline/demo -H "Content-Type: application/json" -d '{"case_id":1,"with_demo_confirmation":true}'
~~~

- Trường hợp chưa có minh chứng: điểm **dự kiến**, không tăng điểm đã xác nhận.
- Trường hợp có minh chứng từ fixture phía server: chỉ tính **xác nhận trong demo**, không được hiểu là xác nhận chính thức.
- Không tự chọn quy tắc bằng từ khóa; mapping `rule_id` nằm trong bản duyệt.
- Không tự cộng hoạt động có trong danh sách đã tính; áp trần qua engine SP2.
- Mọi hoạt động được regex trả `valid` vẫn cần người duyệt. P08 với ngày trích dẫn từ thông báo cũ sẽ bị gắn cờ.
- Bài trùng vẫn giữ các URL và đơn vị đăng, đưa về review.

## Quy chế và giới hạn

- Quyết định 1028 (phụ lục mục 1.1): **R11 = 10 điểm**; đã sửa riêng bản trên nhánh tích hợp và cập nhật expected outputs.
- Mục 2.2: **R22** là đánh giá trên 50% môn học; **R23** không có căn cứ độc lập trong phụ lục đang đối chiếu, đã đặt `needs_review` để không tự cộng.
- Mục 4.3: **R4302** dùng phân nhóm thời lượng đã xác minh `24_hours_to_under_one_week`, không chuyển "một tuần" thành 168 giờ lao động.
- Sổ tay HCMUS đã đăng khung của **Thông tư 40/2026** với cơ cấu điểm mới. Khả năng áp dụng bộ 1028 cho học kỳ hiện tại phải được xác nhận với nhà trường. Toàn bộ đầu ra trên nhánh này chỉ là **demo**, không phải điểm ĐRL chính thức.
- Chưa có hệ thống xác thực minh chứng của HCMUS hoặc quy trình phê duyệt nhân sự thực tế. Test dùng bản duyệt và giấy xác nhận **giả lập, có gắn nhãn**.
- Phần UI do Tiến phụ trách; Lead chỉ quản lý hợp đồng API, kiểm thử và merge sau khi review.

Nguồn và danh sách các hạn chế: `docs/REGULATION_SOURCE_AUDIT_20261027.md`, `docs/LEAD_INTEGRATION_HANDOFF.md`.

Chưa merge `main` khi chưa được approval theo ruleset và xác minh điều kiện nghiệm thu.
