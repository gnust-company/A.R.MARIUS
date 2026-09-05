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
| **Gemini CLI** (`--acp`; `--experimental-acp` là tên cũ, còn nhận) | ACP | Người chủ chốt là bắt buộc (FR-039) |
| **Claude Code** | chạy-một-phát | Đang dùng thật hằng ngày trong dự án |
| **Codex** | app-server *(bảng này ghi là chạy-một-phát cho tới 2026-09-05 — xem §9.3)* | Có mô hình thư mục nhà riêng, thử được cơ chế dựng môi trường |

**Rationale**: hai họ giao thức đều có đại diện ngay từ đợt đầu, nên ranh giới ở FR-035/FR-037 bị ép phải
đúng từ sớm thay vì được dựng quanh một họ rồi sửa sau. Hoá ra có **ba** họ, và ranh giới ấy chịu được —
họ thứ ba nối vào bằng một hàng trong bảng loại CLI và một tệp trong gói runtime, không sửa gì phía trên.

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

**Ghi 2026-08-25, đo trên máy phát triển lúc làm T033:** `gemini` **có** trên máy này, bản `0.56.0`, và
`gemini --version` chạy được. Hai điều đọc thẳng từ `gemini --help` của chính bản ấy:

- **Cờ đã đổi tên.** `--acp` là cờ hiện tại; `--experimental-acp` vẫn còn nhưng bản trợ giúp ghi rõ
  *"deprecated, use --acp instead"*. Cả đặc tả (FR-039) lẫn mục 9 ở trên đều đang chép tên cũ. Mã nào bật
  ACP phải dùng `--acp`, giữ tên cũ làm đường lui.
- Nó cũng khai `-r, --resume`, `--session-file`, `--session-id`, `--list-sessions` và
  `-o, --output-format` có `stream-json` — tức ngoài ACP nó còn một đường chạy-một-phát. Đợt này không
  dùng đường ấy: chọn họ giao thức là việc của T116/T117, sau khi T013 chạy thật.

Cái này **không tick được T013**: bốn câu hỏi của T013 hỏi về *phiên ACP đang chạy*, không hỏi về bản trợ
giúp, và `gemini --acp` cần đăng nhập thì mới bắt tay được. Nửa chạy thật vẫn chờ `probe-gemini-acp.mjs`.

**Câu hỏi thứ năm, không có trong bảng gốc nhưng daemon không tránh được**: `gemini` có đòi đăng nhập tương
tác khi bị **một chương trình khác** khởi chạy (stdin không phải terminal) không? Issue #12042 báo đúng ca
này, và daemon **luôn** chạy nó theo kiểu đó. Script hỏi luôn câu này.

### 9.2 Chạy thật, 2026-08-31 — `gemini 0.56.0` trên máy phát triển

Ghi chú 2026-08-24 *"máy phát triển không cài được `gemini`"* đã lỗi thời: `gemini` **có** trên máy, chạy
được, và daemon đăng ký nó thành chỗ làm *ready*. Đã chạy `daemon/scripts/probe-gemini-acp.mjs`.

**Đo được — đây là phần thay thế phỏng đoán:**

| Điều | Kết quả |
| --- | --- |
| Bắt tay ACP khi bị chương trình khác bật, stdin không phải terminal | **XONG SẠCH.** `initialize` trả về `{"name":"gemini-cli","version":"0.56.0"}` |
| Câu hỏi thứ năm (issue #12042): có đòi đăng nhập tương tác không | **KHÔNG.** Bắt tay đi qua bình thường |
| `agentCapabilities` nó tự khai | `loadSession: true`, `promptCapabilities: {image, audio, embeddedContext}`, `mcpCapabilities: {http: true, sse: true}` |

`loadSession: true` **đo được**, không phải đọc mã — issue #15502 báo `false` là bản cũ, đúng như mục 9.1
dự đoán. `mcpCapabilities` là thứ T061 cần khi khai bộ công cụ gọi ngược cho Gemini.

**Không đo được, và vì sao:** một lượt prompt không chạy nổi. Google **cắt hẳn client này cho tài khoản cá
nhân miễn phí** — không phải hết quota:

```
IneligibleTierError · reasonCode: UNSUPPORTED_CLIENT · tierId: free-tier
"This client is no longer supported for Gemini Code Assist for individuals.
 To continue using Gemini, please migrate to the Antigravity suite of products"
```

Nên câu 1, 2, 4 (dấu cắm trong `GEMINI.md` có tới model không, kỹ năng có được thấy không, lời gọi công cụ
mang gì) **vẫn chưa xem tận mắt**. Đường đáng thử tiếp: `GEMINI_API_KEY` — Gemini CLI có đường xác thực
bằng API key, khác đường OAuth vừa bị chặn.

**Phát hiện phụ, đọc mã nguồn trên mạng không ra — và nó là thứ quan trọng nhất của cả lần chạy:**

Gemini có **cổng thư mục tin cậy**. Chạy trong `/tmp/...` nó ghi ra luồng lỗi:

```
Skipping project agents due to untrusted folder.
Project hooks disabled because the folder is not trusted.
```

Thư mục daemon tự tạo cho mỗi đầu việc **luôn** là thư mục chưa ai tin cậy. Không xử thì bản tóm tắt ghi
vào `GEMINI.md` nằm đó không ai đọc — mà **không có lỗi nào**: đúng hình dạng hỏng-trong-im-lặng.

Cách xử, đọc từ chính bundle của bản cài (`checkPathTrust`): biến môi trường
**`GEMINI_CLI_TRUST_WORKSPACE=true`** được xét **trước** danh sách trên đĩa. Một biến, không phải sửa
`trustedFolders.json` của người vận hành.

**Ba thứ nữa đọc từ bundle bản cài** (`/usr/local/lib/node_modules/@google/gemini-cli/bundle`), mạnh hơn
tài liệu vì đó là đúng thứ đang chạy:

- `GEMINI_DIR = ".gemini"` là **hằng số**, không phải biến nó đọc ⇒ chỉ có một cần gạt là đổi `HOME`.
- `.gemini/skills` — có trong bundle. Thư mục kỹ năng **cá nhân** (`~/.gemini/skills`) đọc không cần
  quyết định tin cậy, còn thư mục kỹ năng của dự án thì nằm sau đúng cái cổng ấy.
- `"GEMINI.md"` và `contextFileName` — có trong bundle.

**Còn phải đo lại khi có tài khoản chạy được**: dấu cắm trong `GEMINI.md` và trong kỹ năng có quay lại
trong câu trả lời của model không; và một lời gọi công cụ mang `rawInput`/`rawOutput` hay chỉ mang tiêu đề.


---

### 9.3 Codex: đo bằng nguồn của chính nó, không đo bằng cách chạy (2026-09-05, T130)

Máy phát triển không chạy nổi `codex` một lần nào — bản cài npm thiếu gói nền tảng
(`Missing optional dependency @openai/codex-linux-x64`), nên nó không khởi động, không phải hết quota.

Nên câu trả lời tới từ hai nguồn hạng khác nhau, và chỗ này ghi rõ hạng nào:

| Nguồn | Cho biết | Hạng |
| --- | --- | --- |
| `multica-ai/multica`, `server/pkg/agent/codex.go` | Multica chạy `codex app-server --listen stdio://`, không phải `codex exec` | mã của một daemon đang chạy thật — đã bị Codex thật sửa lưng |
| `openai/codex`, `codex-rs/app-server-protocol` và `codex-rs/app-server/README.md` | tên từng phương thức, hình dạng từng tin, tên từng trường, tập giá trị từng enum | **chính hợp đồng**, không phải mô tả lại hợp đồng |
| chạy một lượt thật | công cụ có tới tay agent không, mạch có nối lại được không, cạn hạn mức in ra câu gì | **chưa có** — T130a |

Ba thứ hợp đồng nói ra mà đọc Multica một mình không thấy:

1. Bắt tay là **hai** tin: `initialize`, rồi thông báo `initialized`. Mọi câu khác trên đường nối ấy bị từ
   chối *Not initialized* cho tới khi tin thứ hai tới. Thiếu nó là một daemon nối được rồi bị nói không với
   mọi thứ nó hỏi.
2. `thread/resume` mặc định **trả cả lịch sử mạch** về trong `thread.turns`, và cách tắt là `excludeTurns:
   true`. Không tắt là trả tiền để chuyển một bản ghi qua ống rồi bỏ đi.
3. `decline` được **định nghĩa trong nguồn** là *người dùng từ chối; agent sẽ đi tiếp lượt của nó* — khác
   `cancel`, thứ cắt luôn lượt chạy. Nên từ chối quyền theo FR-013b có đúng một từ đúng, và nó không phải
   từ làm chết lượt chạy.

Và một thứ chỉ đọc mã Multica mới thấy, vì nó là hệ quả của việc không có ai ngồi đây: Codex **gọi ngược
lại** để xin duyệt, qua bốn phương thức. Bảng khai cũ của Armarius thiếu hẳn nhánh này — tức một lượt chạy
gặp lệnh cần duyệt sẽ **treo**, không phải hỏng. Đó là FR-039e.

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
| **Gemini CLI** | `GEMINI.md` | `.gemini/skills/` (bản cá nhân, trong nhà) |

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

---

## 12. Lối gọi ngược của agent — một thứ, hai mặt (chốt 2026-08-29)

### 12.1 Agent gọi về bằng gì

**Decision**: daemon cấp cho mỗi lượt chạy **một binary**, mang hai mặt của cùng một danh sách việc — gọi
được như **một lệnh** từ thư mục làm việc, và nói được **giao thức nạp công cụ (MCP) qua luồng chuẩn** cho
CLI nào biết nạp (FR-013a). Token của lượt chạy đi qua **biến môi trường**, không qua tham số dòng lệnh
(FR-013c).

**Rationale**: mặt lệnh là mặt nền vì **mọi** agent CLI đều chạy được một lệnh — kể cả loại không có cơ chế
nạp công cụ nào — nên không CLI nào bị bỏ lại và ranh giới FR-035/FR-037 không phải rẽ nhánh theo tên
runtime. Mặt native là mặt Multica dùng (§7) và là chữ FR-013a vốn đã viết. Một binary chứ không hai bản
cài, vì hai bản là **hai danh sách việc agent làm được**, và chúng sẽ lệch nhau đúng vào lúc thêm việc mới.

**Alternatives considered**:

- *Giữ tờ hướng dẫn dạy agent tự viết lời gọi mạng* — đây là hiện trạng: 405 dòng, 22 lời gọi `curl`, 22 lần
  nhắc token sống lâu. Bỏ vì loại token ấy đang bị gỡ (FR-014g), và vì FR-043 ghi **đầy đủ tham số** mỗi lần
  agent gọi công cụ: một lời gọi mạng cầm credential trong tham số là một credential nằm trong bản ghi trên
  server.
- *Chỉ làm mặt native, đúng như Multica* — bỏ vì CLI của đợt đầu không đồng đều, và một agent không nạp được
  công cụ thì mất **toàn bộ** đường gọi ngược chứ không mất một phần.
- *Agent không cầm token, binary nói với daemon qua một lối cục bộ rồi daemon mới gắn token* — chặn rò tận
  gốc, nhưng phải sửa FR-014a (Multica cũng bơm token qua biến môi trường, §6) và đẻ thêm một mặt tiếp xúc
  cục bộ phải giữ tương thích về sau. Không chọn: token của lượt chạy đã có phạm vi hẹp và chết lúc khép
  lượt, nên phần lợi thêm không đáng cái giá ấy.

**Giá phải trả của phương án đã chọn, ghi ra để sau này khỏi phải tìm lại** (người chủ nêu lúc review PR
#236, 2026-08-29): token của lượt chạy nằm trong biến môi trường của tiến trình agent, nên **mọi tiến trình
con agent tự khởi chạy đều thừa kế nó**. Chấp nhận được vì token chết lúc khép lượt và chỉ mở đúng một đầu
việc. Nhưng nếu về sau có yêu cầu chặt hơn — ví dụ agent được phép chạy mã của người lạ — thì đây là chỗ
phải xem lại đầu tiên, và phương án *agent không cầm token* ở trên là chỗ quay về.

### 12.2 Phạm vi của một lượt chạy

**Decision**: phạm vi quyết bằng **bộ công cụ cấp cho lượt ấy**, không bằng một bảng quyền tra lúc gọi
(FR-013d). Lượt chạy cấp đầu việc nhận công cụ của đầu việc; lượt chạy cấp dự án nhận công cụ của dự án.
Server vẫn từ chối cú ghi vượt phạm vi (FR-059).

**Rationale**: đây là cách Multica trả lời câu ấy — *công cụ đi theo đầu việc như hành lý* (§7) — và nó hợp
với ta vì bảng lượt chạy **đã có sẵn hai cấp**: `runs.task_id` để trống được, và bảy cớ gọi dậy cấp dự án đã
tồn tại từ đặc tả 001. Không phải đẻ khái niệm mới, chỉ phải đọc đúng thứ đã có.

**Alternatives considered**: cho lượt chạy nào cũng chạm được mọi thứ trong dự án của nó. Bỏ vì khi ấy một
agent thợ đang làm một đầu việc cũng nộp được kế hoạch dự án — thu hẹp thời hạn của token mà không thu hẹp
quyền thì gần như không thu được gì.

### 12.3 Buổi onboarding cũng là một lượt chạy

**Decision**: buổi hỏi–đáp dựng đội của Tác nhân Không gian là **một lượt chạy cấp workspace** — không đầu
việc, không dự án (FR-040c).

**Rationale**: hai lối `/agent/onboarding/*` là **thứ duy nhất** trong 22 lối agent không thuộc lượt chạy
nào. Nếu chúng không thành lượt chạy thì lối xác thực phải chừa lại một đường thứ hai cho riêng chúng, và
token sống lâu không bao giờ chết được — T039d đứng vĩnh viễn. Bảng lượt chạy cho phép cả `task_id` lẫn
`project_id` để trống, nên không phải thêm gì vào schema.

**Alternatives considered**: đúc một loại token thứ ba sống bằng đúng buổi phỏng vấn. Bỏ vì FR-014a nói
thẳng hệ thống chỉ có hai loại, và một ngoại lệ cho một màn hình là cách một luật bắt đầu mục ruỗng.

---

## 13. Model và mức suy nghĩ — Multica hỏi runtime, không tra bảng (chốt 2026-08-29)

**Decision**: danh sách model và mức suy nghĩ **hỏi chỗ làm**, và mỗi danh sách nói rõ **nó chắc đến đâu**.
Bảng tên model cho tool không liệt kê được thì **được phép nằm ở daemon**, cấm ở server (FR-007k, sửa
2026-08-29).

**Nguồn**: [multica.ai/docs/agents-create](https://multica.ai/docs/agents-create),
[multica.ai/docs/agents](https://multica.ai/docs/agents), đọc 2026-08-29. Nguyên văn:

> *"Each runtime already maps to one AI coding tool. After picking a runtime, you can pick a model and
> thinking level **the tool supports**."*
> *"Some tools expose a **fixed set of model names**; others return available models based on **local
> configuration, the signed-in account, and subscription entitlements**."*
> *"If the list is empty, confirm the runtime is online and the tool is signed in, then **refresh** the
> model list."*
> *"Left blank, the runtime or local CLI default applies."*

**Rationale**: đây là câu trả lời cho một chỗ đặc tả ta tự viết vào ngõ cụt. FR-007k bản đầu cấm "bảng chép
cứng theo tên CLI" mà không nói cấm ở đâu — mà đo `claude 2.1.226` thì **không có đường liệt kê model**:
`--model` chỉ in ví dụ, không lệnh con nào liệt kê, `config list` đòi tương tác. Đọc chặt thì FR-007k tự mâu
thuẫn với chính CLI đầu tiên của đợt. Multica tách được nút ấy: bảng nằm ở **phía máy**, chỗ nhìn thấy tool
đã cài và tài khoản đang đăng nhập, còn server thì không giữ bảng nào — đúng Điều III.

**Đo được, và tốt hơn ta tưởng**: cả hai danh sách của Claude Code ra thẳng từ binary, **không cần bảng nào
cả**.

| Thiết lập | Cách tool khai | Đọc ra |
| --- | --- | --- |
| mức suy nghĩ | `--effort <level>` … `(low, medium, high, xhigh, max)` | **bộ đủ** — giá trị ngoài nó bị từ chối |
| model | `--model <model>` … `(e.g. 'fable', 'opus', or 'sonnet')` | **ví dụ** — nhận cả giá trị người dùng tự gõ |

**Ba luật kế thừa thêm**, FR-007k bản đầu chưa có:

- **danh sách rỗng là trạng thái hợp lệ** kèm lý do đọc được, không phải lỗi;
- **số lựa chọn khác nhau theo tool** — Codex có thêm *service tier*, nên chỗ chứa phải theo thứ tool khai
  ra, không phải hai cột đúng tên;
- Multica **xoá** model/mức nghĩ/hạng khi agent bị ép sang runtime khác, *"those three are cleared and must
  be re-selected"*. Ta **không cần** luật này: FR-007 buộc agent vào đúng một chỗ làm suốt đời, không có
  đường đổi (T077 đã chốt). Ghi ra để sau này ai định mở đường đổi thì biết còn món nợ này.

**Alternatives considered**: *ô nhập tự do cho model* — đơn giản nhất, bỏ vì người dùng gõ sai thì lượt chạy
hỏng lúc khởi chạy chứ không hỏng lúc chọn. *Để task đứng tới khi có CLI liệt kê được* — bỏ vì mức suy nghĩ
đã liệt kê được ngay, và chặn cả hai vì một nửa là bỏ phí nửa đo được.
