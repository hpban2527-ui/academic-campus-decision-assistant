# DRL Sources – Nguồn quy chế điểm rèn luyện

## 1. Văn bản nguồn

- **Tên văn bản:** Quy chế Đánh giá kết quả rèn luyện sinh viên hệ chính quy 
- **Số quyết định:** 1028/QĐ-KHTN-CTSV.
- **Ngày ban hành:** 04/09/2020 (có sửa đổi/bổ sung vào 12/12/2023)
- **Đơn vị ban hành:** Trường Đại học Khoa học Tự nhiên, ĐHQG-HCM.
- **Tệp nguồn:** https://hcmus.edu.vn/wp-content/uploads/2024/03/QD-1028-QC-DRL-2020_20231.pdf 
- **Link văn bản gốc:** https://hcmus.edu.vn/quy-che-danh-gia-ket-qua-ren-luyen-sinh-vien-he-chinh-quy/
- **Phạm vi áp dụng:**  sinh viên đang trong thời gian đào tạo Đại học, Cao đẳng hệ chính quy tại Trường Đại học Khoa học tự nhiên, ĐHQG-HCM.

## 2. Vị trí tra cứu

Đã tóm tắt vào link: https://docs.google.com/spreadsheets/d/1XVZt8lrpBiSeGojb3bSWql5XKXuK6K3YFKKQVoXPaH8/edit?gid=0#gid=0 

## 3. Trạng thái xác minh
Tất cả đã đối chiếu/ xác minh với các điều khoản/ phụ lục tương ứng ("status": "verified")

### Bổ sung ngày 14/11/2026: tiêu chí 2.3 (khảo sát)

- `R2301` (tiêu chí 2.3, +5 điểm mỗi đợt khảo sát/lấy ý kiến/điều tra xã hội) lấy từ **Sổ tay Sinh viên 2025 (STSV2025)**, theo bảng chú giải tiêu chí trong `docs/Data_Report.md` (Minh Trí, 12/11/2026). Người phụ trách SP2 (Thảo Duyên) chấp nhận ngày 14/11/2026. **Còn thiếu số trang trong sổ tay**: cần bổ sung trước khi nộp báo cáo.
- `R23` (phụ lục QĐ 1028, mục 2.2) giữ `needs_review` vì phụ lục không có dòng cộng điểm riêng cho khảo sát. Hai tài liệu khác nhau, nên chỉ `R2301` mang điểm khảo sát; không bật đồng thời `R23` và `R2301`.
- Mục bắt buộc liên quan: `R61` (không tham gia hoặc khai sai khảo sát, −5) vẫn giữ nguyên.

## 4. Lưu ý khi chuyển quy chế thành dữ liệu

- Các trường `field`, `rule_id` và cấu trúc JSON là quy ước do nhóm thiết kế, không phải tên trường nguyên văn trong quyết định.
- Điểm được thông báo cho một hoạt động không mặc nhiên đồng nghĩa với điểm rèn luyện đã được xác nhận.
- Khi chưa đủ dữ liệu hoặc minh chứng, hệ thống cần đánh dấu cần xem xét thay vì tự suy đoán.
