# Dòng sự kiện đẩy

Một chiều, máy chủ đẩy về trình duyệt. Hiến pháp IV cấm giao diện hỏi vòng để biết trạng thái.

Hai kênh đã chạy: theo **lượt chạy** và theo **đầu việc**. Cần thêm hai kênh phạm vi rộng hơn.

| Kênh | Trạng thái | Ai nghe |
|---|---|---|
| Theo lượt chạy | **[có]** | Màn hình theo dõi một lượt agent chạy |
| Theo đầu việc | **[có]** | Phòng cộng tác của một đầu việc |
| Theo workspace | **[có]** | Thanh trên cùng, danh bạ agent, trang chi tiết một agent |
| **Theo dự án** | **[mới]** | Bảng dự án — đổi giai đoạn, đổi trạng thái đầu việc, cờ đình trệ |
| **Theo người chủ** | **[mới]** | Hộp thư — mục mới, mục được giải quyết, lời nhắc |

## Sự kiện cần thêm

### Kênh dự án

| Sự kiện | Khi nào | Mang theo |
|---|---|---|
| `project.phase_changed` | Dự án đổi giai đoạn | Giai đoạn trước, sau, ai quyết |
| `plan.submitted` | Trưởng dự án trình kế hoạch | Phiên bản kế hoạch |
| `plan.decided` | Người chủ quyết ở cổng duyệt | Duyệt, yêu cầu chỉnh, hay hỏi lại |
| `task.created` | Một đầu việc vừa được tạo | Mã đầu việc, trạng thái ban đầu |
| `task.status_changed` | Mọi lần đổi trạng thái | Mã đầu việc, trước, sau, lý do |
| `task.stalled` | Nổi hoặc gỡ cờ đình trệ | Mã đầu việc, lý do mất động cơ |
| `task.unblocked` | Một đầu việc xong, mở khoá việc phụ thuộc | Danh sách mã vừa mở khoá |
| `signature.recorded` | Một chữ ký được ghi | Loại người ký, kết quả, có phải ký tự động không |
| `orchestration.swept` | Xong **mỗi** lượt rà của nhịp điều phối, kể cả lượt không thấy gì | Mốc rà, số điểm treo, có gọi Trưởng dự án không |

`task.created` thêm ở T175. Bảng cũ chỉ có *"mọi lần đổi trạng thái"*, mà một đầu việc mới **không đổi
trạng thái** — nó xuất hiện. Nên bảng dự án đang mở đứng im cho tới khi có người tải lại trang, và đứng im
thì nhìn giống hệt một dự án đang yên. Cái mà người xem cần biết là **thứ được vẽ trên màn hình vừa đổi**,
không phải *"trạng thái vừa đổi"* — hai câu đó chỉ trùng nhau cho tới lần đầu có thứ được vẽ mà không đi
qua một lần đổi trạng thái nào.

Lượt rà không thấy gì **vẫn phải bắn**. Khối "lượt rà gần nhất" trên bảng dự án sinh ra để phân biệt *dự án
đang yên* với *vòng điều phối đã chết*, mà hai thứ đó nhìn giống hệt nhau nếu chỉ có lượt rà thấy-việc mới
lên tiếng. Thiếu sự kiện này thì bảng chỉ còn một cách giữ khối đó đúng: hỏi lại theo đồng hồ — đúng thứ
Hiến pháp IV cấm, và đúng thứ nó đã làm trước Đợt 9.

### Kênh workspace

| Sự kiện | Khi nào | Mang theo |
|---|---|---|
| `run.status_changed` | Một lượt chạy đổi trạng thái: mở, bắt đầu, kết thúc, bị dừng giữa chừng, bị tuyên treo | Mã lượt chạy, mã agent, mã đầu việc, mã dự án, trạng thái mới |
| `marius.offline` | Một agent tụt qua ngưỡng im lặng thành đã tắt | Mã agent |

`marius.offline` là cặp còn thiếu của `marius.online` đã có sẵn. Chiều sống lại vẫn báo, chiều
tắt hẳn thì không — nên chấm sống/chết trên màn hình chỉ đi được một chiều, và chiều nó không đi
được lại đúng là chiều người dùng cần biết. Phần xử lý agent tắt vốn được viết để **cứu đầu việc
đang rơi dở**; báo cho người đang ngồi nhìn chưa bao giờ nằm trong phạm vi của nó.

Cả hai tin đều **cố tình không mang trạng thái** — chúng là tín hiệu, theo nguyên tắc 1 dưới đây.
Người nghe đọc lại agent chứ không đọc nội dung tin. Nhét trạng thái vào cho tiện là biến dòng sự
kiện thành nguồn sự thật, và khi tin rơi khỏi cửa sổ gửi bù thì màn hình sai mà không ai biết.

Đây là kênh duy nhất trả lời được câu **"agent này có gì mới không?"**. Hai kênh cũ đều đòi
người nghe biết trước mình cần nghe cái gì: kênh lượt chạy phải có mã lượt chạy, kênh đầu việc
phải có mã đầu việc. Trang chi tiết một agent không có cả hai — nó nhìn theo *agent* — nên trước
Đợt 9 nó hỏi lại máy chủ mỗi 15 giây, đúng thứ Hiến pháp IV cấm.

Phải bắn ở **cả năm** chỗ đổi trạng thái, không phải chỉ chỗ dễ thấy. Hai chỗ không có ai bấm gì
mà trạng thái vẫn đổi — máy chủ dừng giữa lượt chạy, và người canh gác tuyên một lượt chạy là
treo — chính là hai chỗ mà thiếu tin báo thì màn hình quay mãi. Bốn trên năm cũng bằng không:
người dùng không biết mình đang nhìn một ô đã chết.

### Kênh người chủ

| Sự kiện | Khi nào | Mang theo |
|---|---|---|
| `inbox.item_added` | Một mục chờ xuất hiện | Loại, dự án, đầu việc liên quan |
| `inbox.item_resolved` | Mục được xử lý | Định danh mục |
| `inbox.reminded` | Một bậc nhắc được gửi | Định danh mục, bậc thứ mấy |
| `escalation.level_3` | Một việc leo lên người chủ | Hồ sơ đã thử, điều cần quyết |

## Nguyên tắc

1. **Sự kiện là tín hiệu, không phải nguồn sự thật.** Trình duyệt nhận sự kiện rồi đọc lại phần dữ liệu cần;
   không dựng trạng thái chỉ từ dòng sự kiện.
2. **Mất kết nối phải bù được.** Mỗi sự kiện mang số thứ tự để nối lại sau khi đứt, theo đúng cách kênh đầu
   việc đang làm.
3. **Giới hạn theo workspace.** Người nghe chỉ nhận sự kiện của workspace mình; không rò rỉ sự tồn tại của
   dự án thuộc workspace khác.
4. **Không đẩy nội dung nhạy cảm.** Sự kiện mang định danh và nhãn, không mang toàn văn thành phẩm.

## Đổi tên sự kiện (2026-08-13)

Mười sáu tên sự kiện vốn viết bằng tiếng Việt không dấu. Chúng nằm giữa hai lối: không phải tiếng Anh như
mọi định danh khác trong mã, mà cũng không phải tiếng Việt thật vì mất dấu — thành ra kho có ba lối đặt tên
thay vì hai. Nay theo đúng lối các sự kiện tiếng Anh đã có sẵn (`marius.online`, `workspace_agent.designated`).

Kênh sự kiện chạy hoàn toàn trong bộ nhớ nên **không phải chuyển dữ liệu**; khởi động lại là xong.

| Tên cũ | Tên mới |
|---|---|
| `boi-canh.trinh` | `context.submitted` |
| `boi-canh.quyet` | `context.decided` |
| `cong-nhan.ky` | `signature.recorded` |
| `dau-viec.tao-moi` | `task.created` |
| `dau-viec.doi-trang-thai` | `task.status_changed` |
| `dau-viec.dinh-tre` | `task.stalled` |
| `dau-viec.mo-khoa` | `task.unblocked` |
| `du-an.doi-giai-doan` | `project.phase_changed` |
| `hop-thu.muc-moi` | `inbox.item_added` |
| `hop-thu.da-giai-quyet` | `inbox.item_resolved` |
| `hop-thu.nhac` | `inbox.reminded` |
| `ke-hoach.trinh` | `plan.submitted` |
| `ke-hoach.quyet` | `plan.decided` |
| `leo-thang.muc-3` | `escalation.level_3` |
| `luot-chay.doi-trang-thai` | `run.status_changed` |
| `nhip-dieu-phoi.quet` | `orchestration.swept` |

Giao diện so **tiền tố** ở ba chỗ, không so tên đầy đủ — `plan.`, `context.`, `orchestration.`. Đây là chỗ
dễ sót nhất khi đổi tên: tìm theo tên đầy đủ sẽ không thấy chúng.
