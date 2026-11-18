# SP2 → SP3 Output Contract (sp2_sp3_v1)

## 1. Mục đích
SP2 bàn giao trạng thái điểm rèn luyện của sinh viên để SP3 lập kế hoạch hoạt động. SP3 vẫn tự nhận danh sách hoạt động từ SP1, mục tiêu cá nhân và lịch rảnh của sinh viên; các dữ liệu đó không bị coi là đã nằm đầy đủ trong output SP2.

## 2. Nguyên tắc
- `confirmed_total` chỉ gồm điểm đã được xác nhận hợp lệ.
- Điểm ghi trên thông báo SP1 không tự động trở thành điểm đã xác nhận.
- `expected_points` là điểm dự kiến sau khi đối chiếu được hoạt động với quy chế; không cộng vào `confirmed_total`.
- Thiếu minh chứng, thiếu thông tin hoặc không xác định được tiêu chí thì để `null` và bật `needs_review`; không tự suy đoán.
- Trần điểm nhóm lấy từ `scoring_model.category_caps`. Không tự gán trần nhóm thành trần của từng tiêu chí.
- `DEDUCTION` là nhóm điểm trừ; không có trần nhóm dương. Tổng cuối cùng vẫn bị giới hạn theo `max_total_score`.
- Schema này là hợp đồng dữ liệu đề xuất cho SP3; engine cần xuất đúng cấu trúc này sau khi adapter/điều chỉnh hoàn tất.

## 3. Cấu trúc trường

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `schema_version` | string | Phiên bản hợp đồng output |
| `student` | object | Mã sinh viên, học kỳ và loại hình đào tạo |
| `regulation` | object | Quyết định áp dụng, trạng thái kiểm tra phạm vi và nguồn |
| `summary` | object | Tổng điểm đã xác nhận, trần tổng và điểm còn thiếu đến 100 |
| `category_scores` | array | Điểm thô, điểm sau trần và điểm còn thiếu theo C1–C5/DEDUCTION |
| `criteria` | array | Điểm đã xác nhận theo từng tiêu chí, rule và hồ sơ đóng góp |
| `activity_assessments` | array | Điểm công bố, điểm dự kiến, tiêu chí/rule khớp và tình trạng tham gia/xác minh |
| `pending_records` | array | Hồ sơ đang chờ hoặc cần xác minh, không tính vào tổng |
| `review` | object | Cờ và lý do cần người kiểm tra |

## 4. Định nghĩa quan trọng
- `raw_confirmed_points`: tổng điểm hợp lệ trước khi áp trần nhóm.
- `confirmed_points`: điểm được ghi nhận sau khi áp trần nhóm.
- `cap`: trần của nhóm; `null` đối với DEDUCTION.
- `remaining_to_cap`: `max(0, cap - confirmed_points)`; `null` nếu không có trần.
- `criterion_id`: mã tiêu chí trong quy chế, ví dụ `1.1`, `1.2`, `4.3`.
- `matched_rule_ids`: danh sách rule_id trong `drl_rules.json` làm căn cứ tính điểm.
- `announced_points`: điểm được công bố trong dữ liệu SP1.
- `expected_points`: điểm dự kiến sau khi đối chiếu quy chế và có đủ căn cứ; có thể khác `announced_points`.
- `confirmed_points` trong `activity_assessments`: điểm của hoạt động đã được xác nhận; nếu chưa xác nhận thì bằng 0.
- `scope_status`: `APPLICABLE`, `NEEDS_INFO`, `NEEDS_VERIFICATION` hoặc `NOT_APPLICABLE`.
- `verification_status`: `CONFIRMED`, `VERIFIED`, `NEEDS_VERIFICATION`, `UNVERIFIED`.

*Lưu ý*: 
`sp2_sp3_output_sample.json` là một output mẫu hoàn chỉnh. `sp2_sp3_output_tests.json` gồm các input và expected output để kiểm tra những tình huống quan trọng của chính schema này. 