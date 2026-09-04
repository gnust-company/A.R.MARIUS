# Số đo công nhận — chạy trọn [quickstart.md](quickstart.md) trên dịch vụ thật

**Feature**: 002 · **Task**: T129 · **Đo ngày**: 2026-09-04

Đây là bản ghi của **một lần chạy thật**, không phải bản kế hoạch. Mỗi dòng dưới đây là một con số
đọc được từ dịch vụ đang sống, và chỗ nào không đo được thì nói rõ là không đo được cùng lý do —
một tiêu chí ghi *đạt* mà không có số đo là một tiêu chí chưa kiểm.

> Luật của dự án: **build xanh không tính là xong.**

---

## Chỗ đo

| | |
|---|---|
| Máy | Linux 6.8, một máy, `gnust-Nitro-AN515-55` |
| Dịch vụ | `docker compose` — API :8080, giao diện :3000, Postgres :5434, MinIO trong mạng compose |
| Daemon | dựng từ nguồn của nhánh này, cả `armarius-daemon` và `armarius` |
| Agent CLI dò được | `claude_code` 2.1.252 · `gemini` 0.56.0 · `codex` **không chạy nổi** (thiếu binary nền tảng, `cli_not_runnable`) |
| Họ CLI đã lái thật | `claude_code` (một-phát). Họ ACP không lái được: tài khoản `gemini` trên máy này bị hãng từ chối ở `session/new` (đã đo ở T131a) |

Mọi lượt chạy trong bản ghi này là **agent CLI thật trên máy thật**, gọi dậy qua cửa thật, đọc lại
bằng màn hình thật. Không có chỗ nào giả lập tiến trình agent.

---

## Mười sáu tiêu chí

| Tiêu chí | Số đo | |
|---|---|---|
| **SC-001** nối máy trong 10 phút | **112,8 giây** từ lúc gõ `login` tới câu *Linked*, kể cả thời gian mở trình duyệt và bấm duyệt. Màn hình Máy sau đó hiện đủ hai chỗ làm ở trạng thái sẵn sàng | đạt |
| **SC-002** 95% dưới 15 giây | Năm lượt gọi dậy trên một máy còn chỗ trống: **0,14 – 0,19 giây**, p95 **0,19 giây**. Con số p95 tính trên *toàn bộ* lượt chạy của phiên đo là 184 giây, và đó là số của hai thứ khác: những lượt xếp hàng sau một lượt khác trên cùng máy (FR-008a), và hai quãng daemon bị tắt có chủ ý | đạt |
| **SC-003** hiện lên trong 3 giây | Mười sự kiện trên một màn hình đang mở: chín cái **0,02 – 0,14 giây**, cái chậm nhất **1,20 giây** (sự kiện đầu, sinh ra lúc trang còn đang tải). **Không một lần tải lại trang nào** — đếm bằng `framenavigated` | đạt |
| **SC-004** hiện vật tải về được | Agent thật viết tệp rồi tự công bố bằng công cụ của nó; tải về từ giao diện ra **`report.txt`, 10 bytes, đúng từng byte** | đạt |
| **SC-004a** công bố lại ra đúng một | Gửi trọn một cú công bố rồi **cắt socket trước khi đọc câu trả lời** (đúng hình dạng câu trả lời chết trên đường), rồi gửi lại y hệt: lần hai trả **200** với cùng một `id`, đầu việc có **đúng một** hiện vật, và nó tải về được | đạt |
| **SC-005** không mất động cơ đẩy quá 5 phút | `kill -9` daemon giữa lượt chạy. Sau **156 giây** đầu việc chuyển `blocked` kèm lý do *người phụ trách ngoại tuyến*, và giữ động cơ `run_active` với hạn riêng của nó (`drive_expires_at` = lúc bắt đầu + 14 phút). Không lúc nào rơi vào khoảng lặng | đạt |
| **SC-006** 95% gọi dậy sau lần đầu nối lại được phiên | Mười một lượt trên một đầu việc, đọc từ `runs.session_id_before/after`: **8 trên 8** lượt trong điều kiện SC-006 nêu (cùng máy, trong hạn giữ) nối lại đúng phiên cũ = **100%**. Hai lượt còn lại là hai ca **bị cố ý phá** để đo SC-007 | đạt |
| **SC-007** 100% lần không nối lại được đều được báo | Hai ca, hai cách phá khác nhau: sợi chỉ thuộc chỗ làm khác, và sợi chỉ quá hạn giữ. Cả hai ghi lại **mã kèm tham số** (`session_workplace_rebuilt`, `session_expired` với `idle_seconds`) và cả hai **mở phiên mới**, mở đầu bằng đúng câu tiếng Anh — đọc lại nguyên văn trong bản ghi phiên của CLI | đạt |
| **SC-008** thêm CLI không sửa tầng nghiệp vụ | `tests/test_constitution_guards.py` — **11 bài, xanh cả 11**. Hai bài đầu là bài quét mã | đạt |
| **SC-009** một máy chạy được ít nhất 5 lượt đồng thời | Nâng trần trên màn hình Máy lên 5, rồi năm agent nhận việc cùng lúc: **đỉnh chồng nhau = 5**, cả năm xong, và `run.started` **không lượt nào có hai lần** | đạt |
| **SC-010** offline rồi online lại: không mất, không chạy trùng | Daemon quay lại trong khoảng ân hạn: lượt cũ bị thu là `timed_out`, đầu việc còn nguyên, và sinh ra **đúng một** lượt thay thế (2 lượt tổng: 1 chết + 1 chạy xong) | đạt |
| **SC-011** 100% lần gọi công cụ đọc lại được tham số và bản rút gọn | Một lượt có ba lần gọi công cụ: `tool.started` mang **toàn văn** tham số, `tool.completed` mang `bytes` và đoạn mở đầu. Đọc lại trên màn hình nhật ký: `seq 1 20000` hiện nguyên văn | đạt |
| **SC-012** sự kiện lên màn hình trong 3 giây | Cùng phép đo với SC-003 | đạt |
| **SC-013** trả lời được *agent đã làm gì và vì sao* chỉ bằng nhật ký | Màn hình nhật ký của một lượt chở: lời nhắc đã gửi, từng lần gọi công cụ kèm tham số đầy đủ, bản rút gọn kết quả kèm kích thước thật, lời agent nói, và lọc được theo loại sự kiện | đạt |
| **SC-014** 1000 sự kiện vẫn mở và cuộn được | Một lượt **1001 sự kiện**: hàng đầu hiện sau **0,92 giây**, đọc hết sau **3,80 giây**, và chỉ **13 hàng** thực sự nằm trong DOM cùng lúc. Mười hai bước cuộn, bước chậm nhất **0,16 giây** | đạt |
| **SC-015** không giá trị bí mật nào lọt lên nguyên bản | Gài một chuỗi hình dạng khoá API vào tham số một lệnh Bash. Trên máy chủ, tham số về thành `echo '[redacted]'`. Đếm trong cơ sở dữ liệu: **0** trong `run_events` và **0** trong `run_event_blobs`, tính trên mọi sự kiện **daemon gửi lên** | đạt |

### Một chỗ phải nói rõ ở SC-015

Câu đếm phải trừ `run.prompt` ra. Sự kiện ấy là lời nhắc **do chính máy chủ soạn** từ chữ người chủ
gõ vào mô tả đầu việc — chuỗi gài của phép đo này nằm ở đó vì chính tay tôi gõ nó vào, và nó đã ở
trên máy chủ từ trước khi có lượt chạy nào. FR-048 đặt việc che ở phía máy: *bí mật nào tới được máy
chủ thì đã rời khỏi máy rồi*. Chiều đi lên là chiều được che, và nó **sạch**. Chuyện người chủ tự gõ
một bí mật vào ô mô tả là một câu hỏi khác, và bản đặc tả chưa hỏi nó.

### Một chỗ phải nói rõ ở SC-004

Đo trên kho hiện vật **`local`**, không phải MinIO. MinIO trên máy này từ chối mọi lượt ghi với
`XMinioStorageFull`: nó đòi một tỉ lệ trống tối thiểu trên ổ, mà ổ của máy này đang đầy 100% (còn
khoảng 6 GB trên 938 GB — MinIO cần cỡ 47 GB). Đây là **điều kiện của cái máy**, không phải của sản
phẩm: cùng đường mã ấy, cùng cửa ấy, cùng phép kiểm tự động ấy chạy trên cả hai kho. Dọn đủ chỗ
trống rồi chạy lại `s3d`/`s3e` là đo lại được trên MinIO trong hai phút.

Kèm một điều đo được lúc làm: kho `local` **không có volume** trong `docker-compose.yml`, nên nó
chết theo container — dựng lại image một lần là mất hết bytes đã công bố. Nó là kho cho phép kiểm và
cho lúc phát triển, không phải kho để chạy thật, và mặc định của compose là MinIO vì đúng lý do đó.

---

## Bốn thứ lần chạy này lòi ra, và đã sửa trong cùng PR

**1. Trần số lượt chạy đồng thời không ai đổi được.** `machines.max_concurrent` là một cột với mặc
định bằng 1 mà **không cửa nào, không màn hình nào ghi vào** — 47 hàng máy trong cơ sở dữ liệu đều
đứng ở 1. Cửa nhận việc lấy số nhỏ hơn giữa nó và số chỗ trống daemon báo (FR-008d), nên trần 1 là
trần thật: SC-009 **không lần nào đạt được**, và FR-008 nói *trần ấy PHẢI chỉnh được* thì đúng với
schema mà sai với sản phẩm. Nay có `PATCH /v1/workspaces/{ws}/machines/{id}` và một ô trên màn hình
Máy; đo lại SC-009 thì đỉnh chồng nhau lên đúng 5.

**2. Hiện vật công bố rồi không tải về được.** Bytes vào kho dùng chung và được đọc lại một lần để
chứng minh kho có giữ — rồi **không cửa nào xin lại được nữa**, và cái liên kết trên màn hình đầu
việc trỏ vào đường dẫn tương đối trong kho, tức là trỏ vào không đâu cả. *Đã lưu* và *lấy lại được*
là hai lời khẳng định khác nhau, mà SC-004 hỏi lời thứ hai. Nay có
`GET /v1/tasks/{id}/artifacts/{artifact_id}/content` và một nút tải thật trên màn hình.

**3. Cửa công bố của người chủ trả 201 cho một lần thử lại.** Cửa của agent đã làm đúng FR-020c từ
trước (201 lần đầu, 200 khi cùng bytes cùng tên đã có); cửa của người chủ trả 201 cho cả hai. Không
đẻ ra hàng thứ hai, nhưng mã trạng thái là thứ người gọi đọc được mà không cần bóc thân câu trả lời,
và nói *đã tạo* về một lần không tạo gì là nói sai ở đúng chỗ ấy.

**4. Cạn hạn mức: đo được rồi (T124a).** Ba mươi mốt lượt chạy trên tài khoản đã quá hạn mức in ra
đúng một dòng — `You've hit your session limit · resets 5:50pm (Asia/Ho_Chi_Minh)` — rồi thoát 1 với
`is_error: true` **và** `subtype: "success"`. Nên các trường có cấu trúc không phân biệt được ca này
với bất kỳ ca thoát-lỗi nào khác; câu chữ là chỗ duy nhất nói ra sự khác biệt. Đây là phép đo mà
T124a chờ. Daemon nay khai `failure: "quota_exhausted"` cho họ `claude_code`, chỉ khi lượt chạy
**thật sự hỏng** — một agent nhắc tới hạn mức trong lúc làm xong việc thì không phải đụng tường.

---

## Bốn thứ quickstart nói sai, và đã sửa

- Mục *Chuẩn bị* chỉ dựng `armarius-daemon`. Daemon **từ chối chạy** nếu không có `armarius` bên
  cạnh — `make build` cũng chỉ dựng một cái. Nay cả hai, ở cả hai chỗ.
- Mục §1 nói `login` in ra danh sách CLI dò được. Không: đó là việc của `start`.
- Mục §5 đếm blob trên `e.type = 'tool.finished'`, một **loại sự kiện không tồn tại** (loại thật là
  `tool.completed`). Câu ấy vẫn ra 0 — số 0 của một câu hỏi rỗng, và là một phép kiểm luôn xanh.
- Mục §8 gọi `tests/test_business_layer_knows_no_runtime.py`, tệp không có. Bài thật ở
  `tests/test_constitution_guards.py`.
- Mục §6 dùng `pkill -f armarius-daemon`, mà `-f` khớp cả dòng lệnh nên nó giết luôn cái shell đang
  gõ câu ấy. Nay `pkill -x`. Thêm một câu về việc SC-005 phải đo trên đầu việc ở trạng thái **cái
  lưới an toàn có nhìn tới**: việc mới tạo nằm ở `backlog`, mà `backlog` cố ý không ai canh.

---

## Ba chỗ thấy được nhưng không sửa ở PR này

- **Agent không có động từ để đẩy đầu việc ra khỏi `backlog`.** Công cụ `update_task` nhận
  `backlog / in_progress / in_review / done`, mà `backlog → in_progress` là bước không hợp lệ — đường
  hợp lệ đi qua `todo`, và `todo` không có trong danh sách agent được đưa. Chính agent nói ra điều
  này trong `next_action` của nó. Là chuyện của đặc tả 001 (vòng đời đầu việc), không phải của 002.
- **Một lần bắt đầu lại được ghi bằng sự kiện `run.error`.** Mã và tham số thì đúng (Điều VII), chỉ
  cái tên loại là sai: bắt đầu lại một cuộc nói chuyện không phải một lỗi, và màn hình đọc nó ra như
  lỗi. Đổi tên một loại sự kiện là đổi hợp đồng, nên để riêng.
- **`tasks.status_reason` lưu một câu tiếng Việt** (*người phụ trách ngoại tuyến*). Trường này chỉ
  người chủ đọc nên chưa vi phạm Điều VII, nhưng nó là câu lưu sẵn thay vì mã kèm tham số, và một
  màn hình đổi ngôn ngữ sẽ không đổi được nó. Cũng là chuyện của 001.

---

## Chạy lại bản ghi này

Tám mục của [quickstart.md](quickstart.md), theo đúng thứ tự ấy, trên dịch vụ dựng từ nhánh này. Ba
điều kiện của môi trường phải có trước, và cả ba đã làm lần này hụt một lần rồi mới thấy:

1. **Cả hai binary** (`make build`), không thì `start` chết ngay.
2. **Một agent CLI thật chạy được và còn hạn mức.** Hạn mức cạn giữa phiên đo thì mọi lượt sau đó
   hỏng, và bản ghi sẽ đầy những con số của một thứ khác.
3. **CLI của người vận hành phải được phép làm việc trong thư mục của nó.** Daemon cố ý không trả
   lời câu hỏi về quyền thay người chủ (FR-013b): nó chỉ cho phép đúng bộ công cụ gọi ngược của
   chính nó. Mọi quyền khác là thiết lập của CLI ấy, và không có nó thì agent viết một tệp cũng
   không xong.
