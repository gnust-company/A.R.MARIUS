# Tasks: Daemon tại máy người dùng và chuẩn ACP

**Input**: Design documents from `specs/002-daemon-acp-runtime/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/)

**Tests**: **CÓ, bắt buộc.** Đặc tả tự yêu cầu phép kiểm tự động ở FR-038, SC-008 và SC-015 — không phải
lựa chọn.

**Organization**: Nhóm theo user story để mỗi story dựng và kiểm được độc lập.

## Format: `[ID] [P?] [Story] Mô tả kèm đường dẫn tệp`

- **[P]**: chạy song song được (khác tệp, không phụ thuộc task chưa xong)
- **[Story]**: US1…US5 theo spec.md

---

## Ngoài phạm vi đợt này — nói rõ để khỏi hiểu nhầm là sót

| Thứ | Vì sao không có task |
| --- | --- |
| **Dựng CI** | Repo chưa có `.github/workflows` hay bất kỳ cấu hình CI nào, và **không FR nào của đặc tả này yêu cầu CI**. Dựng CI từ số không là một khối việc riêng, phải có FR riêng. Đợt này chạy kiểm tại chỗ bằng `daemon/Makefile` và `uv run pytest` |
| **FR-006b, FR-028, FR-029, FR-029a** — agent bị tuyên offline, khoảng ân hạn, lượt chạy bị tuyên hỏng | **Không cần task mới.** Đặc tả tự nói "chạy đúng luồng offline đang có". T042 làm agent chuyển offline; từ đó luồng `LivenessState`/`plan_tick` và thang phục hồi ba mức đang chạy sẵn tiếp quản, kể cả `_WAKE_GRACE`. Việc duy nhất phải làm là **chứng minh** — T126 |
| **FR-029b** — tầng dưới giữ được tiến trình sống qua một lần đứt | Điều khoản dạng cho phép, không dạng bắt buộc. Chỉ áp khi một CLI cụ thể làm được; chưa CLI nào trong ba cái đợt đầu khai điều đó |
| **FR-039b** — kế thừa cách làm không kế thừa câu chữ | Ràng buộc pháp lý về cách viết nội dung, không phải việc lập trình. Thể hiện ở T056 và ở `daemon/README.md` (T127) |
| **FR-060** — không mở lại đường thợ tự nhận việc | Điều khoản dạng cấm. Đường ấy đã gỡ ở đặc tả 001, dấu vết còn ở `presentation/api/agent.py:378`. T024 canh không cho nó quay lại |

---

## Phase 1: Setup

**Purpose**: dựng khung cho chương trình Go mới và chỗ ngồi của phần backend mới.

- [x] T001 Tạo thư mục `daemon/` với `go.mod` (module `github.com/gnust-company/armarius-daemon`, Go 1.23+)
- [x] T002 [P] Tạo khung lệnh `daemon/cmd/armarius-daemon/main.go` với ba lệnh con: `login`, `start`, `status`
- [x] T003 [P] Cấu hình `daemon/.golangci.yml`
- [x] T004 [P] Cấu hình `.goreleaser.yml` ở gốc để đóng gói daemon cho linux/darwin/windows
- [x] T005 Tạo thư mục `backend/armarius/infrastructure/daemon/` với `__init__.py`
- [x] T006 [P] Viết `daemon/Makefile` với một mục tiêu `check` chạy `go vet` + `golangci-lint run` + `go test ./...` — đây là cách kiểm của đợt này, **không có CI**

---

## Phase 2: Foundational

**Purpose**: schema, migration, bốn quyết định đã chốt, và ranh giới kiến trúc.

**Chặn**: T007–T012 và T014–T026 chặn **mọi** user story. T013 chặn **riêng US4**.

### Bốn quyết định đã chốt 2026-08-22 — giờ là việc hiện thực, không còn là câu hỏi

Chi tiết và lý do ở [research.md §10](research.md).

- [x] T007 [P] Bỏ ký ức dài hạn khỏi khái niệm nền: **không** dựng kho chung. Xử lý theo từng CLI trong `daemon/internal/execenv/home.go` — liên kết ra kho sống lâu hơn thư mục làm việc, đúng cách Multica làm cho Hermes (FR-007e)
- [ ] T008 Thêm trạng thái **"đang chờ máy rảnh"** vào `backend/armarius/domain/services/push_reason_rules.py` — dùng **động cơ số 5**, **không đồng hồ, không tính giờ** (FR-008a, FR-008e, FR-008c)
- [x] T009 [P] Viết `daemon/internal/execenv/gc.go` — quét định kỳ, tự hỏi trạng thái đầu việc, xoá khi đầu việc **xong hoặc huỷ** và đã im **24 giờ**; thư mục đang có lượt chạy thì không đụng (FR-021)
- [ ] T009a Thêm nhánh thu hồi thư mục **không ai nhận** vào `daemon/internal/execenv/gc.go` — thư mục mà server không kể tên trong lượt hỏi thì xoá sau **72 giờ** kể từ lần sửa gần nhất, tách hẳn khỏi hạn 24 giờ của FR-021 (FR-021a). *Thêm 2026-08-24: T009 chỉ xoá khi **biết** đầu việc đã khép lại, nên thư mục orphan nằm lại vĩnh viễn — lỗ này lộ ra lúc chạy thử T009 trên đĩa thật. Con số 72 giờ lấy theo nhánh sẵn có của Multica (research §10.3), người chủ đổi được.*
- [x] T010 [P] Viết `daemon/internal/supervisor/watchdog.go` — ngưỡng im lặng nền **10 phút** đếm từ sự kiện gần nhất, **không** giới hạn tổng thời gian chạy (FR-031)
- [x] T011 [P] Trong `daemon/internal/supervisor/watchdog.go`: cho phép từng CLI đặt ngưỡng riêng nhưng **chỉ siết chặt hơn, không nới rộng** ngưỡng nền (FR-031a)
- [x] T012 [P] Đặt hạn giữ phiên **14 ngày** trong `daemon/internal/execenv/gc.go` (FR-027)

### Nghiên cứu Gemini CLI — chặn riêng US4

- [ ] T013 Cài `gemini`, chạy `gemini --experimental-acp`, ghi **bốn câu trả lời** vào `research.md` §9: đọc tệp bối cảnh nào, dò kỹ năng ở thư mục nào, có khai nối lại phiên không, có lộ tham số và kết quả gọi công cụ không. Điền hai ô **chưa xác minh** trong bảng ở [research §11.1](research.md). **Không được viết mã Gemini trước khi task này xong** (FR-039a)

### Schema và migration

- [x] T014 Tạo model ORM sáu bảng mới trong `backend/armarius/infrastructure/daemon/models.py`: `machines`, `workplaces`, `run_claims`, `agent_workplace_bindings`, `daemon_link_codes`, `run_event_blobs`
- [x] T015 Thêm cột `accepted_at` vào `Run` trong `backend/armarius/domain/entities/run.py` — **đúng một cột, trung lập runtime**, không thêm `machine_id` (Hiến pháp Điều III)
- [x] T016 Thêm bốn cột vào model `run_events` trong `backend/armarius/infrastructure/database/models.py`: `truncated`, `original_byte_size`, `omission_reason`, `redacted` (FR-043b, FR-047)
- [x] T017 Thêm `logical_name` và `content_hash` cùng ràng buộc duy nhất `(task_id, logical_name, content_hash)` vào model `artifacts` trong `backend/armarius/infrastructure/database/models.py` (FR-020c)
- [x] T018 Viết migration trong `backend/armarius/infrastructure/alembic/versions/` tạo sáu bảng, thêm các cột trên, và thêm chỉ mục `(run_id, type)` cho `run_events` (FR-052) cùng chỉ mục riêng `(workplace_id) WHERE machine_id IS NULL` cho `run_claims` (FR-054)
- [x] T019 Viết **migration mới** trong `backend/armarius/infrastructure/alembic/versions/` (revision `d8a3b6c41e57`): **xoá dữ liệu** mọi agent có `adapter_type = 'hermes_gateway'` cùng lượt chạy, phiên và yêu cầu gọi dậy treo theo (FR-040a). *Sửa 2026-08-24: câu gốc ghi "trong cùng tệp migration" với T018, nhưng luật một PR không quá 5 task đã tách T018 sang PR #216 và nó đã merge. Alembic chỉ chạy mỗi revision đúng một lần, nên sửa tệp đã merge thì phần xoá dữ liệu vĩnh viễn không chạy trên máy nào đã `upgrade head`. Phải là revision riêng.*
- [x] T020 Gỡ mặc định `"hermes_gateway"` khỏi `backend/armarius/domain/entities/marius.py`, `backend/armarius/presentation/schemas.py` và `backend/armarius/application/use_cases/enrollment.py` (FR-040)
- [x] T021 Xoá `backend/armarius/infrastructure/adapters/hermes_gateway.py` và dòng nối nó trong `backend/armarius/presentation/container.py` (FR-040)
- [x] T022 **Đổi trước khi xoá**: sửa `type = "hermes_gateway"` ở `backend/tests/support/fakes.py:700` sang loại mặc định mới. **13 tệp test dùng chung fake này** — đổi mặc định trước thì T023 mới không làm đỏ hàng loạt
- [x] T023 Xoá `backend/tests/test_hermes_adapter.py`; dọn phần tham chiếu hermes còn lại trong `test_onboarding_api.py`, `test_onboarding_service.py`, `test_invite_service.py`, `test_agent_prompt_footer.py`, `test_mariuses_api.py`. *Sửa 2026-08-24: câu gốc bảo xoá luôn `test_gateway_health_probe.py`, nhưng tệp ấy **không kiểm adapter hermes** — nó kiểm `GatewayHealthLivenessProbe`, thứ vẫn còn trong mã cho tới T043 và vẫn đang chạy thật. Xoá bây giờ là bỏ 132 dòng che một đoạn mã còn sống. Chuyển việc xoá nó xuống T043, chỗ chính probe ấy bị thay.*

### Ranh giới kiến trúc — dựng trước, không dựng sau

- [ ] T024 **Mở rộng tệp guard đang có** `backend/tests/test_constitution_guards.py` — thêm phép quét cấm chuỗi `daemon`, `machine`, `runtime`, `workplace` xuất hiện trong `application/use_cases/` và `domain/`, và cấm route tự nhận việc quay lại. Đặt cạnh `test_the_business_layers_never_branch_on_which_runtime_it_is` **đang có ở dòng 99**, không tạo tệp thứ hai làm việc gần giống (FR-035, FR-037, FR-038, FR-060, SC-008)
- [ ] T025 Trỏ test phần nhận việc vào **Postgres của `docker-compose.yml`** (`postgres:16-alpine` đã có sẵn) bằng một fixture riêng trong `backend/tests/conftest.py` đọc `TEST_DATABASE_URL`; `psycopg[binary]` đã nằm trong `backend/pyproject.toml` nhóm `postgres` nên **không thêm dependency**. SQLite không có `SKIP LOCKED` nên test nhận việc chạy trên nó là vô nghĩa
- [x] T026 [P] Thêm `daemon/internal/config/config.go` đọc năm con số đặt được: nhịp poll, nhịp heartbeat, hạn giữ sau khi nhận việc, ngưỡng cắt nhật ký, trần đồng thời. Hạn giữ PHẢI lớn hơn mốc 15 giây ở SC-002 (FR-056c) — chốt **120 giây** theo [research §3](research.md)

**Checkpoint**: schema xong, đường cũ đã gỡ sạch. Mọi user story bắt đầu được.

---

## Phase 3: User Story 1 — Cắm máy vào workspace rồi giao được việc thật (P1) 🎯 MVP

**Goal**: cài daemon, nối vào workspace, dò được agent CLI, buộc agent vào chỗ làm, giao một đầu việc và
thấy nó chạy thật.

**Independent Test**: cài daemon lên máy có sẵn một agent CLI, tạo agent và **chọn chỗ làm cho nó**, tạo
đầu việc, giao cho nó. Đầu việc chuyển sang *đang làm*, diễn biến hiện lên màn hình, xong thì rời *đang làm*.

### Nối máy vào workspace

- [ ] T027 [P] [US1] Viết `backend/armarius/infrastructure/daemon/enrollment.py` — sinh mã, duyệt, cấp token, tất cả dùng một lần và hết hạn sau 10 phút (FR-001)
- [ ] T028 [US1] Thêm `POST /daemon/link/start` và `POST /daemon/link/poll` vào `backend/armarius/presentation/api/daemon.py` (FR-001)
- [ ] T029 [US1] Thêm `POST /daemon/token/renew` vào `backend/armarius/presentation/api/daemon.py` — **server quyết** đã tới lúc gia hạn chưa (FR-014a, FR-014d)
- [ ] T030 [P] [US1] Viết `daemon/internal/client/enroll.go` — lệnh `login`, in mã, hỏi lại theo nhịp, lưu token vào `~/.armarius/daemon.json` với quyền `0600` (FR-001)
- [ ] T031 [P] [US1] Viết màn hình duyệt mã `frontend/src/pages/LinkMachine.tsx` và thêm route `/link` (FR-001)
- [ ] T032 [P] [US1] Thêm chuỗi tiếng Việt đủ dấu cho màn hình duyệt vào `frontend/src/i18n/vi.ts` (Điều VI)

### Dò agent CLI và đăng ký chỗ làm

- [ ] T033 [P] [US1] Viết `daemon/internal/discovery/discover.go` — dò `gemini`, `claude`, `codex` trên `PATH`, lấy phiên bản (FR-002)
- [ ] T034 [US1] Viết `daemon/internal/discovery/capabilities.go` — **hỏi khả năng thật** từng CLI, KHÔNG suy từ tên loại (FR-017)
- [ ] T035 [P] [US1] Viết `daemon/internal/execenv/linkprobe.go` — thử tạo symbolic link lúc khởi động, rơi về junction trên Windows, và **báo chỗ làm không sẵn sàng** nếu thứ bắt buộc không liên kết được ([research §5](research.md))
- [ ] T036 [US1] Thêm `PUT /daemon/workplaces` và `POST /daemon/heartbeat` vào `backend/armarius/presentation/api/daemon.py`; chỗ làm mang **tên máy đọc được** qua `machines.display_name` (FR-002, FR-003, FR-004)
- [ ] T037 [US1] Viết `backend/armarius/infrastructure/daemon/workplaces.py` — đồng bộ chỗ làm; CLI mất thì chuyển `not_ready(cli_removed)`, **không xoá** vì agent đang buộc vào đó (FR-033)
- [ ] T038 [P] [US1] Viết `daemon/internal/supervisor/heartbeat.go` — phát nhịp 15 giây kèm số chỗ trống hiện tại (FR-004, FR-055c)
- [ ] T038a [US1] Dựng ruột cho lệnh `status`: viết `daemon/internal/client/status.go`, nối vào `daemon/cmd/armarius-daemon/main.go`, và cho `start` ghi ra một tệp trạng thái nhỏ khi lên để `status` biết daemon còn sống không. In ra: workspace đã nối, các agent CLI dò được (dùng lại T033) kèm chỗ làm nào sẵn sàng, và tiến trình daemon còn chạy hay không; kèm cờ `-json` (FR-005a). *Thêm 2026-08-24: T002 khai ba lệnh con nhưng chỉ `login` (T030) và `start` (T038, T052, T054) có task dựng ruột — `status` thì không, và cũng không FR nào đòi nó. Lỗ này có từ bản `tasks.md` gốc (commit `7a590f2`), do chính cơ chế "lệnh chưa dựng thì báo lỗi kèm số task còn nợ" của PR #218 phơi ra. Người chủ chốt giữ lệnh này 2026-08-24, kèm FR-005a làm chỗ dựa.*

### Buộc agent vào chỗ làm — lỗ nghiệp vụ, không có nó thì cả chuỗi đứt

- [ ] T039 [US1] Sửa use case tạo/mời agent trong `backend/armarius/application/use_cases/enrollment.py` — **bắt buộc có chỗ làm**, ghi một hàng vào `agent_workplace_bindings`, và từ chối tạo agent không chỗ làm. Mối buộc **không đổi được** sau khi tạo (FR-007, FR-007f)
- [ ] T040 [US1] Thêm trường chỗ làm vào schema tạo agent trong `backend/armarius/presentation/schemas.py` và route tương ứng; thêm `GET /workplaces` liệt kê chỗ làm sẵn sàng **trong workspace của người gọi** (FR-007f, Điều I)
- [ ] T041 [P] [US1] Thêm ô chọn chỗ làm vào màn hình tạo/mời agent trong `frontend/src/pages/` và chuỗi tiếng Việt vào `frontend/src/i18n/vi.ts` — danh sách chỉ hiện chỗ làm sẵn sàng, không cho tạo khi bỏ trống (FR-007f, Điều VI)

### Sống chết — sau port đã có, không đụng tầng nghiệp vụ

- [ ] T042 [US1] Thêm `DaemonLivenessProbe` vào `backend/armarius/infrastructure/adapters/liveness_probe.py` — trả lời từ `machines` + `workplaces` + `agent_workplace_bindings`; agent chưa buộc chỗ làm nào thì **offline**; **không ping agent**, và **cú poll của daemon không được tính là dấu hiệu sống** (FR-006, FR-006a, FR-006d, FR-007f, FR-055b)
- [ ] T043 [US1] Thay `GatewayHealthLivenessProbe` bằng `DaemonLivenessProbe` trong `backend/armarius/infrastructure/adapters/liveness_probe.py`, sửa dòng nối ở `backend/armarius/presentation/container.py`, và **xoá `backend/tests/test_gateway_health_probe.py`** (chuyển từ T023 xuống — tệp ấy kiểm probe cũ, phải sống tới đúng lúc probe cũ chết). **Lưu ý**: `PlaceholderLivenessProbe` đã bị thay từ đợt trước; trong mã hiện chỉ còn `GatewayHealthLivenessProbe` (FR-040)
- [ ] T044 [P] [US1] Hiện **lý do agent offline ở mức người đọc hiểu** (máy tắt / CLI bị gỡ / cạn hạn mức / chưa buộc chỗ làm) trên màn hình agent trong `frontend/src/pages/`, kèm chuỗi tiếng Việt ở `frontend/src/i18n/vi.ts` (FR-006c, FR-007c)

### Nhận việc — cửa duy nhất

- [ ] T045 [US1] Viết `backend/armarius/infrastructure/daemon/claim.py` — `atomic compare-and-swap` một câu theo [research §4](research.md); ghi `run_claims.claimed_at` và `runs.accepted_at` **trong cùng một giao dịch**. Tính đúng-một-lần nằm ở đây, **không** dựa vào daemon tự xếp hàng (FR-053, FR-054, FR-054a, FR-054b)
- [ ] T046 [US1] Thêm `POST /daemon/runs/claim` vào `backend/armarius/presentation/api/daemon.py` — server lấy **số nhỏ hơn** giữa trần và số chỗ trống daemon báo (FR-008, FR-008d, FR-055c)
- [ ] T047 [US1] Thêm `POST /daemon/runs/{run_id}/start` — trả **404** nếu lượt chạy không còn thuộc máy này; đầu việc đã có máy nhận thì buộc vào đúng máy ấy (FR-007d, FR-058, FR-059)
- [ ] T048 [US1] Viết `DaemonAdapter` trong `backend/armarius/infrastructure/adapters/daemon_adapter.py` — `dispatch()` **chỉ đánh dấu run có thể nhận rồi trả về ngay**, không gọi ra máy (FR-009)
- [ ] T049 [US1] Sửa `infer_drive` trong `backend/armarius/domain/services/push_reason_rules.py` — động cơ số 1 bật từ `accepted_at`, **không đợi** `run_last_output_at` (FR-056)
- [ ] T050 [US1] Thêm đồng hồ cho động cơ số 1 và đường thu hồi khi quá hạn trong `backend/armarius/infrastructure/daemon/claim.py` (FR-056a, FR-056c)
- [ ] T051 [US1] Trong `backend/armarius/domain/services/push_reason_rules.py`: đặt lại đồng hồ động cơ số 2 tại mốc nhận việc (FR-056b) và tách *chưa máy nào nhận* khỏi *máy nhận rồi chết giữa lúc chuẩn bị* (FR-057)
- [ ] T052 [P] [US1] Viết `daemon/internal/supervisor/claimloop.go` — vòng lặp xin việc theo nhịp poll, tôn trọng trần đồng thời; poll là fallback, nhịp đặt được và được phép thưa (FR-055, FR-055d)
- [ ] T053 [US1] Thêm `GET /daemon/events` (SSE) vào `backend/armarius/presentation/api/daemon.py` — tin đẩy **chỉ là tín hiệu**, không mang việc, không phải lệnh chạy (FR-055a)
- [ ] T054 [P] [US1] Viết `daemon/internal/client/events.go` — giữ kết nối SSE, nhận tin thì đi xin việc ngay (FR-055)
- [ ] T055 [P] [US1] Hiện trạng thái **"đang chờ máy rảnh"** trên màn hình đầu việc trong `frontend/src/pages/`, phân biệt rõ với *chưa ai nhận* và với *agent chết*; chuỗi tiếng Việt ở `frontend/src/i18n/vi.ts`, phía server lưu **mã + tham số** không lưu câu (FR-008b, Điều VI, Điều VII)

### Dựng gói việc — thông điệp, kỹ năng, bộ công cụ

**Đây là khoảng trống lớn nhất `/speckit-analyze` tìm ra**: đã có chỗ bật CLI nhưng chưa có chỗ nào quyết
định đưa gì cho nó. Kỹ năng theo [research §11](research.md) — **nguyên flow Multica**.

- [ ] T056 [US1] Dựng thông điệp gửi agent ở **phía server**, trong `backend/armarius/application/use_cases/wake_engine.py` — Bối cảnh dự án, mô tả đầu việc, mã lý do gọi dậy kèm tham số, hành động kế tiếp đã lưu. Bằng **tiếng Anh**; chữ do người nhập giữ nguyên tiếng người viết. Nội dung **tự viết**, không chép câu chữ Multica. Trả xuống trong gói nhận việc (FR-011, FR-011a, FR-012, FR-039b, Điều V, Điều VII)
- [ ] T057 [US1] Ghi **toàn văn thông điệp** vào `run_events` ngay tại lời gọi nhận việc, trong `backend/armarius/infrastructure/daemon/claim.py` — server ghi, **không phải** daemon gửi ngược về (FR-012a, FR-042, FR-049)
- [ ] T058 [US1] Đưa **kỹ năng của agent** xuống trong gói nhận việc tại `backend/armarius/infrastructure/daemon/claim.py` — bản đồ *đường dẫn tương đối → nội dung*, lấy qua `container.skills.resolve`; từ chối gói có đường dẫn thoát ra ngoài thư mục kỹ năng (FR-011b)
- [ ] T059 [US1] Viết `daemon/internal/execenv/context_file.go` — ghi thông điệp vào **đúng tệp bối cảnh native** của từng CLI (`CLAUDE.md`, `AGENTS.md`, …) theo bảng ở [research §11.1](research.md). Daemon **không dựng nội dung**, chỉ đặt vào đúng chỗ (FR-011a, FR-039)
- [ ] T060 [US1] Viết `daemon/internal/execenv/skills.go` — ghi kỹ năng vào **thư mục kỹ năng native của từng CLI** dưới dạng **tệp thật, ghi mới mỗi lượt chạy**. CẤM liên kết ra kho dùng chung, CẤM ghi vào cấu hình CLI trên máy (FR-011b, FR-007b)
- [ ] T061 [US1] Viết `daemon/internal/execenv/tools.go` — bơm **bộ công cụ gọi ngược theo từng lượt chạy** qua cơ chế nạp công cụ sẵn có của từng CLI, mang **token của lượt chạy**. Cùng luật với kỹ năng: không ghi vào cấu hình dùng chung (FR-013, FR-013a)
- [ ] T062 [US1] Gỡ `GET /agent/skills` và `GET /agent/skills/{slug}` khỏi `backend/armarius/presentation/api/agent.py` cùng hàm `effective_skills`, và **đóng lại** vòng xác nhận đã-cài-xong còn dở dang từ đợt trước — daemon ghi tệp trực tiếp thì không còn gì để xác nhận (FR-011c)

### Chạy agent thật

- [ ] T063 [US1] Viết `daemon/internal/execenv/workdir.go` — dựng thư mục làm việc **theo đầu việc**, trắng, dùng chung cho mọi lượt của đầu việc ấy; hai đầu việc khác nhau thì hai thư mục tách biệt (FR-010, FR-010b, FR-041)
- [ ] T064 [US1] Viết `daemon/internal/execenv/token.go` — nhét token của lượt chạy vào agent qua biến môi trường; **cấm rơi về token của daemon** kể cả khi đúc hỏng (FR-014, FR-014c)
- [ ] T065 [US1] Viết `daemon/internal/runtime/oneshot.go` — họ chạy-một-phát cho Claude Code và Codex (FR-039)
- [ ] T066 [P] [US1] Viết `daemon/internal/runtime/acp.go` — họ ACP nói JSON-RPC qua luồng chuẩn (FR-039)
- [ ] T067 [US1] Viết `daemon/internal/supervisor/run.go` — bật CLI, theo dõi tiến trình con, dọn cây tiến trình khi kết thúc; truyền diễn biến về **trong lúc đang chạy** (FR-015)
- [ ] T068 [US1] Thêm `POST /daemon/runs/{run_id}/finish` — thu hồi token lượt chạy, và bảo đảm đầu việc **có động cơ đẩy sống ngay**, không đợi vòng quét (FR-014b, FR-030, FR-030a)
- [ ] T069 [P] [US1] Viết màn hình `frontend/src/pages/Machines.tsx` — danh sách máy, chỗ làm, trạng thái sẵn sàng kèm lý do, và **agent nào đang buộc vào chỗ làm nào** (FR-003, FR-007a, FR-033)
- [ ] T070 [P] [US1] Thêm chuỗi tiếng Việt cho màn hình máy vào `frontend/src/i18n/vi.ts` (Điều VI)

### Test cho US1

- [ ] T071 [P] [US1] `backend/tests/test_daemon_enrollment.py` — device flow, mã hết hạn, mã dùng một lần (FR-001)
- [ ] T072 [US1] `backend/tests/test_run_claim_atomic.py` — **chạy trên Postgres thật**; hai cú xin đồng thời chỉ một cú nhận được việc, và 5 lượt chạy đồng thời trên một máy không lượt nào bị nhận hai lần (FR-054, FR-054b, SC-009)
- [ ] T073 [P] [US1] `backend/tests/test_daemon_claim_batch.py` — lấy nhiều đầu việc cùng lúc vẫn atomic (FR-055e)
- [ ] T074 [P] [US1] `backend/tests/test_claim_expiry_returns_run.py` — quá hạn giữ thì đầu việc quay về trạng thái chưa ai nhận (FR-056a)
- [ ] T075 [P] [US1] `backend/tests/test_daemon_tenant_isolation.py` — mọi route `/daemon/*` chạm workspace khác trả **404** (Điều I, FR-036)
- [ ] T076 [P] [US1] `backend/tests/test_poll_is_not_a_liveness_signal.py` — máy bật mà CLI bị gỡ thì agent vẫn phải offline (FR-055b, FR-006a)
- [ ] T077 [P] [US1] `backend/tests/test_agent_must_bind_to_a_workplace.py` — tạo agent không chỗ làm bị từ chối; mối buộc không đổi được sau khi tạo; agent chưa buộc thì offline (FR-007, FR-007f)
- [ ] T078 [P] [US1] `backend/tests/test_wake_message_is_recorded_at_claim.py` — toàn văn thông điệp có mặt trong `run_events` ngay sau cú nhận việc, không đợi daemon báo về (FR-012a, FR-042)
- [ ] T079 [P] [US1] `backend/tests/test_claim_carries_skills.py` — gói nhận việc mang đủ kỹ năng của agent ấy và **chỉ** của agent ấy; đường dẫn thoát ra ngoài bị từ chối (FR-011b, FR-007b)
- [ ] T080 [P] [US1] `daemon/internal/execenv/skills_test.go` — kỹ năng ghi ra **tệp thật** chứ không phải liên kết, và **ghi mới** ở lượt chạy thứ hai (FR-011b)
- [ ] T081 [P] [US1] `daemon/internal/discovery/capabilities_test.go` — khả năng lấy từ hỏi thật, không từ tên loại (FR-017)
- [ ] T082 [P] [US1] `daemon/internal/execenv/linkprobe_test.go` — không tạo được liên kết bắt buộc thì báo không sẵn sàng, **không âm thầm chép** ([research §5](research.md))

**Checkpoint**: US1 xong là đã có MVP chạy được thật.

---

## Phase 4: User Story 2 — Kết quả buộc phải rời khỏi máy (P2)

**Goal**: hiện vật lên kho dùng chung được, công bố lặp không đẻ bản trùng, chưa có hiện vật thì không rời
*đang làm*.

**Independent Test**: cho agent tạo tệp rồi công bố; tải về từ giao diện, so nội dung. Rồi cho agent không
công bố gì mà cố đổi trạng thái — phải bị chặn kèm mã lý do.

- [ ] T083 [US2] Thêm khoá chống lặp vào `backend/armarius/application/use_cases/artifacts.py` — cùng tên cùng hash thì trả hiện vật cũ, cùng tên khác hash thì ra bản mới ([research §6](research.md)) (FR-020c)
- [ ] T084 [US2] Sửa `POST /agent/artifacts` trong `backend/armarius/presentation/api/agent.py` — trả `200 created=false` cho ca thử lại, `201` cho ca mới (FR-020c)
- [ ] T085 [US2] Trong `backend/armarius/application/use_cases/artifacts.py`: cho phép **thử lại không giới hạn**, kể cả ở lượt chạy sau, vì thư mục làm việc sống theo đầu việc (FR-020b)
- [ ] T086 [US2] Trong `backend/armarius/application/use_cases/push_reason.py`: bảo đảm đầu việc **giữ động cơ đẩy sống** trong lúc một cú công bố còn dở (FR-020d)
- [ ] T087 [US2] Thêm đường **kiểm hiện vật thật sự tải về được** vào `backend/armarius/application/use_cases/artifacts.py` — đọc lại từ kho và so `content_hash` sau khi ghi; hỏng thì hiện vật **không được tính là đã công bố** (FR-020)
- [ ] T088 [P] [US2] Thêm `GET /agent/workdir/changes` — daemon liệt kê thứ đã đổi trong thư mục làm việc; **thông tin, không tự công bố hộ** (FR-020a, FR-018)
- [ ] T089 [P] [US2] Viết `daemon/internal/execenv/changes.go` — theo dõi thay đổi trong thư mục làm việc (FR-020a)
- [ ] T090 [US2] Thêm luật *chưa có hiện vật thì chưa rời đang làm* vào tờ hướng dẫn gửi agent trong `backend/static/skills/` — dặn **không thay cho chặn** (FR-019)
- [ ] T091 [US2] Nối phần thu hồi thư mục ở T009 vào luồng chạy thật trong `daemon/internal/supervisor/run.go`; **không bao giờ** chạm thư mục mà một lượt chạy đang giữ (FR-022)
- [ ] T092 [P] [US2] `backend/tests/test_artifact_publish_idempotent.py` — công bố lại y hệt ra **đúng một** hiện vật (SC-004a)
- [ ] T093 [P] [US2] `backend/tests/test_done_gate_still_holds_under_daemon.py` — chưa có hiện vật thì bị chặn, đầu việc vẫn giữ động cơ đẩy; và hiện vật đã ghi nhận **tải về được thật** (Điều II, SC-004, FR-020)

---

## Phase 5: User Story 5 — Ngồi một chỗ thấy hết agent đang làm gì (P2)

**Goal**: đọc lại được toàn văn thông điệp gửi đi, toàn văn tham số gọi công cụ, bản rút gọn kết quả, chữ
agent sinh ra, lỗi — trong lúc đang chạy và sau khi xong.

**Independent Test**: chạy một lượt gọi ít nhất hai công cụ; đọc lại đúng thứ tự, đúng tham số, đúng bản
rút gọn; và trong lúc chạy thì các dòng hiện dần không phải tải lại.

- [ ] T094 [US5] Viết `daemon/internal/redact/redact.go` — **che bí mật ở phía daemon** trước khi rời máy, phủ mọi kênh: thông điệp, tham số, kết quả, chữ agent, biến môi trường (FR-048, FR-048a)
- [ ] T095 [US5] Viết `daemon/internal/runtime/events.go` — cắt kết quả công cụ còn bản rút gọn theo ngưỡng, ghi rõ **đã cắt bao nhiêu bytes**; ghi chữ agent sinh ra, phần suy luận nếu CLI có lộ, và mọi lỗi (FR-043, FR-043a, FR-043b, FR-044)
- [ ] T096 [US5] Trong `daemon/internal/runtime/events.go`: phân biệt hai lý do vắng dữ liệu — `truncated_by_policy` và `not_exposed_by_cli` (FR-047)
- [ ] T097 [US5] Thêm `POST /daemon/runs/{run_id}/events` vào `backend/armarius/presentation/api/daemon.py` — nhận theo lô, `seq` tăng đơn điệu không trùng (FR-045)
- [ ] T098 [US5] Từ chối ở server mọi sự kiện `tool.finished` mang toàn văn kết quả — **kiểm ở tầng nhận**, không tin daemon đã cắt đúng (FR-043a)
- [ ] T099 [US5] Viết `backend/armarius/infrastructure/daemon/event_blobs.py` — tách toàn văn sang kho riêng khi vượt ngưỡng, **chỉ cho loại được phép**: thông điệp gửi agent và tham số gọi công cụ (FR-049)
- [ ] T100 [US5] Mở rộng `backend/armarius/presentation/api/trace.py` — đọc nhật ký đầy đủ, lọc theo loại sự kiện (FR-052), giới hạn theo workspace (FR-051); đủ để trả lời *"agent đã làm gì và vì sao kết luận như vậy"* chỉ bằng nhật ký (FR-016, SC-013)
- [ ] T101 [US5] Thêm hạn giữ nhật ký 30 ngày, tách khỏi hạn giữ thư mục làm việc, trong `backend/armarius/application/use_cases/task_log.py` (FR-050)
- [ ] T102 [P] [US5] Viết màn hình `frontend/src/pages/RunTrace.tsx` — dòng sự kiện, bộ lọc theo loại, mở toàn văn theo yêu cầu, ảo hoá danh sách để 1000 sự kiện không treo (FR-052, SC-011, SC-014)
- [ ] T103 [P] [US5] Nối `frontend/src/pages/RunTrace.tsx` vào kênh sự kiện sẵn có qua `frontend/src/hooks/` để sự kiện hiện dần trong 3 giây (FR-046, SC-003, SC-012)
- [ ] T104 [P] [US5] Thêm chuỗi tiếng Việt cho màn hình nhật ký vào `frontend/src/i18n/vi.ts` (Điều VI)
- [ ] T105 [P] [US5] `backend/tests/test_tool_result_never_leaves_machine.py` — không hàng nào trong `run_event_blobs` gắn với `tool.finished` (FR-043a)
- [ ] T106 [P] [US5] `backend/tests/test_secret_redaction.py` — gài token vào tham số, khẳng định **không** tới server ở dạng nguyên bản (SC-015)
- [ ] T107 [P] [US5] `backend/tests/test_run_event_ordering.py` — thứ tự xác định, không trùng `seq` (FR-045)
- [ ] T108 [P] [US5] Lái màn hình nhật ký bằng **Playwright** — công cụ có sẵn trên máy ở `~/.local/bin/playwright`. Dựng lại container frontend rồi lái thật: bộ lọc theo loại, mở toàn văn, cuộn 1000 sự kiện. **Không** thêm Playwright vào `frontend/package.json` và **không** nộp bộ test vào repo — cùng cách đã làm ở feature 001 T051/T077. Không dừng ở build xanh (SC-011, SC-014)

---

## Phase 6: User Story 3 — Gọi dậy lần sau nối đúng mạch cũ (P3)

**Goal**: mọi lượt gọi dậy trong cùng một đầu việc nối lại cùng một phiên; không nối được thì báo thẳng
bằng tiếng Anh.

**Independent Test**: gọi dậy hai lần trên cùng đầu việc, lần hai hỏi câu chỉ trả lời được nếu nhớ lần một.
Rồi ép mất phiên và lặp lại — agent phải nhận câu báo bắt đầu lại.

- [ ] T109 [US3] Viết `daemon/internal/execenv/session.go` — giữ trạng thái phiên **theo đầu việc**, trùng ranh giới thư mục làm việc (FR-023, FR-010a)
- [ ] T110 [US3] Trong `daemon/internal/execenv/session.go` và `daemon/internal/execenv/workdir.go`: hai đầu việc khác nhau có hai phiên và hai thư mục tách biệt, kể cả cùng một agent (FR-024, FR-010b)
- [ ] T111 [US3] Nối phần thu hồi phiên ở T012 vào `daemon/internal/execenv/session.go` — quá hạn thì mở phiên mới kèm câu báo theo FR-025 (FR-027)
- [ ] T112 [US3] Sinh **câu báo bắt đầu lại bằng tiếng Anh** kèm lý do khi không nối lại được phiên, trong `daemon/internal/runtime/continuity.go` (FR-025, Điều VII)
- [ ] T113 [US3] Trong `daemon/internal/runtime/continuity.go`: xử ca chỗ làm giữ phiên cũ đã bị dựng lại — mở phiên mới, có báo, **không giả vờ nối tiếp** (FR-026)
- [ ] T114 [P] [US3] `backend/tests/test_session_boundary_is_task.py` — cùng đầu việc nối lại, khác đầu việc thì tách (SC-006)
- [ ] T115 [P] [US3] `daemon/internal/runtime/continuity_test.go` — mất phiên thì **100%** số lần có câu báo, không lần nào im lặng (SC-007)

---

## Phase 7: User Story 4 — Thêm loại agent CLI mới mà không đụng tầng nghiệp vụ (P4)

**Goal**: thêm một CLI chỉ đụng tầng dưới cùng. **Chặn bởi T013.**

**Independent Test**: chạy cùng một đầu việc trên hai loại CLI khác nhau; hình dạng diễn biến, cách nộp hiện
vật, cách báo lỗi và cách tính sống chết giống hệt nhau ở tầng trên.

- [ ] T116 [US4] Viết `daemon/internal/runtime/registry.go` — bảng đặc tính từng CLI: tệp bối cảnh, thư mục kỹ năng, biến môi trường, lệnh nối lại phiên. Nguồn là bảng 17 CLI ở [research-multica-daemon.md §3](research-multica-daemon.md) (FR-039)
- [ ] T117 [US4] Thêm Gemini CLI vào `daemon/internal/runtime/registry.go` theo **kết quả T013**, không theo phỏng đoán (FR-039)
- [ ] T118 [US4] Trong `daemon/internal/runtime/registry.go`: hạ cấp có báo khi một CLI không khai một khả năng nào đó — theo FR-039a điều đó **vẫn tính là hỗ trợ**, không phải hỏng (FR-017, FR-039a)
- [ ] T119 [US4] Khai ngưỡng im lặng riêng cho từng CLI trong `daemon/internal/runtime/registry.go`, tôn trọng luật chỉ-siết-không-nới ở T011 (FR-031a)
- [ ] T120 [P] [US4] `daemon/internal/runtime/registry_test.go` — hai họ giao thức đi qua cùng một hợp đồng (FR-035)
- [ ] T121 [P] [US4] `backend/tests/test_same_task_two_clis.py` — cùng một đầu việc trên hai loại CLI đi qua **đúng một đường mã** ở tầng nghiệp vụ (FR-037, SC-008)

---

## Phase 8: Polish & việc xuyên suốt

- [ ] T122 [P] Viết `daemon/internal/supervisor/shutdown.go` — tắt có trật tự thì gọi `PUT /daemon/workplaces` với danh sách rỗng để gỡ đăng ký ngay, không để hệ thống đợi hết ngưỡng heartbeat (FR-005)
- [ ] T123 [P] Nâng cấp daemon **không cắt ngang** lượt chạy đang diễn ra, trong `daemon/internal/supervisor/upgrade.go` (FR-034)
- [ ] T124 [P] Trong `backend/armarius/application/use_cases/recovery.py`: phân biệt **lỗi tạm** với **lỗi cần người xử**; token lượt chạy bị thu hồi, token daemon bị thu hồi giữa lượt chạy, và cạn hạn mức đều xếp vào loại sau, không tiêu ngân sách tự phục hồi (FR-014e, FR-014f, FR-032, FR-007c)
- [ ] T125 [P] Cập nhật `backend/static/skills/armarius-mcp/SKILL.md` — gỡ các lệnh đã bị xoá (`enroll`, `enrollment_code`, `claim_task`) còn sót từ đợt trước, và gỡ mọi lệnh dạy agent tự cài kỹ năng (FR-011c)
- [ ] T126 [P] `backend/tests/test_daemon_death_reuses_the_offline_flow.py` — giết daemon giữa lượt chạy: agent chuyển offline qua `DaemonLivenessProbe`, rồi **luồng offline đang có** tiếp quản đúng như trước, kể cả khoảng ân hạn. Đây là phép chứng minh cho FR-006b, FR-028, FR-029, FR-029a — thứ được cố ý **không viết mã mới** (SC-005, SC-010)
- [ ] T127 [P] Viết `daemon/README.md` — hướng dẫn cài ba nền tảng, câu về Developer Mode trên Windows để bật symbolic link, và câu ghi nhận sản phẩm xây trên Multica kèm link repo gốc (FR-039b)
- [ ] T128 Chạy `cd mcp && uv run pytest` trên bộ test riêng ở `mcp/tests/` — bắt buộc vì đợt này đổi schema backend
- [ ] T129 Chạy **trọn bộ tám mục** của [quickstart.md](quickstart.md) trên dịch vụ thật, ghi lại số đo cho **cả 16 tiêu chí** SC-001…SC-015 — không chỉ bốn cái. Mục §5 phủ SC-011/SC-013/SC-014/SC-015, mục §6 phủ SC-005/SC-010, mục §7 phủ SC-009, mục §9 phủ phần kỹ năng

---

## Dependencies

```
Phase 1 Setup
   ↓
Phase 2 Foundational  ← T007–T012 quyết định đã chốt; T014–T026 schema và ranh giới
   ↓                     (T013 KHÔNG chặn ở đây — nó chỉ chặn US4)
Phase 3 US1 (P1) ─── MVP ───┐
   ↓                        │
Phase 4 US2 (P2)  ←─────────┤  US2, US5 độc lập nhau, chạy song song được
Phase 5 US5 (P2)  ←─────────┘
   ↓
Phase 6 US3 (P3)
   ↓
Phase 7 US4 (P4)  ← chặn bởi T013 (nghiên cứu Gemini)
   ↓
Phase 8 Polish
```

**Chặn cứng**:

- T013 chặn T117, T118, T119 — **không viết mã Gemini trước khi chạy thử thật**
- T022 chặn T023 — đổi fake mặc định **trước**, xoá test **sau**; ngược lại là 13 tệp test đỏ cùng lúc
- T009 chặn T091 · T011 chặn T119 · T012 chặn T111 — phần dọn và phần watchdog phải có trước khi nối vào luồng chạy
- T045 chặn T046, T047, T048 — có cửa nhận việc rồi mới có route
- T025 chặn T072 — không có Postgres thật thì test nhận việc vô nghĩa
- T039 chặn T042 — chưa ghi được mối buộc agent↔chỗ làm thì `DaemonLivenessProbe` không có gì để đọc
- T030 và T033 chặn T038a — `status` đọc tệp cấu hình mà `login` ghi ra, và dùng lại phần dò CLI
- T056 chặn T057 và T059 · T058 chặn T060 và T079 — dựng thông điệp và gói kỹ năng trước, ghi lại và đặt vào chỗ sau
- T062 chặn T125 — gỡ route rồi mới sửa tờ hướng dẫn cho khớp

## Cơ hội chạy song song

| Nhóm | Task |
| --- | --- |
| Setup | T002, T003, T004, T006 |
| Phần Go và phần Python của US1 | T030/T033/T035/T038/T052/T054 song song với T027/T028/T036/T045 |
| Ba nhánh của gói việc | T059 thông điệp · T060 kỹ năng · T061 bộ công cụ — khác tệp, chạy được ngay sau T056/T058 |
| Toàn bộ test của US1 | T071, T073, T074, T075, T076, T077, T078, T079, T080, T081, T082 |
| US2 và US5 | hai phase chạy song song sau khi US1 xong |
| Giao diện | T031, T041, T044, T055, T069, T102 song song với phần backend tương ứng |

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** Xong ba phase này là daemon chạy thật: cắm máy, dò CLI, buộc
agent vào chỗ làm, nhận việc, dựng gói việc, chạy agent, thấy diễn biến. Đủ để dùng và đủ để biết thiết kế
có đứng được không.

**Đợt hai**: US2 và US5 song song — một cái đóng cổng Hiến pháp Điều II, một cái cho khả năng nhìn thấy.
Cả hai đều P2 và không đụng nhau.

**Đợt ba**: US3 rồi US4.

**Không gộp Phase 2 vào các phase sau.** T007–T012 là nền mà nhiều task sau nối vào; làm sau là phải quay
lại sửa chỗ đã viết.

**Không tách khối T056–T062 ra khỏi US1.** Không có nó thì daemon bật được tiến trình CLI nhưng không biết
đưa gì cho nó — đây là lỗ `/speckit-analyze` ngày 2026-08-23 tìm ra sau khi đã qua ba vòng rà.
