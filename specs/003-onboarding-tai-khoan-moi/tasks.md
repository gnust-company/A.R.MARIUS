# Tasks: Ba bước đầu tiên của một tài khoản mới, và người chủ nhà của không gian làm việc

**Đặc tả**: [`spec.md`](./spec.md) · **Nhánh**: `038-onboarding-tai-khoan-moi` (backend), `039-…` (giao diện)

Hai đợt, và thứ tự không đổi được: giao diện ba bước không có gì để gọi nếu backend chưa có cửa.

---

## Phase 1 — Backend: người chủ nhà, và những cửa ba bước cần (đợt 1)

- [x] T001 `PATCH /auth/me` cho người dùng đổi **tên hiển thị của chính mình** (FR-101). Hôm nay có `GET /auth/me` và **không có cửa nào sửa** — tên nhập lúc đăng ký là tên vĩnh viễn. Chỉ `full_name`; email, mật khẩu, vai đều không nằm ở đây. Mọi trường đều tuỳ chọn và chỉ thứ được gửi mới bị chạm: một màn hình lưu một ô không được phải gửi lại cả phần còn lại, vì client dựng lại cả đối tượng là client âm thầm xoá thay đổi vừa làm ở tab khác. *Đo trên dịch vụ thật*: đổi tên xong đọc lại vẫn còn; gửi riêng `onboarding_step` không xoá tên; bước ngoài 0–3 và tên rỗng đều 422.
- [x] T002 Một cửa **có tên riêng** tạo người chủ nhà **chưa được đặt chỗ** (FR-110, FR-114, FR-115). KHÔNG nới `create(...)` bằng cách cho `placement_id` một mặc định: docstring của chính nó nói *"A default would quietly reintroduce the state this requirement exists to abolish"*, và nói đúng. Gọi từ chỗ tạo không gian làm việc, cho **mọi** không gian làm việc mới, kể cả cái tạo lúc đăng ký. Chỉ dẫn bằng tiếng Anh; tên `Livia` là chuỗi hiển thị. Trùng tên phải lách được, và nhánh này KHÔNG ĐƯỢC làm việc tạo không gian làm việc thất bại (FR-113). Đặt tên là `provide_host`; `ensure_workspace_agent` vẫn chỉ-tra-cứu như #63 chốt.

  **Ba chốt Hiến pháp trong bộ kiểm bắt tôi liên tiếp, và cả ba đều đúng** — đây là phần đáng ghi nhất của task này, vì mỗi lần bị bắt là một lần thiết kế của tôi bị đẩy về chỗ đúng hơn:
  1. *"Chỉ có đúng một đường tạo agent, và nó ở `enrollment.py`"*. Tôi dựng `Marius` ngay trong `workspace_agent.py` — đúng đường thứ hai mà chốt ấy sinh ra để chặn, và lời nhắc của nó viết rằng lần trước một đường như thế nằm đó cả tháng không ai thấy. Chuyển việc dựng về `enrollment.py` thành `create_unplaced`, đặt ngay cạnh `create`: như vậy ngoại lệ của FR-007f **nằm cạnh chính luật nó trừ ra**, ai đọc tệp ấy thấy hết mọi đường một agent ra đời — đúng ý chốt, và tốt hơn cách tôi làm ban đầu.
  2. *"Tạo agent không được đẻ ra vai"* (Điều V, FR-007l). Tôi truyền `role=` vào lúc tạo. Bỏ hẳn tham số ấy; vai do `designate` đặt, và đó vẫn là đường hợp lệ. Nhưng bỏ nó sinh ra một cửa sổ thật: tạo và ngồi ghế nay là **hai** lần commit, chết ở giữa để lại một con không ai trỏ tới, và lần gọi sau sẽ đẻ thêm `Livia 2`. Nên `provide_host` **nhận lại con dựng dở** thay vì đẻ thêm, theo một luật không thể nhầm: tên ấy, không vai, và **không có chỗ làm** — người dùng không tạo được agent thiếu chỗ làm (cửa ấy đòi có, không mặc định), và chỗ làm không bao giờ bị lấy đi khỏi một agent.
  3. *"Tầng nghiệp vụ không được nhánh mã theo loại agent"* (Điều III, FR-083). Luật nhận-lại bản đầu của tôi đọc `adapter_type == ""`. Đổi sang hỏi chính placement — *agent này có chỗ làm chưa* — vì đó là câu hỏi thuộc tầng ấy, và `NOT_PLACED` đã có nghĩa sẵn. `adapter_type` để rỗng — đó chính là hình dạng của *chưa được đặt chỗ*, và đoán một giá trị ở đó là tầng nghiệp vụ tự đặt tên một runtime (Điều III). *Đo*: 5 bài đơn vị (tạo ra chưa đặt chỗ và giữ ghế; gọi hai lần không ra hai con; không gian làm việc đã có chủ nhà thì giữ nguyên của họ; tên `Livia` bị dùng thì lách sang tên khác) + 2 bài qua cửa HTTP thật.
- [x] T003 Đặt người chủ nhà vào **runtime đầu tiên sẵn sàng**, tự động, đúng một lần (FR-112). Hook ở chỗ daemon khai runtime. Đã đặt rồi thì runtime mới không làm nó chuyển đi; nhiều runtime cùng sẵn sàng thì cách chọn phải xác định được. Chỉ **id của runtime** đi qua ranh giới — bên gọi biết máy nào khai và tool nào chạy, tầng nghiệp vụ không được biết (Điều III), nên nó tự hỏi chính runtime xem có nhận việc được không. Chọn theo id nhỏ nhất: cái nhìn của tầng miền về một chỗ làm **không có tuổi** (cố ý, đó là thứ hạ tầng giữ riêng), nên thứ ổn định duy nhất còn lại là id — và một luật ổn định quan trọng hơn một luật có ý nghĩa, vì thay thế của nó là *thứ tự hàng nào về trước*. *Đo*: 5 bài đơn vị (đặt đúng chỗ và chép `carried_by` xuống; runtime thứ hai không làm nó chuyển đi; runtime đóng hoặc không nói được ai chở việc thì không phải chỗ để đặt; bốn runtime đảo thứ tự vẫn chọn cùng một cái; *không có gì để làm* không phải lỗi) + 2 bài qua luồng thật.
- [x] T004 Ghi **trạng thái ba bước** trên người dùng và trả nó ra `GET /auth/me` (FR-104). Sống lâu hơn một phiên: bỏ dở thì lần sau vào lại đúng chỗ, đi xong thì lần sau không gặp lại. Trên người dùng chứ không trong browser: ba bước là một lần cho **một tài khoản**, nên người đăng ký ở laptop rồi mở lại ở điện thoại không bị hỏi lần hai. `onboarded_at` có giá trị là toàn bộ nghĩa của *đã xong* — một con số bước không nói được điều đó (bước 3 vừa là *đang đứng ở bước cuối* vừa là *đã xong*), còn thêm một cờ boolean cạnh con số là thêm hai thứ có thể nói ngược nhau. Xong là **một chiều**: gửi `onboarding_done: false` được nhận và không làm gì. **Nửa quan trọng của migration là backfill**: mọi người dùng đã có được đánh dấu xong, dùng `created_at` của chính họ chứ không phải `now()` — không thì sáng mai mọi người đang dùng đều bị đẩy vào luồng dành cho người mới. *Đo trên Postgres thật*: 56 người dùng, **0** người chưa xong ba bước sau migration.
- [x] T005 Vá cửa hậu: không gian làm việc **đã tồn tại** mà chưa có người chủ nhà (FR-110, FR-113). Làm bằng migration, không làm lúc đăng nhập: đây là việc **một lần** cho dữ liệu đã có, nhét vào đường đăng nhập là bắt mọi lần đăng nhập về sau trả giá cho một lần sửa dữ liệu. `downgrade` **không** gỡ lại, và đó là chủ ý: người chủ nhà là một agent thật, có thể đã được đổi tên, sửa chỉ dẫn, đặt vào runtime, giao việc — xoá theo tên và theo vai là xoá cả những con ấy. *Đo trên Postgres thật*: trước 57 không gian làm việc / **2** chủ nhà; sau **57** chủ nhà / **0** không gian làm việc không có con trỏ. **Hai lỗi tôi tự tạo ra, mỗi lỗi bị một dialect bắt, và không lỗi nào suy ra được nếu chỉ chạy một bên**: bản đầu dùng `gen_random_uuid()` — hàm riêng của Postgres — làm đỏ **12** bài kiểm migration chạy trên SQLite; sửa sang `str(uuid4())` thì SQLite xanh và Postgres thật đổ với `column "id" is of type uuid but expression is of type character varying`. Nay tham số nói rõ kiểu (`sa.bindparam(..., type_=sa.Uuid)`), và đã đo **cả hai** bên.

### Còn để lại sau đợt 1

- [ ] T005b Một migration **cũ** không đi xuống được trên Postgres. Tìm ra 2026-09-07 khi kiểm chuỗi migration cả hai chiều trên một cơ sở dữ liệu Postgres tạm: `alembic downgrade base` chết ở `e9c2a4d7f0b3 → d3f7b2a6c1e8` (spec001 T199, *một cái ghế là một hàng sống*) với `relation "pk_seat_grants" already exists`. Không liên quan tới đặc tả này — hai migration của nó đi xuống trơn trước khi tới đó — và bộ kiểm không bắt được vì nó chạy chuỗi ấy trên SQLite, nơi tên ràng buộc không đụng nhau. Không sửa ở đây: nó thuộc spec 001, và đi xuống tận base trên Postgres không phải đường ai đang dùng. Ghi lại để không phải tìm lại lần nữa.

- [ ] T005a Không có gì **thử lại** việc tạo người chủ nhà. FR-113 nói nhánh ấy không được làm việc tạo không gian làm việc thất bại, nên nó bị nuốt và ghi log. Hệ quả thật thà: nếu nó hỏng đúng lúc ấy thì còn lại một không gian làm việc không có chủ nhà, và chủ nó không dùng được chế độ dựng dự án bằng hỏi–đáp — cho tới khi có ai gọi lại `provide_host`. Hôm nay chỉ có hai chỗ gọi: chính dòng ấy ở lần tạo không gian làm việc sau, và migration vá dữ liệu cũ. Chưa quyết nên vá bằng gì: một lần thử lại lúc đăng nhập trả giá mọi lần đăng nhập, còn gọi lúc đọc danh bạ là ghi trên đường đọc.

## Phase 2 — Giao diện: ba bước (đợt 2)

- [x] T006 Màn ba bước và đường dẫn tới nó (FR-100). Đăng ký xong đổ vào đây thay vì màn chọn không gian làm việc; đi xong thì vào trong không gian làm việc. Trang sống **ngoài** `/w/:workspaceId`: không gian làm việc đã tồn tại rồi, nhưng đặt tên nó là một trong ba bước, nên bọc nó trong layout có sidebar của chính nó là hiện câu trả lời ngay cạnh câu hỏi. Người đăng nhập lại mà bỏ dở cũng bị đổ về đây, không riêng người vừa đăng ký.
- [x] T007 Bước *về bạn* và bước *không gian làm việc* (FR-101, FR-102). Tên người dùng hiện sẵn và sửa được; tên không gian làm việc **đổi tên** cái đã có (không tạo cái thứ hai, nếu không thì ai đóng tab giữa chừng sẽ có hai), tên rỗng thì nút Tiếp không bấm được. Ô tên **suy ra** chứ không gieo bằng effect: `null` nghĩa là chưa ai gõ nên hiện tên lúc đăng ký — kể cả khi người dùng về muộn một nhịp sau lần vẽ đầu; một chuỗi bất kỳ, kể cả rỗng, là thứ họ đã gõ và không bị chạm. ESLint bắt bản đầu của tôi ghi state trong effect, và nó đúng: một effect ghi state lúc dữ liệu về là hai nguồn cho một giá trị, và hai nguồn ấy nói ngược nhau đúng một khung hình.
- [x] T008 Bước *nối máy* (FR-103). Lệnh cài và lệnh nối dạng **chép được** — dòng cài dài 88 ký tự URL, và gõ sai nó là một 404 người dùng không đọc nổi. Địa chỉ trong lệnh nối dựng từ chính nơi trang đang chạy, đổi cổng sang `:8080`, vì đó là cửa API chứ không phải trang web. Đường tới tài liệu và **một đường bỏ qua**, chỉ ở bước này: hai bước trước hỏi đúng những thứ hệ thống đang tự trả lời hộ, bỏ qua chúng là đặt lại sự im lặng. **Không hỏi vòng** đợi máy xuất hiện (Điều IV) — daemon tự mở trang phê duyệt (FR-001b) nên đường đi tiếp nằm ở tay daemon, không ở màn hình này.
- [x] T009 Chuỗi hiển thị cả hai ngôn ngữ, đủ diacritics (FR-100–FR-103). Khoá là `firstSteps`, **không** phải `onboarding`: chữ ấy trong sản phẩm này đã có nghĩa khác — buổi hỏi–đáp dựng dự án — và bản đầu của tôi trùng khoá, làm `tsc -b` đỏ với TS1117.
- [x] T010 Kiểm trên dịch vụ thật. **15/15 bản tiếng Anh**: đăng ký xong vào thẳng ba bước; tên lúc đăng ký hiện sẵn; đổi tên rồi sang bước 2; đặt tên không gian làm việc rồi sang bước 3; bước 3 có lệnh cài, lệnh nối và địa chỉ `:8080`; rời trang rồi mở lại thì về **đúng bước đang dở**; bỏ qua thì vào trong không gian làm việc; tên tự đặt còn đó và **không còn** chữ `"Personal"`; danh bạ có Livia; đăng nhập lại **không** gặp lại ba bước; tên đã sửa còn giữ. **7/7 bản tiếng Việt** trên cùng luồng ấy, đặt ngôn ngữ trước khi ứng dụng khởi động. *Một lần tôi suýt báo sai*: lệnh dựng frontend hỏng vì trùng khoá i18n, mà tôi lại `| tail -1` nên nuốt mất lỗi, rồi khởi động lại container trên **ảnh cũ** và đo bản cũ — kết luận lúc ấy sẽ là *tính năng không chạy*, trong khi mã mới chưa từng được dựng.

---

## Dependencies

```
T001, T002, T004  ← độc lập nhau, khác tệp
   ↓
T003  ← cần T002 (không có người chủ nhà thì không có gì để đặt)
T005  ← cần T002 (dùng lại đúng cửa ấy)
   ↓
T006 → T007, T008 → T009 → T010
```

## Implementation Strategy

**Đợt 1 = Phase 1.** Xong Phase 1 là người chủ nhà đã có thật và tự sống khi máy đầu tiên nối vào —
đo được không cần một dòng giao diện nào. Đó cũng là nửa trả lại chế độ dựng dự án bằng hỏi–đáp cho
mọi tài khoản mới, tức là nửa có giá trị ngay.

**Không gộp T003 vào T002.** Tạo được người chủ nhà mà không có đường đặt chỗ thì FR-111 đúng vĩnh
viễn: một con ngoại tuyến, có lý do đọc được, và không bao giờ hết ngoại tuyến.
