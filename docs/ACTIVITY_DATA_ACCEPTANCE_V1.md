# Hợp đồng sử dụng dữ liệu hoạt động v1

Thống nhất với người dùng ngày 18/11/2026. Phiên bản hiện hành: `activity-acceptance/1.2` (xem mục "1.1 changes" và "1.2 changes"; bản 1.0 là nội dung còn lại).
Triển khai: `src/sp1/acceptance.py`, cấu hình `data/config/activity_acceptance_v1.json`.

## Nguyên tắc

- AI trích xuất dữ kiện và bằng chứng; quy tắc quyết định khả năng dùng dữ kiện. Không cần người duyệt từng bài để chạy phân loại tự động.
- Không có thông tin trong nguồn là một kết quả hợp lệ (`null` hoặc `[]`), không phải yêu cầu phải đoán hoặc bắt người duyệt điền cho đủ.
- `AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD` khác với nhãn người đã kiểm tra và gold độc lập. Hai lớp trạng thái này không thay thế nhau.
- Phạm vi đợt hiện tại: 129 bài dev/pool. Không sử dụng hoặc thay đổi 60 bài test.

## Quyết định dữ liệu

| Trạng thái | Ý nghĩa |
| --- | --- |
| READY | Đủ dữ kiện tạo lịch, chưa có cảnh báo dữ liệu |
| READY_WITH_WARNINGS | Đủ dữ kiện lịch; giữ các trường phụ thiếu/chưa chắc |
| NOT_SCHEDULABLE | Chưa có lịch có thể bảo vệ bằng dữ kiện/quy ước; lưu nguồn và lý do, không tự đưa vào lịch |
| NOT_AN_ACTIVITY | Bài chỉ cung cấp thông tin; lưu để tra cứu |

Các trạng thái nói về độ sẵn sàng dữ liệu, không bảo đảm sinh viên đủ điều kiện, chưa quá hạn hay sẽ đạt điểm. SP2/SP3 phải tiếp tục áp các cổng đó.

## Lịch

- Buổi offline, online trực tiếp hoặc hybrid cần ngày và giờ bắt đầu được nêu. Không lấy ngày đăng bài hoặc `00:00` của ngày chỉ có độ chính xác đến ngày làm giờ tham gia.
- Có giờ bắt đầu nhưng không có giờ kết thúc: giữ quy ước nhóm 120 phút offline, 30 phút online/hybrid; dùng thời lượng công bố nếu có. Ghi rõ `team_default` trong lịch, không thêm vào dữ kiện trích xuất.
- Quiz online có cửa sổ tham gia rõ được xếp linh hoạt. Biên chỉ có ngày được chuẩn hóa 00:00 và 23:59 như biên cửa sổ, không phải giờ tham gia bắt buộc. Thời lượng công bố được ưu tiên, nếu thiếu dùng 30 phút theo quy ước nhóm.
- Không biến webinar/Zoom/Meet thành quiz linh hoạt chỉ vì có một phần trắc nghiệm. Chưa xác định chắc lịch/cửa sổ thì chặn tự động thay vì giả định.
- Không rút ngắn thời lượng đã nêu để ép hoạt động vừa cửa sổ.
- Xung đột hay chưa chắc ở trường lịch cốt lõi chặn xếp lịch. Các nghĩa vụ bắt buộc không xếp được vẫn được giữ cảnh báo.
- Nhiều buổi/vòng: bản ghi đang xét buổi đầu theo phạm vi nhóm; các yêu cầu toàn khóa vẫn phải giữ ở ghi chú, không tuyên bố hoàn thành toàn khóa chỉ bằng một buổi.

## Thiếu hoặc chưa rõ trường phụ

- Domain không rõ: giữ `null`; không tự coi là khớp sở thích.
- Chi phí không rõ hoặc nhiều mức chưa chọn được: giữ `null` ở giá trị vận hành; không tự coi là 0. Phí theo đội/đặt cọc/đơn vị không rõ không đủ chứng minh ngân sách theo người.
- Không có URL đăng ký không tự loại hoạt động. Giữ cách tham gia trong nguồn; URL chỉ có ý nghĩa khi nguồn thực sự cung cấp.
- Không có hạn đăng ký: giữ `null` và cảnh báo, không tự lấy giờ bắt đầu làm hạn.
- Địa điểm hoặc loại hoạt động còn chưa chắc: giữ cảnh báo và giá trị chưa biết. Chưa rõ địa điểm không được khẳng định phù hợp cơ sở; chưa rõ loại không được tự gán quy tắc tính điểm.
- Các giới hạn đối tượng, điều kiện hoàn thành, tính bắt buộc còn mâu thuẫn không được âm thầm bỏ qua. Thiếu năng lực biểu diễn được ghi rõ để bổ sung hợp đồng sau; tạm không tự lập lịch với điều kiện chưa chắc.

## Duyệt và tương thích

- Sửa lỗi trích xuất chỉ qua `data/review/decisions.csv` (gắn với fingerprint của văn bản); kết quả vẫn được phân loại lịch độc lập.
- Danh mục v1 dùng `unilife-policy-catalog/1.0`, gồm `accepted_record`, `schedule`, `warnings`, `budget_known`, `scoring_verified=false`, `student_eligibility_verified=false`.
- Hợp đồng SP3 14 trường cũ đang yêu cầu `fee` là số; không ép `null` thành 0 để tương thích. Bộ danh mục mới là đầu vào cho adapter cập nhật sau, không tự thay thế dữ liệu runtime của branch khác.
- Không công bố tỉ lệ đúng NLP từ số bản ghi đạt policy. Đây là kiểm tra cấu trúc và điều kiện dùng dữ liệu, không phải thước đo tính đúng ngữ nghĩa.

## 1.1 changes

- **Uncertain end of a fixed event.** If `window_open` has a certain date and time and `window_close` is the only
  uncertain schedule field (`window_open`, `window_close`, `duration_minutes_stated`), `window_close` is ignored.
  The end is the stated duration, otherwise the team default (120 minutes offline, 30 online/hybrid), with the
  warning `uncertain_end_time_default_used`. A flexible online quiz with an uncertain end still blocks
  (`uncertain:window_close`), as does an uncertain `window_open` or a date-only start.
- **Uncertain `completion_requirements` is soft.** The accepted value is unknown, the warning is
  `uncertain_soft:completion_requirements`, and the SP3 activity carries the marker `UNKNOWN` (not `NOT_STATED`,
  which means the post says nothing). It is never treated as completed or as "none required".
- **Review path.** The offline viewer and human-export import were removed; `data/review/decisions.csv` is the
  only correction mechanism.

## 1.2 changes

Plausibility checks (limits in `plausibility` of `data/config/activity_acceptance_v1.json`). Every hit carries a
machine-readable code; none invents a time, deadline or cost.

| Check | Code | Effect |
| --- | --- | --- |
| End not after start | `end_before_start`, `invalid_quiz_window` | excluded |
| FIXED block longer than 12 h unless the stated duration covers it | `fixed_duration_over_12h` | excluded |
| FLEXIBLE window longer than 62 whole days | `flexible_window_over_62_days` | excluded |
| Event more than 400 days from `date_posted` | `event_far_from_post_date` | excluded |
| Date whose year was inferred from the post date lies outside [post - 60 days, post + 400 days] | `inferred_year_inconsistent_with_post_date` | excluded |
| Stated registration deadline after the event start | `registration_deadline_after_start` | warning only |

An online, non-live activity with a stated sitting shorter than a long timed window ("40 questions in 45 minutes",
open for several days) is scheduled as a flexible window (warning `online_window_treated_as_flexible`) instead of
one long FIXED block.
