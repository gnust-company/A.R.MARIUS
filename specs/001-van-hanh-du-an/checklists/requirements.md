# Danh mục kiểm chất lượng đặc tả: Vận hành dự án tự chủ

**Mục đích**: Xác nhận đặc tả đủ và đạt chất lượng trước khi sang bước thiết kế
**Ngày tạo**: 2026-07-30
**Tính năng**: [spec.md](../spec.md)

## Chất lượng nội dung

- [x] Không lẫn chi tiết cài đặt (ngôn ngữ, khung nền, giao diện lập trình)
- [x] Bám vào giá trị người dùng và nhu cầu nghiệp vụ
- [x] Viết cho người đọc không chuyên kỹ thuật
- [x] Đủ mọi mục bắt buộc

## Độ đầy đủ của yêu cầu

- [x] Không còn dấu [NEEDS CLARIFICATION] nào
- [x] Yêu cầu kiểm được và không nước đôi
- [x] Tiêu chí thành công đo được
- [x] Tiêu chí thành công không dính công nghệ cụ thể
- [x] Đủ kịch bản chấp nhận
- [x] Đã nhận diện các tình huống biên
- [x] Phạm vi có ranh giới rõ
- [x] Đã nêu phụ thuộc và giả định

## Mức sẵn sàng của tính năng

- [x] Mọi yêu cầu chức năng đều có tiêu chí chấp nhận rõ
- [x] Các câu chuyện người dùng phủ hết luồng chính
- [x] Tính năng đạt được các kết quả đo được đã đặt
- [x] Không rò chi tiết cài đặt vào đặc tả

## Ghi chú

**Vòng rà 1 — kết quả: đạt hết.** Hai điểm đã sửa trong lúc rà:

1. **FR-055 từng không kiểm được** — nói "đặt trần số lần đánh thức theo nhịp" mà không có con số, trong khi
   tài liệu gốc cũng để ngỏ. Đã bổ sung mặc định vào mục Giả định (rà mỗi 15 phút, trần 4 lần trong một giờ,
   giãn tối đa 2 giờ), nhờ đó SC-008 mới đo được.
2. **Bốn điểm tài liệu gốc để ngỏ** (§5.2 của `THIET-KE-VAN-HANH-DU-AN.md`) — thay vì để lại dấu chờ làm rõ,
   đã lấy chính đề xuất trong tài liệu làm mặc định và ghi rõ trong mục Giả định là chờ người chủ chốt lại.

**Vòng rà 2 (2026-07-30) — cả bốn điểm đã được người chủ chốt, thêm một chỗ hở được vá.** Chi tiết ở mục Làm
rõ trong đặc tả:

1. **Ranh giới "thay đổi lớn"** — giữ nguyên năm thứ (FR-075).
2. **Cơ chế công nhận** — **đổi hẳn thiết kế**, không chỉ chọn mặc định: bỏ cờ theo từng việc; mọi đầu việc
   cần hai chữ ký (Trưởng dự án + người chủ đã cấp agent vào ghế), kèm công tắc tự động công nhận theo cặp
   *(dự án, người chủ)*. Đã viết lại toàn bộ mục F (FR-033…FR-043), Câu chuyện 3, bộ trường ở FR-015, hai
   thực thể, và thêm SC-014.
3. **Chuyển vận hành ↔ bảo trì** — Trưởng dự án đề xuất, người chủ quyết (FR-004). Kéo theo FR-037: công tắc
   tự động công nhận **không** thay người chủ ở duyệt kế hoạch, duyệt thay đổi lớn, và chuyển giai đoạn.
4. **Ngưỡng thời gian** — nhịp dự án là "mỗi đầu việc vài giờ tới vài ngày", giữ nguyên bộ số đề xuất.
5. **Chỗ hở phát hiện thêm** — FR-027 (cổng duyệt) trước đây nói "đầu việc được đánh dấu cần người chủ đồng
   ý" mà không có luật nào định khi nào dấu ấy được đặt, nên không kiểm được. Nay đã rõ: Trưởng dự án tự tạo
   và giao trong khuôn kế hoạch đã duyệt; ngoài khuôn thì phải ở lại *nháp* chờ người chủ gật. Thêm hai kịch
   bản chấp nhận cho Câu chuyện 2.

**Không còn điểm nào chờ người chủ chốt.** Đặc tả sẵn sàng cho bước thiết kế.

**Ràng buộc từ Hiến pháp** đã được nạp thành yêu cầu tường minh: đa tenant nghiêm ngặt (FR-081), cổng Done
qua thành phẩm (FR-024, FR-026), trung lập adapter (FR-083), đẩy không hỏi vòng (FR-080), góc nhìn dự án
(FR-082), tiếng Việt qua đa ngôn ngữ (FR-084).
