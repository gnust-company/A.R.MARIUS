# Feature Specification: Các bước đầu tiên của một tài khoản mới, và người chủ nhà của không gian làm việc

**Feature Branch**: `038-onboarding-tai-khoan-moi` · sửa lần hai trên `spec003-buoc-agent-dau-tien`

**Created**: 2026-09-07 · **Sửa**: 2026-10-12

**Status**: Draft

**Input**: Người chủ, 2026-09-07: *"cho tôi 1 flow onboard như Multica tức là ngay khi tạo account mới sẽ có bước onboard About you, Workspace để đặt tên workspace và bước tiếp theo là connect để tạo agent đầu tien luôn, thì bước này óc thể cho set up machine luôn, thì có thể tạo ra workspace agent như của họ là Mika, còn không thì skip nhưng vẫn có mika, bao giờ vào workspace thì thêm máy sau cũng được"*

**Input (sửa 2026-10-12)**: Người chủ, sau khi tự đi lại luồng như một người dùng mới: *"Phần onboarding đang có UX chưa thực sự tốt, đáng nhẽ phần onboarding nên dạy người dùng lần lượt từ thêm máy, xong tạo workspace agent đầu tien với skill default ko tháo được và cũng ko cần show, với instruction default nhưng cho phép sửa, và cho phép chọn runtime lần đầu chứ đúng ko, rõ ràng nó thuộc về 003"*

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

### Vì sao sửa lại (2026-10-12)

Người chủ tự đi lại luồng như một người dùng mới, trên một tài khoản mới, và gặp đúng ba chuyện:

1. **Onboarding dừng ở nối máy và không nói gì về agent.** Đi hết các bước, vào trong không gian làm
   việc, người dùng chưa từng được cho biết là đã có sẵn một agent tên Livia. Họ không biết Livia làm
   gì và chạy ở đâu, và cũng không biết là mình đã có quyền chọn những thứ ấy hay chưa.
2. **Runtime của Livia do hệ thống chọn, theo một luật không có nghĩa gì với người dùng.** FR-112 đặt
   Livia vào runtime sẵn sàng có id nhỏ nhất. Trên máy của người chủ có cả claude lẫn gemini, và id
   của gemini nhỏ hơn, nên Livia chạy trên gemini. Người chủ không nhắn được cho nó, và lúc tìm ra lý
   do thì không có chỗ nào để đổi: FR-007 của đặc tả 002 không cho đổi chỗ làm.
3. **Bước nối máy chỉ in lệnh rồi bỏ đó.** Người dùng chép ba lệnh, chạy, và màn hình không cho biết
   lệnh nào đã xong. Duyệt máy xong thì luồng kết thúc luôn (FR-106), trong khi máy chỉ thật sự có
   runtime sau khi chạy lệnh `start`.

Cách sửa là để onboarding **dạy lần lượt**: thêm máy, đến lúc máy thật sự chạy, rồi **dựng agent đầu
tiên** ngay trong luồng ấy. Người dùng được chọn runtime cho agent đó. Skill mặc định để agent làm việc
với hệ thống thì gắn sẵn và không hiện ra. System prompt làm nên một người chủ nhà thì hiện ra nhưng
khoá lại, còn chỉ dẫn mặc định thì người dùng sửa được.

## Clarifications

### Session 2026-09-07

- Q: Bỏ qua bước nối máy thì người chủ nhà có tồn tại không? → A: **Có.** Người chủ nhà được tạo
  cùng lúc với không gian làm việc, không chờ máy nào. Chưa có runtime thì nó **ngoại tuyến** với lý
  do *chưa được đặt vào runtime nào* — đúng câu cuối FR-007f đã viết sẵn từ trước.
- Q: Vậy nó được đặt vào runtime lúc nào? → A: **Lần đầu tiên không gian làm việc có một runtime sẵn
  sàng**, tự động, một lần. Không phải người dùng làm; họ vừa mới nối máy xong và không có lý do gì
  phải đi làm thêm một việc nữa. *(**Đã thay** ở phiên 2026-10-12: người dùng tự chọn runtime, trong
  onboarding cũng như ngoài onboarding. Xem FR-112.)*
- Q: Có nới luật *"tạo agent là phải chọn runtime"* không? → A: **Không.** Luật ấy giữ nguyên cho
  luồng người dùng tạo agent. Người chủ nhà đi qua **một cửa riêng, có tên riêng**, dùng đúng một
  chỗ — chứ không phải bằng cách cho tham số `runtime` một giá trị mặc định.
- Q: Tên người chủ nhà là gì? → A: **Livia**. Multica gọi con của họ là Mika; đây là con của mình
  nên có tên của mình, và tên ấy ở trong đúng một chuỗi hiển thị — đổi là đổi một dòng.

### Session 2026-10-12

- Q: Onboarding dạy người dùng tới đâu? → A: **Lần lượt từ thêm máy, rồi tạo agent đầu tiên của không
  gian làm việc.** Không dừng ở chỗ nối máy.
- Q: Agent đầu tiên có những gì? → A: **Một skill mặc định không tháo được, cũng không cần hiện ra.**
  **Một chỉ dẫn mặc định, nhưng cho sửa.**
- Q: Ai chọn runtime cho agent đầu tiên? → A: **Người dùng chọn, ngay lần đầu.** Không để hệ thống
  chọn hộ theo một luật người dùng không thấy.
- Q: Ngoài onboarding (bỏ qua bước agent, hoặc không gian làm việc thứ hai trở đi) thì người chủ nhà
  được đặt vào runtime thế nào? → A: **Người dùng chọn một lần trên trang của agent.** Hệ thống không tự
  đặt nữa, ở bất cứ đâu.
- Q: Phần mặc định có hiện ở trang agent không? → A: **Tách làm hai.** *Skill* mặc định — những skill
  để agent làm việc được với hệ thống — thì **ẩn hết**, ở mọi nơi: chúng là thứ hệ thống tự gắn, không
  phải thứ để người dùng xem hay chọn. *System prompt* thì **phải hiện**.
- Q: Thư viện skill của không gian làm việc có ẩn luôn các skill mặc định không? → A: **Có.** Bỏ hẳn
  mục "Tích hợp sẵn"; thư viện chỉ còn skill do người dùng tự thêm.

### Session 2026-10-26 — sau lần người chủ thử đầu tiên

Người chủ dựng lại từ một cơ sở dữ liệu trắng, đi hết các bước, và báo bốn chỗ vướng. Cả bốn sửa trong
một lần.

- Q: Duyệt máy lần đầu xong, nút *sang danh sách máy* đưa vào thẳng trong không gian làm việc trong khi
  onboarding còn dở — có đúng không? → A: **Không.** Đang dở onboarding thì mọi lối ra của trang phê
  duyệt dẫn về các bước đầu (FR-106).
- Q: Vì sao agent đầu tiên không đổi tên được? → A: **Không có lý do.** Đặc tả chỉ nói bước ấy *hiện*
  tên; chữ *không sửa* do bản tasks tự thêm. Tên sửa được, lưu cùng lần với runtime và chỉ dẫn
  (FR-122, FR-126).
- Q: Các ô chọn đang dùng ô mặc định của trình duyệt, nhìn không hợp dự án. → A: **Thay hết** bằng một
  ô chọn chung theo giao diện dự án (FR-129).
- Q: Danh sách model của Claude Code chỉ có ba cái, chọn một cái rồi phải xoá mới chọn lại được; có lấy
  được danh sách đủ không? → A: **Lấy được, và lấy.** Claude Code trả lời câu hỏi *liệt kê model* qua
  kênh điều khiển của nó, đúng danh sách mà màn `/model` của nó hiện, kèm mức suy nghĩ từng model nhận
  (FR-007k của đặc tả 002, sửa 2026-10-26).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Đăng ký xong thì biết mình đang ở đâu (Priority: P1)

Một người vừa tạo tài khoản. Thay vì bị đổ ra một danh sách trống rỗng, họ đi qua bốn bước ngắn:
xác nhận tên mình, đặt tên cho không gian làm việc, được dạy nối máy, và dựng agent đầu tiên. Hai
bước sau bỏ qua được (User Story 3).

**Vì sao là P1**: đây là toàn bộ khoảng thời gian một người quyết định sản phẩm này có dùng được
hay không. Hôm nay khoảng thời gian ấy là một danh sách một dòng tên `"Personal"`.

**Phép kiểm độc lập**: đăng ký một tài khoản mới, đi hết các bước, đặt tên không gian làm việc là
một chữ tự chọn. Vào trong thì không gian làm việc mang đúng cái tên ấy, và tên người dùng đúng
cái họ vừa nhập.

**Acceptance Scenarios**

1. **Given** một người vừa đăng ký, **When** họ vào bước một, **Then** tên họ đã nhập lúc đăng ký
   nằm sẵn trong hộp và sửa được.
2. **Given** đang ở bước hai, **When** họ đặt tên không gian làm việc, **Then** không gian làm việc
   được tạo lúc đăng ký **đổi tên** — không sinh ra cái thứ hai.
3. **Given** đang ở bước ba, **When** họ bấm bỏ qua, **Then** họ vào trong không gian làm việc, và
   người chủ nhà vẫn có mặt.
4. **Given** đã đi hết các bước, **When** họ đăng nhập lại lần sau, **Then** **không** phải đi lại —
   các bước này là một lần, không phải một cửa.

### User Story 2 - Không gian làm việc có người chủ nhà từ phút đầu (Priority: P1)

Không gian làm việc nào cũng có một Tác nhân Không gian, tên **Livia**, có mặt ngay khi không gian
ấy được tạo. Chưa nối máy thì Livia ngoại tuyến và **nói rõ vì sao**. Nối máy xong, chạy daemon,
người dùng chọn runtime cho Livia — Livia được đặt vào đó và sống.

**Vì sao là P1**: nó mở lại chế độ dựng dự án bằng hỏi–đáp, thứ hôm nay chết với mọi tài khoản mới.

**Phép kiểm độc lập**: tạo một không gian làm việc mới, chưa nối máy nào. Danh bạ agent có Livia,
ngoại tuyến, lý do *chưa được đặt vào runtime nào*. Nối một máy, chạy daemon, chọn runtime cho
Livia: Livia trực tuyến, và màn tạo dự án **không còn** tắt chế độ hỏi–đáp.

**Acceptance Scenarios**

1. **Given** một không gian làm việc vừa tạo, **When** mở danh bạ agent, **Then** Livia có mặt, giữ
   ghế chủ nhà, ngoại tuyến với lý do đọc được.
2. **Given** Livia chưa được đặt, **When** runtime đầu tiên của không gian làm việc báo sẵn sàng,
   **Then** Livia **không** tự bị đặt vào đó. Runtime của Livia do người dùng chọn (FR-112, FR-125).
3. **Given** Livia đã được đặt, **When** thêm runtime thứ hai, **Then** Livia **không** chuyển đi —
   đặt một lần là một lần.
4. **Given** một không gian làm việc **đã có** người chủ nhà do người dùng tự mời trước đây, **When**
   luật này chạy, **Then** không sinh thêm con nào và không ai bị hạ ghế.

### User Story 3 - Onboarding dạy từ thêm máy tới agent đầu tiên (Priority: P1)

Người dùng tới bước nối máy. Màn hình dạy **lần lượt**: cài, nối, chạy. Xong lệnh nào thì màn hình
biết lệnh ấy đã xong. Máy chạy rồi thì luồng tự sang bước cuối: **dựng agent đầu tiên của không gian
làm việc**. Ở bước này người dùng thấy chỉ dẫn mặc định của agent nằm sẵn trong ô và sửa được. Họ
chọn runtime cho agent từ danh sách runtime đang sẵn sàng, và không phải lo chuyện skill: agent đã
có sẵn các skill mặc định để làm việc với hệ thống, và không màn nào bày chúng ra. System prompt làm nên
một người chủ nhà thì hiện ngay trên ô chỉ dẫn, để đọc chứ không để sửa. Bấm xong là tới thẳng chỗ nhắn tin với
agent ấy.

**Vì sao là P1**: đây là chỗ người chủ vấp khi tự đi lại luồng. Đi hết onboarding mà vẫn không nhắn
được cho agent duy nhất mình có, vì nó đang chạy trên một runtime mình không chọn và không đổi được.

**Phép kiểm độc lập**: đăng ký một tài khoản mới trên một máy có **hai** runtime sẵn sàng. Đi hết
onboarding, chọn runtime **không** phải cái có id nhỏ nhất, sửa một chữ trong chỉ dẫn. Vào trong thì
Livia chạy đúng runtime đã chọn, chỉ dẫn có đúng chữ đã sửa, Livia trực tuyến, và tin nhắn đầu tiên
gửi cho nó có trả lời.

**Acceptance Scenarios**

1. **Given** đang ở bước nối máy, **When** người dùng duyệt máy ở cửa sổ khác, **Then** cửa sổ đang
   đợi đánh dấu xong phần *nối* mà không cần ai tải lại, và chỉ sang phần *chạy*.
2. **Given** máy đã được duyệt, **When** daemon chạy lên và báo các runtime của nó, **Then** cửa sổ
   đang đợi tự sang bước *agent đầu tiên*.
3. **Given** đang ở bước *agent đầu tiên*, **When** nhìn vào màn hình, **Then** system prompt hiện ra
   và không sửa được, ô chỉ dẫn có sẵn chỉ dẫn mặc định và sửa được, danh sách runtime chỉ có những
   runtime đang sẵn sàng của không gian làm việc này (kèm tên máy), và **không** có danh sách skill nào.
4. **Given** có đúng một runtime sẵn sàng, **When** mở bước này, **Then** runtime ấy được chọn sẵn và
   người dùng nhìn thấy nó trước khi bấm. **Given** có từ hai runtime sẵn sàng trở lên, **Then** không
   cái nào được chọn sẵn, và nút xong chỉ bấm được khi người dùng đã chọn.
5. **Given** người dùng chọn một runtime và bấm xong, **When** vào trong không gian làm việc, **Then**
   Livia được buộc vào đúng runtime ấy, được kiểm sống ngay, và người dùng đứng ở chỗ nhắn tin với
   Livia.
6. **Given** người dùng xoá trắng ô chỉ dẫn, **When** bấm xong, **Then** Livia vẫn làm đúng việc của
   một người chủ nhà, vì system prompt và các skill mặc định không nằm trong ô ấy.
7. **Given** người dùng bỏ qua bước nối máy, **When** vào trong không gian làm việc, **Then** bước
   *agent đầu tiên* cũng không hiện, vì chưa có runtime nào để chọn. Livia có mặt, ngoại tuyến, và
   nói rõ là chưa được chọn runtime.

### Edge Cases

- **Người dùng đóng tab giữa các bước.** Đăng nhập lại thì vào lại đúng bước còn dở, không mất gì đã
  lưu ở các bước trước. Không gian làm việc vẫn tồn tại (nó được tạo lúc đăng ký), chỉ là chưa được
  đặt tên. Đóng tab ở bước *agent đầu tiên* thì chữ đang gõ dở trong ô chỉ dẫn có thể mất, vì bước ấy
  chỉ lưu khi bấm xong. Mở lại thì ô hiện lại chỉ dẫn mặc định.
- **Tên không gian làm việc để trống.** Không nhận. Không quay về `"Personal"` sau lưng người dùng —
  cái tên im lặng ấy chính là thứ đặc tả này mở ra để bỏ.
- **Tên `Livia` đã bị một agent khác dùng.** Luật cấm trùng tên trong một không gian làm việc là có
  thật. Người chủ nhà lấy một tên còn trống theo cách đọc được, không được làm hỏng việc tạo không
  gian làm việc.
- **Runtime đầu tiên sẵn sàng rồi tắt ngay.** Livia vẫn ở đó, ngoại tuyến với lý do của runtime ấy —
  giống mọi agent khác. Không tự nhảy sang runtime khác (FR-007).
- **Hai runtime sẵn sàng cùng lúc.** Người dùng chọn, hệ thống không chọn hộ (FR-125). Đã chọn rồi
  thì không đổi về sau (FR-007).
- **Không gian làm việc thứ hai, thứ ba.** Cũng có người chủ nhà của riêng nó. Các bước onboarding thì
  không — chúng là của tài khoản, không phải của mỗi không gian làm việc. Người chủ nhà ở đó được đặt
  chỗ theo FR-112.
- **Tải lại trang ngay sau khi duyệt máy.** Từ lúc duyệt tới lúc daemon nhận giấy tờ mất vài giây, và
  trong khoảng ấy workspace chưa có dòng máy nào. Tải lại đúng lúc ấy thì phần *nối* có thể hiện là chưa
  xong. Muộn nhất là khi daemon chạy lên và báo runtime thì nó tự xong.
- **Duyệt máy rồi nhưng chưa chạy `start`.** Bước nối máy đứng ở phần *chạy*, chỉ ra đúng lệnh còn
  thiếu, và vẫn bỏ qua được. Không có đồng hồ nào tự cho qua.
- **Máy chạy rồi nhưng không runtime nào sẵn sàng**, chẳng hạn chưa cài agent CLI nào hoặc CLI chưa
  đăng nhập. Bước *agent đầu tiên* vẫn hiện, liệt kê từng runtime cùng lý do chưa sẵn sàng, đọc được,
  và chỉ tới tài liệu. Không chọn được runtime nào, nhưng bỏ qua được. Một runtime sẵn sàng trở lại
  thì danh sách tự cập nhật, không cần tải lại trang.
- **Runtime đã chọn tắt đi trước khi bấm xong.** Hệ thống từ chối và nói vì sao. Livia không bị đặt
  vào đâu cả, và danh sách hiện đúng trạng thái mới.
- **Máy của người chủ nhà bị gỡ khỏi không gian làm việc.** Người chủ nhà mất chỗ làm, ngoại tuyến với
  lý do *chưa được chọn runtime*, và trang của nó lại có đường chọn (FR-128). Đây không phải đổi chỗ
  làm, vì chỗ làm cũ đã không còn. Agent **thường** mất chỗ làm theo cách này thì **không** có đường ấy:
  FR-007 vẫn đứng, và việc cho đổi chỗ làm của agent thường là một quyết định riêng, chưa chốt.
- **Hai cửa sổ cùng bấm xong bước *agent đầu tiên*, mỗi cửa sổ chọn một runtime.** Lần bấm tới trước
  được nhận. Cửa sổ kia được báo là Livia đã chạy trên runtime nào. Không bao giờ có hai người chủ
  nhà, và Livia không bao giờ bị chuyển chỗ.

## Requirements *(mandatory)*

### Nhóm A — Các bước của một tài khoản mới

- **FR-100**: Sau khi đăng ký, hệ thống PHẢI dẫn người dùng qua **bốn bước** trước khi vào không gian
  làm việc: *về bạn*, *không gian làm việc*, *nối máy*, *agent đầu tiên* (bước thứ tư thêm ngày
  2026-10-12, xem Nhóm C). Bước ba và bước bốn PHẢI bỏ qua được. Bỏ qua bước ba thì cũng bỏ qua luôn
  bước bốn, vì chưa có runtime nào để chọn. Hai bước đầu KHÔNG ĐƯỢC bỏ qua — chúng chỉ hỏi những thứ
  hệ thống đang tự điền hộ, mà điền hộ chính là lỗi.
- **FR-101**: Bước *về bạn* PHẢI hiện sẵn tên người dùng đã nhập lúc đăng ký và cho **sửa**. Hệ thống
  PHẢI có đường đổi tên hiển thị của chính mình — hôm nay không có cửa nào làm việc đó.
- **FR-102**: Bước *không gian làm việc* PHẢI **đổi tên** không gian làm việc đã được tạo lúc đăng ký,
  KHÔNG ĐƯỢC tạo cái thứ hai. Tên rỗng bị từ chối, và KHÔNG ĐƯỢC âm thầm rơi về `"Personal"`.
- **FR-103**: Bước *nối máy* PHẢI đưa ra **lệnh cài** và **lệnh nối** dạng chép được, cùng đường dẫn
  tới tài liệu, và một đường sang màn phê duyệt máy. Nó KHÔNG ĐƯỢC chờ máy xuất hiện bằng cách hỏi
  vòng — Hiến pháp Điều IV. Người dùng chạy lệnh thì chính daemon mở trang phê duyệt ra (FR-001b), nên
  không có gì phải chờ ở đây cả.
- **FR-104**: Các bước này là **một lần cho một tài khoản**, không phải một cửa. Đi xong rồi thì đăng
  nhập lần sau KHÔNG ĐƯỢC gặp lại. Bỏ dở thì lần sau vào lại đúng chỗ bỏ dở.

- **FR-105**: Bước *nối máy* PHẢI đưa ra **cả ba lệnh**: cài, nối, và **chạy**. Nối chỉ đổi lấy giấy
  tờ rồi thoát; thứ làm máy có runtime là lệnh chạy. Thiếu lệnh thứ ba thì người ta đi hết ba bước,
  máy có mặt trong danh sách, và mọi agent trên nó ngoại tuyến — mà không có gì trên màn hình nói tại
  sao. Lệnh nối, khi tự nó chạy xong, cũng PHẢI nói ra lệnh còn lại.
- **FR-106** *(sửa 2026-10-12)*: Duyệt một máy trong lúc onboarding **còn dở** PHẢI đánh dấu xong
  phần *nối* của bước ba. Nó KHÔNG còn kết thúc onboarding như bản 2026-09-07 viết: duyệt xong máy mới
  chỉ có giấy tờ, chưa có runtime nào, và kết thúc ở đó là thả người dùng vào một không gian làm việc
  mà mọi agent đều ngoại tuyến (FR-120).

  Trang phê duyệt là **một cửa sổ khác**: daemon tự mở nó ra (FR-001b), nên lúc duyệt xong có hai cửa
  sổ cùng mở, một cái vừa xong việc và một cái vẫn đứng ở bước ba. Cửa sổ đang đợi KHÔNG ĐƯỢC bị bỏ
  lại như thế. Nó PHẢI tự cập nhật khi máy được duyệt, và KHÔNG ĐƯỢC hỏi vòng để biết điều đó (Hiến
  pháp Điều IV) — tin ấy được **đẩy sang**. Cửa sổ vừa duyệt PHẢI nói tiếp lệnh `start` và nói rằng
  cửa sổ onboarding đang đợi ở bước sau. Nó KHÔNG ĐƯỢC nói là onboarding đã xong.

  *(Sửa 2026-10-26.)* Khi người duyệt còn dở onboarding, **mọi lối ra** của trang phê duyệt PHẢI dẫn về
  các bước đầu, đúng bước đang dở, và KHÔNG ĐƯỢC dẫn vào trong không gian làm việc. Bản trước chỉ đổi
  chữ, còn hai nút *sang danh sách máy* và *quay lại* vẫn đưa thẳng vào trong. Người dùng thế là đứng
  trong một không gian làm việc với onboarding còn dở, và cửa sổ onboarding nằm khuất phía sau.

  Hai cửa sổ ở **hai browser khác nhau** thì có thể không đẩy sang được, và đó là giới hạn chấp nhận
  được: cửa sổ đang đợi vẫn còn nút đi tiếp của chính nó, và tải lại trang là đủ để nó biết mình đang
  ở đâu.

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
- **FR-112** *(sửa 2026-10-12)*: Runtime của người chủ nhà PHẢI do **một người chọn**, không do hệ
  thống tự đặt. Bản 2026-09-07 tự đặt người chủ nhà vào runtime sẵn sàng đầu tiên, và khi có nhiều
  runtime thì lấy cái có id nhỏ nhất. Luật ấy ổn định, nhưng người dùng không thấy nó và nó không có
  nghĩa gì với họ: trên máy có cả claude lẫn gemini, nó chọn gemini chỉ vì id của gemini nhỏ hơn, rồi
  FR-007 khoá luôn lựa chọn ấy lại.

  Trong onboarding, người dùng chọn ở bước *agent đầu tiên* (FR-125). Ngoài onboarding — người dùng đã
  bỏ qua bước ấy, hoặc không gian làm việc thứ hai trở đi — người dùng chọn trên trang của agent
  (FR-128). Hệ thống KHÔNG ĐƯỢC tự đặt người chủ nhà vào runtime nào, ở bất cứ đâu, kể cả khi
  không gian làm việc chỉ có đúng một runtime.

  Đặt rồi thì không đổi được (FR-007): runtime mới xuất hiện KHÔNG ĐƯỢC làm người chủ nhà chuyển đi.
- **FR-113**: Luật FR-110 KHÔNG ĐƯỢC đụng tới không gian làm việc **đã có** người chủ nhà: không sinh
  thêm, không hạ ghế ai. Và nó KHÔNG ĐƯỢC làm việc tạo không gian làm việc thất bại — một cái tên
  trùng, hay bất cứ thứ gì ở nhánh này, KHÔNG ĐƯỢC leo lên thành lỗi của cả việc tạo.
- **FR-114**: Cửa tạo người chủ nhà PHẢI là **một cửa riêng có tên riêng**, dùng đúng một chỗ. KHÔNG
  ĐƯỢC nới luật *"tạo agent là phải chọn runtime"* bằng cách cho tham số ấy một giá trị mặc định:
  một mặc định ở đó là mở lại đúng trạng thái FR-007f sinh ra để đóng, cho **mọi** agent.
- **FR-115** *(sửa 2026-10-12)*: **System prompt** và **chỉ dẫn mặc định** của người chủ nhà PHẢI bằng
  **tiếng Anh** (Hiến pháp Điều VII), vì chúng là chữ hệ thống gửi cho agent. Chữ người dùng tự viết vào
  ô chỉ dẫn giữ nguyên thứ tiếng họ viết. Tên hiển thị là chữ cho người đọc, nên nó nằm ở tầng hiển thị.

### Nhóm C — Dạy từ thêm máy tới agent đầu tiên (thêm 2026-10-12)

- **FR-120**: Bước *nối máy* PHẢI dạy **lần lượt** ba phần: *cài*, *nối*, *chạy*. Mỗi phần có lệnh
  chép được của nó (FR-103, FR-105), và PHẢI hiện là đã xong **khi hệ thống biết nó đã xong**:
  - *nối* xong khi một máy được duyệt vào không gian làm việc này;
  - *chạy* xong khi máy ấy báo lên các runtime của nó.

  Phần *cài* thì hệ thống không thấy được, nên nó không có dấu xong riêng: *nối* xong là đủ biết đã
  cài. Mọi thay đổi PHẢI được **đẩy** tới màn hình, KHÔNG ĐƯỢC hỏi vòng (Hiến pháp Điều IV).

- **FR-121**: Khi phần *chạy* xong, onboarding PHẢI **tự sang** bước *agent đầu tiên*, không bắt người
  dùng bấm thêm. Không gian làm việc đã có máy báo runtime từ trước (chẳng hạn máy đã nối ở một lần bỏ
  dở) thì bước *nối máy* PHẢI cho đi tiếp ngay.

- **FR-122**: Bước *agent đầu tiên* là nơi người dùng **dựng người chủ nhà** của không gian làm việc
  (Livia, FR-110). Nó KHÔNG sinh thêm agent thứ hai. Về nội dung, bước này hiện đúng bốn thứ, chưa kể
  các nút và đường dẫn tới tài liệu:
  1. tên của agent, có sẵn tên hiện tại của người chủ nhà và **sửa được** *(sửa 2026-10-26)*. Tên
     trùng với một agent khác trong không gian làm việc thì bị từ chối như ở mọi chỗ đổi tên agent;
  2. **system prompt** của người chủ nhà, chỉ để đọc (FR-123a);
  3. ô **chỉ dẫn**, có sẵn chỉ dẫn mặc định (FR-124);
  4. danh sách **runtime đang sẵn sàng** của không gian làm việc này, mỗi dòng kèm tên máy và loại
     agent CLI để phân biệt cùng một CLI trên hai máy.

  Bước này KHÔNG hiện danh sách skill (FR-123).

- **FR-123**: Mọi agent, người chủ nhà cũng vậy, PHẢI mang sẵn các **skill mặc định**, tức là những
  skill giúp agent làm việc được với hệ thống. Chúng được gắn tự động, và người dùng KHÔNG tháo ra
  được. Chúng KHÔNG ĐƯỢC hiện ở bất cứ chỗ nào trong sản phẩm, kể cả:
  - bước *agent đầu tiên*;
  - màn tạo agent;
  - trang của agent;
  - thư viện skill của không gian làm việc: thư viện chỉ còn skill do người dùng tự thêm, và KHÔNG có
    mục riêng nào cho skill dựng sẵn.

  Lý do: đây là thứ hệ thống tự gắn để agent dùng được, không phải thứ để người dùng xem hay chọn. Bày
  chúng ra cạnh skill do người dùng chọn chỉ làm người ta tưởng mình phải quyết định về chúng.
  Danh sách skill người dùng nhìn thấy trên một agent PHẢI chỉ có skill do người dùng chọn.

- **FR-123a**: Người chủ nhà PHẢI có một **system prompt**: phần chữ làm nên một người chủ nhà, do sản
  phẩm viết và bằng tiếng Anh (Hiến pháp Điều VII). System prompt PHẢI **hiện ra**, chỉ để đọc, ở bước
  *agent đầu tiên* và ở trang của agent. Người dùng KHÔNG sửa và KHÔNG xoá được nó.

  System prompt tách khỏi ô chỉ dẫn là có chủ ý. Người dùng sửa hay xoá trắng ô chỉ dẫn cũng KHÔNG làm
  người chủ nhà mất việc của nó. Nó hiện ra để người dùng biết vì sao người chủ nhà cư xử như vậy, và
  để họ không phải chép lại chính những câu ấy vào ô chỉ dẫn.

- **FR-124**: Ô chỉ dẫn ở bước *agent đầu tiên* PHẢI có sẵn một **chỉ dẫn mặc định**, và người dùng
  PHẢI sửa được, kể cả xoá trắng. Chỉ dẫn mặc định là chữ hệ thống gửi cho agent nên PHẢI bằng tiếng
  Anh (Hiến pháp Điều VII). Thứ được lưu là đúng chữ người dùng để lại trong ô lúc bấm xong. Ô ấy từ đó
  là chỉ dẫn của chính họ, sửa tiếp được ở trang của agent như mọi agent khác (FR-007i).

- **FR-125**: Chọn runtime ở bước *agent đầu tiên* là đặt chỗ cho người chủ nhà. Đã đặt rồi thì nó
  **không đổi sang chỗ làm khác** (FR-007). Nếu có đúng một runtime sẵn sàng thì runtime ấy được chọn sẵn, và người dùng nhìn thấy nó
  trước khi bấm. Nếu có từ hai runtime trở lên thì KHÔNG cái nào được chọn sẵn, và nút xong PHẢI khoá
  cho tới khi người dùng chọn. Danh sách KHÔNG ĐƯỢC có runtime chưa sẵn sàng như một lựa chọn bấm
  được. Runtime chưa sẵn sàng thì hiện kèm lý do đọc được, để người dùng biết vì sao không chọn được.

- **FR-126**: Bấm xong bước *agent đầu tiên* PHẢI:
  1. buộc người chủ nhà vào runtime đã chọn, lưu chỉ dẫn và tên, **cùng một lần**: không có trạng
     thái lưng chừng kiểu chỉ dẫn đã lưu mà chưa có runtime, hay tên đã đổi mà chưa có runtime;
  2. kiểm người chủ nhà sống hay chết **ngay** (FR-006e của đặc tả 002);
  3. kết thúc onboarding và đưa người dùng tới **chỗ nhắn tin với người chủ nhà** (FR-007p của đặc tả
     002). Người chủ nhà chưa kịp trực tuyến thì chỗ ấy nói vì sao, không im lặng.

- **FR-127**: Bước *agent đầu tiên* PHẢI an toàn khi bấm hai lần hoặc bấm từ hai cửa sổ. Lần tới trước
  được nhận. Lần sau KHÔNG ĐƯỢC sinh người chủ nhà thứ hai và KHÔNG ĐƯỢC chuyển chỗ người chủ nhà. Cửa
  sổ tới sau được báo là người chủ nhà đã chạy trên runtime nào, rồi đi tiếp như đã xong.

- **FR-128**: Người chủ nhà **chưa được đặt chỗ** PHẢI hiện ngoại tuyến với lý do là *chưa được chọn
  runtime* (FR-111). Trang của nó PHẢI có đường chọn runtime cho nó, với đúng danh sách và đúng luật
  chọn của FR-125. Đường này biến mất khi người chủ nhà đã được đặt chỗ, và **chỉ có ở người chủ nhà**.

  Đây không phải đổi chỗ làm: lúc ấy người chủ nhà không có chỗ làm nào. Hoặc nó chưa từng có, vì nó là
  agent duy nhất được sinh ra mà chưa có chỗ làm (FR-114). Hoặc máy của nó vừa bị gỡ khỏi không gian
  làm việc, và chỗ làm cũ đã không còn.

### Nhóm D — Sửa sau lần thử đầu (thêm 2026-10-26)

- **FR-129**: Mọi ô chọn trong sản phẩm — chọn một trong nhiều, kể cả ô có gợi ý cho gõ thêm — PHẢI
  dùng **một ô chọn chung theo giao diện của dự án**, không dùng ô mặc định của trình duyệt. Danh sách
  mở ra PHẢI hiện **đủ** các lựa chọn, kể cả khi ô đã có một giá trị. Ô có gợi ý thì chọn lại một gợi ý
  khác KHÔNG ĐƯỢC đòi người dùng xoá chữ đang có trước: ô gợi ý mặc định của trình duyệt lọc danh sách
  theo chính chữ đang nằm trong ô, nên chọn *sonnet* rồi thì chỉ còn *sonnet* để chọn.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-100**: Một tài khoản mới đi từ lúc bấm đăng ký đến lúc ở trong một không gian làm việc **do
  chính họ đặt tên** trong **dưới 60 giây**, không đọc tài liệu nào.
- **SC-101**: **100%** không gian làm việc mới có người chủ nhà, đo bằng cách tạo không gian làm việc
  và đọc danh bạ agent — không cần thao tác nào khác.
- **SC-102**: Số không gian làm việc mang tên hệ thống tự đặt (`"Personal"`) trong các tài khoản tạo
  sau đặc tả này: **0**.
- **SC-103**: Chế độ dựng dự án bằng hỏi–đáp dùng được ngay sau bước *agent đầu tiên*, đo bằng việc
  màn tạo dự án **không** còn tắt chế độ ấy.
- **SC-104**: Người chủ nhà đang có chỗ làm thì **không bao giờ đổi sang chỗ khác**: thêm runtime thứ hai
  không làm nó đổi chỗ.
- **SC-105**: Một tài khoản mới đi hết bốn bước, không bỏ bước nào, thì **100%** trường hợp đứng ở chỗ
  nhắn tin với một người chủ nhà **đang trực tuyến**, và tin nhắn đầu tiên có trả lời. Không cần mở
  trang nào khác ngoài trang phê duyệt máy do daemon tự mở.
- **SC-106**: Trong các tài khoản tạo sau lần sửa này, số người chủ nhà chạy trên một runtime mà
  **không ai chọn**: **0**.
- **SC-107**: Ở bước *nối máy*, người dùng biết mình đang ở phần nào mà không cần tải lại trang: duyệt
  máy thì phần *nối* đánh dấu xong, daemon chạy lên thì luồng sang bước *agent đầu tiên*. Cả hai đều
  hiện **trong vòng 5 giây**.
- **SC-108**: Số chỗ trong sản phẩm hiện skill mặc định cho người dùng xem: **0**. Mọi agent vẫn mang
  đủ các skill ấy, và mọi người chủ nhà vẫn mang đủ system prompt, kể cả khi ô chỉ dẫn bị xoá trắng.

## Assumptions

- Không gian làm việc vẫn được tạo lúc đăng ký như hôm nay. Onboarding **đổi tên** nó, không tạo mới —
  như vậy người dùng đóng tab giữa đường thì không để lại một tài khoản không có không gian nào.
- Tên `Livia` là chữ hiển thị, ở một chuỗi. Người chủ đổi tên khác thì đổi một dòng.
- ~~Bước *nối máy* không tự biết máy đã nối xong.~~ *(Bỏ 2026-10-12.)* Bản cũ cho rằng màn hình này
  không cần biết, vì daemon tự mở trang phê duyệt (FR-001b). Người chủ tự đi lại luồng thì thấy đó
  chính là chỗ người dùng bị bỏ rơi. Nay màn hình được đẩy tin tới và biết từng phần đã xong (FR-120).
- Các bước onboarding là của **tài khoản**. Không gian làm việc thứ hai không kéo lại các bước ấy.
- *(2026-10-12)* Bước *agent đầu tiên* **không** cho chọn model hay thinking level. Agent dùng mặc định
  của runtime, và người dùng đổi được về sau ở trang của agent (FR-007k của đặc tả 002). Thêm hai ô ấy
  vào bước này là làm dài thêm đúng chỗ người dùng mới chưa đủ biết để chọn.
- *(2026-10-12)* Tên vẫn là `Livia`. Bước *agent đầu tiên* hiện tên nhưng không bắt đặt tên, vì người
  dùng không có lý do gì phải nghĩ ra một cái tên trước khi biết agent ấy làm gì.
- *(2026-10-12)* Lần sửa này **không** đụng tới FR-007 của đặc tả 002. Người chủ nhà nào **đã** được đặt
  chỗ thì giữ nguyên chỗ ấy, kể cả người chủ nhà đang chạy gemini ở không gian làm việc của người chủ.
  Cho đổi chỗ làm của một agent là một quyết định riêng, chưa chốt.
- *(2026-10-12)* Tài khoản đã đi xong onboarding trước lần sửa này không bị kéo vào lại để làm bước
  thứ tư.

## Key Entities

- **Trạng thái onboarding** — của một người dùng: đã đi tới bước nào (nay có bốn), đã xong chưa. Sống lâu hơn một
  phiên đăng nhập, vì FR-104 nói lần sau không được gặp lại.
- **Tác nhân Không gian** — không phải thực thể mới: vẫn là một `Marius`, vẫn được trỏ tới bởi
  `workspace.workspace_agent_id` như #32 đã chốt. Cái mới là nó **có thể chưa được đặt chỗ**.
  Từ 2026-10-12 nó có hai phần chữ tách nhau: **system prompt** hiện ra nhưng khoá lại (FR-123a) và
  **chỉ dẫn** của người dùng, bắt đầu bằng chỉ dẫn mặc định (FR-124).
- **Skill mặc định** — không phải thực thể mới: là các skill dựng sẵn mà mọi agent vẫn đang được gắn
  để làm việc với hệ thống. Cái mới là chúng **không hiện ở đâu cả** (FR-123).
