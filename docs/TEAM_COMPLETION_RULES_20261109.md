# Quy tắc hoàn thành hoạt động — ghi nhận trao đổi ngày 09/11/2026

Tài liệu ghi lại yêu cầu trực tiếp của người dùng. Đây là cơ sở cho các thay đổi tiếp theo, chưa phải mô tả tính năng đã được triển khai. Tên trường hiện có trong code là `completion_requirements`.

Các mục có ngày là lịch sử quyết định. Nếu khác nhau, áp dụng xác nhận mới nhất; phần ghi rõ là đề xuất chưa được coi là quyết định.

## Các quyết định đã được người dùng xác nhận

- Quyết định ngày 09/11 về việc mọi hoạt động đầu vào đều thuộc diện ĐRL đã được thay thế bởi cập nhật ngày 11/11 bên dưới. Không dùng giả định này cho bộ nguồn mở rộng.
- Mục đích của `completion_requirements` là mô tả điều kiện để sinh viên tự xác nhận đã hoàn thành hoạt động. Đăng ký và hoàn thành là hai trạng thái riêng.
- Online dạng quiz: lấy ngưỡng hoàn thành từ bài nguồn, chẳng hạn số câu đúng hoặc tỷ lệ cần đạt. Sau thời hạn thực hiện, hệ thống hỏi sinh viên đã đạt ngưỡng đó chưa.
- Offline dạng tham gia sự kiện: điều kiện cơ bản là có mặt. Sau thời hạn thực hiện, hệ thống hiển thị yêu cầu xác nhận đã tham gia.
- Sinh viên tự xác nhận hoàn thành là căn cứ để ứng dụng ghi nhận điểm theo quy tắc áp dụng. Chỉ đăng ký chưa đủ để cộng điểm hoàn thành. Yêu cầu này không đòi hỏi một bước xác minh nhân sự bên ngoài thay cho thao tác tự xác nhận.
- Người dùng sẽ tự thử AI extraction và đối chiếu thủ công với bài nguồn.

## Các nội dung đang được hỏi ý kiến, chưa chốt thay đổi code

- `drl_recognized` được giữ với ba giá trị theo quyết định ngày 12/11 bên dưới. Đề xuất bỏ trường này trước đó đã được thay thế.
- Cách bổ sung mapping quy tắc và dữ liệu lịch cho hoạt động thật sau khi sửa extraction.
- Cách xử lý các loại hoạt động ngoài hai trường hợp quiz online và tham gia sự kiện offline, hoặc bài thiếu ngưỡng/thời hạn rõ ràng.

## Ghi chú triển khai đề xuất để đối chiếu sau này

- Tách điều kiện của hoạt động khỏi trạng thái hoàn thành của từng sinh viên. SP1 trích xuất điều kiện; backend lưu trạng thái đăng ký, tự xác nhận và thời điểm xác nhận.
- Nếu áp dụng mặc định offline là "có mặt", lưu nguồn giá trị là quy tắc của nhóm; không tạo đoạn trích dẫn giả từ bài đăng. Giữ các yêu cầu cụ thể được bài nguồn nêu và đối chiếu nếu khác quy tắc chung.
- Không đoán ngưỡng quiz khi bài nguồn thiếu. Không dùng một thời điểm do mặc định kỹ thuật tạo ra làm thời hạn chắc chắn để hỏi hoàn thành.
- Cộng điểm theo SP2, áp trần và chống cộng trùng khi xác nhận hoặc gửi lại yêu cầu. Nếu trước đó có điểm dự kiến, cần chuyển trạng thái phù hợp để tránh cộng hai lần.
- `main` đã kiểm tra ở commit `b1242036cebb414f62dde97a869de4396b35cc2d`: SP3 dùng dữ liệu mẫu riêng; luồng web đang có ô tự khai minh chứng và bước lưu điểm demo. Luồng hỏi hoàn thành sau thời hạn và sự liên kết với hoạt động thật cần được triển khai/kiểm chứng theo các quyết định phía trên.

## Cập nhật phạm vi dữ liệu ngày 11/11/2026

- Trí tiếp tục thu thập bài từ nhiều học kỳ. Nhóm đã quyết định cho sinh viên chọn học kỳ.
- Bộ nguồn gồm cả bài được và không được ghi nhận điểm. Người dùng nêu các bài thông báo, bài không có đăng ký/không có link thi là các trường hợp không được cộng điểm theo phạm vi dự án.
- Cần làm rõ ý nghĩa "bài thông báo" (thông tin thuần túy hay bao gồm thông báo mở hoạt động) và tiêu chí đăng ký: có bắt buộc một URL hay chấp nhận cách đăng ký khác được nêu rõ.
- Chưa chốt thuật toán gán học kỳ, các mốc học kỳ theo chương trình/năm học, hoặc cách xử lý hoạt động qua nhiều kỳ. Không mặc định ngày đăng bài là kỳ ghi nhận.
- Đề xuất để thảo luận: giữ riêng bài nguồn, thông tin trích xuất, kết luận đủ điều kiện theo chính sách nhóm và phạm vi học kỳ. Thiếu dữ liệu vì thu thập/trích xuất lỗi cần phân biệt với nguồn thực sự không đáp ứng chính sách.

## Quyết định về lịch ngày 12/11/2026

Các quyết định dưới đây ghi nhận lời xác nhận mới nhất của người dùng khi làm rõ tài liệu `hoàn thiện đồ án.md`. Đây là quy tắc đề án cần triển khai, chưa phải hành vi đã được sửa trong code.

### Đã xác nhận

- Offline có thời điểm bắt đầu rõ và thiếu thời điểm kết thúc: tham gia cố định từ lúc bắt đầu đến hai tiếng sau. Lưu căn cứ của thời điểm kết thúc được tính là mặc định theo chính sách.
- Offline có cả bắt đầu và kết thúc: tham gia toàn bộ khoảng start–end được bài nêu; không cắt hoặc kéo thành hai tiếng.
- Quiz có thời lượng được nêu: dùng thời lượng đó. Quiz không nêu thời lượng: dùng mặc định 30 phút.
- Quy tắc online cho phép chọn thời điểm tham gia trong cửa sổ hoạt động áp dụng cả webinar trực tiếp theo quyết định nhóm.
- Hoạt động nhiều buổi: chọn buổi đầu tiên. Tài liệu người dùng cũng chọn vòng 1 cho hoạt động nhiều vòng.

### Đề xuất đang chờ người dùng chốt

- Vòng 1 online áp dụng quy tắc online: quiz có thời lượng thì dùng giá trị nguồn, quiz thiếu thời lượng dùng 30 phút; trường hợp online còn lại áp dụng quy tắc online chung trong tài liệu. Thời gian tham gia phải nằm trọn trong cửa sổ của vòng 1.
- Các trường hợp chưa có đủ giờ bắt đầu, thiếu cửa sổ online, cửa sổ ngắn hơn thời lượng và ý nghĩa thời lượng được nêu cho webinar vẫn cần được xác định khi hoàn thiện quy tắc.

## Quyết định bổ sung ngày 12/11/2026: đăng ký, địa điểm, học kỳ và bắt buộc

### Đăng ký và `drl_recognized`

- Chỉ cần có yếu tố đăng ký trong nội dung, không bắt buộc phải có URL đăng ký.
- Link Zoom/Meet hoặc link làm quiz được coi là cách tham gia hợp lệ.
- Bài nói rõ được ghi nhận hoạt động/điểm thì `drl_recognized=true` kể cả không có link.
- Bài thực sự không có căn cứ theo chính sách trên thì `false`. Bài bị cắt hoặc thiếu dữ liệu để kết luận thì `null`.
- Bài bắt buộc làm và bỏ qua bị trừ điểm vẫn được giữ trong luồng xử lý kể cả không có đăng ký/link. Quy tắc giữ lại bài bắt buộc không phụ thuộc riêng vào việc có link.

### Domain và audience

- Domain sẽ được thống nhất thêm với người phụ trách personalized. Chưa tự chốt cấu trúc hoặc cách so khớp mới.
- Audience ngoài các nội dung đã chốt được tạm hoãn; chưa mở rộng xử lý.

### Địa điểm

- Nguyễn Văn Cừ tương ứng CS1.
- Linh Trung tương ứng CS2.
- Ngoài trường tương ứng Other.
- Online có location null.
- "Một trong hai cơ sở, thông báo sau" lưu cả CS1 và CS2 như các khả năng địa điểm, không chọn tùy ý một cơ sở đã xác định.
- `location` giữ địa chỉ chi tiết. Đề xuất kỹ thuật: nhãn cơ sở nằm trong dữ liệu bổ sung, hỗ trợ lưu nhiều cơ sở; tên trường/schema bổ sung chưa được chốt.

### Học kỳ

- Gán học kỳ theo khoảng ngày bắt đầu và kết thúc học kỳ do nhóm cung cấp. Mốc cụ thể sẽ được nhóm chốt sau.
- Phạm vi dự án không có hoạt động kéo dài qua hai học kỳ.
- Người dùng yêu cầu bám phạm vi này và không tiếp tục suy diễn thêm nhiều tình huống ngoài phạm vi.

### Hoạt động bắt buộc

- Planner phải đưa hoạt động bắt buộc áp dụng cho sinh viên vào kế hoạch.
- Nếu bỏ qua hoạt động bắt buộc thì có trừ điểm. Chưa có quyết định mới về số điểm trừ hoặc thời điểm áp dụng; cần lấy từ quy tắc SP2/phần triển khai tương ứng.
- Tính bắt buộc có phạm vi đối tượng, ví dụ yêu cầu đối với K25 hoặc nội dung "K25 CLC". Giữ nguyên điều kiện nguồn để đối chiếu hồ sơ; không coi mọi sinh viên đều bắt buộc.
- Về xung đột lịch học, người dùng cho biết ít khi xảy ra. Chưa có quyết định cho phép xếp chồng lịch hay cách giải quyết xung đột; không chuyển nhận định ít xảy ra thành chính sách bỏ qua ràng buộc lịch.
