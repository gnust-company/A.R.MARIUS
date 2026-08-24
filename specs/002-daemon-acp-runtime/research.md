# Phase 0 — Nghiên cứu và quyết định kỹ thuật

**Feature**: 002 — Daemon tại máy người dùng và chuẩn ACP
**Ngày**: 2026-08-21

Tài liệu này giải hết những chỗ đặc tả cố ý để lại cho bước lập kế hoạch. Nền đọc từ mã nguồn Multica nằm ở
[research-multica-daemon.md](research-multica-daemon.md); tệp này chỉ ghi **quyết định của Armarius**.

---

## 1. Cách daemon nối vào workspace

**Decision: device flow.** Daemon in ra một mã ngắn kèm địa chỉ; người dùng mở địa chỉ ấy trên trình duyệt
đã đăng nhập Armarius, bấm duyệt; daemon nhận token của mình qua đường hỏi lại theo nhịp.

```
$ armarius-daemon login
  Mở https://armarius.example/link và nhập mã:  KQ7F-M2XD
  Đang chờ duyệt...
  ✓ Đã nối vào workspace "Gnust". Tìm thấy 3 agent CLI.
```

**Rationale**:
- Đạt SC-001 (tự làm xong trong 10 phút, không phải xin ai) mà không bắt người dùng đi tạo token trước.
- **Chạy được trên máy không có màn hình** — cài qua SSH vẫn xong, vì việc duyệt diễn ra ở trình duyệt bất
  kỳ, không cần trình duyệt trên chính máy đó.
- Người dùng **không phải sao chép một chuỗi bí mật** qua clipboard hay lịch sử terminal.

**Alternatives considered**:
- *Người dùng tự tạo token trên giao diện rồi dán vào daemon* — đây là cách Multica làm. Chạy được, nhưng
  bắt đi qua một màn hình tạo token trước, và chuỗi bí mật đi qua clipboard cùng lịch sử shell.
- *Daemon mở cổng cục bộ rồi chuyển hướng trình duyệt về* — gãy trên máy không màn hình và trên máy sau
  tường lửa, đúng hai môi trường người dùng hay cài daemon nhất.

---

## 2. Poll của daemon có vi phạm Điều IV không

**Decision: không.** Ghi lại đây để bước sau không tranh cãi lại.

**Rationale**: nguyên văn Điều IV — *"Trạng thái và sự kiện PHẢI được đẩy về **trình duyệt** qua kênh sự
kiện. **Giao diện** KHÔNG ĐƯỢC hỏi-vòng."* Điều này nói về chặng **server ↔ trình duyệt**. Poll của daemon
nằm ở chặng **server ↔ máy người dùng**, khác chặng, khác người đọc. Giao diện không đổi gì và vẫn nhận sự
kiện qua kênh đẩy sẵn có.

---

## 3. Ba con số: nhịp poll, nhịp heartbeat, hạn giữ sau khi máy nhận việc

**Decision**:

| Con số | Mặc định | Đặt được | Buộc với |
| --- | --- | --- | --- |
| Nhịp poll (fallback) | **5 giây** | có | — |
| Nhịp heartbeat | **15 giây**; mất 3 nhịp liên tiếp → máy coi như mất liên lạc (45 giây) | có | FR-004 |
| Hạn giữ sau khi máy nhận việc | **120 giây** | có | FR-056a, FR-056c |
| Ngưỡng im lặng của một lượt chạy | **10 phút**, đếm từ sự kiện gần nhất; **không** giới hạn tổng thời gian chạy | có, nhưng chỉ siết chặt được | FR-031, FR-031a |
| Hạn giữ phiên | **14 ngày** | có | FR-027 |
| Hạn giữ thư mục làm việc | **24 giờ** kể từ lúc đầu việc xong/huỷ và im | có | FR-021 |
| Đầu việc đang chờ máy rảnh | **không có hạn** — xem §10 | — | FR-008e |

**Rationale**:

Ngân sách SC-002 là 15 giây từ lúc quyết định gọi dậy tới lúc agent bắt đầu chạy. Chia ra:

```
push tới daemon        < 1 giây
daemon xin việc, nhận  < 1 giây
dựng thư mục + đổ kỹ năng + bật CLI   ← phần ăn hết ngân sách, 2–5 giây điển hình
```

Nhịp poll 5 giây là **fallback**, chỉ dùng khi push không tới nơi; đặt 5 thay vì 3 như Multica vì push của
ta đáng tin hơn (xem §8) và ngân sách vẫn còn chỗ.

Hạn giữ 120 giây rộng gấp nhiều lần thời gian chuẩn bị điển hình, thoả FR-056c. Rộng như thế **không tốn
gì**, vì FR-007 buộc mỗi agent vào đúng một chỗ làm: hết hạn không phải để trao cho máy khác, mà để đầu việc
thôi kẹt ở trạng thái *đã có máy nhận* khi cái máy ấy đã chết. Đặt hẹp mới nguy hiểm — nó cướp lại đầu việc
giữa lúc một máy chậm đang chuẩn bị đúng.

**Alternatives considered**: đặt hạn giữ bằng đúng 15 giây cho khớp SC-002 — sai, vì SC-002 đo *đường
thường*, còn hạn giữ phải chịu được *đuôi phân bố*: máy chậm, gói kỹ năng to, CLI khởi động nguội trên
Windows.

---

## 4. Hiện thực `atomic compare-and-swap` cho cú xin việc

**Decision**: một câu lệnh duy nhất trên Postgres:

```sql
WITH taken AS (
    UPDATE run_claims SET
        machine_id = :machine, claimed_at = NOW(), claim_expires_at = NOW() + :hold
    WHERE run_id IN (
        SELECT c.run_id FROM run_claims c JOIN runs r ON r.id = c.run_id
        WHERE c.machine_id IS NULL
          AND c.workplace_id = ANY(:workplaces)
          AND r.status = 'queued'
        ORDER BY r.created_at
        FOR UPDATE OF c SKIP LOCKED
        LIMIT :n
    )
    RETURNING run_id
)
UPDATE runs SET accepted_at = NOW()
WHERE id IN (SELECT run_id FROM taken)
RETURNING *;
```

Hai lệnh `UPDATE` nằm trong **một câu**, nên `run_claims.claimed_at` và `runs.accepted_at` luôn được ghi
cùng nhau — đúng ràng buộc ở [data-model.md](data-model.md). Cột `machine_id` chỉ có mặt ở `run_claims`
(tầng infrastructure); bảng `runs` ở tầng domain chỉ nhận `accepted_at`, trung lập runtime.

**Rationale**: `FOR UPDATE SKIP LOCKED` cho phép lấy nhiều đầu việc cùng lúc (FR-055e) mà vẫn giữ đúng tính
chất của FR-054 — hai cú xin đồng thời không bao giờ trả về cùng một hàng. Một câu lệnh, không có bước tách
rời để chen vào.

**Cảnh báo dialect — phải xử ở tasks**: SQLite **không có** `SKIP LOCKED`. Backend hiện mặc định
`sqlite+aiosqlite`, còn Postgres là tuỳ chọn. Nên:
- Đường SQLite dùng giao dịch ghi độc quyền, chấp nhận được vì SQLite chỉ để test và test chỉ có một người ghi.
- **Bắt buộc có ít nhất một test chạy trên Postgres thật** cho phần này, vì đây đúng chỗ SQLite không mô
  phỏng được hành vi thật.

**Alternatives considered**: khoá tư vấn ở tầng ứng dụng (`SELECT` rồi `UPDATE` trong một giao dịch có khoá
hàng) — chạy được nhưng là `read-then-write` có khoá, tốn hơn và dễ viết sai thứ tự khoá.

---

## 5. Ràng buộc Windows

**Decision**: daemon **thử tạo liên kết lúc khởi động** rồi ghi kết quả thành một khả năng của chỗ làm.

| Thứ cần liên kết | Có quyền tạo symbolic link | Không có quyền |
| --- | --- | --- |
| Thư mục (cấu hình, plugin) | symbolic link | **junction** — Windows không đòi quyền đặc biệt |
| Kỹ năng (dựng lại mỗi lượt) | symbolic link | **chép** — an toàn vì nội dung sinh lại mỗi lượt |
| Trạng thái phiên, ký ức | symbolic link | **chỗ làm báo không sẵn sàng, kèm lý do đọc được** |

**Rationale**: kế thừa đúng nguyên tắc *chứng minh trước khi làm* của Multica. Hàng cuối là chỗ tuyệt đối
không được âm thầm rơi về chép: một tệp trạng thái phiên **được chép** sẽ hút hết phần ghi của lượt chạy vào
một bản mà lượt sau vứt đi — agent mất trí nhớ mà không ai biết vì sao. Thà báo chỗ làm không sẵn sàng.

Windows mở được symbolic link bằng cách bật Developer Mode; hướng dẫn cài phải nói câu đó.

---

## 6. Dấu nhận dạng để công bố hiện vật lặp không đẻ bản trùng

**Decision**: khoá là **(đầu việc, tên hiện vật do agent đặt)**, cộng **hash nội dung** để phân biệt hai ca:

| Trường hợp | Kết quả |
| --- | --- |
| Cùng đầu việc, cùng tên, **cùng** hash | Không làm gì, trả về hiện vật đã có — **đây là ca thử lại sau khi đứt** |
| Cùng đầu việc, cùng tên, **khác** hash | Bản mới của cùng hiện vật đó |
| Tên khác | Hiện vật khác |

**Rationale**: agent đẩy lại `report.pdf` sau khi mất mạng phải rơi đúng vào hàng một. Nếu chỉ lấy hash làm
khoá thì một tệp có nhúng dấu thời gian bên trong sẽ sinh ra hiện vật thứ hai mỗi lần chạy lại. Nếu chỉ lấy
tên thì mất khả năng phân biệt *thử lại* với *ra bản mới* — mà hai cái ấy cần hành vi khác nhau.

**Alternatives considered**: bắt agent tự gửi kèm một mã chống lặp do nó tự sinh — đẩy phần ghi sổ sang cho
agent, và agent sẽ làm sai; sau một lần khởi động lại nó sinh mã mới cho cùng một tệp là hỏng.

---

## 7. Ngưỡng cắt và hạn giữ của tầng nhật ký

**Decision**:

| Thứ | Mặc định | Đặt được |
| --- | --- | --- |
| Bản rút gọn của **kết quả công cụ** giữ inline | **2 KB**, kèm kích thước thật và số bytes đã cắt | có |
| Sự kiện **được phép mang toàn văn** (thông điệp, tham số, chữ agent) vượt ngưỡng thì tách kho | **32 KB** | có |
| Hạn giữ nhật ký | **30 ngày**, tách khỏi hạn giữ thư mục làm việc | có |

**Rationale**: 2 KB đủ thấy hình dạng kết quả (mấy dòng đầu, kiểu dữ liệu) mà không mang nội dung tệp đi
đâu — đúng ràng buộc FR-043a. Ở mức xấu nhất SC-014 (1000 sự kiện) thì một lượt chạy nặng khoảng 2 MB, cuộn
được thoải mái.

Bản rút gọn **phải ghi rõ đã cắt bao nhiêu** (FR-043b) và phải phân biệt được với ca *CLI không lộ dữ liệu*
(FR-047) — hai lý do khác nhau, không được hiện giống nhau.

---

## 8. Đường đẩy tin xuống daemon

**Decision: SSE trên kênh sự kiện sẵn có**, không dùng WebSocket. Daemon giữ một kết nối `GET` mở tới
`/daemon/events`; server đẩy tin *"có việc"* xuống đó.

**Rationale**:
- Tin đẩy là **một chiều server → daemon** và theo FR-055a nó **chỉ là tín hiệu, không mang việc và không
  bao giờ là lệnh chạy**. Đó đúng hình dạng của SSE.
- Backend đã có `sse-starlette` và bus sự kiện — **không thêm dependency nào**.
- Daemon gửi ngược bằng lời gọi HTTP thường, nên không cần kênh hai chiều.

**Alternatives considered**: WebSocket như Multica. Họ cần hai chiều vì **chạy luôn cả cú xin việc qua đó**
— và chính lựa chọn ấy đẻ ra sự cố nhận việc hai lần của họ (MUL-4257): cùng một cú xin đi được hai đường
vận chuyển thì có lúc không biết cú nào đã ăn. Ta không kế thừa hình dạng đó. Cú xin việc của ta **chỉ đi
một đường HTTP duy nhất**, tin đẩy chỉ giục.

---

## 10. Bốn chỗ hở `/speckit-analyze` tìm ra — chốt 2026-08-22

### 10.1 Ký ức dài hạn của agent — **bỏ khỏi khái niệm nền**

**Decision**: không dựng kho ký ức chung. Làm **y hệt Multica**: để trong thư mục nhà giả mà daemon dựng
cho chính CLI đó, liên kết ra một kho sống lâu hơn thư mục làm việc, dọn theo hạn giữ riêng.

**Rationale**: đọc kỹ tên biến của Multica thì thấy nó là tính năng **riêng của một runtime**, không phải
khái niệm nền:

```
<profile dir>/hermes-state/<agent-id>/<hermes-profile>/memories/
MULTICA_GC_HERMES_MEMORY_TTL = 2160h (90 ngày)
```

`hermes-state`, `HERMES_MEMORY` — nó tồn tại vì agent Hermes có thư mục `memories/`. Ba CLI đợt đầu chưa
chắc cái nào dùng. Dựng một kho nền cho thứ có thể không ai dùng là việc thừa.

**Alternatives considered**: dựng kho ký ức chung theo id agent cho mọi CLI — đó là bản nháp đầu, và nó
tổng quát hoá một tính năng của một hãng thành luật của cả nền tảng.

### 10.2 *Đang chờ máy rảnh* — **trạng thái, không phải timeout**

**Decision**: thêm một trạng thái hiện lên màn hình. **Không có đồng hồ, không tính giờ.** Động cơ đẩy
chuyển từ số 2 sang **số 5 — đang bị chặn bởi việc khác**.

**Rationale**: hai chứng cứ độc lập cùng chỉ một hướng.

*Multica không đặt hạn.* Chú thích trong mã họ: một cú xin việc báo không còn chỗ thì *"phải nhận về không
cái nào"*, và đầu việc cứ nằm đó. `stale reclaim` của họ chỉ vớt đầu việc **đã có máy nhận rồi bị bỏ rơi**.

*Và mã của chính ta đã có tiền lệ.* Chú thích ở động cơ số 5 trong `push_reason_rules.py`:

> *"Không có đồng hồ ở đây. Đầu việc chặn nó có động cơ đẩy riêng, và nếu **nó** kẹt thì chuông reo ở đó,
> chỗ có người xử được."*

*Chờ máy rảnh* đúng hình dạng ấy: thứ gỡ nó là một lượt chạy khác kết thúc, mà lượt chạy đó **đã có ngưỡng
im lặng riêng**. Gắn thêm đồng hồ ở đây là đo lại một thứ đã được đo.

Đối chiếu ngoài ngành: GitHub Actions và Prefect đều có trạng thái chờ hiện ra (`Queued`, `Pending`) chứ
không coi việc chờ là lỗi.

**Alternatives considered**: động cơ số 2 kèm hạn 30 phút rồi nổi cờ — bản nháp đầu. Sai hai lần: mô tả
sai cơ chế (không có ai hẹn giờ, poll lo hết), và đo lại một thứ đã có đồng hồ.

### 10.3 Dọn thư mục làm việc — **theo thời gian, không có tin báo**

**Decision**: daemon tự quét định kỳ và tự hỏi trạng thái đầu việc. Xoá khi đầu việc **đã xong hoặc đã huỷ**
*và* đã im quá **24 giờ**. Thư mục đang có lượt chạy thì **không bao giờ** đụng.

**Rationale**: đây đúng cách Multica làm, và nó dựng sẵn cả bốn chế độ dọn:

```
GC quét mỗi 2 giờ
issue done/cancelled + im 24 giờ   →  xoá cả thư mục
không có sổ ghi + 72 giờ           →  xoá
thư mục đang có việc chạy          →  không bao giờ đụng
```

Không cần thêm loại tin đẩy nào. Hệ quả: điều khoản FR-021 phải sửa lại, vì bản cũ hứa *"thu hồi khi đầu
việc khép lại"* — nghe như có tin báo.

### 10.4 Ngưỡng im lặng — **10 phút, đếm từ sự kiện gần nhất**

**Decision**: **không giới hạn tổng thời gian chạy.** Chỉ đếm từ sự kiện gần nhất agent nhả ra. Nền 10
phút; từng CLI đặt riêng được nhưng **chỉ siết chặt hơn, không nới rộng**.

**Rationale**: mô hình của Multica, chép nguyên:

```
Agent timeout                 0  = KHÔNG giới hạn tổng thời gian ("bounded by the watchdogs")
Codex semantic inactivity   10m
OpenCode idle watchdog      10m   (0 → rơi về nền; KHÔNG nới rộng được)
```

Một lượt chạy ba tiếng vẫn hợp lệ miễn là còn nhả sự kiện. Thứ giết nó là im lặng, không phải độ dài.

Luật *chỉ siết không nới* đáng chép: cấu hình của một CLI không được phép tắt lưới an toàn chung.

**Ghi nhận giới hạn của nghiên cứu**: con số của **ngưỡng nền chung** bên Multica không tìm thấy trong tài
liệu đang có; 10 phút lấy theo hai giá trị per-CLI tìm được, và người chủ chốt cứng con số này.

---

## 9. Bộ agent CLI cho đợt đầu

**Decision**: ba cái, phủ **cả hai họ giao thức**:

| CLI | Họ | Vì sao có trong đợt đầu |
| --- | --- | --- |
| **Gemini CLI** (`--experimental-acp`) | ACP | Người chủ chốt là bắt buộc (FR-039) |
| **Claude Code** | chạy-một-phát | Đang dùng thật hằng ngày trong dự án |
| **Codex** | chạy-một-phát | Có mô hình thư mục nhà riêng, thử được cơ chế dựng môi trường |

**Rationale**: hai họ giao thức đều có đại diện ngay từ đợt đầu, nên ranh giới ở FR-035/FR-037 bị ép phải
đúng từ sớm thay vì được dựng quanh một họ rồi sửa sau.

### Rủi ro lịch trình: Gemini CLI chưa được xác minh

Người chủ chốt 2026-08-22: **bắt buộc hỗ trợ, và phải research kỹ trước khi code.** Đây là rủi ro lịch
trình duy nhất đáng ghi của đợt này, vì nó là CLI duy nhất trong ba cái mà ta chưa từng chạy thật.

Chưa biết bốn thứ, và mỗi thứ đổi một phần thiết kế khác nhau:

| Chưa biết | Nếu câu trả lời xấu thì đổi gì |
| --- | --- |
| Đọc tệp bối cảnh nào (`GEMINI.md`? khác?) | Bảng ánh xạ trong `daemon/internal/runtime` |
| Dò kỹ năng ở thư mục nào | Cách `execenv` đổ kỹ năng cho riêng nó |
| Có nối lại được phiên không | Theo FR-039a, không nối lại được thì mở phiên mới kèm câu báo — **vẫn tính là hỗ trợ**, không phải hỏng |
| Có lộ tham số và kết quả gọi công cụ qua ACP không | Nếu không lộ thì nhật ký của nó phải đánh dấu `not_exposed_by_cli` (FR-047), và SC-011 không áp cho nó |

**Việc đầu tiên trong `tasks.md` cho phần Gemini phải là một task nghiên cứu độc lập**: cài `gemini`, chạy
`gemini --experimental-acp`, ghi lại bốn câu trả lời trên vào chính tệp này, **rồi mới** viết mã. Không
được vừa dò vừa code — dò sai thì phải viết lại cả tầng dựng môi trường cho nó.

### 9.1 Đọc thẳng từ mã nguồn `google-gemini/gemini-cli@main`, 2026-08-24 — **CHƯA chạy thật**

Người chủ 2026-08-24: máy phát triển **không cài được `gemini`** vì tài khoản không đủ quyền, nhưng có máy
khác cài được. Nên T013 tách làm hai nửa — nửa tra cứu ghi ở đây, nửa chạy thật làm bằng
`daemon/scripts/probe-gemini-acp.mjs`.

> **Đọc bảng này phải nhớ**: nó đọc từ **mã nguồn và tài liệu**, không phải từ một lần chạy. Bản `gemini`
> cài trên máy kia có thể khác nhánh `main`. Chưa được coi là đã trả lời cho tới khi script chạy xong và
> đối chiếu khớp.

| Câu hỏi | Trả lời (đọc từ mã) | Nguồn |
| --- | --- | --- |
| Đọc tệp bối cảnh nào | **`GEMINI.md`**, xếp tầng: `~/.gemini/GEMINI.md` dùng cho mọi dự án, cộng `GEMINI.md` ở thư mục làm việc và các thư mục cha. Nối hết lại rồi gửi kèm **mọi** lượt prompt | tài liệu `docs/cli/gemini-md.md` |
| Dò kỹ năng ở thư mục nào | **`~/.gemini/skills/`** (cá nhân) và **`.gemini/skills/`** (dự án, tính từ gốc repo). Một kỹ năng là một thư mục có `SKILL.md`. Đầu phiên nó quét, nhét **tên + mô tả** vào system prompt, rồi gọi công cụ `activate_skill` khi thấy hợp | tài liệu `docs/cli/skills.md` |
| Có khai nối lại phiên không | **CÓ** — `agentCapabilities.loadSession: true`, và `session/load` có hiện thực thật, không phải khai suông | `packages/cli/src/acp/acpRpcDispatcher.ts:91-93`, `acpSessionManager.ts:164` |
| Có lộ tham số và kết quả gọi công cụ không | **Tham số: KHÔNG. Kết quả: một phần.** `tool_call` và `tool_call_update` chỉ mang `toolCallId`, `status`, `title`, `content`, `locations`, `kind` — **không có `rawInput`**, nên tham số gọi công cụ không rời khỏi CLI. `content` dựng từ `toolResult.returnDisplay`, tức bản **để hiển thị** chứ không phải kết quả thô; và `toToolCallContent` trả `null` khi tool không có `returnDisplay`, nên có tool **không sinh nội dung kết quả nào** | `acpSession.ts:820-845`, `acpUtils.ts:47-83` |

**Hệ quả nếu lần chạy thật xác nhận đúng:**

- **Nối lại phiên: được.** Không phải rơi về FR-025. Lưu ý issue #15502 báo `loadSession: false` — đó là bản
  cũ; mã hiện tại đã đổi. Đây đúng là lý do phải chạy thật thay vì tin một issue trên mạng.
- **Nhật ký của Gemini phải đánh dấu `not_exposed_by_cli` cho phần tham số** gọi công cụ (FR-047), và
  SC-011 không áp trọn cho nó.
- Kết quả công cụ **có** nhưng là bản hiển thị. **Chưa hỏi người chủ**: bản hiển thị có tính là *kết quả*
  theo FR-043b không, hay cũng phải đánh dấu là không lộ.

**Câu hỏi thứ năm, không có trong bảng gốc nhưng daemon không tránh được**: `gemini` có đòi đăng nhập tương
tác khi bị **một chương trình khác** khởi chạy (stdin không phải terminal) không? Issue #12042 báo đúng ca
này, và daemon **luôn** chạy nó theo kiểu đó. Script hỏi luôn câu này.

---

## 11. Kỹ năng và thông điệp — kế thừa nguyên flow Multica (chốt 2026-08-23)

**Decision**: kỹ năng đi xuống **trong gói nhận việc**, daemon ghi vào **thư mục kỹ năng native của từng
CLI**, dưới dạng **tệp thật ghi mới mỗi lượt chạy**. Bỏ hẳn đường agent tự gọi về lấy rồi tự ghi.

### 11.1 Brief đi vào tệp nào, kỹ năng vào thư mục nào

Bảng dưới là phần rút gọn của [research-multica-daemon.md §3](research-multica-daemon.md) cho ba CLI của
đợt đầu. Bảng đầy đủ 17 CLI nằm ở tệp đó và là nguồn cho `daemon/internal/runtime/registry.go`.

| CLI | Tệp bối cảnh | Thư mục kỹ năng |
| --- | --- | --- |
| **Claude Code** | `CLAUDE.md` | `.claude/skills/` |
| **Codex** | `AGENTS.md` | qua `CODEX_HOME` |
| **Gemini CLI** | **chưa xác minh** — task T013 phải trả lời | **chưa xác minh** — task T013 |

Nguyên tắc chung của Multica, giữ nguyên: **không dạy agent một đường nạp mới**. Ghi vào đúng chỗ nó vốn
tự đọc, tự dò. Agent không cần biết Armarius tồn tại để nhận được kỹ năng.

### 11.2 Vì sao kỹ năng là tệp thật, không phải liên kết

Trong thư mục nhà giả Multica dựng cho Hermes, mọi thứ đều là liên kết — đăng nhập, cấu hình, ký ức,
transcript — **riêng `skills/` là tệp thật, ghi mới mỗi lượt**. Đây không phải chỗ họ làm ẩu, mà là chỗ họ
cố ý khác.

**Rationale**: một chỗ làm phục vụ nhiều agent (FR-007a). Liên kết trỏ về một kho kỹ năng dùng chung thì
agent A đọc được kỹ năng của agent B — đúng thứ FR-007b cấm. Ghi tệp thật mỗi lượt là cách rẻ nhất bảo đảm
thư mục kỹ năng của một lượt chạy chỉ chứa kỹ năng của đúng agent ấy. Ghi mới mỗi lượt còn xử luôn ca kỹ
năng bị đổi giữa hai lượt chạy: không có trạng thái cũ để mà lệch.

**Alternatives considered**:
- *Liên kết ra kho dùng chung như đăng nhập và ký ức* — rẻ hơn, nhưng vỡ tách-theo-agent. Đây chính là lý
  do Multica không làm.
- *Agent tự gọi `GET /agent/skills` rồi tự ghi* — đường đang có hôm nay. Bỏ vì ba lý do: nó cần một vòng
  xác nhận đã cài xong (thứ còn dở dang từ đợt trước), nó tiêu lượt gọi công cụ của agent cho việc hạ tầng,
  và nó không bảo đảm được kỹ năng đã sẵn sàng **trước khi** agent đọc dòng đầu tiên.

### 11.3 Thông điệp gửi agent — server dựng, server ghi

**Decision**: server dựng toàn văn thông điệp và trả xuống trong gói nhận việc; **server ghi lại toàn văn
tại chính thời điểm ấy** (FR-011a, FR-012a, FR-042). Daemon chỉ đặt thông điệp vào tệp bối cảnh.

**Rationale**: nội dung dựng từ vai trò trong dự án (Điều V) và phải bằng tiếng Anh (Điều VII). Cả hai luật
sống ở server. Để daemon dựng thì hai luật ấy phải đi theo xuống máy người dùng và được kiểm ở nơi không
kiểm được. Ghi ở server cũng bỏ được một đường truyền ngược: daemon không phải gửi lại thứ nó vừa nhận.

**Alternatives considered**: daemon ghi ở sự kiện đầu tiên của lượt chạy. Bỏ vì nó biến một chuyện đã biết
chắc thành một chuyện phải chờ xác nhận — mất kết nối ngay sau khi nhận việc là mất luôn bản ghi thông
điệp, đúng lúc cần nó nhất để tìm hiểu vì sao lượt chạy hỏng.
