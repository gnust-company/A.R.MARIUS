# 01 — Mô hình miền (thực thể + máy trạng thái)

> Ghi lại **các thực thể nghiệp vụ** của Armarius và **các máy trạng thái** (state machine) của
> chúng, đúng như mã nguồn ngày 18/07/2026. Tầng miền (`backend/armarius/domain/`) là mã **thuần**:
> chỉ dữ liệu và luật chuyển trạng thái, **không** đụng cơ sở dữ liệu, mạng hay adapter — phần I/O do
> tầng ứng dụng (`application/`) bơm vào.
>
> Nhãn dùng trong file này: **[ĐÚNG-NHƯ-CODE]** = spec chép đúng code; **[ĐÍCH-CẦN-SỬA]** = code
> hiện làm khác, spec ghi đích đúng, sửa ở Giai đoạn 2.

---

## 1. Bản đồ thực thể

```
Workspace (không gian dùng chung, thuộc một Patron)
│
├── Marius (agent)                 — danh tính agent + cấu hình adapter + token
├── Skill (kho kỹ năng)            — năng lực cài được cho agent
├── Label (nhãn task)              — tag phạm vi workspace
├── workspace_agent_id ───────────► trỏ tới một Marius làm "quản gia" onboarding
│
└── Project (dự án)                — một sáng kiến độc lập
    ├── Role (vai trò/ghế)         — định nghĩa ghế: key, title, seats, is_leader
    ├── SeatGrant (cấp ghế)        — gán một Marius vào một role_key
    ├── Task (công việc)           — đơn vị việc, kiêm phòng cộng tác
    │   ├── Comment (tin nhắn thread)
    │   ├── ChecklistItem (ô tick)
    │   ├── TaskDependency (cạnh blocked_by)
    │   └── Artifact (hiện vật đầu ra)   — file trong MinIO hoặc link ngoài
    ├── Artifact (kho hiện vật dự án)
    ├── Run + RunEvent (một lần chạy + luồng sự kiện trace)
    ├── AgentTaskSession (phiên bền: (Marius, task) ↔ session runtime)
    ├── WakeupRequest (yêu cầu đánh thức, luôn gắn task)
    └── ProjectLeaderConversation (chat 1-1 với Leader, #82)
```

Các thực thể **cấp workspace**: `Workspace`, `Marius`, `Skill`, `Label`, `User` (Patron), `OnboardingSession`.
Các thực thể **cấp dự án**: mọi thứ dưới `Project`.

---

## 2. Nhóm danh tính & không gian

### 2.1 Workspace — `entities/workspace.py`  [ĐÚNG-NHƯ-CODE]

Không gian làm việc dùng chung, thuộc **một** Patron (`owner_user_id`). Có `name`, `slug`, và
`workspace_agent_id` — con trỏ (khoá ngoại) tới một `Marius` được chỉ định làm **quản gia onboarding**.

### 2.2 User (Patron) — `entities/user.py`  [ĐÚNG-NHƯ-CODE]

Người dùng con người. `role` ∈ {`patron`, `member`, `admin`}. Trong sản phẩm này người chủ workspace là
**Patron**. Mật khẩu băm ở tầng service.

### 2.3 Marius (agent) — `entities/marius.py`

Danh tính một agent, gắn với một adapter runtime. Các trường chính:

| Trường | Ý nghĩa | Nhãn |
|---|---|---|
| `adapter_type` | loại adapter (mặc định `hermes_gateway`) | [ĐÚNG-NHƯ-CODE] |
| `adapter_config` | thông tin kết nối gateway (`base_url` + `api_key`), lấy từ operator lúc mời | [ĐÚNG-NHƯ-CODE] |
| `agent_token` | bearer để agent gọi ngược vào API của Armarius; đúc **lúc mời** | [ĐÚNG-NHƯ-CODE] |
| `skills`, `skill_ids` | kỹ năng agent có / id kỹ năng liên kết từ kho | [ĐÚNG-NHƯ-CODE] |
| `invite_status` | FSM mời (xem §5.1) | [ĐÚNG-NHƯ-CODE] |
| `liveness`, `last_seen_at`, `probe_attempts`, `backoff_step`, `next_probe_at`, `offline_since` | sổ sách sống/chết (xem [04-liveness.md](04-liveness.md)) | [ĐÚNG-NHƯ-CODE] |
| `role` | vai trò **cấp workspace** — chuỗi tự do, **thường rỗng**; dấu tích, prompt không còn đọc (issue #87) | [ĐÚNG-NHƯ-CODE] |

**Điểm quan trọng — hai khái niệm "vai trò" khác nhau:**

- `Marius.role` là **vai trò cấp workspace**: một chuỗi ghi lúc mời, phần lớn để rỗng.
- Vai trò **thật sự trong dự án** không nằm ở đây, mà suy ra từ `SeatGrant.role_key` → `Role` (xem
  [03-roster-wake.md](03-roster-wake.md)).

Đây từng là gốc của lỗi "Leader không biết vai trò đồng đội": các prompt đọc `Marius.role` (rỗng) thay vì
tra vai trò dự án. **Đã sửa ở issue #87** — mọi prompt cấp dự án nay tra vai trò dự án (`SeatGrant.role_key
→ Role`); `Marius.role` còn lại chỉ là trường workspace **không dùng tới** (dấu tích), không còn bị đọc
nhầm. Chi tiết: [03-roster-wake.md](03-roster-wake.md) §3.

### 2.4 Skill — `entities/skill.py`  [ĐÚNG-NHƯ-CODE]

Năng lực cài được, tác giả trong "Skill Shop" của workspace. Gốc cây là `SKILL.md`; `files` là bản đồ
đường-dẫn → nội-dung. `source` ∈ {`builtin`, `manual`, `imported`}. `source_url` là nơi quảng bá cho
agent trong lời mời; `absolute_source_url()` ghép với base URL công khai khi là đường dẫn tương đối.

### 2.5 Label — `entities/label.py`  [ĐÚNG-NHƯ-CODE]

Tag phạm vi workspace, gắn lên task. Có `name` và `color` (mã hex).

---

## 3. Nhóm dự án & roster

### 3.1 Project — `entities/project.py`

Một sáng kiến độc lập trong workspace; sở hữu roster, task và một thư mục hiện vật dùng chung.

- **Vòng đời** (`ProjectStatus`): `setup → active → archived`. Đạt `active` **một lần** (khi mọi ghế đã
  cấp VÀ mọi agent ngồi ghế đều ONLINE) và không lùi lại. [ĐÚNG-NHƯ-CODE]
- **`settings`** (Patron chỉnh được), mặc định thận trọng:
  - `require_review_before_done = True`
  - `require_approval_for_done = False`
  - `comment_required_for_review = False`
  - `yolo_mode = False` — chế độ YOLO (#82): `False` ⇒ task Leader đề xuất là `draft` chờ Patron duyệt;
    `True` ⇒ Leader tạo + gán task được **tự duyệt**, không cần xin phép. [ĐÚNG-NHƯ-CODE] (hành vi chi
    tiết ở [05-task-leaderchat.md](05-task-leaderchat.md))
- **Bối cảnh brief** (Patron cung cấp, tuỳ chọn): `objective`, `success_metrics`, `target_date`,
  `github_url`, `context`. [ĐÚNG-NHƯ-CODE]
- **`key`** — mã dự án ngắn kiểu JIRA (2–10 ký tự hoa `[A-Z][A-Z0-9]{1,9}`, bắt đầu bằng chữ),
  **duy nhất theo workspace**, **bất biến** sau khi đặt. Làm phần "KEY" trong mã task `{key}-{seq}`.
  Patron đặt lúc tạo (FE tự gợi ý từ tên); bỏ trống ⇒ hệ thống suy từ tên + tự uniquify (đuôi số);
  trùng ⇒ `DuplicateProjectKey` (409); sai format ⇒ `InvalidProjectKey` (422). [ĐÚNG-NHƯ-CODE]
- **`next_task_seq`** — bộ đếm monotonic per-project; `ProjectRepository.allocate_task_number` cấp
  phát **atomic** bằng `UPDATE … RETURNING` khi tạo task, nên số không bao giờ trùng (tạo-cùng-lúc)
  và không bao giờ tái sử dụng. [ĐÚNG-NHƯ-CODE]

### 3.2 Role — `entities/role.py`

Định nghĩa một **ghế** trong roster của dự án.

| Trường | Ý nghĩa |
|---|---|
| `key` | slug ổn định, ví dụ `backend`, `leader` |
| `title` | nhãn người đọc, ví dụ "Backend" |
| `seats` | số ghế; role Leader **luôn** `seats == 1` |
| `is_leader` | đúng một role/dự án là Leader |
| `skill_ids` | kỹ năng role này mang (tuỳ chọn) |

**Mô tả vai trò — [ĐÚNG-NHƯ-CODE]:** Role có **một** trường `description` duy nhất — "mô tả vai trò" —
dùng cho **mọi** role, kể cả Leader. Trường cũ `responsibilities` (từng ghi "nhiệm vụ riêng của Leader",
thực chất là mã chết: không khung nhìn hay prompt nào đọc) đã **gỡ bỏ** ở #93; khi nâng cấp CSDL, chữ
trong `responsibilities` được dồn sang `description` nếu `description` còn trống. `description` **được
nhắc trong prompt** gửi tới agent giữ role đó (dòng self-role) và trong danh bạ đồng đội (xem
[03-roster-wake.md](03-roster-wake.md) §3.1). Màn tạo dự án cho Patron nhập `description` cho cả worker
lẫn Leader.

Luật: đúng một role là Leader, và role Leader luôn 1 ghế — kiểm ở `domain/services/project_rules.py`.

### 3.3 SeatGrant — `entities/seat_grant.py`  [ĐÚNG-NHƯ-CODE]

Gán một `Marius` vào một `role_key` của dự án. Đây là mã **hệ-thống-cấp**: agent không tự ứng tuyển,
không có bước chấp nhận. Trạng thái: `granted` (ngay khi Patron gán) → `revoked` (lối ra duy nhất;
revoke lần hai là lỗi). `role_key` khớp 1-1 với `Role.key`; ghế Leader mang `role_key = "leader"`.

**Đây là cầu nối vai-trò-dự-án:** để biết vai trò của một agent trong một dự án, tra `SeatGrant` của agent
đó trong dự án → lấy `role_key` → tra `Role` cùng key → đọc `title` + mô tả.

---

## 4. Nhóm công việc & cộng tác

### 4.1 Task — `entities/task.py`

Đơn vị công việc, **kiêm** phòng cộng tác. FSM ở §5.2. Các trường đáng chú ý:

| Trường | Ý nghĩa | Nhãn |
|---|---|---|
| `status`, `priority` | trạng thái + độ ưu tiên | [ĐÚNG-NHƯ-CODE] |
| `next_action` | gợi ý tiếp tục bền — agent định làm gì kế tiếp (resume từ trạng thái task, không từ session) | [ĐÚNG-NHƯ-CODE] |
| `parent_id` | task con của task khác | [ĐÚNG-NHƯ-CODE] |
| `definition_of_done` | mô tả "thế nào là xong" | [ĐÚNG-NHƯ-CODE] |
| `assigned_marius_id` | **người phụ trách duy nhất** của task | [ĐÚNG-NHƯ-CODE] |
| `identifier` | mã task người-đọc `{project.key}-{seq}`, ví dụ `CALC-7` | [ĐÚNG-NHƯ-CODE] |

**Một người phụ trách — [ĐÚNG-NHƯ-CODE]:** mỗi task có **đúng một người phụ trách**, biểu diễn bằng
`assigned_marius_id` — đây là **nguồn sự thật duy nhất** cho mọi luồng (gán, tự-nhận, đánh thức). Thực thể
`TaskParticipant` (mô hình nhiều-người song song, một người `is_primary`) **đã được gỡ sạch ở issue #101
(GĐ-2)**; nó vốn là mã chết mồ côi — không có bảng CSDL, không kho/mapper, không nơi nào dùng — nên **không
cần di trú** khi gỡ. Frontend cũng gỡ danh sách "người tham gia" (luôn rỗng) và nối các chỗ hiển thị vào đúng
một người phụ trách.

**Mã task — [ĐÚNG-NHƯ-CODE]:** `Task.identifier` = `{project.key}-{seq}`, sinh ở `TaskService.create`:

- **KEY** là `Project.key` (xem §3.1) — mã dự án ngắn, Patron đặt (có gợi ý), duy nhất workspace, bất biến.
- **`seq`** cấp phát từ `Project.next_task_seq` bằng `allocate_task_number` (`UPDATE … RETURNING`):
  **atomic** (hai tạo-cùng-lúc không bao giờ cùng số) và **không bao giờ tái sử dụng**.

Đây là thiết kế JIRA-style (thay cho auto-suy tiền tố + `max+1` từng xét: `max+1` không atomic nên tạo-cùng-lúc
trùng được, và key tự-suy không duy nhất giữa các dự án cùng tên). Cột `tasks.identifier` persist mã qua tải lại.

Hai **cổng** miền được thực thi thuần trong `transition_to()` (tầng ứng dụng bơm `has_artifact` /
`deps_satisfied`): [ĐÚNG-NHƯ-CODE]

- **Cổng DONE:** không thể vào `in_review`/`done` nếu chưa có hiện vật đã publish. → `ArtifactRequiredError`.
- **Cổng phụ thuộc:** không thể vào `todo`/`in_progress` khi còn một `blocked_by` chưa `done`. → `DependencyNotMetError`. Tầng ứng dụng tính `deps_satisfied` từ cạnh **bền** (§4.4) ở mọi đường vào trạng thái bị chặn (`transition`, `claim`, duyệt draft).

### 4.2 Comment — `entities/comment.py`  [ĐÚNG-NHƯ-CODE]

Tin nhắn trong thread của task. `author_kind` ∈ {`human`, `agent`, `system`}. `mentions` chứa danh sách
`marius_id` **cần được đánh thức** khi bị nhắc tên (nguồn wake `MENTION`).

### 4.3 ChecklistItem — `entities/checklist_item.py`  [ĐÚNG-NHƯ-CODE]

Một ô tick trên task: `text`, `done`, `order`.

### 4.4 TaskDependency — `entities/task_dependency.py`  [ĐÚNG-NHƯ-CODE]

Cạnh `blocked_by`: `task_id` (bị chặn) chờ `blocks_task_id`. Cấm tự-trỏ-chính-mình (`__post_init__`
ném `TaskDependencyError`). Lưu bền ở bảng `task_dependencies` (duy nhất theo cặp `(task_id,
blocks_task_id)`); repository liệt kê blocker của một task và trả lời "mọi blocker đã `done` chưa" để
nuôi cổng phụ thuộc ở §4.1.

### 4.5 Artifact — `entities/artifact.py`  [ĐÚNG-NHƯ-CODE]

Hiện vật đầu ra đẩy vào kho dùng chung. Chỉ **hai** loại: `file` (bytes trong bucket MinIO `armarius`,
`stored = True`, `uri` là khoá bucket) và `link` (URL ngoài, ví dụ PR đã merge, `stored = False`). Cả hai
đều thoả cổng DONE của task. (Chi tiết kho + cổng: [06-artifacts-sse.md](06-artifacts-sse.md).)

---

## 5. Các máy trạng thái (FSM)

### 5.1 FSM mời agent — `Marius.invite_status`  [ĐÚNG-NHƯ-CODE]

Mô hình **operator-invite** (issue #63): operator nhập gateway của agent = đã quyết định thu nhận, nên
token đúc ngay lúc mời. Không còn bước enroll/approve.

```
INVITED ──activate(token)──► APPROVED ──revoke()──► REVOKED
   │                                                   ▲
   └──────────────── revoke() ─────────────────────────┘
```

- `activate(token, now)`: `INVITED` (hoặc `PENDING_REVIEW` của hàng cũ) → `APPROVED`, gắn token + mốc
  duyệt. Activate lần hai hoặc activate từ `REVOKED` là lỗi (`InviteError`).
- `revoke()`: từ mọi trạng thái chưa-revoked → `REVOKED`.
- Enum còn **4** giá trị (kể cả `PENDING_REVIEW`) chỉ để tương thích hàng dữ liệu cũ; agent mới đi thẳng
  `INVITED → APPROVED`. Chi tiết luồng: [02-invite.md](02-invite.md).

### 5.2 FSM task — `Task.status`  [ĐÚNG-NHƯ-CODE]

Mỗi dòng liệt kê **các đích đi trực tiếp** từ trạng thái bên trái (dấu `|` = "hoặc"), không phải một chuỗi
nối tiếp:

```
DRAFT ──────► TODO | CANCELLED
BACKLOG ────► TODO | CANCELLED
TODO ───────► IN_PROGRESS | BLOCKED | BACKLOG | CANCELLED
IN_PROGRESS ► IN_REVIEW | BLOCKED | DONE | TODO | CANCELLED
IN_REVIEW ──► DONE | IN_PROGRESS | BLOCKED | CANCELLED
BLOCKED ────► IN_PROGRESS | TODO | BACKLOG | CANCELLED
DONE ───────► IN_PROGRESS         (mở lại)
CANCELLED ──► BACKLOG             (khôi phục)
```

- `DRAFT` = đề xuất của Leader (chờ xác nhận), đi **thẳng** tới `TODO` (duyệt) **hoặc** `CANCELLED` (từ chối) — hai nhánh độc lập.
- Vào `IN_REVIEW`/`DONE` phải qua **cổng DONE** (có hiện vật); vào `TODO`/`IN_PROGRESS` phải qua **cổng phụ thuộc**.
- Chuyển sang chính trạng thái hiện tại là no-op (chỉ cập nhật `status_reason`).

### 5.3 Vòng đời dự án — `Project.status`  [ĐÚNG-NHƯ-CODE]

`setup → active → archived`. `active` đạt một lần, không lùi (xem §3.1).

### 5.4 FSM cấp ghế — `SeatGrant.status`  [ĐÚNG-NHƯ-CODE]

`granted → revoked` (một chiều).

### 5.5 FSM sống/chết — `Marius.liveness`  [ĐÚNG-NHƯ-CODE]

`OFFLINE → ONLINE → CHECKING → OFFLINE ...` (có backoff), cùng `WORKING`/`HUNG`. Sau một lượt chạy kết
thúc, agent về `ONLINE` (`last_seen_at` vừa = tín hiệu) — đây cũng là trạng thái "rảnh giữa các lượt".
Logic ở `domain/services/liveness_fsm.py`; chi tiết: [04-liveness.md](04-liveness.md).

### 5.6 FSM chat với Leader — `ProjectLeaderConversation.state`  [ĐÚNG-NHƯ-CODE]

`IDLE → THINKING → IDLE` (hoặc `FAILED` khi lượt Leader lỗi, coi như idle để thử lại). "Leader offline ⇒
khoá ô nhập" là thuộc tính **suy ra lúc đọc** từ liveness của Leader, **không lưu**. Chi tiết:
[05-task-leaderchat.md](05-task-leaderchat.md).

### 5.7 FSM onboarding — `OnboardingSession.status`  [ĐÚNG-NHƯ-CODE]

`open → finalized | abandoned`. Quản gia (Workspace Agent) phỏng vấn Patron; `collected` tích luỹ kế
hoạch; `finalize` dựng `Project` thật. Chi tiết luồng ở [02-invite.md](02-invite.md).

---

## 6. Thực thể hạ tầng-chạy (runtime)

- **Run + RunEvent** — `entities/run.py`: một lần chạy có biên và luồng sự kiện trace teo từ adapter.
  `RunStatus` ∈ {queued, running, completed, failed, timed_out, stopped}. `WakeSource` = lý do chạy
  (assignment, mention, comment, on_demand, continuation, nudge, leader_chat). [ĐÚNG-NHƯ-CODE]
- **WakeupRequest** — `entities/wakeup.py`: yêu cầu đánh thức **luôn gắn task** (`task_id`); không có bộ
  đếm giờ toàn cục. `WakeupStatus` ∈ {queued, dispatched, coalesced, done, failed}. Chi tiết mô hình wake:
  [03-roster-wake.md](03-roster-wake.md). [ĐÚNG-NHƯ-CODE]
- **AgentTaskSession** — `entities/session.py`: liên kết bền `(Marius, adapter, task) ↔ session runtime`.
  Lưu handle gốc (`session_params_json`) để lần wake sau **resume** thay vì khởi động lạnh. [ĐÚNG-NHƯ-CODE]
- **ProjectLeaderConversation** — `entities/leader_chat.py`: chat 1-1 cấp dự án với Leader (#82). Tối đa
  một/dự án; resume session `armarius:project:{project_id}:leader` mỗi lượt. [ĐÚNG-NHƯ-CODE]

---

## 7. Nợ kỹ thuật miền cần dọn ở Giai đoạn 2

**Bảng nợ đã dọn xong.** Mọi món nợ miền của Giai đoạn 2 đã sửa xong và spec ở trạng thái [ĐÚNG-NHƯ-CODE].
Còn lại một việc **nằm ngoài §7**: hoàn thiện/gỡ `install-skills` (#74) — đang **tạm gác** theo chủ dự án
(xem [02-invite.md](02-invite.md) §6).

> ✅ **Đã sửa ở issue #101 (GĐ-2 — một người phụ trách):** gỡ sạch thực thể `TaskParticipant` (mô hình
> nhiều-người song song, mã chết mồ côi: không bảng CSDL, không kho/mapper, không nơi dùng) + dead code
> frontend; `Task.assigned_marius_id` là **nguồn sự thật duy nhất** cho một người phụ trách. **Không cần di
> trú** (không có bảng để xoá). Xem §4.1 + [05-task-leaderchat.md](05-task-leaderchat.md) §1.1.
>
> ✅ **Đã sửa ở issue #99 (GĐ-2 C+D):** gỡ sạch Commission (đã bị Chat với Leader #82 thay thế) — thực thể
> `CommissionSession`/`CommissionStatus`/`LeaderState`, use case, endpoint `/v1/commissions/*`,
> `WakeSource.COMMISSION`, bảng CSDL `commission_sessions` + toàn bộ dead code FE; và thống nhất
> `Liveness.IDLE` → dùng lại `ONLINE` (sau lượt agent về `ONLINE`, watchdog duy trì qua nhánh ONLINE có
> sẵn). Di trú `a1c4e8b2d6f9` xoá bảng + backfill `idle → online`. Xem [05-task-leaderchat.md](05-task-leaderchat.md)
> §5 + [04-liveness.md](04-liveness.md) §4.
>
> ✅ **Đã sửa ở issue #97:** gỡ sạch tàn dư enroll-and-wait — trường `Marius.enrollment_code` (entity +
> cột CSDL, di trú `f3a1b8c5d2e7`), nhánh STEP-0 trong `build_invite_prompt`, và 2 chỗ chữ sai cơ chế ở
> MCP. **`InviteStatus.PENDING_REVIEW` được GIỮ** — nó đang đúng vai trò hỗ trợ hàng cũ (chỉ `activate`
> admit từ legacy; `InviteService.invite` dùng `INVITED`→`APPROVED`, không gán hàng mới). Xem
> [02-invite.md](02-invite.md) §3.1.
>
> ✅ **Đã sửa ở issue #93:** gộp `Role.description` + `Role.responsibilities` thành **một** trường
> `description` (gỡ `responsibilities`, dồn dữ liệu cũ khi nâng cấp CSDL). Xem §3.2.

> ✅ **Đã sửa ở issue #87:** lỗi prompt đọc `Marius.role` rỗng (nay tra vai trò dự án `SeatGrant.role_key →
> Role`) và phạm vi danh bạ wake theo workspace (nay theo dự án). Xem [03-roster-wake.md](03-roster-wake.md) §3.
>
> ✅ **Đã sửa ở issue #89:** sinh mã task theo thiết kế JIRA — `Task.identifier = {project.key}-{seq}` với
> `Project.key` (Patron đặt, duy nhất workspace, bất biến) + `Project.next_task_seq` (bộ đếm monotonic cấp
> phát atomic). Thay auto-suy tiền tố + `max+1` (không atomic, không duy nhất). Xem §3.1 + §4.1.

---

## 8. Tiêu chí nghiệm thu

Bản nền này coi là **đúng-như-code** khi:

1. Mọi thực thể liệt kê ở §1 tồn tại trong `backend/armarius/domain/entities/` với đúng các trường nêu ở §2–§4.
2. Các FSM ở §5 khớp bảng chuyển trạng thái trong `task.py`, `marius.py`, `seat_grant.py`, `project.py`,
   `leader_chat.py`.
3. Hai cổng miền (DONE, phụ thuộc) ném đúng ngoại lệ khi vi phạm (`ArtifactRequiredError`,
   `DependencyNotMetError`) — có test ở tầng miền.

Cơ chế Giai đoạn 2: mỗi món nợ ở §7 khi code sửa xong thì nhãn tương ứng đổi từ [ĐÍCH-CẦN-SỬA] sang
[ĐÚNG-NHƯ-CODE]. Bảng §7 **đã dọn xong** (xem các ghi chú ✅ ở §7); việc miền còn lại duy nhất là #74
(install-skills) đang tạm gác, nằm ngoài §7.
