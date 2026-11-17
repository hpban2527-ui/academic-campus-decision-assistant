# Bộ quy tắc xử lý thông tin hoạt động — tổng hợp đến 13/11/2026

Nguồn: tài liệu `hoàn thiện đồ án.md` của Duyên và các xác nhận tiếp theo trong cuộc trao đổi. Khi có khác biệt, quyết định mới hơn được ưu tiên. Đây là bản tổng hợp nghiệp vụ, không phải xác nhận các quy tắc đã được triển khai trong code. Những mục ghi “chưa chốt” hoặc “đề xuất” không được coi là quyết định của nhóm.

## 1. Phạm vi và trách nhiệm SP1–SP3

- Dữ liệu do Trí thu thập có thể gồm bài nhiều học kỳ, bài hoạt động, thông báo thuần túy và bài thiếu thông tin. Không còn giả định tất cả bài đều được ghi nhận điểm rèn luyện.
- SP1 đọc nội dung bài đăng và dữ liệu nguồn để trích xuất, chuẩn hóa thông tin hoạt động theo quy tắc.
- SP2 dùng thông tin hoạt động và bộ quy tắc tính điểm để xác định mục điểm, giá trị và điều kiện áp dụng. Có căn cứ ghi nhận hoạt động không đồng nghĩa đã biết số điểm hoặc đã cộng điểm cho sinh viên.
- SP3 dùng thông tin hoạt động, kết quả SP2 và hồ sơ/lịch của sinh viên để kiểm tra khả năng tham gia, lập kế hoạch. Kết quả tự xác nhận hoàn thành thuộc từng sinh viên, không phải dữ kiện được AI trích xuất từ bài đăng.
- Chưa chốt việc giao AI lựa chọn rule SP2 đến mức nào, hay danh mục loại hoạt động/vai trò phục vụ mapping.

## 2. Đơn vị trích xuất và tên hoạt động

- Một bài đăng được xem là một hoạt động.
- Nhiều buổi: chọn buổi đầu tiên; theo phạm vi đơn giản hóa của nhóm, tham gia một buổi là đủ.
- Nhiều vòng: chỉ xét tham gia vòng đầu tiên.
- `title`: lấy tên chính thức, giữ những tiền tố như “THÔNG BÁO”, “MỞ FORM” nếu thuộc tên được lấy từ bài.
- Đề xuất kỹ thuật: giữ định danh, nội dung gốc và URL bài đăng để truy ngược khi kiểm tra. Không nhầm URL nguồn với URL đăng ký/tham gia.

## 3. Phân loại bài và `drl_recognized`

| Căn cứ trong nguồn | Quy tắc đã chốt |
| --- | --- |
| Có yếu tố đăng ký tham gia/đăng ký thi | `true`; không bắt buộc phải có URL đăng ký |
| Có link Zoom/Meet hoặc link làm quiz phục vụ hoạt động | Được xem là cách tham gia hợp lệ |
| Nói rõ được ghi nhận hoạt động/điểm, dù không có link | `true` |
| Nguồn đủ thông tin và thực sự không có căn cứ thuộc các nhóm trên | `false` |
| Bài bị cắt hoặc thiếu thông tin khiến không kết luận được | `null`, cần kiểm tra |
| Bài bắt buộc, không làm bị trừ điểm, không có đăng ký/link | Vẫn giữ để xử lý bắt buộc và điểm trừ; chưa chốt rằng riêng trường hợp này phải gán `drl_recognized=true` |

- Bài thông tin thuần túy như thông báo kết quả, tổng kết, nhắc lịch hành chính: lưu nguồn, không đưa vào danh sách hoạt động để kiếm điểm. Cần đọc nội dung, không loại chỉ vì tiêu đề có chữ “thông báo”.
- Bài có căn cứ tham gia/ghi nhận: tiếp tục kiểm tra và mapping SP2.
- Bài chưa đủ thông tin: kiểm tra lại; không tự động coi là không có điểm.
- Extractor không tìm thấy thông tin chưa chứng minh rằng nguồn không có thông tin đó.
- Giữ `drl_recognized` hoặc trạng thái tương đương trong thiết kế mới; quyết định cũ bỏ trường vì mọi bài đều có điểm đã không còn phù hợp với phạm vi dữ liệu mới.
- `true` là kết luận theo quy ước phân loại của nhóm, không phải xác nhận nhà trường đã cộng điểm cho một sinh viên cụ thể.

## 4. Domain, loại hoạt động và hình thức

- `domain` mô tả lĩnh vực/chủ đề phục vụ sở thích; một hoạt động có một domain.
- Sở thích là tùy chọn, dùng hỗ trợ lựa chọn giữa những hoạt động phù hợp, ví dụ cùng một timeslot nhưng khác domain.
- Định hướng ban đầu: domain và sở thích có thể thể hiện bằng ngôn ngữ tự nhiên. Quy ước domain và cách so khớp cuối cùng còn chờ thống nhất với người phụ trách personalized.
- Domain không đồng nghĩa loại hoạt động dùng mapping SP2. Ví dụ “công nghệ” mô tả chủ đề, còn “cuộc thi” mô tả hình thức hoạt động; ví dụ này không phải danh mục nhãn đã chốt.
- `mode`: `online`, `offline`, `hybrid`.
- `hybrid` theo định nghĩa của nhóm: được chọn online hoặc offline. Cách planner chọn và điều kiện hoàn thành hybrid chưa chốt.

## 5. Thời gian và thời lượng

Phải phân biệt khoảng mở hoạt động trong nguồn với khoảng sinh viên thực sự được xếp tham gia. Đặc biệt với online, một cửa sổ mở nhiều ngày không có nghĩa sinh viên phải tham gia liên tục nhiều ngày.

| Trường hợp | Quy tắc hiện tại |
| --- | --- |
| Offline có giờ bắt đầu và kết thúc | Tham gia toàn bộ start–end |
| Offline có giờ bắt đầu, không có giờ kết thúc | Tham gia 2 giờ kể từ giờ bắt đầu; 08:00 thì 08:00–10:00 |
| Online | Theo chính sách của nhóm, được xếp linh hoạt trong khoảng mở–đóng, kể cả webinar trực tiếp |
| Quiz có công bố thời lượng | Dùng thời lượng quiz công bố |
| Quiz không có thời lượng | Mặc định 30 phút |
| Online khác | Bản quy tắc gốc đặt thời lượng mặc định 30 phút; cách xử lý thời lượng công bố của online không phải quiz chưa được xác nhận riêng |
| Có ngày, thiếu giờ | Bản gốc quy ước biên mở 00:00 ngày đầu, biên đóng 23:59 ngày cuối; cần phân biệt đây là biên chuẩn hóa với giờ tham gia thực tế |
| Có ngày/tháng, thiếu năm | Suy luận dựa trên ngày đăng bài |
| Nhắc ngày trong thông báo cũ | Chỉ lấy nếu thực sự là lịch của hoạt động đang xét |
| Các mốc thời gian mâu thuẫn | Đánh dấu cần đối chiếu |
| Múi giờ | Chuẩn hóa `+07:00` |

- Online: cả giờ bắt đầu và kết thúc của lượt tham gia phải nằm trong cửa sổ mở–đóng.
- Nhiều buổi lấy lịch buổi đầu; nhiều vòng lấy lịch vòng đầu.
- Còn mở: bản gốc quy định vòng đầu mặc định 2 giờ; sau đó xuất hiện câu hỏi nếu vòng đầu online thì dùng 30 phút hay 2 giờ. Chưa có xác nhận cuối cùng. Đề xuất là dùng quy tắc theo mode/quiz, nhưng chưa coi là đã chốt.
- Còn mở: offline chỉ có ngày, thiếu giờ thực tế, sẽ chọn 2 giờ trong ngày hay áp dụng một mốc bắt đầu khác. Không tự hiểu 00:00 chuẩn hóa là giờ sự kiện chắc chắn bắt đầu.
- Không tự suy luận thêm các tình huống năm/học kỳ ngoài phạm vi nhóm đã xác nhận.
- Đề xuất kỹ thuật: lưu riêng cửa sổ hoạt động, thời lượng và khoảng đã xếp; tên trường cụ thể cần thống nhất schema, chưa phải thay đổi đã được duyệt.

## 6. Đăng ký và đường dẫn

- Chỉ cần có yếu tố đăng ký, không yêu cầu luôn có link.
- Zoom/Meet/link quiz là cách tham gia hợp lệ.
- Có công bố ghi nhận hoạt động vẫn hợp lệ dù thiếu link.
- Không tự tạo URL hoặc hạn đăng ký từ suy đoán.
- Hạn đăng ký và giờ đóng hoạt động mang ý nghĩa khác nhau; không tự đồng nhất.
- Cách xử lý khi không có hạn đăng ký để SP3 vẫn đánh giá được còn cần chốt. Việc thiếu hạn đăng ký không tự động bác bỏ căn cứ `drl_recognized` đã có.
- Cấu trúc lưu URL đăng ký và URL tham gia riêng hay chung chưa được chốt trong schema cuối cùng.

## 7. Địa điểm

| Nội dung | Kết quả |
| --- | --- |
| Nguyễn Văn Cừ | CS1 |
| Linh Trung | CS2 |
| Ngoài trường | Other |
| Online | `location=null` |
| “Một trong hai cơ sở, thông báo sau” | Lưu cả CS1 và CS2 như những địa điểm có thể diễn ra |

- Giữ phòng, hội trường và địa chỉ chi tiết trong `location`.
- Địa điểm ở một cơ sở không giới hạn đối tượng chỉ còn sinh viên cơ sở đó.
- Lưu cả hai cơ sở không có nghĩa phải tham gia ở cả hai hoặc đã chọn được một cơ sở chắc chắn.
- Đề xuất kỹ thuật: tách nhãn cơ sở khỏi địa chỉ chi tiết để tránh `location` vừa phải chứa mã vừa phải chứa địa chỉ. Tên trường và kiểu dữ liệu chưa chốt.

## 8. Đối tượng và tính bắt buộc

Đối tượng:
- Các thuộc tính đang xét: khóa như K24/K25 và chương trình đại trà/CLC.
- Không nêu đối tượng: mọi sinh viên được tham gia.
- “Ưu tiên” không phải điều kiện loại trừ bắt buộc.
- Các điều kiện đối tượng ngoài phạm vi trên tạm thời chưa triển khai.

Bắt buộc:
- Có “bắt buộc”, “không làm bị trừ điểm” hoặc ý tương đương: `mandatory=true`.
- Không có căn cứ bắt buộc: mặc định `false`.
- Bắt buộc có phạm vi, áp dụng theo đối tượng của bài; không tự áp dụng cho tất cả sinh viên.
- Planner phải đưa hoạt động bắt buộc áp dụng cho sinh viên vào kế hoạch.
- Bỏ qua có trừ điểm; mức trừ và mục bị trừ phải theo quy tắc SP2, không tự bịa số.
- Bài bắt buộc không có link/đăng ký vẫn được giữ.
- Xử lý khi bắt buộc trùng lịch học chưa chốt. Nhận định “ít khi xung đột” không phải quy tắc cho phép xếp chồng.
- Cần giữ nguyên phạm vi nguồn. Ví dụ “K25 CLC” có cả khóa và chương trình; xác nhận sau đó mới nhấn mạnh K25, chưa đủ để tự loại bỏ điều kiện CLC.

## 9. Điều kiện hoàn thành và ghi nhận cho sinh viên

Mục đích: phân biệt đăng ký với hoàn thành. Theo chính sách nhóm, sinh viên tự xác nhận đã thực hiện và đạt điều kiện thì hệ thống ghi nhận điểm tương ứng qua SP2.

| Loại hoạt động | Điều kiện/thông báo xác nhận |
| --- | --- |
| Offline | Xác nhận đã tham gia và điểm danh |
| Nhiều buổi | Xác nhận tham gia một buổi; buổi được chọn để xét là buổi đầu |
| Quiz có ngưỡng | Giữ đúng ngưỡng từ nguồn; hỏi đã tham gia và đạt ngưỡng chưa |
| Quiz không có ngưỡng | Hỏi xác nhận đã tham gia |
| Hybrid hoặc nộp sản phẩm | Tạm thời chưa chốt cách xử lý |

- Không tự tạo ngưỡng số câu đúng, tỷ lệ hoặc điểm đạt.
- Hỏi xác nhận sau thời hạn thực hiện. Với online, kích hoạt sau lượt được xếp hay sau toàn bộ cửa sổ đóng còn chưa chốt.
- Điều kiện hoàn thành là thông tin của hoạt động; đã hoàn thành hay chưa là trạng thái của từng sinh viên.
- Điểm tính cho kế hoạch là điểm dự kiến; chưa đăng ký/hoàn thành không có nghĩa đã nhận điểm.
- Đề xuất triển khai: xác nhận lặp lại không được làm cộng điểm nhiều lần cho cùng một hoạt động.

## 10. Phí và điểm

- Không ghi phí: mặc định miễn phí theo quy ước nhóm.
- Phí theo đội: giữ giá theo đội, không tự chia hoặc coi là phí mỗi người.
- Đặt cọc: được coi là phí tham gia theo quy ước nhóm.
- Chưa chốt cách biểu diễn khi có đồng thời nhiều khoản phí/đặt cọc.
- Không ghi số điểm: để SP2 xác định bằng bộ mapping; không coi thiếu số điểm là được 0 điểm.
- Giả định dữ liệu hiện tại của nhóm là bài đăng không công bố số điểm. Nếu gặp số điểm được công bố và khác mapping, cách ưu tiên chưa chốt.
- `drl_recognized`, mục điểm, số điểm dự kiến và trạng thái đã nhận điểm là các thông tin khác nhau.

## 11. Học kỳ

- Sinh viên chọn học kỳ; có hai chương trình: đại trà và CLC.
- Cả hai chương trình đang xét HK2 năm học 2025–2026 và HK1 năm học 2026–2027.
- Gán kỳ dựa trên thời gian hoạt động đối chiếu ngày bắt đầu/kết thúc học kỳ do nhóm cung cấp; không lấy ngày đăng bài làm ngày hoạt động để gán kỳ.
- Trong phạm vi đã chốt không có hoạt động kéo dài qua hai kỳ.
- Ngày cụ thể của từng kỳ chưa được cung cấp/chốt trong tài liệu hiện có.

## 12. Đề xuất chuyển bộ quy tắc thành NLP

Phần này là hướng triển khai, không phải toàn bộ đã được nhóm duyệt:

1. Đối chiếu schema cũ với các nhu cầu trên; giữ trường còn phù hợp và thống nhất phần bổ sung trước khi làm adapter.
2. Phân biệt dữ kiện có trong nguồn, giá trị suy ra theo quy tắc và thông tin chưa biết. Ví dụ “2 giờ” có thể là mặc định, không phải câu được bài đăng công bố.
3. Dùng AI đọc ngôn ngữ, xác định dữ kiện và căn cứ; dùng bước chuẩn hóa/kiểm tra để áp dụng các quy tắc cố định như cộng 2 giờ, múi giờ và mã cơ sở.
4. Lưu căn cứ từ bài và dấu hiệu cần kiểm tra; không bắt AI điền chắc chắn khi nguồn thiếu hoặc mâu thuẫn.
5. Duyên đối chiếu kết quả AI với nguồn, tạo bộ mẫu đã kiểm tra và dùng lại để kiểm tra khi sửa prompt/quy tắc.
6. Kiểm tra cả đường đi SP1 → SP2 → SP3, không chỉ việc AI xuất được một file đúng cấu trúc. Mỗi SP cần nhận đúng ý nghĩa của thời gian, điểm, địa điểm và trạng thái.

Không đặt giả định AI bảo đảm đúng 100% trên mọi bài mới. Bộ quy tắc cùng bộ mẫu chuẩn giúp đo lỗi, tìm nguyên nhân và ngăn dữ liệu chưa rõ bị coi là chắc chắn.

## 13. Những phần còn cần chốt trước khi đóng phiên bản

1. Thời lượng vòng đầu online; offline chỉ có ngày; thời lượng công bố của online không phải quiz.
2. Hạn đăng ký vắng mặt và cách SP3 xử lý.
3. Domain và cách so khớp sở thích với người làm personalized.
4. Schema thống nhất cho cơ sở/địa chỉ, lịch/thời lượng, URL, phí theo đội và phạm vi đối tượng.
5. Danh mục và căn cứ mapping SP2; mức/mục điểm trừ; cách xử lý điểm công bố nếu gặp.
6. Giá trị `drl_recognized` cho ngoại lệ bắt buộc không có căn cứ đăng ký/ghi nhận khác; chắc chắn vẫn phải giữ bài.
7. Xung đột lịch của hoạt động bắt buộc và phạm vi khóa/chương trình phải được bảo toàn.
8. Thời điểm hiện xác nhận hoàn thành online; hybrid/nộp sản phẩm vẫn là phần đang hoãn.
9. Mốc ngày cụ thể của các học kỳ.

Không cần mở rộng thêm các trường hợp ngoài phạm vi đã thống nhất để triển khai phiên bản đầu. Những phần đang hoãn phải được ghi nhận là chưa hỗ trợ, không âm thầm gán một quy tắc mặc định mới.
