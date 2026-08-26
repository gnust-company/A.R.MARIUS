# Quickstart — cách tự kiểm chứng tính năng này

**Feature**: 002 | **Phase**: 1

Tệp này là **cách chứng minh tính năng chạy thật**, không phải hướng dẫn code. Mỗi mục nối thẳng với một
tiêu chí đo được trong [spec.md](spec.md).

> Luật của dự án: **build xanh không tính là xong.** Phải dựng dịch vụ thật lên và tự lái qua giao diện.

---

## Chuẩn bị

```bash
# Backend + Postgres (cổng 8080 API, 3000 giao diện — 8000/5432 đang bị hàng xóm chiếm)
docker compose up -d --build

# Daemon
cd daemon && go build -o ./bin/armarius-daemon ./cmd/armarius-daemon
```

Cần **ít nhất một agent CLI thật** trên máy. Đợt đầu hỗ trợ `gemini`, `claude`, `codex`.

**Bắt buộc cho phần nhận việc**: chạy trên **Postgres thật**, không phải SQLite. Câu lệnh nhận việc dùng
`FOR UPDATE SKIP LOCKED`, mà SQLite không có — test trên SQLite sẽ xanh mà không chứng minh được gì.

---

## 1. Nối máy vào workspace — SC-001 (10 phút, tự làm)

```bash
./bin/armarius-daemon login --server http://localhost:8080
#   Mở http://localhost:3000/link và nhập mã:  KQ7F-M2XD
```

Mở địa chỉ đó, bấm duyệt.

**Mong đợi**: daemon in ra tên workspace và **danh sách agent CLI dò được**. Vào màn hình Máy trên giao
diện thấy máy vừa nối, mỗi CLI một chỗ làm ở trạng thái sẵn sàng, kèm tên máy đọc được.

**Bấm giờ từ lúc gõ `login`** — phải dưới 10 phút với người chưa từng cài.

---

## 2. Giao một đầu việc và xem nó chạy — SC-002, SC-003

Tạo agent gắn vào chỗ làm vừa có, tạo một đầu việc, giao cho nó.

**Mong đợi**:
- Đầu việc chuyển sang *đang làm*, agent CLI thật bật lên trên máy — kiểm bằng `ps aux | grep gemini`
- **Dưới 15 giây** từ lúc giao tới lúc tiến trình agent xuất hiện (SC-002)
- Diễn biến hiện dần trên màn hình theo dõi **không phải tải lại trang** (SC-003)

```bash
# Đo mốc 15 giây bằng dữ liệu thật, không bằng cảm giác
docker compose exec db psql -U armarius -c \
  "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (started_at - created_at)))
   FROM runs WHERE started_at IS NOT NULL;"
```

---

## 3. Hiện vật buộc rời khỏi máy — SC-004, SC-004a

Bảo agent tạo một tệp rồi công bố. Tải hiện vật về từ giao diện, so nội dung.

**Rồi thử ca ngược lại:**

```bash
# Agent chưa công bố gì mà cố đánh dấu xong → phải bị chặn kèm mã lý do
# Đầu việc vẫn giữ một động cơ đẩy sống, không rơi vào khoảng lặng
```

**Ca thử lại (SC-004a)** — cắt mạng giữa lúc công bố rồi cho công bố lại:

```bash
docker compose exec backend tc qdisc add dev eth0 root netem loss 100%   # cắt
# … cho agent công bố …
docker compose exec backend tc qdisc del dev eth0 root                   # nối lại
# … cho agent công bố lại y hệt …
```

**Mong đợi**: ra **đúng một** hiện vật, không ra hai, và **không phải chạy lại cả lượt**.

---

## 4. Nối lại đúng phiên — SC-006, SC-007

Gọi dậy hai lần trên cùng một đầu việc, lần hai hỏi một câu chỉ trả lời được nếu agent nhớ lần một.

**Mong đợi**: agent trả lời được. Thư mục làm việc **vẫn là thư mục cũ** — kiểm trên máy, tệp lần một còn
nguyên.

Rồi ép mất phiên (xoá trạng thái phiên trên máy) và gọi dậy lại: agent phải nhận được **câu báo bắt đầu
lại, bằng tiếng Anh** (SC-007, Điều VII).

---

## 5. Nhật ký đầy đủ — SC-011, SC-013, SC-014

Chạy một lượt có gọi ít nhất hai công cụ. Mở màn hình nhật ký.

**Mong đợi**:
- **Toàn văn tham số** của từng lần gọi công cụ
- **Bản rút gọn** kết quả, kèm dòng ghi rõ đã cắt bao nhiêu bytes
- Chỗ CLI không lộ dữ liệu hiện **khác** với chỗ bị cắt theo ngưỡng — hai lý do, hai cách hiện
- Lọc được theo loại sự kiện

**Kiểm điều quan trọng nhất — toàn văn kết quả công cụ KHÔNG lên server:**

```bash
docker compose exec db psql -U armarius -c \
  "SELECT count(*) FROM run_event_blobs b JOIN run_events e ON e.id = b.run_event_id
   WHERE e.type = 'tool.finished';"
#   PHẢI ra 0
```

**Che bí mật (SC-015)** — cho agent gọi một công cụ có token trong tham số:

```bash
docker compose exec db psql -U armarius -c \
  "SELECT count(*) FROM run_events WHERE payload::text LIKE '%<token đã gài>%';"
#   PHẢI ra 0 — che làm ở phía daemon, không phải ở server
```

**SC-014** — chạy một lượt sinh 1000 sự kiện, mở màn hình, cuộn. Không được treo.

---

## 6. Agent offline và phục hồi — SC-005, SC-010

```bash
# Gập máy giữa lượt chạy: giết daemon
pkill -f armarius-daemon
```

**Mong đợi trong vòng 5 phút** (SC-005): đầu việc **không** mất hết động cơ đẩy mà im lặng. Hoặc nó giữ
một động cơ hợp lệ, hoặc cờ đình trệ nổi lên.

```bash
# Bật lại trong khoảng ân hạn
./bin/armarius-daemon start
```

**Mong đợi** (SC-010): đầu việc **không mất** và **không chạy trùng** — kiểm bằng số lượt chạy trên đầu
việc đó, phải đúng như trước.

---

## 7. Hai máy không giẫm chân nhau — SC-009

Chạy 5 đầu việc đồng thời trên một máy.

```bash
docker compose exec db psql -U armarius -c \
  "SELECT run_id, count(*) FROM run_events WHERE type='run.started' GROUP BY run_id HAVING count(*) > 1;"
#   PHẢI rỗng — không lượt nào bị khởi động hai lần
```

Rồi ép hai cú xin việc đồng thời từ cùng một máy (bật hai tiến trình daemon cùng lúc) — **cùng phải rỗng**.
Đây là ca [FR-054b](spec.md) nói tới, và là ca duy nhất `atomic compare-and-swap` tồn tại để chặn.

---

## 8. Thêm một loại agent CLI mà không đụng tầng nghiệp vụ — SC-008

```bash
cd backend && uv run pytest tests/test_business_layer_knows_no_runtime.py
```

Phép kiểm này quét mã và **phải đỏ** nếu chuỗi `daemon`, `machine`, `runtime` xuất hiện trong
`application/use_cases/` hay `domain/`. Gỡ mất ranh giới thì test đỏ, không được im lặng trôi (FR-038).

---

## 9. Kỹ năng đi xuống cùng gói việc — FR-011b, FR-013a

Gắn một kỹ năng vào agent trên giao diện, rồi chạy một lượt và soi ngay trên máy trong lúc nó còn chạy.

```bash
# Thu muc ky nang native cua CLI dang chay — vi du Claude Code
ls -la ~/.armarius/work/<task-id>/.claude/skills/
#   PHAI la TEP THAT, khong phai symbolic link (cot dau khong bat dau bang 'l')
```

**Mong đợi**:
- Kỹ năng nằm đúng thư mục native của CLI ấy, theo bảng ở [research §11.1](research.md)
- **Tệp thật**, không phải liên kết ra kho dùng chung — đây là chỗ Multica cố ý làm khác với đăng nhập và
  ký ức, và là điều kiện để nhiều agent dùng chung một chỗ làm mà không đọc được kỹ năng của nhau
- Cấu hình CLI của chính người dùng (`~/.claude/`) **không bị đụng**

**Ca ghi mới**: đổi nội dung kỹ năng trên giao diện rồi gọi dậy lại cùng đầu việc ấy — nội dung trên máy
phải là bản mới, không phải bản cũ còn sót.

**Ca tách theo agent**: hai agent khác nhau trên **cùng một chỗ làm**, mỗi cái một kỹ năng khác nhau. Chạy
cả hai, soi hai thư mục làm việc — không cái nào thấy kỹ năng của cái kia.

**Ca đường cũ đã đóng**: agent gọi `GET /agent/skills` phải nhận **404** — đường tự cài đã gỡ (FR-011c).

---

## Chạy toàn bộ test

```bash
cd backend  && uv run pytest                # 96 tệp hiện có + ~18 tệp mới
cd backend  && TEST_DATABASE_URL=postgresql+psycopg://armarius:armarius@localhost:5434/armarius_test \
               uv run pytest tests/test_run_claim_races.py     # BẮT BUỘC trên Postgres thật
cd daemon   && make check                   # go vet + golangci-lint + go test
cd frontend && npm run build
```

Đổi giao diện thì **phải dựng lại container frontend** rồi **lái thật bằng Playwright** — không được dừng ở
`npm run build` xanh. Playwright là công cụ của người kiểm, chạy từ bản cài sẵn trên máy; **không thêm vào
`frontend/package.json`** và không nộp bộ test vào repo. Cùng cách đã làm ở feature 001.
