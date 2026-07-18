# 03 — Roster (vai trò/ghế) & mô hình đánh thức (wake)

> Cách một dự án định nghĩa vai trò và gán agent vào ghế, và cách Armarius **đánh thức** agent để làm việc.
> Đây là file chứa **hai lỗi thiết kế** quan trọng nhất đang chờ sửa — cả hai đều vi phạm nguyên tắc
> "góc nhìn dự án" ([00-intent.md](00-intent.md) §7.5). Phản ánh code ngày 18/07/2026.
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

## 3. Hai lỗi prompt đang chờ sửa

Cả hai prompt gửi tới agent hiện **không** truyền đúng ngữ cảnh vai-trò-dự-án. Đây là mối lo gốc của chủ
dự án: "Leader chat nhắc đồng đội chỉ bằng **tên** với vai trò để trống — nên Leader/agent không biết năng
lực của nhau trong dự án".

### 3.1 Lỗi vai trò — [ĐÍCH-CẦN-SỬA] (Giai đoạn 2)

**Prompt wake task** (`wake_prompt.py::build_wake_prompt` + `wake_engine.py::_wake_context`):

- Dòng đầu: *"You are {name}, an agent collaborating inside Armarius."* — **không** nói agent này giữ vai
  trò gì trong dự án, không kèm mô tả.
- Danh bạ: `DirectoryEntry(role=m.role, ...)` với `m.role` là **vai trò workspace (rỗng)** → in ra
  `@con2 () [online]`.

**Prompt chat với Leader** (`leader_chat_prompt.py` + `leader_chat.py::_team`):

- Danh bạ đội: `ChatDirectoryEntry(role=worker.role, ...)` — lại đọc `worker.role` **rỗng** →
  `- con2 () [online] — marius_id: ...`. (Header thì có "the Leader of this project" nhưng không kèm mô tả
  vai trò Leader.)

**Đích cho MỌI prompt cấp dự án:** phải nêu

1. **Vai trò của chính agent nhận prompt** trong dự án + mô tả (tra `SeatGrant` của agent → `Role`).
2. **Danh bạ đồng đội theo vai trò dự án**: mỗi người kèm `title` vai trò thật (tra `g.role_key` → `Role`),
   không đọc `Marius.role`.

### 3.2 Lỗi phạm vi danh bạ (D) — [ĐÍCH-CẦN-SỬA] (Giai đoạn 2)

Chỉ ở **luồng wake task**. `wake_engine.py::_do_execute_run` dựng danh bạ bằng:

```python
directory = list(await uow.mariuses.list_by_workspace(marius.workspace_id))   # ← workspace-scoped
```

Tức là liệt kê **mọi agent trong workspace**, kể cả agent **không** thuộc dự án của task. Điều này **sai
thiết kế**: theo mô hình, cộng tác/@mention chỉ trong phạm vi **người tham gia dự án** (participant), và —
như §2.1 đã lập luận — mọi wake vốn đã gắn một task thuộc một dự án, nên **không có** sự kiện wake nào ở cấp
workspace để biện minh cho danh bạ cấp workspace.

**Đích:** danh bạ prompt wake là **những người giữ ghế của đúng dự án đó** (`seat_grants.list_by_project`),
giống hệt cách `leader_chat.py::_team` đã làm. Nói cách khác, luồng chat-với-Leader **đã** đúng phạm vi dự
án; chỉ luồng wake task còn theo workspace và phải sửa cho khớp.

> Vì sao đây là lỗi chứ không phải "lựa chọn thiết kế": không tồn tại wake cấp workspace; danh bạ rộng hơn
> phạm vi dự án làm rò rỉ agent của team khác vào ngữ cảnh một dự án, phá nguyên tắc đa-tenant/góc-nhìn-dự-án.

---

## 4. Tiêu chí nghiệm thu

**Phần đúng-như-code (không sửa):**

1. Tạo dự án vi phạm luật roster (không có Leader / Leader nhiều ghế / thiếu thợ) ⇒ `InvalidProjectPlan`.
2. Cấp/thu ghế bởi người-không-hệ-thống ⇒ `SystemOnlyOperation`.
3. Dự án `active` khi và chỉ khi mọi ghế đã cấp và mọi agent ngồi ghế ONLINE; không lùi về `setup`.
4. Wake luôn có `task_id`; wake trùng cặp `(marius, task)` bị gộp thành `COALESCED`.

**Phần đích Giai đoạn 2 (khi sửa xong thì đạt):**

5. Prompt wake task và prompt chat-với-Leader **đều** nêu vai trò dự án của agent nhận + mô tả, và liệt kê
   đồng đội kèm **title vai trò dự án thật** (không còn dấu `()` rỗng).
6. Danh bạ trong prompt wake task **chỉ** gồm người giữ ghế của đúng dự án đó (không còn agent workspace
   ngoài dự án).
