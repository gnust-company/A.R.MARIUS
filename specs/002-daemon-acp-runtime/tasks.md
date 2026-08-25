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
- [x] T008 Thêm trạng thái **"đang chờ máy rảnh"** vào `backend/armarius/domain/services/push_reason_rules.py` — dùng **động cơ số 5**, **không đồng hồ, không tính giờ** (FR-008a, FR-008e, FR-008c). *Ghi 2026-08-24: động cơ số 5 nay có hai dáng, phân biệt bằng mã `blocked_on_task` và `blocked_on_capacity` (Điều VII) — không thì màn hình không tách được hai cái chờ khác hẳn nhau. Xếp ngay dưới động cơ số 1: mọi động cơ có đồng hồ ở dưới đều không mở nổi lượt chạy khi hết chỗ, để chúng cầm đầu việc là báo động về một chuyện bị chặn từ gốc. Danh sách rỗng thì **không** phải động cơ này — không có gì cầm đồng hồ thì đầu việc rơi khỏi lưới vĩnh viễn.*
- [x] T009 [P] Viết `daemon/internal/execenv/gc.go` — quét định kỳ, tự hỏi trạng thái đầu việc, xoá khi đầu việc **xong hoặc huỷ** và đã im **24 giờ**; thư mục đang có lượt chạy thì không đụng (FR-021)
- [x] T009a Xoá thư mục làm việc mà **server không còn biết đầu việc nào ứng với nó**, trong `daemon/internal/execenv/gc.go` (FR-021a). *Bối cảnh: trên đĩa máy người dùng, mỗi đầu việc có một thư mục riêng, tên thư mục chính là id của đầu việc. Cứ 2 giờ daemon gom tên các thư mục đó gửi lên server hỏi "mấy đầu việc này đang thế nào?". T009 xử bốn câu trả lời: đang chạy thì không đụng, còn mở thì giữ, đóng chưa quá 24 giờ thì giữ, đóng quá 24 giờ thì xoá. Còn câu thứ năm — **server không trả lời gì về id đó** — thì T009 giữ mãi mãi. Xảy ra khi người dùng xoá đầu việc, xoá dự án hoặc xoá cả workspace, hoặc lượt chạy chết trước khi server kịp ghi nhận đầu việc. Hệ quả: thư mục nằm lại vĩnh viễn, không có đường tự dọn. T009a thêm nhánh thứ năm: server không biết id đó **và** không có gì được ghi vào thư mục suốt **72 giờ** → xoá. 72 chứ không phải 24 vì đây là suy đoán chứ không phải sự thật server nói ra. Con số lấy theo nhánh sẵn có của Multica (research §10.3), người chủ đổi được.* **Xong 2026-08-25**: hạn 72 giờ đo bằng lần ghi gần nhất **ở bất cứ đâu trong cây thư mục**, không phải mtime của riêng thư mục gốc — mtime thư mục gốc không nhúc nhích khi người ta sửa một file nằm sâu bên trong, nên tin nó là xoá nhầm cây đang có người làm. Cú quét sâu chỉ chạy ngay trước lệnh xoá, không chạy ở đường giữ lại.
- [x] T010 [P] Viết `daemon/internal/supervisor/watchdog.go` — ngưỡng im lặng nền **10 phút** đếm từ sự kiện gần nhất, **không** giới hạn tổng thời gian chạy (FR-031)
- [x] T011 [P] Trong `daemon/internal/supervisor/watchdog.go`: cho phép từng CLI đặt ngưỡng riêng nhưng **chỉ siết chặt hơn, không nới rộng** ngưỡng nền (FR-031a)
- [x] T012 [P] Đặt hạn giữ phiên **14 ngày** trong `daemon/internal/execenv/gc.go` (FR-027)

### Nghiên cứu Gemini CLI — chặn riêng US4

- [ ] T013 Cài `gemini`, chạy `gemini --experimental-acp`, ghi **bốn câu trả lời** vào `research.md` §9: đọc tệp bối cảnh nào, dò kỹ năng ở thư mục nào, có khai nối lại phiên không, có lộ tham số và kết quả gọi công cụ không. Điền hai ô **chưa xác minh** trong bảng ở [research §11.1](research.md). **Không được viết mã Gemini trước khi task này xong** (FR-039a). *Sửa 2026-08-24: máy phát triển không cài được `gemini` (người chủ: tài khoản không đủ quyền), nên T013 tách hai nửa. **Nửa tra cứu — xong**: đọc thẳng mã nguồn `gemini-cli@main`, bốn câu trả lời cùng trích dẫn tệp:dòng nằm ở [research §9.1](research.md), kèm một câu hỏi thứ năm về đăng nhập khi bị chương trình khác khởi chạy. **Nửa chạy thật — chưa**: `daemon/scripts/probe-gemini-acp.mjs`, người chủ chạy ở máy có `gemini` rồi gửi `gemini-acp-probe.log` và `.json` về. Tick T013 khi đối chiếu kết quả chạy thật với §9.1 xong. Đọc mã KHÔNG thay được chạy thật: issue #15502 trên mạng báo `loadSession: false` trong khi mã hiện tại là `true`.*

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

- [x] T024 **Mở rộng tệp guard đang có** `backend/tests/test_constitution_guards.py` — thêm phép quét cấm chuỗi `daemon`, `machine`, `runtime`, `workplace` xuất hiện trong `application/use_cases/` và `domain/`, và cấm route tự nhận việc quay lại. Đặt cạnh `test_the_business_layers_never_branch_on_which_runtime_it_is` **đang có ở dòng 99**, không tạo tệp thứ hai làm việc gần giống (FR-035, FR-037, FR-038, FR-060, SC-008). *Ghi 2026-08-24: quét theo **tên định danh đã tách chữ** chứ không quét chuỗi thô — `machine_id` và `MachineAdapter` đều dính, còn `RuntimeError` của Python thì không. Phạm vi quét lấy nguyên `domain/` và `application/` cho khớp phép kiểm FR-083 ngay bên cạnh; cả hai đang sạch. Phần cấm tự nhận việc canh ba dáng: đường có chữ `claim`/`take`, gọi thẳng `.assign(`, và tự điền `assign…=marius.id` — dáng thứ ba mới là cốt lõi. `POST /daemon/runs/claim` **không** nằm trong phạm vi vì khác tầng (FR-060).*
- [x] T025 Trỏ test phần nhận việc vào **Postgres của `docker-compose.yml`** (`postgres:16-alpine` đã có sẵn) bằng một fixture riêng trong `backend/tests/conftest.py` đọc `TEST_DATABASE_URL`; `psycopg[binary]` đã nằm trong `backend/pyproject.toml` nhóm `postgres` nên **không thêm dependency**. SQLite không có `SKIP LOCKED` nên test nhận việc chạy trên nó là vô nghĩa. *Ghi 2026-08-24: tách làm hai — `postgres_engine` (dựng lại schema) và `postgres_uow_factory` (không dùng connection pool, vì test cần nhiều kết nối tranh nhau thật). Fixture **xoá sạch mọi bảng**, nên nó từ chối mọi URL có tên database không kết thúc bằng `_test`: cơ sở dữ liệu thật của người chủ chỉ cách một cú `export` sai. `docker-compose.yml` nay công bố cổng `${POSTGRES_PORT:-5434}` — 5432 và 5433 trên máy này đều đã có người dùng. Kèm `backend/tests/test_postgres_fixture.py` giữ cho fixture khỏi mục trước khi T072 tới.*
- [x] T026 [P] Thêm `daemon/internal/config/config.go` đọc năm con số đặt được: nhịp poll, nhịp heartbeat, hạn giữ sau khi nhận việc, ngưỡng cắt nhật ký, trần đồng thời. Hạn giữ PHẢI lớn hơn mốc 15 giây ở SC-002 (FR-056c) — chốt **120 giây** theo [research §3](research.md)

**Checkpoint**: schema xong, đường cũ đã gỡ sạch. Mọi user story bắt đầu được.

---

## Phase 3: User Story 1 — Cắm máy vào workspace rồi giao được việc thật (P1) 🎯 MVP

**Goal**: cài daemon, nối vào workspace, dò được agent CLI, buộc agent vào chỗ làm, giao một đầu việc và
thấy nó chạy thật.

**Independent Test**: cài daemon lên máy có sẵn một agent CLI, tạo agent và **chọn chỗ làm cho nó**, tạo
đầu việc, giao cho nó. Đầu việc chuyển sang *đang làm*, diễn biến hiện lên màn hình, xong thì rời *đang làm*.

### Nối máy vào workspace

- [x] T027 [P] [US1] Viết `backend/armarius/infrastructure/daemon/enrollment.py` — sinh mã, duyệt, cấp token, tất cả dùng một lần và hết hạn sau 10 phút (FR-001) — **xong 2026-08-24**: token đúc **lúc trao**, không phải lúc duyệt, nên `consumed_at` đúng nghĩa và bí mật chỉ sinh ra đúng khoảnh khắc đưa được thẳng cho máy giữ nó; server chỉ giữ hash. **Sửa sau review (2026-08-25)**: `approve_link` có đúng cái lỗ tranh nhau mà `poll_link` đã vá — đọc "chưa ai duyệt" rồi mới ghi, hai lượt duyệt cùng lúc thì cả hai cùng ghi và người ghi sau thắng trong im lặng. Nay cả hai chỗ đều ghi **có điều kiện** và kiểm số dòng
- [x] T028 [US1] Thêm `POST /daemon/link/start` và `POST /daemon/link/poll` vào `backend/armarius/presentation/api/daemon.py` (FR-001) — **xong 2026-08-24**, kèm **hai lối cho người duyệt** mà cả hợp đồng lẫn danh sách này đều chưa có: `GET /v1/machines/link/{code}` và `POST /v1/machines/link/{code}/approve`. Không có chúng thì màn hình ở T031 không gọi được vào đâu, mà máy thì không tự nhận mình vào workspace được. Đã ghi vào [hợp đồng](contracts/daemon-api.md) §1
- [x] T029 [US1] Thêm `POST /daemon/token/renew` vào `backend/armarius/presentation/api/daemon.py` — **server quyết** đã tới lúc gia hạn chưa (FR-014a, FR-014d) — **xong 2026-08-24**: hạn 90 ngày, chỉ gia hạn khi còn dưới 14 ngày; gia hạn **giữ nguyên chuỗi bí mật**, chỉ dời hạn, để máy không phải ghi lại token giữa một lần chạy không ai trông
- [x] T030 [P] [US1] Viết `daemon/internal/client/enroll.go` — lệnh `login`, in mã, hỏi lại theo nhịp, lưu token vào `~/.armarius/daemon.json` với quyền `0600` (FR-001) — **xong 2026-08-24**: ghi bằng cách **trộn vào** tệp cũ chứ không đè, vì tệp ấy dùng chung với năm con số của T026; tệp có sẵn mà đang lỏng thì bị siết lại `0600` chứ không tin
- [x] T031 [P] [US1] Viết màn hình duyệt mã `frontend/src/pages/LinkMachine.tsx` và thêm route `/link` (FR-001) — **xong 2026-08-25**: route nằm **ngoài** `/w/:workspaceId` vì lúc gõ mã thì máy chưa thuộc không gian nào, và chọn nó vào đâu chính là quyết định đang làm ở đây. Ô nhập tự đặt lại dấu gạch nên gõ `kq7fm2xd` vẫn đúng. **Không** có đồng hồ đếm ngược: đặt đồng hồ lên màn hình là phạm FR-080, mà mã hết hạn giữa chừng thì lời từ chối của server đã nói đúng rồi. Cùng lúc **thêm `/daemon` vào `frontend/nginx.conf`** — thiếu nó thì máy ở ngoài chỉ gọi được qua cổng API, thứ mà bản triển khai thật không mở
- [x] T032 [P] [US1] Thêm chuỗi tiếng Việt đủ dấu cho màn hình duyệt vào `frontend/src/i18n/vi.ts` (Điều VI) — **xong 2026-08-25**, kèm `en.ts`; và đưa `pages/LinkMachine.tsx` vào danh sách màn hình bị lưới canh chữ cứng soi (đổi tên `_SPEC_001_SCREENS` thành `_SCREENS_UNDER_THE_RULE` vì nó không còn chỉ của đợt 001)

### Dò agent CLI và đăng ký chỗ làm

- [x] T033 [P] [US1] Viết `daemon/internal/discovery/discover.go` — dò `gemini`, `claude`, `codex` trên `PATH`, lấy phiên bản (FR-002) — **xong 2026-08-25**: một cái nhị phân **có trên `PATH` mà không chạy nổi** thì **không** thành chỗ làm, chỉ báo `cli_not_runnable` kèm dòng lỗi của chính nó. Không phải giả định: `codex` trên máy phát triển đúng ca ấy (thiếu gói nhị phân theo nền tảng), và đăng ký nó là nhận việc rồi hỏng trong im lặng — đúng thứ FR-033 cấm
- [x] T034 [US1] Viết `daemon/internal/discovery/capabilities.go` — **hỏi khả năng thật** từng CLI, KHÔNG suy từ tên loại (FR-017) — **xong 2026-08-25**: hỏi theo **họ giao thức**, vì cách hỏi phải khớp cách daemon sẽ chạy CLI ấy thật. Họ chạy-một-phát không có bắt tay, nên câu hỏi là bản tự khai của chính nhị phân (`--help`) — vẫn là *nó* trả lời, thứ bị cấm là trả lời thay bằng cái tên. Họ ACP **chưa hỏi được**: đường JSON-RPC qua luồng chuẩn là T066, và trả lời trước khi có nó thì chỉ còn cách đoán. Nên mọi khả năng chưa hỏi được ghi thẳng là `unanswered` kèm mã `no_probe_for_family`, không ghi `false` trơn — một phỏng đoán đã nằm trong cơ sở dữ liệu thì không ai phân biệt được với câu trả lời nữa. Khả năng thiếu vẫn là **được hỗ trợ, có hạ cấp** (FR-039a)
- [x] T035 [P] [US1] Viết `daemon/internal/execenv/linkprobe.go` — thử tạo symbolic link lúc khởi động, rơi về junction trên Windows, và **báo chỗ làm không sẵn sàng** nếu thứ bắt buộc không liên kết được ([research §5](research.md)) — **xong 2026-08-25**: tạo link xong **chưa tính là được**, phải với tới được thứ nằm sau nó; một liên kết tạo ra mà trỏ vào hư không thì không báo lỗi lúc tạo và hỏng giữa lượt chạy. Phần junction của Windows nằm riêng trong `linkprobe_windows.go` (dựng chéo được, không chạy thử được ở đây)
- [x] T036 [US1] Thêm `PUT /daemon/workplaces` và `POST /daemon/heartbeat` vào `backend/armarius/presentation/api/daemon.py`; chỗ làm mang **tên máy đọc được** qua `machines.display_name` (FR-002, FR-003, FR-004) — **xong 2026-08-25**, kèm **nửa bên máy** mà danh sách này chưa có lối nào: `daemon/internal/client/workplaces.go` (gọi hai lối trên bằng token của máy) và `LoadCredentials`. Không có nó thì hai lối vừa dựng không ai gọi, y như ca T028. `pending_work` chỉ bật khi máy **còn chỗ trống** — báo việc cho máy đầy là tiếng ồn, vì cú xin nó sinh ra chắc chắn về tay không. `cancel` là những lượt chạy máy khai đang chạy mà nó **không còn giữ** — cú ghi của chúng đằng nào cũng bị từ chối (FR-059), nói sớm thì đỡ phải sinh ra. Đã ghi vào [hợp đồng](contracts/daemon-api.md) §2
- [x] T037 [US1] Viết `backend/armarius/infrastructure/daemon/workplaces.py` — đồng bộ chỗ làm; CLI mất thì chuyển `not_ready(cli_removed)`, **không xoá** vì agent đang buộc vào đó (FR-033) — **xong 2026-08-25**: hàng giữ nguyên **cả id**, nên mối buộc agent↔chỗ làm không đứt; CLI quay lại thì chính hàng ấy sẵn sàng trở lại, không đẻ hàng thứ hai. Máy không tạo được liên kết thì **mọi** chỗ làm của nó mang `link_unsupported`. Hai lượt đồng bộ cùng lúc thì chỉ mục duy nhất `(machine_id, cli_kind)` chặn, kẻ thua **chạy lại một lần** và tìm thấy hàng — chứng minh trên Postgres thật ở `test_daemon_workplace_races.py`, gỡ vòng chạy lại ra là đỏ cả ba lần chạy
- [x] T038 [P] [US1] Viết `daemon/internal/supervisor/heartbeat.go` — phát nhịp 15 giây kèm số chỗ trống hiện tại (FR-004, FR-055c) — **xong 2026-08-25**: nhịp đầu đi **ngay**, không đợi hết một khoảng, để máy vừa lên đã có mặt. Số chỗ trống **đọc lại mỗi nhịp**, không giữ từ lúc khởi động. Nhịp hỏng **không bao giờ là chết**, và cố ý **không có** hạn số lần hỏng liên tiếp như `login` — ở đây không có ai đang đứng đợi, và cái laptop mất wifi một tiếng phải trở lại workspace khi wifi về, chứ không phải thoát. Kết luận máy chết là của server. Cùng lúc nối `start` vào: đọc token, dò liên kết, dò CLI, đăng ký, rồi phát nhịp
- [x] T038a [US1] Dựng ruột cho lệnh `status`: viết `daemon/internal/client/status.go`, nối vào `daemon/cmd/armarius-daemon/main.go`, và cho `start` ghi ra một tệp trạng thái nhỏ khi lên để `status` biết daemon còn sống không. In ra: workspace đã nối, các agent CLI dò được (dùng lại T033) kèm chỗ làm nào sẵn sàng, và tiến trình daemon còn chạy hay không; kèm cờ `-json` (FR-005a). *Thêm 2026-08-24: T002 khai ba lệnh con nhưng chỉ `login` (T030) và `start` (T038, T052, T054) có task dựng ruột — `status` thì không, và cũng không FR nào đòi nó. Lỗ này có từ bản `tasks.md` gốc (commit `7a590f2`), do chính cơ chế "lệnh chưa dựng thì báo lỗi kèm số task còn nợ" của PR #218 phơi ra. Người chủ chốt giữ lệnh này 2026-08-24, kèm FR-005a làm chỗ dựa.* *Xong 2026-08-25: lệnh này **không hỏi server một câu nào** — đó mới là điểm của nó. Bốn ca mà màn hình Máy trên web không tách nổi (máy tắt / daemon chết / thẻ truy cập hết hạn / agent CLI bị gỡ) thì ba ca chỉ nhìn từ trong máy mới thấy, mà ca thứ tư là ca không ai chạy được lệnh này. Nên câu trả lời dựng từ ba nguồn tại chỗ: tệp cấu hình `login` ghi, tệp trạng thái `start` ghi rồi làm mới mỗi nhịp, và một lượt dò `PATH` **ngay lúc hỏi**. Chính cái lượt dò ngay lúc hỏi biến "gemini đang đăng ký" cộng "gemini không còn trên máy" thành một mâu thuẫn nhìn thấy được. Tệp trạng thái **giữ thêm kết quả nhịp gần nhất**, hơn câu chữ gốc của task một chút: không có nó thì daemon hết hạn thẻ trông y hệt daemon khoẻ — tiến trình sống, chỗ làm sẵn sàng, mà chẳng gì tới được server. Tệp ấy bị xoá khi tắt có trật tự, nên file còn mà tiến trình mất nghĩa là **bị giết**, không phải tắt. Lệnh **luôn thoát mã 0**: "không có gì chạy ở đây" là câu trả lời, không phải lỗi. Kèm `daemon/internal/client/status_test.go`. Gỡ đăng ký chỗ làm lúc tắt là T122, không đụng ở đây.*

### Buộc agent vào chỗ làm — lỗ nghiệp vụ, không có nó thì cả chuỗi đứt

- [x] T039 [US1] Sửa use case tạo/mời agent trong `backend/armarius/application/use_cases/enrollment.py` — **bắt buộc có chỗ làm**, ghi một hàng vào `agent_workplace_bindings`, và từ chối tạo agent không chỗ làm. Mối buộc **không đổi được** sau khi tạo (FR-007, FR-007f) — **xong 2026-08-25**: câu chữ gốc của task đụng thẳng Điều III. Lưới canh ở T024 cấm mọi định danh mang chữ `workplace` trong `application/`, mà `enrollment.py` nằm đúng đó; ghi thẳng vào bảng chỗ làm từ đấy là phạm điều khoản không thương lượng. Cách gỡ là cách chính đặc tả đã dùng một lần ở T046 cho `slots_taken_by`: **tầng nghiệp vụ gọi thứ nó cần bằng tên của chính nó**. Ở đây là *chỗ đặt* — agent được đặt ở một chỗ, chỗ ấy mở hay đóng, hết; nó **không** cần biết chỗ ấy là một agent CLI trên một cái máy. Nên có `domain/entities/placement.py` + cổng `PlacementRepository`, còn bản dịch ngược về chỗ làm nằm **gọn trong một tệp** `infrastructure/daemon/placement.py`. Phép thử thật không phải là qua được lưới canh chữ mà là: **luật này có phải sửa không nếu mai việc chạy ở chỗ khác?** Không — nên nó đúng chỗ. Mối buộc ghi **trong cùng giao dịch** tạo agent, nên không có khoảnh khắc nào tồn tại agent chưa có chỗ làm. Cổng **cố ý không có** phương thức chuyển agent: FR-007 nói không đổi được, mà một cổng có `move` là một cổng sẽ có người gọi — kèm bài kiểm canh đúng chuyện đó. Cùng lúc **vá một lỗ có sẵn**: xoá agent hoặc xoá workspace chưa hề dọn sáu bảng của daemon, nên trước đợt này chưa lộ (bảng rỗng) mà từ nay thì mọi agent đều có hàng — gom vào `infrastructure/daemon/cleanup.py`, đặt cạnh chính mô hình nó là danh sách của
- [x] T040 [US1] Thêm trường chỗ làm vào schema tạo agent trong `backend/armarius/presentation/schemas.py` và route tương ứng; thêm `GET /workplaces` liệt kê chỗ làm sẵn sàng **trong workspace của người gọi** (FR-007f, Điều I) — **xong 2026-08-25**: `workplace_id` **không có giá trị mặc định**, nên thiếu nó là `422` trước khi có bất kỳ agent nào tồn tại. Lối liệt kê là `GET /v1/workspaces/{id}/workplaces` — lối của **người**, dùng thẻ đăng nhập, đi qua đúng phép kiểm chủ sở hữu mà mọi cửa workspace khác dùng, nên workspace của người khác đọc y hệt workspace không tồn tại. Chỉ liệt kê chỗ làm **sẵn sàng**, nên không có cờ `ready` để vẽ: mời agent vào một chỗ làm đã hỏng là đẻ ra một agent ngoại tuyến từ giây đầu tiên, mà mối buộc thì không đổi được — đường ra duy nhất là xoá agent làm lại. Danh sách **rỗng là câu trả lời thật**, không phải lỗi. Mã từ chối mang chữ `placement` chứ không phải `workplace` vì tầng nghiệp vụ ném nó; câu chữ trên màn vẫn là "chỗ làm". Đã ghi vào [hợp đồng](contracts/daemon-api.md) §2
- [x] T041 [P] [US1] Thêm ô chọn chỗ làm vào màn hình tạo/mời agent trong `frontend/src/pages/` và chuỗi tiếng Việt vào `frontend/src/i18n/vi.ts` — danh sách chỉ hiện chỗ làm sẵn sàng, không cho tạo khi bỏ trống (FR-007f, Điều VI) — **xong 2026-08-25** ở `pages/Directory.tsx`. Danh sách đọc **lúc mở biểu mẫu**, không giữ trong kho chung: một bản sao cũ chỉ dẫn người ta chọn nhầm. Đúng **một** chỗ làm thì chọn sẵn — một lựa chọn duy nhất không phải là lựa chọn; **từ hai trở lên thì để trống**, vì chọn hộ ở đây là chọn hộ cái máy mà agent sẽ sống suốt đời. Chưa nối máy nào thì không phải ô rỗng mà là câu nói rõ phải làm gì. **Hơn câu chữ gốc một chỗ**: biểu mẫu này trước giờ **nuốt mọi lời từ chối** của server (`void doInvite()` bỏ rơi promise hỏng), nên hai mã từ chối T039 vừa dựng sẽ không ai đọc được — người dùng chỉ thấy cái nút không làm gì. Nay dựng câu từ mã bằng `errorText`, thứ các màn khác đã dùng
- [x] T039a Xoá `MariusService.register` khỏi `backend/armarius/application/use_cases/mariuses.py` — **lối tạo agent thứ hai** (FR-007f). *Bối cảnh: trong code có hai chỗ tạo ra một agent mới. Chỗ thật là `InviteService`, nằm sau route `POST /workspaces/{id}/mariuses`, tức là màn hình thêm agent — chỗ này đã bắt buộc chọn chỗ làm từ T039. Chỗ thứ hai là `MariusService.register`: không route nào gọi, chỉ 17 file test gọi để dựng sẵn dữ liệu, và nó tạo agent **không có chỗ làm**. FR-007f viết "không có đường tạo agent nào mà bỏ trống chỗ làm", nên luật đang bị vi phạm ngay trong `application/`. Chưa gây hại vì không route nào chạm tới, nhưng ngày ai đó nối một route vào thì luật thủng mà không test nào kêu. Người chủ chốt 2026-08-25: **end user chỉ biết một lối tạo agent**, nên trong code cũng chỉ được có một.* **Xong 2026-08-25**: hàm dời xuống `backend/tests/support/agents.py` thành `make_agent` — đúng cái nó vốn là, đồ dựng cảnh cho test. Bản mới **có gắn chỗ làm**, vì một fixture tạo ra trạng thái mà sản phẩm không tạo nổi thì test dựng trên đó không còn là bằng chứng về sản phẩm nữa.

### Tạo agent kiểu Multica — bỏ hẳn gateway (chốt 2026-08-25)

Cả nhóm này là hệ quả của một quyết định: **thay luồng mời agent bằng đúng mô hình agent của Multica** —
đặt tên, viết instructions, gắn skill, chọn chỗ làm. Bốn thứ của đường gateway cũ (gateway url, api key,
probe trước khi tạo, setup prompt sau khi tạo) và **agent token sống lâu** đều chỉ tồn tại để phục vụ
đường ấy, nên FR-040a bảo gỡ theo. Đợt gỡ Hermes trước (T019–T023) mới gỡ adapter và dữ liệu, **chưa chạm
tới luồng tạo agent** — đây là chỗ vá lỗ đó.

- [x] T039b Gỡ `gateway_url` và `api_key` khỏi `RegisterMariusIn` trong `backend/armarius/presentation/schemas.py` và khỏi `InviteService.invite` trong `backend/armarius/application/use_cases/enrollment.py`; bỏ luôn cú probe `test_environment` trước khi tạo và `GatewayUnreachable`. Đổi tên `InviteService` → `AgentService` và `invite` → `create` cho khớp việc nó đang làm (FR-007g, FR-040a) **Xong 2026-08-25**: `InviteService` → `AgentService`, `invite` → `create`. Agent token vẫn đúc — chưa gỡ được vì `/agent/*` chưa có gì khác để xác thực (T039d) — nhưng không còn được đẩy đi đâu nữa, ai cần thì đọc thẳng từ database. Gỡ luôn `adapter_type` khỏi thân request: người gọi không được chọn runtime nữa, vì runtime là hệ quả của chỗ làm — **FR-007g1 mới, viết ra lúc làm task này**.
- [x] T039c Gỡ cú đẩy setup prompt: bỏ `push_setup`, `build_invite_prompt` và `build_skill_install_prompt` cùng hai chỗ gọi chúng ở `backend/armarius/presentation/api/workspaces.py`; bỏ `send_status` khỏi response và khỏi giao diện. Skill nay đi xuống trong gói nhận việc (FR-011b), nên không còn gì để đẩy (FR-007g, FR-011c) **Xong 2026-08-25**: gỡ luôn `build_invite_prompt`, `build_skill_install_prompt`, `install_steps_for` và `_skill_block`; `onboarding.py` giờ chỉ còn `credential_file_for` — thứ duy nhất của module đó còn ai dùng (wake prompt và leader chat). Đường link skill giữ nguyên, chỉ bỏ cú đẩy; trạng thái `failed` cũng bỏ theo vì không còn hành động nào ở đây có thể hỏng.
- [ ] T039d Gỡ **agent token sống lâu**: bỏ `agent_token`, `invite_status`, `approved_at` khỏi `backend/armarius/domain/entities/marius.py` và cột tương ứng, kèm migration xoá cột. FR-014a chốt hệ thống chỉ có hai token — của daemon và của lượt chạy — nên token thứ ba là mã chết. **Chặn**: phải xong T064 (token lượt chạy) trước, vì `/agent/*` hiện xác thực bằng chính token này (FR-007g, FR-014a)
- [x] T039e Thêm `instructions` và `description` vào `backend/armarius/domain/entities/marius.py`, schema, và migration. `instructions` đi xuống agent **mỗi lượt chạy** trong gói nhận việc; `description` **không bao giờ** vào prompt (FR-007i, FR-007j) **Xong 2026-08-25 — CHỈ phần lưu trữ**: hai cột `NOT NULL DEFAULT ''` chứ không nullable, vì với mọi chỗ đọc thì "chỉ dẫn rỗng" và "không có chỉ dẫn" là một, cột nullable chỉ bắt từng chỗ đọc tự quyết lại chuyện đó. **Vế "đi xuống agent mỗi lượt chạy" CHƯA nối** — hiện `instructions` mới chỉ được ghi và đọc lại, chưa có chỗ nào đưa nó vào prompt thật gửi agent. Việc nối là **T039i**, chặn bởi T045.
- [x] T039f Thêm luật **tên agent không trùng trong workspace**: unique index `(workspace_id, name)` kèm migration, và error code riêng khi trùng (FR-007h) **Xong 2026-08-25**: ràng buộc duy nhất `(workspace_id, name)` trong database, cộng một cú kiểm ở use case để trả về error code đọc được thay vì lỗi 500 của database. So tên đã bỏ hoa thường và cắt khoảng trắng hai đầu — "Marin" với "  marin " gọi lên vẫn là một người.
- [ ] T039g Thêm `model` và `thinking_level` vào agent; danh sách chọn lấy từ `workplaces.capabilities` (FR-017), CLI nào tự quản model thì không trả về lựa chọn nào. Bỏ trống thì dùng mặc định của chính CLI (FR-007k)
- [x] T039h Dựng lại màn hình thêm agent ở `frontend/src/pages/Directory.tsx`: bỏ ô gateway url, ô api key và ô chọn loại adapter; thêm ô instructions, ô description, ô chọn model và thinking level. Đổi chữ "Mời Agent" thành "Thêm Agent" ở `frontend/src/i18n/vi.ts` và `en.ts`. Ô chọn chỗ làm giữ nguyên như T041 đã dựng (FR-007g, FR-007i, FR-007j, FR-007k, Điều VI) **Xong 2026-08-25**: bỏ luôn ô chọn adapter — nó bày ba lựa chọn mà chỉ một cái có thật, và câu trả lời thật (công cụ nào chạy agent này) đã nằm ở ô chọn chỗ làm. Đổi chữ ở cả `vi.ts` và `en.ts`. *Bẫy đáng ghi: `npx tsc --noEmit` ở `frontend/` **không kiểm gì cả** — `tsconfig.json` để `"files": []` và chỉ trỏ references, nên nó exit 0 trên file có `Cannot find name`. Phải dùng `npx tsc -p tsconfig.app.json --noEmit`. Vì tin lệnh sai nên một `setAdapterType is not defined` lọt tới runtime, chỉ Playwright bắt được.*
- [ ] T039i Đưa `instructions` của agent vào gói nhận việc tại `backend/armarius/infrastructure/daemon/claim.py`, cạnh bối cảnh dự án của FR-011. **Chặn**: sau T045 (FR-007i, FR-011, FR-011a)
- [ ] T039j Chặn luồng tạo agent sinh thêm role: khi thêm agent vào dự án thì thêm thẳng agent, không qua role. **Không gỡ** bảng role/ghế ở đợt này — việc ấy đụng lõi đặc tả 001 và có đặc tả riêng (FR-007l)

### Test cho nhóm tạo agent

- [x] T082c [P] `backend/tests/test_create_agent.py` — tạo agent chỉ cần tên + chỗ làm; trùng tên trong cùng workspace bị từ chối; trùng tên ở workspace khác thì được; `description` không xuất hiện trong prompt gửi agent; `instructions` có mặt trong gói nhận việc (FR-007g, FR-007h, FR-007i, FR-007j) **Xong 2026-08-25**: `backend/tests/test_create_agent.py`, 10 bài.
- [x] T082d [P] Mở rộng `backend/tests/test_constitution_guards.py` — quét cấm chuỗi `gateway_url`, `api_key`, `push_setup`, `agent_token` quay lại trong `application/` và `presentation/`, và cấm role theo dự án quay lại luồng tạo agent (FR-007g, FR-007l, FR-040a) **Xong 2026-08-25**: quét `application/` và `presentation/`, KHÔNG quét `infrastructure/` — một adapter nói HTTP thì có base URL là đúng việc của nó, cấm chữ ở đó là cấm tầng ấy làm việc.


### Sống chết — sau port đã có, không đụng tầng nghiệp vụ

- [ ] T042 [US1] Thêm `DaemonLivenessProbe` vào `backend/armarius/infrastructure/adapters/liveness_probe.py` — trả lời từ `machines` + `workplaces` + `agent_workplace_bindings`; agent chưa buộc chỗ làm nào thì **offline**; **không ping agent**, và **cú poll của daemon không được tính là dấu hiệu sống** (FR-006, FR-006a, FR-006d, FR-007f, FR-055b)
- [ ] T043 [US1] Thay `GatewayHealthLivenessProbe` bằng `DaemonLivenessProbe` trong `backend/armarius/infrastructure/adapters/liveness_probe.py`, sửa dòng nối ở `backend/armarius/presentation/container.py`, và **xoá `backend/tests/test_gateway_health_probe.py`** (chuyển từ T023 xuống — tệp ấy kiểm probe cũ, phải sống tới đúng lúc probe cũ chết). **Lưu ý**: `PlaceholderLivenessProbe` đã bị thay từ đợt trước; trong mã hiện chỉ còn `GatewayHealthLivenessProbe` (FR-040)
- [ ] T044 [P] [US1] Hiện **lý do agent offline ở mức người đọc hiểu** (máy tắt / CLI bị gỡ / cạn hạn mức / chưa buộc chỗ làm) trên màn hình agent trong `frontend/src/pages/`, kèm chuỗi tiếng Việt ở `frontend/src/i18n/vi.ts` (FR-006c, FR-007c). *Ghi 2026-08-25: T036/T037 đã sinh ra hai mã lý do thật nằm ở `workplaces.not_ready_reason` — `cli_removed` và `link_unsupported` (máy không tạo được liên kết bắt buộc). Câu tiếng Việt cho hai mã ấy thuộc task này; chúng **chưa** có trong bảng câu chữ vì chưa màn hình nào đọc tới*

### Nhận việc — cửa duy nhất

- [ ] T045 [US1] Viết `backend/armarius/infrastructure/daemon/claim.py` — `atomic compare-and-swap` một câu theo [research §4](research.md); ghi `run_claims.claimed_at` và `runs.accepted_at` **trong cùng một giao dịch**. Tính đúng-một-lần nằm ở đây, **không** dựa vào daemon tự xếp hàng (FR-053, FR-054, FR-054a, FR-054b)
- [ ] T046 [US1] Thêm `POST /daemon/runs/claim` vào `backend/armarius/presentation/api/daemon.py`, và cùng lúc **nối trọn hành vi khi máy đầy** — một task, vì nửa vời thì không ra hành vi nào cả (FR-008, FR-008a, FR-008b, FR-008c, FR-008d, FR-008e, FR-055c):
  1. Server lấy **số nhỏ hơn** giữa trần và số chỗ trống daemon báo; phần vượt trần **giữ nguyên ở trạng thái chưa ai nhận**, không huỷ, không xếp lại, không hẹn giờ thử lại.
  2. Thêm một cổng ở `backend/armarius/application/ports/` trả lời "những lượt chạy nào đang chiếm hết chỗ mà đầu việc này cần", hiện thực ở `backend/armarius/infrastructure/daemon/`, rồi điền `slots_taken_by` trong `PushReasonService.snapshot()` — nếu không, đầu việc chờ 10 phút là lưới an toàn tưởng nó rơi và reo chuông nhầm. Tên cổng và tên phương thức **không được** mang chữ `daemon`/`machine`/`runtime`/`workplace` — T024 canh đúng chỗ này.
  3. Lượt hỏi tiếp theo của daemon, khi đã có chỗ trống, **phải lấy được đúng đầu việc đang chờ ấy** — đây mới là bằng chứng hành vi, không phải hai mục trên.
- [ ] T047 [US1] Thêm `POST /daemon/runs/{run_id}/start` — trả **404** nếu lượt chạy không còn thuộc máy này; đầu việc đã có máy nhận thì buộc vào đúng máy ấy (FR-007d, FR-058, FR-059)
- [ ] T048a [US1] Dựng lại phần dưới của màn hình **"Thiết lập bằng Tác nhân"** trên đường daemon, giữ nguyên phần người dùng thấy. Hôm nay `backend/armarius/application/use_cases/onboarding_session.py` gọi `adapter.execute` rồi **đứng đợi** câu trả lời; daemon không có kiểu gọi-rồi-đợi. Người dùng vẫn chat với Tác nhân Không gian đúng như cũ — hỏi một câu, trả lời, hỏi câu tiếp, cuối cùng ra dự án và đội hình (FR-040b). **Chặn**: sau T048
- [ ] T048b [US1] Rà **mọi luồng còn lại đang gọi agent qua gateway** và chuyển sang đường daemon mà không đổi hành vi ở tầng người dùng; liệt kê từng luồng kèm chỗ gọi trong PR (FR-040b)
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

- [x] T071 [P] [US1] `backend/tests/test_daemon_enrollment.py` — device flow, mã hết hạn, mã dùng một lần (FR-001) — **xong 2026-08-24**: 15 test chạy qua app thật, cộng `daemon/internal/client/enroll_test.go` cho nửa bên máy. **Bổ sung sau review (2026-08-25)**: `backend/tests/test_daemon_enrollment_races.py` — hai chỗ tranh nhau (hai lượt duyệt, hai lượt hỏi) dựng trên **Postgres thật**, vì trên SQLite chúng lúc bắt được lỗi lúc không, tuỳ hai lời gọi có chồng nhau hay không — đo thật, không phỏng đoán
- [ ] T072 [US1] `backend/tests/test_run_claim_atomic.py` — **chạy trên Postgres thật**; hai cú xin đồng thời chỉ một cú nhận được việc, và 5 lượt chạy đồng thời trên một máy không lượt nào bị nhận hai lần (FR-054, FR-054b, SC-009)
- [ ] T073 [P] [US1] `backend/tests/test_daemon_claim_batch.py` — lấy nhiều đầu việc cùng lúc vẫn atomic (FR-055e)
- [ ] T074 [P] [US1] `backend/tests/test_claim_expiry_returns_run.py` — quá hạn giữ thì đầu việc quay về trạng thái chưa ai nhận (FR-056a)
- [ ] T075 [P] [US1] `backend/tests/test_daemon_tenant_isolation.py` — mọi route `/daemon/*` chạm workspace khác trả **404** (Điều I, FR-036)
- [ ] T076 [P] [US1] `backend/tests/test_poll_is_not_a_liveness_signal.py` — máy bật mà CLI bị gỡ thì agent vẫn phải offline (FR-055b, FR-006a)
- [x] T077 [P] [US1] Tạo agent không chỗ làm bị từ chối; mối buộc không đổi được sau khi tạo; agent chưa buộc thì offline (FR-007, FR-007f) — **xong 2026-08-25 trong `backend/tests/test_agent_workplace_binding.py`** (T082b). *Gộp 2026-08-25: lúc làm T039 tôi không thấy dòng này nên viết một tệp test thứ hai cùng nội dung. Giữ một tệp, không giữ hai. Vế "agent chưa buộc thì offline" vẫn chờ T042 — chưa có `DaemonLivenessProbe` thì chưa kiểm được, đã ghi trong T042.*
- [ ] T078 [P] [US1] `backend/tests/test_wake_message_is_recorded_at_claim.py` — toàn văn thông điệp có mặt trong `run_events` ngay sau cú nhận việc, không đợi daemon báo về (FR-012a, FR-042)
- [ ] T079 [P] [US1] `backend/tests/test_claim_carries_skills.py` — gói nhận việc mang đủ kỹ năng của agent ấy và **chỉ** của agent ấy; đường dẫn thoát ra ngoài bị từ chối (FR-011b, FR-007b)
- [ ] T079a [US1] `backend/tests/test_full_machine_just_waits.py` — **chạy trên Postgres thật**, viết đúng hành vi người chủ đòi và không viết gì khác: trần 5, đang chạy đủ 5, đầu việc thứ 6 tới. Nó **không** bị huỷ, **không** bị hẹn giờ thử lại, **không** bị lưới an toàn tuyên đình trệ dù để trôi quá ngưỡng 10 phút, và mang trạng thái *đang chờ tới lượt* phân biệt được với *máy chết*. Rồi cho một lượt chạy kết thúc và để daemon hỏi lại theo nhịp poll bình thường — **đúng đầu việc thứ 6 ấy phải được lấy đi**, không cần ai đánh thức nó (FR-008, FR-008a, FR-008b, FR-008c, FR-008d, FR-008e)
- [ ] T080 [P] [US1] `daemon/internal/execenv/skills_test.go` — kỹ năng ghi ra **tệp thật** chứ không phải liên kết, và **ghi mới** ở lượt chạy thứ hai (FR-011b)
- [x] T081 [P] [US1] `daemon/internal/discovery/capabilities_test.go` — khả năng lấy từ hỏi thật, không từ tên loại (FR-017) — **xong 2026-08-25**: bài chốt là *cùng một CLI, cùng cái tên, bản không có cờ nối lại phiên* phải ra kết quả khác. Bản `--help` dùng trong test **chép từ `claude 2.1.226` thật**, không bịa
- [x] T082 [P] [US1] `daemon/internal/execenv/linkprobe_test.go` — không tạo được liên kết bắt buộc thì báo không sẵn sàng, **không âm thầm chép** ([research §5](research.md)) — **xong 2026-08-25**, kèm bài canh phép dò **không để lại gì** trên đĩa của người dùng
- [x] T082a [P] [US1] `backend/tests/test_daemon_workplaces.py` — CLI mất thì chỗ làm không sẵn sàng mà hàng vẫn còn nguyên id; máy không liên kết được thì cả loạt không sẵn sàng; máy đầy không bị gọi đi xin việc; máy này không thấy chỗ làm của máy khác (FR-002, FR-003, FR-004, FR-033, Điều I) — **xong 2026-08-25**, 14 bài. *Thêm 2026-08-25: T036 và T037 dựng hai lối và một dịch vụ mà bảng test của US1 không có dòng nào cho chúng — T075 chỉ soi phần 404 xuyên workspace, T079a chỉ soi ca máy đầy sau khi có cửa nhận việc. Lỗ có từ bản `tasks.md` gốc.*
- [x] T082b [P] [US1] `backend/tests/test_agent_workplace_binding.py` — tạo agent thì ghi đúng một mối buộc; thiếu chỗ làm thì không đẻ ra agent nào; chỗ làm của workspace khác đọc y hệt chỗ làm không tồn tại; chỗ làm hỏng bị từ chối kèm đúng mã lý do; nhiều agent chung một chỗ làm; CLI bị gỡ mà mối buộc vẫn trỏ về chỗ cũ; xoá agent thì nhả chỗ làm nhưng chỗ làm vẫn đứng đó cho những agent còn lại (FR-007, FR-007a, FR-007f, FR-033, Điều I) — **xong 2026-08-25**, 13 bài, **bảy phép thử phá** đều đỏ đúng chỗ. *Thêm 2026-08-25: T039–T041 dựng luật nền của cả chuỗi giao việc mà bảng test của US1 không có dòng nào cho nó — cùng một dạng lỗ với T082a.*

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
- [ ] T126a [P] Chặn dò mã nối máy: đặt trần số lần gọi `GET /v1/machines/link/{code}` và `POST /v1/machines/link/{code}/approve` cho mỗi người dùng, và trần số lần gọi `POST /daemon/link/poll` cho mỗi mã, trong `backend/armarius/presentation/api/daemon.py`. **Ghi lúc hiện thực T028 (2026-08-24)**: mã dài 8 ký tự trên bảng chữ 32 ký tự và sống 10 phút, nên đoán mò là không thực tế — nhưng chuẩn device flow (RFC 8628 §5.2) đòi trần này, và nay chưa có chỗ nào trong dự án làm được việc chặn tần suất, nên nó là một mẩu hạ tầng phải dựng chứ không phải một dòng thêm vào (FR-001)
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
- T064 chặn T039d — `/agent/*` đang xác thực bằng chính agent token sống lâu; gỡ nó trước khi token lượt chạy chạy được là khoá cửa của agent. *Sửa 2026-08-25: dòng này trước ghi T049, sai — T049 là chuyện `accepted_at` của động cơ đẩy, không dính gì tới token.*
- T045 chặn T039i — chưa có gói nhận việc thì instructions không có chỗ để đi xuống
- T048 chặn T048a — màn hình "Thiết lập bằng Tác nhân" phải có `DaemonAdapter` rồi mới nối lại được
- T025 chặn T072 — không có Postgres thật thì test nhận việc vô nghĩa
- T008 chặn T046 · T046 chặn T055 — có luật rồi mới có dữ liệu, có dữ liệu rồi mới vẽ được
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
| Toàn bộ test của US1 | T071, T072, T073, T074, T075, T076, T077, T078, T079, T079a, T080, T081, T082, T082a, T082b, T082c, T082d |
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
