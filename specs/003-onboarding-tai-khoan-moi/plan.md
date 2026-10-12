# Implementation Plan: Onboarding dạy từ thêm máy tới agent đầu tiên

**Branch**: `spec003-buoc-agent-dau-tien` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: lần sửa 2026-10-12 của `specs/003-onboarding-tai-khoan-moi/spec.md` — Nhóm C (FR-120 đến
FR-128), FR-100, FR-106 và FR-112 sửa lại, SC-105 đến SC-108.

Plan này chỉ phủ **lần sửa 2026-10-12**. Phần 2026-09-07 (T001–T014) đã xong và không làm lại.

---

## Summary

Onboarding hôm nay dừng ở chỗ nối máy, và runtime của Livia do hệ thống tự chọn theo id. Lần sửa này làm
bốn việc:

1. **Bước *nối máy* biết mình đang ở đâu.** Dùng lại sự kiện `machine.linked`, thêm sự kiện
   `machine.workplaces_reported`. Duyệt máy thì đánh dấu xong phần *nối*. Daemon chạy lên thì tự sang
   bước mới.
2. **Bước *agent đầu tiên*.** Bước này hiện system prompt chỉ đọc, chỉ dẫn mặc định sửa được, và danh
   sách runtime sẵn sàng để chọn. Bấm xong thì gọi một cửa mới, **chỉ dành cho người chủ nhà**: cửa này
   đặt chỗ và lưu chỉ dẫn trong cùng một lần, rồi kiểm sống ngay.
3. **Bỏ tự đặt chỗ.** Người chủ nhà chưa có chỗ làm thì trang của nó có đường chọn runtime.
4. **Ẩn skill dựng sẵn ở mọi màn.** Lọc ngay ở cửa API, và dọn id của chúng khỏi `skill_ids`. Phía agent
   không đổi gì.

**Không có bảng mới, không có cột mới, không đổi mã daemon.** Một migration dữ liệu duy nhất dọn id skill
dựng sẵn ([data-model.md](data-model.md)).

| Thứ đang có | Việc phải làm |
| --- | --- |
| `WorkspaceAgentService.place_host` (tự chọn id nhỏ nhất, gọi từ `sync_workplaces`) | **Viết lại** thành cửa nhận đúng chỗ làm người dùng chọn, kèm `instructions`. Xoá lời gọi trong `sync_workplaces` |
| `AgentService.create_unplaced` | Người chủ nhà mới tạo mang `instructions = HOST_DEFAULT_INSTRUCTIONS` |
| `LivenessEngine.placement_changed` (FR-006e) | Dùng lại nguyên |
| `announce_machine_linked` | Giữ nguyên. Thêm `announce_workplaces_reported` cạnh nó |
| `SkillService` / `GET …/skills` | Lọc `source = "builtin"` khỏi mọi cửa cho người xem; cửa ghi bỏ id dựng sẵn |
| `Onboarding.tsx` (3 bước) | 4 bước; bước 3 có ba phần; bước 4 mới |
| `LinkMachine.tsx` | Thôi đánh dấu xong onboarding khi duyệt máy |
| `AgentDetail.tsx` | Đường chọn runtime cho người chủ nhà chưa có chỗ làm |
| `Skills.tsx`, `Directory.tsx`, `SkillsTab.tsx` | Bỏ tab *Tích hợp sẵn* và nhánh chip *luôn bật* |

---

## Technical Context

**Language/Version**: Backend Python 3.12; frontend TypeScript, React 19, Vite 7. Daemon Go: không đổi.

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic (backend); React Router, Zustand, i18next,
shadcn/ui (frontend). Không thêm thư viện nào.

**Storage**: PostgreSQL. Không đổi schema. Một migration dữ liệu dọn `mariuses.skill_ids` và
`mariuses.skills`.

**Testing**: pytest (backend, có cả SQLite lẫn Postgres thật cho migration); vitest (frontend);
Playwright qua `python3` của hệ thống trên stack thật (quickstart K1–K8).

**Target Platform**: web app chạy bằng docker compose (UI `:3000`, API `:8080`).

**Project Type**: web application (backend + frontend), daemon Go đứng ngoài lần sửa này.

**Performance Goals**: đánh dấu xong phần *nối* và sang bước *agent đầu tiên* trong vòng 5 giây kể từ sự
kiện (SC-107). Cả hai đều là tin đẩy nên không có chu kỳ hỏi nào.

**Constraints**:
- Không hỏi vòng (Điều IV).
- Tầng nghiệp vụ không có chữ `machine`, `runtime`, `workplace` (Điều III, có guard trong bộ kiểm).
- Chữ gửi agent bằng tiếng Anh (Điều VII).
- Không chạy `gemini` hay `codex` ở môi trường này (research R10).

**Scale/Scope**:
- Backend: 1 cửa mới, 3 cửa sửa, 1 sự kiện mới, 1 migration dữ liệu.
- Frontend: 1 trang viết lại phần lớn, 4 trang sửa nhỏ, 1 component dùng chung mới.
- Tài liệu người dùng: 2 tệp.

---

## Constitution Check

*GATE: kiểm trước Phase 0, kiểm lại sau Phase 1.*

| Điều | Áp vào lần sửa này | Kết quả |
|------|---------------------|---------|
| **I. Đa tenant** | Cửa đặt chỗ đi qua `_require_owned_workspace`. Agent hoặc chỗ làm thuộc workspace khác thì trả 404. Sự kiện mới chỉ phát trên kênh của đúng workspace | ĐẠT |
| **II. Cổng Done** | Không đụng vòng đời đầu việc | KHÔNG ÁP |
| **III. Trung lập adapter** | Use case chỉ nhận **id chỗ làm** và tự hỏi chỗ làm xem có nhận việc được không, như `place_host` hôm nay. Tên sự kiện có chữ `machine` nằm ở `infrastructure/events/`. `cli_kind` và `machine_name` trong lỗi 409 do presentation tra ra | ĐẠT |
| **IV. Đẩy, không hỏi vòng** | Bước *nối máy*, bước *agent đầu tiên* và trang người chủ nhà chỉ đọc lại khi có `machine.linked` hoặc `machine.workplaces_reported` | ĐẠT |
| **V. Chỉ dẫn thuộc về agent** | Chỉ dẫn mặc định là `instructions` của chính agent; system prompt ở `system_instructions`. Mỗi thứ một chỗ đọc, một chỗ sửa. Không đụng vai theo dự án | ĐẠT |
| **VI. Tiếng Việt cho người dùng** | Mọi nhãn, câu báo, bước, lý do mới đi qua i18n, đủ dấu. System prompt hiện **nguyên văn** trong khung i18n (xem dòng VII) | ĐẠT (có ghi chú) |
| **VII. Tiếng Anh cho agent** | Chỉ dẫn mặc định và system prompt đều bằng tiếng Anh, giữ ở backend. System prompt hiện đúng **một** bản là bản agent nhận, không dịch, nên không có bản chép thứ hai ([research R8](research.md)) | ĐẠT |

**Kiểm lại sau Phase 1**: vẫn đạt cả bảy. Thiết kế có thêm một chốt: cửa đặt chỗ **chỉ cho người chủ nhà**
(research R2). Nhờ vậy FR-007 không bị nới cho agent thường mất chỗ làm khi máy bị gỡ.

---

## Project Structure

### Documentation (this feature)

```text
specs/003-onboarding-tai-khoan-moi/
├── spec.md              # sửa 2026-10-12
├── plan.md              # tệp này
├── research.md          # R1–R10
├── data-model.md
├── quickstart.md        # K1–K8, kiểm trên dịch vụ thật
├── contracts/
│   ├── user-surface.md  # cửa đặt chỗ mới, các cửa sửa
│   └── push-events.md   # machine.workplaces_reported
├── checklists/requirements.md
└── tasks.md             # thêm Phase 4 ở /speckit-tasks
```

### Source Code (repository root)

```text
backend/armarius/
├── application/use_cases/
│   ├── workspace_agent.py        # HOST_DEFAULT_INSTRUCTIONS; place_host viết lại (người dùng chọn, kèm instructions)
│   ├── enrollment.py             # create_unplaced nhận instructions mặc định (đã có tham số)
│   └── skills.py                 # list_skills cho người xem bỏ builtin; hàm lọc id dựng sẵn
├── infrastructure/
│   ├── events/workspace_trace.py # EVENT_WORKPLACES_REPORTED + announce_workplaces_reported
│   ├── daemon/workplaces.py      # (nếu phát ở tầng này) phát sau khi sync
│   └── alembic/versions/…        # migration dữ liệu: bỏ id dựng sẵn khỏi mariuses.skill_ids/skills
└── presentation/
    ├── api/daemon.py             # sync_workplaces: bỏ lời gọi place_host, phát sự kiện
    ├── api/workspaces.py         # POST …/mariuses/{id}/placement; lọc builtin ở list/get skill và cửa ghi skill
    ├── api/auth.py               # onboarding_step le=4
    └── schemas.py                # PlaceHostIn

backend/tests/                    # bài mới cho cửa đặt chỗ, sự kiện, lọc skill, migration;
                                  # sửa các bài đang dựa vào tự đặt chỗ (test_workspace_agent.py,
                                  # test_the_first_steps_of_a_new_account.py, test_daemon_workplaces.py, …)

frontend/src/
├── pages/Onboarding.tsx          # 4 bước; bước 3 có ba phần; bước 4 dựng Livia
├── pages/LinkMachine.tsx         # thôi gửi onboarding_done; nói lệnh start và cửa sổ đang đợi
├── pages/AgentDetail.tsx         # đường chọn runtime cho người chủ nhà chưa có chỗ làm
├── pages/Skills.tsx              # bỏ tab Tích hợp sẵn
├── pages/Directory.tsx           # bỏ nhánh chip luôn bật
├── components/agent/
│   ├── RuntimePicker.tsx         # mới: danh sách runtime sẵn sàng/chưa sẵn sàng + luật chọn sẵn (FR-125)
│   └── SystemPromptBlock.tsx     # tách từ InstructionsTab để onboarding dùng lại (R8)
├── lib/api.ts                    # placeHost(); onboarding_step 0–4
└── i18n/{vi,en}.ts               # chuỗi bước 3–4, lý do not_placed mới, lỗi 409 mới

docs/
├── quickstart.md                 # mục 2–4 theo luồng bốn bước
└── skills.md                     # "Talking to Armarius": tự gắn, không hiện, không phải chọn
```

**Structure Decision**: giữ nguyên cấu trúc web app hiện có (`backend/` Clean Architecture, `frontend/`).
Hai component mới nằm ở `components/agent/` vì cả onboarding lẫn trang agent cùng dùng.

---

## Thứ tự làm

1. **Backend trước.** Giao diện bước 4 không có gì để gọi nếu chưa có cửa đặt chỗ.
   - Cửa đặt chỗ, bỏ tự đặt chỗ, chỉ dẫn mặc định khi tạo người chủ nhà.
   - Sự kiện `machine.workplaces_reported`.
   - `onboarding_step` 0–4.
   - Lọc skill dựng sẵn và migration dữ liệu.
2. **Giao diện.**
   - Component dùng chung (`RuntimePicker`, `SystemPromptBlock`).
   - Onboarding bốn bước.
   - `LinkMachine`.
   - Trang người chủ nhà.
   - Ẩn skill dựng sẵn.
   - i18n.
3. **Tài liệu người dùng**, rồi **kiểm trên dịch vụ thật** theo quickstart K1–K8.

Ước lượng: khoảng 8–10 task, chia hai PR code (backend, rồi giao diện cùng tài liệu). Mỗi PR dưới ~5 task
có nghĩa, theo quy ước PR của dự án.

---

## Complexity Tracking

Không có vi phạm Hiến pháp cần biện minh. Ghi chú duy nhất là cách hiện system prompt, đã giải ở research R8:
một bản nguyên văn đặt trong khung i18n, không phải chuỗi giao diện chưa dịch.
