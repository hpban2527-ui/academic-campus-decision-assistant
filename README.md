# PROJECT E — SP1 + SP2 (Điểm rèn luyện)

Lead & Integration: Bình An. SP1: Trí (data), Duyên (extractor). SP2: Tuyền (rules), Ngọc (engine). UI: Tiến. SP3 chưa triển khai.

## Chạy thử

~~~bash
python -m pip install -r requirements.txt
python run_server.py
~~~

Web: http://localhost:8000. Phải bật server; JavaScript **không** còn cơ chế tính điểm giả khi API mất kết nối.

## API và đầu ra

- GET /api/health — trạng thái, số lượng rules, cảnh báo quy chế.
- GET /api/activities — dữ liệu hoạt động thu thập, **chưa được xác nhận ĐRL**.
- GET /api/rules — bộ 75 quy tắc của Tuyền và nguồn.
- POST /api/evaluate — văn bản + nguồn → SP1 → 14-field candidate → trùng lặp/review. Không cộng điểm từ bài đăng hoặc checkbox.
- POST /api/sp2/evaluate — chạy **engine của Ngọc với rules của Tuyền** trong chế độ DEMO_ONLY. Phải có snapshot sinh viên được đánh dấu minh chứng hợp lệ trong dữ liệu demo. Trả official_award_verified=false.

Ví dụ input POST /api/sp2/evaluate:

~~~json
{"demo":true,"student_profile":{"university":"HCMUS"},"scope":{"universities":["HCMUS"]},"student_snapshot":{"status":"CONFIRMED","evidence_status":"VERIFIED","values":{"semester_gpa":8.5,"academic_exam_violations":0}},"personal_targets":{"C1":30}}
~~~

Kết quả logic minh họa C1 = 25/30, còn thiếu 5; **không** phải kết quả ĐRL chính thức.

## Hợp đồng đã khóa

- schemas/activity.schema.json: output công bố **14 trường**.
- Extractor Duyên tạo draft **15 trường**; drl_recognized được lưu vào meta ở cổng công bố, không thêm vào 14 trường cuối.
- Theo quyết định nhóm: mandatory không nêu → false; fee không nêu → 0. Mọi giá trị mặc định lưu lý do trong meta.derived.
- Thiếu mode/completion_requirements và các lỗi chứng cứ phải review.
- Các bài regex dù được ghi valid vẫn **cần người duyệt** trước khi công bố, vì từng xảy ra false-positive về ngày.
- Chuẩn hóa URL bỏ các tham số theo dõi để ID bền vững. SP1 trích xuất không đồng nghĩa SV đủ điều kiện nhận điểm.

## Chạy kiểm thử

~~~bash
PYTHONPATH=src python -m pytest -q tests/sp1 tests/sp2 tests/integration tests/test_e2e_pipeline.py
python -m compileall -q src tests scripts run_server.py
~~~

Trên PowerShell, đặt $env:PYTHONPATH = "src" trước khi chạy lệnh pytest. CI: .github/workflows/integration.yml.

## Chưa thể gọi là nghiệm thu cuối

- Duyên báo 20 bài: 7 valid, 10 partial, 3 failed; 5/7 valid còn sai ít nhất một trường. Cần review thủ công/lỗi ngày được sửa và đo lại.
- R22 và R23 của Tuyền có điều kiện trùng; R4302 có ngưỡng "one_week" không phải số. Engine đánh dấu chưa thể tự chấm; phải đối chiếu văn bản quy chế trước khi sửa.
- Dữ liệu Trí có bài đăng chéo và nguồn tổ chức khác nguồn chia sẻ; giữ URL nguồn/ghi nhận xung đột.
- Checkbox has_evidence, lựa chọn rule_override và tự gửi "VERIFIED" từ trình duyệt không được coi là xác minh độc lập. Để xác nhận điểm chính thức cần nguồn dữ liệu/thẩm quyền từ trường.
- Frontend có hồ sơ và số điểm mẫu; đã gắn banner DEMO, không phù hợp dùng trực tiếp cho hồ sơ thật.

Chỉ mở nhánh/PR để review, **không merge main**.
