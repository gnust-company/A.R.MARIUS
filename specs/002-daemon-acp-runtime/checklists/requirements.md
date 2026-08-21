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

### Còn để bước lập kế hoạch

1. Nhịp hẹn lại và ngưỡng bỏ cuộc khi chạm trần (FR-008a/c)
2. Lấy gì làm dấu nhận dạng để hai lần công bố biết là cùng một thứ (FR-020c)
3. Ngưỡng cắt bản rút gọn và hạn giữ mặc định của nhật ký (FR-043a, FR-049, FR-050)
4. Ràng buộc riêng của Windows (quyền tạo liên kết tệp)
5. Nhịp poll và hạn giữ của trạng thái *đã có máy nhận* (FR-055d, FR-056a) — 3 giây là con số của Multica,
   ta không cần chép

Nền để lập kế hoạch: [research-multica-daemon.md](../research-multica-daemon.md), mục 13 chốt **tự viết
daemon bằng Go, không fork** — kèm ràng buộc license của Multica.
