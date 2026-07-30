# Khảo sát: Vận hành dự án tự chủ

**Giai đoạn 0** của [plan.md](./plan.md) · Đặc tả: [spec.md](./spec.md) · Ngày: 2026-07-30

Tài liệu này trả lời một câu: **84 yêu cầu trong đặc tả đối chiếu với mã đang chạy thì đứng ở đâu?** Đây là
bước bắt buộc của dự án đã có mã — không đề xuất thiết kế nào trước khi biết cái gì đã có.

## Cách khảo sát

Đọc mã qua chỉ mục CodeGraph, tập trung sáu vùng: thực thể dự án và vòng đời, thực thể đầu việc và các cổng,
bộ máy đánh thức, luật sống/chết, mặt giao tiếp với người dùng, và hạ tầng vòng lặp nền. Mọi kết luận dưới
đây trỏ tới tệp và dòng thật.

---

## 1. Bức tranh tổng thể

| Mức độ | Số yêu cầu | Nghĩa |
|---|---:|---|
| **Đã có, khớp đích** | 22 | Mã hiện tại đã làm đúng điều đặc tả đòi |
| **Có một phần hoặc lệch** | 20 | Có mầm mống nhưng thiếu hoặc làm khác |
| **Chưa có** | 42 | Không tồn tại dưới bất kỳ hình thức nào |

Điều đáng mừng: **phần lõi đầu việc gần như đã đúng**. Tám trạng thái, cổng bằng chứng, cổng phụ thuộc, chống
vòng phụ thuộc, một-người-phụ-trách, mã định danh bất biến, việc kế tiếp bền — tất cả đã chạy thật và có kiểm
thử. Đó là nền tốt.

Điều phải nói thẳng: **toàn bộ tầng điều phối chưa tồn tại**. Không có kế hoạch, không có cổng duyệt kế
hoạch, không có nhịp điều phối của Trưởng dự án, không có động cơ đẩy, không có cờ đình trệ, không có thang
phục hồi ba mức, không có hộp thư người chủ như một thực thể thật. Đây đúng là "vai quản lý bị đánh rơi" mà
sổ ghi nhớ dự án đã nêu.

---

## 2. Đối chiếu từng nhóm yêu cầu

### A. Dự án và vòng đời giai đoạn (FR-001 → FR-006)

| Yêu cầu | Hiện trạng | Nơi trong mã |
|---|---|---|
| FR-001 năm giai đoạn | **Lệch** — chỉ ba: `setup` → `active` → `archived` | `domain/entities/project.py:17` |
| FR-002 điều kiện rời thiết lập | **Đã có, khớp chính xác** — mọi ghế được cấp và mọi thợ trực tuyến | `domain/services/project_rules.py:76-102` |
| FR-003 chặn tạo đầu việc khi chưa vận hành | **Chưa có** — `TaskService.create` không đọc trạng thái dự án | `application/use_cases/tasks.py:38-81` |
| FR-004 chuyển giai đoạn | **Chưa có** | — |
| FR-005 đóng dự án dừng đánh thức | **Chưa có** | — |
| FR-006 không tự tuyên hoàn thành | **Đã đúng** (không có cơ chế nào tự tuyên) | — |

**Ghi chú quan trọng:** luật kích hoạt ở `recompute_active` là **một chiều và một lần** — một thợ rớt mạng
sau đó không kéo dự án về thiết lập. Đặc tả đồng ý với điều này (đã ghi trong Tình huống biên), nên phần này
giữ nguyên, chỉ đổi đích đến từ `active` sang *lập kế hoạch*.

Chú thích trong mã còn nói "cổng hành vi duy nhất khoá theo `active` là task commission" — nhưng commission
đã bị gỡ ở một lần di trú trước (`a1c4e8b2d6f9_drop_commission_and_idle`). Nghĩa là **hiện tại trạng thái dự
án không khoá gì cả**; chú thích đã lỗi thời.

### B. Bối cảnh dự án (FR-007 → FR-010)

`Project` đã có sẵn `objective`, `success_metrics`, `target_date`, `context` — nhưng rời rạc, do người chủ
điền lúc tạo, không phải khối do Trưởng dự án soạn qua đối thoại rồi người chủ duyệt.

Điểm hở nặng nhất: **Bối cảnh không đi vào gói tin đánh thức**. `WakeContext`
(`domain/services/wake_prompt.py:32-51`) có tên workspace, tên dự án, vai, danh bạ, tin nhắn, việc kế tiếp —
nhưng **không có Bối cảnh dự án**. Trong khi `LeaderChatContext` (`leader_chat_prompt.py:43`) thì có
`project_context`. Nghĩa là Trưởng dự án lúc trò chuyện thì biết mục tiêu chung, còn thợ lúc làm việc thì
không. Đúng cái bệnh "làm việc trong mù mờ" mà FR-009 chặn.

### C. Kế hoạch và cổng duyệt (FR-011 → FR-014)

**Chưa có gì.** Từ "plan" trong mã chỉ nói tới *kế hoạch nhân sự* (`project_rules.validate_plan` — kiểm đúng
một vai trưởng, ít nhất một vai thợ), không phải kế hoạch công việc.

### D. Bộ trường đầu việc (FR-015 → FR-021)

| Yêu cầu | Hiện trạng |
|---|---|
| FR-016 mã định danh bất biến | **Đã có** — `{KEY}-{n}`, cấp nguyên tử bằng `allocate_task_number`, không tái dùng số |
| FR-017 đúng một người phụ trách | **Đã có** — `assigned_marius_id`, mô hình nhiều-người đã gỡ |
| FR-020 việc kế tiếp bền | **Đã có** — `next_action`, trả lại kèm khi đánh thức |
| FR-015 bộ trường | **Một phần** — thiếu "người chủ chịu trách nhiệm công nhận" |
| FR-018 mô tả chi tiết bắt buộc | **Chưa có** — `description: str \| None`, không ai cưỡng chế |
| FR-019 định nghĩa hoàn thành đo được | **Lệch** — `definition_of_done: str \| None` là một chuỗi tự do, không phải danh sách tiêu chí đúng/sai. Có thực thể `checklist_item` nhưng chưa nối vào vai trò cái thước |
| FR-021 trường hệ thống chỉ đọc | **Một phần** — có mốc tạo/sửa; **không có nhật ký thay đổi theo đầu việc**. Vết hiện nay là `run_events`, gắn theo *lượt chạy*, không theo đầu việc |

### E. Vòng đời và năm cổng (FR-022 → FR-032)

Đây là vùng khớp nhất.

| Yêu cầu | Hiện trạng | Nơi trong mã |
|---|---|---|
| FR-022 tám trạng thái | **Đã có** — trùng gần như một-một | `entities/task.py:21-29` |
| FR-023 từ chối và giữ nguyên | **Đã có** | `TaskTransitionError` |
| FR-025 cổng phụ thuộc | **Đã có** | `DEPENDENCY_GATED_STATUSES` + `all_blockers_done` |
| FR-026 cổng bằng chứng | **Đã có** | `ARTIFACT_REQUIRED_STATUSES = {in_review, done}` |
| FR-028 cổng một-người | **Đã có** | một trường, không có danh sách |
| FR-032 chặn vòng phụ thuộc | **Đã có** — chặn ngay lúc tạo cạnh | `TaskService._would_cycle` |
| **FR-024 cấm lối tắt** | **LỆCH — vi phạm đặc tả** | xem dưới |
| FR-027 trong/ngoài khuôn kế hoạch | **Một phần** — có `draft` + `approve_proposed`, nhưng điều kiện là công tắc `yolo_mode` chứ không phải "trong khuôn kế hoạch" |
| FR-029 cổng mô tả | **Chưa có** |
| FR-030 lý do trạng thái bắt buộc | **Một phần** — có tham số `reason`, chưa rõ có cưỡng chế |
| FR-031 mở khoá + đánh thức khi xong | **Chưa có** — không có ai chủ động rà lại khi một việc xong |

**Vi phạm cụ thể ở FR-024.** Bảng `VALID_TRANSITIONS` (`entities/task.py:51-77`) đang cho phép:

- `in_progress → done` **thẳng** — đặc tả cấm; thợ không được tự tuyên xong mà bỏ qua rà soát.
- `done → in_progress` và `cancelled → backlog` — đặc tả coi hai trạng thái này là **đóng**, mở lại là tình
  huống đặc biệt của lưới an toàn, không phải chuyển thường ngày.
- Thiếu `draft → backlog` (đặc tả cho cất để dành một đề xuất).

### F. Công nhận đầu ra (FR-033 → FR-043)

**Gần như toàn bộ chưa có.** `Project.settings` khai báo `require_approval_for_done: False` — nhưng tra khắp
mã thì **không nơi nào đọc cờ này**. Nó là một cờ chết, khai báo rồi bỏ đó.

Ba thứ đặc tả đòi mà mã hoàn toàn không có:

1. **Ai là người chủ chịu trách nhiệm.** `SeatGrant` (`entities/seat_grant.py:26-33`) lưu dự án, khoá vai,
   agent, trạng thái, mốc cấp — **không lưu ai đã cấp**. Không có dữ liệu này thì không thể định tuyến đầu
   ra về đúng hộp thư.
2. **Công tắc tự động công nhận theo người chủ.** Có `yolo_mode` nhưng nó ở cấp dự án (một công tắc chung),
   và nó chi phối *việc tạo đầu việc*, không phải *việc công nhận đầu ra*.
3. **Vòng công nhận hai chữ ký.** Hiện `in_review → done` là một bước, ai gọi cũng được.

### G. Gói tin đánh thức và điều phối lời gọi (FR-044 → FR-051)

Gói tin hiện có **sáu trên tám phần**: vai, đầu việc kèm mô tả và trạng thái, lý do gọi dậy (viết thành câu
người đọc hiểu — đã đúng FR-046), danh bạ đồng đội kèm trạng thái sống, tin nhắn mới, việc kế tiếp. Thiếu:
**Bối cảnh dự án**, và **nơi nộp thành phẩm** chỉ nằm lẫn trong đoạn hướng dẫn chứ không phải một mục riêng.

FR-045 (phần rỗng ghi rõ "không có") **chưa có**: `build_wake_prompt` bỏ qua im lặng mọi mục rỗng.

**Gộp lời gọi trùng (FR-050) có nhưng mong manh.** `WakeEngine._active` là một từ điển **trong tiến trình**
(`wake_engine.py:69`) khoá theo `(marius_id, task_id)`. Nó đúng logic, nhưng:

- Mất sạch khi tiến trình khởi động lại → hai lượt chạy song song cho cùng một đầu việc là chuyện có thể xảy ra.
- Không dùng được khi chạy nhiều bản sao tiến trình.
- Cơ sở dữ liệu **đã có** `WakeupStatus.COALESCED` để ghi vết, nhưng quyết định gộp thì không đọc từ đó.

Hai bảng đánh thức (FR-047, FR-048) có một phần: `WakeSource` đã có `assignment`, `mention`, `comment`,
`on_demand`, `continuation`, `nudge`, `leader_chat`. Thiếu hẳn: nhịp điều phối, và đánh thức Trưởng dự án khi
một đầu việc chuyển sang *chờ rà soát* hoặc *xong*.

### H. Nhịp điều phối của Trưởng dự án (FR-052 → FR-055)

**Chưa có gì.** Trưởng dự án hiện đúng là "đồng hồ mù" theo nghĩa ngược lại — nó thậm chí không có đồng hồ,
chỉ phản ứng khi người chủ nhắn trong khung chat.

### I. Lưới an toàn (FR-056 → FR-069)

| Yêu cầu | Hiện trạng |
|---|---|
| FR-056 động cơ đẩy sáu loại | **Chưa có** — không có khái niệm này |
| FR-057 vòng quét canh gác | **Hạ tầng đã có, nội dung chưa** — `LivenessWatchdog` là đúng khuôn một vòng lặp nền có vòng đời gắn với ứng dụng, thân vòng gọi được riêng để kiểm thử. Tái dùng được |
| FR-058 cờ đình trệ | **Chưa có** |
| FR-059 thang ba mức | **Một phần** — `decide_self_wake` + `max_continuation_attempts=3` là Mức 1; `escalate_to_human` là mầm Mức 3. **Mức 2 (Trưởng dự án quyết) không tồn tại** |
| FR-060 trần và đặt lại bộ đếm | **Một phần** — có `continuation_attempt`, **không đặt lại về không khi có tiến triển thật** |
| FR-061 hồ sơ đã thử | **Chưa có** |
| FR-062 báo sống, nghi treo, tuyên treo | **Một phần** — luật sống/chết có `turn_started_at`, trạng thái `HUNG`, và một bộ đếm giờ. Nhưng khi tuyên treo, **đầu việc không bị kéo về trạng thái làm được** và người phụ trách không được gọi lại theo việc kế tiếp |
| FR-063 thử lại giãn dần, tuyên ngoại tuyến | **Một phần** — có `ONLINE → CHECKING → OFFLINE` |
| FR-064 thợ ngoại tuyến thì đầu việc bị chặn | **Chưa có** |
| FR-065 nhắc người chủ ba bậc | **Chưa có** |
| FR-066 chạy tiếp nhánh độc lập khi chờ chủ | **Chưa có** |
| FR-067 xếp hàng tranh chấp thợ/tài nguyên | **Chưa có** |
| FR-068 dựng lại động cơ sau khởi động lại | **Chưa có** |
| FR-069 mất thành phẩm | **Chưa có** |

### J. Ranh giới vai trò (FR-070 → FR-076)

| Yêu cầu | Hiện trạng |
|---|---|
| FR-070 người chủ can thiệp trực tiếp | **Đã có** — mặt giao tiếp cho người dùng đủ đầy |
| FR-073 hệ thống không quyết thay | **Đã đúng** — bộ não tất định của khâu mời agent đã bị xoá từ trước |
| **FR-072 cấm thợ tự nhận việc** | **LỆCH** — `TaskService.claim` cho agent tự gán mình vào một đầu việc rồi bắt tay luôn (`tasks.py:174-190`). Đặc tả cấm thẳng |
| FR-071 cấm vượt cấp | **Một phần** |
| FR-075 thay đổi lớn treo chờ duyệt | **Chưa có** |
| FR-076 chuyển tiếp sạch khi tái hoạch định | **Chưa có** |

### K. Hiển thị, ghi vết, ràng buộc nền (FR-077 → FR-084)

| Yêu cầu | Hiện trạng |
|---|---|
| FR-080 đẩy không hỏi vòng | **Đã có** — dòng sự kiện máy chủ đã chạy hai kênh (theo lượt chạy và theo đầu việc) |
| FR-081 đa tenant | **Đã có** — `get_in_workspace` trả "không tìm thấy" cho truy cập chéo |
| FR-082 góc nhìn dự án | **Đã có** — danh bạ lấy theo ghế trong dự án, vai lấy từ khoá vai của ghế |
| FR-083 trung lập adapter | **Đã có** — sổ đăng ký adapter, tầng nghiệp vụ không nhánh theo loại agent |
| FR-084 tiếng Việt qua đa ngôn ngữ | **Đã có** |
| FR-078 chat và bảng dự án | **Đã có** |
| **FR-077 hộp thư người chủ** | **Một phần yếu** — trang hộp thư ở giao diện chỉ lọc đầu việc theo trạng thái *ở phía trình duyệt* (`in_review`, `blocked`). Không có thực thể mục hộp thư, không có bậc nhắc, không gom được kế hoạch chờ duyệt hay cảnh báo leo thang |
| FR-079 ghi vết | **Một phần** — vết bám theo *lượt chạy*, không có nhật ký theo đầu việc như FR-021 đòi |

---

## 3. Các quyết định thiết kế

### QĐ-1: Mở rộng vòng đời dự án tại chỗ, không dựng thực thể mới

**Chọn**: thêm hai giá trị `planning` và `maintain` vào vòng đời hiện có, đổi tên `archived` thành `closed`
về mặt ngữ nghĩa (giữ giá trị cũ để khỏi phá dữ liệu, hoặc di trú một lần).

**Lý do**: luật kích hoạt ở `project_rules` đã đúng và đã có kiểm thử; chỉ cần đổi đích đến. Dựng một thực
thể vòng đời riêng sẽ tách rời khỏi luật đang chạy.

**Đã cân nhắc và bỏ**: một bảng chuyển giai đoạn riêng — thừa cho năm trạng thái.

### QĐ-2: "Người chủ chịu trách nhiệm" lưu trên ghế, không lưu trên đầu việc

**Chọn**: thêm `granted_by_user_id` vào ghế. Người phải ký cho một đầu ra được **suy ra** từ ghế của người
phụ trách, không sao chép sang từng đầu việc.

**Lý do**: một nguồn sự thật. Nếu chép sang đầu việc thì khi ghế đổi chủ, các đầu việc cũ trỏ sai.

**Đã cân nhắc và bỏ**: lưu thẳng trên đầu việc — nhanh hơn khi đọc nhưng sinh dữ liệu lệch. Nếu sau này đọc
chậm thì thêm chỉ mục, không sao chép.

### QĐ-3: Hộp thư người chủ là một thực thể thật, không phải bộ lọc phía trình duyệt

**Chọn**: dựng thực thể *mục hộp thư* ở tầng nghiệp vụ, mang loại (chờ duyệt kế hoạch, chờ trả lời, chờ công
nhận, cảnh báo leo thang), người nhận, đầu việc hoặc dự án liên quan, bậc nhắc đã gửi, mốc giải quyết.

**Lý do**: ba yêu cầu bắt buộc nó — nhắc ba bậc cần biết đã nhắc mấy lần (FR-065); định tuyến theo người chủ
cần biết ai nhận (FR-035); leo thang Mức 3 cần chỗ đặt hồ sơ đã thử (FR-061). Bộ lọc phía trình duyệt không
làm được cái nào.

### QĐ-4: Động cơ đẩy là một trường suy ra, kiểm bởi vòng quét — không phải trạng thái người dùng đặt

**Chọn**: mỗi lần đầu việc đổi trạng thái hoặc có sự kiện, hệ thống tính lại động cơ đẩy và mốc hết hạn của
nó. Vòng quét chỉ so mốc hết hạn với hiện tại, không suy luận lại từ đầu.

**Lý do**: giữ vòng quét rẻ và tất định. Nếu vòng quét phải suy ra động cơ từ nhiều nguồn mỗi lần thì nó sẽ
nặng và khó kiểm thử.

**Đã cân nhắc và bỏ**: tính động cơ ngay trong vòng quét — đơn giản hơn nhưng chi phí tăng theo số đầu việc
và khó viết kiểm thử tất định.

### QĐ-5: Tái dùng khuôn vòng lặp nền đã có, thêm một vòng quét thứ hai

**Chọn**: dựng vòng quét canh gác theo đúng khuôn `LivenessWatchdog` — một lớp có `start`/`stop` gắn vào
vòng đời ứng dụng, thân vòng gọi được riêng để kiểm thử với đồng hồ cố định.

**Lý do**: khuôn đó đã chứng minh chạy được và kiểm thử được. Không thêm phụ thuộc mới (không bộ lập lịch
ngoài, không hàng đợi tác vụ).

**Đã cân nhắc và bỏ**: một bộ lập lịch bên ngoài — thêm một thành phần hạ tầng cho một nhu cầu mà vòng lặp
trong tiến trình đã đủ, và trái tinh thần giữ hệ đơn giản.

### QĐ-6: Gộp lời gọi trùng chuyển từ bộ nhớ tiến trình sang cơ sở dữ liệu

**Chọn**: bất biến "tối đa một lệnh treo và một lượt chạy cho mỗi cặp agent–đầu việc" cưỡng chế bằng ràng
buộc duy nhất ở tầng lưu trữ, không bằng từ điển trong tiến trình.

**Lý do**: FR-050 và FR-068 cùng đòi điều này. Bộ nhớ tiến trình mất khi khởi động lại — đúng lúc cần nhất.

### QĐ-7: Định nghĩa hoàn thành nâng từ chuỗi tự do lên danh sách tiêu chí

**Chọn**: mỗi tiêu chí là một dòng có nội dung, trạng thái đạt/chưa, và trỏ tới bằng chứng. Thực thể
`checklist_item` đang có được nối vào vai trò này thay vì dựng mới.

**Lý do**: FR-019 đòi "đúng/sai kiểm được"; một chuỗi tự do không chấm được. Việc công nhận phải là thao tác
đối chiếu từng dòng, không phải đọc cảm tính.

### QĐ-8: Gỡ `claim`, siết bảng chuyển trạng thái

**Chọn**: bỏ đường cho thợ tự nhận việc; bỏ `in_progress → done`; đưa `done → in_progress` và
`cancelled → backlog` ra khỏi đường thường ngày, chỉ mở qua một thao tác mở lại có ghi vết.

**Lý do**: ba chỗ này đang cho phép chính xác những gì đặc tả cấm. Để nguyên thì cổng công nhận hai chữ ký
vô nghĩa — ai cũng có đường vòng.

**Rủi ro**: `claim` có thể đang được dùng bởi công cụ phía agent. Phải rà trước khi gỡ, và nếu có thì thay
bằng "xin nhận việc" đi qua Trưởng dự án.

---

## 4. Rủi ro và điểm cần chú ý

1. **Đây là một khối việc lớn.** 42 yêu cầu chưa có, chạm cả tầng nghiệp vụ, tầng lưu trữ, mặt giao tiếp và
   giao diện. Không nên làm một mạch — phần chia đợt nằm trong [plan.md](./plan.md).
2. **Siết bảng chuyển trạng thái là thay đổi phá vỡ tương thích.** Dữ liệu đang có thể chứa đầu việc đi qua
   `in_progress → done`. Phải rà dữ liệu thật trước khi siết, và kiểm thử hiện tại sẽ đỏ ở vài chỗ — đó là
   đỏ đúng, không phải hỏng.
3. **Gói riêng của lớp trung gian có bộ kiểm thử riêng.** Đổi lược đồ đầu việc hoặc mặt giao tiếp là phải
   chạy bộ kiểm thử của gói đó, không chỉ bộ của phần máy chủ.
4. **Cờ chết `require_approval_for_done`.** Khi dựng cơ chế hai chữ ký thì phải quyết: gỡ hẳn cờ này hay
   dùng lại nó. Để cả hai song song là sinh ra hai luật mâu thuẫn.
5. **Ghi vết theo đầu việc chưa có.** Vết hiện bám theo lượt chạy. Nhiều yêu cầu (FR-021, FR-039, FR-061,
   FR-079) cùng cần một nhật ký theo đầu việc — nên dựng một lần cho cả nhóm, không vá lẻ.
6. **Số ngưỡng phải chỉnh được.** Người chủ đã chốt bộ số, nhưng đặc tả ghi rõ mọi ngưỡng là thiết lập, không
   đóng cứng trong mã.
