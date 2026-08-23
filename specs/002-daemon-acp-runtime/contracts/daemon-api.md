# Hợp đồng: server ↔ daemon

**Feature**: 002 | **Phase**: 1

Mọi route dưới `/daemon/*` xác thực bằng **token của daemon** (`Authorization: Bearer …`) và **lọc theo
workspace của token ấy**. Chạm sang workspace khác trả `404`, không trả `403` (Điều I).

Chữ trong `reason` và `code` là **mã**, không phải câu cho người đọc — giao diện tự dựng câu qua i18n
(Điều VI + VII).

---

## 1. Nối máy vào workspace — device flow

### `POST /daemon/link/start`

Không cần xác thực. Daemon gọi lúc người dùng chạy `armarius-daemon login`.

```json
→ { "platform": "linux", "daemon_version": "0.1.0", "hostname": "gnust-thinkpad" }
← 200 { "code": "KQ7F-M2XD", "verify_url": "https://…/link", "expires_in": 600, "interval": 5 }
```

### `POST /daemon/link/poll`

Daemon hỏi lại mỗi `interval` giây cho tới khi người dùng duyệt.

```json
→ { "code": "KQ7F-M2XD" }
← 202 { "status": "pending" }
← 200 { "status": "approved", "machine_id": "…", "token": "…", "workspace_id": "…" }
← 410 { "status": "expired" }
```

`token` chỉ hiện **đúng một lần**; server chỉ giữ hash.

### `POST /daemon/token/renew`

```json
→ {}
← 200 { "renewed": true,  "expires_at": "2026-11-19T…" }
← 200 { "renewed": false, "expires_at": "2026-09-20T…" }    ← chưa tới lúc, không phải lỗi
```

**Server là bên quyết** đã tới lúc gia hạn chưa (FR-014d). Daemon gọi theo nhịp bất kỳ, không tự tính hạn
dùng của token mình đang giữ.

---

## 2. Đăng ký chỗ làm

### `PUT /daemon/workplaces`

Daemon gửi toàn bộ những gì nó dò được. Server đồng bộ: cái mới thì thêm, cái mất thì chuyển
`not_ready(cli_removed)` — **không xoá**, vì agent đang buộc vào đó (FR-007).

```json
→ { "workplaces": [
      { "cli_kind": "gemini", "cli_version": "0.4.1", "protocol_family": "acp",
        "capabilities": { "resumable": true, "exposes_tool_args": true, "exposes_tool_result": false } },
      { "cli_kind": "claude_code", "cli_version": "2.1.0", "protocol_family": "one_shot",
        "capabilities": { "resumable": true, "exposes_tool_args": true, "exposes_tool_result": true } }
    ],
    "symlink_capable": true }
← 200 { "workplaces": [ { "id": "…", "cli_kind": "gemini", "ready": true }, … ] }
```

`capabilities` là kết quả **hỏi khả năng thật** (FR-017), không được suy từ tên loại CLI.

### `POST /daemon/heartbeat`

Mỗi 15 giây.

```json
→ { "free_slots": 3, "running": [ "run-uuid-1", "run-uuid-2" ] }
← 200 { "pending_work": true, "cancel": [ "run-uuid-2" ] }
```

`free_slots` là **số chỗ trống hiện tại, mang tính tham khảo**. Server giữ trần và lấy số nhỏ hơn giữa hai
giá trị (FR-008d).

> **Heartbeat KHÔNG phải bằng chứng agent chạy được.** Nó chứng minh liên lạc tới máy. Chỗ làm có sẵn sàng
> hay không là chuyện khác, và `PUT /daemon/workplaces` mới trả lời (FR-055b).

---

## 3. Nhận việc — cửa duy nhất

### `POST /daemon/runs/claim`

**Đây là đường duy nhất một lượt chạy bắt đầu** (FR-053).

```json
→ { "workplace_ids": ["wp-1","wp-2"], "max": 3 }
← 200 { "runs": [ {
      "run_id": "…", "task_id": "…", "workplace_id": "wp-1",
      "run_token": "…",                     ← token của lượt chạy, chỉ hiện một lần
      "claim_expires_at": "2026-08-21T10:02:00Z",
      "session": { "resume": true, "handle": "…" },
      "prompt": "…",                        ← tiếng Anh (Điều VII)
      "skills": [ { "name": "…", "files": { … } } ],
      "callback_base": "https://…/agent"
    } ] }
← 200 { "runs": [] }                        ← không có việc; đây là câu trả lời thường gặp nhất
```

**Bắt buộc ở phía server**: một câu lệnh `atomic compare-and-swap` (xem [research §4](../research.md)).
Cấm `read-then-write`.

**Bắt buộc ở phía daemon**: đúc `run_token` hỏng thì **trả đầu việc về** — cấm chạy bằng token của daemon
(FR-014c).

**`prompt`** — server dựng, bằng tiếng Anh (Điều VII), và **server ghi lại toàn văn ngay tại lời gọi này**
(FR-011a, FR-012a, FR-042). Daemon KHÔNG dựng nội dung và KHÔNG gửi lại; nó chỉ ghi chuỗi này vào đúng tệp
bối cảnh của CLI — `CLAUDE.md`, `AGENTS.md`, … theo bảng ở [research §11](../research.md).

**`skills`** — kế thừa nguyên flow Multica (FR-011b). Kỹ năng đi xuống **ở đây**, không phải agent tự gọi về
lấy. Daemon ghi chúng vào thư mục kỹ năng native của CLI dưới dạng **tệp thật, ghi mới mỗi lượt chạy** —
KHÔNG liên kết ra kho dùng chung, vì nhiều agent dùng chung một chỗ làm (FR-007b).

```json
"skills": [ { "name": "armarius-http", "files": { "SKILL.md": "…", "ref/api.md": "…" } } ]
```

`files` là bản đồ *đường dẫn tương đối → nội dung*. Đường dẫn PHẢI nằm trong thư mục kỹ năng; server từ chối
gói có đường dẫn thoát ra ngoài.

### `POST /daemon/runs/{run_id}/start`

Daemon báo đã dựng xong môi trường và agent bắt đầu chạy.

```json
→ { "session_handle": "…" }
← 200 {}
← 404 {}     ← lượt chạy không còn thuộc máy này (hạn giữ đã hết) — daemon PHẢI dừng và dọn
```

`404` ở đây chính là lưới ở FR-059: một máy đã bị thu hồi mà ngủ dậy muộn thì **không ghi được gì**.

---

## 4. Gửi diễn biến

### `POST /daemon/runs/{run_id}/events`

Gửi theo lô, trong lúc đang chạy (FR-015).

```json
→ { "events": [
      { "seq": 12, "type": "tool.started",
        "payload": { "name": "read_file", "args": { … } },      ← toàn văn tham số
        "redacted": true },
      { "seq": 13, "type": "tool.finished",
        "payload": { "name": "read_file", "summary": "text/plain, 4821 bytes, 3 dòng đầu: …" },
        "truncated": true, "original_byte_size": 4821,
        "omission_reason": "truncated_by_policy" }
    ] }
← 200 { "accepted_through": 13 }
```

**Ràng buộc cứng**:
- **Toàn văn kết quả công cụ không bao giờ có mặt trong body này** (FR-043a). Chỉ bản rút gọn.
- Che bí mật đã làm **xong ở phía daemon** trước khi gửi (FR-048). Server không che hộ.
- `seq` tăng đơn điệu trong một lượt chạy, không trùng (FR-045).

### `POST /daemon/runs/{run_id}/finish`

```json
→ { "status": "completed" | "failed", "error_code": "…", "session_handle": "…", "usage": { … } }
← 200 {}
```

Server **thu hồi token của lượt chạy ngay tại đây** (FR-014b), và đầu việc phải có một động cơ đẩy sống
ngay lập tức, không đợi vòng quét (FR-030a).

---

## 5. Đường đẩy

### `GET /daemon/events` — SSE

Daemon giữ mở. Server đẩy xuống khi có việc mới cho máy này.

```
event: pending_work
data: {"workplace_id":"wp-1"}
```

**Tin này chỉ là tín hiệu.** Nó không mang việc và không phải lệnh chạy (FR-055a). Daemon nhận được thì đi
gọi `POST /daemon/runs/claim` — đúng cái cửa nó vẫn gọi theo nhịp poll.

Mất kết nối này **không mất việc**: nhịp poll 5 giây là fallback (FR-055d).
