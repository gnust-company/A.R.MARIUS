# Hợp đồng giao diện: Vận hành dự án tự chủ

**Giai đoạn 1** của [plan.md](../plan.md) · Mô hình dữ liệu: [data-model.md](../data-model.md)

Ba mặt giao tiếp phải mở rộng. Ký hiệu: **[có]** đã tồn tại · **[sửa]** đổi hành vi · **[mới]** chưa có.

| Mặt | Ai gọi | Tệp hợp đồng |
|---|---|---|
| Mặt người dùng (`/v1`) | Trình duyệt của người chủ | [user-surface.md](./user-surface.md) |
| Mặt agent (`/agent`) | Trưởng dự án và thợ | [agent-surface.md](./agent-surface.md) |
| Dòng sự kiện đẩy | Trình duyệt, một chiều | [push-events.md](./push-events.md) |

## Nguyên tắc chung

1. **Đa tenant** — mọi lối vào giới hạn trong workspace của người gọi; chéo workspace trả *không tìm thấy*,
   không trả *không có quyền* (không rò rỉ sự tồn tại). Luật này đã chạy, phần mới phải theo.
2. **Trung lập adapter** — không lối vào nào nhận hay trả thứ gì đặc thù một loại runtime agent.
3. **Chặn thì nói rõ vì sao** — mỗi lần một cổng từ chối, câu trả lời nêu đúng điều còn thiếu (mã đầu việc
   chưa xong, trường nào trống…), và trạng thái giữ nguyên.
4. **Đẩy, không hỏi vòng** — mọi thay đổi trạng thái mà giao diện cần biết đều phát một sự kiện đẩy.
5. **Chuỗi hiển thị đi qua đa ngôn ngữ** — mặt giao tiếp trả mã lỗi và tham số, không trả câu tiếng Việt
   dựng sẵn.

## Mã lỗi dùng chung

| Mã | Khi nào |
|---|---|
| `404` | Không tìm thấy, **kể cả** khi tài nguyên tồn tại ở workspace khác |
| `409` | Vi phạm một cổng: chuyển trạng thái sai đường, còn việc phụ thuộc, chưa nộp thành phẩm, đã có người phụ trách, thiếu mô tả, chưa đủ hai chữ ký, dự án chưa ở giai đoạn cho phép |
| `422` | Dữ liệu vào sai: thiếu lý do bắt buộc, cạnh phụ thuộc khép vòng, khoá dự án sai khuôn |
| `403` | Sai vai: thợ báo cáo vượt cấp, Trưởng dự án tự duyệt kế hoạch của mình, Trưởng dự án đụng vào công tắc tự động công nhận của người chủ *(vế "người chủ này đổi công tắc của người chủ khác" hoãn cùng phần nhiều người chủ — chốt 2026-08-03)* |
