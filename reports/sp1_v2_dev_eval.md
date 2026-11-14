# SP1 v2 development evaluation

These are development results on small samples. Held-out test evaluation remains pending.

## Gold v1 (16 posts)

| Method | Field | n | Correct | Wrong | Fabricated | Missed | Accuracy | 95% Wilson |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| v1 | title | 16 | 7 | 9 | 0 | 0 | 43.8% | 23.1%–66.8% |
| v1 | window_open | 16 | 10 | 2 | 2 | 2 | 62.5% | 38.6%–81.5% |
| v1 | window_close | 16 | 11 | 0 | 3 | 2 | 68.8% | 44.4%–85.8% |
| v1 | registration_deadline | 16 | 9 | 0 | 0 | 7 | 56.2% | 33.2%–76.9% |
| v1 | mode | 16 | 10 | 1 | 0 | 5 | 62.5% | 38.6%–81.5% |
| v1 | location | 16 | 11 | 1 | 0 | 4 | 68.8% | 44.4%–85.8% |
| v1 | fee | 16 | 15 | 0 | 0 | 1 | 93.8% | 71.7%–98.9% |
| v1 | registration_url | 16 | 13 | 0 | 2 | 1 | 81.2% | 57.0%–93.4% |
| v1 | mandatory_stated | 16 | 16 | 0 | 0 | 0 | 100.0% | 80.6%–100.0% |
| v1 | domain | 16 | 8 | 4 | 0 | 4 | 50.0% | 28.0%–72.0% |
| v1 | TOTAL | 160 | 110 | 17 | 7 | 26 | 68.8% | 61.2%–75.4% |
| v2 | title | 16 | 9 | 7 | 0 | 0 | 56.2% | 33.2%–76.9% |
| v2 | window_open | 16 | 13 | 2 | 1 | 0 | 81.2% | 57.0%–93.4% |
| v2 | window_close | 16 | 15 | 0 | 0 | 1 | 93.8% | 71.7%–98.9% |
| v2 | registration_deadline | 16 | 15 | 0 | 0 | 1 | 93.8% | 71.7%–98.9% |
| v2 | mode | 16 | 12 | 1 | 0 | 3 | 75.0% | 50.5%–89.8% |
| v2 | location | 16 | 11 | 1 | 0 | 4 | 68.8% | 44.4%–85.8% |
| v2 | fee | 16 | 15 | 0 | 0 | 1 | 93.8% | 71.7%–98.9% |
| v2 | registration_url | 16 | 13 | 0 | 2 | 1 | 81.2% | 57.0%–93.4% |
| v2 | mandatory_stated | 16 | 16 | 0 | 0 | 0 | 100.0% | 80.6%–100.0% |
| v2 | domain | 16 | 8 | 4 | 0 | 4 | 50.0% | 28.0%–72.0% |
| v2 | TOTAL | 160 | 127 | 15 | 3 | 15 | 79.4% | 72.5%–84.9% |

| Position | Method | Field | Outcome | Predicted | Gold |
| ---: | --- | --- | --- | --- | --- |
| 1 | v1 | registration_deadline | missed | null | "2026-10-28T23:59:00+07:00" |
| 1 | v1 | domain | wrong | "career" | "skills" |
| 1 | v2 | domain | wrong | "career" | "skills" |
| 2 | v1 | title | wrong | "LET IT SHINE 2026" | "LET IT SHINE 2026 - KHÚC KHẢI HOÀN MÙA ĐÔNG" |
| 2 | v1 | location | wrong | "cơ sở phường Chợ Quán" | "Vòng Sơ khảo: cơ sở phường Chợ Quán; Vòng Chung kết: Giảng đường 1, cơ sở phườn |
| 2 | v1 | domain | missed | null | "culture_sports" |
| 2 | v2 | title | wrong | "LET IT SHINE 2026" | "LET IT SHINE 2026 - KHÚC KHẢI HOÀN MÙA ĐÔNG" |
| 2 | v2 | window_close | missed | null | "2026-11-22T20:30:00+07:00" |
| 2 | v2 | location | wrong | "cơ sở phường Chợ Quán" | "Vòng Sơ khảo: cơ sở phường Chợ Quán; Vòng Chung kết: Giảng đường 1, cơ sở phườn |
| 2 | v2 | domain | missed | null | "culture_sports" |
| 3 | v1 | window_open | fabricated | "2025-09-09T00:00:00+07:00" | null |
| 3 | v1 | window_close | fabricated | "2026-09-04T23:59:00+07:00" | null |
| 3 | v1 | domain | missed | null | "other" |
| 3 | v2 | window_open | fabricated | "2026-05-25" | null |
| 3 | v2 | domain | missed | null | "other" |
| 4 | v1 | title | wrong | "HỖ TRỢ TRUYỀN THÔNG" | "Avalanche Team1 UniHack HCMC 2026" |
| 4 | v1 | mode | wrong | "online" | "hybrid" |
| 4 | v1 | location | missed | null | "Online; Vòng Pitching trực tiếp tại TP.HCM" |
| 4 | v2 | title | wrong | "Thực hiện nhiệm vụ thúc đẩy hệ sinh thái đổi mới sáng tạo, chuyển đổi số và nân | "Avalanche Team1 UniHack HCMC 2026" |
| 4 | v2 | mode | wrong | "online" | "hybrid" |
| 4 | v2 | location | missed | null | "Online; Vòng Pitching trực tiếp tại TP.HCM" |
| 5 | v1 | window_open | fabricated | "2026-09-24T00:00:00+07:00" | null |
| 5 | v1 | window_close | fabricated | "2026-10-26T23:59:00+07:00" | null |
| 5 | v1 | registration_url | fabricated | "https://datastudio.google.com/.../e586d666.../page/cRFBG" | null |
| 5 | v1 | domain | missed | null | "other" |
| 5 | v2 | registration_url | fabricated | "https://datastudio.google.com/.../e586d666.../page/cRFBG" | null |
| 5 | v2 | domain | missed | null | "other" |
| 6 | v1 | domain | wrong | "skills" | "other" |
| 6 | v2 | title | wrong | "KHTN ZERO+ 2026 \| SINH VIÊN KHTN ƠI, CÙNG THAM GIA THI TRỰC TUYẾN" | "KHTN ZERO+ 2026 \| SINH VIÊN KHTN ƠI, CÙNG THAM GIA THI TRỰC TUYẾN!" |
| 6 | v2 | domain | wrong | "skills" | "other" |
| 7 | v1 | title | wrong | "THÔNG BÁO Chuyên đề “Sinh viên với kỹ năng tham gia giao thông và đảm bảo trật  | "Chuyên đề \"Sinh viên với kỹ năng tham gia giao thông và đảm bảo trật tự, an to |
| 7 | v2 | title | wrong | "THÔNG BÁO Chuyên đề “Sinh viên với kỹ năng tham gia giao thông và đảm bảo trật  | "Chuyên đề \"Sinh viên với kỹ năng tham gia giao thông và đảm bảo trật tự, an to |
| 8 | v1 | title | wrong | "Ánh trăng rằm tháng Tám không chỉ mang theo hương vị ngọt ngào của bánh nướng,  | "VƯƠN BƯỚC ĐÊM RẰM - MỞ ĐƠN ĐĂNG KÝ" |
| 8 | v1 | registration_deadline | missed | null | "2026-09-24T23:59:00+07:00" |
| 8 | v1 | mode | missed | null | "offline" |
| 9 | v1 | registration_deadline | missed | null | "2026-05-12T20:00:00+07:00" |
| 9 | v1 | mode | missed | null | "offline" |
| 10 | v1 | title | wrong | "Tháng tư lại về … Xuân chưa nỡ rời xa" | "HẠT NẮNG ĐÊM - MỞ FORM" |
| 10 | v1 | window_open | missed | null | "2026-04-12T15:00:00+07:00" |
| 10 | v1 | window_close | missed | null | "2026-04-12T21:00:00+07:00" |
| 10 | v1 | registration_deadline | missed | null | "2026-04-10T23:00:00+07:00" |
| 10 | v1 | mode | missed | null | "offline" |
| 10 | v1 | location | missed | null | "Địa điểm phát: Các tuyến đường tại Quận 10; Địa điểm nấu: 14/1 Ngô Quyền, Phườn |
| 10 | v2 | mode | missed | null | "offline" |
| 10 | v2 | location | missed | null | "Địa điểm phát: Các tuyến đường tại Quận 10; Địa điểm nấu: 14/1 Ngô Quyền, Phườn |
| 11 | v1 | title | wrong | "FIT SUPER LEAGUE 2026" | "FIT SUPER LEAGUE 2026 - CHÍNH THỨC MỞ ĐƠN" |
| 11 | v1 | registration_deadline | missed | null | "2026-03-08T23:59:00+07:00" |
| 11 | v1 | mode | missed | null | "offline" |
| 11 | v1 | location | missed | null | "Sân bóng đá Phạm Hùng, Hẻm C7D/17e24, Đ. Phạm Hùng, Bình Hưng, Bình Chánh, TP H |
| 11 | v1 | fee | missed | null | 500000 |
| 11 | v1 | domain | wrong | "skills" | "culture_sports" |
| 11 | v2 | title | wrong | "FIT SUPER LEAGUE 2026" | "FIT SUPER LEAGUE 2026 - CHÍNH THỨC MỞ ĐƠN" |
| 11 | v2 | registration_deadline | missed | null | "2026-03-08T23:59:00+07:00" |
| 11 | v2 | mode | missed | null | "offline" |
| 11 | v2 | location | missed | null | "Sân bóng đá Phạm Hùng, Hẻm C7D/17e24, Đ. Phạm Hùng, Bình Hưng, Bình Chánh, TP H |
| 11 | v2 | fee | missed | null | 500000 |
| 11 | v2 | domain | wrong | "skills" | "culture_sports" |
| 12 | v1 | window_open | wrong | "2026-10-11T00:00:00+07:00" | "2026-10-11T12:00:00+07:00" |
| 12 | v2 | window_open | wrong | "2026-10-11" | "2026-10-11T12:00:00+07:00" |
| 13 | v1 | window_open | wrong | "2026-10-04T23:59:00+07:00" | "2026-10-25T07:30:00+07:00" |
| 13 | v1 | window_close | fabricated | "2026-10-25T07:30:00+07:00" | null |
| 13 | v1 | registration_deadline | missed | null | "2026-10-04T23:59:00+07:00" |
| 13 | v1 | mode | missed | null | "offline" |
| 13 | v1 | location | missed | null | "Một trong hai cơ sở của Trường Đại học Khoa học tự nhiên, ĐHQG-HCM (thí sinh đư |
| 13 | v2 | window_open | wrong | "2026-10-08" | "2026-10-25T07:30:00+07:00" |
| 13 | v2 | mode | missed | null | "offline" |
| 13 | v2 | location | missed | null | "Một trong hai cơ sở của Trường Đại học Khoa học tự nhiên, ĐHQG-HCM (thí sinh đư |
| 14 | v1 | title | wrong | "- “+1 MÁY” LÊN KÈO, VÈO VÈO CHẠY TRẠM" | "[ITogether] - \"+1 MÁY\" LÊN KÈO, VÈO VÈO CHẠY TRẠM" |
| 14 | v1 | domain | wrong | "volunteer" | "skills" |
| 14 | v2 | title | wrong | "[ITogether]  - “+1 MÁY” LÊN KÈO, VÈO VÈO CHẠY TRẠM" | "[ITogether] - \"+1 MÁY\" LÊN KÈO, VÈO VÈO CHẠY TRẠM" |
| 14 | v2 | domain | wrong | "volunteer" | "skills" |
| 15 | v1 | title | wrong | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN “THEO DẤU CHÂN NGƯỜI”" | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN \"THEO DẤU CHÂN NGƯỜI\"" |
| 15 | v1 | window_open | missed | null | "2026-06-05T20:00:00+07:00" |
| 15 | v1 | window_close | missed | null | "2026-06-12T23:59:00+07:00" |
| 15 | v1 | registration_url | fabricated | "https://bit.ly/TheoDauChanNguoi2026" | null |
| 15 | v1 | domain | missed | null | "other" |
| 15 | v2 | title | wrong | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN “THEO DẤU CHÂN NGƯỜI" | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN \"THEO DẤU CHÂN NGƯỜI\"" |
| 15 | v2 | registration_url | fabricated | "bit.ly/TheoDauChanNguoi2026" | null |
| 15 | v2 | domain | missed | null | "other" |
| 16 | v1 | title | wrong | "- MỞ FORM ĐĂNG KÝ" | "[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ" |
| 16 | v1 | registration_deadline | missed | null | "2026-09-25T23:59:00+07:00" |
| 16 | v1 | registration_url | missed | null | "https://bit.ly/BLIT2026_DangKy" |
| 16 | v2 | registration_url | missed | null | "https://bit.ly/BLIT2026_DangKy" |

## Gold v2 (5 posts)

| Method | Field | n | Correct | Wrong | Fabricated | Missed | Accuracy | 95% Wilson |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| v2 | post_type | 5 | 4 | 1 | 0 | 0 | 80.0% | 37.6%–96.4% |
| v2 | title | 5 | 4 | 1 | 0 | 0 | 80.0% | 37.6%–96.4% |
| v2 | domain | 5 | 3 | 0 | 0 | 2 | 60.0% | 23.1%–88.2% |
| v2 | multi_session | 5 | 4 | 0 | 0 | 1 | 80.0% | 37.6%–96.4% |
| v2 | window_open | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | window_close | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | duration_minutes_stated | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | registration_deadline | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | mode | 5 | 2 | 1 | 1 | 1 | 40.0% | 11.8%–76.9% |
| v2 | location | 5 | 4 | 0 | 0 | 1 | 80.0% | 37.6%–96.4% |
| v2 | audience_text | 5 | 2 | 1 | 1 | 1 | 40.0% | 11.8%–76.9% |
| v2 | audience_scope | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | mandatory_stated | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | recognition_stated | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | points_stated | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | fee | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | registration_url | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | join_url | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | completion_requirements | 5 | 5 | 0 | 0 | 0 | 100.0% | 56.6%–100.0% |
| v2 | TOTAL | 95 | 83 | 4 | 2 | 6 | 87.4% | 79.2%–92.6% |

| Position | Method | Field | Outcome | Predicted | Gold |
| ---: | --- | --- | --- | --- | --- |
| 26 | v2 | title | wrong | "[HTTN26] - HÈ RỒI, CÙNG NHAU KHÁM PHÁ VĂN HÓA NƯỚC BẠN THÔI" | "[HTTN26] - HÈ RỒI, CÙNG NHAU KHÁM PHÁ VĂN HÓA NƯỚC BẠN THÔI!" |
| 26 | v2 | audience_text | fabricated | "sinh viên Trường Đại học Khoa học tự nhiên, ĐHQG-HCM." | null |
| 28 | v2 | domain | missed | null | "academic" |
| 28 | v2 | mode | fabricated | "offline" | null |
| 28 | v2 | audience_text | wrong | "Sinh viên ngành Công nghệ thông tin, Khoa học máy tính hoặc các bạn quan tâm đế | "Sinh viên ngành Công nghệ thông tin, Khoa học máy tính hoặc các bạn quan tâm đế |
| 36 | v2 | post_type | wrong | "insufficient" | "info_only" |
| 36 | v2 | domain | missed | null | "volunteer" |
| 48 | v2 | mode | missed | null | "offline" |
| 48 | v2 | location | missed | null | " Trường Đại học Khoa học tự nhiên, ĐHQG-HCM " |
| 54 | v2 | multi_session | missed | null | true |
| 54 | v2 | mode | wrong | "offline" | "online" |
| 54 | v2 | audience_text | missed | null | "Bảng A: Dành cho học sinh THCS hoặc độ tuổi tương đương; thi theo đội, mỗi đội  |

