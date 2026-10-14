LINK: https://docs.google.com/spreadsheets/d/16WElV1oN1HwGfLPK82Tsxed0mFSLlZPpMxZMm44r118/edit?gid=0#gid=0 

# Data Provenance:
- Nguồn: Moodle/ Chương trình đào tạo của ngành CNTT khóa 2025 (https://www.ctda.hcmus.edu.vn/wp-content/uploads/2026/01/CTDT_TCTA_Khoa-2025.pdf)

- Phạm vi: 16 môn học đại diện thuộc các khối kiến thức Đại cương, Cơ sở ngành và Chuyên ngành Công nghệ thông tin (Năm 1 & Năm 2).

# Đề xuất Schema cơ bản: 
Dữ liệu được lưu trữ dưới định dạng .csv (đã đính kèm file courses.csv) với cấu trúc các cột phục vụ cho việc dựng Đồ thị tiên quyết (DAG) và kiểm tra lịch trình:
- `course_id`: Mã môn học 
- `course_name`: Tên đầy đủ của môn học
- `credits`: Số tín chỉ của môn
- `timetable`: Lịch học lý thuyết (Bao gồm thứ, khung giờ, phòng học)
- `lab_timetable`: Lịch học thực hành (Tách riêng biệt để tránh xung đột)

# Data Assessment: 
1. Reliability & Provenance: 
   - Đánh giá: Cao. Dữ liệu lấy từ các nguồn chính thống của trường, đảm bảo chính xác mã môn, tên môn và số tín chỉ theo chương trình đào tạo thực tế.
   - Hạn chế: Lịch học (`timetable` và `lab_timetable`) mang tính chất mẫu theo một lớp học phần cố định (25C09) để làm khung thử nghiệm hệ thống.

2. Completeness:  
   - Đánh giá: Đạt yêu cầu cho MVP (Minimum Viable Product). Bộ 16 môn mẫu gom đủ kiến thức nền tảng từ năm 1 đến năm 2 (đã trừ 2 HP TD1 & GDQP-AN), hoàn toàn đủ dữ liệu để nhóm chạy thử nghiệm thuật toán tìm đường găng (Critical Path) và kiểm tra trùng lịch.

3. Format Compatibility: 
   - Đánh giá: Định dạng CSV phẳng giúp việc tích hợp vào mã nguồn Python trở nên tối ưu và nhẹ nhàng, không đòi hỏi quá trình phân tích cú pháp phức tạp như các định dạng lồng nhau.