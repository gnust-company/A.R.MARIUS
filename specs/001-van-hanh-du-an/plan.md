# Kế hoạch triển khai: Vận hành dự án tự chủ

**Nhánh**: `spec/001-van-hanh-du-an` | **Ngày**: 2026-07-30 | **Đặc tả**: [spec.md](./spec.md)

**Đầu vào**: Đặc tả tính năng tại `specs/001-van-hanh-du-an/spec.md` (84 yêu cầu, 6 câu chuyện, 5 điểm đã
được người chủ chốt).

## Tóm tắt

Đưa toàn bộ sản phẩm khớp với thiết kế vận hành dự án: dự án có **năm giai đoạn** với cổng duyệt kế hoạch bắt
buộc, đầu việc chuẩn hoá qua **năm cổng chặn**, đầu ra cần **hai chữ ký** (Trưởng dự án và người chủ đã cấp
agent) kèm công tắc tự động công nhận, gói tin đánh thức **lõi bốn phần cộng phần riêng theo loại lời gọi**
với gộp lời gọi bền, **nhịp điều phối có kiểm soát** cho Trưởng dự án, và một **lưới an toàn** sáu động cơ
đẩy với thang phục hồi ba mức.

Khảo sát mã hiện tại ([research.md](./research.md)) cho ra bức tranh: **22 yêu cầu đã đúng, 20 có một phần
hoặc lệch, 42 chưa có**. Phần lõi đầu việc gần như đã đúng và là nền tốt; toàn bộ **tầng điều phối** chưa tồn
tại. Cách làm: giữ và tái dùng những gì đã đúng (luật kích hoạt dự án, bốn cổng, khuôn vòng lặp nền, sổ đăng
ký adapter), siết ba chỗ đang cho phép đúng điều đặc tả cấm, và dựng mới tầng điều phối theo sáu đợt bám
đúng thứ tự ưu tiên của sáu câu chuyện.

## Bối cảnh kỹ thuật

**Ngôn ngữ**: Python 3.12 (máy chủ) · TypeScript 5.9 + React 19 (giao diện)

**Phụ thuộc chính**: FastAPI 0.131 · SQLAlchemy 2.0 bất đồng bộ · Pydantic 2.12 · Alembic · Vite 7 ·
Tailwind 3.4 · i18next 26

**Lưu trữ**: PostgreSQL

**Kiểm thử**: pytest (41 tệp ở phần máy chủ) · bộ kiểm riêng của gói lớp trung gian · Playwright lái giao
diện thật

**Nền chạy**: máy chủ Linux trong docker compose + trình duyệt; giao diện cổng 3000, máy chủ cổng 8080

**Loại dự án**: ứng dụng web — máy chủ và giao diện tách riêng, cộng một gói lớp trung gian

**Mục tiêu hiệu năng**: vòng quét canh gác mỗi 60 giây trên toàn bộ đầu việc chưa đóng; nhịp điều phối mỗi 15
phút mỗi dự án và **bỏ qua trong im lặng** khi không có điểm treo; sự kiện đẩy tới giao diện tức thời

**Ràng buộc**: Kiến trúc sạch — tầng nghiệp vụ không biết gì về khung nền hay cơ sở dữ liệu; không thêm phụ
thuộc hạ tầng mới (không bộ lập lịch ngoài, không hàng đợi tác vụ); mọi ngưỡng thời gian là thiết lập chỉnh
được, không đóng cứng

**Quy mô**: nhiều workspace, mỗi workspace nhiều dự án, mỗi dự án hàng chục tới hàng trăm đầu việc và nhiều
agent ngủ–thức liên tục

## Kiểm tra Hiến pháp

*Cổng: phải qua trước Giai đoạn 0, kiểm lại sau Giai đoạn 1.*

| Nguyên tắc | Trước thiết kế | Sau thiết kế |
|---|---|---|
| **I. Đa tenant nghiêm ngặt** | Đạt — luật đã chạy, truy cập chéo trả *không tìm thấy* | **Đạt** — hai kênh sự kiện mới và hộp thư đều giới hạn theo workspace (FR-081) |
| **II. Cổng Done** | Đạt — cổng bằng chứng đã cưỡng chế | **Đạt và siết chặt hơn** — bỏ đường *đang làm → xong* đang cho phép lách cổng |
| **III. Trung lập adapter** | Đạt — sổ đăng ký adapter, tầng nghiệp vụ không nhánh theo loại agent | **Đạt** — không lối vào mới nào nhận hay trả thứ đặc thù một runtime |
| **IV. Đẩy, không hỏi vòng** | Đạt — hai kênh sự kiện đã chạy | **Đạt** — thêm kênh dự án và kênh người chủ thay vì cho giao diện hỏi vòng hộp thư |
| **V. Góc nhìn dự án** | Đạt — danh bạ và vai lấy theo ghế trong dự án | **Đạt** — Bối cảnh, kế hoạch, ngưỡng, công tắc tự động đều ở cấp dự án |
| **VI. Tiếng Việt cho người dùng** | Đạt | **Đạt** — mặt giao tiếp trả mã lỗi và tham số, giao diện dựng câu qua cơ chế đa ngôn ngữ |

**Không có vi phạm nào cần giải trình.** Bảng Theo dõi độ phức tạp để trống.

Một điểm đáng nêu: thiết kế này **củng cố** Hiến pháp ở hai chỗ đang hở — cổng Done bị lách qua đường
*đang làm → xong*, và luật "không nghĩ hộ" bị mờ vì cờ `require_approval_for_done` khai báo rồi bỏ đó.

## Cấu trúc

### Tài liệu của tính năng này

```text
specs/001-van-hanh-du-an/
├── spec.md              # Đặc tả (84 yêu cầu)
├── plan.md              # Tệp này
├── research.md          # Giai đoạn 0 — khảo sát mã hiện tại
├── data-model.md        # Giai đoạn 1 — thực thể, trường, chuyển trạng thái, di trú
├── contracts/           # Giai đoạn 1 — hợp đồng giao diện
│   ├── README.md
│   ├── user-surface.md
│   ├── agent-surface.md
│   └── push-events.md
├── quickstart.md        # Giai đoạn 1 — kịch bản kiểm chứng chạy thật
└── checklists/
    └── requirements.md
```

### Mã nguồn

```text
backend/armarius/
├── domain/
│   ├── entities/        # project, task, seat_grant, run, wakeup + [mới] plan, context,
│   │                    #   approval, push_reason, inbox_item, task_log
│   └── services/        # project_rules, wake_policy, wake_prompt, liveness_fsm
│                        #   + [mới] plan_gate, approval_rules, push_reason_rules,
│                        #     orchestration_cadence, escalation
├── application/
│   ├── ports/           # adapter, event_bus, liveness_probe + [mới] cổng cho hộp thư
│   └── use_cases/       # projects, tasks, wake_engine, liveness_watchdog
│                        #   + [mới] plans, approvals, inbox, stall_watchdog, orchestrator
├── infrastructure/
│   ├── persistence/     # models, mappers, repositories — mở rộng cho thực thể mới
│   ├── alembic/versions/# các bản di trú theo từng đợt
│   └── events/          # kênh sự kiện — thêm kênh dự án và kênh người chủ
└── presentation/api/    # projects, tasks, agent + [mới] plans, approvals, inbox

frontend/src/
├── pages/               # ProjectBoard, Inbox, CollaborationRoom — sửa nặng
│                        #   + [mới] trang kế hoạch và cổng duyệt
├── components/          # thẻ việc (cờ đình trệ), ô công nhận, công tắc tự động
├── lib/                 # mappers, sse — thêm hai kênh mới
└── i18n/                # vi.ts, en.ts — chuỗi mới, tiếng Việt đủ dấu

mcp/                     # gói riêng, bộ kiểm riêng — chạy khi đổi lược đồ đầu việc
```

**Quyết định về cấu trúc**: giữ nguyên bốn tầng Kiến trúc sạch đang có. Luật thuần (quyết định không cần
đọc/ghi) đặt ở `domain/services` để kiểm thử được bằng hàm thuần — đúng khuôn `project_rules` và
`wake_policy` đang chạy. Hai vòng lặp nền mới đi theo khuôn `LivenessWatchdog`: một lớp có khởi động/dừng gắn
vòng đời ứng dụng, thân vòng gọi được riêng để kiểm thử với đồng hồ cố định.

## Chia đợt

42 yêu cầu chưa có, chạm cả bốn tầng. Không làm một mạch. Sáu đợt bám đúng thứ tự sáu câu chuyện; **mỗi đợt
là một nhánh, một PR, dừng chờ người chủ duyệt**.

| Đợt | Câu chuyện | Nội dung | Yêu cầu | Phụ thuộc |
|---|---|---|---|---|
| **1** | 1 (P1) | Năm giai đoạn, Bối cảnh có phiên bản, bản kế hoạch, cổng duyệt bắt buộc | FR-001…014 | — |
| **2** | 2 (P1) | Siết đầu việc: cổng mô tả, bỏ lối tắt, lý do bắt buộc, danh sách tiêu chí, mở khoá tự động, nhật ký theo đầu việc, gỡ đường thợ tự nhận | FR-015…032, FR-072 | Đợt 1 (cần hạng mục để biết "trong khuôn") |
| **3** | 3 (P2) | Hai chữ ký, người cấp trên ghế, công tắc tự động, hộp thư thật | FR-033…043, FR-077 | Đợt 2 |
| **4** | 4 (P2) | Gói tin lõi bốn phần kèm Bối cảnh đã duyệt cộng phần riêng theo loại lời gọi, gộp lời gọi bền ở tầng lưu trữ, bổ sung cớ đánh thức và cưỡng chế hai danh sách cớ | FR-044…051 | Đợt 1 (cần Bối cảnh) |
| **5** | 5 (P3) | Nhịp điều phối có kiểm soát | FR-052…055 | Đợt 4 |
| **6** | 6 (P3) | Động cơ đẩy, cờ đình trệ, thang ba mức, nhắc chủ ba bậc, xếp hàng, khôi phục | FR-056…069, FR-075, FR-076 | Đợt 3, 5 |

Bảy yêu cầu nền (FR-078 → FR-084) không thành đợt riêng — chúng là ràng buộc mọi đợt phải giữ, kiểm ở mục
Hiến pháp trong [quickstart.md](./quickstart.md).

**Một điều chỉnh sau bước soi chéo (2026-07-31)**: thực thể *mục hộp thư* và *nhật ký thay đổi đầu việc* dời
lên **giai đoạn nền chung** thay vì nằm trong Đợt 3 — vì Đợt 1 đã cần chỗ đặt mục chờ duyệt kế hoạch và Đợt 2
cần chỗ đặt mục chờ duyệt đầu việc ngoài khuôn. Đợt 3 giữ phần khó thật của nó: định tuyến theo người cấp
agent, công tắc tự động, bậc nhắc. Chi tiết trong [tasks.md](./tasks.md).

**Đợt 1 và 2 là mốc dùng được đầu tiên**: sau hai đợt này, một dự án đã chạy đúng vòng thiết lập → lập kế
hoạch → duyệt → vận hành với đầu việc không còn lối tắt nào. Đó là lát cắt nhỏ nhất mà người chủ thấy được
giá trị.

## Ba điểm phải nói trước

1. **Siết bảng chuyển trạng thái là thay đổi phá vỡ tương thích.** Bỏ *đang làm → xong* sẽ làm đỏ một số bài
   kiểm hiện có và có thể chặn thói quen đang dùng. Đây là đỏ đúng — sửa bài kiểm theo luật mới, không nới
   luật cho bài kiểm xanh. Phải rà dữ liệu thật trước khi siết.

2. **Ghế cũ không biết ai đã cấp.** Cơ chế hai chữ ký cần dữ liệu này. Bản di trú sẽ lấp bằng người tạo dự
   án và ghi rõ đây là suy đoán, không phải sự thật lịch sử.

3. **Gói riêng của lớp trung gian có bộ kiểm thử riêng.** Đợt 2 và 3 đổi lược đồ đầu việc và mặt giao tiếp
   nên bắt buộc chạy bộ kiểm của gói đó, không chỉ bộ của phần máy chủ.

## Theo dõi độ phức tạp

Không có vi phạm Hiến pháp nào cần giải trình.
