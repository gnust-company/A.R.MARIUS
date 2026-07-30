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

1. **FR-051 từng không kiểm được** — nói "đặt trần số lần đánh thức theo nhịp" mà không có con số, trong khi
   tài liệu gốc cũng để ngỏ. Đã bổ sung mặc định vào mục Giả định (rà mỗi 15 phút, trần 4 lần trong một giờ,
   giãn tối đa 2 giờ), nhờ đó SC-008 mới đo được.
2. **Bốn điểm tài liệu gốc để ngỏ** (§5.2 của `THIET-KE-VAN-HANH-DU-AN.md`) — thay vì để lại dấu chờ làm rõ,
   đã lấy chính đề xuất trong tài liệu làm mặc định và ghi rõ trong mục Giả định là **chờ người chủ chốt
   lại**. Bốn điểm đó: ranh giới "thay đổi lớn"; mặc định cờ *cần Chủ đồng-approve*; ai kích chuyển giai đoạn
   giữa vận hành và bảo trì; các ngưỡng thời gian.

**Còn cần người chủ xác nhận** — nếu chốt khác với mặc định đang ghi, các yêu cầu FR-004, FR-033, FR-071 và
bảng ngưỡng trong mục Giả định phải sửa theo trước khi sang bước thiết kế.

**Ràng buộc từ Hiến pháp** đã được nạp thành yêu cầu tường minh: đa tenant nghiêm ngặt (FR-077), cổng Done
qua thành phẩm (FR-024, FR-026), trung lập adapter (FR-079), đẩy không hỏi vòng (FR-076), góc nhìn dự án
(FR-078), tiếng Việt qua đa ngôn ngữ (FR-080).
