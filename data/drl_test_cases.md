# Test Cases – SP2 DRL Rules Engine

**Mục đích:** Đối chiếu việc engine Python đọc `drl_rules.json`, kiểm tra điều kiện, trả về rule áp dụng, điểm và trạng thái cần xem xét.

**Lưu ý cho người triển khai:** Các expected output dưới đây dựa trên cấu trúc JSON hiện tại của nhóm. Với TC10, cần thống nhất schema đầu vào tổng điểm để tránh cộng trùng. Các test này kiểm tra logic kỹ thuật theo JSON hiện tại, không thay thế việc kiểm tra quy chế nguồn.

| Test ID | Nội dung kiểm thử | Kết quả mong đợi |
|---|---|---|
| TC01 | GPA = 8.5, không vi phạm học vụ/khảo thí | R11 (+10), R123 (+10); tổng điểm rule = 20 |
| TC02 | Không tham gia đủ nội dung sinh hoạt công dân | R6401 (-20) |
| TC03 | GPA = 9.0, có 1 vi phạm học vụ/khảo thí| Chỉ R1204 (+15) |
| TC04 | GPA = 7.2, có 1 vi phạm học vụ/khảo thí | Chỉ R1202 (+7) |
| TC05 | Có 1 đề tài nghiên cứu đủ điều kiện | R15 (+15) |
| TC06 | Vai trò hoạt động học thuật = BTC | R1701 (+10) |
| TC07 | Vai trò hoạt động học thuật = CTV | R1702 (+5) |
| TC08 | Không khai báo ngoại trú | R62 (-15) |
| TC09 | Thiếu `academic_exam_violations` | R1203 (+10); `needs_review = true`, báo thiếu trường; không tự gán 0 |
| TC10 | Điểm hiện có 96, điểm đủ điều kiện cộng thêm 25 | Tổng thô 121, điểm cuối sau giới hạn = 100; phải tránh cộng trùng |

