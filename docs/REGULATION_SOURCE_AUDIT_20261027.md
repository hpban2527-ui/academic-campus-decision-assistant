# Đối chiếu quy chế ĐRL – 27/10/2026

Phạm vi: bộ `data/drl_rules.json` của sprint SP1–SP2, dựa trên QĐ 1028/QĐ-KHTN ngày 04/09/2020. Đây là **bản đối chiếu quy chế cho demo**, chưa phải chứng nhận quy định có hiệu lực cho mọi học kỳ 2026.

## Nguồn đã đọc

1. Bản QĐ 1028 kèm phụ lục (website chính thức HCMUS): https://hcmus.edu.vn/wp-content/uploads/2024/03/QD-1028-QC-DRL-2020_20231.pdf
   - PDF trang 9 (số trang in 8): Mục 1.1.
   - PDF trang 10 (số trang in 9): Mục 2.2.
   - PDF trang 11 (số trang in 10): Mục 4.3.
2. Sổ tay sinh viên HCMUS cập nhật quy chế theo Thông tư 40/2026/TT-BGDĐT: https://stsv.hcmus.edu.vn/quy-che-diem-ren-luyen
3. Tổng quan các nhóm điểm: https://stsv.hcmus.edu.vn/he-thong-diem-ren-luyen

## Các điểm đã chỉnh trong bản tích hợp

| ID | Đối chiếu từ nguồn | Quyết định kỹ thuật | Test |
|---|---|---|---|
| R11 | QĐ1028 mục 1.1 ghi **+10** khi không vi phạm học vụ, khảo thí | Sửa 15 thành 10 trên nhánh tích hợp, cập nhật TC01/TC10, fixture, test SP2 | 10 test cases kiểm tra lại |
| R22 | QĐ1028 mục 2.2 ghi **+5** cho đánh giá hơn 50% số môn đã đăng ký | Giữ điều kiện liên quan đến đánh giá học phần | kiểm thử riêng |
| R23 | Mục 2.2 không liệt kê thêm một khoản thưởng độc lập cho khảo sát xã hội | Đặt `status=needs_review`, bỏ điều kiện trùng R22; engine bỏ qua quy tắc chưa xác minh | không tự cộng |
| R4302 | Mục 4.3 ghi **24 giờ đến dưới một tuần** là +10 | Dùng `volunteer_duration_bucket="24_hours_to_under_one_week"`, phải do người kiểm tra hồ sơ xác định; không suy đoán 1 tuần = 168 giờ lao động | test nhóm thời lượng |

Các thay đổi chỉ nằm trên nhánh `integration/lead-sp1-sp2-20261027`, **không sửa nhánh Ngoc_Tuyen**. Với R23, nội dung quy định chưa được xác nhận là mục thưởng độc lập; chỉ người đối chiếu văn bản có thẩm quyền mới được bật lại. 

## Cảnh báo về phạm vi thời gian

Sổ tay mới của HCMUS dẫn Thông tư 40/2026 và khung năm 2026 có các trần tiêu chí khác 1028 (như trách nhiệm chấp hành pháp luật/nội quy 25, tinh thần học tập 20). Do chưa có văn bản xác nhận cách HCMUS chuyển tiếp từng học kỳ trong phần dữ liệu nhóm, **không dùng điểm tính theo ma trận QĐ1028 để khẳng định điểm ĐRL chính thức HK 2026–2027**.

Các API gắn `DEMO_ONLY` và `official_award_verified=false`. Khi có văn bản trường xác định cụ thể hiệu lực, cần tạo phiên bản rules mới có `effective_from`, `effective_to`, đối tượng áp dụng và test tương ứng, không ghi đè dữ liệu lịch sử.

## Kiểm tra còn mở

- Xác định văn bản/cập nhật nội bộ về điểm R23 và hiệu lực hiện hành.
- Gắn tiêu chí cho hoạt động chỉ khi người duyệt đã đối chiếu điều kiện tham gia và nguồn.
- Cấp quyền xét duyệt và minh chứng từ hệ thống trường nếu tiến tới bản vận hành chính thức.
