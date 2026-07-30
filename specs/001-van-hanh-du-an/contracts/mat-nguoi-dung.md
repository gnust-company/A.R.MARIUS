# Mặt người dùng (`/v1`)

Trình duyệt của người chủ gọi. Ký hiệu: **[có]** · **[sửa]** · **[mới]**.

## 1. Dự án và giai đoạn

| Lối vào | Trạng thái | Ý nghĩa |
|---|---|---|
| `GET /v1/projects/{id}` | **[sửa]** | Trả thêm giai đoạn (một trong năm), Bối cảnh đã duyệt, bản kế hoạch hiện hành và trạng thái duyệt của nó |
| `POST /v1/projects/{id}/phase` | **[mới]** | Người chủ quyết chuyển giai đoạn. Thân: giai đoạn đích, lý do. `409` nếu đường chuyển không hợp lệ; `403` nếu người gọi không phải người chủ. Công tắc tự động công nhận **không** thay thế lối vào này |
| `GET /v1/projects/{id}/thresholds` · `PUT` | **[mới]** | Đọc/ghi bộ ngưỡng thời gian của dự án. Thiếu trường nào thì lấy mặc định hệ thống |

**Cổng**: dự án chưa ở *vận hành* hoặc *bảo trì* thì mọi lối vào tạo hoặc giao đầu việc thật trả `409` kèm
lý do "kế hoạch chưa được duyệt" (FR-003).

## 2. Bối cảnh dự án **[mới]**

| Lối vào | Ý nghĩa |
|---|---|
| `GET /v1/projects/{id}/context` | Bản đã duyệt, kèm bản chờ duyệt nếu có |
| `POST /v1/projects/{id}/context/approve` | Người chủ duyệt. Thân: có duyệt không, góp ý nếu không |

Sửa Bối cảnh theo hướng đổi mục tiêu hoặc phạm vi luôn tạo một bản *chờ duyệt*, không ghi đè bản đang hiệu
lực (FR-010).

## 3. Kế hoạch và cổng duyệt **[mới]**

| Lối vào | Ý nghĩa |
|---|---|
| `GET /v1/projects/{id}/plan` | Bản kế hoạch hiện hành: danh sách hạng mục, rủi ro, mốc, trạng thái |
| `POST /v1/projects/{id}/plan/decision` | Ba lựa chọn của người chủ (FR-013): `duyet` · `yeu_cau_chinh` (kèm góp ý) · `hoi_lai` (kèm câu hỏi) |

- `duyet` → dự án sang *vận hành*, ghi vết mốc duyệt, đánh thức Trưởng dự án với việc kế tiếp "chẻ đầu việc
  và giao thợ".
- `yeu_cau_chinh` → đánh thức Trưởng dự án kèm góp ý, dự án ở lại *lập kế hoạch*.
- Trưởng dự án gọi lối vào này → `403` (FR-014).

## 4. Công nhận đầu ra **[mới]**

| Lối vào | Ý nghĩa |
|---|---|
| `POST /v1/tasks/{id}/approval` | Một chữ ký. Thân: tán thành hay từ chối, lý do (bắt buộc khi từ chối) |

- Người gọi phải là **người chủ chịu trách nhiệm** của đầu việc (suy từ ghế của người phụ trách), nếu không
  thì `403`.
- Đầu việc không ở *chờ rà soát*, hoặc Trưởng dự án chưa ký → `409`.
- Từ chối → đầu việc về *đang làm*, việc kế tiếp đặt thành "sửa theo phản hồi", đánh thức đúng thợ cũ.
- Đủ hai chữ ký tán thành → *xong*, mở khoá việc phụ thuộc, đánh thức Trưởng dự án.

| Lối vào | Ý nghĩa |
|---|---|
| `GET /v1/projects/{id}/auto-approval` · `PUT` | Công tắc tự động công nhận của **chính người gọi** trong dự án đó. Đổi của người khác → `403` (FR-038). Mọi lần đổi ghi vết |

## 5. Hộp thư người chủ **[sửa]**

Hiện giao diện tự lọc đầu việc phía trình duyệt. Thay bằng một mặt giao tiếp thật.

| Lối vào | Ý nghĩa |
|---|---|
| `GET /v1/inbox` | Các mục đang chờ **người gọi**, theo loại và mức khẩn. Có lọc theo dự án |
| `POST /v1/inbox/{item_id}/resolve` | Đánh dấu đã giải quyết (thường do chính hành động duyệt/công nhận gọi ngầm) |

Mỗi mục mang: loại, dự án, đầu việc liên quan (có thể rỗng), bậc nhắc đã gửi, mốc tạo. Mục *cảnh báo leo
thang* mang thêm **hồ sơ đã thử** — Mức 1 làm gì mấy lần, Mức 2 quyết gì, và chính xác điều cần người chủ
quyết (FR-061).

## 6. Đầu việc **[sửa]**

Giữ nguyên các lối vào đang có, siết hành vi:

| Lối vào | Thay đổi |
|---|---|
| `POST /v1/projects/{id}/tasks` | Thêm trường hạng mục kế hoạch. Không có hạng mục → đầu việc sinh ra ở *nháp/đề xuất* (FR-027) |
| `POST /v1/tasks/{id}/status` | Bảng chuyển siết lại: bỏ *đang làm → xong*; *xong* và *huỷ* không rời được bằng lối vào này |
| `POST /v1/tasks/{id}/reopen` | **[mới]** — đường duy nhất mở lại một đầu việc đã đóng, bắt buộc lý do, ghi vết |
| `GET /v1/tasks/{id}` | Trả thêm: động cơ đẩy, cờ đình trệ, các chữ ký đã có, hạng mục kế hoạch |
| `GET /v1/tasks/{id}/log` | **[mới]** — nhật ký thay đổi của đầu việc theo dòng thời gian |
| `GET /v1/tasks/{id}/criteria` · `PUT` | **[mới]** — danh sách tiêu chí công nhận. Sửa sau khi thợ bắt tay là một thay đổi lớn → treo chờ duyệt |
