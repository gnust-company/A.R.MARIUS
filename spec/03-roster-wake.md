# 03 — Roster (vai trò/ghế) & mô hình đánh thức (wake)

> Cách một dự án định nghĩa vai trò và gán agent vào ghế, và cách Armarius **đánh thức** agent để làm việc.
> §3 từng chứa hai lỗi vi phạm nguyên tắc "góc nhìn dự án" ([00-intent.md](00-intent.md) §7.5) — **đã sửa ở
> issue #87**. Phản ánh code ngày 18/07/2026 (cập nhật sau #87).
>
> Nhãn: **[ĐÚNG-NHƯ-CODE]** / **[ĐÍCH-CẦN-SỬA]**.

---

## 1. Roster — vai trò và ghế của dự án

### 1.1 Luật roster lúc tạo dự án  [ĐÚNG-NHƯ-CODE]

`domain/services/project_rules.py::validate_plan` + `application/use_cases/projects.py::create_project`.
Một dự án sinh ra cùng roster của nó, và roster **phải**:

- có **đúng một** role Leader (`is_leader = True`), và role Leader **phải** đúng **1 ghế**;
- có **ít nhất một** role thợ (không-Leader) với `seats ≥ 1`.

Vi phạm ⇒ `InvalidProjectPlan`. Dự án khởi tạo ở trạng thái `setup`.

### 1.2 Cấp ghế — chỉ hệ thống  [ĐÚNG-NHƯ-CODE]

`grant_seat` / `revoke_seat` mang cờ `system=True`; người gọi không-hệ-thống bị chặn
(`SystemOnlyOperation`). Agent **không tự ứng tuyển**, không có bước chấp nhận: `SeatGrant` sinh ra ở
trạng thái `granted` ngay khi hệ thống gán, lối ra duy nhất là `revoked`. Mỗi lần cấp/thu ghế đều
**tính lại điều kiện kích hoạt** dự án.

### 1.3 Kích hoạt dự án  [ĐÚNG-NHƯ-CODE]

`recompute_active`: `setup → active` **một lần**, khi **mọi ghế đã được cấp** VÀ **mọi agent ngồi ghế đều
ONLINE**. Một chiều — agent offline sau đó **không** kéo dự án active về lại setup.

### 1.4 Chuỗi suy ra vai-trò-dự-án  [ĐÚNG-NHƯ-CODE]

Đây là quan hệ mấu chốt (và là thứ hai prompt ở §3 đang bỏ quên):

```
SeatGrant (project_id, marius_id, role_key = "backend")
        │  role_key khớp 1-1 với Role.key
        ▼
Role (project_id, key="backend", title="Backend", description=..., seats, is_leader)
```

Muốn biết **vai trò của một agent trong một dự án**: tìm `SeatGrant` GRANTED của agent trong dự án → lấy
`role_key` → tra `Role` cùng key → đọc `title` + mô tả. `get_roster` (`projects.py`) **đã** làm đúng việc
này cho giao diện: nó dựng `RosterRoleView`/`SeatView` với `role.title`, `role.description` thật. **Chỉ các
prompt (§3) là quên tra chuỗi này** và đọc nhầm `Marius.role` (rỗng).

> **[ĐÍCH-CẦN-SỬA] gộp mô tả vai trò:** `RoleSpec`/`Role` hiện mang **hai** trường `description` +
> `responsibilities`; `get_roster` chỉ trả `description`, bỏ `responsibilities`. Đích: gộp một trường
> "mô tả vai trò" duy nhất (xem [01-domain.md](01-domain.md) §3.2), Giai đoạn 2.

---

## 2. Mô hình đánh thức (wake)  [ĐÚNG-NHƯ-CODE]

`application/use_cases/wake_engine.py`. Đây là "trái tim" của Armarius.

### 2.1 Mọi wake đều gắn task

`WakeEngine.enqueue(*, marius_id, task_id, source, reason, continuation_attempt)` — **luôn** có `task_id`.
Không có wake cấp workspace, không có bộ đếm giờ toàn cục dò tìm. Task thuộc một dự án, nên **mọi wake đã
tự động nằm trong phạm vi một dự án**. Đây là căn cứ để khẳng định danh bạ trong prompt wake **phải** theo
dự án (xem §3.2).

### 2.2 Gộp trùng (coalescing) & phiên bền  [ĐÚNG-NHƯ-CODE]

- Trong tiến trình giữ bản đồ `(marius_id, task_id) → run đang chạy`. Một wake mới cho cặp đang chạy được
  **gộp** (`WakeupStatus.COALESCED`) vào run hiện có thay vì mở run thứ hai.
- Mỗi lần chạy mở/tiếp `AgentTaskSession` của `(marius, adapter, task)`; kết thúc thì lưu lại handle session
  để lần sau **resume** thay vì khởi động lạnh.
- Sự kiện adapter được **tee** vào cả nhật ký run bền (`RunEvent`, trừ `assistant.delta` chỉ stream) lẫn
  kênh sự kiện trực tiếp, và kênh `task:{id}` của phòng cộng tác.

### 2.3 Các nguồn wake (`WakeSource`)  [ĐÚNG-NHƯ-CODE]

`assignment`, `mention`, `comment`, `on_demand`, `continuation` (tự tiếp việc sau khi run rớt/còn dở),
`nudge`, `commission` (**sắp gỡ** — xem [05-task-leaderchat.md](05-task-leaderchat.md)), `leader_chat`.

### 2.4 Chính sách tự-wake  [ĐÚNG-NHƯ-CODE]

`domain/services/wake_policy.py::decide_self_wake` — hàm thuần theo bảng (trạng thái task × kết quả run).
Quy tắc dẫn dắt: **chỉ wake khi "bóng đang ở sân của agent"**; khi người khác nợ nước đi kế, im lặng chờ
sự kiện của họ. Tóm tắt:

| Trạng thái task | Kết quả run | Quyết định |
|---|---|---|
| terminal (done/cancelled) | — | không wake |
| in_review | — | không wake (chờ người duyệt) |
| todo | — | không wake (sự kiện assignment đã wake) |
| blocked/backlog **có** lý do | — | không wake (chờ gỡ) |
| blocked/backlog **không** lý do | — | nudge một lần; hết ngân sách ⇒ báo người |
| in_progress | run rớt/timeout | continuation (tiếp session), tối đa N lần |
| in_progress | completed + còn `next_action` | continuation |
| in_progress | completed, không ghi gì | nudge; hết ngân sách ⇒ báo người |

---

## 3. Vai trò dự án trong prompt (đã sửa — issue #87)

Đây là mối lo gốc của chủ dự án: "Leader chat nhắc đồng đội chỉ bằng **tên** với vai trò để trống — nên
Leader/agent không biết năng lực của nhau trong dự án". Đã sửa ở issue #87; mục này giờ mô tả hành vi đúng.

### 3.1 Vai trò trong prompt  [ĐÚNG-NHƯ-CODE]

**Mọi prompt cấp dự án phải nêu hai thứ, và nay đã nêu:**

1. **Vai trò của chính agent nhận prompt** trong dự án + mô tả (tra `SeatGrant` của agent → `Role`).
2. **Danh bạ đồng đội theo vai trò dự án**: mỗi người kèm `title` vai trò thật (tra `g.role_key` → `Role`),
   **không** đọc `Marius.role` (rỗng).

**Prompt wake task** (`wake_prompt.py::build_wake_prompt` + `wake_engine.py::_wake_context`):

- Dòng đầu khi agent có ghế: *"You are {name}, the {vai-trò} on this project inside Armarius."* kèm mô tả
  vai trò; nếu agent không giữ ghế nào thì lùi về câu chung *"an agent collaborating inside Armarius."*.
- Danh bạ: `DirectoryEntry.role` mang **title vai trò dự án** (tra từ ghế), kèm `role_description` tuỳ chọn.

**Prompt chat với Leader** (`leader_chat_prompt.py` + `leader_chat.py::_team`):

- `_team` tra `g.role_key → Role` cho từng worker ⇒ `ChatDirectoryEntry.role` là **title vai trò dự án**
  (lùi về chính `role_key` nếu thiếu Role, **không bao giờ để trống**), kèm `role_description`.
- Header thêm mô tả vai trò của chính Leader (`leader_role_description`).

> Ghi chú: hiện dùng `Role.description` sẵn có làm "mô tả vai trò". Việc **gộp** `description` +
> `responsibilities` thành một trường vẫn là đích [ĐÍCH-CẦN-SỬA] riêng (xem [01-domain.md](01-domain.md) §3.2).

### 3.2 Phạm vi danh bạ theo dự án  [ĐÚNG-NHƯ-CODE]

`wake_engine.py::_do_execute_run` nay dựng danh bạ qua `_project_directory(...)`: lấy **người giữ ghế của
đúng dự án của task** (`seat_grants.list_by_project` + `roles.list_by_project`), **không** còn liệt kê mọi
agent trong workspace. Agent trong workspace nhưng **không** giữ ghế dự án sẽ **không** xuất hiện trong danh
bạ prompt. Đúng bằng cách `leader_chat.py::_team` vốn đã làm — hai luồng nay nhất quán.

> Vì sao đây từng là lỗi chứ không phải "lựa chọn thiết kế": không tồn tại wake cấp workspace; danh bạ rộng
> hơn phạm vi dự án làm rò rỉ agent của team khác vào ngữ cảnh một dự án, phá nguyên tắc đa-tenant/góc-nhìn-dự-án.

---

## 4. Tiêu chí nghiệm thu  [ĐÚNG-NHƯ-CODE]

1. Tạo dự án vi phạm luật roster (không có Leader / Leader nhiều ghế / thiếu thợ) ⇒ `InvalidProjectPlan`.
2. Cấp/thu ghế bởi người-không-hệ-thống ⇒ `SystemOnlyOperation`.
3. Dự án `active` khi và chỉ khi mọi ghế đã cấp và mọi agent ngồi ghế ONLINE; không lùi về `setup`.
4. Wake luôn có `task_id`; wake trùng cặp `(marius, task)` bị gộp thành `COALESCED`.
5. Prompt wake task và prompt chat-với-Leader **đều** nêu vai trò dự án của agent nhận + mô tả, và liệt kê
   đồng đội kèm **title vai trò dự án thật** (không còn dấu `()` rỗng). — kiểm bởi `test_wake_prompt.py`,
   `test_leader_chat_prompt.py`.
6. Danh bạ trong prompt wake task **chỉ** gồm người giữ ghế của đúng dự án đó (không còn agent workspace
   ngoài dự án). — kiểm bởi `test_integration_wake.py::test_wake_directory_is_project_scoped_with_project_roles`.
