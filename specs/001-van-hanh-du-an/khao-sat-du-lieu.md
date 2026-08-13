# Khảo sát trước khi siết — Đợt 1

**Ngày**: 2026-07-31 · **Việc**: T001, T002, T003 của [tasks.md](./tasks.md)

Chạy trên cơ sở dữ liệu thật của bản dựng cục bộ (`docker compose`, PostgreSQL). Mục đích: biết mình đang
đứng ở đâu **trước khi** siết bảng chuyển trạng thái và đổi lược đồ, để sau này phân biệt được "đỏ đúng vì
luật mới" với "đỏ vì mình làm hỏng".

---

## T001 — Dữ liệu thật có gì đáng lo

### Đầu việc

| Chỉ mục | Số | Ý nghĩa |
|---|---|---|
| Tổng đầu việc | 12 | |
| Đang *xong* | 1 | |
| *Xong* mà **không có thành phẩm** | **0** | Cổng Done chưa bị lách lần nào — Hiến pháp II an toàn |
| *Chờ rà soát* mà không có thành phẩm | **0** | |
| *Xong* có dấu `in_progress_at` | **0** | Không đầu việc nào đi thẳng *đang làm → xong* |
| Mô tả chi tiết còn trống | 5 | |
| **Đã gán người mà mô tả trống** | **1** | Cổng mô tả của Đợt 2 (FR-029) sẽ chặn đúng một đầu việc này |
| Có định nghĩa hoàn thành | 1 | Đợt 2 nâng thành danh sách tiêu chí — chỉ một chuỗi phải chuyển |

Phân bố trạng thái: `backlog` 5 · `todo` 3 · `in_review` 1 · `in_progress` 1 · `blocked` 1 · `done` 1.

**Kết luận về rủi ro "Cao" mà [plan.md](./plan.md) nêu**: bỏ đường *đang làm → xong* **không đụng dữ liệu
hiện có**. Không có đầu việc nào đã đi đường đó. Rủi ro thật nằm ở bài kiểm, không nằm ở dữ liệu.

> Lưu ý phải nói thẳng: hiện **chưa có bảng lịch sử chuyển trạng thái** nào — đó chính là thứ T005–T014 dựng
> lên. Nên con số "đi thẳng *đang làm → xong*" là suy từ dấu `in_progress_at` và `completed_at`, không phải
> đọc từ vết. Với 12 đầu việc thì suy được; nếu sau này chạy lại trên dữ liệu lớn thì phải đọc nhật ký mới.

### Dự án

| Chỉ mục | Số |
|---|---|
| Tổng dự án | 23 |
| Đang ở `setup` | **23** |
| Đang ở `active` hoặc `archived` | 0 |
| Mang cờ `require_approval_for_done` trong thiết lập | 23 |
| Mang công tắc `yolo_mode` trong thiết lập | 14 |

**Kết luận về di trú giai đoạn**: không dự án nào từng rời `setup`, nên việc thêm hai giai đoạn và ánh xạ
*lưu trữ → đóng* là **không rủi ro** trên dữ liệu này. Bản di trú vẫn phải viết đủ đường ánh xạ vì máy khác
có thể có dữ liệu khác.

**Về hai cờ bị gỡ ở T036**: cả hai đều gỡ được ngay.

- `require_approval_for_done` là cờ chết, không nơi nào đọc — gỡ là dọn rác.
- `yolo_mode` thì **mã còn đọc** ở khung chat với Trưởng dự án và ở một lối vào mặt agent (xem T003 bên
  dưới). Gỡ khỏi dữ liệu mà chưa gỡ mã thì `settings.get("yolo_mode", False)` trả về `False` — **đúng bằng
  giá trị mặc định**, nên hành vi không đổi. Lối vào bật/tắt còn sống sẽ ghi lại khoá này cho tới khi T062
  của Đợt 2 gỡ hẳn mã. Đây là điểm cần nói rõ trong PR, không phải lỗi.

---

## T002 — Mốc nền trước khi sửa

Đo trên nhánh `main` tại `c1e2a84`, trước dòng mã đầu tiên của Đợt 1.

| Thước | Con số nền |
|---|---|
| Bài kiểm máy chủ | **274 xanh**, 0 đỏ (1 phút 56 giây) |
| Lỗi `mypy` | **165 lỗi ở 44 tệp** (đã có từ trước, không phải do đợt này) |
| Cảnh báo `ruff` máy chủ | **0** — sạch |
| Cảnh báo lint giao diện | **50** (45 lỗi, 5 cảnh báo) |
| `tsc --noEmit` giao diện | **sạch** |

**Cách dùng bảng này**: sau Đợt 1, số bài kiểm phải **tăng** (thêm bài kiểm mới), không được có bài nào từ
274 cái cũ chuyển sang đỏ trừ khi đó là bài dựa vào luật vừa bị siết — trường hợp đó phải sửa bài kiểm theo
luật mới và ghi rõ trong PR. Lỗi `mypy` và cảnh báo lint giao diện phải **không tăng** so với 165 và 50.

### Mốc nền rà mã giao diện đổi ở T173 (2026-08-13)

| Thước | Mốc cũ | **Mốc mới** |
|---|---|---|
| Rà mã giao diện | không được vượt **50** | **phải bằng 0** |

Từ T173, `npm run lint` **thoát 0** và cổng này là cổng đỏ/xanh thật, không còn là cổng "không được tăng".
Con số 50 cũ rơi dần qua T171 và T172; T173 dọn nốt mười lăm cái cuối, tất cả cùng một điều luật
`react-hooks/preserve-manual-memoization`.

Kèm theo đó là một thước **mới**, và nó quan trọng hơn con số rà mã: **bộ biên dịch React bỏ cuộc ở bao
nhiêu chỗ**. Rà mã không báo thước này — nó chỉ báo khi lớp ghi nhớ *viết tay* không giữ được, còn những
cú pháp bộ biên dịch chưa hạ được thì nó im lặng đi qua. Đo bằng cách chạy bộ biên dịch trên toàn bộ
`frontend/src` và đếm sự kiện biên dịch hỏng:

| Thước | Trên `main` trước T173 | Sau T173 |
|---|---|---|
| Hàm được bộ biên dịch tối ưu | 341 | **357** |
| Lần bỏ cuộc | 20 | **2** |
| Tệp có ít nhất một lần bỏ cuộc | 13 | **1** |

Hai lần bỏ cuộc còn lại đều nằm trong `components/ui/calendar.tsx` — một thành phần dựng sẵn **không màn
hình nào nhập vào**, nên nó không bao giờ được vẽ. Sửa nó là sửa một tệp sẽ bị sinh lại, để đổi lấy con số 0
trên một thứ không chạy.

---

## T003 — Ai đang gọi đường tự nhận việc

Rủi ro QĐ-8: Đợt 2 (T070) gỡ đường thợ tự nhận việc. Cần biết trước gỡ thì gãy ở đâu.

| Nơi | Vai trò |
|---|---|
| `backend/armarius/application/use_cases/tasks.py:174` | Bản dựng nghiệp vụ `TaskService.claim` |
| `backend/armarius/presentation/api/agent.py:233` | Lối vào `POST /agent/tasks/{id}/claim` |
| `mcp/src/armarius_mcp/client.py:113` | Lớp trung gian gọi thẳng lối vào trên |
| `mcp/src/armarius_mcp/tools.py:41` | Công cụ `claim_task` phơi ra cho agent |
| `mcp/src/armarius_mcp/server.py:49` | Đăng ký công cụ |
| `mcp/src/armarius_mcp/server.py:31` | **Chuỗi hướng dẫn** bảo agent "gọi `claim_task` trước khi làm" |

**Giao diện không gọi** — không có nơi nào trong `frontend/src` chạm tới đường này.

**Điều phải nhớ khi tới T070**: gỡ lối vào ở máy chủ là gãy **bốn** chỗ trong gói lớp trung gian, kể cả một
câu hướng dẫn đang dạy agent làm đúng cái việc sắp bị cấm. Gói đó có bộ kiểm riêng (`cd mcp && uv run
pytest`) nên phải chạy riêng, bộ kiểm của máy chủ không bắt được.

**Nơi đọc `yolo_mode`** (phục vụ T036 và T062):

- `backend/armarius/domain/entities/project.py:32` — mặc định trong thiết lập dự án
- `backend/armarius/application/use_cases/projects.py:268,277` — bật/tắt
- `backend/armarius/application/use_cases/leader_chat.py:60,205,218,332` — khung chat với Trưởng dự án
- `backend/armarius/domain/services/leader_chat_prompt.py:46,108` — dựng lời nhắc
- `backend/armarius/presentation/api/agent.py:202` — cổng duyệt ở mặt agent
- `backend/armarius/presentation/api/leader_chat.py:46,75,82` và `schemas.py:533,544` — mặt giao tiếp
- `frontend/src/lib/api.ts:659,676` và `components/LeaderChatPanel.tsx:76` — giao diện

Mười lăm chỗ, ba tầng, cộng giao diện. T062 phải rà hết, không để lại cờ chết thứ hai.
