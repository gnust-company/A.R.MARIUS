# Feature Specification: Ba bước đầu tiên của một tài khoản mới, và người chủ nhà của không gian làm việc

**Feature Branch**: `038-onboarding-tai-khoan-moi`

**Created**: 2026-09-07

**Status**: Draft

**Input**: Người chủ, 2026-09-07: *"cho tôi 1 flow onboard như Multica tức là ngay khi tạo account mới sẽ có bước onboard About you, Workspace để đặt tên workspace và bước tiếp theo là connect để tạo agent đầu tien luôn, thì bước này óc thể cho set up machine luôn, thì có thể tạo ra workspace agent như của họ là Mika, còn không thì skip nhưng vẫn có mika, bao giờ vào workspace thì thêm máy sau cũng được"*

---

## Bối cảnh: vì sao mở đặc tả này

Hôm nay đăng ký xong thì chuyện xảy ra là: server **im lặng** tạo một không gian làm việc tên
`"Personal"`, rồi đổ người dùng về màn chọn không gian làm việc. Không có bước nào, không câu nào,
không ai hỏi gì. Người dùng đứng trước một danh sách một dòng và không biết dòng ấy là gì.

Hai thứ hỏng đi kèm, và cái thứ hai nặng hơn:

1. **Cái tên `"Personal"` không phải của họ.** Nó là mặc định của hệ thống, và vì không ai được hỏi
   nên nó ở đấy mãi. Cơ sở dữ liệu của máy dev đang có **bốn** không gian làm việc cùng tên
   `"Personal"` — không phải trùng hợp, đó là hệ quả trực tiếp.

2. **Không gian làm việc mới không có người chủ nhà nào.** Tác nhân Không gian (*Workspace Agent*)
   **cố tình không tự tạo** — quyết định của issue #63, với lý do ghi rõ trong mã: *"no config-less,
   token-less shell that can neither wake nor authenticate its callbacks"*. Hồi ấy đúng: mọi agent
   đều cần địa chỉ gateway và một khoá, tạo sẵn một con không có hai thứ đó là tạo một cái vỏ.

   **Lý do ấy đã hết hiệu lực.** Từ đặc tả 002, agent không cần gateway và không cần khoá — nó cần
   một **runtime**, và runtime đến từ máy của chính người dùng. Nhưng luật cũ vẫn nằm đó, nên hệ
   quả hôm nay là: **mọi tài khoản mới đều không dùng được chế độ dựng dự án bằng hỏi–đáp**, vì màn
   tạo dự án tự tắt chế độ ấy với câu *"set up a Workspace Agent first"* và không có đường nào để
   người dùng làm việc đó. Một tính năng đã xây xong, đang chết, cho mọi người dùng mới.

Cái người chủ mô tả — ba bước, và một người chủ nhà có mặt từ phút đầu — vừa đúng là cái vá cả hai.

## Clarifications

### Session 2026-09-07

- Q: Bỏ qua bước nối máy thì người chủ nhà có tồn tại không? → A: **Có.** Người chủ nhà được tạo
  cùng lúc với không gian làm việc, không chờ máy nào. Chưa có runtime thì nó **ngoại tuyến** với lý
  do *chưa được đặt vào runtime nào* — đúng câu cuối FR-007f đã viết sẵn từ trước.
- Q: Vậy nó được đặt vào runtime lúc nào? → A: **Lần đầu tiên không gian làm việc có một runtime sẵn
  sàng**, tự động, một lần. Không phải người dùng làm; họ vừa mới nối máy xong và không có lý do gì
  phải đi làm thêm một việc nữa.
- Q: Có nới luật *"tạo agent là phải chọn runtime"* không? → A: **Không.** Luật ấy giữ nguyên cho
  luồng người dùng tạo agent. Người chủ nhà đi qua **một cửa riêng, có tên riêng**, dùng đúng một
  chỗ — chứ không phải bằng cách cho tham số `runtime` một giá trị mặc định.
- Q: Tên người chủ nhà là gì? → A: **Livia**. Multica gọi con của họ là Mika; đây là con của mình
  nên có tên của mình, và tên ấy ở trong đúng một chuỗi hiển thị — đổi là đổi một dòng.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Đăng ký xong thì biết mình đang ở đâu (Priority: P1)

Một người vừa tạo tài khoản. Thay vì bị đổ ra một danh sách trống rỗng, họ đi qua ba bước ngắn:
xác nhận tên mình, đặt tên cho không gian làm việc, và được chỉ cách nối máy. Bước ba bỏ qua được.

**Vì sao là P1**: đây là toàn bộ khoảng thời gian một người quyết định sản phẩm này có dùng được
hay không. Hôm nay khoảng thời gian ấy là một danh sách một dòng tên `"Personal"`.

**Phép kiểm độc lập**: đăng ký một tài khoản mới, đi hết ba bước, đặt tên không gian làm việc là
một chữ tự chọn. Vào trong thì không gian làm việc mang đúng cái tên ấy, và tên người dùng đúng
cái họ vừa nhập.

**Acceptance Scenarios**

1. **Given** một người vừa đăng ký, **When** họ vào bước một, **Then** tên họ đã nhập lúc đăng ký
   nằm sẵn trong hộp và sửa được.
2. **Given** đang ở bước hai, **When** họ đặt tên không gian làm việc, **Then** không gian làm việc
   được tạo lúc đăng ký **đổi tên** — không sinh ra cái thứ hai.
3. **Given** đang ở bước ba, **When** họ bấm bỏ qua, **Then** họ vào trong không gian làm việc, và
   người chủ nhà vẫn có mặt.
4. **Given** đã đi hết ba bước, **When** họ đăng nhập lại lần sau, **Then** **không** phải đi lại —
   ba bước này là một lần, không phải một cửa.

### User Story 2 - Không gian làm việc có người chủ nhà từ phút đầu (Priority: P1)

Không gian làm việc nào cũng có một Tác nhân Không gian, tên **Livia**, có mặt ngay khi không gian
ấy được tạo. Chưa nối máy thì Livia ngoại tuyến và **nói rõ vì sao**. Nối máy xong, chạy daemon,
runtime đầu tiên sẵn sàng — Livia được đặt vào đó, tự động, và sống.

**Vì sao là P1**: nó mở lại chế độ dựng dự án bằng hỏi–đáp, thứ hôm nay chết với mọi tài khoản mới.

**Phép kiểm độc lập**: tạo một không gian làm việc mới, chưa nối máy nào. Danh bạ agent có Livia,
ngoại tuyến, lý do *chưa được đặt vào runtime nào*. Nối một máy và chạy daemon: Livia trực tuyến,
và màn tạo dự án **không còn** tắt chế độ hỏi–đáp.

**Acceptance Scenarios**

1. **Given** một không gian làm việc vừa tạo, **When** mở danh bạ agent, **Then** Livia có mặt, giữ
   ghế chủ nhà, ngoại tuyến với lý do đọc được.
2. **Given** Livia chưa được đặt, **When** runtime đầu tiên của không gian làm việc báo sẵn sàng,
   **Then** Livia được đặt vào đó và không cần ai bấm gì.
3. **Given** Livia đã được đặt, **When** thêm runtime thứ hai, **Then** Livia **không** chuyển đi —
   đặt một lần là một lần.
4. **Given** một không gian làm việc **đã có** người chủ nhà do người dùng tự mời trước đây, **When**
   luật này chạy, **Then** không sinh thêm con nào và không ai bị hạ ghế.

### Edge Cases

- **Người dùng đóng tab giữa ba bước.** Đăng nhập lại thì vào lại đúng bước còn dở, không mất gì đã
  nhập. Không gian làm việc vẫn tồn tại (nó được tạo lúc đăng ký), chỉ là chưa được đặt tên.
- **Tên không gian làm việc để trống.** Không nhận. Không quay về `"Personal"` sau lưng người dùng —
  cái tên im lặng ấy chính là thứ đặc tả này mở ra để bỏ.
- **Tên `Livia` đã bị một agent khác dùng.** Luật cấm trùng tên trong một không gian làm việc là có
  thật. Người chủ nhà lấy một tên còn trống theo cách đọc được, không được làm hỏng việc tạo không
  gian làm việc.
- **Runtime đầu tiên sẵn sàng rồi tắt ngay.** Livia vẫn ở đó, ngoại tuyến với lý do của runtime ấy —
  giống mọi agent khác. Không tự nhảy sang runtime khác (FR-007).
- **Hai runtime sẵn sàng cùng lúc.** Chọn một, xác định được, và không đổi về sau.
- **Không gian làm việc thứ hai, thứ ba.** Cũng có người chủ nhà của riêng nó. Ba bước thì không —
  ba bước là của tài khoản, không phải của mỗi không gian làm việc.

## Requirements *(mandatory)*

### Nhóm A — Ba bước của một tài khoản mới

- **FR-100**: Sau khi đăng ký, hệ thống PHẢI dẫn người dùng qua **ba bước** trước khi vào không gian
  làm việc: *về bạn*, *không gian làm việc*, *nối máy*. Bước ba PHẢI bỏ qua được. Hai bước đầu KHÔNG
  ĐƯỢC bỏ qua — chúng chỉ hỏi những thứ hệ thống đang tự điền hộ, mà điền hộ chính là lỗi.
- **FR-101**: Bước *về bạn* PHẢI hiện sẵn tên người dùng đã nhập lúc đăng ký và cho **sửa**. Hệ thống
  PHẢI có đường đổi tên hiển thị của chính mình — hôm nay không có cửa nào làm việc đó.
- **FR-102**: Bước *không gian làm việc* PHẢI **đổi tên** không gian làm việc đã được tạo lúc đăng ký,
  KHÔNG ĐƯỢC tạo cái thứ hai. Tên rỗng bị từ chối, và KHÔNG ĐƯỢC âm thầm rơi về `"Personal"`.
- **FR-103**: Bước *nối máy* PHẢI đưa ra **lệnh cài** và **lệnh nối** dạng chép được, cùng đường dẫn
  tới tài liệu, và một đường sang màn phê duyệt máy. Nó KHÔNG ĐƯỢC chờ máy xuất hiện bằng cách hỏi
  vòng — Hiến pháp Điều IV. Người dùng chạy lệnh thì chính daemon mở trang phê duyệt ra (FR-001b), nên
  không có gì phải chờ ở đây cả.
- **FR-104**: Ba bước này là **một lần cho một tài khoản**, không phải một cửa. Đi xong rồi thì đăng
  nhập lần sau KHÔNG ĐƯỢC gặp lại. Bỏ dở thì lần sau vào lại đúng chỗ bỏ dở.

- **FR-105**: Bước *nối máy* PHẢI đưa ra **cả ba lệnh**: cài, nối, và **chạy**. Nối chỉ đổi lấy giấy
  tờ rồi thoát; thứ làm máy có runtime là lệnh chạy. Thiếu lệnh thứ ba thì người ta đi hết ba bước,
  máy có mặt trong danh sách, và mọi agent trên nó ngoại tuyến — mà không có gì trên màn hình nói tại
  sao. Lệnh nối, khi tự nó chạy xong, cũng PHẢI nói ra lệnh còn lại.
- **FR-106**: Duyệt một máy trong lúc ba bước **còn dở** PHẢI **kết thúc ba bước**. Bước ba hỏi một
  việc duy nhất — nối một máy — nên chính việc ấy xong là bước xong, không phải một cái nút xác nhận
  lần nữa.

  Trang phê duyệt là **một cửa sổ khác**: daemon tự mở nó ra (FR-001b), nên lúc duyệt xong có hai cửa
  sổ cùng mở, một cái vừa xong việc và một cái vẫn đứng ở bước ba. Cửa sổ đang đợi KHÔNG ĐƯỢC bị bỏ
  lại như thế. Nó PHẢI tự đi tiếp khi máy được duyệt, và KHÔNG ĐƯỢC hỏi vòng để biết điều đó (Hiến
  pháp Điều IV) — tin ấy được **đẩy sang** từ cửa sổ vừa duyệt.

  Hai cửa sổ ở **hai browser khác nhau** thì không đẩy sang được, và đó là giới hạn chấp nhận được:
  cửa sổ đang đợi vẫn còn nút đi tiếp của chính nó, và tải lại trang là đủ để nó biết ba bước đã xong.

### Nhóm B — Người chủ nhà của không gian làm việc

- **FR-110**: Mỗi không gian làm việc PHẢI có một **Tác nhân Không gian**, được tạo **cùng lúc với
  không gian làm việc**, không chờ máy nào và không chờ ai bấm gì. Tên hiển thị: **Livia**.

  Đây là **đảo lại** một nửa quyết định của issue #63, và lý do phải ghi ra: #63 cấm tự tạo vì hồi ấy
  một agent không có gateway và khoá là một cái vỏ không gọi dậy được. Từ 002, agent không có hai thứ
  đó nữa — nó có một runtime, và runtime là thứ đến sau. Cái #63 cấm là *vỏ rỗng vĩnh viễn*; cái này
  tạo ra là *một agent chưa được đặt chỗ*, mà đó là một trạng thái FR-007f **đã** định nghĩa sẵn:
  *"Agent chưa buộc vào chỗ làm nào PHẢI bị coi là offline, không phải lỗi im lặng."*

- **FR-111**: Người chủ nhà chưa được đặt vào runtime nào PHẢI hiện **ngoại tuyến** kèm lý do đọc
  được, y như mọi agent chưa được đặt chỗ. KHÔNG ĐƯỢC im lặng, và KHÔNG ĐƯỢC hiện như đang sống.
- **FR-112**: **Lần đầu tiên** không gian làm việc có một runtime sẵn sàng, người chủ nhà chưa được
  đặt chỗ PHẢI được đặt vào đó — tự động, đúng một lần. Đã đặt rồi thì runtime mới KHÔNG ĐƯỢC làm nó
  chuyển đi (FR-007). Nhiều runtime cùng sẵn sàng thì cách chọn PHẢI xác định được, không phụ thuộc
  thứ tự tình cờ.
- **FR-113**: Luật FR-110 KHÔNG ĐƯỢC đụng tới không gian làm việc **đã có** người chủ nhà: không sinh
  thêm, không hạ ghế ai. Và nó KHÔNG ĐƯỢC làm việc tạo không gian làm việc thất bại — một cái tên
  trùng, hay bất cứ thứ gì ở nhánh này, KHÔNG ĐƯỢC leo lên thành lỗi của cả việc tạo.
- **FR-114**: Cửa tạo người chủ nhà PHẢI là **một cửa riêng có tên riêng**, dùng đúng một chỗ. KHÔNG
  ĐƯỢC nới luật *"tạo agent là phải chọn runtime"* bằng cách cho tham số ấy một giá trị mặc định:
  một mặc định ở đó là mở lại đúng trạng thái FR-007f sinh ra để đóng, cho **mọi** agent.
- **FR-115**: Chỉ dẫn của người chủ nhà PHẢI bằng **tiếng Anh** (Hiến pháp Điều VII) — nó là chữ hệ
  thống gửi cho agent. Tên hiển thị thì là chữ cho người đọc, nên nó nằm ở tầng hiển thị.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-100**: Một tài khoản mới đi từ lúc bấm đăng ký đến lúc ở trong một không gian làm việc **do
  chính họ đặt tên** trong **dưới 60 giây**, không đọc tài liệu nào.
- **SC-101**: **100%** không gian làm việc mới có người chủ nhà, đo bằng cách tạo không gian làm việc
  và đọc danh bạ agent — không cần thao tác nào khác.
- **SC-102**: Số không gian làm việc mang tên hệ thống tự đặt (`"Personal"`) trong các tài khoản tạo
  sau đặc tả này: **0**.
- **SC-103**: Chế độ dựng dự án bằng hỏi–đáp dùng được ngay sau khi nối máy đầu tiên, đo bằng việc
  màn tạo dự án **không** còn tắt chế độ ấy.
- **SC-104**: Người chủ nhà được đặt chỗ **đúng một lần**: thêm runtime thứ hai không làm nó đổi chỗ.

## Assumptions

- Không gian làm việc vẫn được tạo lúc đăng ký như hôm nay. Ba bước **đổi tên** nó, không tạo mới —
  như vậy người dùng đóng tab giữa đường thì không để lại một tài khoản không có không gian nào.
- Tên `Livia` là chữ hiển thị, ở một chuỗi. Người chủ đổi tên khác thì đổi một dòng.
- Bước *nối máy* không tự biết máy đã nối xong. Nó không cần biết: daemon tự mở trang phê duyệt
  (FR-001b), nên đường đi tiếp nằm ở tay daemon chứ không ở màn hình này.
- Ba bước là của **tài khoản**. Không gian làm việc thứ hai không kéo lại ba bước ấy.

## Key Entities

- **Trạng thái ba bước** — của một người dùng: đã đi tới bước nào, đã xong chưa. Sống lâu hơn một
  phiên đăng nhập, vì FR-104 nói lần sau không được gặp lại.
- **Tác nhân Không gian** — không phải thực thể mới: vẫn là một `Marius`, vẫn được trỏ tới bởi
  `workspace.workspace_agent_id` như #32 đã chốt. Cái mới là nó **có thể chưa được đặt chỗ**.
