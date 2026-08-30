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

### `GET /v1/machines/link/{code}` — người duyệt xem đang duyệt máy nào

Không phải lối của daemon: **người** gọi, xác thực bằng phiên đăng nhập thường. Bổ sung
2026-08-24 lúc hiện thực T028 — màn hình duyệt ở T031 phải gọi được vào đâu đó, mà cả hợp đồng
lẫn tasks.md đều chưa có lối nào cho nó.

```json
← 200 { "code": "KQ7F-M2XD", "hostname": "gnust-thinkpad", "platform": "linux",
        "daemon_version": "0.1.0", "expires_at": "2026-08-24T…" }
← 404   ← mã không có, hết hạn, hoặc đã dùng rồi
```

Ba giá trị `hostname`/`platform`/`daemon_version` là **lời máy tự khai**, không phải danh tính đã
kiểm chứng. Màn hình phải nói rõ như vậy.

Chỉ người đã đăng nhập mới gọi được: mã ngắn nên đoán mãi cũng ra, và đây đúng là lối sẽ xác nhận
cho kẻ đoán biết là họ đoán trúng.

### `POST /v1/machines/link/{code}/approve` — người duyệt

```json
→ { "workspace_id": "…" }
← 200 { "code": "KQ7F-M2XD", "hostname": "gnust-thinkpad", … }
← 404   ← mã chết, **hoặc** workspace không phải của người gọi (Điều I)
← 409   ← đã có người duyệt mã này rồi
```

Đây là **chỗ duy nhất** một cái máy được nhận vào workspace. Không có lối nào khác, và không có
đường nào cho máy tự nhận mình vào.

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
      { "cli_kind": "gemini", "cli_version": "0.56.0", "protocol_family": "acp",
        "capabilities": { "resumable": false, "exposes_tool_args": false, "exposes_tool_result": false,
                          "unanswered": [ { "capability": "resumable", "reason": "no_probe_for_family" }, … ] } },
      { "cli_kind": "claude_code", "cli_version": "2.1.226", "protocol_family": "one_shot",
        "capabilities": { "resumable": true, "exposes_tool_args": true, "exposes_tool_result": true,
                          "choices": [
                            { "key": "thinking_level", "values": ["low","medium","high","xhigh","max"],
                              "source": "tool_declared" },
                            { "key": "model", "values": ["fable","opus","sonnet"],
                              "source": "tool_examples" } ] } }
    ],
    "symlink_capable": true }
← 200 { "workplaces": [ { "id": "…", "cli_kind": "gemini", "ready": true,
                          "not_ready_reason": null, "machine_name": "gnust-thinkpad" }, … ] }
```

`capabilities` là kết quả **hỏi khả năng thật** (FR-017), không được suy từ tên loại CLI.

**`choices` — bổ sung 2026-08-29 lúc hiện thực T039g (FR-007k).** Thứ người dùng đặt được cho một agent
đặt ở chỗ làm này, và **giá trị nào tool nhận**. Danh sách này là thứ duy nhất quyết ô chọn trên màn hình:
server **không giữ bảng nào theo tên CLI** (Điều III), nó chỉ nhận và chuyển tiếp.

`source` nói **danh sách chắc đến đâu**, và nó không phải trang trí — nó quyết cả cách vẽ lẫn cách chặn:

| `source` | Nghĩa | Hệ quả |
| --- | --- | --- |
| `tool_declared` | tool in ra **cả bộ** | danh sách đóng; giá trị ngoài nó bị **từ chối** (422 `placement_option_value_unsupported`) |
| `tool_examples` | tool kể **vài cái làm ví dụ** | gợi ý cạnh ô nhập; **không** chặn giá trị lạ |
| `known_names` | daemon mang sẵn cho tool không chịu liệt kê | như `tool_declared`; **chỉ được nằm ở daemon** |

Khoá `key` là **tên chung của server** (`model`, `thinking_level`, `service_tier`…), không phải cờ dòng
lệnh — chỉ daemon biết cái nào thành `--effort`. Bộ khoá **khác nhau theo tool**, nên đây là một danh sách
chứ không phải hai trường cố định: Codex có thêm hạng dịch vụ mà Claude Code không có.

Chỗ làm khai `choices` rỗng hoặc thiếu hẳn là **chuyện thường**: không có gì để chọn, agent trên đó chạy
bằng mặc định của chính tool (FR-007k).

**`unanswered` — bổ sung 2026-08-25 lúc hiện thực T034.** Ba khoá boolean là *câu trả lời*; khoá thứ tư
này là danh sách những khả năng **không hỏi được**, mỗi mục một mã lý do (`no_probe_for_family` khi daemon
chưa nói được giao thức của họ ấy — đường ACP dựng ở T066; `probe_failed` khi CLI được hỏi mà không đáp).
Vắng mặt hoặc rỗng nghĩa là hỏi đủ. Không có nó thì "hỏi rồi, CLI bảo không có" và "chưa hỏi được" đọc
giống hệt nhau, mà FR-017 cấm đúng chuyện đó — một phỏng đoán đã ghi vào cơ sở dữ liệu không còn phân biệt
được với một câu trả lời.

**`machine_name`** là `machines.display_name`, để cùng một CLI trên hai máy của một người là hai chỗ làm
phân biệt được bằng mắt (FR-003). **`not_ready_reason`** là mã: `cli_removed` (CLI không còn trên máy —
FR-033) hoặc `link_unsupported` (máy không tạo được liên kết bắt buộc — [research §5](../research.md)).

Lối này **từ chối `409 workplace_reported_twice`** khi một `cli_kind` xuất hiện hai lần trong cùng một
thân yêu cầu: một cái máy quét một `PATH` không thể tìm thấy cùng một CLI hai lần, nên đây là bên gọi
hỏng, và gộp hai mục mâu thuẫn lại là quyết định thay cho bên gọi.

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

> **Nhịp không phải lối duy nhất chứng minh máy còn đó** (FR-004a, bổ sung 2026-08-25). `PUT
> /daemon/workplaces` cũng ghi lại lần liên lạc gần nhất, vì một cái máy đang khai chỗ làm là một cái máy
> đang nói chuyện. Nếu chỉ đọc mỗi cột nhịp thì daemon vừa khởi động — đã nối, đã khai xong, chưa kịp phát
> nhịp vòng đầu — sẽ bị đọc là đã chết.

### `GET /v1/workspaces/{workspace_id}/workplaces` — người chọn chỗ đặt agent

**Bổ sung 2026-08-25 lúc hiện thực T040.** Đây là lối của **người**, không phải của máy: nó nằm dưới
`/v1/…` và dùng thẻ đăng nhập, không dùng token máy. Không gian làm việc không phải của người gọi trả
`404` y hệt không gian không tồn tại (Điều I).

```json
← 200 [ { "id": "…", "cli_kind": "claude_code", "machine_name": "gnust-thinkpad" } ]
```

**Chỉ liệt kê chỗ làm đang sẵn sàng**, nên không có cờ `ready` để vẽ: một chỗ làm không nhận được việc thì
không có lý do gì nằm trong danh sách mà mục đích duy nhất là để chọn (FR-007f). Danh sách **rỗng là câu
trả lời thật**, không phải lỗi — nghĩa là người này chưa nối máy nào, hoặc máy đã nối chưa có agent CLI
nào chạy được.

### `POST /v1/workspaces/{workspace_id}/mariuses` — thêm trường bắt buộc

**Sửa 2026-08-25 lúc hiện thực T039–T040.** Thân yêu cầu tạo agent nay **bắt buộc** có `workplace_id`.
Thiếu nó là `422`; chỉ ra chỗ làm của không gian khác hoặc chỗ làm không tồn tại đều là
`404 placement_not_found` (Điều I); chỉ ra chỗ làm của chính mình nhưng không sẵn sàng là
`400 placement_not_ready` kèm tham số `reason` mang đúng mã ở `workplaces.not_ready_reason`.

Mối buộc ghi vào `agent_workplace_bindings` **trong cùng giao dịch tạo agent**, nên không có khoảnh khắc
nào tồn tại một agent chưa có chỗ làm (FR-007, FR-007f).

> Mã lỗi nói `placement` chứ không nói `workplace` là **cố ý**: tầng nghiệp vụ ném nó, mà tầng ấy bị cấm
> biết chỗ làm là một agent CLI trên một cái máy (Điều III). Câu chữ hiện lên màn hình vẫn là "chỗ làm" —
> cùng một thứ, hai người đọc.

---

## 3. Nhận việc — cửa duy nhất

### `POST /daemon/runs/claim`

**Đây là đường duy nhất một lượt chạy bắt đầu** (FR-053).

```json
→ { "workplace_ids": ["wp-1","wp-2"], "max": 3 }
← 200 { "runs": [ {
      "run_id": "…", "task_id": "…", "project_id": "…", "workplace_id": "wp-1",
      "run_token": "…",                     ← token của lượt chạy, chỉ hiện một lần
      "claim_expires_at": "2026-08-21T10:02:00Z",
      "session": { "resume": true, "handle": "…" },
      "prompt": "…",                        ← tiếng Anh (Điều VII)
      "skills": [ { "name": "…", "files": { … } } ],
      "callback_base": "https://…/agent"
    } ] }
← 200 { "runs": [] }                        ← không có việc; đây là câu trả lời thường gặp nhất
```

**Đã dựng tới đâu (2026-08-26, T045–T047 rồi T056–T058; `project_id` thêm 2026-08-29)**: `run_id`,
`task_id`, `project_id`, `workplace_id`, `run_token`, `claim_expires_at`, `prompt`, `skills`. Còn
thiếu `session` (T039i) và `callback_base` (T061).

`task_id` và `project_id` **đều để trống được**, và cặp ấy là thứ nói lượt chạy này thuộc loại nào
(FR-013d). Máy cần đúng cặp ấy cho một việc: nó quyết **bộ lệnh** máy trao cho agent. Một cái máy chỉ
được cho mã lượt chạy sẽ phải hỏi ngược lại xem lượt chạy này nói về cái gì — và một cái máy phải hỏi
là một cái máy có thể bị trả lời về thứ khác. Chúng **không** trả về rỗng: một `prompt` rỗng thì daemon vẫn ghi ra tệp bối cảnh, và một tệp
bối cảnh rỗng đọc y hệt một tệp bối cảnh đúng.

**Việc không dựng nổi gói thì không được trao đi.** Server dựng thông điệp *sau* khi đổi chủ xong —
dựng nó đọc thêm nửa tá bảng khác, mà làm việc ấy trong lúc còn giữ khoá của cái máy thì mọi cú xin
khác của chính máy ấy phải đợi hết quãng đọc. Nhưng nếu dựng hỏng, hoặc ghi lại hỏng, thì lượt chạy
**quay lại kệ ngay** kèm thu hồi token, chứ không đi xuống dạng nửa vời: máy cầm một lượt chạy không có
chữ nào sẽ ôm chỗ ấy tới lúc hết hạn giữ rồi trả lại đúng thứ nó vừa nhận.

**Bắt buộc ở phía server**: một câu lệnh `atomic compare-and-swap` (xem [research §4](../research.md)).
Cấm `read-then-write`.

**Trần đồng thời khoá theo từng máy**: trước khi đếm chỗ trống, server giữ độc quyền đúng hàng của cái
máy đang hỏi. Không có nó thì bốn cú xin cùng lúc đều đọc thấy máy còn rỗng và mỗi cú lấy trọn phần của
mình — máy trần 2 ôm 8 việc. Khoá theo máy nên hai máy khác nhau không bao giờ chờ nhau.

**Đầu việc của dự án đã đóng không được trao**: bộ lọc nằm trong chính câu lệnh lấy việc, không ở cửa.
Một cú xin không nói về dự án nào cả — nó là một cái máy hỏi về mọi thứ nó đang chứa — nên chặn cả cú
xin vì một đầu việc thuộc dự án đã đóng là đóng băng luôn phần việc không liên quan trên cùng máy ấy.

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
**cả gói** có đường dẫn thoát ra ngoài — bỏ lẻ một tệp thì agent đọc một `SKILL.md` mà những tệp nó nhắc
tới đã lặng lẽ biến mất, tệ hơn là không có kỹ năng ấy. Daemon kiểm lại một lần nữa lúc ghi: kiểm ở server
giữ cho mọi gói sạch, kiểm ở daemon mới là thứ làm lời hứa ấy đúng trên một cái máy thật.

Thứ tự trong danh sách là **thứ tự người chủ cấp**, không xáo lại.

### `POST /daemon/runs/{run_id}/start`

Daemon báo đã dựng xong môi trường và agent bắt đầu chạy.

```json
→ { "session_handle": "…" }
← 200 {}
← 404 {}     ← lượt chạy không còn thuộc máy này (hạn giữ đã hết) — daemon PHẢI dừng và dọn
```

`404` ở đây chính là lưới ở FR-059: một máy đã bị thu hồi mà ngủ dậy muộn thì **không ghi được gì**. Hạn
giữ đã trôi qua là đủ để trả `404`, **không đợi** vòng quét dọn hàng — nếu đợi thì trong quãng tối đa một
vòng quét, máy vẫn bật được agent lên trên đầu việc mà vòng quét sắp trả về kệ, và đầu việc ấy đi ra lần
thứ hai.

Gọi lại lần nữa **không phải lỗi**: gói tin trả lời rơi mất là một trong ba đường sinh ra race ở FR-054b,
nên máy phải lặp lại được mà không bị đuổi đi dọn một lượt chạy đang khoẻ.

**Lúc này đồng hồ giữ việc dừng lại, còn mối giữ thì không.** FR-056a bấm giờ quãng *chuẩn bị*; agent lên
rồi thì có thứ thật để canh — lượt chạy im lặng — nên `claim_expires_at` về rỗng và máy giữ tiếp. Để đồng
hồ chạy tiếp là cướp lại một lượt chạy khoẻ sau đúng hai phút.

---

## 4. Gửi diễn biến

### `POST /daemon/runs/{run_id}/events`

Gửi theo lô, trong lúc đang chạy (FR-015).

```json
→ { "events": [
      { "seq": 12, "type": "tool.started",
        "payload": { "call": "toolu_1", "name": "read_file", "args": { … } },   ← toàn văn tham số
        "redacted": true },
      { "seq": 13, "type": "tool.completed",
        "payload": { "call": "toolu_1", "failed": false,
                     "bytes": 4821, "kind": "text", "opening": "…" },
        "truncated": true, "original_byte_size": 4821,
        "omission_reason": "truncated_by_policy" },
      { "seq": 14, "type": "tool.completed",
        "payload": { "call": "toolu_2", "failed": false },
        "omission_reason": "not_exposed_by_cli" }
    ] }
← 200 {}
```

**Bản rút gọn của một kết quả** gồm `bytes` (kích thước **trước** khi che và cắt), `kind` khi CLI
nói, và `opening` — phần đầu cắt theo ngưỡng. Tên khoá tránh `content`/`result`/`output`/`stdout`/
`stderr`/`body`/`data`: server từ chối cả lô nếu thấy một trong số đó, hoặc nếu payload của một
`tool.completed` vượt 4096 bytes.

**Bốn trường ngoài payload** nói về *bản ghi*, không về việc đã xảy ra, nên chúng nằm cạnh payload
chứ không trong: người đọc hỏi *chỗ nào bị cắt* mà không phải mở từng payload. Cả bốn đều bỏ được —
một daemon bản cũ gửi đúng số bytes như trước, và sự kiện của nó lưu lại đúng như nó vốn thế.

**Ràng buộc cứng**:
- **Toàn văn kết quả công cụ không bao giờ có mặt trong body này** (FR-043a). Chỉ bản rút gọn.
- Che bí mật đã làm **xong ở phía daemon** trước khi gửi (FR-048). Server không che hộ. Server
  **không** che thay, nhưng nó **từ chối** một lô mang token của chính hệ thống này ở dạng nguyên
  bản — `400 credential_in_the_clear`, nhận ra theo hình dạng của hai tiền tố nó tự đúc
  (`armr_run_…`, `armd_…`, mỗi cái kèm ít nhất 40 ký tự url-safe theo sau). Đây là bản sao thứ hai
  của luật, đúng hình dạng T098 đã dựng cho kết quả công cụ: nó làm SC-015 thành câu về **kho**,
  không phải câu về hạnh kiểm của một chương trình. Phía này không so theo *giá trị* được — nó chỉ
  giữ hash — nên nó chỉ nhận ra được đúng loại bí mật nó tự sinh ra.
- `omission_reason` chỉ nhận `truncated_by_policy` hoặc `not_exposed_by_cli`; giá trị khác bị từ
  chối **ở cửa** (422). Một chuỗi tự do ở đây là một màn hình phải đoán (FR-047).
- `seq` tăng đơn điệu trong một lượt chạy, không trùng (FR-045). Có **lỗ** thì được — một sự kiện
  bị bỏ để lại chỗ trống mà không gì lấp được, và bản ghi tự nói ra chỗ trống ấy (xem dưới).

**Từ chối là câu trả lời cuối, hay chỉ là *chưa phải lúc*** — daemon phải phân biệt được, vì lô bị
giữ lại là lô chặn mọi sự kiện phía sau nó (FR-047):

| Server đáp | Daemon hiểu | Daemon làm |
|---|---|---|
| `404` | lượt chạy không còn của máy này (FR-059) | dừng lượt chạy, không gửi gì nữa |
| `401` `403` `408` `425` `429` | *chưa phải lúc* | giữ lô, gửi lại |
| `400 credential_in_the_clear` | lô mang bí mật chưa che (FR-048) | **bỏ**, và sửa phép che trên máy |
| `4xx` còn lại | server đã đọc và không nhận | **bỏ**, không hỏi lại |
| `5xx`, lỗi mạng | chưa đọc tới nơi | giữ lô, gửi lại |

Server từ chối **cả lô** và không nói sự kiện nào sai, nên daemon **chia đôi lô rồi hỏi lại** để tìm
ra đúng sự kiện bị từ chối, bỏ mình nó, và đẩy phần còn lại lên. Mỗi lần hỏi thêm loại bỏ hẳn ít nhất
một sự kiện, nên việc này không quay vòng.

Chỗ trống để lại được nói ra bằng một sự kiện `run.error` do chính máy viết: `events_dropped` (buffer
đầy — máy chạy nhanh hơn đường truyền) hoặc `events_refused` (server không nhận). Hai mã tách nhau vì
hai chuyện khác nhau; một con số gộp sẽ đẩy người đọc đi sai hướng.

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

Daemon giữ mở, xác thực bằng token của máy như mọi cửa `/daemon/*` khác. Server đẩy xuống khi có việc mới
cho **máy này** — kênh khoá theo máy, không phải theo workspace: vẫy một máy không lấy được việc ấy là bắt
nó đi hỏi một câu chỉ có thể về tay không.

```
event: pending_work
data: {"workplace_id":"wp-1"}
```

**Tin này chỉ là tín hiệu.** Nó không mang việc và không phải lệnh chạy (FR-055a). Daemon nhận được thì đi
gọi `POST /daemon/runs/claim` — đúng cái cửa nó vẫn gọi theo nhịp poll. Phía daemon **không đọc phần thân
tin**: nó vốn hỏi về mọi chỗ làm nó đang giữ, nên thứ duy nhất tin này nói được có ích là *có*. Đọc một
lượt chạy ra khỏi đó là lúc một tín hiệu lặng lẽ biến thành một mệnh lệnh.

**Không phát lại.** Mọi luồng SSE khác trong hệ thống trả cho khách phần đã bỏ lỡ theo `Last-Event-ID`, vì
chúng mang tin tức. Đường này không: một cái vẫy tay chỉ đúng vào lúc vẫy. Máy nối lại là đã đi hỏi rồi,
nên phát lại chồng cũ chỉ đẻ ra những lượt hỏi về tay không. Vì thế khung tin ở đây **không có `id:`**.

**Không phải dấu hiệu sống.** Giữ đường này mở chứng minh liên lạc được tới máy; nó không chứng minh agent
CLI trên máy còn chạy được, và tuyệt đối không ghi nhịp tim (FR-055b).

Server gửi keep-alive dạng chú thích SSE (`: ping - <thời điểm>`) để proxy không cắt kết nối đang rảnh.
Chú thích không phải sự kiện: daemon bỏ qua, và không đi hỏi vì nó.

Mất kết nối này **không mất việc**: nhịp poll 5 giây là fallback (FR-055d). Nhịp nối lại của đường đẩy
giãn dần 1 → 60 giây, và nó **chỉ là nhịp của đường đẩy** — nhịp đi hỏi không bao giờ bị rút ngắn để bù.
