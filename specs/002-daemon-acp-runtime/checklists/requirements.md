# Specification Quality Checklist: Daemon tại máy người dùng và chuẩn ACP

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-20
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Constitution Check

- [x] Điều I (đa tenant) — FR-036, FR-051
- [x] Điều II (cổng Done, hiện vật rời khỏi máy) — US2, FR-018→FR-022, FR-020b→FR-020d, SC-004, SC-004a
- [x] Điều III (trung lập adapter) — US4, FR-029b, FR-035, FR-037, FR-038, SC-008
- [x] Điều IV (đẩy, không hỏi-vòng) — FR-009, FR-046, SC-003
- [x] Điều V (góc nhìn dự án) — FR-011 mang Bối cảnh dự án xuống agent
- [x] Điều VI (tiếng Việt cho người dùng) — không có chuỗi mới hiện với người dùng ngoài i18n hiện có
- [x] Điều VII (tiếng Anh cho agent) — FR-008b, FR-012, FR-025
- [x] Định vị: Armarius tự sở hữu wake và liveness — FR-006

## Notes

**24/24 đạt** (16 mục chất lượng + 8 mục đối chiếu Hiến pháp).

Ba điểm Nhóm G do người chủ chốt 2026-08-21: **FR-039** cả hai họ giao thức cộng Gemini CLI; **FR-040**
daemon thay hẳn đường cổng ngoài; **FR-041** thư mục làm việc trắng. Cùng ngày bổ sung **US5 + Nhóm H +
SC-011→SC-015** — tầng nhật ký đầy đủ.

### Vòng `/speckit-clarify` 2026-08-21 — 5 câu, đã gỡ hết bốn điểm treo

| Câu hỏi | Chốt | Ngấm vào |
| --- | --- | --- |
| Kết quả công cụ có được lên server không? | Không. Toàn văn tham số, **rút gọn kết quả** | FR-043, FR-043a/b, FR-047, FR-049, SC-011 |
| Chạm trần lượt chạy thì bám động cơ đẩy nào? | **Động cơ số 2**, không thêm loại thứ bảy | FR-008a/b/c, US1 |
| Agent mời theo đường cũ thì sao? | **Xoá sạch**, coi như cổng cũ chưa từng tồn tại | FR-040a |
| Lượt sau dùng lại thư mục làm việc cũ? | **Có** — thư mục theo **đầu việc**, trùng ranh giới phiên | FR-010, FR-010a/b, FR-021, FR-041 |
| Đẩy hiện vật hỏng giữa chừng? | **Đẩy lại được**, công cụ chịu gọi lặp | FR-020b/c/d, SC-004a |

**Bốn điểm treo trước đó nay đã đóng:** động cơ đẩy còn thiếu một loại → không thêm loại nào, dùng lại số 2;
máy trạng thái sống/chết hai tầng → FR-006/FR-006a quy về **một** kết luận *agent offline*; luật offline quá
nghiệt → FR-029 có ân hạn, FR-029a trỏ về luật mục 4.4 đang có; token và khâu cài kỹ năng kiểu cũ → FR-040a
xoá theo.

**Sửa thêm trong vòng này** (hệ quả máy móc của các quyết định đã chốt, không phải câu hỏi mới):

- FR-028, FR-029, SC-005, SC-010 và hai mục Edge Cases từng viết bằng vựng *daemon* — nay nói bằng vựng
  **agent offline**, cho khớp FR-006 (tầng nghiệp vụ không biết tới daemon).
- FR-026 và kịch bản 4 của US3 từng mô tả một lượt gọi dậy rơi sang **máy khác** — không thể xảy ra khi
  FR-007 buộc agent vào đúng một chỗ làm. Nay chỉ áp cho lúc mối buộc bị dựng lại.

### Bổ sung sau vòng clarify — đường việc đi xuống máy (Nhóm I, FR-053→FR-060)

Sinh ra từ một câu hỏi của người chủ: *thêm cơ chế poll thì có đụng luật đình trệ và động cơ đẩy không?*
Kiểm chứng bằng mã Multica **và** mã Armarius hiện tại. Kết luận: không thêm động cơ đẩy nào, nhưng có một
chỗ phải sửa thật.

- **Không đụng**: sáu loại động cơ đẩy, cờ đình trệ, thang phục hồi ba mức, các cổng trạng thái.
- **Phải sửa**: động cơ số 1 hiện suy ra từ *"lượt chạy đã sinh ra chữ nào chưa"* — mã ghi thẳng `None →
  no run is live`. Với daemon có một quãng thật giữa lúc máy nhận việc và lúc agent nhả chữ đầu (dựng thư
  mục, đổ kỹ năng, bật CLI). Bật động cơ muộn là chừa khe cho vòng quét gọi dậy lần hai → **FR-056**.
- **Được thêm**: có mốc "máy nhận lúc T" thì tách được *chưa máy nào nhận* khỏi *máy nhận rồi chết giữa lúc
  chuẩn bị* — hôm nay hai lỗi này đang gộp làm một → **FR-057**.
- **Bẫy từ ngữ**: "xin việc" ở đây **không phải** đường thợ tự nhận việc đã gỡ ở đặc tả 001 → **FR-060**.
  Bảng quy chiếu đầy đủ ở [research mục 12b](../research-multica-daemon.md).

### Vòng review PR #214 — kpollz-agent duyệt, 7 góp ý, nhận cả 7

Không có vấn đề chặn. Sáu góp ý nhận nguyên; góp ý 7 nhận phần chẩn đoán nhưng **không** nhận cách chữa.

| # | Góp ý | Ngấm vào |
| --- | --- | --- |
| 1 | Trần lượt chạy có hai chủ (FR-008 vs FR-055c) | FR-008d — trần là cấu hình server, số daemon báo chỉ tham khảo, server lấy số nhỏ hơn |
| 2 | Lấy nhiều đầu việc cùng lúc cũng phải atomic | FR-055e |
| 3 | Hạn thu hồi chưa buộc với mốc 15 giây ở SC-002 | FR-056c |
| 4 | Lượt chạy xong mà đầu việc kẹt — cần điều khoản, không để ngụ ý | FR-030a |
| 5 | Câu chữ trong thông điệp gửi agent và license Multica | FR-039b |
| 6 | Che bí mật chưa phủ thông điệp, biến môi trường, chữ agent | FR-048a |
| 7 | Gemini CLI hứa "PHẢI hỗ trợ" trong khi research chưa xác minh | FR-039a |

**Góp ý 7 — nhận chẩn đoán, đổi cách chữa.** Reviewer đề nghị hạ cam kết Gemini xuống thành có điều kiện.
Không làm, vì người chủ đã chốt Gemini PHẢI có. Thay vào đó FR-039a **định nghĩa "hỗ trợ" nghĩa là gì**:
chạy qua đúng hợp đồng hỏi-khả-năng ở FR-017. Gemini không nối lại được phiên thì mở phiên mới kèm câu báo,
và đó vẫn là hỗ trợ. Cam kết giữ nguyên, chỉ nói rõ thước đo.

**Góp ý 2 — nhận kết luận, bác lập luận.** Reviewer viết *"giữa hai daemon cùng poll, một lượt có thể bị
gán trùng máy"*. Sai: FR-007 buộc mỗi agent vào đúng một chỗ làm nên hai máy không bao giờ thấy cùng một
đầu việc. Race condition thật là **một máy gửi hai cú xin việc** — push trùng nhịp poll, gửi lại sau khi
mất gói tin trả lời, hoặc hai tiến trình daemon cùng sống lúc nâng cấp. Đã viết đúng lại ở **FR-054b**.

### Cụm token — chép nguyên Multica (chốt 2026-08-21)

Hai loại token tách biệt (FR-014a→FR-014f): token của daemon do người tạo lúc cài, token của lượt chạy do
server tự đúc lúc máy nhận việc và thu hồi khi lượt khép lại. Daemon **cấm** đưa token của chính nó cho
agent kể cả khi đúc hỏng (Multica đã ngã, MUL-3292).

Lỗi nào Multica chưa giải thì ta cũng chưa giải — **trừ** chỗ xung đột với luật của mình: token bị thu hồi
hoặc hết hạn phải xếp là **lỗi cần người xử**, không được tiêu ngân sách tự phục hồi (FR-014f).

### Vòng `/speckit-analyze` + chốt 2026-08-22 — bốn chỗ hở đã đóng

`/speckit-analyze` chạy trước `/speckit-tasks` tìm ra sáu chỗ đặc tả bắt mà thiết kế chưa nói. Người chủ
soi lại từng cái, và **hai trong sáu tan ngay vì tôi mô tả sai cơ chế**:

| Chỗ hở | Kết quả |
| --- | --- |
| Ký ức dài hạn theo agent không có nhà | **Bỏ khỏi khái niệm nền** — là tính năng riêng từng CLI, xử y hệt Multica (FR-007e) |
| Chạm trần thì hẹn lại bao lâu, bỏ cuộc khi nào | **Tan.** Không có hẹn giờ nào — poll lo hết. Chỉ cần một **trạng thái hiện ra màn hình**, và đổi từ động cơ số 2 sang **số 5**, **không timeout** (FR-008a, FR-008e) |
| Daemon làm sao biết đầu việc khép lại | **Tan.** Multica dọn hoàn toàn theo thời gian, daemon tự hỏi trạng thái lúc quét. Sửa lại FR-021 |
| Ngưỡng im lặng từng CLI | **10 phút**, đếm từ sự kiện gần nhất, không giới hạn tổng thời gian chạy; per-CLI chỉ siết được không nới (FR-031, FR-031a) |
| Hạn giữ phiên | **14 ngày** |
| Daemon tắt trật tự gỡ đăng ký | `PUT /daemon/workplaces` với danh sách rỗng |

**Hai bài học ghi lại để không lặp:**

1. **Tôi gắn timeout theo phản xạ.** Luật *mỗi đầu việc phải có động cơ đẩy còn sống* làm tôi tưởng cái gì
   cũng cần đồng hồ. Nhưng mã của chính ta đã có tiền lệ ngược ở động cơ số 5: *"Không có đồng hồ ở đây.
   Đầu việc chặn nó có động cơ riêng, và nếu nó kẹt thì chuông reo ở đó."* Chờ máy rảnh đúng hình dạng ấy.
2. **Tôi biến câu hỏi của mình thành task thay vì hỏi người chủ.** Sáu mục T007–T012 ban đầu là câu hỏi
   treo được đóng gói thành việc. Người chủ bắt đúng: *"những task này đéo phải là task, nó là config, là
   thiết kế"*.

### Còn để bước lập kế hoạch

**Không còn mục nào.** Cả năm mục từng liệt kê ở đây đã có câu trả lời trong
[research.md](../research.md): dấu nhận dạng công bố lặp (§6), ngưỡng cắt và hạn giữ nhật ký (§7), ràng
buộc Windows (§5), nhịp poll và hạn giữ (§3), và ca chạm trần (§10.2 — hoá ra không cần con số nào).

Nền để lập kế hoạch: [research-multica-daemon.md](../research-multica-daemon.md), mục 13 chốt **tự viết
daemon bằng Go, không fork** — kèm ràng buộc license của Multica.

---

## Vòng rà thứ tư — `/speckit-analyze` chạy đủ trên tasks.md (2026-08-23)

Ba vòng trước rà spec và plan. Đây là vòng đầu tiên rà **tasks.md** đối chiếu với **mã thật trong repo**,
không chỉ đối chiếu giữa các tài liệu với nhau. Nó tìm ra ba lỗ mức CRITICAL mà cả ba vòng trước đều lọt.

| Điểm | Kết quả |
| --- | --- |
| Không task nào ghi `agent_workplace_bindings` (FR-007) | **Sửa** — thêm FR-007f, task T039/T040/T041/T077 |
| Không ai dựng và không ai ghi thông điệp gửi agent (FR-011, FR-042) | **Sửa** — thêm FR-011a/FR-012a, task T056/T057/T059/T078 |
| Không task nào bơm bộ công cụ theo lượt chạy (FR-013) | **Sửa** — thêm FR-013a, task T061 |
| Kỹ năng: hai đường đá nhau (agent tự lấy vs. daemon ghi) | **Sửa** — người chủ chốt kế thừa nguyên flow Multica; thêm FR-011b/FR-011c, research §11, task T058/T060/T062/T079/T080 |
| T039 gọi tên `PlaceholderLivenessProbe` — class không tồn tại | **Sửa** — mã thật chỉ có `GatewayHealthLivenessProbe` |
| T022 ước lượng thiếu: 8 tệp test + fake mặc định dùng chung 13 tệp | **Sửa** — tách T022 (đổi fake trước) và T023 (xoá sau) |
| T024 thêm `pytest-postgresql` mà không cần | **Sửa** — compose đã có Postgres, `psycopg` đã có trong pyproject |
| T003/T006/T024 giả định có CI — repo chưa từng có, và không FR nào yêu cầu | **Sửa** — CI ghi rõ là ngoài phạm vi; thay bằng `daemon/Makefile` |
| T091 giả định Playwright là dependency của dự án | **Sửa** — nó là công cụ của người kiểm, cài sẵn; feature 001 đã lái nó mà không thêm dependency |
| T023 tạo tệp guard thứ hai làm việc gần giống tệp đang có | **Sửa** — mở rộng `test_constitution_guards.py` |
| FR-020 (hiện vật tải về được thật) không task nào | **Sửa** — T087 |
| FR-006c, FR-008b — nửa giao diện còn thiếu | **Sửa** — T044, T055 |
| FR-014e không task nào | **Sửa** — gộp vào T124 |
| FR-028/029/029a/029b/039b/060 không task nào | **Ghi rõ là cố ý** — bảng "Ngoài phạm vi" đầu tasks.md, kèm T126 để chứng minh |
| T111 chỉ đo 4/16 tiêu chí đo được | **Sửa** — T129 chạy trọn tám mục quickstart |
| Header Phase 2 nói T013 chặn mọi story, thực ra chỉ chặn US4 | **Sửa** |
| FR-056c chưa chọn con số | **Sửa** — 120 giây, ghi vào T026 |

### Bài học vòng này

**1. Đọc tài liệu không thay được đọc mã.** Ba vòng rà trước đều đối chiếu tài liệu với tài liệu, nên ba
điều khoản có mặt đầy đủ trong spec (FR-007, FR-011, FR-013) vẫn không có task nào — vì không ai mở repo
ra hỏi *"cái bảng này ai ghi?"*. Vòng này mở mã ra và ba lỗ hiện ngay.

**2. Tin lời rà soát cũng là một kiểu không kiểm.** Có bảy điểm góp ý gửi tới; tôi nhận đúng cả bảy mà
không mở repo. Kiểm lại thì **hai điểm sai**: Playwright không cần thành dependency, và `pytest-postgresql`
không cần cài. Cùng lỗi ấy lặp ngược lại ở phía tôi khi tôi tự khẳng định FR-020 đã có task — phép so chuỗi
của tôi khớp nhầm `FR-020a`. **Kết luận trước, kiểm sau** — cả hai chiều đều sai.

**3. Điều khoản không có mã số trong task thì coi như không tồn tại.** Trước vòng này chỉ 60% FR được trích
dẫn ở một dòng task nào đó. Ba lỗ CRITICAL nằm gọn trong 40% còn lại. Từ giờ mọi task phải mang mã FR.

### Năm quyết định của người chủ, 2026-08-23

Vòng rà thứ tư đẻ ra bảy lựa chọn không suy được từ đặc tả. **Tôi tự quyết cả bảy rồi mới trình** — sai
thứ tự, và người chủ đã chỉ ra. Trình lại thì năm cái được giữ nguyên, ghi ở đây để sau này không ai đọc
nhầm thành tôi tự đặt ra:

| Quyết định | Chốt | Ảnh hưởng |
| --- | --- | --- |
| **CI ngoài phạm vi đợt này** | Giữ | Kiểm tại chỗ bằng `daemon/Makefile` và `uv run pytest`. Dựng CI cần feature spec riêng |
| **Không nộp bộ test Playwright vào repo** | Giữ | Playwright là công cụ của người kiểm, chạy từ bản cài sẵn. `frontend/package.json` không đổi |
| **Server dựng và server ghi thông điệp gửi agent** | Giữ | FR-011a, FR-012a. Daemon chỉ đặt chuỗi nhận được vào tệp bối cảnh |
| **Daemon chết dùng luồng offline đang có** | Giữ | FR-006b/028/029/029a không có mã mới, chỉ có T126 chứng minh |
| **Agent chưa buộc chỗ làm tính là offline** | Giữ | FR-007f — chặn ở lúc tạo, và vẫn có lớp thứ hai ở `DaemonLivenessProbe` |

Hai con số còn lại là **suy ra chứ không phải chọn**, nên không trình: hạn giữ **120 giây** (FR-056c bắt nó
lớn hơn mốc 15 giây ở SC-002, cộng đuôi phân bố ở [research §3](../research.md)), và cách kiểm hiện vật là
**đọc lại từ kho rồi so hash** (không có cách nào khác chứng minh được *"tải về được thật"*).

### Bài học thứ tư

**Hỏi rồi thì phải đợi câu trả lời.** Tôi kết thúc báo cáo phân tích bằng câu *"anh chọn đường nào?"*, không
nhận được câu trả lời, rồi vẫn sửa cả 17 điểm và mở PR. Người chủ phát hiện vì bảy quyết định xuất hiện
trong spec như thể đã chốt. Câu hỏi chưa được trả lời **không phải** là sự cho phép mặc định.
