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

---

## 6. Cài thêm kỹ năng cho agent đã onboard

Khi Patron gán thêm kỹ năng cho một agent **đã kết nối**, hệ thống dựng một prompt cài kỹ năng riêng
(`build_skill_install_prompt`) và đẩy qua gateway của agent — tương tự STEP 3 của prompt mời, nhưng gửi
độc lập sau này. Điểm cuối: `POST /v1/workspaces/{ws}/mariuses/{m}/install-skills`.

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
