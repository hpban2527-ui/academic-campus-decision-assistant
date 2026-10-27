# Báo cáo kiểm thử Lead & Integration — 27/10/2026

Nhánh: `integration/lead-sp1-sp2-20261027`  
PR: https://github.com/hpban2527-ui/academic-campus-decision-assistant/pull/3  
Workflow đã kiểm tra: https://github.com/hpban2527-ui/academic-campus-decision-assistant/actions/runs/40459619331

## Kết quả GitHub Actions

| Job | Kết quả | Chi tiết |
| --- | --- | --- |
| Backend SP1/SP2/Lead | PASS | **269 passed, 1 warning** |
| Kiểm tra 10 ca quy tắc | PASS | **10/10 cases** |
| Frontend/API compatibility | PASS | **14 passed, 1 warning** |
| Compile Python | PASS | `python -m compileall -q src tests scripts run_server.py` |

Log test chạy trên GitHub Actions (Python 3.12), không phải tự đánh dấu PASS trong README.

## Phạm vi test tích hợp

- Input của Trí → extractor Duyên không vướng `share_url`.
- Draft 15 trường → candidate công bố đúng 14 trường; quy ước `mandatory=false`, `fee=0` và lưu lý do.
- Trích xuất P08 có ngày từ thông báo cũ bị cờ review; link đăng ký dạng placeholder không được coi là đường dẫn đủ tin cậy.
- Hoạt động chỉ được tính trong pipeline khi có **bản duyệt phù hợp**; bản duyệt ràng buộc fingerprint nội dung + URL nguồn + rule.
- Điểm dự kiến, điểm xác nhận mô phỏng, category cap, chống cộng trùng, baseline theo từng sinh viên, từ chối dữ liệu bị sửa sau duyệt.
- R11 dùng 10 điểm theo phụ lục gốc; R23 không được tự cộng; R4302 không quy đổi một tuần tùy ý.
- Audit nhóm bài đăng giống/trùng: giữ mọi nguồn để người kiểm tra xác nhận.
- API không tự cấp điểm chính thức bằng checkbox hoặc rule_override.

## Điều kiện chưa có và quyết định

**Backend demo: đạt các test đã khai báo.**  
**Chưa coi là nghiệm thu sản phẩm vận hành chính thức**, vì:
1. Điểm từ bộ QĐ1028 chỉ đang mô phỏng; khung HCMUS năm 2026 cần xác nhận hiệu lực theo học kỳ.
2. Bản duyệt mẫu và minh chứng trong `/api/pipeline/demo` là **synthetic fixture**; chưa kết nối tài khoản xét duyệt hoặc dữ liệu minh chứng từ nhà trường.
3. Nhiều bài từ dataset thực vẫn cần người kiểm tra (đặc biệt nguồn đăng chéo, ngày, URL đăng ký và điều kiện hoàn thành).
4. Tiến là owner giao diện, cần review bản tích hợp và nghiệm thu demo chung. PR vẫn Draft, chưa có approval/merge.

**Trạng thái cuối:** sẵn sàng cho nhóm review backend và demo kiểm thử; **chưa merge vào `main`**.
