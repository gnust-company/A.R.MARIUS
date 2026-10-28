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

- [x] T005b Migration cũ đi xuống được trên Postgres — **xong**. Gốc: `downgrade` dựng bảng tạm mang **đúng tên ràng buộc** mà bảng thật đang giữ, và trên Postgres tên ràng buộc là duy nhất trong **cả schema** chứ không phải trong một bảng — nên nó chạy trên SQLite và chết trên Postgres, đúng lý do bộ kiểm không thấy. Sửa bằng cách dọn bảng cũ **trước**: chở dữ liệu sang một bảng mang tạm không ràng buộc nào, xoá bảng cũ, dựng lại bảng thật với đúng tên chuẩn, đổ về, bỏ bảng chở. `CREATE TABLE … AS SELECT` cả hai dialect đều hiểu nên không phải phân nhánh theo dialect. Đo cả hai chiều trên một Postgres tạm: xuống tận base, lên lại head, tên ràng buộc trở về chuẩn. Chốt mới ở `test_migrations_on_postgres.py`, **chỉ chạy khi có `ARMARIUS_TEST_POSTGRES_URL`** — nói thẳng vì kho chưa có CI, nên thứ thật sự chạy nó là một người gõ biến môi trường. Thử ngược: đưa `downgrade` về hình cũ thì nó đỏ đúng câu `relation "pk_seat_grants" already exists`.

- [x] T005a Thử lại việc tạo người chủ nhà — **xong**, và vá đúng chỗ hoá đơn tới. Hai đường task này nêu ra đều tệ hơn: thử lại lúc đăng nhập thì mọi lần đăng nhập của mọi tài khoản đang lành đều trả giá, còn gọi lúc đọc danh bạ là ghi trên đường đọc. Đường thứ ba đúng hơn cả hai: vá ở **chỗ mở buổi phỏng vấn**, vì chế độ dựng dự án bằng hỏi–đáp chính là thứ người chủ nhà sinh ra để làm, nên đó là nơi thiếu nó mới thành một sự thật nhìn thấy được. Không tốn gì cho tới đúng lúc đã hỏng, và cửa vốn idempotent nên một người chủ nhà xuất hiện xen giữa chỉ đơn giản được trả về. Bài kiểm giữ cả hình dạng thật: lần mở đầu **vẫn hỏng** vì người chủ nhà vừa dựng chưa có chỗ làm, nhưng từ đó trở đi nó là một không gian làm việc bình thường — trước khi vá thì không có đường nào tới đó cả.

## Phase 2 — Giao diện: ba bước (đợt 2)

- [x] T006 Màn ba bước và đường dẫn tới nó (FR-100). Đăng ký xong đổ vào đây thay vì màn chọn không gian làm việc; đi xong thì vào trong không gian làm việc. Trang sống **ngoài** `/w/:workspaceId`: không gian làm việc đã tồn tại rồi, nhưng đặt tên nó là một trong ba bước, nên bọc nó trong layout có sidebar của chính nó là hiện câu trả lời ngay cạnh câu hỏi. Người đăng nhập lại mà bỏ dở cũng bị đổ về đây, không riêng người vừa đăng ký.
- [x] T007 Bước *về bạn* và bước *không gian làm việc* (FR-101, FR-102). Tên người dùng hiện sẵn và sửa được; tên không gian làm việc **đổi tên** cái đã có (không tạo cái thứ hai, nếu không thì ai đóng tab giữa chừng sẽ có hai), tên rỗng thì nút Tiếp không bấm được. Ô tên **suy ra** chứ không gieo bằng effect: `null` nghĩa là chưa ai gõ nên hiện tên lúc đăng ký — kể cả khi người dùng về muộn một nhịp sau lần vẽ đầu; một chuỗi bất kỳ, kể cả rỗng, là thứ họ đã gõ và không bị chạm. ESLint bắt bản đầu của tôi ghi state trong effect, và nó đúng: một effect ghi state lúc dữ liệu về là hai nguồn cho một giá trị, và hai nguồn ấy nói ngược nhau đúng một khung hình.
- [x] T008 Bước *nối máy* (FR-103). Lệnh cài và lệnh nối dạng **chép được** — dòng cài dài 88 ký tự URL, và gõ sai nó là một 404 người dùng không đọc nổi. Địa chỉ trong lệnh nối dựng từ chính nơi trang đang chạy, đổi cổng sang `:8080`, vì đó là cửa API chứ không phải trang web. Đường tới tài liệu và **một đường bỏ qua**, chỉ ở bước này: hai bước trước hỏi đúng những thứ hệ thống đang tự trả lời hộ, bỏ qua chúng là đặt lại sự im lặng. **Không hỏi vòng** đợi máy xuất hiện (Điều IV) — daemon tự mở trang phê duyệt (FR-001b) nên đường đi tiếp nằm ở tay daemon, không ở màn hình này.
- [x] T009 Chuỗi hiển thị cả hai ngôn ngữ, đủ diacritics (FR-100–FR-103). Khoá là `firstSteps`, **không** phải `onboarding`: chữ ấy trong sản phẩm này đã có nghĩa khác — buổi hỏi–đáp dựng dự án — và bản đầu của tôi trùng khoá, làm `tsc -b` đỏ với TS1117.
- [x] T010 Kiểm trên dịch vụ thật. **15/15 bản tiếng Anh**: đăng ký xong vào thẳng ba bước; tên lúc đăng ký hiện sẵn; đổi tên rồi sang bước 2; đặt tên không gian làm việc rồi sang bước 3; bước 3 có lệnh cài, lệnh nối và địa chỉ `:8080`; rời trang rồi mở lại thì về **đúng bước đang dở**; bỏ qua thì vào trong không gian làm việc; tên tự đặt còn đó và **không còn** chữ `"Personal"`; danh bạ có Livia; đăng nhập lại **không** gặp lại ba bước; tên đã sửa còn giữ. **7/7 bản tiếng Việt** trên cùng luồng ấy, đặt ngôn ngữ trước khi ứng dụng khởi động. *Một lần tôi suýt báo sai*: lệnh dựng frontend hỏng vì trùng khoá i18n, mà tôi lại `| tail -1` nên nuốt mất lỗi, rồi khởi động lại container trên **ảnh cũ** và đo bản cũ — kết luận lúc ấy sẽ là *tính năng không chạy*, trong khi mã mới chưa từng được dựng.

## Phase 3 — Ba bước kết thúc bằng một máy đang chạy (đợt 3)

*Người chủ tự đi hết luồng 2026-09-07 và báo hai chỗ.*

- [x] T011 Bước ba nói **cả ba lệnh**, và lệnh nối tự nói ra lệnh còn lại (FR-105). Hôm nay bước ba dừng ở `login`, mà `login` chỉ đổi lấy giấy tờ rồi thoát — `start` mới là lệnh chạy daemon. Hệ quả người chủ gặp: đi hết ba bước, máy có mặt, mọi agent ngoại tuyến, và không dòng nào trên màn hình nói tại sao. `install.sh` có in "Next steps… start" ở cuối, nhưng người đi theo màn hình chép hai dòng trên trang chứ không đọc đuôi installer. Sửa ở hai chỗ vì có hai người đọc: màn ba bước, và câu cuối `login` in ra.
- [x] T012 Duyệt máy xong thì **không còn cửa sổ mồ côi** (FR-106). Daemon tự mở trang phê duyệt, nên lúc duyệt xong có hai cửa sổ: cái vừa duyệt, và cái vẫn đứng ở bước ba. Hôm nay cái thứ hai không biết gì cả, và người chủ nói đúng câu ấy: *"còn tab đang onboard bị mồ côi, tôi không biết phải dùng như nào nữa"*. Duyệt máy trong lúc ba bước còn dở thì chính việc ấy **kết thúc ba bước**, và cửa sổ đang đợi được **đẩy tin sang** để tự đi tiếp — đẩy, không hỏi vòng (Điều IV). Khác browser thì không đẩy sang được: cửa sổ đợi vẫn còn nút của chính nó, và tải lại trang là biết. **Guard hiến pháp bắt được chỗ đặt đầu tiên của tôi**: tên sự kiện nằm ở `application/ports/`, mà Điều III cấm tầng nghiệp vụ biết việc chạy ở đâu — `machine` nằm trong danh sách từ cấm. Nó đúng: cổng phát tin vốn đã tổng quát, nên tên ấy chuyển xuống hạ tầng và tầng trên không cần một chữ nào cho nó.
- [x] T013 Khổ màn ba bước rộng ra (FR-105). *Người chủ: "cái view boarding phần modal hiển thị hơi nhỏ cho nó rộng ra tý".* Bước ba đang phải xuống dòng giữa một dòng lệnh 88 ký tự trong một khung 448px, và sắp có lệnh thứ ba nữa.
- [x] T014 Kiểm trên dịch vụ thật, **12/12 đạt**, đúng cảnh người chủ mô tả: cửa sổ 1 đứng ở bước ba, một máy xin mã như `login` vẫn làm, cửa sổ 2 mở `/link?code=…` nhận ra tên máy rồi duyệt — và cửa sổ 1 **tự rời** bước ba sang trong không gian làm việc, không cần ai chạm vào. Kèm: bước ba có đủ ba lệnh; khung đo được **576px** (trước là 448px); cửa sổ 2 nhắc chạy `start` và nói ba bước đã xong; đăng nhập lại không gặp lại ba bước. **6/6 bản tiếng Việt** trên cùng luồng ấy, đặt ngôn ngữ trước khi ứng dụng khởi động. Bộ kiểm cũ của đợt 2 chạy lại **15/15**, không hỏng gì.

---

# Lần sửa 2026-10-12 — onboarding dạy từ thêm máy tới agent đầu tiên

**Đặc tả**: FR-100, FR-104, FR-106, FR-112, FR-115 (sửa) · Nhóm C FR-120 đến FR-128 · SC-103 đến SC-108.
**Thiết kế**: [plan.md](./plan.md), [research.md](./research.md) R1–R10,
[contracts/](./contracts/), [quickstart.md](./quickstart.md) K1–K8. Hiến pháp **2.1.0**.

Hai PR code, theo tầng: **PR backend** (T015, T016, T018, T019, T021, T022), rồi **PR giao diện và tài
liệu** (T017, T020, T023–T027). Mỗi PR đều kiểm trên dịch vụ thật trước khi báo xong. Bài kiểm nằm
**trong** từng task, như các đợt trước.

## Phase 4 — Nền: thứ cả US2 và US3 cùng cần

- [x] T015 [P] `onboarding_step` nhận 0–4 (research R6). Sửa `le=3` thành `le=4` ở `backend/armarius/presentation/api/auth.py` (lớp body của `PATCH /auth/me`), và sửa chú thích "three first steps" ở `backend/armarius/infrastructure/database/models.py` cùng `backend/armarius/domain/entities/user.py` cho khớp bốn bước. Cột không đổi, không migration. *Đo*: thêm bài vào `backend/tests/test_the_first_steps_of_a_new_account.py`: bước 4 được nhận; 5 trả 422; `onboarding_done: false` sau khi đã xong vẫn không làm gì.
  **Xong.** `le=4`; bài mới: bước 4 nhận được mà chưa là *đã xong*, 5/9/-1 trả 422. Thử phá (`le=3`) thì đỏ.
- [x] T016 Sự kiện `machine.workplaces_reported` (contracts/push-events.md, research R4). Thêm `EVENT_WORKPLACES_REPORTED` và `announce_workplaces_reported(trace, workspace_id)` cạnh `announce_machine_linked` ở `backend/armarius/infrastructure/events/workspace_trace.py`. Payload chỉ có `{"workspace_id"}`. Gọi nó trong `sync_workplaces` ở `backend/armarius/presentation/api/daemon.py`, ngay sau khi `container.daemon_workplaces.sync(...)` trả về, **kể cả** khi `stopping`. Container phải đưa được trace publisher tới chỗ ấy: xem cách `infrastructure/daemon/enrollment.py` đang giữ `_workspace_trace`. Tên sự kiện KHÔNG được xuất hiện dưới `domain/` hay `application/` (guard ở `backend/tests/test_constitution_guards.py`). *Đo*: bài mới `backend/tests/test_a_machine_reporting_its_runtimes_is_announced.py`, nghe kênh `ws:{id}` trên bus thật: một lần đồng bộ có runtime phát đúng một sự kiện; lần báo `stopping` cũng phát; máy ở workspace khác thì kênh này im.
  **Xong.** Phát ngay sau `sync`, cả lần `stopping`. Thử phá hai chỗ (bỏ lần `stopping`, nhét danh sách vào tin) thì cả hai đều đỏ. *Đo trên dịch vụ thật*: daemon chạy lên thì tin tới sau 0,15 giây (SC-107 đòi dưới 5 giây); daemon dừng cũng có tin.
- [x] T017 [P] Hai component dùng chung và hàm gọi API (research R2, R8; FR-122, FR-123a, FR-125).
  - `frontend/src/components/agent/RuntimePicker.tsx`: nhận danh sách runtime sẵn sàng (`listWorkplaces`) và danh sách máy (`listMachines`, để hiện runtime chưa sẵn sàng cùng lý do qua `machines.notReady.*`). Mỗi dòng hiện loại CLI và tên máy. Runtime chưa sẵn sàng thì không bấm được. Luật chọn sẵn của FR-125 không nằm trong component mà là một hàm thuần `initialRuntimeChoice(ready)` ở `frontend/src/lib/runtimeChoice.ts`: đúng một runtime sẵn sàng thì trả id của nó; không có hoặc từ hai trở lên thì trả `null` (chưa chọn).
  - `frontend/src/components/agent/SystemPromptBlock.tsx`: tách khối system prompt chỉ đọc ra khỏi `frontend/src/components/agent/InstructionsTab.tsx` rồi cho tab ấy dùng lại. Thêm dòng giải thích i18n (`agentDetail.systemPrompt.note`: chữ do Armarius viết, gửi nguyên văn cho agent, không sửa được).
  - `placeHost(workspaceId, mariusId, body)` ở `frontend/src/lib/api.ts`, đúng contracts/user-surface.md §1. Lỗi 409 `agent_already_placed` mang `cli_kind` và `machine_name` lên cho người gọi.
  - Chuỗi vi/en ở `frontend/src/i18n/vi.ts`, `frontend/src/i18n/en.ts`, đủ dấu.
  - *Đo*: `frontend/src/lib/runtimeChoice.test.ts` (vitest chạy `src/**/*.test.ts` trong môi trường node, nên không có bài kiểm component): không runtime nào thì `null`; một thì id của nó; hai thì `null`. Phần hiện ra trên màn hình đo ở T027.
  **Xong.** Thêm hai hàm thuần cạnh `initialRuntimeChoice`: `currentRuntimeChoice` (lựa chọn suy ra mỗi lần vẽ, nên runtime vừa tắt không còn được chọn) và `unavailableRuntimes` (runtime chưa sẵn sàng kèm lý do, không bao giờ hiện hai lần). Hai danh sách đọc chung một lượt qua `frontend/src/hooks/use-runtime-offer.ts`. Tiến độ bước nối máy cũng là hàm thuần, ở `frontend/src/lib/firstSteps.ts`. 14 bài vitest mới; thử phá 6 chỗ trong các hàm thuần thì cả 6 đỏ.

## Phase 5 — US2: Livia chạy đúng runtime người dùng chọn (P1)

**Mục tiêu**: người chủ nhà không bao giờ tự bị đặt chỗ. Người dùng chọn runtime cho nó qua một cửa chỉ dành cho người chủ nhà (FR-112, FR-127, FR-128).
**Phép kiểm độc lập**: quickstart K3, K4, K5, K7.

- [x] T018 [US2] Cửa đặt chỗ cho người chủ nhà (contracts/user-surface.md §1, research R2).
  - Viết lại `WorkspaceAgentService.place_host` ở `backend/armarius/application/use_cases/workspace_agent.py` thành `place_host(workspace_id, marius_id, placement_id, *, instructions=None)`:
    - agent không giữ ghế chủ nhà → `Conflict("placement_is_fixed")`;
    - đã có chỗ làm → `Conflict("agent_already_placed")`;
    - chỗ làm không thuộc workspace → `NotFound("placement_not_found")`;
    - chỗ làm không `ready` hoặc không có `carried_by` → `PlacementNotReady("placement_not_ready")` (400, cùng mã cửa tạo agent đang trả).
  - Một lần commit gồm: `uow.placements.attach`, `adapter_type = place.carried_by`, `instructions` nếu có. Thua đua khi `attach` (`Conflict`) thì trả đúng `agent_already_placed`. Sau đó gọi `self._liveness.placement_changed([id])` (FR-006e). Tầng này chỉ thấy id chỗ làm (Điều III).
  - Route `POST /workspaces/{workspace_id}/mariuses/{marius_id}/placement` ở `backend/armarius/presentation/api/workspaces.py`, qua `_require_owned_workspace`. Body `PlaceHostIn` (`workplace_id`, `instructions: str | None`, tối đa 20000 ký tự) ở `backend/armarius/presentation/schemas.py`. Trả `MariusOut`. Lỗi 409 `agent_already_placed` được presentation điền `cli_kind` và `machine_name` của chỗ đang ở.
  - *Đo*: bài mới `backend/tests/test_the_owner_chooses_where_the_host_works.py`, mỗi hàng lỗi trong contract một bài, cộng các bài sau:
    - đặt xong thì `runtime` có giá trị, `instructions` đã lưu, và trạng thái sang *đang kiểm* ngay;
    - lỗi thì không thứ gì đổi, kể cả `instructions`;
    - hai yêu cầu đồng thời thì một 200, một 409;
    - người chủ nhà mất chỗ làm vì máy bị gỡ thì đặt lại được;
    - agent thường mất chỗ làm vì máy bị gỡ thì nhận 409 `placement_is_fixed` (K7);
    - workspace của người khác thì 404.
  **Xong.** Mã lỗi dùng lại `placement_not_found` (404) và `placement_not_ready` (400) của cửa tạo agent, thay vì hai mã mới viết trong contract (đã sửa contract cho khớp); chỉ thêm `placement_is_fixed`. Thua đua: `attach` dịch `IntegrityError` thành `agent_already_placed`, có bài đua trên **Postgres thật** (`test_host_placement_races.py`, chạy khi có `TEST_DATABASE_URL`). 14 bài HTTP + 7 bài đơn vị; thử phá 6 chỗ ở cửa này thì cả 6 đỏ. *Đo trên dịch vụ thật*: hai runtime, chọn claude, 200 và Livia online ngay; lần chọn thứ hai 409 kèm `cli_kind`, `machine_name`; agent thường mất máy 409 `placement_is_fixed`; runtime chưa sẵn sàng 400.
- [x] T019 [US2] Bỏ tự đặt chỗ (FR-112, research R3). Xoá lời gọi `container.workspace_agent.place_host(...)` trong `sync_workplaces` ở `backend/armarius/presentation/api/daemon.py`, cùng khối chú thích FR-112 đi kèm. Sửa các bài đang khẳng định tự đặt chỗ, cho chúng khẳng định điều ngược lại: máy báo runtime thì người chủ nhà **vẫn** chưa có chỗ làm, và vẫn ngoại tuyến với lý do `not_placed`. Các bài ấy ở `backend/tests/test_workspace_agent.py`, `backend/tests/test_the_first_steps_of_a_new_account.py`, `backend/tests/test_daemon_workplaces.py`, `backend/tests/test_a_new_place_is_measured_at_once.py`. Bài nào dựng một người chủ nhà *đã có chỗ làm* để thử việc khác thì chuyển sang gọi cửa của T018. Chạy toàn bộ bộ kiểm backend để bắt những bài phụ thuộc ngầm.
  **Xong.** 31 bài đỏ sau khi bỏ, chia ba gốc: bài khẳng định tự đặt chỗ (đổi thành người chủ chọn qua `put_host_to_work`); bài đọc agent đầu danh bạ theo vị trí, vô tình trúng Livia đã tự được đặt cùng máy (đổi sang chọn theo id); bài mượn skill dựng sẵn làm skill mẫu (xem T022). Thử phá — cài lại tự đặt chỗ — thì đỏ.
- [x] T020 [US2] Trang người chủ nhà có đường chọn runtime (FR-128). Ở `frontend/src/pages/AgentDetail.tsx`: agent là người chủ nhà (`workspace.workspaceAgentId === agent.id`) và `runtime` rỗng thì hiện một khối có `RuntimePicker` (T017) cùng nút chọn, gọi `placeHost` **không** kèm `instructions`. Khối ấy nghe `machine.workplaces_reported` qua `subscribeWorkspaceEvents` để đọc lại danh sách (K3 bước 3); nghe, không hỏi vòng. Agent thường chưa có chỗ làm thì **không** có khối này. Đổi câu `agentDetail.offlineReason.not_placed` và các khoá cùng nghĩa ở `frontend/src/i18n/vi.ts`, `frontend/src/i18n/en.ts` thành *chưa được chọn runtime*. Thêm câu cho ba mã 409 mới ở `errors.*`.
  **Xong.** Khối nằm ở tab *Tổng quan*, tách ra `frontend/src/components/agent/HostRuntimeChooser.tsx`. Nó nghe qua kết nối layout đang giữ (`onWorkspaceEvent`), không mở luồng thứ hai bằng `subscribeWorkspaceEvents`. Mã 409 mới chỉ còn `placement_is_fixed`, đã có câu từ PR backend. `agent_already_placed` giữ câu chung, vì cửa tạo agent cũng trả mã ấy mà không kèm tham số. Đổi luôn `agentDetail.runtimeNone` và `settingsTab.runsNowhere`. *Đo trên dịch vụ thật*: K3 và K7 đạt.

## Phase 6 — US3: onboarding dạy từ thêm máy tới agent đầu tiên (P1)

**Mục tiêu**: bốn bước; bước nối máy tự biết từng phần đã xong; bước cuối dựng Livia với system prompt chỉ đọc, chỉ dẫn mặc định sửa được, runtime do người dùng chọn, không skill nào hiện ra (FR-100, FR-106, FR-120–FR-127, FR-123, FR-123a).
**Phép kiểm độc lập**: quickstart K1, K2, K6, K8.
**Phụ thuộc**: T018 (cửa đặt chỗ), T016 (sự kiện), T017 (component).

- [x] T021 [US3] Chỉ dẫn mặc định khi tạo người chủ nhà (FR-124, FR-115, research R1). Thêm hằng `HOST_DEFAULT_INSTRUCTIONS` ở `backend/armarius/application/use_cases/workspace_agent.py`, ngay dưới `HOST_INSTRUCTIONS`, với đúng chữ ở research R1 (người chủ duyệt trong PR docs). `provide_host` truyền `instructions=HOST_DEFAULT_INSTRUCTIONS` vào `create_unplaced`. System prompt giữ nguyên. Người chủ nhà đã có từ trước thì **không** đụng. *Đo*: workspace mới có Livia với `instructions` là chữ mặc định và `system_instructions` không đổi; một Livia dựng dở (nhánh *orphan* của `provide_host`) không bị ghi đè `instructions`.
  **Xong.** Chữ đúng như research R1. Bài mới: người chủ nhà mới mang chỉ dẫn mặc định cạnh system prompt; gọi lại `provide_host` không ghi đè chữ người chủ đã sửa. Thử phá (bỏ chỉ dẫn mặc định) thì đỏ.
- [x] T022 [US3] Ẩn skill dựng sẵn ở cửa API, kèm migration dữ liệu (FR-123, contracts/user-surface.md §3–§4, data-model.md, research R7).
  - Ở `backend/armarius/presentation/api/workspaces.py`:
    - `list_skills` bỏ dòng `source == "builtin"`;
    - `get_skill`, sửa skill, xoá skill: với skill dựng sẵn thì trả 404;
    - tạo agent, sửa agent, `install-skills`: lẳng lặng bỏ id dựng sẵn khỏi `skill_ids` trước khi ghi, và không bao giờ trả chúng trong `MariusOut.skill_ids` hay `skills`.
  - Migration mới ở `backend/armarius/infrastructure/alembic/versions/` (down_revision là head hiện tại): bỏ khỏi `mariuses.skill_ids` mọi id thuộc skill `source = 'builtin'` cùng workspace, và bỏ tên tương ứng khỏi `mariuses.skills`. `downgrade` để trống có chủ ý.
  - `wake_engine` và `builtins_for` **không đổi**.
  - *Đo*:
    - bài API: không còn dòng dựng sẵn trong danh sách; GET theo id trả 404; gửi id dựng sẵn khi tạo agent thì không lỗi và không lưu;
    - bài migration chạy trên SQLite (`backend/tests/test_migrations.py`) và trên Postgres thật (`backend/tests/test_migrations_on_postgres.py`, khi có `ARMARIUS_TEST_POSTGRES_URL`);
    - bài sẵn có `backend/tests/test_claim_carries_skills.py` vẫn xanh: lượt chạy vẫn nhận *Talking to Armarius*.
  **Xong.** Lọc ở cửa cho người xem: danh sách, GET/PUT/DELETE theo id (404), và ba cửa ghi skill của agent. *Bài cũ phải sửa*: `test_skills_and_agents.py` và `test_a_deleted_skill_leaves_nothing_behind.py` mượn skill dựng sẵn làm skill mẫu để gắn — đổi sang skill người chủ tự tạo; bài *skill dựng sẵn bị nghỉ* nay dựng mối gắn thẳng trong DB, đúng hình dạng dữ liệu cũ; bài xoá skill dựng sẵn giữ cả hai khoá (cửa 404, service vẫn từ chối). *Migration*: thử phá lần đầu **lọt** — bỏ bước chuẩn hoá UUID mà bài vẫn xanh, vì bài gieo mọi thứ có gạch nối. Dữ liệu thật trên SQLite trộn hai dạng: ORM ghi cột UUID thành 32 hex, còn `skill_ids` giữ `str(id)` có gạch nối. Gieo đúng hỗn hợp ấy thì bài bắt được. Đo trên Postgres thật bằng dữ liệu gieo tay, và trên DB đang chạy: sau migration **0** agent còn id dựng sẵn. *Sửa theo review #289*: bản đầu lọc **tên** bằng so chuỗi, độc lập với id, nên một skill riêng mang đúng tên skill dựng sẵn bị mất tên mà vẫn giữ id. Nay chỉ id quyết định bỏ gì; agent nào thật sự mất id thì tên được dựng lại từ id còn giữ, như `_forget_everywhere` — ở cả cửa ghi lẫn migration. Bài mới cho đúng ca trùng tên ở cả hai phía; cài lại cách lọc cũ thì cả hai đỏ. DB đang chạy đã lên revision này bằng bản đầu; soát lại thì không agent nào lệch.
- [x] T023 [P] [US3] Ẩn skill dựng sẵn ở giao diện (FR-123, SC-108).
  - `frontend/src/pages/Skills.tsx`: bỏ tab *Tích hợp sẵn* và state `activeTab` chỉ để chọn tab ấy.
  - `frontend/src/pages/Directory.tsx`: bỏ nhánh chip *luôn bật* (`always = skill.type === 'builtin'`).
  - `frontend/src/lib/mappers.ts`: bỏ kiểu `'builtin'`.
  - `frontend/src/store/appStore.ts`: bỏ `'builtin'` khỏi union.
  - Gỡ khoá i18n không còn ai dùng (`skills.type.builtin`, `skills.emptyBuiltin*`, `directory.skillAlwaysOn`). Giữ `errors.builtin_skill_undeletable`, vì backend vẫn có thể trả mã ấy.
  **Xong.** Gỡ thêm `skills.tabLibrary` và `skills.tabBuiltin`: bỏ tab dựng sẵn thì tab *Thư viện* đứng một mình, nên bỏ cả hàng tab. *Đo trên dịch vụ thật* (K6): thư viện, màn tạo agent, tab skill và bước 4 đều không có skill dựng sẵn; SC-108 = 0.
- [x] T024 [P] [US3] Trang phê duyệt thôi kết thúc onboarding (FR-106, research R6). Ở `frontend/src/pages/LinkMachine.tsx`, bỏ `updateMe({ onboarding_step: 3, onboarding_done: true })`. Khi người duyệt còn đang onboarding, trang nói: chạy `armarius-daemon start`, và cửa sổ onboarding sẽ tự sang bước dựng agent. Trang **không** được nói là đã xong. Chuỗi vi/en.
  **Xong.** Trang không ghi gì vào onboarding nữa. *Đo trên dịch vụ thật* (K1): cửa sổ hai nói tiếp lệnh `start` và chuyện cửa sổ onboarding tự sang bước dựng agent; DB xác nhận duyệt máy xong thì onboarding vẫn chưa xong.
- [x] T025 [US3] Onboarding bốn bước (FR-100, FR-104, FR-120–FR-127; research R5, R9). Ở `frontend/src/pages/Onboarding.tsx`:
  - `STEPS = 4`. Bỏ qua ở bước 3 thì nhảy thẳng tới xong.
  - **Bước 3** hiện ba phần *cài*, *nối*, *chạy* với lệnh chép được:
    - *nối* xong khi `listMachines` có máy, hoặc tab đã nghe `machine.linked`;
    - *chạy* xong khi có máy báo ít nhất một runtime;
    - vào bước này thì đọc ngay; nghe `machine.linked` và `machine.workplaces_reported` thì đọc lại (không hỏi vòng);
    - *chạy* xong thì tự `updateMe({ onboarding_step: 3 })` và sang bước 4 (FR-121);
    - bỏ effect cũ đang kết thúc onboarding khi nghe `machine.linked`.
  - **Bước 4** hiện tên Livia (không sửa), `SystemPromptBlock` (T017), ô chỉ dẫn lấy sẵn `instructions` hiện có của Livia kèm dòng i18n *viết thứ tiếng nào cũng được*, và `RuntimePicker` (T017). Nghe `machine.workplaces_reported` để đọc lại danh sách.
  - **Bấm xong**:
    1. `placeHost(ws, hostId, { workplace_id, instructions })`;
    2. `updateMe({ onboarding_step: 4, onboarding_done: true })`;
    3. chuyển tới `wsHref(ws, '/agents/' + hostId)`.

    Lỗi 409 `agent_already_placed` thì báo *Livia đã chạy trên {cli_kind} ở {machine_name}* rồi làm tiếp 2 và 3. Lỗi 400 `placement_not_ready` thì báo lỗi và đọc lại danh sách.
  - **Bỏ qua ở bước 4** thì chỉ làm 2, rồi về `/projects` như hôm nay.
  - Chuỗi vi/en đủ dấu.
  - Người đang dở ở bước 0–2 lúc triển khai thì vào đúng bước của mình trong luồng mới (K8).
  **Xong.** Bước hiện ra được **suy** từ dữ liệu máy: đang ở bước nối máy mà đã có máy báo runtime thì hiện bước 4 ngay, rồi ghi `onboarding_step: 3`. Không có effect nào tự đặt bước. Một luồng sự kiện dùng chung cho bước 3 và 4, nên sang bước không phải nối lại. Bước 4 không có nút quay lại, vì quay về bước nối máy đã xong chỉ để nó tự sang lại. Cửa sổ nhớ mình đã đặt chỗ thành công, nên bấm lại sau khi bước đánh dấu xong bị lỗi không bị đọc nhầm thành *chọn ở cửa sổ khác*. Thêm nút *Kiểm lại*: một lần đọc khi người dùng bấm, không phải vòng lặp, dùng cho lúc luồng đẩy rớt. *Đo trên dịch vụ thật*: K1, K2, K5 (màn hình), K8 đạt, cả bản tiếng Anh.

## Phase 7 — Hoàn thiện

- [x] T026 [P] Tài liệu người dùng.
  - `docs/quickstart.md` mục 2–4 viết lại theo bốn bước: dạy nối máy, rồi dựng Livia và chọn runtime cho nó; bỏ ý tạo agent đầu tiên bằng tay.
  - `docs/skills.md` mục *"Talking to Armarius"*: skill này tự gắn cho mọi agent, không hiện ở đâu, không phải chọn. Bỏ câu *"hãy gắn nó cho mọi agent"*, vì câu ấy đã sai từ 2026-09-06.
  - Thêm một đoạn ở trang tài liệu nói về agent: Livia chưa có chỗ làm thì chọn runtime ngay trên trang của nó.
  **Xong.** `docs/quickstart.md` mục 2–4 viết lại. `docs/skills.md` sửa cả sơ đồ: skill dựng sẵn đi thẳng tới agent, không qua thư viện. `docs/agents.md` có mục mới *Người chủ nhà chưa có runtime*, gồm cả system prompt.
- [x] T027 Kiểm trên dịch vụ thật theo quickstart K1–K8, rồi chạy đủ bộ kiểm.
  - Dựng lại container frontend và backend, log ra file.
  - Daemon thử chỉ thấy `claude` (thư mục cấu hình riêng, `PATH` hạn chế). Máy giả lập chỉ báo runtime qua HTTP; không chạy `gemini` hay `codex`.
  - Playwright qua `python3` của hệ thống.
  - Đo cả SC-107 (5 giây) và SC-108 (0 chỗ hiện skill dựng sẵn).
  - Bộ kiểm: backend chạy nền khoảng 11 phút; `ruff check`; `npm run build`; `npx eslint`; `npx vitest run`.
  - Dọn tài khoản `verify-*@acme.dev`. Không đụng daemon và tài khoản thật của người chủ.
  - PR backend kiểm trước phần của nó, bằng cách gọi API thật: K4, K5, K7, và K6 phần API.
  **Xong.** Trên dịch vụ thật, 59/59 đạt (Playwright; daemon thử chỉ thấy `claude`; máy giả lập báo `gemini` qua HTTP): K1, K2, K3, K5 phần màn hình, K6, K7, K8, và một lượt tiếng Anh. SC-107: phần *nối* hiện xong 0,11 giây sau khi bấm duyệt, sang bước 4 sau 0,26 giây kể từ lệnh `start`, runtime vừa tắt rời danh sách sau 0,10 giây. SC-108 = 0. Tin nhắn đầu tiên cho Livia có trả lời. Lượt đầu có 2 bài đỏ, cả hai do script: một bài đọc chữ khi danh sách còn đang tải; một bài đợi mạng *yên* trong khi trang luôn giữ luồng SSE. Sửa script rồi chạy lại cả lượt. Bộ kiểm: backend 1327 đạt, 22 bỏ qua (chỉ chạy trên Postgres); `ruff check` sạch; `npm run build` đạt; `npx eslint` chỉ còn 1 cảnh báo có từ trước ở `RunTrace.tsx`; `npx vitest run` 24/24. Đã dọn tài khoản thử; daemon và tài khoản thật của người chủ không bị đụng.

## Phase 8 — Sửa sau lần thử đầu (2026-10-26)

**Nguồn**: người chủ dựng lại từ cơ sở dữ liệu trắng, đi hết các bước và báo bốn chỗ vướng (spec.md,
phiên 2026-10-26). Một PR cho cả bốn.

- [x] T028 [P] Trang phê duyệt dẫn về các bước đầu khi người duyệt còn dở onboarding (FR-106 sửa 2026-10-26). Ở `frontend/src/pages/LinkMachine.tsx`: khi `currentUser.onboarded === false`, nút chính sau khi duyệt là *Quay lại các bước đầu* (về `/onboarding`), nút *Nối thêm một máy nữa* lùi xuống thành lối phụ, và nút *Quay lại* ở cuối trang cũng về `/onboarding`. Người đã xong onboarding thì giữ nguyên như hôm nay. Chuỗi vi/en. *Đo*: K1 bấm lối ra của cửa sổ phê duyệt thì tới đúng bước nối máy, phần *nối* đã xong.
  **Xong.** Lúc kiểm lộ thêm một kẽ: bấm lối ra ngay sau khi duyệt thì daemon có thể chưa kịp nhận giấy tờ, nên chưa có dòng máy nào và phần *nối* hiện là chưa xong. Trang phê duyệt nay mang theo tin *vừa duyệt một máy* khi dẫn về, như cửa sổ onboarding vẫn nghe được qua kênh. *Đo trên dịch vụ thật*: sau khi duyệt chỉ còn lối *Quay lại các bước đầu*; bấm vào là về bước 3 và phần *nối* xong ngay.
- [x] T029 Cửa đặt chỗ nhận thêm tên, và đổi tên trùng thành 409 thay vì 500 (FR-122, FR-126 sửa 2026-10-26).
  - `PlaceHostIn.name: str | None` ở `backend/armarius/presentation/schemas.py` (bỏ khoảng trắng hai đầu, 1–200 ký tự).
  - `WorkspaceAgentService.place_host(..., name=None)` ở `backend/armarius/application/use_cases/workspace_agent.py`: tên trùng một agent **khác** trong không gian làm việc (không phân biệt hoa thường) → `NameTaken("agent_name_taken")`, trước mọi lần ghi; lưu tên cùng lần commit với chỗ làm và chỉ dẫn.
  - Lỗ cũ lộ ra khi tra: `PATCH …/mariuses/{id}` đổi sang một tên đã có thì **500**, vì `update` của repository không dịch `IntegrityError` như `add` làm. Dịch nó thành `NameTaken`, và cho `MariusService.update` nhìn trước như cửa tạo.
  - Sửa `contracts/user-surface.md` §1.
  - *Đo*: đặt chỗ kèm tên mới → 200, tên mới; tên trùng → 409 `agent_name_taken`, không thứ gì đổi (kể cả chỗ làm); gửi đúng tên hiện tại → 200; PATCH đổi tên trùng → 409.
  **Xong.** Dịch lời từ chối của cơ sở dữ liệu chỉ cho đúng luật một tên một agent; mọi lần ghi agent đều đi qua cửa sửa, nên lỗi khác vẫn nổi lên. 6 bài mới, gồm một bài đi thẳng xuống repository để đo đường hai lần đổi tên chạy đua.
- [x] T030 [P] Bước 4 cho sửa tên người chủ nhà (FR-122). Ở `frontend/src/pages/Onboarding.tsx`: ô tên lấy sẵn tên hiện tại, sửa được; tên trống thì nút xong khoá; bấm xong gửi tên cùng runtime và chỉ dẫn qua `placeHost`. Lỗi `agent_name_taken` hiện câu i18n có sẵn, không gì bị đặt chỗ. `appStore.placeHost` nhận thêm tên.
  **Xong.** *Đo trên dịch vụ thật*: ô tên có sẵn *Livia*; gõ tên một agent đã có thì báo đúng câu, ở lại bước 4, Livia không được đặt chỗ; đổi sang *Aurelia* thì tên lưu cùng runtime.
- [x] T031 Daemon hỏi Claude Code danh sách model (FR-007k của đặc tả 002, sửa 2026-10-26). Ở `daemon/internal/discovery/capabilities.go`:
  - sau khi đọc `--help`, mở `claude --print --verbose --input-format stream-json --output-format stream-json --strict-mcp-config` qua đường `Handshake` sẵn có, gửi một `control_request` `list_models`, đóng stdin, đọc `control_response` khớp `request_id`;
  - thành công thì lựa chọn `model` thành: giá trị là tên model đã phân giải (`resolvedModel`, khử trùng), nguồn `tool_listed`, kèm `labels` (tên đọc được) và `narrows` (`{"thinking_level": [...]}` theo `supportedEffortLevels`, rỗng khi model không nhận mức nào). Dòng `default` không thành lựa chọn; dòng `disabled` bị bỏ;
  - thất bại thì giữ y như hôm nay: ba cái tên ví dụ, nguồn `tool_examples`;
  - `Choice` thêm `Labels` và `Narrows`, đều `omitempty`. Sửa `specs/002-daemon-acp-runtime/contracts/daemon-api.md`;
  - *Đo*: bài Go với `Handshake` giả: đúng argv, đúng yêu cầu; trả lời thành công thì ra danh sách, nhãn, thu hẹp; CLI cũ trả `Unsupported control request subtype` thì về ví dụ; không có trả lời, JSON hỏng, danh sách rỗng cũng về ví dụ.
  **Xong.** Tách ra `daemon/internal/discovery/catalog.go`. Bài khởi động daemon (`cmd/armarius-daemon/start_test.go`) dùng một `claude` giả coi mọi lần gọi là một lượt chạy, nên lời hỏi mới làm nó tưởng có việc; nay `claude` giả trả lời như một bản cũ không biết yêu cầu này. *Đo trên dịch vụ thật* (`claude` 2.1.301): 12 model, có tên đọc được, mức suy nghĩ theo từng model.
- [x] T032 Server chuyển tiếp nhãn và luật thu hẹp, và từ chối mức model không nhận (FR-007k sửa 2026-10-26).
  - `OptionSource.LISTED = "tool_listed"` (không đóng) ở `backend/armarius/domain/entities/placement.py`; `PlacementOption` thêm `labels` và `narrows`, vẫn không biết khoá nào là model.
  - `options_of` ở `backend/armarius/infrastructure/daemon/placement.py` đọc `labels`, `narrows` một cách phòng thủ: chỉ giữ nhãn và luật cho giá trị có trong danh sách, chỉ giữ luật trỏ tới khoá có thật.
  - `Placement.refuse_unchosen(chosen, alongside=...)`: một giá trị gửi lần này nằm ngoài danh sách mà lựa chọn khác (sau khi trộn) cho phép → 422 `placement_option_value_unsupported`. Giá trị đã lưu không bị đo lại.
  - `PlacementOptionOut` thêm `labels`, `narrows`.
  - *Đo*: bài đơn vị cho `refuse_unchosen` và `options_of` (dữ liệu hỏng bị bỏ); bài HTTP: tạo agent với model không nhận mức đã chọn → 422; đổi riêng mức theo model đã lưu → đo theo model ấy; đổi riêng model không làm mức đã lưu bị từ chối.
  **Xong.** 8 bài mới. Thử phá 8 chỗ trong server và daemon thì cả 8 đều đỏ; chỗ lọt lần đầu (bỏ bước khử trùng ở daemon) do dữ liệu mẫu thiếu ca hai dòng cùng một model, đã thêm.
- [x] T033 Ô chọn chung theo giao diện dự án (FR-129) và ô model đọc được (FR-007k).
  - `frontend/src/components/Dropdown.tsx` trên Radix Select (đã có trong dự án): màu, viền, cỡ chữ theo dự án; giá trị rỗng là một lựa chọn thật (Radix không cho mục rỗng, nên đổi qua một khoá riêng); mục bị khoá kèm lý do.
  - `frontend/src/components/SuggestBox.tsx` trên Popover + cmdk cho danh sách mở: mở ra là thấy **đủ** danh sách, gõ để lọc, gõ tên khác thì có mục *dùng tên này*, có mục *mặc định của CLI*.
  - Thay mọi `<select>` và `<datalist>`: `CreateProject.tsx`, `CollaborationRoom.tsx` (3), `Directory.tsx` (2), `ProjectBoard.tsx` (3), `LinkMachine.tsx`, `Inbox.tsx`, `RuntimeOptionFields.tsx`.
  - `RuntimeOptionFields`: hiện nhãn cạnh giá trị; danh sách mức suy nghĩ thu hẹp theo model đang chọn; đổi model mà mức đang chọn không còn hợp thì mức về mặc định; model không nhận mức nào thì ô mức khoá kèm câu giải thích. Luật này là hàm thuần ở `frontend/src/lib/runtimeOptions.ts`, có bài vitest.
  **Xong.** Không còn `<select>` hay `<datalist>` nào trong mã giao diện. 10 bài vitest mới cho luật thu hẹp. *Đo trên dịch vụ thật*: mở ô model thấy đủ 13 dòng (kể cả *mặc định*); chọn *Sonnet 5.5* rồi mở lại vẫn đủ 13 dòng; đổi sang *Opus 4.6* thì mức `xhigh` về mặc định và không còn trong danh sách; *Haiku 4.5* thì ô mức khoá kèm câu giải thích; gõ được tên model ngoài danh sách.
- [x] T034 Kiểm trên dịch vụ thật rồi chạy đủ bộ kiểm. Dựng daemon thử từ mã nguồn (chỉ thấy `claude`) để ô model hiện danh sách thật; Playwright cho cả bốn conflict; backend, ruff, `go test ./...`, build, eslint, vitest.
  **Xong.** 27/27 trên dịch vụ thật. Backend 1341 đạt, 22 bỏ qua (chỉ chạy trên Postgres); ruff sạch; `go vet` và `go test ./...` đạt; build đạt; eslint chỉ còn 1 cảnh báo có từ trước ở `RunTrace.tsx`; vitest 34/34. Lượt đầu dừng ở C3 vì script đợi chữ của ô runtime, trong khi không gian thử chỉ có một runtime nên ô đã chọn sẵn; sửa script rồi chạy lại cả lượt. Đã dọn tài khoản thử; tài khoản ông đang test giữ nguyên.
- [x] T035 [P] Lệnh cài đặt daemon vào thư mục của người dùng (FR-008n của đặc tả 002, sửa 2026-10-28). Ở `scripts/install.sh`: mặc định `$HOME/.local/bin`, không `sudo`; `ARMARIUS_BIN_DIR` vẫn đè được, và chỗ ấy cần `sudo` thì nói rằng daemon sẽ không tự cập nhật ở đó. Cài xong thì dọn bản cũ trên `PATH` (thường là `/usr/local/bin`), dùng `sudo` khi cần; không dọn được thì in đúng lệnh. Daemon đang chạy từ chỗ cũ thì in lệnh khởi động lại. Thêm `ARMARIUS_RELEASES`. Sửa `docs/machines-and-daemon.md` và `docs/quickstart.md`.
  **Xong.** Thêm một chỗ lúc kiểm: bản trong `~/.local/bin` đã mới nhất thì lệnh cài dừng sớm và bỏ qua cả việc dọn lẫn khởi động lại, nên hai bước ấy nay chạy cả khi đã mới nhất. Lệnh cài **tự khởi động lại** daemon đang chạy từ chỗ cũ (`stop` cho các lượt đang chạy xong rồi `start` từ chỗ mới); daemon chạy dưới dịch vụ systemd thì để systemd lo, chỉ nói cần sửa gì. Chỉ dọn ở các thư mục trên `PATH`, và chỉ thư mục có chính daemon. Tài liệu: `docs/machines-and-daemon.md`, `daemon/README.md` (cả tệp dịch vụ systemd nay trỏ `%h/.local/bin`).
- [x] T036 Daemon nói ra khi không tự cập nhật được (FR-008n sửa 2026-10-28). Ở `daemon/internal/update/loop.go`: kiểm thư mục chứa chính nó có ghi được không, ngay lúc chạy lên và trước mỗi lần cài; mỗi lần kéo bản mới thì báo một mã qua `Report` — `install_dir_not_writable`, `release_unreachable`, `install_failed`, hoặc rỗng khi ổn. `client.BeatRequest` thêm `update_problem` (bỏ khi rỗng). Cấu hình `auto_update_releases` trỏ nơi phát hành. *Đo*: bài Go cho từng mã, cho mã biến mất khi lần sau thành công, cho thư mục không ghi được thì không tải gì.
  **Xong.** Thêm: nhịp tim mang theo **phiên bản đang chạy**. Trước đây phiên bản trên màn Máy chỉ ghi lúc nối máy, nên daemon tự cập nhật xong màn hình vẫn hiện bản cũ. 6 bài Go mới; thử phá 5 chỗ thì cả 5 đỏ (chỗ lọt lần đầu — báo ngay lúc chạy lên — do bộ khung kiểm cho mọi nhịp tới ngay; thêm bài có nhịp không bao giờ tới).
- [x] T037 Server nhận và giữ mã ấy (FR-008n sửa 2026-10-28). `HeartbeatIn.update_problem` (mã, không phải câu); `DaemonWorkplaceService.heartbeat` ghi vào cột mới `machines.update_problem` (migration); vắng thì xoá. `MachineOut.update_problem`. Sửa `specs/002-daemon-acp-runtime/contracts/daemon-api.md`. *Đo*: nhịp tim có mã thì màn Máy đọc được mã; nhịp sau không có thì mã biến mất; mã sai hình dạng bị từ chối 422.
  **Xong.** Migration `e7b3d1f9a2c4`. 5 bài mới, gồm phiên bản đi theo nhịp tim và daemon cũ không gửi thì giữ nguyên.
- [x] T038 [P] Màn Máy hiện vì sao daemon không tự cập nhật (FR-008n sửa 2026-10-28). Ở `frontend/src/pages/Machines.tsx`: một dòng cảnh báo trên thẻ máy, câu i18n theo mã, nói việc cần làm. Mã lạ thì có câu chung.
  **Xong.**
- [x] T039 Kiểm cả vòng trên máy thật, không phát hành gì lên GitHub: một nơi phát hành giả trên máy (hai bản `0.2.90`, `0.2.91` dựng từ nhánh này, đủ `checksums.txt`), `HOME` riêng. Cài bằng chính `scripts/install.sh` → nằm trong `~/.local/bin`, thuộc tài khoản thường; daemon chạy lên, đổi `latest` sang `0.2.91` → daemon tự cài và khởi động lại vào `0.2.91`. Cài vào thư mục không ghi được → màn Máy hiện cảnh báo. Trỏ nơi phát hành vào chỗ không tới được → màn Máy hiện cảnh báo. Rồi chạy đủ bộ kiểm.
  **Xong.** 24/24 trên máy thật, `HOME` riêng, `PATH` chỉ có `claude`, nơi phát hành giả trên `127.0.0.1`: lệnh cài đặt daemon vào `~/.local/bin` thuộc tài khoản thường, dọn bản cũ trên `PATH`; daemon `0.2.90` tự lên `0.2.91` sau 125 giây và màn Máy hiện `0.2.91`; trỏ nơi phát hành vào chỗ không tới được thì màn Máy cảnh báo; **ca của người chủ** — daemon chạy từ thư mục không ghi được thì màn Máy cảnh báo ngay khi chạy lên, chạy lệnh cài một lần thì daemon sang `~/.local/bin`, tự khởi động lại từ đó, cảnh báo biến mất. Bộ kiểm: backend 1346 đạt, 22 bỏ qua; ruff sạch; `go vet`, `go test ./...` đạt; vitest 34/34; eslint chỉ còn 1 cảnh báo có từ trước. Lúc kiểm, `docker compose build` trên máy này hỏng vì Compose v5.6.1 dựng qua `bake` và đòi cấp quyền `network.host` có trong `docker-compose.yml`; dựng thẳng bằng `docker build --network host`, không sửa cấu hình. Một lần xem dạng JSON của `status` đã chạy với `PATH` thường nên `gemini --version` bị gọi; không đổi gì, và mọi lần sau đều dùng `PATH` chỉ có `claude`.

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

### Lần sửa 2026-10-12

```
T015, T016, T017  ← nền, độc lập nhau (T017 viết theo contract, không chờ backend)
   ↓
T018 → T019       ← cùng tệp workspace_agent.py / daemon.py, làm tuần tự
T021              ← sau T018 (cùng workspace_agent.py)
T022              ← độc lập với T018–T021 về logic, nhưng chạm workspaces.py như T018: làm sau T018
   ↓
T020              ← cần T017, T018
T023, T024        ← [P], khác tệp
T025              ← cần T016, T017, T018, T021
   ↓
T026 [P], T027    ← cuối
```

**Song song được**: T015 ∥ T016 ∥ T017; T023 ∥ T024 ∥ T026.

**MVP**: Phase 4 + Phase 5 (US2). Xong hai phase ấy là không còn Livia nào bị đặt vào runtime người dùng
không chọn, và Livia nào chưa có chỗ làm cũng chọn được runtime ngay trên trang của nó. Đó là đúng lỗi
người chủ vấp hôm 2026-10-12. Phase 6 (US3) là phần dạy trong onboarding, xây trên chính cửa ấy.

**Không gộp T019 vào T018**: bỏ tự đặt chỗ mà chưa có cửa chọn thì mọi Livia mới sẽ ngoại tuyến vĩnh viễn.
Hai task vẫn đi chung một PR nên không bao giờ lên `main` lệch nhau.

