# 03 — Roster (vai trò/ghế) & mô hình đánh thức (wake)

> Cách một dự án định nghĩa vai trò và gán agent vào ghế, và cách Armarius **đánh thức** agent để làm việc.

---

## 1. Roster — vai trò và ghế của dự án

### 1.1 Luật roster lúc tạo dự án

`domain/services/project_rules.py::validate_plan` + `application/use_cases/projects.py::create_project`.
Một dự án sinh ra cùng roster của nó, và roster **phải**:

- có **đúng một** role Leader (`is_leader = True`), và role Leader **phải** đúng **1 ghế**;
- có **ít nhất một** role thợ (không-Leader) với `seats ≥ 1`;
- **mọi** role (leader lẫn thợ) phải có `description` **khác rỗng** — để prompt wake/leader-chat hiện được
  vai trò của mỗi agent + đồng đội (xem §3.1). Ép ở cả tầng API (schema `min_length=1`) lẫn tầng miền
  (`validate_plan`, kiểm sau thành phần leader/worker; `add_role` tự guard) (#112).

Vi phạm ⇒ `InvalidProjectPlan`. Dự án khởi tạo ở trạng thái `setup`.

### 1.2 Cấp ghế — chỉ hệ thống

`grant_seat` / `revoke_seat` mang cờ `system=True`; người gọi không-hệ-thống bị chặn
(`SystemOnlyOperation`). Agent **không tự ứng tuyển**, không có bước chấp nhận: `SeatGrant` sinh ra ở
trạng thái `granted` ngay khi hệ thống gán, lối ra duy nhất là `revoked`. Mỗi lần cấp/thu ghế đều
**tính lại điều kiện kích hoạt** dự án.

### 1.3 Kích hoạt dự án

`recompute_active`: `setup → active` **một lần**, khi **mọi ghế đã được cấp** VÀ **mọi agent ngồi ghế đều
ONLINE**. Một chiều — agent offline sau đó **không** kéo dự án active về lại setup.

### 1.4 Chuỗi suy ra vai-trò-dự-án

Đây là quan hệ mấu chốt:

```
SeatGrant (project_id, marius_id, role_key = "backend")
        │  role_key khớp 1-1 với Role.key
        ▼
Role (project_id, key="backend", title="Backend", description=..., seats, is_leader)
```

Muốn biết **vai trò của một agent trong một dự án**: tìm `SeatGrant` GRANTED của agent trong dự án → lấy
`role_key` → tra `Role` cùng key → đọc `title` + mô tả. `get_roster` (`projects.py`) làm đúng việc này cho
giao diện: dựng `RosterRoleView`/`SeatView` với `role.title`, `role.description` thật. Các prompt cấp dự án
**cũng** tra chuỗi này (xem §3), không đọc `Marius.role` (rỗng).

`RoleSpec`/`Role` mang **một** trường `description` duy nhất; `get_roster` trả `description`. Xem
[01-domain.md](01-domain.md) §3.2.

---

## 2. Mô hình đánh thức (wake)

`application/use_cases/wake_engine.py`. Đây là "trái tim" của Armarius.

### 2.1 Mọi wake đều gắn task

`WakeEngine.enqueue(*, marius_id, task_id, source, reason, continuation_attempt)` — **luôn** có `task_id`.
Không có wake cấp workspace, không có bộ đếm giờ toàn cục dò tìm. Task thuộc một dự án, nên **mọi wake đã
tự động nằm trong phạm vi một dự án**. Đây là căn cứ để khẳng định danh bạ trong prompt wake **phải** theo
dự án (xem §3.2).

### 2.2 Gộp trùng (coalescing) & phiên bền

- Trong tiến trình giữ bản đồ `(marius_id, task_id) → run đang chạy`. Một wake mới cho cặp đang chạy được
  **gộp** (`WakeupStatus.COALESCED`) vào run hiện có thay vì mở run thứ hai.
- Mỗi lần chạy mở/tiếp `AgentTaskSession` của `(marius, adapter, task)`; kết thúc thì lưu lại handle session
  để lần sau **resume** thay vì khởi động lạnh.
- Sự kiện adapter được **tee** vào cả nhật ký run bền (`RunEvent`, trừ `assistant.delta` chỉ stream) lẫn
  kênh sự kiện trực tiếp, và kênh `task:{id}` của phòng cộng tác.

### 2.3 Các nguồn wake (`WakeSource`)

`assignment`, `mention`, `comment`, `on_demand`, `continuation` (tự tiếp việc sau khi run rớt/còn dở),
`nudge`, `leader_chat`.

### 2.4 Chính sách tự-wake

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

## 3. Vai trò dự án trong prompt

Mọi prompt cấp dự án phải cho agent biết nó là ai trong dự án và ai là đồng đội — nếu không, Leader/agent
sẽ không biết năng lực của nhau. Vì thế:

### 3.1 Vai trò trong prompt

**Mọi prompt cấp dự án nêu hai thứ:**

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

"Mô tả vai trò" là **một** trường `Role.description` duy nhất (xem [01-domain.md](01-domain.md) §3.2).

### 3.2 Phạm vi danh bạ theo dự án

`wake_engine.py::_do_execute_run` dựng danh bạ qua `_project_directory(...)`: lấy **người giữ ghế của đúng
dự án của task** (`seat_grants.list_by_project` + `roles.list_by_project`), **không** liệt kê mọi agent
trong workspace. Agent trong workspace nhưng **không** giữ ghế dự án sẽ **không** xuất hiện trong danh bạ
prompt. Đúng bằng cách `leader_chat.py::_team` làm — hai luồng nhất quán.

Vì sao phạm vi phải theo dự án: không tồn tại wake cấp workspace; một danh bạ rộng hơn phạm vi dự án sẽ làm
rò rỉ agent của team khác vào ngữ cảnh một dự án, phá nguyên tắc đa-tenant / góc-nhìn-dự-án
([00-intent.md](00-intent.md) §7.5).

---

## 4. Tiêu chí nghiệm thu

1. Tạo dự án vi phạm luật roster (không có Leader / Leader nhiều ghế / thiếu thợ / **role thiếu mô tả**) ⇒
   `InvalidProjectPlan` (→ 422). — kiểm bởi `test_project_rules.py`, `test_project_service.py`.
2. Cấp/thu ghế bởi người-không-hệ-thống ⇒ `SystemOnlyOperation`.
3. Dự án `active` khi và chỉ khi mọi ghế đã cấp và mọi agent ngồi ghế ONLINE; không lùi về `setup`.
4. Wake luôn có `task_id`; wake trùng cặp `(marius, task)` bị gộp thành `COALESCED`.
5. Prompt wake task và prompt chat-với-Leader **đều** nêu vai trò dự án của agent nhận + mô tả, và liệt kê
   đồng đội kèm **title vai trò dự án thật** (không còn dấu `()` rỗng). — kiểm bởi `test_wake_prompt.py`,
   `test_leader_chat_prompt.py`.
6. Danh bạ trong prompt wake task **chỉ** gồm người giữ ghế của đúng dự án đó (không có agent workspace
   ngoài dự án). — kiểm bởi `test_integration_wake.py::test_wake_directory_is_project_scoped_with_project_roles`.
