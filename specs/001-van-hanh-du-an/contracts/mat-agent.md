# Mặt agent (`/agent`)

Trưởng dự án và thợ gọi, bằng thẻ định danh theo workspace. Ký hiệu: **[có]** · **[sửa]** · **[mới]** · **[gỡ]**.

## 1. Ranh giới vai trò — cưỡng chế ở mặt giao tiếp

| Luật | Cách cưỡng chế |
|---|---|
| Thợ không báo cáo vượt cấp lên người chủ | Không có lối vào nào cho thợ đặt mục vào hộp thư người chủ. Thợ muốn hỏi thì bình luận trên đầu việc → Trưởng dự án được đánh thức (FR-071) |
| Thợ không tự nhận việc | **[gỡ]** đường tự-nhận đang có. Thay bằng `POST /agent/tasks/{id}/request` — một lời xin, định tuyến tới Trưởng dự án (FR-072) |
| Trưởng dự án không tự duyệt kế hoạch của mình | Mặt agent không có lối vào quyết kế hoạch (FR-014) |
| Hệ thống không quyết thay ai | Không lối vào nào để agent nhờ hệ thống chọn thợ hay lập kế hoạch (FR-073) |

## 2. Trưởng dự án

| Lối vào | Trạng thái | Ý nghĩa |
|---|---|---|
| `POST /agent/projects/{id}/context` | **[mới]** | Nộp bản Bối cảnh đã chốt sau đối thoại với người chủ → chuyển sang *chờ duyệt* |
| `POST /agent/projects/{id}/plan` | **[mới]** | Trình bản kế hoạch (hạng mục, thứ tự, phụ thuộc, rủi ro, mốc, định nghĩa hoàn thành mức hạng mục) kèm tin nhắn tóm tắt → đặt mục *chờ duyệt kế hoạch* vào hộp thư người chủ |
| `POST /agent/projects/{id}/tasks` | **[sửa]** | Thêm trường hạng mục. Trong khuôn → tạo và giao ngay; ngoài khuôn → ở lại *nháp* và đặt mục chờ duyệt (FR-027) |
| `POST /agent/tasks/{id}/approval` | **[mới]** | Chữ ký của Trưởng dự án: tán thành hay từ chối kèm lý do. Tán thành mà công tắc tự động của người chủ đang tắt → đầu việc **chưa** đóng, mục chờ công nhận vào hộp thư |
| `POST /agent/projects/{id}/phase-proposal` | **[mới]** | Đề xuất chuyển *vận hành ↔ bảo trì* → mục chờ quyết vào hộp thư. Agent **không** tự chuyển (FR-004) |
| `POST /agent/projects/{id}/change-request` | **[mới]** | Xin duyệt một thay đổi lớn: chạm phạm vi, mục tiêu, chi phí, thời hạn, hoặc tiêu chí công nhận (FR-075). Thay đổi nội bộ **không** đi qua đây |
| `POST /agent/tasks/{id}/recovery` | **[mới]** | Hành động phục hồi Mức 2: đổi người, chẻ lại, làm rõ đề, gia hạn, đổi ưu tiên. Bắt buộc nêu hành động chọn và lý do. **Ghi lại quyết định, không kết thúc Mức 2** — cái kết thúc Mức 2 là đầu việc có động cơ đẩy trở lại, nên hành động phải được *làm thật* chứ không chỉ khai |
| `POST /agent/tasks/{id}/escalate` | **[mới]** | Cửa thứ hai của Mức 2: đầu việc này ngoài tầm Trưởng dự án → đưa thẳng người chủ, không chờ hết lượt hỏi. Bắt buộc nêu lý do. Không có cửa này thì một Trưởng dự án biết ngay là mình bó tay chỉ còn hai nước: ngồi hết ngân sách, hoặc bịa một hành động cho có |

Hai cửa trên là **một cửa sổ, hai lối** (FR-060b), nên chúng dùng chung đúng một luật gọi:

- **Đòi ghế Trưởng dự án.** Thợ gọi → `404` (không phải `403`: sự tồn tại của đầu việc không được lộ, Hiến pháp I). Cả hai cửa đều chạm tới thứ chỉ Trưởng dự án được chạm — một cửa ghi một quyết định **mang danh Trưởng dự án** vào đúng cái sổ dựng nên hồ sơ gửi người chủ, cửa kia gọi thẳng tới một con người.
- **Chỉ mở ở Mức 2.** Ngoài cửa sổ đó → `409`. Dưới Mức 2 hệ còn đang tự thử; từ Mức 3 câu hỏi đã thuộc về người chủ.

## 3. Thợ

| Lối vào | Trạng thái | Ý nghĩa |
|---|---|---|
| Cập nhật đầu việc, nộp thành phẩm, bình luận, đặt việc kế tiếp | **[có]** | Giữ nguyên |
| `POST /agent/tasks/{id}/status` | **[sửa]** | Bảng chuyển siết; *đang làm → xong* trả `409` kèm lý do "phải qua rà soát" |
| `POST /agent/tasks/{id}/request` | **[mới]** | Xin nhận một đầu việc → định tuyến tới Trưởng dự án, không tự gán |
| `POST /agent/tasks/{id}/handback` | **[mới]** | Trả việc kèm lý do, hoặc đặt một câu hỏi làm rõ. Đây là hành vi lành mạnh: đầu việc gắn động cơ *chờ Trưởng dự án*, **không** tính là đình trệ (FR-056) |

## 4. Gói tin đánh thức **[sửa]**

Không phải một lối vào — là nội dung hệ thống trao cho agent lúc gọi dậy. Tám phần bắt buộc:

1. Vai của agent trong dự án này
2. **Bối cảnh dự án đã duyệt** — phần đang thiếu
3. Đầu việc đang nói tới, kèm mô tả và trạng thái
4. Lý do gọi dậy, viết thành câu người đọc hiểu
5. Danh bạ đồng đội kèm trạng thái sống
6. Tin nhắn mới kể từ lượt trước
7. Việc kế tiếp đang chờ
8. **Nơi nộp thành phẩm và cách báo trạng thái** — tách thành mục riêng

Phần nào rỗng thì ghi rõ "không có" (FR-045).

Với gói tin **nhịp điều phối** gửi Trưởng dự án, phần *lý do gọi dậy* liệt kê đích danh từng điểm treo —
"đầu việc AR-12 im hai ngày, AR-19 sắp trễ, AR-23 đang chờ bạn quyết" — không nói chung chung (FR-054).

## 5. Cớ đánh thức

| Cớ | Trạng thái | Ai nhận |
|---|---|---|
| Được giao việc, bị nhắc tên, có bình luận mới, tiếp lượt dở, gọi tay | **[có]** | Thợ |
| Vướng đã được gỡ | **[sửa]** | Thợ |
| Bị nhắc vì im lâu | **[mới]** | Thợ |
| Đầu việc chuyển *chờ rà soát* | **[mới]** | Trưởng dự án |
| Đầu việc chuyển *xong* | **[mới]** | Trưởng dự án |
| Người chủ quyết (duyệt kế hoạch, công nhận, chuyển giai đoạn) | **[mới]** | Trưởng dự án |
| Thợ trả việc hoặc kêu cứu | **[mới]** | Trưởng dự án |
| Đầu việc thất bại hoặc quá hạn | **[mới]** | Trưởng dự án |
| **Nhịp điều phối** | **[mới]** | Trưởng dự án — chỉ bắn khi có điểm treo thật |
| Phục hồi treo | **[mới]** | Người phụ trách cũ |

**Bất biến gộp** (FR-050): mỗi cặp *(agent, đầu việc)* tối đa **một** lệnh treo và **một** lượt chạy tại một
thời điểm — cưỡng chế ở tầng lưu trữ, không bằng bộ nhớ tiến trình, để sống sót qua khởi động lại.
