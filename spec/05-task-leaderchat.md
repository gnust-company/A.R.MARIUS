# 05 — Vòng đời task, thêm task tay, Chat với Leader & chế độ YOLO

> Cách một task đi qua vòng đời, cách Patron/Leader tạo việc, và cuộc trò chuyện cấp dự án với Leader (#82).
> Phản ánh code ngày 18/07/2026. FSM task đã tả ở [01-domain.md](01-domain.md) §5.2; file này tả **thao tác**.
>
> Nhãn: **[ĐÚNG-NHƯ-CODE]** / **[ĐÍCH-CẦN-SỬA]**.

---

## 1. Thao tác trên task  [ĐÚNG-NHƯ-CODE]

`application/use_cases/tasks.py::TaskService`.

| Thao tác | Hành vi |
|---|---|
| `create(...)` | Tạo task. Mặc định `backlog`. Đề xuất của Leader truyền `status=DRAFT` + `assigned_marius_id` gợi ý. Thêm-tay của Patron truyền đủ định nghĩa (priority/due_date/definition_of_done/assignee). |
| `assign(task, marius)` | Gán người phụ trách; nếu đang `backlog` → `todo`; **bắn wake `ASSIGNMENT`** cho người được gán. |
| `claim(task, marius)` | Agent tự nhận: gán mình + (nếu `backlog`/`todo`) → `in_progress`; **không** bắn wake (agent đang thức). |
| `transition(task, target, reason)` | Chuyển trạng thái có cổng: đếm hiện vật rồi `has_artifact = count > 0`; áp **cổng DONE**. |
| `approve_proposed(task)` | Duyệt một draft của Leader: `draft → todo`, rồi bắn wake `ASSIGNMENT` cho assignee (nếu có). |
| `reject_proposed(task)` | Từ chối draft: `draft → cancelled` (không wake). |
| `set_next_action(task, text)` | Ghi gợi ý tiếp việc bền. |

### 1.1 Một người phụ trách — [ĐÍCH-CẦN-SỬA]

Toàn bộ luồng thao tác **thực tế** chỉ dùng **`Task.assigned_marius_id`** (một người). Thực thể
`TaskParticipant` (nhiều người, một `is_primary`) tồn tại nhưng **không** được các thao tác trên dùng.
**Đích:** giữ một-người-phụ-trách, **gỡ** `TaskParticipant` ở Giai đoạn 2 (xem [01-domain.md](01-domain.md) §4.1).

### 1.2 Mã task `{KEY}-{seq}` — [ĐÚNG-NHƯ-CODE]

Mỗi task sinh mã `{project.key}-{seq}` ngay khi tạo: KEY là mã dự án (Patron đặt, có gợi ý, duy nhất
workspace, bất biến); seq là bộ đếm monotonic per-project, cấp phát **atomic** (`UPDATE … RETURNING`)
nên không trùng khi tạo-cùng-lúc và không bao giờ tái sử dụng. Ví dụ dự án "Calculator" (key `CALC`) →
`CALC-1`, `CALC-2`… Chi tiết ở [01-domain.md](01-domain.md) §3.1 (key + seq) + §4.1.

### 1.3 Cổng phụ thuộc — [ĐÚNG-NHƯ-CODE]

Cạnh `blocked_by` được **lưu bền** (bảng `task_dependencies`) và cổng phụ thuộc được thực thi
**đầu-cuối**. Mọi đường vào trạng thái bị chặn — `TaskService.transition`, `claim`, `approve_proposed`
(duyệt draft) — đều tính `deps_satisfied` từ cạnh **thật** (mọi task mà nó `blocked_by` đã `done` chưa)
rồi bơm vào `transition_to`; còn một `blocked_by` chưa `done` ⇒ không vào được `todo`/`in_progress`
(`DependencyNotMetError` → **409**). `assign` cũng tôn trọng cổng: task bị chặn thì **ở lại `backlog`**
thay vì bị đẩy lên `todo`. Quản cạnh qua API `POST`/`DELETE`/`GET` `.../dependencies`; cạnh
tự-trỏ-chính-mình, trùng cặp, khác dự án, hoặc tạo vòng lặp ⇒ **422**. Chi tiết miền:
[01-domain.md](01-domain.md) §4.1 + §4.4.

---

## 2. Hai cách tạo việc

### 2.1 Thêm task tay (Patron)  [ĐÚNG-NHƯ-CODE]

Patron tự điền đầy đủ định nghĩa task và tạo thẳng (thường vào `backlog`/`todo`, kèm assignee). Đây là hành
động của bảng công việc; nút "+" trên một cột đặt task vào đúng cột đó (create nhận `status`).

### 2.2 Nhờ Leader tạo (qua Chat với Leader)  [ĐÚNG-NHƯ-CODE]

Trong khi trò chuyện, Patron nhờ Leader tạo việc; Leader dùng công cụ tạo-task của nó. Kết quả **draft hay
live** tuỳ **chế độ YOLO của dự án** (§4).

---

## 3. Chat với Leader (#82)  [ĐÚNG-NHƯ-CODE]

`application/use_cases/leader_chat.py::LeaderChatService` + `domain/services/leader_chat_prompt.py`.
Cuộc trò chuyện 1-1 **cấp dự án** với Leader về *mọi thứ* trong dự án (định hướng, trạng thái, kế hoạch).

- **Phạm vi dự án, tối đa một cuộc/dự án.** `ProjectLeaderConversation` resume một session Leader riêng
  `armarius:project:{project_id}:leader` mỗi lượt.
- **Leader là agent ⇒ mỗi lượt bất đồng bộ.** Dịch vụ lái thẳng primitive streaming của adapter
  (`adapter.execute` + `on_event`), **tee** mọi sự kiện lên kênh `leader-chat:{project_id}`. Câu trả lời của
  Leader được **dựng lại từ các mẩu `assistant.delta`** (đúng thứ Patron thấy chạy chữ) rồi ghi vào
  `transcript` bền — **không** bắt agent gọi API để "nộp" câu trả lời.
- **Lượt lần lượt (turn-taking).** Tối đa một lượt đang chạy: khi đang chạy, cuộc trò chuyện ở `THINKING` và
  API **từ chối** tin mới bằng **409**; xong lượt về `IDLE` (hoặc `FAILED` để thử lại).
- **Offline ⇒ tắt hẳn chat, không xếp hàng.** "Leader offline" là thuộc tính **suy ra lúc đọc** từ liveness
  của Leader (`_AVAILABLE` = online/working/idle/checking), **không lưu**. Không có Leader ngồi ghế, hoặc
  Leader offline, hoặc đang bận ⇒ `LeaderChatError` → **409**.
- **Đây là bản thay thế cho Commission cũ.** Prompt cố ý **không** phải prompt wake-task chung (thứ bảo agent
  "cập nhật task, publish hiện vật" — vô nghĩa cho một cuộc trò chuyện), lý do khiến wake commission cũ thấy
  "bạc nhược".

> Ghi chú: danh bạ đội trong prompt chat này đúng phạm vi dự án **và** (sau issue #87) nêu **title vai trò
> dự án thật** của từng worker + mô tả, kèm mô tả vai trò của chính Leader ở header. Xem
> [03-roster-wake.md](03-roster-wake.md) §3.

---

## 4. Chế độ YOLO  [ĐÚNG-NHƯ-CODE]

`Project.settings["yolo_mode"]` (mặc định `False`). Bật/tắt qua `ProjectService.set_yolo_mode` (gộp đúng một
khoá, không đụng cài đặt khác). Ý nghĩa: **Leader toàn quyền hay phải xin Patron duyệt**.

- **YOLO BẬT** — Leader toàn quyền: task nó tạo trong Chat với Leader được tạo **sống + gán ngay**, worker
  được đánh thức tức thì. Không cần Patron duyệt.
- **YOLO TẮT** (mặc định) — có cổng duyệt: task Leader tạo là **`draft` chờ Patron duyệt**; chưa worker nào
  bị đánh thức. Patron `approve_proposed` (`draft → todo` + wake assignee) hoặc `reject_proposed`
  (`draft → cancelled`). Prompt nói rõ cho Leader biết nó đang ở chế độ nào và phải báo Patron rằng việc
  "đang chờ duyệt".

Prompt Leader luôn nêu trạng thái YOLO hiện tại để Leader hành xử đúng.

---

## 5. Commission cũ — [ĐÍCH-CẦN-SỬA] (gỡ ở Giai đoạn 2)

Còn tồn tại trong code: `CommissionSession` + `CommissionStatus` + `LeaderState` (thực thể),
`WakeSource.COMMISSION`, use case `commission.py`, và endpoint commission. Toàn bộ **đã bị
`ProjectLeaderConversation` (Chat với Leader) thay thế** về mặt sản phẩm: chat cấp dự án hấp thụ vai trò
"giao việc qua Leader" mà commission cũ đảm nhiệm.

**Đích:** **gỡ bỏ** commission (thực thể, use case, endpoint, nguồn wake) ở Giai đoạn 2. File đặc tả này
**không** mô tả commission như một tính năng sống.

---

## 6. Tiêu chí nghiệm thu

**Đúng-như-code:**

1. `assign` một task ⇒ người được gán nhận wake `ASSIGNMENT`; `claim` ⇒ **không** wake.
2. Chuyển sang `in_review`/`done` khi task **chưa** có hiện vật ⇒ bị chặn (cổng DONE).
6. Có cạnh `blocked_by` chưa `done` ⇒ vào `todo`/`in_progress` (kể cả qua `claim`/duyệt draft) bị chặn
   (cổng phụ thuộc, `DependencyNotMetError` → 409); blocker `done` xong ⇒ vào được.
3. Gửi tin cho Leader khi đang có lượt chạy ⇒ 409 (turn-taking); Leader offline ⇒ 409 (chat tắt).
4. Câu trả lời của Leader chạy chữ trên kênh `leader-chat:{project_id}` và được lưu vào transcript.
5. YOLO tắt: Leader tạo việc ⇒ `draft`, không wake ai; Patron duyệt ⇒ `todo` + wake assignee. YOLO bật:
   tạo việc ⇒ live + wake ngay.

**Đích Giai đoạn 2:** §1.1 (một người phụ trách, gỡ participant), §5 (gỡ commission).
