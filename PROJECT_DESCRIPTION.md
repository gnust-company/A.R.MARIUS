# Armarius — Project Description & Design Brainstorm

> Tài liệu brainstorm/thiết kế ban đầu. Mục tiêu: chốt được **mental model**, **domain model**, và **các quyết định kiến trúc lớn** trước khi viết code.
> Tham chiếu: `paperclip` (adapter + session model), `openclaw-mission-control` (board chat + governance).

---

## 0. TL;DR — Armarius là gì (và KHÔNG là gì)

**Là:** một *shared workspace* để nhiều người ở nhiều team **mời agent của mình vào**, agent **tự nhận task — hỏi/đáp với các bên liên quan — cộng tác ngang hàng với agent khác — đẩy artifact vào kho chung**, còn con người chỉ **giám sát & approve**.

**KHÔNG là:**
- KHÔNG phải "vận hành cả công ty" (bỏ khái niệm CEO / Goal / org-chart như Paperclip).
- KHÔNG bó buộc một loại agent (không chỉ OpenClaw như Mission Control).
- KHÔNG phụ thuộc heartbeat của runtime bên ngoài — Armarius **tự sở hữu vòng đánh thức**.

Một câu định vị: **"Armarius là provisioner cho sự cộng tác giữa các team, nơi agent là worker và bạn là patron."**

---

## 1. Chắt lọc từ 2 thử nghiệm

### 1.1 Giữ lại từ Paperclip
| Cơ chế | File tham chiếu | Vì sao giữ |
|---|---|---|
| **Adapter registry** (server/ui/cli, pluggable qua npm) | `server/src/adapters/registry.ts`, `docs/adapters/overview.md` | Deal với mọi loại agent như nhau, không xử lý riêng từng loại |
| **Task = Session** liên kết bền | `packages/db/src/schema/agent_task_sessions.ts` | Cho phép agent làm việc liên tục trên 1 task qua nhiều lần đánh thức |
| **Invite + skill install** | (custom của bạn) | Onboard agent vào hệ thống chuẩn hoá |
| **Heartbeat run model** (run có status, usage, log, sessionId before/after) | `packages/db/src/schema/heartbeat_runs.ts` | Trace được từng lần thực thi |

### 1.2 Giữ lại từ Mission Control
- **Board chat chung trong project** để con người + agent cùng trao đổi.
- **Đơn giản, governance/approval là first-class.**

### 1.3 Vứt bỏ / Sửa
| Vấn đề ở ref | Hướng Armarius |
|---|---|
| Paperclip: CEO/Goal, vận hành công ty | Bỏ. Chỉ có **Project** + **Roster (yêu cầu role/skill)** |
| Agent không biết về nhau, ai làm việc nấy | **Agent Directory + Mention + Lateral threads** là tính năng lõi |
| Không có workspace chung, agent tạo file ở local | **Shared Artifact Store** bắt buộc — "done" chỉ hợp lệ khi output nằm trong kho chung |
| Mission Control phụ thuộc heartbeat OpenClaw, mất kiểm soát khi hang | **Armarius tự chủ scheduler/liveness**, runtime chỉ là "executor" |
| Paperclip adapter chủ yếu local | Ưu tiên **gateway/remote adapter** (OpenClaw Gateway, Hermes) |

---

## 2. Domain Model (đề xuất)

```
Organization / Tenant
└── Workspace                      ← không gian cộng tác chung (cross-team)
    ├── Project                    ← 1 sáng kiến/sản phẩm; có Roster yêu cầu
    │   ├── Roster (Role spec)     ← cần role nào, skill nào → gate "ứng tuyển"
    │   ├── Member (Human)         ← supervisor / stakeholder
    │   ├── Marius (Agent seat)    ← agent đã được nhận vào project
    │   ├── Task                   ← đơn vị công việc; mỗi task ≈ 1 "phòng" cộng tác
    │   │   ├── Thread (chat)      ← hỏi/đáp giữa human ↔ agent ↔ agent
    │   │   ├── Session (per agent)← liên kết task ↔ runtime session của từng agent
    │   │   ├── Run (heartbeat)    ← 1 lần thực thi
    │   │   └── Artifact ref       ← output đẩy vào Shared Store
    │   └── Approval queue
    └── Shared Artifact Store      ← workspace files chung (S3/volume/git)
```

### Khái niệm cốt lõi cần định nghĩa rõ
- **Marius (Agent):** một danh tính có `adapterType`, `adapterConfig`, **danh sách skill/role đã verify**, owner (người mời vào), trạng thái liveness.
- **Task:** không chỉ là "việc" mà là **một phòng cộng tác**: có thread, có nhiều agent tham gia, mỗi agent giữ session riêng, output gom về artifact.
- **Roster / Role spec:** project khai báo *"cần 1 Backend, 1 Reviewer, kỹ năng X/Y"*. Agent muốn vào phải **đáp ứng** (xem §6).

---

## 3. Mô hình cộng tác — phần thiếu của cả 2 ref (quan trọng nhất)

Đây là điểm khác biệt cốt lõi. Cả Paperclip lẫn Mission Control đều để agent "ai làm việc nấy". Armarius phải làm cho **agent biết về nhau và nói chuyện được**.

### 3.1 Agent Directory (agent biết về nhau)
- Trong mỗi project có "danh bạ": ai đang ở đây, role gì, skill gì, đang bận task nào.
- Khi agent được đánh thức, context **luôn kèm directory** (ai có thể hỏi, hỏi việc gì).

### 3.2 Cơ chế trao đổi: Mention + Thread + Wakeup
Cộng tác = **message-passing có địa chỉ**, không phải shared mutable state hỗn loạn:

1. Agent A đang làm task, cần spec → post comment vào thread, `@mention` agent B (hoặc human stakeholder).
2. Mention sinh ra một **wakeup request** tới B (đây là lý do Armarius phải tự sở hữu scheduler — xem §5).
3. B thức dậy, đọc thread, trả lời (hoặc tạo sub-task), `@mention` lại A.
4. A được đánh thức bởi reply → tiếp tục.

> Đây chính là cách chữa bệnh "CEO tự làm hết, phải mention mới đi tìm member" ở Paperclip: **mention là first-class và nó thực sự đánh thức đúng agent.**

### 3.3 Hai loại hội thoại
- **Vertical (human ↔ agent):** approve, làm rõ yêu cầu, chặn/huỷ.
- **Lateral (agent ↔ agent):** hỏi spec, bàn giao, review chéo. *Không có controller trung tâm điều phối từng message.*

### 3.4 Định nghĩa "Done" (chống bệnh file-ở-local)
Một task chỉ được chuyển sang `review/done` khi:
- Có **artifact nằm trong Shared Artifact Store** (không phải đường dẫn local của runtime), và
- Artifact được link vào task.

→ Bắt buộc qua **skill/tool** mà agent dùng để "publish artifact" (Armarius cấp tool này khi onboard, xem §6.2). Agent không publish được = task không done được.

---

## 4. Task ↔ Session: thiết kế liên kết (trả lời câu hỏi kỹ thuật #2)

### 4.1 Paperclip làm thế nào (đã verify trong code)
- Bảng `agent_task_sessions`: unique `(companyId, agentId, adapterType, taskKey)`.
- Adapter chạy xong trả **native session handle** (vd Claude → `session_id`), lưu vào `sessionParamsJson` + `sessionDisplayId`.
- Lần đánh thức kế tiếp của **cùng agent trên cùng task** → tra row → truyền session cũ cho adapter → **resume**.
- Mỗi `heartbeat_run` ghi `sessionIdBefore` / `sessionIdAfter` để trace.

**Insight:** "session" gắn với **cặp (agent, task)**, không global. Nhiều agent trên 1 task → mỗi agent một dòng session riêng → mỗi agent có ngữ cảnh liên tục của riêng nó về task đó.

### 4.2 Đề xuất cho Armarius
Giữ nguyên ý tưởng, tổng quát hoá khoá:

```
agent_task_sessions (
  workspace_id, project_id,
  marius_id,            -- agent seat
  adapter_type,
  task_id,              -- = taskKey
  session_params_json,  -- handle native do adapter trả về (sessionId / threadId / conversationId…)
  session_display_id,
  last_run_id,
  ...
)
UNIQUE (marius_id, adapter_type, task_id)
```

- **Adapter contract** phải có `resumeHint` trong/ra: `execute(ctx)` nhận `ctx.session` (nếu có) và trả `result.session` (handle mới/giữ nguyên).
- Với runtime **không resumable** (vd webhook stateless): `session_params_json` rỗng → mỗi run là cold-start, Armarius bù bằng cách **bơm transcript/thread summary vào prompt** (context replay). → Adapter khai báo `capabilities.resumable: true|false`.
- **Reset session**: xoá row → lần sau cold-start (giống Paperclip).

**Ánh xạ cụ thể theo adapter (handle native lưu trong `session_params_json`):**
| Adapter | `session_params_json` chứa gì | Resumable |
|---|---|---|
| `hermes_gateway` | `{ session_id: "armarius:task:{taskId}", session_key: "armarius:agent:{agentId}:task:{taskId}" }` (đã verify §5.3) | ✅ (state.db) |
| `openclaw_gateway` | `{ sessionKey: "agent:{agentId}:armarius:task:{taskId}" }` | ✅ |
| `claude_local`/CLI | `{ session_id }` native do CLI trả về | ✅ |
| `http` (webhook) | rỗng → context replay | ❌ |

---

## 4.3 Wake model — KHÔNG global timer, chỉ event + self/liveness (gated theo status)

> Đây là phần đối chiếu kỹ code Paperclip (`heartbeat.ts`, `run-liveness.ts`, `task-watchdogs.ts`, `run-liveness-continuations.ts`) rồi *chắt lọc lại cho gọn hơn cả Paperclip*. Paperclip có một kênh "timer-wake dạo việc" chạy trong **session nháp toàn cục, reset mỗi lần** — ta **cố tình loại bỏ** vì nó vừa tốn (đánh thức LLM để "ngó rồi ngủ") vừa vô nghĩa khi đã có event + recovery.

### Nguyên tắc gốc
**Chỉ đánh thức agent khi "bóng đang ở chân nó".** Nếu task đang ở trạng thái mà người/agent khác mới là người đi nước tiếp → **im lặng**, để chính EVENT của họ đánh thức. Mọi wake đều **task-scoped** (đi thẳng vào session của task), không bao giờ có session nháp toàn cục.

### Hai họ wake (cả hai đều nhắm session task)
1. **event-wake (đẩy):** thế giới ngoài đổi — `assign` / `comment` / `mention` / `review` / `agent-online ping`. → vào session task liên quan.
2. **self/liveness-wake (sinh từ chính run/task):** quyết định bắn hay không là **hàm của (task status × run status)**, cộng thêm input **schedule** (agent tự hẹn "đánh thức tôi sau X"). KHÔNG phải clock gõ mù.

### Bảng chính sách: trạng thái → có self-wake không
| Task status | Run vừa rồi | Bắn self-wake? | Cái gì đánh thức tiếp |
|---|---|---|---|
| in_progress | đang chạy | ❌ (đang làm) | **watchdog** nếu tắc (im lặng quá lâu) |
| in_progress | xong + để việc dở (có `nextAction`) | ✅ **continuation** (resume session) | — |
| in_progress | xong, không chốt gì, không đổi status | ✅ **nudge có giới hạn** → hết lượt escalate người | "bạn dừng mà chưa ghi tiến độ" |
| blocked / backlog | **có** lý do + chủ rõ | ❌ | event unblock |
| blocked / backlog | **không** lý do (limbo) | ✅ **nudge 1 nhát** đòi cập nhật lý do → escalate | — |
| in_review / chờ duyệt | — | ❌ (bóng ở chân người duyệt) | event duyệt/comment |
| todo (vừa assign) | — | ❌ (assign đã là event-wake) | retry → blocked nếu lỗi kết nối |
| done / cancelled | — | ❌ vĩnh viễn | — |

### Recovery cho ca "agent hang / dừng đột ngột" (KHÔNG dùng timer)
1. **Watchdog** thấy run của task T im lặng bất thường (`lastOutputAt` quá cũ) → stop run, hoặc run chạm timeout/grace.
2. **Liveness** chấm trạng thái run vừa chết, trích `nextAction`.
3. **Continuation-wake** enqueue một wake **mang `taskId`** → route thẳng vào **session T cũ (resume)**, kèm nhắc `nextAction`. Bounded bằng `continuationAttempt` + idempotency → hết lượt thì escalate người, không loop vô hạn.

### Vì sao bỏ được "reconciliation timer"
- Ca **agent offline lúc assign**: giải bằng **agent-online ping = một event** → re-đánh giá task kẹt của agent đó → event-wake. Không cần clock.
- Ca **event bị rớt do bug**: nếu đường event **transactional + bền** (tạo event và enqueue wake trong cùng transaction; dispatcher quét lại hàng đợi khi restart) thì gap tự đóng. Nếu muốn bảo hiểm thêm → một sweep **deterministic bằng SQL, KHÔNG LLM**, chạy chậm.
- Ca **thế giới ngoài đổi không báo** (CI/PR): webhook, hoặc agent tự đặt **scheduled-wake** "check lại sau X" (vẫn gắn task).

> **Nguồn sự thật là TASK, không phải session.** Session resume chỉ là tiện ích cho liền mạch. Vì `nextAction` + comments + status + work-products đều durable trong DB, nên kể cả khi session mất sạch (restart/evict), một session mới vẫn tiếp tục được từ trạng thái task. → Ép agent luôn ghi `nextAction` durable.

---

## 5. Adapter & câu hỏi Gateway/Websocket (trả lời câu hỏi kỹ thuật #1)

### 5.1 Mô hình thực thi của Paperclip (đã verify)
Heartbeat → gọi `adapter.execute(ctx)` → adapter **spawn process / gọi HTTP** → chờ tới khi exit/timeout → capture stdout/usage → trả result. Tức là **request/response, có điểm bắt đầu & kết thúc rõ ràng** (pull-based, Armarius chủ động gọi).

- `process` / `*_local`: spawn CLI cục bộ.
- `http`: POST webhook + agent **callback ngược** về API (fire-and-forget).
- `openclaw_gateway`: gọi tới endpoint gateway của OpenClaw.

### 5.2 Khả thi cho Hermes / OpenClaw qua Gateway vs Websocket
Mấu chốt: **mô hình `execute()` của Paperclip là "có biên" (bounded request)**. Cần ánh xạ runtime vào mô hình đó.

| Kiểu kết nối | Hợp với mô hình `execute()`? | Ghi chú thiết kế |
|---|---|---|
| **Gateway HTTP (request/response)** | ✅ Tự nhiên nhất | Adapter gọi `POST /invoke`, chờ phản hồi hoặc poll `GET /runs/{id}`. Khuyến nghị làm **trước**. |
| **Gateway + callback (webhook)** | ✅ Như `http` adapter | Armarius gửi `runId` + callback URL; runtime gọi ngược. Cần endpoint nhận callback + map về run. |
| **Websocket (long-lived, streaming)** | ⚠️ Cần lớp bao | Websocket là **stateful, không có biên**. Phải gói trong một "**session broker**": Armarius mở/duy trì WS, adapter `execute()` chỉ là "gửi 1 turn → đợi turn kết thúc (chuỗi event tới khi `done`)". Liveness/timeout do Armarius quản. |

**Khuyến nghị triển khai theo độ ưu tiên:**
1. **Gateway request/response** cho cả OpenClaw & Hermes (nếu Hermes có HTTP gateway) — rẻ, khớp model.
2. **Webhook callback** nếu runtime chạy lâu (giống `http` adapter sẵn có).
3. **Websocket** chỉ làm khi cần streaming/turn-by-turn realtime — và làm qua **một adapter loại mới `gateway_ws`** với session broker riêng, **không nhồi vào model `execute()` đồng bộ**.

> **✅ ĐÃ VERIFY (xem §5.3):** Hermes Agent expose **HTTP gateway server** thật sự (không chỉ CLI). Nó khớp model `execute()` còn *sạch hơn* OpenClaw (HTTP+SSE thay vì WebSocket+device-pairing). Rủi ro "chỉ có CLI local" đã được loại bỏ.

### 5.3 Hermes Gateway — đã verify bằng code (`gateway/platforms/api_server.py` v0.17.0)

Bật bằng `API_SERVER_ENABLED=true` + `API_SERVER_KEY` (bearer, bắt buộc kể cả loopback). Server HTTP mặc định `:8642`, chạy song song cùng các platform khác (Telegram/Discord/...).

**So sánh với OpenClaw Gateway (đối chiếu cả 2 code base):**

| Khía cạnh | OpenClaw Gateway (`execute.ts`) | **Hermes Gateway** (`api_server.py`) |
|---|---|---|
| Transport | WebSocket v3, frame `req/res/event` tự định nghĩa | **HTTP + SSE** chuẩn |
| Auth | ed25519 device keypair + pairing flow (nặng) | **Bearer token** (`API_SERVER_KEY`) |
| Gửi 1 turn | method `agent` qua WS | `POST /v1/runs` → `202 {run_id}` |
| Theo dõi tiến trình | `agent.wait` + event frames | `GET /v1/runs/{id}/events` (SSE) |
| Dừng | đóng WS | `POST /v1/runs/{id}/stop` |
| **Human approval** | không có | `POST /v1/runs/{id}/approval` ✅ built-in |
| Khám phá năng lực | không | `GET /v1/capabilities`, `/v1/skills`, `/v1/toolsets` |

**Ba lớp định danh của Hermes (đọc thẳng source):**
1. `session_id` (`X-Hermes-Session-Id` / `body.session_id`) → transcript hội thoại, **lưu vào `state.db`** qua `SessionDB`; hiện trong `hermes sessions list`. Rotate khi gọi `/new`. **Bền qua restart nếu mount volume `~/.hermes`.**
2. `session_key` (`X-Hermes-Session-Key`) → memory scope dài hạn (Honcho), **sống xuyên qua transcript rotation**; đúng semantics `session_key` của native gateway.
3. `previous_response_id` / `conversation` (API `/v1/responses`) → lưu `response_store.db` (SQLite **LRU max 100, có evict**) → **KHÔNG bền**, tránh dùng làm continuity chính.

**Công thức "1 task = 1 session resume" cho adapter `hermes_gateway`:**
```
POST /v1/runs
  Authorization: Bearer <API_SERVER_KEY>
  X-Hermes-Session-Key: armarius:agent:{agentId}:task:{taskId}   # memory scope bền
  body: { "input": "<wake prompt>",
          "session_id": "armarius:task:{taskId}" }                # transcript bền (state.db)
→ 202 { run_id };  GET /v1/runs/{run_id}/events (SSE);  POST .../stop | .../approval
```
(`_handle_runs` dòng ~80: `session_id = body.get("session_id") or stored_session_id or run_id` → nhận session_id tường minh.) Armarius lưu `session_params_json = { session_id, session_key }` theo §4.

**Lưu ý triển khai (không phải blocker):**
- **Không gọi `/new`** với session của task → giữ nguyên `session_id` là resume.
- **Persistence = volume**: mount `~/.hermes` (chứa `state.db`) để sống qua restart container.
- **1 instance Hermes ≈ 1 danh tính agent** (1 `config.yaml`, 1 model, 1 toolset `api_server`) → khớp ý tưởng "mỗi team 1 docker = 1 Marius". Nhiều persona → nhiều instance.
- Invitation flow khả thi như OpenClaw: Hermes có toolset cấu hình per-platform (`platform_toolsets.api_server`) + `/v1/skills`/`/v1/toolsets` → cài "Armarius skill", agent claim token rồi gọi ngược API Armarius.

### 5.4 Adapter contract đề xuất cho Armarius (tổng quát hoá Paperclip)
```ts
interface MariusAdapter {
  type: string;                        // "openclaw_gateway" | "hermes_gateway" | "http" | ...
  capabilities: {
    resumable: boolean;                // có session resume không
    streaming: boolean;                // có stream event không
    transport: "process" | "http" | "webhook" | "ws";
  };
  execute(ctx: ExecCtx): Promise<ExecResult>;   // 1 turn có biên
  testEnvironment(cfg): Promise<Diagnostics>;
  // optional: parseTranscript (UI), formatEvent (CLI)
}
```
`ExecCtx` mang: task context, **agent directory**, thread mới từ lần ngủ, session cũ, danh sách tool/skill được cấp.

---

## 6. Onboarding: Invite → Vet → Skill install

### 6.1 Mời agent (từ Paperclip, giữ nguyên tinh thần)
Armarius sinh **invite prompt**. Owner dán cho agent của mình → agent follow để: gọi API xin vào, cài skill Armarius, lưu token.

### 6.2 Skill mà Armarius cài cho agent
Tối thiểu một bộ skill/tool để agent "sống" trong workspace:
- `armarius.claim_task` / `update_task` — nhận & cập nhật task.
- `armarius.post_comment` / `mention` — hỏi/đáp, đánh thức người khác.
- `armarius.publish_artifact` — **đẩy output vào Shared Store** (điều kiện để "done").
- `armarius.read_directory` — biết ai đang trong project.

> Đây là cách Armarius *ép* hành vi cộng tác đúng — không trách agent được, phải design ở platform (đúng nhận xét của bạn về Mission Control).

### 6.3 Role/Skill gate khi vào Project ("ứng tuyển")
Khác Mission Control (để agent hỏi rồi tự tạo). Armarius **fix & control**:
1. Project khai báo **Roster**: `requiredRoles: [{role: "reviewer", skills: ["security"], min: 1}]`.
2. Agent xin vào một slot → Armarius **vet**: kiểm tra skill đã verify / chạy một **capability probe** (test nhỏ) / hoặc owner confirm.
3. Đạt mới được cấp seat + scope quyền theo role. Không đạt → từ chối.

→ Cho phép kiểm soát "cần role nào, skill nào" như bạn mong muốn, mà không để agent tự tung tự tác.

---

## 7. Liveness & Scheduling — Armarius tự chủ (chữa bệnh Mission Control)

Vấn đề ở Mission Control: phụ thuộc heartbeat của OpenClaw, một instance quá nhiều agent → hang → mất kiểm soát.

**Nguyên tắc:** *runtime chỉ là executor; Armarius sở hữu vòng đánh thức và liveness.*

- **Wakeup sources** (như Paperclip): `timer`, `assignment`, `on_demand`, `mention/automation`.
- **Coalescing:** agent đang chạy → wakeup mới gộp lại, không spawn trùng.
- **Liveness watchdog của Armarius:** mỗi run có timeout/grace; nếu runtime treo → Armarius đánh dấu `timed_out`, có thể retry/escalate cho người. **Không tin tưởng mù vào heartbeat của runtime.**
- **Backpressure theo gateway:** giới hạn concurrency mỗi gateway/instance để tránh dồn 1 instance OpenClaw tới mức hang.

---

## 8. Human-in-the-loop / Approval

- **Inbox của patron:** chỉ hiện khi cần quyết định (artifact ready, agent bị chặn, hành động nhạy cảm cần approve).
- **Approval policy:** action nào auto, action nào phải gate (vd publish ra ngoài, xoá, deploy).
- **Trace:** từng run có log/usage/session — xem lại được "ai làm gì, khi nào".

### 8.1 Observability & Trace — tee luồng event qua adapter (đã verify code 2 phía)

Mục tiêu: **xem được agent đang nghĩ/gọi tool gì ngay trên dashboard Armarius, KHÔNG phải vào gateway để trace.**

**Cơ chế cốt lõi: adapter là điểm "tee" (rẽ đôi).** Khi Armarius đánh thức agent qua gateway, adapter **giữ kết nối streaming suốt run**; mỗi event chảy về vừa đẩy realtime lên UI, vừa ghi xuống store để trace sau. Gateway dashboard và Armarius dashboard cùng xem **một luồng** — Armarius chỉ hứng nó vào nhà mình.

Cần 3 mảnh (Paperclip có đủ cả 3 để học/port):
1. **Adapter subscribe luồng event của gateway** (đã là trọng tâm adapter contract §5.4 — `streaming: true`, callback `onEvent`).
2. **Run-log store** (persist event/run, trace lại) **+ live event bus** (SSE/WS đẩy lên browser tức thời).
3. **UI transcript renderer** (parse event → timeline tool/assistant).

**OpenClaw** (đã verify `openclaw-gateway/execute.ts`): nhận WS event frame (`stream = assistant | lifecycle | error`) → `ctx.onLog(...)` → run log + realtime + `ui-parser`.

**Hermes** (đã verify `api_server.py`): *dễ hơn* — SSE với event **đã đặt tên sẵn** trên `GET /v1/runs/{run_id}/events`:
```
run.started → message.started → assistant.delta (token)
   → tool.progress / tool.started / tool.completed / tool.failed
   → assistant.completed → run.completed
```
(kèm `tool_name`, `token_count`, `reasoning`, `finish_reason`). Luồng adapter: `POST /v1/runs → {run_id}` → mở SSE `…/events` → tee mỗi event → `run.completed` thì finalize. Giữ SSE sống tới hết run; rớt thì poll `GET /v1/runs/{id}` làm fallback. Timeout/liveness vẫn do Armarius quản (§7, §4.3).

**Lợi thế Armarius có mà gateway dashboard không có:**
- **Trace bền & tập trung:** event nằm trong DB Armarius → xem lại kể cả khi gateway xoá/restart; **gộp trace nhiều agent/nhiều gateway một chỗ.**
- **Trace GIÀU hơn — 2 nguồn ghép lại:** (a) **luồng runtime** (agent nghĩ gì, gọi tool gì — từ SSE) + (b) **các call agent gọi NGƯỢC vào API Armarius** (claim task, comment, publish artifact). Gateway chỉ thấy (a); Armarius thấy cả hai → kể trọn câu chuyện *"nghĩ → gọi tool → cập nhật task T"*. Đúng pillar **"You trace"** trong README.

---

## 9. Kiến trúc & tech stack (đề xuất sơ bộ)

```
┌─────────────────────────────────────────────┐
│  Web UI (supervise, approve, board chat)     │
└───────────────┬─────────────────────────────┘
                │ REST + realtime (SSE/WS)
┌───────────────▼─────────────────────────────┐
│  Armarius Core API                          │
│  - Projects/Tasks/Threads/Roster            │
│  - Wake engine: event + self/liveness (§4.3)│
│  - Scheduler + Liveness watchdog (§7)       │
│  - Run-log store + live event bus (§8.1)    │
│  - Approval engine (§8)                      │
│  - Adapter Registry (§5)                     │
│  - Session store (§4)                        │
│  - Artifact Store gateway (§3.4)            │
└───────┬───────────────────────┬─────────────┘
        │ adapter.execute() ↕ SSE/WS event tee │ publish/read
   ┌────▼─────┐  ┌────▼────┐  ┌──▼──────────────┐
   │ OpenClaw │  │ Hermes  │  │ Shared Artifact │
   │ Gateway  │  │ Gateway │  │ Store (S3/git)  │
   └──────────┘  └─────────┘  └─────────────────┘
```

**Gợi ý stack:** tận dụng được cái nào bạn quen.
- Theo Paperclip: **TypeScript** (Node + Drizzle + Postgres), adapter ecosystem có sẵn để học/port.
- Theo Mission Control: **Python/FastAPI clean-architecture** nếu bạn thích tách domain rõ.
- *Khuyến nghị:* nếu muốn **tái dùng adapter/khái niệm của Paperclip nhanh nhất → đi TypeScript.** Nếu ưu tiên governance/clean domain và team quen Python → FastAPI. (Cần bạn quyết — xem §11.)

---

## 10. Phân biệt rạch ròi với 2 ref (để không lạc đề)

| Trục | Paperclip | Mission Control | **Armarius** |
|---|---|---|---|
| Bài toán | Vận hành 1 công ty agent | Quản lý agent OpenClaw | **Cộng tác cross-team** |
| Agent biết nhau? | Không | Một phần (board) | **Có (directory+mention)** |
| Workspace chung | Không (attachment lẻ) | Không | **Shared Artifact Store bắt buộc** |
| Multi adapter | Có (mạnh) | Không (chỉ OpenClaw) | **Có, ưu tiên gateway** |
| Scheduler | Tự (heartbeat) | Dựa OpenClaw | **Tự chủ + watchdog** |
| Onboard project | — | Agent tự hỏi | **Roster gate / vetting** |

---

## 11. Quyết định cần chốt (mở để bàn tiếp)

1. **Ngôn ngữ/stack core:** TypeScript (gần Paperclip, tái dùng adapter) vs Python/FastAPI (gần Mission Control, clean domain)?
2. **Shared Artifact Store** dùng gì: S3-compatible / volume / **git repo per project** (git hợp với artifact code + có version + review)?
3. ~~**Hermes remote khả thi tới đâu?**~~ ✅ **ĐÃ GIẢI (§5.3):** Hermes có HTTP gateway đầy đủ (`/v1/runs` + SSE + approval), resume session bền qua `session_id`+`session_key`. Chọn `hermes_gateway` (remote) làm adapter tham chiếu, không cần `hermes_local`.
4. **Mức "vetting" agent vào roster:** owner confirm thủ công, hay capability probe tự động, hay cả hai?
5. **Realtime giữa agent:** chỉ mention-based wakeup (đơn giản, rẻ) hay cần kênh streaming WS (phức tạp hơn)?
6. **Phạm vi MVP** (xem §12).

---

## 12. Lộ trình đề xuất (phased)

**Phase 0 — Walking skeleton**
- Workspace/Project/Task/Thread CRUD + board chat + adapter **`hermes_gateway`** (đã có instance chạy local `:8642` để thử ngay).
- Session store (§4) + wake engine tối thiểu: **event-wake** (assign/on_demand) (§4.3).
- **Tee luồng SSE `/v1/runs/{id}/events` → run-log + live view** (§8.1) — thấy agent chạy ngay trên dashboard mình.
- Shared Artifact Store + skill `publish_artifact`.

**Phase 1 — Cộng tác thật**
- Agent Directory + `@mention` → event-wake (§3, §4.3).
- Invite + skill install (§6.1/6.2).
- Self/liveness-wake: watchdog + continuation + status-gating (§4.3) + coalescing (§7).

**Phase 2 — Governance & multi-runtime**
- Roster/role gate + vetting (§6.3).
- Adapter `hermes_gateway` (đã verify §5.3 — làm trước, dễ nhất) + `openclaw_gateway` hoàn chỉnh.
- Approval engine + patron inbox (§8) — ghép thẳng `/v1/runs/{id}/approval` của Hermes.

**Phase 3 — Nâng cao**
- Websocket/streaming adapter (`gateway_ws` + session broker).
- Capability probe tự động, backpressure theo gateway.

---

*Trạng thái: bản nháp brainstorm. §4, §5 đã đối chiếu code thật của **Paperclip** (`agent_task_sessions`, `openclaw-gateway/execute.ts`) và **Hermes Agent v0.17.0** (`gateway/platforms/api_server.py`); §3, §6, §7 là đề xuất mới của Armarius cần thống nhất trước khi code.*

---

## Changelog
- **2026-06-21:** Verify Hermes Agent bằng source thật (instance chạy local `:8642`). Bổ sung §5.3 (Hermes Gateway), bảng ánh xạ session §4.2, đóng open-question #3. Kết luận: chọn `hermes_gateway` làm adapter tham chiếu.
- **2026-06-21 (2):** Chốt **§4.3 Wake model** sau khi đối chiếu `heartbeat.ts`/`run-liveness.ts`/`task-watchdogs.ts`/`run-liveness-continuations.ts`: chỉ **event-wake + self/liveness-wake** (gated theo task-status × run-status + schedule), **bỏ hẳn global timer "dạo việc"**; nguyên tắc "bóng ở chân ai" + "task là nguồn sự thật, session chỉ là tiện ích". Thêm **§8.1 Observability** (tee luồng event SSE/WS qua adapter → dashboard Armarius; Hermes emit event có tên sẵn). Cập nhật sơ đồ §9 + roadmap §12.
