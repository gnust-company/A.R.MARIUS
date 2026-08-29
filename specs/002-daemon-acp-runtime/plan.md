# Implementation Plan: Daemon tại máy người dùng và chuẩn ACP

**Branch**: `002-daemon-acp-runtime` | **Date**: 2026-08-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-daemon-acp-runtime/spec.md`

---

## Summary

Đổi chặng dưới cùng của Armarius: thay vì gọi agent qua một gateway ngoài, hệ thống phát việc xuống một
**daemon chạy trên máy người mời agent**, và daemon khởi chạy agent CLI ngay tại đó.

Điểm mấu chốt của kế hoạch này: **không thêm khái niệm nào vào tầng nghiệp vụ.** Hai port đã có sẵn nhận
thêm một implementation, cộng một bề mặt HTTP mới và sáu bảng — **và cả sáu đều nằm ở tầng infrastructure,
không bảng nào chạm vào thực thể domain.**

| Thứ đang có | Việc phải làm |
| --- | --- |
| `MariusAdapter.dispatch()` | Thêm `DaemonAdapter`. `dispatch()` **không gọi ra máy** — nó đánh dấu run có thể nhận rồi trả về ngay. Đúng hợp đồng đang có: *"dispatch thành công ngay khi runtime nhận việc"* |
| `LivenessProbe.probe()` | Thêm `DaemonLivenessProbe` — trả lời từ heartbeat của máy và tình trạng chỗ làm, **không** ping agent |
| `WakeEngine`, `StallWatchdog`, `PushReasonService` | **Không sửa logic.** Chỉ một chỗ: động cơ số 1 phải bật lúc máy nhận việc (FR-056) |
| `RunEvent` | Dùng lại nguyên cho tầng nhật ký; thêm cột cho phần rút gọn và mã che bí mật |

Daemon là chương trình **Go** riêng, không nằm trong backend Python. Backend chỉ mọc thêm một nhóm route
`/daemon/*` và một nhóm bảng.

**Nền mà kế hoạch này dựa vào đã ổn định** (người chủ xác nhận 2026-08-22): các luật vận hành ở đặc tả 001 —
bốn tác nhân, vòng đời đầu việc, các cổng chuyển trạng thái, luật động cơ đẩy, thang phục hồi ba mức — đã
chốt xong. Đợt này không chờ 001 nữa.

**Migration phải xoá dữ liệu, không chỉ gỡ mã** (chốt cùng ngày): mọi agent kiểu cổng ngoài cũ cùng những gì
treo theo nó bị xoá hẳn. Chi tiết năm chỗ phải sửa ở [data-model.md](data-model.md).

---

## Technical Context

**Language/Version**:
- Backend: **Python 3.12** (giữ nguyên)
- Daemon: **Go 1.23+** — chương trình mới, thư mục riêng `daemon/`
- Frontend: **TypeScript / React 19** (giữ nguyên)

**Primary Dependencies**:
- Backend: FastAPI 0.131, SQLAlchemy 2.0 (asyncio), Pydantic 2.12, `sse-starlette` 3.2, Alembic — **không
  thêm dependency mới**
- Daemon: thư viện chuẩn Go + `net/http`, `encoding/json`, `os/exec`. Không dùng framework. Đóng gói bằng
  `goreleaser` cho ba nền tảng
- Frontend: shadcn + Tailwind hiện có — **không thêm dependency mới**

**Storage**: PostgreSQL (thật) / SQLite (chỉ để test). **Cảnh báo dialect:** phép `atomic compare-and-swap`
ở FR-054 dựa trên `UPDATE … WHERE status = 'queued' … RETURNING` — Postgres còn có `FOR UPDATE SKIP LOCKED`
cho FR-055e. SQLite không có `SKIP LOCKED`; test chạy trên SQLite phải dùng đường tuần tự tương đương và
**phải có một test chạy trên Postgres thật** cho phần này — dùng `postgres:16-alpine` đã có sẵn trong
`docker-compose.yml` và `psycopg[binary]` đã có trong nhóm `postgres` của `pyproject.toml`, nên **không thêm
dependency nào**.

**Testing**: pytest + pytest-asyncio (backend, 96 tệp test hiện có), `go test` (daemon), Playwright (giao
diện — **công cụ của người kiểm, cài sẵn trên máy**; KHÔNG thêm vào `frontend/package.json`, không nộp bộ
test vào repo, đúng cách feature 001 đã làm ở T051/T077).

**Không có CI**: repo chưa có `.github/workflows` hay cấu hình CI nào, và không FR nào của đặc tả này yêu
cầu. Đợt này kiểm tại chỗ: `daemon/make check` và `uv run pytest` ở `backend/`. *(Sửa 2026-08-26: package `mcp/` đã xoá — xem T125.)* Dựng CI là khối
việc riêng, cần FR riêng.

**Target Platform**: Backend Linux/Docker. Daemon **Linux, macOS, Windows**.

**Project Type**: Web service + desktop daemon + web frontend.

**Performance Goals**: SC-002 — 95% số lần dưới **15 giây** từ lúc quyết định gọi dậy đến lúc agent bắt đầu
chạy. SC-003/SC-012 — sự kiện lên màn hình trong **3 giây**. SC-009 — một máy chạy **≥ 5** lượt đồng thời.
SC-014 — một lượt **1000 sự kiện** vẫn cuộn mượt.

**Constraints**:
- Toàn văn kết quả công cụ **không được rời máy người dùng** (FR-043a)
- Che bí mật làm **ở phía daemon**, không phải ở server (FR-048)
- Tầng nghiệp vụ không được biết tới khái niệm máy / runtime / daemon (FR-006)
- Windows: tạo symbolic link cần quyền riêng → xem research §5

**Scale/Scope**: Quy mô đội nhỏ — chục máy mỗi workspace, mỗi máy ≤ 20 lượt đồng thời. Không phải bài toán
hàng nghìn máy.

---

## Constitution Check

*GATE: phải qua trước Phase 0. Soi lại sau Phase 1.*

| Điều | Cách kế hoạch này tuân | Chứng minh bằng |
| --- | --- | --- |
| **I. Đa tenant** | Mọi route `/daemon/*` lọc theo workspace của token daemon; đọc nhật ký cũng vậy | Test 404 chéo workspace cho từng route mới |
| **II. Cổng Done** | Không đụng cổng đang có. Thêm đường **thử lại được** cho cú công bố hiện vật hỏng giữa chừng | `test_artifact_publish_idempotent` |
| **III. Trung lập adapter** | `DaemonAdapter` và `DaemonLivenessProbe` nằm sau hai port đã có. **Không** thêm tham số máy/runtime vào bất kỳ use case nào | Test quét mã cấm chuỗi `daemon`/`machine`/`runtime` xuất hiện trong `application/use_cases/` và `domain/` |
| **IV. Đẩy, không hỏi-vòng** | Giao diện vẫn nhận sự kiện qua kênh đẩy sẵn có. **Poll của daemon không phải giao diện** — Điều IV nói về trình duyệt | Không có thay đổi phía giao diện theo hướng poll |
| **V. Góc nhìn dự án** | Thông điệp gửi agent vẫn dựng từ vai trò trong dự án, đường dựng không đổi | Dùng lại `wake_engine` |
| **VI. Tiếng Việt cho người dùng** | Chuỗi mới ở màn hình nhật ký và màn hình máy đi qua `i18n/vi.ts`, đủ dấu | Test quét chuỗi cứng |
| **VII. Tiếng Anh cho agent** | Câu báo mở phiên mới (FR-025) và thông điệp gửi xuống viết tiếng Anh; trạng thái *đang chờ chỗ trống* lưu **mã + tham số**, không lưu câu (FR-008b) | `test_wake_body_is_a_code_not_a_sentence` mở rộng |

**Kết quả gate: PASS.** Không có vi phạm phải giải trình → phần Complexity Tracking để trống.

Một điểm đáng ghi: **Điều IV suýt bị đọc nhầm.** Nguyên văn Điều IV nói *"đẩy về **trình duyệt**"* và
*"**Giao diện** KHÔNG ĐƯỢC hỏi-vòng"*. Poll của daemon nằm ở chặng server↔máy, không phải chặng
server↔trình duyệt, nên không thuộc phạm vi điều này. Đã ghi vào research §2 để bước sau không tranh cãi lại.

---

## Project Structure

### Documentation (this feature)

```text
specs/002-daemon-acp-runtime/
├── spec.md                        # đã chốt, 103 điều khoản
├── research-multica-daemon.md     # nghiên cứu đọc từ mã nguồn Multica
├── plan.md                        # tệp này
├── research.md                    # Phase 0 — tám quyết định kỹ thuật
├── data-model.md                  # Phase 1 — sáu bảng mới + cột thêm
├── contracts/
│   ├── daemon-api.md              # hợp đồng server ↔ daemon
│   └── agent-callback.md          # hợp đồng agent ↔ server trong một lượt chạy
├── quickstart.md                  # Phase 1 — cách tự kiểm chứng
└── tasks.md                       # Phase 2 — /speckit-tasks sinh ra, KHÔNG phải tệp này
```

### Source Code (repository root)

```text
backend/armarius/
├── domain/                        # ── KHÁI NIỆM MÁY KHÔNG ĐƯỢC VÀO ĐÂY ──
│   ├── entities/
│   │   └── run.py                 # SỬA — thêm ĐÚNG MỘT cột `accepted_at`, trung lập runtime
│   └── services/
│       └── push_reason_rules.py   # SỬA — động cơ số 1 đọc `accepted_at` (FR-056)
├── application/
│   ├── ports/
│   │   └── adapter.py             # KHÔNG SỬA — hợp đồng đã đủ
│   └── use_cases/
│       └── (không thêm use case nào biết tới máy)
├── infrastructure/
│   ├── daemon/                    # MỚI — toàn bộ khái niệm máy sống ở đây
│   │   ├── models.py              #   machines, workplaces, run_claims,
│   │   │                          #   agent_workplace_bindings, daemon_link_codes
│   │   ├── claim.py               #   atomic compare-and-swap khi máy xin việc
│   │   └── enrollment.py          #   device flow nối máy vào workspace
│   ├── adapters/
│   │   ├── daemon_adapter.py      # MỚI — DaemonAdapter, sau port đã có
│   │   ├── liveness_probe.py      # SỬA — thêm DaemonLivenessProbe
│   │   └── hermes_gateway.py      # XOÁ (FR-040a)
│   └── alembic/versions/          # MỚI — một migration
└── presentation/api/
    ├── daemon.py                  # MỚI — nhóm route /daemon/*
    └── trace.py                   # SỬA — đọc nhật ký đầy đủ

daemon/                            # MỚI — chương trình Go độc lập
├── cmd/armarius-daemon/main.go
├── cmd/armarius/                  # MỚI — thứ agent gọi ngược; một binary, hai mặt (FR-013a)
├── internal/
│   ├── callback/                  # MỚI — ruột của binary trên: MỘT bảng lệnh, hai mặt đọc chung
│   │   ├── registry.go            #   bảng lệnh và phạm vi của từng nhóm (FR-013d)
│   │   ├── cli.go                 #   mặt lệnh — mã thoát, JSON ra stdout
│   │   ├── mcp.go                 #   mặt công cụ native — MCP qua stdio
│   │   └── workdir.go             #   câu hỏi trả lời TẠI MÁY, không lên server (FR-020a)
│   ├── client/                    # nói chuyện với server
│   ├── discovery/                 # dò agent CLI có trên máy
│   ├── execenv/                   # dựng thư mục làm việc, đổ kỹ năng, bơm công cụ
│   │   ├── context_file.go        #   đặt thông điệp vào tệp bối cảnh native của CLI
│   │   ├── skills.go              #   ghi kỹ năng — TỆP THẬT, ghi mới mỗi lượt (FR-011b)
│   │   ├── tools.go               #   cấp bộ công cụ theo lượt chạy (FR-013a)
│   │   └── changes.go             #   thư mục làm việc có gì — thứ agent tự làm ra (FR-020a)
│   ├── runtime/                   # hai họ giao thức: ACP và chạy-một-phát
│   ├── redact/                    # che bí mật TRƯỚC khi rời máy (FR-048)
│   └── supervisor/                # vòng lặp xin việc, heartbeat, trần đồng thời
└── go.mod

frontend/src/
├── pages/RunTrace.tsx             # MỚI — màn hình nhật ký đầy đủ
├── pages/Machines.tsx             # MỚI — danh sách máy và chỗ làm
└── i18n/vi.ts                     # SỬA — chuỗi mới

backend/tests/                     # ~18 tệp test mới
daemon/internal/**/*_test.go       # test của daemon
```

**Structure Decision**: Giữ nguyên bố cục Clean Architecture hiện có của backend. Daemon là **thư mục cấp
cao mới** `daemon/`, không nhét vào `backend/`, vì nó là chương trình khác ngôn ngữ, khác vòng đời phát
hành, và chạy trên máy người dùng chứ không phải trên hạ tầng.

Lý do không fork mã Multica: xem [research-multica-daemon.md §13](research-multica-daemon.md) — license của
họ cấm dùng mã để chạy dịch vụ cho bên thứ ba hoặc nhúng vào sản phẩm thương mại nếu chưa có commercial
license. Kế thừa **cách làm**, không kế thừa mã.

---

## Constitution Check — soi lại sau Phase 1

Lần soi này **bắt được một chỗ thiết kế ban đầu tự vi phạm**, và đã sửa trước khi chốt.

### Vi phạm đã tìm ra và đã sửa

**Bản nháp đầu đặt `machine_id` và `workplace_id` thẳng lên bảng `runs`, và `workplace_id` lên `mariuses`.**
Cả `Run` lẫn `Marius` đều là thực thể **tầng domain**, nên làm thế là để tầng nghiệp vụ biết tới khái niệm
máy — đúng thứ FR-006 cấm, và phép kiểm tự động ở FR-038 sẽ đỏ ngay.

Đã sửa thành:

| | Trước (sai) | Sau (đúng) |
| --- | --- | --- |
| Mốc nhận việc | `runs.machine_id`, `runs.claimed_at` | `runs.accepted_at` — **trung lập runtime**, chỉ nói *đã có ai đó nhận* |
| Chi tiết máy | trên `runs` | bảng riêng `run_claims` ở tầng infrastructure |
| Mối buộc agent ↔ chỗ làm | `mariuses.workplace_id` | bảng riêng `agent_workplace_bindings` |

Ràng buộc kèm theo: `runs.accepted_at` và `run_claims.claimed_at` phải ghi **trong cùng một giao dịch** với
cú `atomic compare-and-swap`. Ghi lệch nhau là đẻ ra đúng khe mà FR-056 sinh ra để bịt.

### Kết quả soi lại

| Điều | Sau thiết kế |
| --- | --- |
| I. Đa tenant | **PASS** — cả sáu bảng mới đều có `workspace_id`; mọi route `/daemon/*` lọc theo token |
| II. Cổng Done | **PASS** — cổng không đổi; thêm đường thử lại cho cú công bố hỏng giữa chừng |
| III. Trung lập adapter | **PASS sau khi sửa** — xem trên |
| IV. Đẩy, không hỏi-vòng | **PASS** — poll nằm ở chặng server↔máy, không phải chặng server↔trình duyệt (research §2) |
| V. Góc nhìn dự án | **PASS** — dùng lại đường dựng thông điệp hiện có |
| VI. Tiếng Việt cho người dùng | **PASS** — `not_ready_reason` lưu **mã**, giao diện dựng câu qua i18n |
| VII. Tiếng Anh cho agent | **PASS** — thông điệp gửi xuống và câu báo mở phiên mới đều tiếng Anh |

---

## Complexity Tracking

Không có vi phạm nào **còn lại** phải giải trình — chỗ tìm ra ở lần soi sau thiết kế đã sửa thay vì xin
miễn trừ. Bảng để trống.
