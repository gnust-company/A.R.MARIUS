# 07 — Danh mục điểm cuối API (endpoint)

> Danh mục các điểm cuối HTTP thật đang có (`backend/armarius/presentation/api/*.py`). Đây là bản tra cứu;
> hành vi chi tiết nằm ở các file 01–06.

Ba nhóm theo đối tượng gọi:

- **`/auth/*`** — xác thực người dùng (Patron).
- **`/v1/*`** — API cho web app (Patron), yêu cầu đăng nhập; mọi route giới hạn theo workspace của chủ.
- **`/agent/*`** — API cho agent gọi ngược, xác thực bằng `agent_token` (Bearer), phạm vi theo workspace của token.

---

## 1. Xác thực — `/auth`

| Method | Path | Việc |
|---|---|---|
| POST | `/auth/register` | Đăng ký Patron (tạo tài khoản + workspace cá nhân) → 201 |
| POST | `/auth/login` | Đăng nhập → access + refresh token |
| POST | `/auth/refresh` | Làm mới access token |
| GET | `/auth/me` | Hồ sơ người dùng hiện tại |

## 2. Workspace, agent, kỹ năng, nhãn — `/v1`

| Method | Path | Việc |
|---|---|---|
| POST | `/v1/workspaces` | Tạo workspace |
| GET | `/v1/workspaces` | Liệt kê workspace của chủ |
| PATCH | `/v1/workspaces/{ws}` | Sửa workspace |
| DELETE | `/v1/workspaces/{ws}` | Xoá workspace |
| POST | `/v1/workspaces/{ws}/mariuses` | **Mời agent** (operator-invite) → 201 + `send_status` (xem [02-invite.md](02-invite.md)) |
| GET | `/v1/workspaces/{ws}/mariuses` | Danh bạ agent trong workspace |
| GET | `/v1/workspaces/{ws}/mariuses/{m}/runs` | Lịch sử chạy của một agent |
| PATCH | `/v1/workspaces/{ws}/mariuses/{m}` | Sửa agent |
| POST | `/v1/workspaces/{ws}/mariuses/{m}/designate` | Phong agent làm quản gia (Workspace Agent) |
| POST | `/v1/workspaces/{ws}/mariuses/{m}/install-skills` | Đẩy prompt cài kỹ năng mới cho agent đã kết nối (xem [02-invite.md](02-invite.md) §6) |
| DELETE | `/v1/workspaces/{ws}/mariuses/{m}` | Gỡ agent → 204 |
| GET | `/v1/workspaces/{ws}/labels` · POST | Nhãn task (xem/tạo) |
| GET | `/v1/workspaces/{ws}/skills` | Kho kỹ năng (Skill Shop) |
| GET/PUT/DELETE | `/v1/workspaces/{ws}/skills/{id}` | Xem/sửa/xoá một kỹ năng |
| POST | `/v1/workspaces/{ws}/skills/manual` | Tạo kỹ năng thủ công |
| POST | `/v1/workspaces/{ws}/skills/import` | Nhập kỹ năng từ GitHub |

## 3. Dự án, roster, ghế — `/v1`

| Method | Path | Việc |
|---|---|---|
| GET | `/v1/workspaces/{ws}/projects` · POST | Liệt kê / tạo dự án (create áp luật roster) |
| GET | `/v1/projects/{p}` | Chi tiết dự án |
| PATCH | `/v1/projects/{p}` | Sửa brief/settings dự án |
| DELETE | `/v1/projects/{p}` | Xoá dự án → 204 |
| GET | `/v1/projects/{p}/roster` | Roster: role + ghế đã lấp + agent ngồi ghế (kèm liveness) |
| POST | `/v1/projects/{p}/roles` | Thêm role → 201 |
| PATCH/DELETE | `/v1/projects/{p}/roles/{role_key}` | Sửa/xoá role (xoá chỉ khi không còn ai ngồi) |
| POST | `/v1/projects/{p}/grant` | **Cấp ghế** cho agent (hệ-thống) → 201 |
| DELETE | `/v1/projects/{p}/grant` | Thu ghế |
| GET | `/v1/projects/{p}/agents` | Danh sách người tham gia dự án (ghế đã cấp) |

## 4. Task, thread, hiện vật, đánh thức — `/v1`

| Method | Path | Việc |
|---|---|---|
| GET | `/v1/projects/{p}/tasks` · POST | Liệt kê / **thêm task tay** (Patron) → 201 |
| GET | `/v1/tasks/{t}` | Chi tiết task |
| POST | `/v1/tasks/{t}/assign` | Gán agent (→ wake `ASSIGNMENT`) |
| POST | `/v1/tasks/{t}/status` | Chuyển trạng thái (áp cổng DONE **và cổng phụ thuộc**) |
| GET/POST | `/v1/tasks/{t}/dependencies` | Liệt kê / thêm cạnh `blocked_by` (`{blocks_task_id}`) → 201; tự-trỏ/trùng → 422 |
| DELETE | `/v1/tasks/{t}/dependencies/{b}` | Gỡ cạnh `blocked_by` → 204 |
| POST | `/v1/tasks/{t}/next-action` | Ghi gợi ý tiếp việc |
| GET/POST | `/v1/tasks/{t}/comments` | Thread task (xem/gửi tin, @mention → wake) |
| GET/POST | `/v1/tasks/{t}/artifacts` | Hiện vật của task (xem/publish) |
| POST | `/v1/tasks/{t}/wake` | Đánh thức thủ công (on-demand) → 202 |

## 5. Chat với Leader & YOLO — `/v1`

| Method | Path | Việc |
|---|---|---|
| GET | `/v1/projects/{p}/leader-chat` | Lấy/mở cuộc chat với Leader + ngữ cảnh sống (leader_online, yolo) |
| POST | `/v1/projects/{p}/leader-chat/messages` | Gửi tin cho Leader (409 nếu offline/đang bận — turn-taking) |
| PUT | `/v1/projects/{p}/yolo-mode` | Bật/tắt YOLO |
| GET | `/v1/projects/{p}/proposed-tasks` | Danh sách draft Leader đề xuất chờ duyệt |
| POST | `/v1/tasks/{t}/approve` | Duyệt draft (`draft → todo` + wake) |
| POST | `/v1/tasks/{t}/reject` | Từ chối draft (`draft → cancelled`) |

## 6. Trace & luồng sự kiện (SSE) — `/v1`

| Method | Path | Việc |
|---|---|---|
| GET | `/v1/tasks/{t}/runs` | Lịch sử run của task |
| GET | `/v1/runs/{r}` · `/v1/runs/{r}/events` | Chi tiết run + nhật ký sự kiện bền |
| GET | `/v1/runs/{r}/stream` | SSE trace trực tiếp một run |
| GET | `/v1/workspaces/{ws}/events` | SSE mặt phẳng điều khiển workspace |
| GET | `/v1/tasks/{t}/stream` | SSE trace của một task (phòng cộng tác) |
| GET | `/v1/projects/{p}/leader-chat/stream` | SSE chạy chữ của Chat với Leader |

Chi tiết kênh: [06-artifacts-sse.md](06-artifacts-sse.md). **Chỉ web app đọc SSE; agent không đọc SSE.**

## 7. Onboarding dự án qua hội thoại — `/v1`

| Method | Path | Việc |
|---|---|---|
| POST | `/v1/workspaces/{ws}/onboarding` | Bắt đầu phiên onboarding (đánh thức quản gia; 409 nếu quản gia offline) |
| GET | `/v1/workspaces/{ws}/onboarding/active` | Phiên đang mở (nếu có) |
| GET | `/v1/onboarding/{s}` | Chi tiết phiên |
| POST | `/v1/onboarding/{s}/answer` | Patron trả lời (đánh thức quản gia lượt tiếp) |
| POST | `/v1/onboarding/{s}/finalize` · `/abandon` | Chốt thành dự án / bỏ dở |

## 8. API cho agent gọi ngược — `/agent`

Xác thực bằng `agent_token` (Bearer). Mọi route giới hạn theo workspace của token (task/dự án chéo workspace
đọc là "không tìm thấy").

| Method | Path | Việc |
|---|---|---|
| GET | `/agent/me` | Hồ sơ mình + danh bạ đồng đội; **gọi cái này = một tín hiệu liveness** (→ ONLINE) |
| GET | `/agent/skills` · `/agent/skills/{slug}` | Liệt kê / tải cây file một kỹ năng được gán |
| POST | `/agent/projects/{p}/tasks` | **Công cụ tạo-task của Leader** (draft hay live tuỳ YOLO) → 201 |
| GET | `/agent/tasks/{t}` | Đọc task |
| POST | `/agent/tasks/{t}/claim` | Agent tự nhận task |
| POST | `/agent/tasks/{t}/comment` | Đăng tin vào thread (@mention → wake) → 201 |
| POST | `/agent/tasks/{t}/status` | Chuyển trạng thái task (áp cổng DONE) |
| POST | `/agent/tasks/{t}/next-action` | Ghi gợi ý tiếp việc |
| POST | `/agent/tasks/{t}/artifact` | Publish hiện vật (file/link) → 201 |
| POST | `/agent/onboarding/{s}/question` · `/complete` | Quản gia đăng câu hỏi / chốt onboarding |

## 9. Meta & sức khoẻ

| Method | Path | Việc |
|---|---|---|
| GET | `/healthz` · `/health` | Thăm sức khoẻ (cũng là endpoint gateway-health dùng cho probe) |
| GET | `/v1/meta` · `/v1/adapters` | Thông tin build / danh sách adapter |

---

## 10. Ghi chú & tiêu chí nghiệm thu

- **Có hai điểm cuối tạo task**: `POST /v1/projects/{p}/tasks` (Patron thêm tay) và
  `POST /agent/projects/{p}/tasks` (công cụ của Leader trong Chat với Leader). Đây là chủ ý, không phải trùng lặp.
- Tiêu chí nghiệm thu: mọi hàng trong §1–§9 gọi được đúng phương thức/đường dẫn nêu trên; route `/v1/*`
  chặn truy cập chéo chủ sở hữu (404); route `/agent/*` yêu cầu Bearer token và chặn chéo workspace.
