# 06 — Kho hiện vật dùng chung & các kênh sự kiện đẩy (SSE)

> Cổng "Done" chống-file-ở-local, và cách trạng thái/sự kiện được **đẩy** về trình duyệt theo thời gian thực.

---

## 1. Kho hiện vật dùng chung

`application/use_cases/artifacts.py::ArtifactService` + cổng `application/ports/artifact_store.py`.

Đây là hiện thân của nguyên tắc bất biến "kết quả luôn nằm trong kho chung" ([00-intent.md](00-intent.md) §7.2).
Chỉ **hai** loại hiện vật (xem [01-domain.md](01-domain.md) §4.5):

- **`file`** — bytes thật đẩy vào bucket MinIO `armarius` qua `store.save_bytes(project_id, name, content)`;
  lưu lại `uri` (khoá bucket), `content_sha256`, `size_bytes`, và `stored = True`.
- **`link`** — một URL ngoài (ví dụ PR đã merge); yêu cầu `uri`, `stored = False`.

`publish` luôn gắn với **một task** (từ đó suy ra `project_id`). File thiếu `content`, hoặc link thiếu `uri`
⇒ lỗi `ValueError`.

## 2. Cổng "Done" — chống file ở máy agent

Đây là điểm chữa "căn bệnh" agent làm xong nhưng để kết quả ở máy nó. Cổng thực thi hai tầng:

- **Tầng miền** (`Task.transition_to`): vào `in_review`/`done` mà `has_artifact = False` ⇒ `ArtifactRequiredError`.
- **Tầng ứng dụng** (`TaskService.transition`): đếm hiện vật của task (`artifacts.count_by_task`) rồi truyền
  `has_artifact = count > 0`.

Nói cách khác: **một task không rời khỏi trạng thái đang-làm nếu chưa có ít nhất một hiện vật (file hoặc
link) trong kho chung.**

---

## 3. Các kênh sự kiện đẩy (SSE)

Nguyên tắc "đẩy, không hỏi-vòng" ([00-intent.md](00-intent.md) §7.4). Có **hai** cơ chế pub/sub trong tiến
trình (một tiến trình; chỗ để thay bằng Redis sau này là chính hai lớp này, endpoint giữ nguyên).
**Chỉ trình duyệt (web app) đọc SSE — agent không bao giờ đọc SSE.**

### 3.1 Bus theo chủ đề (topic) — `infrastructure/events/topic_bus.py::TopicEventBus`

Khoá theo chuỗi chủ đề. Mỗi sự kiện mang `seq` tăng đơn điệu (dùng làm `id` của SSE), mỗi chủ đề giữ một
vùng đệm phát lại có giới hạn để client nối lại từ `Last-Event-ID` (phát lại phần bỏ lỡ rồi bám đuôi trực
tiếp). Các chủ đề:

| Chủ đề | Dùng cho | Vòng đời |
|---|---|---|
| `ws:{workspace_id}` | mặt phẳng điều khiển workspace (sự kiện nhẹ, ví dụ `marius.status_changed`) | luôn bật |
| `task:{task_id}` | trace chạy của một task (tee các sự kiện lifecycle của run) | mở khi phòng cộng tác đang hiển thị |
| `leader-chat:{project_id}` | Chat với Leader (chạy chữ `assistant.delta`, `patron.message`, `leader.message`, `chat.state`) | khi mở chat |

Khi vượt trần số chủ đề, chỉ **thu hồi chủ đề không có người nghe** (LRU) — không bao giờ xoá vùng đệm của
một chủ đề đang có stream (giữ cửa sổ phát lại cho `Last-Event-ID`).

### 3.2 Bus theo run — `infrastructure/events/in_memory_bus.py::InMemoryEventBus`

Khoá theo `run_id`: dòng sự kiện trace **chi tiết** của một lần chạy cụ thể (kể cả từng mẩu `assistant.delta`).
Tự kết thúc khi gặp sự kiện chấm dứt `run.finished`.

### 3.3 Cơ chế "tee" hai ngả

Khi adapter chảy sự kiện về, WakeEngine ghi **đồng thời**:

- vào **nhật ký bền** (`RunEvent` trong cơ sở dữ liệu) — trừ `assistant.delta` chỉ chảy trực tiếp không lưu;
- lên **bus theo run** (§3.2) cho trace trực tiếp;
- và tee các sự kiện lifecycle (không phải từng token delta) lên **chủ đề `task:{task_id}`** (§3.1) cho phòng
  cộng tác — để 1000 token delta không làm ngập phòng.

Sự kiện điều khiển workspace (ví dụ mời agent xong) phát lên `ws:{workspace_id}`.

---

## 4. Tiêu chí nghiệm thu

1. `publish` loại `file` ⇒ bytes nằm trong bucket MinIO `armarius`, hiện vật có `sha256`/`size`/`stored=True`.
   Loại `link` ⇒ lưu `uri` ngoài, `stored=False`. Cả hai đều thoả cổng DONE.
2. Chuyển task sang `in_review`/`done` khi chưa có hiện vật nào ⇒ bị chặn; sau khi publish một hiện vật ⇒ cho qua.
3. Mở SSE `task:{task_id}` giữa một lần chạy ⇒ nhận các sự kiện lifecycle của run theo thời gian thực; nối lại
   với `Last-Event-ID` ⇒ nhận đúng phần bỏ lỡ, không trùng, không sót.
4. Chat với Leader chạy chữ trên `leader-chat:{project_id}`; agent **không** đọc bất kỳ kênh SSE nào.
