# 02 — Mời agent (operator-invite) & onboarding dự án

> Cách một agent gia nhập workspace theo mô hình operator-invite, và cách quản gia (Workspace Agent) dẫn
> dắt lập dự án qua hội thoại.

---

## 1. Nguyên tắc operator-invite

**Operator tự nhập gateway của agent, và việc đó chính là sự phê duyệt.** Nhờ vậy token được đúc **ngay lúc
mời**, `adapter_config` (gateway `base_url` + `api_key`) được điền tại nguồn, và hệ thống tự đẩy prompt cài
đặt tới agent. Không có bước enroll, không có bước duyệt tay riêng.

Điều then chốt operator-invite bảo đảm: **Armarius luôn biết gateway của agent**. Nếu `adapter_config` rỗng,
mọi lần wake sau (`POST {gateway}/v1/runs`) sẽ không tới được agent — nên gateway phải được nắm ngay từ lúc
mời, không để agent tự khai sau.

---

## 2. Luồng mời một agent

Điểm cuối: `POST /workspaces/{workspace_id}/mariuses` (`presentation/api/workspaces.py:invite_marius`).
Nghiệp vụ: `application/use_cases/enrollment.py::InviteService`.

Các bước, đúng thứ tự:

1. **Kiểm quyền sở hữu workspace** — không phải chủ ⇒ coi như không tìm thấy (404).
2. **Chọn adapter** — `registry.get(adapter_type)`; loại lạ ⇒ `UnknownAdapter` → **HTTP 400**.
3. **Thử với gateway (probe)** — `adapter.test_environment({base_url, api_key})`. Không đạt ⇒
   `GatewayUnreachable` → **HTTP 422**, và **chưa ghi gì vào cơ sở dữ liệu**.
4. **Đúc token + tạo agent** — dựng `Marius` với `adapter_config = {base_url, api_key}`, gọi
   `marius.activate(token, now)` (⇒ trạng thái `APPROVED`), lưu + commit. Agent **sống ngay** khi trả về.
5. **(Tuỳ chọn) Phong quản gia** — nếu operator tick "Make Workspace Agent" (`is_workspace_agent`), gọi
   `workspace_agent.designate(...)` để trao ghế host (host cũ, nếu có, bị hạ xuống agent thường).
6. **Dựng prompt cài đặt** — `build_invite_prompt(marius, public_api_url, workspace_name, skills)`. Prompt
   nhúng thẳng token đã đúc và trỏ agent tới `GET /agent/me`.
7. **Đẩy prompt (fire-and-forget)** — `push_setup(marius_id, prompt=...)` gửi qua adapter và trả
   `send_status`.
8. **Phát sự kiện** — `control_bus.publish("ws:{workspace_id}", "marius.status_changed", {status:
   "approved", send_status})` để giao diện cập nhật tức thì.
9. **Trả về** `MariusCreatedOut` (hồ sơ agent) **kèm `send_status`** — nhưng **không** lộ token cho operator.

### 2.1 "Đã gửi" nghĩa là gì — fire-and-forget

`push_setup` gọi `adapter.dispatch(ctx)`. **"sent" = gateway đã NHẬN lệnh chạy**, KHÔNG phải "agent đã
làm xong lượt". Cố tình **không chờ** run kết thúc: agent tự chứng minh còn sống ngoài luồng bằng cách gọi
`/agent/me` (⇒ ONLINE); chặn lời mời để đợi cả lượt agent sẽ quay vòng tới watchdog và báo lỗi giả cho một
run vốn đã tới nơi.

- Kết quả `RUNNING`/`QUEUED`/`COMPLETED` ⇒ `send_status = "sent"`.
- Chỉ `FAILED`/`TIMED_OUT` hoặc ném ngoại lệ ⇒ `send_status = "send_failed"`.
- **Gửi thất bại KHÔNG chí mạng**: bản ghi agent **đã** `APPROVED`; operator chỉ cần bấm "Thử lại" (gọi
  lại `push_setup`, **không đúc token mới**).

### 2.2 Bảng trạng thái HTTP

| Tình huống | Mã | Ghi chú |
|---|---|---|
| Workspace không thuộc người gọi | 404 | đa tenant nghiêm ngặt |
| Adapter lạ | 400 | `UnknownAdapter` |
| Gateway không kết nối được | 422 | `GatewayUnreachable`, chưa ghi gì |
| Tạo thành công | 201 | kèm `send_status` |
| Tạo xong nhưng đẩy prompt hỏng | 201 | `send_status = "send_failed"`, agent vẫn sống, cho "Thử lại" |

---

## 3. Nội dung prompt cài đặt

`build_invite_prompt` (`application/use_cases/onboarding.py`). Đây là bước **kết nối một lần**, cố ý
**không** có task, không có gì phải nhớ về sau — việc thật đến ở một phiên wake riêng mang đủ ngữ cảnh.

- **STEP 1 · Lưu thông tin đăng nhập** — agent tạo file `~/.armarius/{slug-workspace}_{ten-agent}.json`
  (đường dẫn từ `credential_file_for`, quyền 0600), chứa `agent_token` + `api_base_url`. Kỹ năng của agent
  đọc token từ file này. Một agent nhiều workspace ⇒ mỗi workspace một file.
- **STEP 2 · Xác nhận đang online** — `GET /agent/me` với Bearer token. `200` kèm hồ sơ + danh bạ đồng đội
  = đã kết nối; `401` = token sai.
- **STEP 3 · Cài kỹ năng** — với mỗi skill được gán: `GET /agent/skills/{slug}` (một cuộc gọi JSON có xác
  thực trả cả cây file). Hướng dẫn cài **khác nhau theo runtime** (`adapter_type`): Hermes dùng công cụ
  `skill_manage` hoặc `/learn`; Echo ghi file vào `~/.echo/skills/`; Claude Code dùng MCP hoặc
  `~/.claude/skills/`.

### 3.1 Phần chân token là HINT chung, không lệnh

Mọi prompt hệ thống→agent (mời, cài skill, onboarding, wake task, leader-chat) đều ghép thêm
`agent_prompt_footer` (`domain/services/agent_prompt.py`) — một **gợi ý nhẹ, trung lập runtime**: credential
(`agent_token` + `api_base_url`) nằm ở `{location}`; **đọc khi nào chưa có token trong tay**, dùng `cat` hay
bất kỳ tool đọc file nào cũng được, rồi **dùng lại** cho mọi lệnh gọi — **không bắt agent đọc lại mỗi bước**.
Không nhúng token vào footer (giữ nguyên nguyên tắc token-free), và **không nhét đặc thù runtime** vào đây:
ví dụ cơ chế dedup "File unchanged" riêng của Hermes **không thuộc footer chung** (nếu cần, đặt ở chỗ riêng
của runtime đó). Đây là hạ tầng chung: một sửa ở `agent_prompt_footer` lan ra toàn bộ prompt hệ thống. Footer
cũng giữ **một dòng ngắn chống rò rỉ** — *"Never echo the token into a comment, artifact, or any output"* —
vì `wake_prompt` (task wake) và `leader_chat_prompt` chỉ nhận cảnh báo này qua footer chung (prompt mời có
riêng, còn các lượt wake lặp lại thì phụ thuộc footer).

---

## 4. Quản gia workspace (Workspace Agent)

`application/use_cases/workspace_agent.py`. Quản gia là một `Marius` được chỉ định làm host của workspace —
người chào Patron và chạy onboarding. **Nguồn sự thật là con trỏ** `workspace.workspace_agent_id` (không
phải chuỗi vai trò).

- `designate(workspace_id, marius_id)`: trao ghế host cho một agent; host cũ (nếu có) bị **hạ xuống** agent
  thường (xoá chuỗi role, giữ token/task) — không bao giờ bị thu hồi. Idempotent nếu đã giữ ghế.
- `ensure_workspace_agent(workspace_id)`: **chỉ tra cứu**, trả host đã chỉ định hoặc `None`. Dưới
  operator-invite, host **không bao giờ tự tạo**: chỉ tồn tại nếu operator đã mời một agent (kèm gateway) và
  tick "Make Workspace Agent".

---

## 5. Onboarding dự án qua hội thoại

`application/use_cases/onboarding_session.py`. Quản gia phỏng vấn Patron để dựng một `Project` thật
(`OnboardingSession`: `open → finalized | abandoned`, xem [01-domain.md](01-domain.md) §5.7).

- Mỗi lượt `start`/`answer` **đánh thức quản gia thật** qua adapter (session
  `armarius:onboarding:{session_id}`), thời hạn có biên.
- **Quản gia là agent online thật**: không có "bộ não tất định" chạy kịch bản trong tiến trình. Nếu quản gia
  **offline hoặc wake hỏng** ⇒ **bỏ dở phiên + `WorkspaceAgentUnavailable` → HTTP 409**, **không có phương
  án dự phòng**. Runtime phía sau gateway là việc của operator.
- Chỉ trạng thái `ONLINE`/`WORKING` mới coi là "sẵn sàng" để nhận lượt; `CHECKING`/`OFFLINE` ⇒ thất bại
  nhanh thay vì xếp hàng chờ.
- **Prompt mỗi lượt tự-đủ.** Lời nhắc wake ở **cả `start` lẫn `answer`** mang sẵn **đúng địa chỉ gọi lại +
  khuôn dữ liệu** (nộp câu hỏi / nộp bản nháp) và dặn agent **chỉ làm đúng một việc đó** — không đi nạp cẩm
  nang khác, không gọi địa chỉ nào khác. Nhờ vậy một mô hình yếu cũng không lạc khỏi giao thức giữa chừng.
  Onboarding **không** phải một skill: toàn bộ chỉ dẫn được nhồi vào prompt.
- **Kịch bản field có thứ tự (lượt `start`).** Prompt hướng dẫn không để agent tự do liên tưởng: nó liệt kê
  **đúng các field bản nháp cần, theo thứ tự** — mục tiêu → tên dự án → roster (vai trò người làm) → thước đo
  thành công → ngày mục tiêu → "còn gì nữa không?" — dặn hỏi **mỗi lượt một câu theo thứ tự**, hỏi hết thì nộp
  bản nháp. Một mô hình yếu đi theo kịch bản số thay vì xoay quanh chi tiết triển khai (tính năng, tech stack).
- **Lịch sử hỏi–đáp đầy đủ (lượt `answer`).** Prompt continuation mang theo **toàn bộ các cặp hỏi–đáp đã qua**
  (xây từ `OnboardingSession.transcript`), kèm đáp án mới nhất — đúng kiểu openclaw-mission-control
  (`_build_answer_dispatch_message`) — thay vì chỉ một dòng đáp án lẻ. Agent luôn biết đã thu thập gì, còn
  thiếu field nào, để chọn đúng câu hỏi kế tiếp hoặc nộp bản nháp.
- **Roster chỉ là worker; Project Leader tự thêm.** Agent chỉ liệt kê các role **worker** (Frontend,
  Backend, …). Role **Project Leader** canonical (key `leader`, `is_leader=true`) được `plan_from_collected`
  **luôn inject** — đúng như path tạo project bình thường (`presentation/api/projects.py` inject leader,
  caller gửi worker). Nếu agent yếu đặt nhầm `is_leader=true` hoặc title "Project Leader" trên một role,
  server **bỏ role đó** rồi inject PL canonical, nên `validate_plan` luôn thấy đúng một leader là PL —
  không bao giờ ra project kiểu "Business Analyst làm leader" như trước (#110).
- **Mỗi role BẮT BUỘC có mô tả (strict, mọi tầng).** Không role nào — leader hay worker — được vào roster
  với mô tả rỗng; đây là điều kiện cho [03-roster-wake.md](03-roster-wake.md) §3.1 (prompt wake/leader-chat
  cần mô tả vai trò để hiện). Ép ở **cả ba tầng** (#112):
  - **Schema API** (`RoleIn`/`LeaderIn`/`AddRoleIn`/`OnboardingRosterRoleIn`): `description` `min_length=1` +
    `leader` không còn default rỗng ⇒ thiếu/để trống ⇒ **422 rõ ràng ngay** (agent onboarding POST draft
    thiếu mô tả bất kỳ role nào cũng nhận 422).
  - **Luật miền** (`validate_plan`): sau khi kiểm tra thành phần leader/worker, chặn mọi role mô tả rỗng
    (nêu tên role còn thiếu). `add_role` (không đi qua `validate_plan`) tự guard cùng luật.
  - **Prompt onboarding**: dặn agent viết một câu mô tả cho **mỗi** worker, nói rõ **REQUIRED** (không còn
    fallback tự-suy: draft thiếu mô tả bị từ chối, agent phải sửa rồi POST lại).

---

## 6. Cài thêm kỹ năng cho agent đã onboard

Khi Patron gán/đổi kỹ năng cho một agent **đã kết nối**, hệ thống liên kết kỹ năng vào agent rồi **đẩy một
prompt cài kỹ năng riêng** (`build_skill_install_prompt`) qua gateway — tương tự STEP 3 của prompt mời, nhưng
gửi độc lập về sau. Điểm cuối: `POST /v1/workspaces/{ws}/mariuses/{m}/install-skills` (body `{skill_ids}`).

- **Đẩy được cả kỹ năng đã sửa, không chỉ kỹ năng mới.** Mọi slug trong yêu cầu đều được đẩy lại, kể cả slug
  **đã liên kết** từ trước — nhờ vậy một cẩm nang **sửa nội dung** cũng tới được agent (cài đè bản cũ). Đây là
  điểm khác cốt yếu so với bản cũ (bản cũ chỉ đẩy slug mới thêm, nên cẩm nang vá xong không có đường tới agent).
- **Theo dõi trạng thái cài từng kỹ năng.** Agent giữ `skill_installs`: bản đồ `slug → trạng thái`
  (`pending` | `installed` | `failed`). Khi đẩy: mỗi slug được yêu cầu chuyển **`pending`** (cổng đã nhận lệnh)
  hoặc **`failed`** (cổng từ chối — cho "Thử lại").
- **Vòng xác nhận cài.** Sau khi cài xong mỗi kỹ năng, agent gọi lại `POST /agent/skills/{slug}/installed`
  (thân rỗng) ⇒ slug đó chuyển **`installed`**. Prompt cài có dặn agent làm bước xác nhận này. Chưa xác nhận ⇒
  slug ở nguyên `pending` (không chắc đã cài). Giao diện đọc `skill_installs` để hiện trạng thái từng kỹ năng.
- **"Đẩy" vẫn là fire-and-forget** như [§2.1](#21-đã-gửi-nghĩa-là-gì--fire-and-forget): `send_status` chỉ nói
  cổng đã nhận lệnh, KHÔNG phải agent đã cài xong — xác nhận thật đến ngoài luồng qua vòng trên.

---

## 7. Tiêu chí nghiệm thu

1. Mời một agent với gateway hợp lệ ⇒ agent về `APPROVED`, `adapter_config` có `base_url`+`api_key`,
   `send_status = "sent"`, và operator **không** nhìn thấy token trong phản hồi.
2. Gateway sai ⇒ 422 và **không** có bản ghi agent nào được tạo.
3. Adapter lạ ⇒ 400.
4. Sau khi agent gọi `GET /agent/me` một lần ⇒ agent chuyển ONLINE (xem [04-liveness.md](04-liveness.md)).
5. Mời agent kèm "Make Workspace Agent" ⇒ `workspace.workspace_agent_id` trỏ tới agent đó; onboarding tiếp
   diễn được.
6. Quản gia offline khi `start`/`answer` ⇒ HTTP 409, phiên bị bỏ dở, không có dự phòng.
7. Gán thêm kỹ năng cho agent đã kết nối ⇒ kỹ năng vào `skill_ids`, prompt cài được đẩy, mỗi slug được yêu
   cầu ở `pending` (hoặc `failed` nếu cổng từ chối).
8. Đẩy lại một kỹ năng **đã liên kết** (bản đã sửa nội dung) ⇒ vẫn được đẩy, không bị bỏ qua vì "đã có".
9. Agent gọi `POST /agent/skills/{slug}/installed` ⇒ slug chuyển `installed` và giao diện cập nhật; slug lạ
   hoặc không liên kết với agent ⇒ 404.
10. Prompt hướng dẫn onboarding liệt kê **kịch bản field có thứ tự** (mục tiêu → tên → roster → thước đo →
    ngày mục tiêu → "còn gì nữa"), gắn đúng body bản nháp — không để agent tự do đi lạc sang chi tiết triển khai.
11. Prompt continuation onboarding mang theo **toàn bộ lịch sử các cặp hỏi–đáp đã qua** (từ transcript) cùng
    đáp án mới nhất — không chỉ một dòng đáp án lẻ.
12. `agent_prompt_footer` là **gợi ý nhẹ, trung lập runtime**: nêu `{location}`, dặn đọc khi chưa có token,
    dùng lại, dùng được `cat`; không lệnh đọc mỗi bước, không nhúng token, không đặc thù runtime (không nhắc
    "File unchanged"/dedup của Hermes).
13. Mô tả role **BẮT BUỘC** ở mọi tầng (#112): tạo dự án (tay hoặc qua onboarding) mà một role bất kỳ thiếu
    mô tả ⇒ **từ chối rõ ràng** — schema API trả 422, `validate_plan`/`add_role` ném `InvalidProjectPlan`
    (→ 422). Không có fallback tự-suy; prompt onboarding nêu rõ mô tả là bắt buộc.
