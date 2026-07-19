# 02 — Mời agent (operator-invite) & onboarding dự án

> Cách một agent gia nhập workspace, và cách quản gia (Workspace Agent) dẫn dắt lập dự án qua hội thoại.
> Phản ánh mã nguồn ngày 18/07/2026 (issue #63 — operator-invite; #61 — onboarding v3).
>
> Nhãn: **[ĐÚNG-NHƯ-CODE]** / **[ĐÍCH-CẦN-SỬA]** như ở [README](README.md).

---

## 1. Bối cảnh — vì sao đổi sang operator-invite

Mô hình **cũ** (enroll-and-wait): operator dán một prompt mời → agent tự gọi `POST /agent/enroll` → chờ
Patron bấm duyệt → nhận token. Hệ quả chí mạng: Armarius **không bao giờ biết gateway của agent**, nên
`adapter_config` rỗng ⇒ mọi lần wake sau (`POST {gateway}/v1/runs`) **không tới được agent**. Đây là gốc
khiến onboarding v3 "chạy trên giấy nhưng không chạy thật" và Workspace Agent luôn hiện OFFLINE.

Giải pháp đã chốt (issue #63): **operator tự nhập gateway của agent**. Việc operator nhập gateway **chính
là sự phê duyệt** — nên token đúc ngay lúc mời, `adapter_config` được điền tại nguồn, và hệ thống tự đẩy
prompt cài đặt tới agent. Không còn bước enroll, không còn bước duyệt tay.

---

## 2. Luồng mời một agent  [ĐÚNG-NHƯ-CODE]

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
   nhúng thẳng token đã đúc và trỏ agent tới `GET /agent/me` (không có bước enroll).
7. **Đẩy prompt (fire-and-forget)** — `push_setup(marius_id, prompt=...)` gửi qua adapter và trả
   `send_status`.
8. **Phát sự kiện** — `control_bus.publish("ws:{workspace_id}", "marius.status_changed", {status:
   "approved", send_status})` để giao diện cập nhật tức thì.
9. **Trả về** `MariusCreatedOut` (hồ sơ agent) **kèm `send_status`** — nhưng **không** lộ token cho operator.

### 2.1 "Đã gửi" nghĩa là gì — fire-and-forget  [ĐÚNG-NHƯ-CODE]

`push_setup` gọi `adapter.dispatch(ctx)`. **"sent" = gateway đã NHẬN lệnh chạy**, KHÔNG phải "agent đã
làm xong lượt". Cố tình **không chờ** run kết thúc: agent tự chứng minh còn sống ngoài luồng bằng cách gọi
`/agent/me` (⇒ ONLINE); chặn lời mời để đợi cả lượt agent sẽ quay vòng tới watchdog và báo lỗi giả cho một
run vốn đã tới nơi.

- Kết quả `RUNNING`/`QUEUED`/`COMPLETED` ⇒ `send_status = "sent"`.
- Chỉ `FAILED`/`TIMED_OUT` hoặc ném ngoại lệ ⇒ `send_status = "send_failed"`.
- **Gửi thất bại KHÔNG chí mạng**: bản ghi agent **đã** `APPROVED`; operator chỉ cần bấm "Thử lại" (gọi
  lại `push_setup`, **không đúc token mới**).

### 2.2 Bảng trạng thái HTTP  [ĐÚNG-NHƯ-CODE]

| Tình huống | Mã | Ghi chú |
|---|---|---|
| Workspace không thuộc người gọi | 404 | đa tenant nghiêm ngặt |
| Adapter lạ | 400 | `UnknownAdapter` |
| Gateway không kết nối được | 422 | `GatewayUnreachable`, chưa ghi gì |
| Tạo thành công | 201 | kèm `send_status` |
| Tạo xong nhưng đẩy prompt hỏng | 201 | `send_status = "send_failed"`, agent vẫn sống, cho "Thử lại" |

---

## 3. Nội dung prompt cài đặt  [ĐÚNG-NHƯ-CODE]

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

### 3.1 Tàn dư enroll-and-wait đã gỡ — [ĐÚNG-NHƯ-CODE]

Toàn bộ đường enroll-and-wait **đã gỡ sạch ở issue #97**: hai điểm cuối `POST /agent/enroll` +
`POST /agent/claim` (đã ra khỏi route từ trước), nhánh STEP-0 trong `build_invite_prompt`, trường
`Marius.enrollment_code` (entity + cột CSDL `mariuses.enrollment_code`, di trú `f3a1b8c5d2e7`), và công cụ
`enroll`/`claim` ở MCP. Operator-invite (#63) mint `agent_token` ngay tại lúc mời, nhúng thẳng vào prompt
đẩy qua gateway, trỏ agent tới `GET /agent/me` — không còn cổng enroll/approve.

`InviteStatus.PENDING_REVIEW` **được giữ** có chủ đích: nó chỉ còn để `activate` tiếp nhận **hàng legacy**
từ thời enroll (xem `test_invite_fsm.py`); `InviteService.invite` luôn dùng `INVITED`→`APPROVED` và không
bao giờ gán `PENDING_REVIEW` cho bản ghi mới. Xem thêm [07-api-contract.md](07-api-contract.md) §8.

---

## 4. Quản gia workspace (Workspace Agent)  [ĐÚNG-NHƯ-CODE]

`application/use_cases/workspace_agent.py`. Quản gia là một `Marius` được chỉ định làm host của workspace —
người chào Patron và chạy onboarding. **Nguồn sự thật là con trỏ** `workspace.workspace_agent_id` (không
phải chuỗi vai trò).

- `designate(workspace_id, marius_id)`: trao ghế host cho một agent; host cũ (nếu có) bị **hạ xuống** agent
  thường (xoá chuỗi role, giữ token/task) — không bao giờ bị thu hồi. Idempotent nếu đã giữ ghế.
- `ensure_workspace_agent(workspace_id)`: **chỉ tra cứu**, trả host đã chỉ định hoặc `None`. Dưới
  operator-invite, host **không bao giờ tự tạo**: chỉ tồn tại nếu operator đã mời một agent (kèm gateway) và
  tick "Make Workspace Agent". Không còn cái vỏ agent-không-cấu-hình-không-token như trước.

---

## 5. Onboarding dự án qua hội thoại  [ĐÚNG-NHƯ-CODE]

`application/use_cases/onboarding_session.py`. Quản gia phỏng vấn Patron để dựng một `Project` thật
(`OnboardingSession`: `open → finalized | abandoned`, xem [01-domain.md](01-domain.md) §5.7).

- Mỗi lượt `start`/`answer` **đánh thức quản gia thật** qua adapter (session
  `armarius:onboarding:{session_id}`), thời hạn có biên.
- **Quản gia là agent online thật** (onboarding v3): không còn "bộ não tất định" chạy kịch bản trong tiến
  trình. Nếu quản gia **offline hoặc wake hỏng** ⇒ **bỏ dở phiên + `WorkspaceAgentUnavailable` → HTTP 409**,
  **không có phương án dự phòng**. Runtime phía sau gateway là việc của operator.
- Chỉ trạng thái `ONLINE`/`WORKING` mới coi là "sẵn sàng" để nhận lượt; `CHECKING`/`OFFLINE` ⇒ thất bại
  nhanh thay vì xếp hàng chờ.

---

## 6. Cài kỹ năng cho agent đã onboard (#74) — [ĐÍCH-CẦN-SỬA] (đang dở, tạm gác)

Có `build_skill_install_prompt` (gửi riêng cho agent đã kết nối khi Patron gán thêm kỹ năng mới). Nhưng
tính năng #74 **mới xây một nửa và đang gác** (theo chủ dự án): chưa gắn vào giao diện, chưa có vòng
xác nhận "đã cài xong" (gửi đi chỉ nghĩa là gateway đã nhận, KHÔNG phải đã cài). **Đích:** hoàn thiện hoặc
gỡ; hiện **không** coi là đã xong.

---

## 7. Tiêu chí nghiệm thu

Coi là **đúng-như-code** khi:

1. Mời một agent với gateway hợp lệ ⇒ agent về `APPROVED`, `adapter_config` có `base_url`+`api_key`,
   `send_status = "sent"`, và operator **không** nhìn thấy token trong phản hồi.
2. Gateway sai ⇒ 422 và **không** có bản ghi agent nào được tạo.
3. Adapter lạ ⇒ 400.
4. Sau khi agent gọi `GET /agent/me` một lần ⇒ agent chuyển ONLINE (xem [04-liveness.md](04-liveness.md)).
5. Mời agent kèm "Make Workspace Agent" ⇒ `workspace.workspace_agent_id` trỏ tới agent đó; onboarding tiếp
   diễn được.
6. Quản gia offline khi `start`/`answer` ⇒ HTTP 409, phiên bị bỏ dở, không có dự phòng.

**Đích Giai đoạn 2** (mục §6): hoàn thiện hoặc gỡ luồng cài kỹ năng #74. (Đường enroll/claim đã gỡ sạch ở
#97 — xem §3.1.)
