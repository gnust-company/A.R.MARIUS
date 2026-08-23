# Phase 1 — Mô hình dữ liệu

**Feature**: 002 — Daemon tại máy người dùng và chuẩn ACP

**Sáu bảng mới, bốn bảng sửa.** Thuật ngữ theo [Từ điển thuật ngữ trong spec.md](spec.md).

---

## Bảng mới

### `machines` — Máy chạy daemon

| Cột | Kiểu | Ghi chú |
| --- | --- | --- |
| `id` | UUID, PK | |
| `workspace_id` | UUID, FK | Điều I — mọi truy vấn lọc theo cột này |
| `owner_user_id` | UUID, FK | Người cài daemon lên máy |
| `display_name` | text | Tên máy đọc được (FR-003) |
| `token_hash` | text | **Chỉ lưu hash** của token daemon, không lưu bản gốc |
| `token_expires_at` | timestamptz | Gia hạn theo FR-014d |
| `last_heartbeat_at` | timestamptz | FR-004 |
| `daemon_version` | text | Để chẩn đoán khi có hai bản daemon cùng sống (FR-034) |
| `platform` | text | `linux` / `darwin` / `windows` |
| `symlink_capable` | bool | Kết quả thử lúc khởi động (research §5) |
| `max_concurrent` | int | Trần lượt chạy đồng thời. **Cấu hình phía server** (FR-008d) |
| `created_at`, `updated_at` | timestamptz | |

**Trạng thái suy ra, không lưu**: máy *còn liên lạc* khi `last_heartbeat_at` trong vòng 3 nhịp heartbeat.
Không có cột `status` — trạng thái là hàm của đồng hồ, lưu ra cột là mời nhau lệch.

---

### `workplaces` — Chỗ làm

Một cặp (agent CLI có trên máy đó × workspace). Đây là thứ nhận việc.

| Cột | Kiểu | Ghi chú |
| --- | --- | --- |
| `id` | UUID, PK | |
| `workspace_id` | UUID, FK | Điều I |
| `machine_id` | UUID, FK → `machines` | |
| `cli_kind` | text | `gemini` / `claude_code` / `codex` |
| `cli_version` | text | |
| `protocol_family` | text | `acp` / `one_shot` |
| `capabilities` | jsonb | Kết quả **hỏi khả năng** (FR-017): nối lại phiên được không, có lộ tham số công cụ không, có lộ kết quả không |
| `ready` | bool | |
| `not_ready_reason` | text \| null | **Mã lý do**, không phải câu (Điều VII). `cli_removed` / `cli_unlaunchable` / `quota_exhausted` / `link_unsupported` |
| `created_at`, `updated_at` | timestamptz | |

**Ràng buộc duy nhất**: `(machine_id, cli_kind)` — một máy chỉ có một bản của mỗi agent CLI.

**Chuyển trạng thái**:

```
      ┌─ dò được lúc daemon khởi động ─→ ready
      │
ready ─┬─ CLI bị gỡ khỏi máy ────────→ not_ready(cli_removed)
       ├─ CLI có nhưng không chạy nổi ─→ not_ready(cli_unlaunchable)
       ├─ cạn hạn mức nhà cung cấp ────→ not_ready(quota_exhausted)   ← FR-007c
       └─ không tạo được liên kết bắt buộc → not_ready(link_unsupported)
```

Mọi nhánh `not_ready` đều quy về **một** kết luận cho tầng trên: *agent offline* (FR-006a). Lý do chỉ là
chữ hiển thị, không phải nhánh rẽ nghiệp vụ (FR-006c).

---

### `daemon_link_codes` — Mã nối máy dùng một lần

Phục vụ device flow ở [research §1](research.md).

| Cột | Kiểu | Ghi chú |
| --- | --- | --- |
| `id` | UUID, PK | |
| `code` | text, unique | Mã ngắn người đọc được, ví dụ `KQ7F-M2XD` |
| `workspace_id` | UUID, FK \| null | Điền lúc người dùng duyệt |
| `approved_by_user_id` | UUID \| null | |
| `machine_id` | UUID \| null | Điền lúc cấp token |
| `expires_at` | timestamptz | **10 phút** |
| `consumed_at` | timestamptz \| null | Dùng một lần, không dùng lại |

---

### `run_event_blobs` — Toàn văn của sự kiện quá lớn

| Cột | Kiểu | Ghi chú |
| --- | --- | --- |
| `id` | UUID, PK | |
| `run_event_id` | UUID, FK → `run_events` | |
| `workspace_id` | UUID, FK | Điều I — đọc nhật ký cũng phải lọc tenant (FR-051) |
| `content` | text | |
| `byte_size` | int | |

**Chỉ chứa loại được phép mang toàn văn lên server**: thông điệp gửi agent, tham số gọi công cụ, chữ agent
sinh ra. **Không bao giờ chứa kết quả công cụ** — FR-043a cấm toàn văn kết quả rời máy người dùng.

---

## Bảng sửa

### `runs` — thêm **đúng một** cột, và nó trung lập runtime

| Cột thêm | Kiểu | Ghi chú |
| --- | --- | --- |
| `accepted_at` | timestamptz \| null | Mốc **một runtime nào đó nhận lượt chạy này**. Động cơ số 1 bật từ đây (FR-056) |

Chỉ có thế. `Run` là thực thể **tầng domain**, nên nó KHÔNG ĐƯỢC mang cột `machine_id` hay `workplace_id` —
FR-006 cấm tầng nghiệp vụ biết tới khái niệm máy, runtime hay daemon. Chữ `accepted_at` cố ý trung lập: nó
nói *đã có ai đó nhận*, không nói *máy nào nhận*.

### `run_claims` — bảng của tầng infrastructure

Mọi thứ dính tới máy sống ở đây, sau hợp đồng adapter. Tầng domain và tầng application **không đọc bảng này**.

| Cột | Kiểu | Ghi chú |
| --- | --- | --- |
| `run_id` | UUID, PK, FK → `runs` | Một lượt chạy nhiều nhất một hàng |
| `workspace_id` | UUID, FK | Điều I |
| `workplace_id` | UUID, FK → `workplaces` | Chỗ làm được xếp |
| `machine_id` | UUID, FK → `machines` \| null | **NULL = chưa máy nào nhận.** Đây là cột quyết định ở FR-054 |
| `claimed_at` | timestamptz \| null | |
| `claim_expires_at` | timestamptz \| null | Mặc định `claimed_at + 120s` (FR-056a) |
| `run_token_hash` | text \| null | Hash token của lượt chạy (FR-014a) |

**Chỉ mục**: `(workplace_id) WHERE machine_id IS NULL` — chỉ mục cú xin việc chạy trên, phải hẹp để câu lệnh
ở [research §4](research.md) rẻ.

**Ràng buộc phải giữ**: `runs.accepted_at` và `run_claims.claimed_at` được ghi **trong cùng một giao dịch**
với cú `atomic compare-and-swap`. Ghi lệch nhau là đẻ ra đúng khe mà FR-056 sinh ra để bịt.

**Chuyển trạng thái**:

```
chưa ai nhận (machine_id NULL, runs.accepted_at NULL)
   │
   ├── máy xin và được đưa ──→ đã có máy nhận (machine_id đặt, accepted_at đặt, hạn đặt)
   │                             │
   │                             ├── daemon báo đã chạy ──→ running
   │                             │
   │                             └── quá claim_expires_at ──→ về lại chưa ai nhận      ← FR-056a
   │                                     machine_id về NULL, runs.accepted_at về NULL
   │
running ──→ completed | failed | timed_out | stopped
```

**Bất biến**: một lượt chạy **hoặc** `machine_id IS NULL` (đang rảnh) **hoặc** có đúng một máy giữ kèm hạn
còn hiệu lực. Không bao giờ vừa rảnh vừa có chủ.

---

### `mariuses` — buộc agent vào chỗ làm

Mối buộc agent ↔ chỗ làm là khái niệm máy, nên **không đặt lên thực thể `Marius`**. Nó sống ở bảng riêng
của tầng infrastructure:

**`agent_workplace_bindings`**

| Cột | Kiểu | Ghi chú |
| --- | --- | --- |
| `marius_id` | UUID, PK, FK | Một agent đúng một mối buộc |
| `workspace_id` | UUID, FK | Điều I |
| `workplace_id` | UUID, FK → `workplaces` | **Đặt lúc tạo agent, KHÔNG đổi được** (FR-007) |
| `created_at` | timestamptz | |

Tầng nghiệp vụ vẫn chỉ hỏi đúng một câu — *agent này sống hay chết?* — và `DaemonLivenessProbe` trả lời từ
bảng này cùng `machines`/`workplaces`, hết. Chuỗi máy → chỗ làm → agent nằm gọn sau hợp đồng adapter.

**Ai ghi bảng này**: luồng tạo/mời agent, và **chỉ nó** (FR-007f). Luồng ấy phải **bắt buộc chọn chỗ làm** —
không có đường tạo agent bỏ trống chỗ làm. Agent chưa có hàng trong bảng này thì `DaemonLivenessProbe` trả
về *offline*, không phải lỗi im lặng. Không có phần ghi này thì bảng vĩnh viễn rỗng và cả chuỗi giao việc
không bao giờ khớp được agent với máy nào.

**Bỏ**: `adapter_type` mặc định `hermes_gateway` và mọi cấu hình gateway (FR-040a).

**Migration PHẢI xoá dữ liệu, không chỉ gỡ mã** (người chủ chốt 2026-08-22). Chuỗi `hermes_gateway` hiện
nằm ở **năm chỗ trong mã**, và một trong số đó là **giá trị mặc định của thực thể domain**:

| Chỗ | Việc |
| --- | --- |
| `domain/entities/marius.py` — `adapter_type: str = "hermes_gateway"` | Bỏ giá trị mặc định |
| `presentation/schemas.py` — mặc định trong schema tạo agent | Bỏ |
| `application/use_cases/enrollment.py` — tham số mặc định | Bỏ |
| `presentation/container.py` — nơi nối adapter vào | Bỏ dòng nối |
| `infrastructure/adapters/hermes_gateway.py` | Xoá tệp |

Và migration phải **xoá hẳn hàng dữ liệu**: mọi agent có `adapter_type = 'hermes_gateway'` cùng những gì
treo theo nó (lượt chạy, phiên, yêu cầu gọi dậy). Không để lại hàng mồ côi trỏ vào một adapter không còn
tồn tại — đó đúng là thứ FR-040a gọi là *mã chết*, chỉ khác là ở dạng dữ liệu.

An toàn được vì hệ thống chưa chạy thật với người dùng ngoài (Assumptions trong spec).

`agent_token` hiện có **giữ nguyên vai trò khác**: nó là danh tính agent ở tầng nghiệp vụ. Token của lượt
chạy là thứ khác, sống trong `run_claims.run_token_hash` ở tầng infrastructure.

---

### `run_events` — thêm dấu vết cắt

**Đã kiểm chứng 2026-08-22**: bảng này **có thật** trong schema nền
(`a40098b66ac7_baseline_schema.py`), sáu cột: `id`, `run_id`, `seq`, `type`, `payload` (`sa.JSON`),
`created_at`. Bốn cột dưới là **thêm thuần**, không đụng cột nào đang có.

Hai điều bước `tasks` phải xử, phát hiện lúc kiểm:

- **`run_events` không có `workspace_id`.** Hôm nay việc lọc tenant đi vòng qua `runs → project →
  workspace`. Bảng `run_event_blobs` ở trên **cố ý có** cột ấy: đọc nhật ký là đường nóng, và bắt nó nối ba
  bảng mỗi lần đọc chỉ để biết tenant là đắt vô ích. Khác biệt này là chủ ý, không phải quên.
- **Cột `type` chưa có chỉ mục.** FR-052 bắt lọc được nhật ký theo loại sự kiện, nên phải thêm chỉ mục
  `(run_id, type)` cùng migration này.

| Cột thêm | Kiểu | Ghi chú |
| --- | --- | --- |
| `truncated` | bool | Đã cắt hay chưa |
| `original_byte_size` | int \| null | Kích thước thật, để bản rút gọn nói được đã cắt bao nhiêu (FR-043b) |
| `omission_reason` | text \| null | Phân biệt hai ca khác nhau: `truncated_by_policy` (cắt theo ngưỡng) và `not_exposed_by_cli` (CLI không lộ dữ liệu, FR-047) |
| `redacted` | bool | Có giá trị bí mật đã bị che ở phía daemon (FR-048) |

Hai lý do vắng dữ liệu **phải hiện khác nhau** trên màn hình — đây là điều FR-047 bắt.

---

### `artifacts` — khoá chống lặp

| Cột thêm | Kiểu | Ghi chú |
| --- | --- | --- |
| `logical_name` | text | Tên do agent đặt |
| `content_hash` | text | |

**Ràng buộc duy nhất**: `(task_id, logical_name, content_hash)` — công bố lại y hệt thì không đẻ bản trùng
(FR-020c). Cùng tên khác hash là bản mới. Xem [research §6](research.md).

---

## Thực thể không có bảng

**Thư mục làm việc** không phải một hàng trong cơ sở dữ liệu. Nó là một thư mục trên máy người dùng, đặt
tên theo `task_id`, và **server không biết đường dẫn của nó**. Server chỉ giữ hạn thu hồi; daemon tự dọn.

Lý do: đường dẫn trên máy người dùng không phải dữ liệu của hệ thống, và lưu nó lên chỉ tạo ra một bản sao
sự thật luôn có nguy cơ lệch với đĩa thật.


---

## Kỹ năng — không thêm bảng nào

Kỹ năng đã có bảng riêng từ trước và **đợt này không đụng schema của nó**. Thứ đổi là **đường đi**, không
phải chỗ chứa:

| | Trước | Sau |
| --- | --- | --- |
| Ai lấy | Agent tự gọi `GET /agent/skills` rồi tự ghi | **Server đưa xuống trong gói nhận việc** |
| Ai ghi ra đĩa | Agent | **Daemon**, trước khi agent đọc dòng đầu tiên |
| Hình thức trên đĩa | tuỳ agent | **Tệp thật, ghi mới mỗi lượt chạy** — không liên kết |
| Xác nhận đã cài | một vòng gọi lại, còn dở dang từ đợt trước | **không còn**, vì daemon ghi trực tiếp |

Đây là nguyên flow của Multica; lý do vì sao là tệp thật chứ không phải liên kết nằm ở
[research §11.2](research.md). Hai route `/agent/skills` bị gỡ (FR-011c), nên **`presentation/api/agent.py`
là chỗ thứ sáu phải sửa** ngoài năm chỗ `hermes_gateway` kể ở trên.

## Thông điệp gửi agent — dùng lại `run_events`, không thêm bảng

Toàn văn thông điệp ghi vào `run_events` như một sự kiện, và tràn ngưỡng thì tách sang `run_event_blobs`
(FR-049). **Server ghi tại thời điểm trả gói nhận việc**, không phải daemon gửi ngược về — xem
[research §11.3](research.md). Đây là một trong hai loại được phép mang toàn văn lên server; loại kia là
tham số gọi công cụ. Kết quả công cụ **không bao giờ** được phép (FR-043a).
