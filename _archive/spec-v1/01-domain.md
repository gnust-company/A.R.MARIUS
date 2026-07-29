# 01 — Mô hình miền (thực thể + máy trạng thái)

> Ghi lại **các thực thể nghiệp vụ** của Armarius và **các máy trạng thái** (state machine) của chúng.
> Tầng miền (`backend/armarius/domain/`) là mã **thuần**: chỉ dữ liệu và luật chuyển trạng thái, **không**
> đụng cơ sở dữ liệu, mạng hay adapter — phần I/O do tầng ứng dụng (`application/`) bơm vào.

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
    └── ProjectLeaderConversation (chat 1-1 với Leader)
```

Các thực thể **cấp workspace**: `Workspace`, `Marius`, `Skill`, `Label`, `User` (Patron), `OnboardingSession`.
Các thực thể **cấp dự án**: mọi thứ dưới `Project`.

---

## 2. Nhóm danh tính & không gian

### 2.1 Workspace — `entities/workspace.py`

Không gian làm việc dùng chung, thuộc **một** Patron (`owner_user_id`). Có `name`, `slug`, và
`workspace_agent_id` — con trỏ (khoá ngoại) tới một `Marius` được chỉ định làm **quản gia onboarding**.

### 2.2 User (Patron) — `entities/user.py`

Người dùng con người. `role` ∈ {`patron`, `member`, `admin`}. Trong sản phẩm này người chủ workspace là
**Patron**. Mật khẩu băm ở tầng service.

### 2.3 Marius (agent) — `entities/marius.py`

Danh tính một agent, gắn với một adapter runtime. Các trường chính:

| Trường | Ý nghĩa |
|---|---|
| `adapter_type` | loại adapter (mặc định `hermes_gateway`) |
| `adapter_config` | thông tin kết nối gateway (`base_url` + `api_key`), lấy từ operator lúc mời |
| `agent_token` | bearer để agent gọi ngược vào API của Armarius; đúc **lúc mời** |
| `skills`, `skill_ids` | kỹ năng agent có / id kỹ năng liên kết từ kho |
| `skill_installs` | trạng thái cài từng kỹ năng (`slug → pending/installed/failed`), cho vòng cài hậu-mời (xem [02-invite.md](02-invite.md) §6) |
| `invite_status` | FSM mời (xem §5.1) |
| `liveness`, `last_seen_at`, `probe_attempts`, `backoff_step`, `next_probe_at`, `offline_since` | sổ sách sống/chết (xem [04-liveness.md](04-liveness.md)) |
| `role` | vai trò **cấp workspace** — chuỗi tự do, thường để rỗng; **không** dùng cho vai trò trong dự án |

**Điểm quan trọng — hai khái niệm "vai trò" khác nhau:**

- `Marius.role` là **vai trò cấp workspace**: một chuỗi ghi lúc mời, phần lớn để rỗng.
- Vai trò **thật sự trong dự án** không nằm ở đây, mà suy ra từ `SeatGrant.role_key` → `Role` (xem
  [03-roster-wake.md](03-roster-wake.md)).

Mọi prompt cấp dự án phải tra vai trò dự án (`SeatGrant.role_key → Role`), **không** đọc `Marius.role`
(rỗng). Chi tiết: [03-roster-wake.md](03-roster-wake.md) §3.

### 2.4 Skill — `entities/skill.py`

Năng lực cài được, tác giả trong "Skill Shop" của workspace. Gốc cây là `SKILL.md`; `files` là bản đồ
đường-dẫn → nội-dung. `source` ∈ {`builtin`, `manual`, `imported`}. `source_url` là nơi quảng bá cho
agent trong lời mời; `absolute_source_url()` ghép với base URL công khai khi là đường dẫn tương đối.

### 2.5 Label — `entities/label.py`

Tag phạm vi workspace, gắn lên task. Có `name` và `color` (mã hex).

---

## 3. Nhóm dự án & roster

### 3.1 Project — `entities/project.py`

Một sáng kiến độc lập trong workspace; sở hữu roster, task và một thư mục hiện vật dùng chung.

- **Vòng đời** (`ProjectStatus`): `setup → active → archived`. Đạt `active` **một lần** (khi mọi ghế đã
  cấp VÀ mọi agent ngồi ghế đều ONLINE) và không lùi lại.
- **`settings`** (Patron chỉnh được), mặc định thận trọng:
  - `require_review_before_done = True`
  - `require_approval_for_done = False`
  - `comment_required_for_review = False`
  - `yolo_mode = False` — chế độ YOLO: `False` ⇒ task Leader đề xuất là `draft` chờ Patron duyệt;
    `True` ⇒ Leader tạo + gán task được **tự duyệt**, không cần xin phép. (Hành vi chi tiết ở
    [05-task-leaderchat.md](05-task-leaderchat.md).)
- **Bối cảnh brief** (Patron cung cấp, tuỳ chọn): `objective`, `success_metrics`, `target_date`,
  `github_url`, `context`.
- **`key`** — mã dự án ngắn kiểu JIRA (2–10 ký tự hoa `[A-Z][A-Z0-9]{1,9}`, bắt đầu bằng chữ),
  **duy nhất theo workspace**, **bất biến** sau khi đặt. Làm phần "KEY" trong mã task `{key}-{seq}`.
  Patron đặt lúc tạo (FE tự gợi ý từ tên); bỏ trống ⇒ hệ thống suy từ tên + tự uniquify (đuôi số);
  trùng ⇒ `DuplicateProjectKey` (409); sai format ⇒ `InvalidProjectKey` (422).
- **`next_task_seq`** — bộ đếm monotonic per-project; `ProjectRepository.allocate_task_number` cấp
  phát **atomic** bằng `UPDATE … RETURNING` khi tạo task, nên số không bao giờ trùng (tạo-cùng-lúc)
  và không bao giờ tái sử dụng.

### 3.2 Role — `entities/role.py`

Định nghĩa một **ghế** trong roster của dự án.

| Trường | Ý nghĩa |
|---|---|
| `key` | slug ổn định, ví dụ `backend`, `leader` |
| `title` | nhãn người đọc, ví dụ "Backend" |
| `seats` | số ghế; role Leader **luôn** `seats == 1` |
| `is_leader` | đúng một role/dự án là Leader |
| `skill_ids` | kỹ năng role này mang (tuỳ chọn) |

**Mô tả vai trò:** Role có **một** trường `description` duy nhất — "mô tả vai trò" — dùng cho **mọi** role,
kể cả Leader. `description` **được nhắc trong prompt** gửi tới agent giữ role đó (dòng self-role) và trong
danh bạ đồng đội (xem [03-roster-wake.md](03-roster-wake.md) §3.1). Màn tạo dự án cho Patron nhập
`description` cho cả worker lẫn Leader.

Luật: đúng một role là Leader, và role Leader luôn 1 ghế — kiểm ở `domain/services/project_rules.py`.

### 3.3 SeatGrant — `entities/seat_grant.py`

Gán một `Marius` vào một `role_key` của dự án. Đây là mã **hệ-thống-cấp**: agent không tự ứng tuyển,
không có bước chấp nhận. Trạng thái: `granted` (ngay khi Patron gán) → `revoked` (lối ra duy nhất;
revoke lần hai là lỗi). `role_key` khớp 1-1 với `Role.key`; ghế Leader mang `role_key = "leader"`.

**Đây là cầu nối vai-trò-dự-án:** để biết vai trò của một agent trong một dự án, tra `SeatGrant` của agent
đó trong dự án → lấy `role_key` → tra `Role` cùng key → đọc `title` + mô tả.

---

## 4. Nhóm công việc & cộng tác

### 4.1 Task — `entities/task.py`

Đơn vị công việc, **kiêm** phòng cộng tác. FSM ở §5.2. Các trường đáng chú ý:

| Trường | Ý nghĩa |
|---|---|
| `status`, `priority` | trạng thái + độ ưu tiên |
| `next_action` | gợi ý tiếp tục bền — agent định làm gì kế tiếp (resume từ trạng thái task, không từ session) |
| `parent_id` | task con của task khác |
| `definition_of_done` | mô tả "thế nào là xong" |
| `assigned_marius_id` | **người phụ trách duy nhất** của task |
| `identifier` | mã task người-đọc `{project.key}-{seq}`, ví dụ `CALC-7` |

**Một người phụ trách:** mỗi task có **đúng một người phụ trách**, biểu diễn bằng `assigned_marius_id` — đây
là **nguồn sự thật duy nhất** cho mọi luồng (gán, tự-nhận, đánh thức). Không có mô hình nhiều-người song song.
Frontend hiển thị đúng một người phụ trách này ở mọi chỗ (thẻ bảng, hộp thư, phòng cộng tác).

**Mã task:** `Task.identifier` = `{project.key}-{seq}`, sinh ở `TaskService.create`:

- **KEY** là `Project.key` (xem §3.1) — mã dự án ngắn, Patron đặt (có gợi ý), duy nhất workspace, bất biến.
- **`seq`** cấp phát từ `Project.next_task_seq` bằng `allocate_task_number` (`UPDATE … RETURNING`):
  **atomic** (hai tạo-cùng-lúc không bao giờ cùng số) và **không bao giờ tái sử dụng**.

Cột `tasks.identifier` persist mã qua tải lại (thiết kế JIRA-style: KEY + số chạy).

Hai **cổng** miền được thực thi thuần trong `transition_to()` (tầng ứng dụng bơm `has_artifact` /
`deps_satisfied`):

- **Cổng DONE:** không thể vào `in_review`/`done` nếu chưa có hiện vật đã publish. → `ArtifactRequiredError`.
- **Cổng phụ thuộc:** không thể vào `todo`/`in_progress` khi còn một `blocked_by` chưa `done`. → `DependencyNotMetError`. Tầng ứng dụng tính `deps_satisfied` từ cạnh **bền** (§4.4) ở mọi đường vào trạng thái bị chặn (`transition`, `claim`, duyệt draft).

### 4.2 Comment — `entities/comment.py`

Tin nhắn trong thread của task. `author_kind` ∈ {`human`, `agent`, `system`}. `mentions` chứa danh sách
`marius_id` **cần được đánh thức** khi bị nhắc tên (nguồn wake `MENTION`).

### 4.3 ChecklistItem — `entities/checklist_item.py`

Một ô tick trên task: `text`, `done`, `order`.

### 4.4 TaskDependency — `entities/task_dependency.py`

Cạnh `blocked_by`: `task_id` (bị chặn) chờ `blocks_task_id`. Cấm tự-trỏ-chính-mình (`__post_init__`
ném `TaskDependencyError`). Lưu bền ở bảng `task_dependencies` (duy nhất theo cặp `(task_id,
blocks_task_id)`); repository liệt kê blocker của một task và trả lời "mọi blocker đã `done` chưa" để
nuôi cổng phụ thuộc ở §4.1.

### 4.5 Artifact — `entities/artifact.py`

Hiện vật đầu ra đẩy vào kho dùng chung. Chỉ **hai** loại: `file` (bytes trong bucket MinIO `armarius`,
`stored = True`, `uri` là khoá bucket) và `link` (URL ngoài, ví dụ PR đã merge, `stored = False`). Cả hai
đều thoả cổng DONE của task. (Chi tiết kho + cổng: [06-artifacts-sse.md](06-artifacts-sse.md).)

---

## 5. Các máy trạng thái (FSM)

### 5.1 FSM mời agent — `Marius.invite_status`

Mô hình **operator-invite**: operator nhập gateway của agent = đã quyết định thu nhận, nên token đúc ngay
lúc mời. Không có bước enroll/approve.

```
INVITED ──activate(token)──► APPROVED ──revoke()──► REVOKED
   │                                                   ▲
   └──────────────── revoke() ─────────────────────────┘
```

- `activate(token, now)`: `INVITED` (hoặc `PENDING_REVIEW` của hàng cũ) → `APPROVED`, gắn token + mốc
  duyệt. Activate lần hai hoặc activate từ `REVOKED` là lỗi (`InviteError`).
- `revoke()`: từ mọi trạng thái chưa-revoked → `REVOKED`.
- Enum còn giữ giá trị `PENDING_REVIEW` **chỉ để tương thích hàng dữ liệu cũ**; agent mới luôn đi thẳng
  `INVITED → APPROVED`. Chi tiết luồng: [02-invite.md](02-invite.md).

### 5.2 FSM task — `Task.status`

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

### 5.3 Vòng đời dự án — `Project.status`

`setup → active → archived`. `active` đạt một lần, không lùi (xem §3.1).

### 5.4 FSM cấp ghế — `SeatGrant.status`

`granted → revoked` (một chiều).

### 5.5 FSM sống/chết — `Marius.liveness`

`OFFLINE → ONLINE → CHECKING → OFFLINE ...` (có backoff), cùng `WORKING`/`HUNG`. Sau một lượt chạy kết
thúc, agent về `ONLINE` (`last_seen_at` vừa = tín hiệu) — đây cũng là trạng thái "rảnh giữa các lượt".
Logic ở `domain/services/liveness_fsm.py`; chi tiết: [04-liveness.md](04-liveness.md).

### 5.6 FSM chat với Leader — `ProjectLeaderConversation.state`

`IDLE → THINKING → IDLE` (hoặc `FAILED` khi lượt Leader lỗi, coi như idle để thử lại). "Leader offline ⇒
khoá ô nhập" là thuộc tính **suy ra lúc đọc** từ liveness của Leader, **không lưu**. Chi tiết:
[05-task-leaderchat.md](05-task-leaderchat.md).

### 5.7 FSM onboarding — `OnboardingSession.status`

`open → finalized | abandoned`. Quản gia (Workspace Agent) phỏng vấn Patron; `collected` tích luỹ kế
hoạch; `finalize` dựng `Project` thật. Chi tiết luồng ở [02-invite.md](02-invite.md).

---

## 6. Thực thể hạ tầng-chạy (runtime)

- **Run + RunEvent** — `entities/run.py`: một lần chạy có biên và luồng sự kiện trace teo từ adapter.
  `RunStatus` ∈ {queued, running, completed, failed, timed_out, stopped}. `WakeSource` = lý do chạy
  (`assignment`, `mention`, `comment`, `on_demand`, `continuation`, `nudge`, `leader_chat`).
- **WakeupRequest** — `entities/wakeup.py`: yêu cầu đánh thức **luôn gắn task** (`task_id`); không có bộ
  đếm giờ toàn cục. `WakeupStatus` ∈ {queued, dispatched, coalesced, done, failed}. Chi tiết mô hình wake:
  [03-roster-wake.md](03-roster-wake.md).
- **AgentTaskSession** — `entities/session.py`: liên kết bền `(Marius, adapter, task) ↔ session runtime`.
  Lưu handle gốc (`session_params_json`) để lần wake sau **resume** thay vì khởi động lạnh.
- **ProjectLeaderConversation** — `entities/leader_chat.py`: chat 1-1 cấp dự án với Leader. Tối đa
  một/dự án; resume session `armarius:project:{project_id}:leader` mỗi lượt.

---

## 7. Tiêu chí nghiệm thu

1. Mọi thực thể liệt kê ở §1 tồn tại trong `backend/armarius/domain/entities/` với đúng các trường nêu ở §2–§4.
2. Các FSM ở §5 khớp bảng chuyển trạng thái trong `task.py`, `marius.py`, `seat_grant.py`, `project.py`,
   `leader_chat.py`.
3. Hai cổng miền (DONE, phụ thuộc) ném đúng ngoại lệ khi vi phạm (`ArtifactRequiredError`,
   `DependencyNotMetError`) — có test ở tầng miền.
