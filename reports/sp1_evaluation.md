# SP1 extraction evaluation

Posts scored: 20 (gold posts missing from the posts file: 0; posts without gold: 0)
Posts with more than one gold activity: 0; with more than one predicted draft: 0 (only the first of each is compared)

| field | n | correct | wrong | fabricated | missed | accuracy | 95% Wilson CI |
|---|---|---|---|---|---|---|---|
| URL_registration | 20 | 16 | 0 | 2 | 2 | 0.80 | 0.58–0.92 |
| title | 20 | 7 | 13 | 0 | 0 | 0.35 | 0.18–0.57 |
| domain | 20 | 10 | 4 | 0 | 6 | 0.50 | 0.30–0.70 |
| start | 20 | 13 | 2 | 2 | 3 | 0.65 | 0.43–0.82 |
| end | 20 | 14 | 0 | 3 | 3 | 0.70 | 0.48–0.85 |
| registration_deadline | 20 | 10 | 0 | 0 | 10 | 0.50 | 0.30–0.70 |
| mode | 20 | 13 | 1 | 0 | 6 | 0.65 | 0.43–0.82 |
| location | 20 | 14 | 1 | 0 | 5 | 0.70 | 0.48–0.85 |
| points | 20 | 20 | 0 | 0 | 0 | 1.00 | 0.84–1.00 |
| drl_recognized | 0 | 0 | 0 | 0 | 0 | n/a | n/a |
| mandatory | 20 | 20 | 0 | 0 | 0 | 1.00 | 0.84–1.00 |
| audience | 20 | 10 | 2 | 2 | 6 | 0.50 | 0.30–0.70 |
| fee | 20 | 19 | 0 | 0 | 1 | 0.95 | 0.76–0.99 |
| completion_requirements | 20 | 18 | 2 | 0 | 0 | 0.90 | 0.70–0.97 |

## Draft status (first draft per post)

| status | posts |
|---|---|
| failed | 3 |
| partial | 10 |
| valid | 7 |

## Wrong, fabricated and missed values

| post_id | field | outcome | predicted | gold |
|---|---|---|---|---|
| pfbid02buJY8Rrn2XezSWbCNxpUnfSHX4yDYWi5EgXbngmL1FKiEE47XQarhqVqb4WjERECl | domain | wrong | "career" | "skills" |
| pfbid02buJY8Rrn2XezSWbCNxpUnfSHX4yDYWi5EgXbngmL1FKiEE47XQarhqVqb4WjERECl | registration_deadline | missed | null | "2026-10-28T23:59:00+07:00" |
| pfbid02EJmkk2oaZJuBw5VqRhEUeSUNqVW6dav9qSV4AZsK661vLikur7U4PPBqJcPDBYHzl | title | wrong | "- KEY ƠI, ĐỪNG QUÊN CÓ HẸN VỚI VÒNG 4 - ALT!" | "[BẢN LĨNH IT 2026] - KEY ƠI, ĐỪNG QUÊN CÓ HẸN VỚI VÒNG 4 - ALT!" |
| pfbid02EJmkk2oaZJuBw5VqRhEUeSUNqVW6dav9qSV4AZsK661vLikur7U4PPBqJcPDBYHzl | domain | missed | null | "skills" |
| pfbid02EJmkk2oaZJuBw5VqRhEUeSUNqVW6dav9qSV4AZsK661vLikur7U4PPBqJcPDBYHzl | mode | missed | null | "offline" |
| pfbid02EJmkk2oaZJuBw5VqRhEUeSUNqVW6dav9qSV4AZsK661vLikur7U4PPBqJcPDBYHzl | location | missed | null | "Vườn điều, Cơ sở phường Đông Hòa, Trường Đại học Khoa học tự nhiên, ĐHQG-HCM" |
| pfbid0ouxPwhrPNLVJkqySBkTXowuqDC2wkabJwYYuqsGe2qVP3o836nNvFAHHTMW7KJv5l | title | wrong | "LET IT SHINE 2026" | "LET IT SHINE 2026 - KHÚC KHẢI HOÀN MÙA ĐÔNG" |
| pfbid0ouxPwhrPNLVJkqySBkTXowuqDC2wkabJwYYuqsGe2qVP3o836nNvFAHHTMW7KJv5l | domain | missed | null | "culture_sports" |
| pfbid0ouxPwhrPNLVJkqySBkTXowuqDC2wkabJwYYuqsGe2qVP3o836nNvFAHHTMW7KJv5l | location | wrong | "cơ sở phường Chợ Quán" | "Vòng Sơ khảo: cơ sở phường Chợ Quán; Vòng Chung kết: Giảng đường 1, cơ sở phường Chợ Quán" |
| pfbid0dmRU1XavPQ3rzXsGMSTaL69GEcdsmKnXeVaWA4LYybFFgsJDfg3qtMetBGfn7zKkl | title | wrong | "Nhà G có gì hot? TIPS & Tricks đã trở lại với những nội dung bất bại rồi đây!" | "[GDGoC-HCMUS TIPS & TRICKS]" |
| pfbid0dmRU1XavPQ3rzXsGMSTaL69GEcdsmKnXeVaWA4LYybFFgsJDfg3qtMetBGfn7zKkl | start | missed | null | "2026-10-03T00:00:00+07:00" |
| pfbid0dmRU1XavPQ3rzXsGMSTaL69GEcdsmKnXeVaWA4LYybFFgsJDfg3qtMetBGfn7zKkl | end | missed | null | "2026-10-25T23:59:00+07:00" |
| pfbid0dmRU1XavPQ3rzXsGMSTaL69GEcdsmKnXeVaWA4LYybFFgsJDfg3qtMetBGfn7zKkl | registration_deadline | missed | null | "2026-10-10T23:59:00+07:00" |
| pfbid0dmRU1XavPQ3rzXsGMSTaL69GEcdsmKnXeVaWA4LYybFFgsJDfg3qtMetBGfn7zKkl | audience | wrong | ["TẤT CẢ SINH VIÊN của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, và đặc biệt còn cả những bạn sinh viên trong TP.HCM nữa nha!"] | ["Tất cả sinh viên của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, và sinh viên trong TP.HCM"] |
| pfbid02o8CK5Ziex6z2ZjnEhnv49RyHkZwMxEcLkpF49QmVymQp3N2hghbSAcrvzFram89Pl | title | wrong | "Mỗi mảnh ghép đều mang một màu sắc và dấu ấn riêng, cùng nhau tạo nên bức tranh đầy sắc màu của GDGoC-HCMUS. Và để viết tiếp hành trình ấy, nhà G đang tìm kiếm những mảnh ghép mới. Biết đâu, bạn chính là mảnh ghép tiếp theo mà chúng mình đang chờ đợi?" | "[GDGoC-HCMUS RECRUITMENT 2026]" |
| pfbid02o8CK5Ziex6z2ZjnEhnv49RyHkZwMxEcLkpF49QmVymQp3N2hghbSAcrvzFram89Pl | domain | missed | null | "career" |
| pfbid02o8CK5Ziex6z2ZjnEhnv49RyHkZwMxEcLkpF49QmVymQp3N2hghbSAcrvzFram89Pl | registration_deadline | missed | null | "2026-10-10T23:59:00+07:00" |
| pfbid02o8CK5Ziex6z2ZjnEhnv49RyHkZwMxEcLkpF49QmVymQp3N2hghbSAcrvzFram89Pl | audience | wrong | ["TẤT CẢ SINH VIÊN của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, và đặc biệt còn cả những bạn sinh viên trong TP.HCM nữa nha!"] | ["Tất cả sinh viên của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, và sinh viên trong TP.HCM"] |
| pfbid02kVX7vEbj6FuQSGiHs7NqQMz9CszBXfbmt9RjRcpJfU17z7CnhkjUVEee7vVirgnWl | domain | missed | null | "other" |
| pfbid02kVX7vEbj6FuQSGiHs7NqQMz9CszBXfbmt9RjRcpJfU17z7CnhkjUVEee7vVirgnWl | start | fabricated | "2025-09-09T00:00:00+07:00" | null |
| pfbid02kVX7vEbj6FuQSGiHs7NqQMz9CszBXfbmt9RjRcpJfU17z7CnhkjUVEee7vVirgnWl | end | fabricated | "2026-09-04T23:59:00+07:00" | null |
| pfbid0p8jUJBWv9dCfTj4L9hr7QD8CycCVugW71gPzrRh4BgpB6WWCZWA5urLB783sTwc4l | title | wrong | "HỖ TRỢ TRUYỀN THÔNG" | "Avalanche Team1 UniHack HCMC 2026" |
| pfbid0p8jUJBWv9dCfTj4L9hr7QD8CycCVugW71gPzrRh4BgpB6WWCZWA5urLB783sTwc4l | mode | wrong | "online" | "hybrid" |
| pfbid0p8jUJBWv9dCfTj4L9hr7QD8CycCVugW71gPzrRh4BgpB6WWCZWA5urLB783sTwc4l | location | missed | null | "Online; Vòng Pitching trực tiếp tại TP.HCM" |
| pfbid0p8jUJBWv9dCfTj4L9hr7QD8CycCVugW71gPzrRh4BgpB6WWCZWA5urLB783sTwc4l | audience | missed | null | ["Sinh viên trên toàn quốc"] |
| pfbid02fsjfr4MEtTjN9TpVw3DvfWumQm7Wx2GGE56n7J51Y8sh4brg3p4k1uwhX41h26FFl | URL_registration | fabricated | "https://datastudio.google.com/.../e586d666.../page/cRFBG" | null |
| pfbid02fsjfr4MEtTjN9TpVw3DvfWumQm7Wx2GGE56n7J51Y8sh4brg3p4k1uwhX41h26FFl | domain | missed | null | "other" |
| pfbid02fsjfr4MEtTjN9TpVw3DvfWumQm7Wx2GGE56n7J51Y8sh4brg3p4k1uwhX41h26FFl | start | fabricated | "2026-09-24T00:00:00+07:00" | null |
| pfbid02fsjfr4MEtTjN9TpVw3DvfWumQm7Wx2GGE56n7J51Y8sh4brg3p4k1uwhX41h26FFl | end | fabricated | "2026-10-26T23:59:00+07:00" | null |
| pfbid0DeYsfZBiuFn3oyYi6JE2vjfzPWHirxKMfBAzUk284M4guunLjVQxPTs8oodLfWiJl | domain | wrong | "skills" | "other" |
| pfbid0DeYsfZBiuFn3oyYi6JE2vjfzPWHirxKMfBAzUk284M4guunLjVQxPTs8oodLfWiJl | audience | missed | null | ["Toàn thể sinh viên Trường Đại học Khoa học tự nhiên"] |
| pfbid0DeYsfZBiuFn3oyYi6JE2vjfzPWHirxKMfBAzUk284M4guunLjVQxPTs8oodLfWiJl | completion_requirements | wrong | "Sinh viên hoàn thành 70% bài thi: được ghi nhận tham gia hoạt động tại học kỳ 1/2026-2027" | "Hoàn thành 70% bài thi" |
| pfbid033dzDjjDUpdog6s9h3NWATwuoNp5UumRmNNYnZVyKMxFzyLktCc6xsxstaZP4fPjLl | title | wrong | "THÔNG BÁO Chuyên đề “Sinh viên với kỹ năng tham gia giao thông và đảm bảo trật tự, an toàn giao thông đường bộ”" | "Chuyên đề \"Sinh viên với kỹ năng tham gia giao thông và đảm bảo trật tự, an toàn giao thông đường bộ\"" |
| pfbid0yi4qHyyzkSe4NWeBqXBMo5aifh7TaV4rEj4ZcYvhKM5DmdA8K6z9G1FUCt5TC7mzl | title | wrong | "Ánh trăng rằm tháng Tám không chỉ mang theo hương vị ngọt ngào của bánh nướng, bánh dẻo mà còn thắp sáng những nụ cười và ước mơ trẻ thơ. Tuy vậy, không phải tuổi thơ nào cũng rực rỡ ánh lồng đèn, và trung thu trọn vẹn cũng không tự nhiên mà có. Các em đang chờ đợi một phép màu xảy đến, để đêm rằm tháng tám không còn chỉ là những ước mơ dang dở nữa." | "VƯƠN BƯỚC ĐÊM RẰM - MỞ ĐƠN ĐĂNG KÝ" |
| pfbid0yi4qHyyzkSe4NWeBqXBMo5aifh7TaV4rEj4ZcYvhKM5DmdA8K6z9G1FUCt5TC7mzl | registration_deadline | missed | null | "2026-09-24T23:59:00+07:00" |
| pfbid0yi4qHyyzkSe4NWeBqXBMo5aifh7TaV4rEj4ZcYvhKM5DmdA8K6z9G1FUCt5TC7mzl | mode | missed | null | "offline" |
| pfbid0yi4qHyyzkSe4NWeBqXBMo5aifh7TaV4rEj4ZcYvhKM5DmdA8K6z9G1FUCt5TC7mzl | audience | fabricated | ["40 sinh viên"] | null |
| pfbid02gENqCMzeMBYaWH3zsqfExUZ5coUdTv7jS37xfTeJijUPRfYs6utzCZGZ3H6o9mYQl | registration_deadline | missed | null | "2026-05-12T20:00:00+07:00" |
| pfbid02gENqCMzeMBYaWH3zsqfExUZ5coUdTv7jS37xfTeJijUPRfYs6utzCZGZ3H6o9mYQl | mode | missed | null | "offline" |
| pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl | title | wrong | "Tháng tư lại về … Xuân chưa nỡ rời xa" | "HẠT NẮNG ĐÊM - MỞ FORM" |
| pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl | start | missed | null | "2026-04-12T15:00:00+07:00" |
| pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl | end | missed | null | "2026-04-12T21:00:00+07:00" |
| pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl | registration_deadline | missed | null | "2026-04-10T23:00:00+07:00" |
| pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl | mode | missed | null | "offline" |
| pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl | location | missed | null | "Địa điểm phát: Các tuyến đường tại Quận 10; Địa điểm nấu: 14/1 Ngô Quyền, Phường 5, Quận 10, TP.HCM (Quán cơm từ thiện 2000 đ – SG)" |
| pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl | audience | fabricated | ["30 - 35 sinh viên"] | null |
| pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l | title | wrong | "FIT SUPER LEAGUE 2026" | "FIT SUPER LEAGUE 2026 - CHÍNH THỨC MỞ ĐƠN" |
| pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l | domain | wrong | "skills" | "culture_sports" |
| pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l | registration_deadline | missed | null | "2026-03-08T23:59:00+07:00" |
| pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l | mode | missed | null | "offline" |
| pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l | location | missed | null | "Sân bóng đá Phạm Hùng, Hẻm C7D/17e24, Đ. Phạm Hùng, Bình Hưng, Bình Chánh, TP Hồ Chí Minh" |
| pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l | audience | missed | null | ["Sinh viên khoa Công nghệ Thông tin"] |
| pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l | fee | missed | null | 500000 |
| pfbid026SJmz8cRXUkDwHvJrZyZv4bsikCC1t4pdDBt46gTuwxaTkBKtSHvCPvwJH1KJ47l | URL_registration | missed | null | "https://bit.ly/BLIT2026_DangKy" |
| pfbid026SJmz8cRXUkDwHvJrZyZv4bsikCC1t4pdDBt46gTuwxaTkBKtSHvCPvwJH1KJ47l | title | wrong | "- MỞ FORM ĐĂNG KÝ" | "[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ" |
| pfbid026SJmz8cRXUkDwHvJrZyZv4bsikCC1t4pdDBt46gTuwxaTkBKtSHvCPvwJH1KJ47l | registration_deadline | missed | null | "2026-09-24T23:59:00+07:00" |
| pfbid034Pftro7LAxEMRbiQpWNcxtzw7B8ji6B9DWEvMq6nvmbqHR6RP3fLymeJrd5WJytTl | start | wrong | "2026-10-11T00:00:00+07:00" | "2026-10-11T12:00:00+07:00" |
| pfbid0KfFuXSR1LyKtz1MQvsRR2civySNdRQuKrD8ouyX5gDcH5kGpZdYcwPpWNqVoqhQzl | start | wrong | "2026-10-04T23:59:00+07:00" | "2026-10-25T07:30:00+07:00" |
| pfbid0KfFuXSR1LyKtz1MQvsRR2civySNdRQuKrD8ouyX5gDcH5kGpZdYcwPpWNqVoqhQzl | end | fabricated | "2026-10-25T07:30:00+07:00" | null |
| pfbid0KfFuXSR1LyKtz1MQvsRR2civySNdRQuKrD8ouyX5gDcH5kGpZdYcwPpWNqVoqhQzl | registration_deadline | missed | null | "2026-10-04T23:59:00+07:00" |
| pfbid0KfFuXSR1LyKtz1MQvsRR2civySNdRQuKrD8ouyX5gDcH5kGpZdYcwPpWNqVoqhQzl | mode | missed | null | "offline" |
| pfbid0KfFuXSR1LyKtz1MQvsRR2civySNdRQuKrD8ouyX5gDcH5kGpZdYcwPpWNqVoqhQzl | location | missed | null | "Một trong hai cơ sở của Trường Đại học Khoa học tự nhiên, ĐHQG-HCM (thí sinh được thông báo qua email)" |
| pfbid0KfFuXSR1LyKtz1MQvsRR2civySNdRQuKrD8ouyX5gDcH5kGpZdYcwPpWNqVoqhQzl | audience | missed | null | ["Sinh viên Trường Đại học Khoa học tự nhiên, ĐHQG-HCM"] |
| pfbid02buju6UWyad8k9Z4xH1tR5eNwpWsuaZtnwfesY2o8UQzdFh3p7cHemVx24dkaHSdFl | title | wrong | "- “+1 MÁY” LÊN KÈO, VÈO VÈO CHẠY TRẠM" | "[ITogether] - \"+1 MÁY\" LÊN KÈO, VÈO VÈO CHẠY TRẠM" |
| pfbid02buju6UWyad8k9Z4xH1tR5eNwpWsuaZtnwfesY2o8UQzdFh3p7cHemVx24dkaHSdFl | domain | wrong | "volunteer" | "skills" |
| pfbid02buju6UWyad8k9Z4xH1tR5eNwpWsuaZtnwfesY2o8UQzdFh3p7cHemVx24dkaHSdFl | audience | missed | null | ["Tân sinh viên khoa Công nghệ thông tin"] |
| pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl | URL_registration | fabricated | "https://bit.ly/TheoDauChanNguoi2026" | null |
| pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl | title | wrong | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN “THEO DẤU CHÂN NGƯỜI”" | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN \"THEO DẤU CHÂN NGƯỜI\"" |
| pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl | domain | missed | null | "other" |
| pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl | start | missed | null | "2026-06-05T20:00:00+07:00" |
| pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl | end | missed | null | "2026-06-12T23:59:00+07:00" |
| pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl | audience | missed | null | ["Toàn thể sinh viên Trường Đại học Khoa học tự nhiên, ĐHQG-HCM"] |
| pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl | completion_requirements | wrong | "Ghi nhận tham gia: Sinh viên đạt từ 23/30 câu đúng trở lên được ghi nhận tham gia hoạt động học kỳ 2 năm học 2025 - 2026 đối với sinh viên chương trình Chuẩn, hoặc học kỳ 3 năm học 2025 - 2026 đối với sinh viên chương trình Đề án" | "Đạt từ 23/30 câu đúng trở lên" |
| pfbid02ATDhaQW22WUMoQuQ4Ef5tbLZS2RCUTLa7VxhpSxRwYiEcThL3pGfrsDf8refWW9Al | URL_registration | missed | null | "https://bit.ly/BLIT2026_DangKy" |
| pfbid02ATDhaQW22WUMoQuQ4Ef5tbLZS2RCUTLa7VxhpSxRwYiEcThL3pGfrsDf8refWW9Al | title | wrong | "- MỞ FORM ĐĂNG KÝ" | "[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ" |
| pfbid02ATDhaQW22WUMoQuQ4Ef5tbLZS2RCUTLa7VxhpSxRwYiEcThL3pGfrsDf8refWW9Al | registration_deadline | missed | null | "2026-09-25T23:59:00+07:00" |
