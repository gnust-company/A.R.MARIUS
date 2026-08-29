# Feature Specification: Daemon tại máy người dùng và chuẩn ACP để nói chuyện với agent

**Feature Branch**: `002-daemon-acp-runtime`

**Created**: 2026-08-20

**Status**: Draft — ba điểm phạm vi đã chốt 2026-08-21; sẵn sàng cho `/speckit-plan`

**Input**: User description: "oke, du học thế đủ rồi, đến giờ kế thừa nào, tôi muốn 1 tính năng tương tự như họ trong việc giao tiếp với các agent, đó là tôi muốn mình cũng sẽ build daemon và sử dụng chuẩn ACP để giao tiếp (hình như thế)"

---

## Bối cảnh: vì sao mở đặc tả này

Hôm nay Armarius nói chuyện với agent qua **một cổng ngoài duy nhất** — một gateway chạy sẵn ở đâu đó, và
Armarius gửi lời gọi dậy vào đó. Hệ quả:

- Thêm một loại agent mới là phải có gateway tương ứng. Thực tế chỉ có **đúng một** loại chạy được.
- Armarius **không nhìn thấy chỗ agent làm việc**. Agent làm ở đâu, sinh ra file gì, để lại thứ gì — hệ
  thống không biết. Đây chính là căn bệnh Điều II của Hiến pháp cấm: *"agent làm xong nhưng để kết quả ở
  máy nó"*. Hôm nay ta chỉ **chặn** được nó ở cổng Done, chứ chưa **giúp** agent đẩy được kết quả ra.
- Mọi thứ phụ thuộc sức khoẻ của một cổng ngoài mà ta không sở hữu.

Tính năng này đổi chặng dưới cùng: thay vì gọi vào một cổng ngoài, Armarius phát việc xuống một **daemon
chạy trên máy của chính người mời agent**, và daemon là bên khởi chạy agent CLI ngay tại đó.

**Không đổi**: bốn tác nhân, vòng đời đầu việc, các cổng chuyển trạng thái, luật động cơ đẩy, thang phục
hồi ba mức. Đặc tả này chỉ thay **cách Armarius nói chuyện với agent**, không thay các luật vận hành.

---

## Clarifications

### Session 2026-08-21

- Q: Nội dung mà công cụ trả về cho agent (ví dụ agent đọc một file thì kết quả là toàn bộ nội dung file)
  có được phép đi lên server Armarius không? → A: Không. Ghi **toàn văn tham số** gọi công cụ, nhưng
  **chỉ ghi rút gọn kết quả** công cụ trả về; toàn văn kết quả ở lại trên máy người dùng.
- Q: Khi một máy còn sống nhưng đã chạm trần số lượt chạy đồng thời, đầu việc thứ N+1 bám vào động cơ đẩy
  nào? → A: Dùng lại **động cơ số 2 — đã hẹn một lần đánh thức**. Không thêm động cơ thứ bảy; mã lý do gọi
  dậy mang thông tin đang chờ chỗ trống. **⚠ ĐÃ BỊ THAY ngày 2026-08-22** — xem mục cuối phần này: động cơ
  đúng là **số 5**, và không có timeout.
- Q: Những agent đã mời theo đường cổng ngoài cũ thì ra sao sau khi đường ấy bị gỡ? → A: **Xoá sạch, coi
  như cổng cũ chưa từng tồn tại.** Hệ thống chưa chạy thật nên không có dữ liệu cần giữ; không viết luật
  chuyển đổi, không giữ tương thích ngược.
- Q: Lần gọi dậy thứ hai của cùng một đầu việc dùng lại thư mục làm việc cũ hay được cấp thư mục trắng mới?
  → A: **Dùng lại thư mục cũ.** Thư mục làm việc tính theo **đầu việc**, không theo lượt chạy — trùng đúng
  ranh giới của phiên, vì phần lớn agent CLI gắn phiên vào chính thư mục đã mở phiên.
- Q: Đẩy hiện vật hỏng giữa chừng thì đẩy lại được hay phải chạy lại cả lượt? → A: **Đẩy lại được, không
  giới hạn số lần.** Công cụ công bố phải chịu được gọi lặp — cùng một thứ công bố hai lần không đẻ ra hai
  hiện vật; đầu việc giữ động cơ đẩy sống trong lúc chưa xong.
- Q: Bốn chỗ hở `/speckit-analyze` tìm ra thì xử thế nào? → A (2026-08-22): **(1)** bỏ ký ức dài hạn khỏi
  khái niệm nền, làm y hệt Multica theo từng CLI; **(2)** *đang chờ máy rảnh* là **trạng thái hiện lên màn
  hình, KHÔNG có timeout** — đổi từ động cơ số 2 sang **động cơ số 5**, vì thứ chặn nó đã có đồng hồ riêng;
  **(3)** dọn thư mục làm việc **theo thời gian**, không có tin báo, đúng cách Multica; **(4)** ngưỡng im
  lặng **10 phút**, đếm từ sự kiện gần nhất, không giới hạn tổng thời gian chạy.
- Q: Daemon lấy việc bằng cách nào, và có đụng luật đình trệ với động cơ đẩy không? → A: Daemon **xin**,
  server **đưa**. Ba lớp tách bạch: push là đường chính, poll là **fallback** khi push không tới nơi, cờ
  đình trệ là lớp cuối. Tin đẩy chỉ là tín hiệu "có việc, đi hỏi đi", KHÔNG bao giờ là lệnh chạy. Poll KHÔNG đánh dấu
  gì về sống chết.
- Q: Thêm trạng thái "đã có máy nhận" thì đụng gì? → A: Không thêm động cơ đẩy mới — nó nằm trong động cơ
  số 2. Nhưng động cơ số 1 phải bật **lúc máy nhận**, không phải lúc agent nhả chữ đầu tiên, và đồng hồ của
  động cơ số 2 phải đặt lại tại thời điểm ấy.
- Q: Token thì làm thế nào? → A: **Chép nguyên Multica**, hai loại tách biệt — token của daemon do người
  tạo lúc cài, token của lượt chạy do server tự đúc lúc trao việc. Lỗi nào Multica chưa giải thì ta cũng
  chưa giải, **trừ** chỗ xung đột với luật của mình: token bị thu hồi phải xếp là lỗi cần người xử, không
  được tiêu ngân sách tự phục hồi.

### Session 2026-08-25

Người chủ chốt sau khi đối chiếu trực tiếp với mô hình agent của Multica (`multica-ai/multica`, tài liệu
`apps/docs/content/docs/agents-create.mdx` và kiểu dữ liệu `packages/core/types/agent.ts`).

- Q: Luồng thêm agent hiện tại bắt nhập gateway url + api key rồi gửi lời mời. Giữ hay bỏ? → A: **Bỏ
  hẳn.** Thay bằng **đúng mô hình agent của Multica**: đặt tên, viết instructions, gắn skill, chọn chỗ làm.
  Chỉ thế thôi. Không probe gateway, không setup prompt, không mint agent token lúc tạo.
- Q: Hai agent trùng tên trong một workspace thì sao? → A: **Cấm trùng.** Trước nay không kiểm chỉ vì
  không điều khoản nào nói, mà "trong một workspace có hai agent cùng tên thì biết gọi ai".
- Q: Có cho chọn model và thinking level như Multica không? → A: **Có.** Đã có daemon giống Multica thì
  phải chọn được.
- Q: Multica cho buộc lại agent sang runtime khác khi runtime cũ chết; FR-007 của ta nói mối buộc không
  đổi được. Theo ai? → A: **Tạm giữ nguyên không đổi được.** Chỉ thêm agent, không đổi chỗ làm của agent
  đã có. Tính tiếp sau.
- Q: Bỏ role theo dự án, chỉ giữ agent ở tầng workspace có đủ instructions và skill, rồi thêm thẳng agent
  vào dự án — được không? → A: **Được, làm luôn.** Role theo dự án **làm loãng skill**, và khi instructions
  đã nằm trên agent thì role chỉ là chỗ chép lại. **Hiến pháp sửa theo** — Điều V viết lại, lên phiên bản
  2.0.0 ngày 2026-08-25. **Giữ nguyên Trưởng dự án.**
- Q: Màn hình "Thiết lập bằng Tác nhân" đang gọi Tác nhân Không gian qua gateway rồi đứng đợi trả lời; bỏ
  gateway thì nó gãy. Xử sao? → A: **Làm lại phần bên dưới, giữ nguyên phần người dùng thấy.** Người chủ
  nói thẳng: *"lúc đó tao chat với workspace agent, chấm hết"*. Đây là luật chung cho cả đợt, không riêng
  màn hình này — xem FR-040b.

### Session 2026-08-29

Người chủ hỏi thẳng: *"cho tôi kịch bản mà khiến bạn bắt buộc phải dùng 2 token"*, và *"Multica làm như
nào?"*. Nền đối chiếu: [research-multica-daemon.md](research-multica-daemon.md) §6 và §7.

- Q: Agent gọi ngược về Armarius bằng gì? Hôm nay tờ hướng dẫn dạy nó tự viết lời gọi mạng kèm **token
  sống lâu** — thứ FR-014a không chừa chỗ cho. → A: **Một thứ, hai mặt.** Một lệnh gọi được từ dòng lệnh
  (nền, vì mọi agent CLI đều chạy được một lệnh), và **chính thứ ấy** nói giao thức nạp công cụ qua luồng
  chuẩn cho CLI nào biết nạp. Đúng cách Multica làm — công cụ đi theo đầu việc, không cài vào máy.
- Q: Vì sao bắt buộc phải hai token? → A: **token của máy nói thay cả cái máy.** Hai kịch bản:
  (1) một máy phục vụ nhiều agent (FR-007a), nên agent cầm token máy thì gọi ngược về ký được tên agent
  bên cạnh và ghi sang dự án nó không có phần — Điều I bị phá từ bên trong, và không lối nào phân biệt
  được vì token ấy không mang tên ai; (2) thư mục làm việc dùng chung cho mọi lượt của một đầu việc
  (FR-010), nên agent chép token ra một tệp ở lượt đầu là giữ chìa khoá cả cái máy, không hạn — còn token
  lượt chạy thì lượt sau đọc lên chỉ còn một chuỗi chết. Multica ngã đúng chỗ này rồi mới đặt luật
  (MUL-3292, đã ghi ở FR-014c).
- Q: Một lượt chạy được chạm tới đâu — chỉ đầu việc của nó, hay cả dự án chứa đầu việc ấy? → A: **bộ công
  cụ cấp cho lượt ấy chính là phạm vi** (FR-013d). Không phải một bảng quyền tra lúc gọi: Multica trả lời
  câu này bằng cấu trúc, và cấu trúc ấy hợp với ta vì bảng lượt chạy **đã có sẵn hai cấp** — cấp đầu việc
  và cấp dự án — cùng bảy cớ gọi dậy cấp dự án đã tồn tại từ đặc tả 001.
- Q: Hai lối onboarding (Tác nhân Không gian hỏi–đáp lúc dựng đội) không thuộc lượt chạy nào thì xác thực
  bằng gì? → A: **nó cũng là một lượt chạy** — cấp workspace, không đầu việc, không dự án, vì lúc ấy dự án
  chưa tồn tại (FR-040c). Nhờ vậy FR-014a giữ nguyên đúng hai loại token.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cắm một cái máy vào workspace rồi giao được việc thật (Priority: P1)

Người mời agent cài daemon lên máy của mình, đăng nhập vào workspace, và daemon tự dò xem máy đó có sẵn
những agent CLI nào. Mỗi cái tìm được trở thành một **chỗ làm** đăng ký với Armarius. Từ lúc đó, đầu việc
giao cho agent ấy được phát xuống máy đó, agent chạy tại chỗ, và diễn biến hiện lên màn hình theo dõi
gần như tức thời.

**Why this priority**: Không có bước này thì không có gì cả. Đây là toàn bộ giá trị mới: agent chạy **trên
máy của người sở hữu nó**, mã nguồn và dữ liệu không rời máy, và Armarius nhìn thấy chỗ nó làm việc.

**Independent Test**: Cài daemon lên một máy có sẵn một agent CLI, mời agent đó vào một dự án, tạo một đầu
việc, giao cho nó. Kiểm chứng: đầu việc chuyển sang đang làm, diễn biến chạy hiện lên màn hình, và khi
xong thì đầu việc rời trạng thái đang làm.

**Acceptance Scenarios**:

1. **Given** một máy đã cài daemon và có ít nhất một agent CLI, **When** người dùng đăng nhập daemon vào
   workspace, **Then** mỗi agent CLI dò được xuất hiện thành một chỗ làm ở trạng thái sẵn sàng, kèm tên
   máy để người dùng phân biệt.
2. **Given** một agent đã có chỗ làm sẵn sàng, **When** Trưởng dự án giao cho nó một đầu việc, **Then**
   daemon nhận việc trong vòng vài giây và khởi chạy agent CLI tương ứng.
3. **Given** một lượt chạy đang diễn ra, **When** agent sinh ra diễn biến (gọi công cụ, viết chữ, báo
   lỗi), **Then** diễn biến ấy hiện lên màn hình theo dõi mà người dùng không phải bấm tải lại.
4. **Given** một agent chưa có chỗ làm nào sẵn sàng, **When** hệ thống muốn giao việc cho nó, **Then** đầu
   việc **không** rơi vào khoảng lặng: nó đi vào đúng luồng offline đang có và người chủ thấy được lý do
   vì sao chưa chạy.
5. **Given** máy còn sống nhưng đã chạm trần số lượt chạy đồng thời, **When** hệ thống muốn giao thêm một
   đầu việc xuống máy ấy, **Then** đầu việc giữ **động cơ số 5 — đang bị chặn bởi việc khác**, màn hình
   hiện **"đang chờ máy rảnh"** phân biệt rõ với máy chết, và **không có đồng hồ nào đếm ngược** — máy rảnh
   thì poll của daemon tự nhặt.

---

### User Story 2 - Kết quả buộc phải rời khỏi máy trước khi được coi là nộp (Priority: P2)

Mỗi đầu việc có một thư mục làm việc riêng do daemon dựng, dùng chung cho mọi lượt chạy của đầu việc ấy —
đó là chỗ **nháp**, không phải kho. Muốn thứ
gì sống sót thì agent phải **tự công bố** nó lên kho hiện vật dùng chung bằng công cụ được cấp. Luật này
vừa **ghi trong tờ hướng dẫn** gửi agent, vừa **chặn ở tầng công cụ**: chưa có hiện vật thì không rời được
khỏi *đang làm*.

**Why this priority**: Đây là Điều II của Hiến pháp, và là đúng cái lỗi người chủ vừa gặp khi thử nghiệm
nền tảng khác: *"báo xong task nhưng file lưu ở local, không ai biết cả"*. Cổng chặn đã có; đợt này giữ
nguyên cổng ấy và bảo đảm nó vẫn đứng vững khi cách nói chuyện với agent đổi sang daemon.

**Independent Test**: Cho agent tạo một file trong thư mục làm việc rồi công bố nó. Kiểm chứng: hiện vật
tải về được từ giao diện và nội dung khớp. Rồi cho agent **không** công bố gì mà cố chuyển trạng thái: phải
bị chặn kèm lý do đọc được.

**Acceptance Scenarios**:

1. **Given** agent đã sinh ra thành phẩm trong thư mục làm việc, **When** nó công bố thành phẩm ấy bằng
   công cụ được cấp, **Then** đầu việc ghi nhận một hiện vật tải về được từ kho dùng chung.
2. **Given** agent chưa công bố hiện vật nào, **When** nó cố chuyển đầu việc rời khỏi *đang làm*, **Then**
   tầng công cụ **chặn**, trả lý do đọc được, và đầu việc vẫn giữ một động cơ đẩy sống.
3. **Given** thư mục làm việc bị thu hồi sau khi đầu việc khép lại, **When** người chủ mở lại đầu việc,
   **Then** hiện vật đã công bố vẫn còn nguyên và tải về được.
4. **Given** agent muốn biết mình đã tạo ra gì, **When** nó hỏi daemon, **Then** daemon liệt kê những thứ
   đã đổi trong thư mục làm việc — chỉ để agent biết mà công bố, **không** tự công bố hộ.

---

### User Story 3 - Gọi dậy lần sau thì nối đúng mạch cũ của đầu việc đó (Priority: P3)

Trong cùng một đầu việc, mọi lần gọi dậy đều nối lại **cùng một phiên** với agent, nên nó không phải đọc
lại từ đầu. Sang đầu việc khác là phiên khác. Khi vì lý do nào đó không nối lại được, hệ thống **nói thẳng
cho agent biết** rằng đây là bắt đầu lại, chứ không im lặng để nó tưởng mình vẫn nhớ.

**Why this priority**: Nó biến chuỗi lượt gọi dậy rời rạc thành một mạch làm việc liên tục. Không có nó,
mỗi lần gọi dậy agent phải dựng lại ngữ cảnh từ đầu — tốn và dễ lệch. Xếp sau P2 vì P2 là luật Hiến pháp,
còn cái này là chất lượng.

**Independent Test**: Gọi dậy hai lần trên cùng một đầu việc với hai lý do khác nhau; lần hai hỏi agent một
câu chỉ trả lời được nếu nó nhớ lần một. Rồi ép mất phiên và lặp lại: agent phải nhận được câu báo bắt đầu
lại.

**Acceptance Scenarios**:

1. **Given** một đầu việc đã có một lượt chạy xong, **When** đầu việc ấy được gọi dậy lần nữa, **Then**
   agent nối lại đúng phiên cũ và giữ được ngữ cảnh lần trước.
2. **Given** hai đầu việc khác nhau của cùng một agent, **When** cả hai cùng chạy, **Then** mỗi đầu việc
   một phiên riêng, không nhìn thấy nhau.
3. **Given** phiên cũ không nối lại được (agent CLI không hỗ trợ, phiên hỏng, hoặc đã quá hạn giữ),
   **When** đầu việc được gọi dậy, **Then** hệ thống mở phiên mới và **kèm một câu báo bằng tiếng Anh** nói
   rõ đây là bắt đầu lại và vì sao.
4. **Given** chỗ làm giữ phiên cũ đã bị dựng lại (máy cài lại daemon nên thành chỗ làm mới), **When** đầu
   việc được gọi dậy tiếp, **Then** hệ thống không giả vờ nối tiếp: nó mở phiên mới và báo như trên.

---

### User Story 4 - Thêm loại agent CLI mới mà không đụng tầng nghiệp vụ (Priority: P4)

Người vận hành thêm được một loại agent CLI mới mà không phải sửa tầng nghiệp vụ, không phải sửa luồng
đánh thức, không phải sửa các cổng trạng thái. Mọi khác biệt giữa các loại nằm gọn ở tầng dưới cùng.

**Why this priority**: Điều III của Hiến pháp. Xếp cuối vì với một loại agent đã có thì hệ vẫn chạy được —
nhưng nếu không dựng đúng ranh giới ngay từ đầu thì sau này gỡ rất đắt.

**Independent Test**: Chạy **cùng một đầu việc** trên hai loại agent CLI khác nhau. Kiểm chứng: hình dạng
diễn biến, cách nộp hiện vật, cách báo lỗi, và cách tính sống/chết **giống hệt nhau** ở tầng trên; và
không có dòng mã nào ở tầng nghiệp vụ rẽ nhánh theo tên loại agent.

**Acceptance Scenarios**:

1. **Given** hai loại agent CLI khác nhau, **When** giao cùng một đầu việc cho mỗi loại, **Then** tầng
   nghiệp vụ xử lý hai lượt chạy bằng đúng một đường mã.
2. **Given** một loại agent CLI không hỗ trợ một khả năng nào đó (ví dụ không nối lại được phiên),
   **When** hệ thống cần khả năng ấy, **Then** nó **hỏi khả năng** rồi hạ cấp có báo, chứ không đoán theo
   tên loại agent.

---

### User Story 5 - Ngồi một chỗ mà thấy hết agent đang làm gì (Priority: P2)

Người chủ mở một lượt chạy ra và đọc được những gì đã diễn ra: thông điệp hệ thống gửi cho agent, từng
lần agent gọi công cụ **kèm đầy đủ tham số**, **bản rút gọn** kết quả từng công cụ trả về, chữ agent sinh
ra, và lỗi nếu có. Xem được **trong lúc đang chạy**, và xem lại được sau khi xong. Không phải đăng nhập vào từng
máy, không phải mò log của từng agent CLI.

**Why this priority**: Đây là điều kiện cần để tin được đội agent. Không nhìn thấy agent làm gì thì không
gỡ được lỗi, không biết nó hiểu sai chỗ nào, và mọi kết luận đều là đoán. Ngang hàng US2 vì cùng là thứ
phải có trước khi giao việc thật.

**Independent Test**: Chạy một lượt có gọi ít nhất hai công cụ. Kiểm chứng: đọc lại được đúng thông điệp đã
gửi đi, đúng tham số của từng lần gọi, đúng kết quả trả về, đúng thứ tự; và trong lúc đang chạy thì các
dòng ấy hiện dần lên màn hình mà không phải tải lại.

**Acceptance Scenarios**:

1. **Given** một lượt chạy vừa bắt đầu, **When** người chủ mở nhật ký của nó, **Then** thấy được **toàn văn
   thông điệp** hệ thống đã gửi cho agent.
2. **Given** agent gọi một công cụ, **When** người chủ xem nhật ký, **Then** thấy tên công cụ, **đầy đủ tham
   số**, và **bản rút gọn kết quả trả về**, xếp đúng thứ tự đã xảy ra.
3. **Given** một lượt chạy đang diễn ra, **When** agent sinh thêm sự kiện, **Then** sự kiện ấy hiện lên màn
   hình đang mở mà người dùng không thao tác gì.
4. **Given** một agent CLI không lộ tham số công cụ, **When** người chủ xem nhật ký, **Then** chỗ ấy **ghi
   rõ là không lấy được và vì sao**, chứ không để trống như thể agent chẳng gọi gì.
5. **Given** một công cụ trả về kết quả rất lớn, **When** người chủ xem nhật ký, **Then** màn hình hiện bản
   rút gọn kèm **chỉ dấu là bản đầy đủ ở lại trên máy**, và màn hình không bị treo.
6. **Given** tham số một công cụ có chứa token, **When** sự kiện ấy rời khỏi máy người dùng, **Then** giá trị
   bí mật **đã bị che từ phía daemon**, không bao giờ tới server ở dạng nguyên bản.

---

### Edge Cases

- **Agent offline giữa lượt chạy.** Đầu việc còn động cơ đẩy nào, bao lâu thì coi là mất, ai gỡ — chạy
  đúng luồng offline đang có, không dựng luồng riêng.
- **Agent online lại sau khi đứt.** Đã có luật ở mục 4.4: lượt chạy hỏng giữa chừng thì coi như chết và
  gọi dậy lại từ hành động kế tiếp. Chuyện tầng dưới có nối lại được luồng hay không là tối ưu nội bộ.
- **Một máy nhận nhiều đầu việc cùng lúc.** Trần bao nhiêu thì đặt được; chạm trần thì đầu việc thứ N+1
  giữ **động cơ số 5** và hiện trạng thái *đang chờ máy rảnh*, **không có timeout** (chốt 2026-08-22).
  Không cần hẹn giờ thử lại: poll của daemon là cơ chế duy nhất.
- **Hai đầu việc của cùng một agent chạy song song.** Có giẫm lên nhau ở thư mục hay ở phiên không?
- **Agent CLI không có trên máy nữa** (bị gỡ, đổi đường dẫn) sau khi đã đăng ký chỗ làm.
- **Agent chạy rất lâu nhưng vẫn sống.** Phân biệt thế nào với treo? Ngưỡng có được đặt riêng cho từng
  loại agent CLI không?
- **Agent CLI dừng vì hết hạn mức nhà cung cấp.** Đây là lỗi cần người xử, không phải lỗi tạm — có bị tự
  gọi dậy lại vô ích không?
- **Đẩy hiện vật thất bại giữa chừng** (mất mạng, kho đầy). Đã chốt 2026-08-21: đẩy lại được không giới
  hạn, công cụ chịu được gọi lặp. Còn phải chốt ở bước lập kế hoạch: lấy gì làm dấu nhận dạng để biết hai
  lần công bố là cùng một thứ.
- **Thư mục làm việc bị người dùng xoá tay** khi đầu việc còn dở.
- **Nhiều daemon cùng đăng ký cho một agent** (người dùng cài trên hai máy). Ai nhận việc? Có nhận trùng
  không?
- **Token của daemon bị thu hồi** khi nó đang giữ một lượt chạy → đã chốt 2026-08-21: không có đường xử
  riêng, để luật động cơ đẩy bắt (FR-014e); riêng khâu phân loại lỗi thì phải đúng (FR-014f).
- **Nâng cấp daemon** khi đang có việc chạy dở.
- **Máy chạy daemon là Windows** — có ràng buộc nào không làm được (ví dụ quyền tạo liên kết tệp)?

---

## Requirements *(mandatory)*

### Nhóm A — Chỗ làm và vòng đời daemon

- **FR-001**: Hệ thống PHẢI cho phép một người cài và chạy daemon trên máy của mình rồi nối nó vào đúng
  một workspace bằng danh tính của người ấy.
- **FR-002**: Daemon PHẢI tự dò các agent CLI có trên máy và đăng ký mỗi cái tìm được thành một **chỗ làm**
  gắn với workspace đó.
- **FR-003**: Mỗi chỗ làm PHẢI mang tên máy đọc được, để người dùng phân biệt được hai máy khác nhau của
  cùng một người.
- **FR-004**: Daemon PHẢI phát tín hiệu sống theo nhịp đều. Mất tín hiệu quá ngưỡng thì mọi chỗ làm của nó
  chuyển sang **không sẵn sàng**.
- **FR-004a**: Tín hiệu sống của máy là **liên lạc được với máy ấy**, không phải một lối gọi cụ thể nào.
  **Mọi** lời gọi `/daemon/*` mà máy thực hiện thành công PHẢI được tính là một lần liên lạc — không riêng
  nhịp. Ngưỡng im lặng là **ba nhịp lỡ**. *Viết ra 2026-08-25 lúc hiện thực T042: đọc mỗi cột nhịp thì một
  cái máy đang khai chỗ làm — tức là đang nói chuyện với server ngay lúc ấy — vẫn bị coi là đã chết, vì
  vòng phát nhịp của nó chưa kịp chạy vòng đầu. Đây đúng bài học đã ghi một tầng trên cho `/agent/*`.*
  Điều này **không** mâu thuẫn FR-055b: liên lạc được tới máy vẫn không chứng minh gì về agent CLI trên máy
  ấy, và không lối nào được ghi dấu hiệu sống cho **agent** từ một cú gọi của máy.
- **FR-005**: Khi daemon tắt có trật tự, nó PHẢI gỡ đăng ký mọi chỗ làm của mình thay vì để hệ thống chờ
  hết ngưỡng.
- **FR-005a**: Daemon PHẢI trả lời được **ngay tại cái máy đang chạy nó** câu hỏi *"máy này đang ở tình
  trạng nào"*: đã nối vào workspace nào, dò được những agent CLI nào và chỗ làm nào đang sẵn sàng, và
  **có tiến trình daemon nào đang sống trên máy này hay không**. Câu trả lời PHẢI có cả dạng đọc bằng mắt
  và dạng máy đọc được. Lý do điều khoản này tồn tại: màn hình Máy trên giao diện web chỉ nói được là máy
  **im lặng** — nó không tách được máy tắt, daemon chết, token hết hạn hay CLI bị gỡ, vì cả bốn ca đều
  biểu hiện y hệt nhau: không còn gì gửi lên nữa. Chỉ một câu hỏi đặt tại chỗ mới phân biệt được (bổ sung
  2026-08-24; Multica có đúng cụm này ở `multica daemon status`).
- **FR-006**: Tầng nghiệp vụ CHỈ ĐƯỢC hỏi đúng một câu — **"agent này sống hay chết?"**. Nó KHÔNG ĐƯỢC
  biết tới khái niệm máy, runtime hay daemon (Hiến pháp — Điều III). Chuỗi máy → runtime → agent là chi
  tiết nằm sau hợp đồng adapter.
- **FR-006a**: Mọi mắt xích đứt trong chuỗi ấy PHẢI quy về đúng **một** kết luận cho tầng trên: *agent
  offline*. Máy mất nhịp thì mọi agent trên máy đó offline; máy còn sống mà agent CLI bị gỡ thì chỉ những
  agent dựa trên CLI đó offline. Hai đường, một kết luận.
- **FR-006b**: Khi một agent bị tuyên offline, hệ thống PHẢI chạy đúng luồng offline đang có — thử lại giãn
  dần giữ động cơ đẩy sống, rồi mới tuyên, rồi leo thang theo thang ba mức. KHÔNG ĐƯỢC dựng luồng riêng cho
  mô hình daemon.
- **FR-006c**: Hệ thống PHẢI hiện được **lý do** một agent offline ở mức người đọc hiểu được (máy tắt / CLI
  bị gỡ / CLI không chạy được), để người chủ biết đường xử — nhưng lý do là **thông tin hiển thị**, không
  phải nhánh rẽ trong tầng nghiệp vụ.
- **FR-006d**: Armarius PHẢI tự sở hữu kết luận sống/chết. Hệ thống KHÔNG ĐƯỢC uỷ quyền kết luận ấy cho
  nhịp tim của một runtime bên ngoài (Hiến pháp — Định vị sản phẩm).
- **FR-007**: Một agent PHẢI được **buộc vào đúng một chỗ làm** lúc tạo, và mối buộc ấy **KHÔNG đổi được**
  về sau. Chỗ làm chết thì agent offline; hệ thống KHÔNG tự chuyển agent sang máy khác — đổi người là quyết
  định của Trưởng dự án ở Mức 2 (chốt 2026-08-21).
- **FR-007f**: Mối buộc ở FR-007 PHẢI được **ghi vào lúc tạo agent**, và luồng tạo agent PHẢI **bắt buộc
  chọn chỗ làm** — không có đường tạo agent mà bỏ trống chỗ làm. Người dùng PHẢI chọn được chỗ làm ngay trên
  màn hình tạo/mời agent, và danh sách chọn chỉ hiện những chỗ làm đang sẵn sàng trong workspace của họ.
  Agent chưa buộc vào chỗ làm nào PHẢI bị coi là offline, không phải lỗi im lặng.
- **FR-007a**: **Nhiều agent PHẢI dùng chung được một chỗ làm.** Một máy chỉ có một bản của mỗi agent CLI,
  nên không cho dùng chung thì mỗi máy chỉ đẻ được một agent cho mỗi loại CLI.
- **FR-007b**: Khi nhiều agent dùng chung một chỗ làm, **sáu** thứ sau PHẢI tách riêng theo **agent**:
  phiên, bộ công cụ, kỹ năng, thư mục làm việc, token gọi ngược, và danh tính kèm chỉ dẫn. Bộ công cụ và
  kỹ năng PHẢI bơm theo từng lượt chạy — **KHÔNG ĐƯỢC ghi vào cấu hình của agent CLI trên máy**, vì cấu
  hình đó dùng chung và thuộc về người dùng.
- **FR-007e**: **Ký ức dài hạn của agent KHÔNG phải khái niệm nền của Armarius** (chốt 2026-08-22). Nó chỉ
  tồn tại ở CLI nào tự có tính năng ấy, nên xử **y hệt Multica**: để trong thư mục nhà giả mà daemon dựng
  cho chính CLI đó, liên kết ra một kho sống lâu hơn thư mục làm việc, và dọn theo hạn giữ riêng. Armarius
  KHÔNG dựng kho ký ức chung cho mọi loại CLI.
- **FR-007g**: Luồng tạo agent PHẢI **bỏ hẳn gateway url và api key**. Tạo một agent chỉ cần **tên** và
  **chỗ làm**; mọi thứ khác có mặc định và sửa được sau. Hệ thống KHÔNG probe gateway trước khi tạo, KHÔNG
  gửi setup prompt sau khi tạo, và KHÔNG mint token riêng cho agent — FR-014a đã chốt hệ thống chỉ có hai
  loại token, của daemon và của lượt chạy. Đây là hệ quả trực tiếp của FR-040a: bốn thứ ấy chỉ tồn tại để
  phục vụ đường gateway cũ.
- **FR-007g1**: Luồng tạo agent PHẢI **không nhận runtime từ người gọi**. Công cụ nào chạy một agent là hệ
  quả của **chỗ làm** người ta đã chọn — thứ họ nhìn thấy và cân nhắc được — chứ không phải một ô chọn riêng
  họ không có cách nào trả lời cho đúng. Giá trị runtime đến từ request bị **bỏ qua**, không phải bị từ chối
  bằng lỗi: nó vốn không phải thứ đường này nhận. Lý do phải viết thành điều khoản: một runtime đặt từ ngoài
  vào có thể là runtime không máy nào chạy nổi, và agent dựng quanh nó là agent không bao giờ chạy được lượt
  nào (bổ sung 2026-08-25, phát hiện lúc gỡ ô chọn adapter ở T039h).
- **FR-007h**: Tên agent PHẢI **không trùng trong cùng một workspace**. Trùng tên thì người giao việc không
  biết mình đang gọi ai.
- **FR-007i**: Agent PHẢI có **instructions** — chữ do người chủ agent viết lúc tạo, mô tả nó là ai, chịu
  trách nhiệm gì, được sửa gì, giao kết quả ra sao. Instructions PHẢI đi xuống agent ở **mỗi lượt chạy**,
  trong chính gói nhận việc, cùng đường với bối cảnh dự án ở FR-011. Đây là chỗ **duy nhất** định nghĩa cách
  cư xử của agent (Hiến pháp — Điều V, phiên bản 2.0.0).
- **FR-007j**: Agent PHẢI có **description** — một dòng giới thiệu cho người trong workspace đọc. Nó
  **KHÔNG ĐƯỢC** đi vào prompt gửi agent. Tách khỏi instructions vì hai thứ có hai người đọc khác nhau; gộp
  lại thì mọi câu viết cho đồng nghiệp đọc đều tốn chỗ trong prompt.
- **FR-007k**: Người dùng PHẢI chọn được **model** và **thinking level** cho từng agent. Danh sách chọn PHẢI
  lấy từ **khả năng thật của chỗ làm** theo FR-017, KHÔNG được lấy từ bảng chép cứng theo tên CLI. Agent CLI
  nào tự quản model thì **không hiện ô chọn**. Bỏ trống thì dùng mặc định của chính CLI đó.
- **FR-007l**: **Bỏ role theo dự án.** Cách cư xử của agent đến từ instructions ở FR-007i, không từ một ghế
  role trong dự án. Thêm agent vào dự án là thêm thẳng agent, không qua role. **Giữ nguyên Trưởng dự án** —
  đó là vị trí điều phối của từng dự án, không phải một ghế trong bộ role đã bỏ (Hiến pháp 2.0.0 — Điều V).
  - Lý do người chủ đưa: role theo dự án **làm loãng skill**, và khi instructions đã nằm trên agent thì role
    chỉ là bản chép thứ hai của cùng một nội dung.
  - Cần hai cách cư xử khác nhau thì **tạo hai agent** — agent chỉ là tên, instructions, skill và chỗ làm.
  - **Phạm vi ở đặc tả này**: chỉ chốt luật và bảo đảm luồng tạo agent mới không sinh thêm role. Việc gỡ
    bảng role, ghế, và những chỗ đang đọc chúng (chữ ký duyệt, thang phục hồi, màn hình đội hình) đụng vào
    phần lõi của đặc tả 001 nên tách sang **đặc tả riêng**; đặc tả này không gỡ.
- **FR-007c**: Đăng nhập và hạn mức của agent CLI là thuộc tính của **chỗ làm**, không của agent. Cạn hạn
  mức PHẢI làm **mọi agent trên chỗ làm ấy** offline cùng lúc, và PHẢI xếp vào **lỗi cần người xử** —
  KHÔNG ĐƯỢC tiêu ngân sách tự phục hồi (xem FR-032).
- **FR-007d**: Hệ thống PHẢI bảo đảm **một lượt chạy chỉ được đúng một máy nhận**. Khi một lượt chạy bị
  tuyên là hỏng, **token của lượt chạy ấy** PHẢI bị thu hồi ngay, để một tiến trình ngủ dậy muộn không ghi
  thêm được gì vào đầu việc.
- **FR-008**: Hệ thống PHẢI có trần số lượt chạy đồng thời trên mỗi máy, và trần ấy PHẢI chỉnh được.
- **FR-008a**: Khi một máy còn sống nhưng đã chạm trần, đầu việc chưa chạy được PHẢI giữ **động cơ đẩy số
  5 — đang bị chặn bởi việc khác** (sửa 2026-08-22; trước đó ghi là động cơ số 2). Thứ chặn nó là chính
  những lượt chạy đang chiếm chỗ trên máy ấy, và **mỗi lượt đó đã có đồng hồ riêng**.
  Hệ thống KHÔNG ĐƯỢC thêm động cơ đẩy thứ bảy, và KHÔNG ĐƯỢC xếp vào động cơ số 6 vì không có gì hỏng.
- **FR-008b**: Trạng thái **"đang chờ máy rảnh"** PHẢI hiện lên màn hình người chủ và PHẢI phân biệt được
  với "máy chết". Thông tin ấy lưu bằng **mã kèm tham số**, không phải câu chữ lưu sẵn (Hiến pháp — Điều
  VII). Đây là trạng thái vận hành bình thường, không phải cảnh báo.
- **FR-008e**: Trạng thái *đang chờ máy rảnh* **KHÔNG có đồng hồ và KHÔNG bị tính giờ**. Đây là ngoại lệ
  hợp lệ của luật đồng hồ, cùng lý do đã ghi cho động cơ số 5: *thứ chặn nó có động cơ đẩy riêng, và nếu
  thứ ấy kẹt thì chuông reo ở đó, chỗ có người xử được*. Gắn thêm đồng hồ ở đây là đo lại một thứ đã được
  đo. Multica cũng không đặt hạn cho đầu việc đang chờ chỗ trống (chốt 2026-08-22).
- **FR-008d**: Trần là **cấu hình phía server** và server là bên quyết duy nhất có đưa thêm việc hay không.
  Con số daemon báo về chỉ là **số chỗ trống hiện tại**, mang tính tham khảo; server PHẢI lấy **số nhỏ hơn**
  giữa hai giá trị. Daemon báo sai hoặc báo cũ thì server vẫn không đưa quá trần.
- **FR-008c**: Hệ thống KHÔNG hẹn giờ thử lại cho ca chạm trần. **Poll của daemon là cơ chế duy nhất** —
  máy rảnh thì tự xin, không cần ai đánh thức (chốt 2026-08-22).

### Nhóm B — Giao việc và nói chuyện với agent

- **FR-009**: Khi một lượt gọi dậy phát sinh, hệ thống PHẢI đẩy việc xuống chỗ làm phù hợp. Giao diện
  KHÔNG ĐƯỢC hỏi-vòng để biết diễn biến (Hiến pháp — Điều IV).
- **FR-010**: Daemon PHẢI dựng một **thư mục làm việc riêng cho từng đầu việc** và khởi chạy agent CLI
  trong đó. Mọi lượt chạy của cùng một đầu việc PHẢI dùng lại **đúng thư mục ấy** (chốt 2026-08-21).
- **FR-010a**: Ranh giới thư mục làm việc PHẢI trùng ranh giới phiên (FR-023), vì phần lớn agent CLI gắn
  phiên vào chính thư mục đã mở phiên — nối lại phiên ở thư mục khác thì hoặc không tìm thấy phiên, hoặc
  tìm thấy nhưng mọi đường dẫn agent nhớ đều trỏ vào chỗ trống.
- **FR-010b**: Hai đầu việc khác nhau PHẢI có hai thư mục làm việc tách biệt, kể cả khi cùng một agent.
- **FR-011**: Daemon PHẢI đưa cho agent đầy đủ những gì gói tin đánh thức hôm nay đang mang: Bối cảnh dự
  án, mô tả đầu việc, mã lý do gọi dậy kèm tham số, và hành động kế tiếp đã lưu.
- **FR-011a**: Thông điệp ở FR-011 PHẢI được **server dựng** và đi xuống trong chính gói nhận việc. Daemon
  KHÔNG dựng nội dung — nó chỉ đặt thông điệp vào đúng tệp bối cảnh mà từng CLI vốn tự đọc. Lý do: nội dung
  dựng từ vai trò trong dự án (Hiến pháp — Điều V) và phải bằng tiếng Anh (Điều VII); cả hai luật ấy sống ở
  server, không sống ở máy người dùng.
- **FR-011b**: **Kỹ năng kế thừa hoàn toàn flow của Multica** (chốt 2026-08-23):
  - Kỹ năng đi xuống **trong cùng gói nhận việc**, không phải agent tự gọi về lấy.
  - Daemon ghi kỹ năng vào **đúng thư mục kỹ năng native của từng CLI** — bảng ánh xạ ở
    [research §11](research.md).
  - Kỹ năng PHẢI là **tệp thật, ghi mới ở mỗi lượt chạy**. KHÔNG ĐƯỢC liên kết ra một kho dùng chung, vì
    liên kết như vậy làm kỹ năng của agent này lộ sang agent khác đang dùng chung chỗ làm (FR-007b).
  - Đây là chỗ Multica cố ý làm khác với những thứ khác trong thư mục nhà giả: đăng nhập, cấu hình và ký ức
    dùng liên kết, riêng kỹ năng ghi tệp thật.
- **FR-011c**: Đường **agent tự gọi về lấy kỹ năng rồi tự ghi** KHÔNG còn là đường cài kỹ năng. Vòng xác
  nhận đã cài xong — thứ còn dở dang từ đợt trước — được đóng lại thay vì hoàn thiện, vì daemon ghi tệp
  trực tiếp thì không còn gì để xác nhận.
- **FR-012**: Mọi chữ **hệ thống** sinh ra rồi gửi cho agent PHẢI bằng tiếng Anh; chữ do **người** nhập giữ
  nguyên thứ tiếng người viết (Hiến pháp — Điều VII).
- **FR-012a**: Hệ thống PHẢI **ghi lại toàn văn thông điệp gửi cho agent** ở mỗi lượt chạy (FR-042).
  **Server ghi tại thời điểm trả gói nhận việc**, vì đó là nơi thông điệp được dựng — daemon không ghi lại
  thứ nó chỉ chuyển tay.
- **FR-013**: Daemon PHẢI đưa cho agent một cách gọi ngược về Armarius, giới hạn đúng phạm vi của agent ấy
  và của lượt chạy ấy.
- **FR-013a**: Bộ công cụ gọi ngược PHẢI được cấp **theo từng lượt chạy** và PHẢI mang **token của lượt
  chạy** chứ không phải token của daemon (FR-014c). Nó PHẢI có **hai mặt của cùng một thứ** (sửa
  2026-08-29):
  - **mặt lệnh** — gọi được như một lệnh bình thường từ trong thư mục làm việc. Đây là **mặt nền**: mọi
    agent CLI đều chạy được một lệnh, kể cả loại không có cơ chế nạp công cụ nào, nên không CLI nào bị bỏ
    lại.
  - **mặt công cụ native** — chính thứ ấy nói giao thức nạp công cụ (MCP) **qua luồng chuẩn**, khai theo
    từng lượt chạy, cho CLI nào có cơ chế nạp. Đây là mặt Multica dùng.

  Hai mặt PHẢI là **một thứ**, không phải hai bản cài. Hai bản là hai danh sách việc agent làm được, và
  chúng sẽ lệch nhau đúng vào lúc thêm một việc mới.

  Cùng luật với kỹ năng ở FR-011b: **KHÔNG ĐƯỢC ghi vào cấu hình dùng chung của CLI trên máy**, vì cấu hình
  ấy thuộc về người dùng và dùng chung cho mọi agent trên chỗ làm đó. Và KHÔNG ĐƯỢC là **một địa chỉ từ xa
  mà agent phải tự khai vào cấu hình** — cùng lý do đã gỡ đường agent tự đi lấy kỹ năng rồi tự ghi
  (FR-011c): thứ gì agent phải tự cài thì có lúc nó cài hỏng, và hệ thống không biết để mà chờ.
- **FR-013b**: Khi agent dừng giữa lượt để **xin phép** làm một việc, daemon **KHÔNG ĐƯỢC** cho phép thay
  người chủ. Nó cầm thông tin xác thực của một cái máy, không cầm quyền phán của người chủ, nên câu trả lời
  duy nhất nó được phép đưa là **từ chối**, kèm một mã ghi lại đúng thứ agent muốn làm. Lý do viết thành
  điều khoản: lượt chạy diễn ra khi không ai ngồi đó, nên nói "được" hộ là gắn một lời chấp thuận không ai
  đưa vào mọi lượt chạy về sau; còn im lặng thì agent treo tới lúc ngưỡng im lặng cắt, và bản ghi không nói
  được vì sao. Đây là **luật, không phải chỗ tạm**: đặc tả này không hứa hẹn một đường xin phép nào cả. Nếu
  sau này người chủ muốn một luồng phê duyệt thật — hỏi ai, hỏi ở đâu trên màn hình, đợi bao lâu, quá hạn thì
  sao — đó là một tính năng phải được đặt ra thành yêu cầu, không phải một mẩu còn thiếu của cụm này (bổ sung
  2026-08-26, phát hiện lúc dựng họ ACP ở T066).
- **FR-013c**: Thứ agent dùng để gọi ngược PHẢI nhận thông tin xác thực qua **biến môi trường**, và KHÔNG
  ĐƯỢC nhận qua **tham số dòng lệnh**. Lý do là một luật khác của chính đặc tả này: FR-043 bắt ghi **đầy đủ
  tham số** mỗi lần agent gọi công cụ, nên một credential nằm trong tham số là một credential nằm trong bản
  ghi trên server — và ngay trên cái máy ấy, mọi tiến trình khác của cùng người dùng đọc được dòng lệnh của
  nhau. Che bí mật (FR-048) là lưới đỡ, không phải chỗ dựa: lưới chỉ bắt được thứ nó nhận ra, còn thứ không
  đưa vào thì không có gì để nhận ra.
- **FR-013d**: Phạm vi của một lượt chạy PHẢI được quyết bằng **bộ công cụ cấp cho lượt ấy**, không bằng
  một bảng quyền tra lúc gọi. Lượt chạy **cấp đầu việc** nhận công cụ của đầu việc; lượt chạy **cấp dự án**
  nhận công cụ của dự án. Kế thừa Multica: *công cụ đi theo đầu việc như hành lý*. Điều này KHÔNG thay
  FR-059 — server VẪN PHẢI từ chối cú ghi vượt phạm vi. Hai lớp vì chúng đỡ hai thứ khác nhau: lớp công cụ
  là thứ agent **nhìn thấy** nên nó không đi nhầm, lớp server là thứ agent **không lách được** nên nó không
  đi nhầm được kể cả khi cố.
- **FR-014**: Thông tin xác thực cấp cho một lượt chạy PHẢI **hết hiệu lực khi lượt chạy kết thúc**, không
  dùng lại được cho lượt khác.
- **FR-014a**: Hệ thống PHẢI có **hai loại token tách biệt**, kế thừa nguyên cách Multica làm (chốt
  2026-08-21):
  - **token của daemon** — con người tạo lúc nối máy vào workspace; daemon dùng cho mọi lời gọi lên server
    (xin việc, gửi diễn biến, phát tín hiệu sống). Đây là token duy nhất người dùng chạm vào.
  - **token của lượt chạy** — server tự đúc **đúng lúc trao việc cho máy**, trả về kèm đầu việc; daemon nhét
    vào agent qua biến môi trường. Người dùng không bao giờ nhìn thấy và không phải cấu hình gì.
- **FR-014b**: Token của lượt chạy PHẢI bị **thu hồi khi lượt chạy khép lại**, dù xong hay hỏng.
- **FR-014c**: Daemon **KHÔNG ĐƯỢC** đưa token của chính nó cho agent, kể cả khi đúc token lượt chạy thất
  bại. Đúc hỏng thì trả đầu việc về trạng thái chưa có máy nhận, KHÔNG ĐƯỢC chạy với token thay thế. Lý do:
  token của daemon nói thay **cả cái máy** — mọi chỗ làm và mọi agent trên đó — còn token lượt chạy chỉ mở
  đúng một đầu việc. Multica đã ngã đúng chỗ này rồi mới đặt luật (MUL-3292).
- **FR-014d**: Token của daemon PHẢI gia hạn được. Daemon ĐƯỢC PHÉP hỏi gia hạn theo nhịp bất kỳ, và
  **server là bên quyết** đã tới lúc gia hạn hay chưa — daemon KHÔNG ĐƯỢC tự tính hạn dùng của token mình
  đang giữ.
- **FR-014e**: Token của daemon bị **thu hồi giữa lúc một lượt chạy đang diễn ra** thì xử **đúng như mọi
  kiểu agent tắt tiếng khác**: lượt chạy im, động cơ số 1 quá hạn, vòng quét nổi cờ, leo thang phục hồi.
  KHÔNG dựng đường xử riêng — Multica cũng không có đường nào cho ca này, và luật động cơ đẩy của ta đã bắt
  được nó mà không cần biết nguyên nhân.
- **FR-014f**: Token bị thu hồi hoặc hết hạn PHẢI xếp vào **lỗi cần người xử**, KHÔNG ĐƯỢC tiêu ngân sách
  tự phục hồi (FR-032). Đây là mẩu duy nhất trong cụm token mà ta phải tự giải, vì thử lại một token đã bị
  thu hồi thì lần nào cũng hỏng.
- **FR-014g**: Mọi lối agent gọi về Armarius PHẢI xác thực bằng **token của lượt chạy**. Sau đợt này hệ
  thống KHÔNG còn token sống lâu cấp cho agent: FR-014a chỉ chừa đúng hai loại, và loại thứ ba còn sống
  tới hôm nay chỉ vì chưa có gì thay chỗ nó. Hệ quả bắt buộc: mọi lời gọi từ agent đều **mang danh tính
  lượt chạy**, thứ FR-059 đòi mà lối xác thực hôm nay không cấp được — token sống lâu không biết nó đang ở
  lượt chạy nào (thêm 2026-08-29).
- **FR-015**: Daemon PHẢI truyền diễn biến của agent về Armarius **trong lúc đang chạy**, không đợi đến khi
  xong.
- **FR-016**: Hệ thống PHẢI ghi lại đủ để **xem lại toàn bộ một lượt chạy** sau khi nó kết thúc.
- **FR-017**: Daemon PHẢI **hỏi khả năng** của agent CLI rồi mới dùng, và hạ cấp có báo khi khả năng ấy
  không có — KHÔNG ĐƯỢC suy ra khả năng từ tên loại agent.

### Nhóm C — Hiện vật buộc rời khỏi máy

- **FR-018**: **Agent tự công bố hiện vật** bằng công cụ được cấp, đúng như hôm nay. Daemon KHÔNG tự dò và
  KHÔNG tự đẩy thành phẩm — thư mục làm việc là chỗ nháp, không phải kho, và luồng chỉ có **một chiều**:
  nháp → kho chung, không bao giờ đồng bộ ngược.
- **FR-019**: Luật "chưa có hiện vật thì chưa được rời khỏi *đang làm*" PHẢI được **ghi trong tờ hướng dẫn
  gửi agent** *và* **chặn ở tầng công cụ** — dặn không thay cho chặn (Hiến pháp — Điều II).
- **FR-020**: Hệ thống PHẢI kiểm được rằng hiện vật đã ghi nhận là **thật sự tải về được**, không chỉ là
  một cái tên trong cơ sở dữ liệu.
- **FR-020a**: Daemon PHẢI cho agent **thấy được** những gì nó đã đổi trong thư mục làm việc, để agent biết
  mình có gì mà công bố. Đây là thông tin, KHÔNG phải công bố tự động.
- **FR-020b**: Công bố hiện vật hỏng giữa chừng PHẢI **thử lại được, không giới hạn số lần** — kể cả ở một
  lượt chạy sau, vì thư mục làm việc sống theo đầu việc (FR-010). Hệ thống KHÔNG ĐƯỢC bắt làm lại cả lượt
  chỉ vì cú đẩy hỏng (chốt 2026-08-21).
- **FR-020c**: Công cụ công bố PHẢI **chịu được gọi lặp**: công bố cùng một thứ nhiều lần chỉ ra **đúng
  một** hiện vật, không đẻ ra bản trùng, kể cả khi lần trước đã đẩy được một phần rồi mới đứt.
- **FR-020d**: Trong lúc một cú công bố còn dở, đầu việc PHẢI giữ một động cơ đẩy sống — KHÔNG ĐƯỢC rơi vào
  khoảng lặng ngay tại cổng Điều II.
- **FR-021**: Thư mục làm việc PHẢI được thu hồi **theo thời gian**, do daemon tự quét định kỳ — hệ thống
  KHÔNG gửi tin báo "đầu việc đã khép lại" xuống daemon (chốt 2026-08-22, theo đúng cách Multica làm).
  Daemon tự hỏi trạng thái đầu việc trong lúc quét. Điều kiện xoá: đầu việc **đã xong hoặc đã huỷ** *và*
  đã im quá hạn giữ đặt được. Hiện vật đã đẩy lên kho **KHÔNG ĐƯỢC** thu hồi theo.
- **FR-021a**: Thư mục làm việc mà server **không nhận ra thuộc đầu việc nào** PHẢI có đường thu hồi riêng,
  hạn dài hơn hẳn hạn ở FR-021. Lý do phải có điều khoản này: bộ dọn KHÔNG ĐƯỢC đoán — nó chỉ xoá khi
  **biết** đầu việc đã khép lại — nên một thư mục mà server không kể tên sẽ nằm lại **vĩnh viễn** trên máy
  người dùng. Đây đúng ca Multica đã gặp và xử bằng nhánh riêng *"không có sổ ghi + 72 giờ → xoá"*. Hạn
  riêng phải dài hơn vì đây là ca **đoán**, không phải ca **biết** (bổ sung 2026-08-24, phát hiện lúc dựng
  T009).
- **FR-022**: Hệ thống KHÔNG ĐƯỢC thu hồi thư mục làm việc mà **một lượt chạy đang giữ**.

### Nhóm D — Phiên và mạch làm việc

- **FR-023**: Mọi lượt gọi dậy trong **cùng một đầu việc** PHẢI nối lại **cùng một phiên** với agent.
- **FR-024**: Hai đầu việc khác nhau PHẢI có hai phiên tách biệt, kể cả khi cùng một agent.
- **FR-025**: Khi không nối lại được phiên cũ, hệ thống PHẢI mở phiên mới **và gửi cho agent một câu báo
  bằng tiếng Anh** nói rõ đây là bắt đầu lại cùng lý do.
- **FR-026**: Khi chỗ làm giữ phiên cũ **không còn là chỗ làm đang phục vụ agent ấy** (máy cài lại, daemon
  đăng ký lại thành chỗ làm mới), hệ thống PHẢI mở phiên mới và báo theo FR-025 — KHÔNG ĐƯỢC giả vờ nối
  tiếp. Lưu ý: vì FR-007 buộc mỗi agent vào đúng một chỗ làm không đổi được, một lượt gọi dậy **không thể**
  rơi sang máy khác trong lúc mối buộc còn nguyên; điều khoản này chỉ áp cho lúc mối buộc bị dựng lại.
- **FR-027**: Phiên PHẢI có hạn giữ đặt được. Quá hạn thì thu hồi, và lần gọi dậy sau xử theo FR-025.

### Nhóm E — Hỏng hóc và lưới an toàn

- **FR-028**: **Agent bị tuyên offline** giữa một lượt chạy PHẢI làm đầu việc **chuyển sang một động cơ
  đẩy hợp lệ khác**, không bao giờ để nó mất hết động cơ mà không nổi cờ.
- **FR-029**: Hệ thống PHẢI có khoảng ân hạn đặt được cho **agent online trở lại** trước khi coi lượt chạy
  là hỏng.
- **FR-029a**: Lượt chạy đã bị tuyên hỏng PHẢI xử theo luật đang có ở mục 4.4 của thiết kế vận hành: coi
  lượt ấy đã chết, đầu việc về trạng thái bền cuối, gọi dậy lại từ **hành động kế tiếp** đã lưu. Đặc tả này
  KHÔNG đặt luật mới cho việc đó.
- **FR-029b**: Nếu tầng dưới hợp đồng giữ được tiến trình agent sống qua một lần đứt và nối lại được luồng
  diễn biến, đó là **tối ưu nội bộ**, KHÔNG ĐƯỢC lộ thành trạng thái mới ở tầng nghiệp vụ. Tầng trên chỉ
  thấy đúng hai kết cục: lượt chạy chạy xong, hoặc agent offline và lượt chạy chết (Hiến pháp — Điều III).
- **FR-030**: Lượt chạy im lặng quá ngưỡng PHẢI đi vào **thang phục hồi ba mức** đang có, không được xử
  bằng một đường riêng.
- **FR-030a**: Khi một lượt chạy **kết thúc** mà đầu việc chưa đủ điều kiện rời *đang làm* (FR-019), đầu
  việc PHẢI có ngay một động cơ đẩy sống — **không đợi vòng quét phát hiện**. FR-030 chỉ xử ca *im lặng quá
  ngưỡng*, mà lượt chạy đã kết thúc thì không im lặng: nó **xong nhưng đầu việc kẹt**. Đây đúng là lỗ đã
  quan sát được ở Multica (research mục 12c): lượt chạy kết thúc sạch, đầu việc vẫn nằm ở *đang làm*, và
  không tác nhân nào được xếp lịch quay lại nhìn nó. Vòng quét của ta bắt được ca này nhưng bắt **muộn**,
  nên nó là lớp cuối chứ không phải cách xử chính.
- **FR-031**: Hệ thống KHÔNG giới hạn **tổng thời gian** một lượt chạy. Thứ bắt treo là **ngưỡng im lặng**
  — thời gian tính từ **sự kiện gần nhất** agent nhả ra. Mặc định **10 phút** (chốt 2026-08-22, khớp con số
  Multica dùng cho Codex và OpenCode).
- **FR-031a**: Ngưỡng im lặng đặt được **riêng cho từng loại agent CLI**, nhưng giá trị riêng ấy **chỉ được
  siết chặt hơn, KHÔNG được nới rộng hơn** ngưỡng nền. Cấu hình của một CLI không được phép tắt lưới an
  toàn chung — luật này chép của Multica.
- **FR-032**: Hệ thống PHẢI phân biệt **lỗi tạm** (đáng tự thử lại) với **lỗi cần người** (hết hạn mức, sai
  cấu hình, thiếu quyền). Lỗi cần người KHÔNG ĐƯỢC tiêu ngân sách tự phục hồi.
- **FR-033**: Agent CLI đã đăng ký nhưng không còn trên máy PHẢI làm chỗ làm ấy chuyển sang không sẵn sàng
  kèm lý do, chứ không im lặng nhận việc rồi hỏng.
- **FR-034**: Nâng cấp daemon KHÔNG ĐƯỢC cắt ngang một lượt chạy đang diễn ra.

### Nhóm F — Ranh giới kiến trúc

- **FR-035**: Tầng nghiệp vụ KHÔNG ĐƯỢC rẽ nhánh theo loại agent CLI. Mọi khác biệt PHẢI nằm sau một hợp
  đồng chung (Hiến pháp — Điều III).
- **FR-036**: Mọi đọc/ghi qua daemon PHẢI giới hạn trong workspace của nó; chạm sang workspace khác PHẢI
  đọc thành "không tìm thấy" (Hiến pháp — Điều I).
- **FR-037**: Thêm một loại agent CLI mới PHẢI chỉ đụng tầng dưới cùng — không đụng luồng đánh thức, không
  đụng các cổng trạng thái, không đụng tầng nghiệp vụ.
- **FR-038**: Hệ thống PHẢI có phép kiểm tự động chứng minh FR-035 và FR-037, chạy trong bộ kiểm thường
  xuyên. Gỡ mất ranh giới thì phép kiểm phải **đỏ**, không được im lặng trôi.

### Nhóm G — Ba điểm đã chốt (người chủ, 2026-08-21)

- **FR-039**: Hệ thống PHẢI hỗ trợ **cả hai họ giao thức**: họ ACP (nói JSON-RPC qua luồng chuẩn) và họ
  chạy-một-phát (prompt qua tham số dòng lệnh, kết quả về theo luồng). Cơ chế giao việc kế thừa từ Multica
  Daemon: brief ghi vào đúng file mà từng CLI vốn tự đọc, kỹ năng đặt vào đúng thư mục từng CLI vốn tự dò,
  công cụ bơm qua cơ chế nạp sẵn có của từng CLI. **Gemini CLI PHẢI nằm trong danh sách hỗ trợ** — Multica
  không có nó, đây là phần Armarius tự thêm.
- **FR-039b**: Thứ kế thừa từ Multica là **cách làm**, không phải **câu chữ**. Nội dung thông điệp Armarius
  gửi cho agent PHẢI **tự viết độc lập**. Nếu có đoạn nào giữ nguyên câu chữ của Multica thì PHẢI ghi nhận
  nguồn theo điều kiện (c) trong license của họ — nêu trong tài liệu người dùng rằng sản phẩm xây trên
  Multica, kèm link repo gốc. Chi tiết ràng buộc ở [research mục 13](research-multica-daemon.md).
- **FR-039a**: "Hỗ trợ một agent CLI" nghĩa là **nó chạy qua đúng hợp đồng hỏi-khả-năng ở FR-017**, không
  phải nó có đủ mọi khả năng. Ví dụ Gemini CLI: nếu nó không khai là nối lại được phiên thì hệ thống mở
  phiên mới kèm câu báo theo FR-025 — và đó **vẫn tính là hỗ trợ**, không phải hỏng. Cam kết ở FR-039 giữ
  nguyên; điều khoản này chỉ nói rõ thước đo, vì tài liệu nghiên cứu ghi Gemini CLI có ACP nhưng **chưa xác
  minh** nó đọc file bối cảnh nào, dò kỹ năng ở đâu, và có nối lại được phiên không.
- **FR-040**: Daemon PHẢI **thay hẳn** đường gọi agent qua cổng ngoài. Sau đợt này hệ thống chỉ còn **một**
  đường nói chuyện với agent. Đường cũ được gỡ, không giữ song song.
- **FR-040a**: Đường cổng ngoài cũ được xử như **chưa từng tồn tại** (chốt 2026-08-21). Không luật chuyển
  đổi, không tương thích ngược, không trạng thái "agent kiểu cũ". Dữ liệu sinh ra từ đường cũ bị xoá, và mọi
  thứ chỉ tồn tại để phục vụ đường cũ bị gỡ theo thay vì để lại dạng mã chết.
- **FR-040b**: Đợt này chỉ được đổi **cách Armarius nói chuyện với agent**. Mọi hành vi ở **tầng người
  dùng giữ nguyên** — cùng màn hình, cùng thao tác, cùng kết quả. Chuyển từ gateway sang daemon nghĩa là
  tầng liên lạc viết lại sạch, KHÔNG phải nghiệp vụ viết lại (người chủ chốt 2026-08-25).
  - Ca cụ thể đang gãy: màn hình **"Thiết lập bằng Tác nhân"**. Hôm nay nó gọi Tác nhân Không gian qua
    gateway của agent đó rồi **đứng đợi** câu trả lời để hỏi câu tiếp. Bỏ gateway thì không còn địa chỉ để
    gọi, và daemon không có kiểu gọi-rồi-đợi: server treo việc lên, máy rảnh lúc nào lấy lúc ấy.
  - Bắt buộc: người dùng vẫn **chat với Tác nhân Không gian** đúng như cũ — hỏi một câu, trả lời, hỏi câu
    tiếp, cuối cùng ra dự án và đội hình. Phần dưới dựng lại trên đường daemon.
  - Điều khoản này áp cho **mọi** luồng khác cũng đang gọi qua gateway, không riêng màn hình trên. Luồng nào
    tầng dưới đổi mà tầng người dùng đổi theo thì luồng đó sai.
- **FR-040c**: Buổi hỏi–đáp dựng đội của Tác nhân Không gian PHẢI là **một lượt chạy** như mọi lượt chạy
  khác, ở **cấp workspace** — không đầu việc, không dự án, vì lúc ấy dự án chưa tồn tại. Nhờ vậy nó xác
  thực bằng chính token của lượt chạy và FR-014a giữ nguyên đúng hai loại token, thay vì phải đúc một loại
  thứ ba chỉ để phục vụ một màn hình. Tầng người dùng không đổi (FR-040b) (chốt 2026-08-29).
- **FR-041**: Thư mục làm việc của một đầu việc bắt đầu ở trạng thái **trắng**. Hệ thống KHÔNG lấy mã nguồn về và
  KHÔNG quản nhánh làm việc; agent tự lo phần mã nguồn bằng thông tin đăng nhập của chính nó. Armarius là
  nơi làm việc chung cho nhiều loại việc, không riêng việc viết mã.

### Nhóm H — Tầng nhật ký đầy đủ cho một lượt chạy

- **FR-042**: Hệ thống PHẢI ghi lại **toàn văn thông điệp gửi cho agent** ở mỗi lượt — cả phần brief ổn
  định lẫn phần đổi theo từng lượt.
- **FR-043**: Hệ thống PHẢI ghi lại **mỗi lần agent gọi công cụ**, gồm tên công cụ và **đầy đủ tham số**.
- **FR-043a**: Kết quả công cụ trả về PHẢI chỉ ghi **bản rút gọn** (kích thước, kiểu, và phần đầu cắt theo
  ngưỡng đặt được). **Toàn văn kết quả KHÔNG ĐƯỢC rời máy người dùng** — không lên server, không vào kho
  phụ (chốt 2026-08-21).
- **FR-043b**: Bản rút gọn PHẢI ghi rõ **đã bị cắt** và **cắt mất bao nhiêu**, để người đọc không tưởng đó
  là toàn bộ kết quả.
- **FR-044**: Hệ thống PHẢI ghi lại chữ agent sinh ra, phần suy luận nếu CLI có lộ, và mọi lỗi.
- **FR-045**: Các sự kiện của một lượt chạy PHẢI có **thứ tự xác định** và **không trùng**, để xem lại đúng
  trình tự đã xảy ra.
- **FR-046**: Người dùng PHẢI xem được nhật ký này **trong lúc lượt chạy đang diễn ra**, không phải đợi
  xong, và không phải bấm tải lại (Hiến pháp — Điều IV).
- **FR-047**: Độ chi tiết ghi được PHỤ THUỘC khả năng từng CLI. Khi một CLI không lộ tham số hoặc kết quả
  công cụ, hệ thống PHẢI **đánh dấu rõ là thiếu và thiếu vì sao** — KHÔNG ĐƯỢC để khoảng trống trông như
  agent không gọi công cụ nào. Chỗ thiếu vì **CLI không lộ** phải phân biệt được với chỗ ngắn vì **bị cắt
  theo FR-043a**; hai lý do khác nhau, không được hiện giống nhau.
- **FR-048**: Trước khi rời khỏi máy người dùng, daemon PHẢI **che các giá trị bí mật** trong tham số và
  kết quả công cụ (token, khoá, biến môi trường nhạy cảm). Che PHẢI làm ở phía daemon, không phải ở server.
- **FR-048a**: Che bí mật PHẢI áp cho **mọi kênh rời khỏi máy người dùng**, không riêng tham số và kết quả
  công cụ: thông điệp gửi agent (FR-042), biến môi trường cấp cho lượt chạy, chữ agent sinh ra (FR-044), và
  thông báo lỗi. Lý do: token của lượt chạy đi **vào** agent qua thông điệp và biến môi trường, nên nó ra
  được bằng chính hai đường đó. FR-013 và FR-014 đã khoanh phạm vi và hạn dùng của token ấy nên thiệt hại
  có trần, nhưng khoanh vùng không thay cho che.
- **FR-049**: Với những sự kiện **được phép mang toàn văn lên server** (thông điệp gửi agent, tham số gọi
  công cụ, chữ agent sinh ra), sự kiện quá lớn PHẢI lưu theo hai phần: một phần rút gọn nằm ngay trong dòng
  sự kiện, và **toàn văn** để ở kho tách riêng, mở ra xem được theo yêu cầu. Ngưỡng cắt PHẢI đặt được. Luật
  hai phần này KHÔNG áp cho kết quả công cụ — kết quả chỉ có bản rút gọn (FR-043a).
- **FR-050**: Nhật ký đầy đủ PHẢI có hạn giữ đặt được, tách khỏi hạn giữ của thư mục làm việc.
- **FR-051**: Đọc nhật ký của một lượt chạy PHẢI giới hạn trong workspace của người đọc; chạm sang workspace
  khác PHẢI đọc thành "không tìm thấy" — nhật ký mang prompt và kết quả làm việc, đọc nhầm là đọc trộm việc
  người khác (Hiến pháp — Điều I).
- **FR-052**: Người dùng PHẢI **lọc được** nhật ký theo loại sự kiện, để tìm nhanh một lần gọi công cụ giữa
  hàng nghìn dòng.

### Nhóm I — Đường việc đi xuống máy (chốt 2026-08-21)

- **FR-053**: Hệ thống PHẢI có **đúng một** đường để một đầu việc bắt đầu chạy: daemon **xin việc**, server
  **đưa**. KHÔNG ĐƯỢC có đường thứ hai nào tự khởi động một lượt chạy trên máy.
- **FR-054**: Cú xin việc PHẢI là một phép **atomic compare-and-swap** ở server — *một câu lệnh duy nhất
  vừa chọn vừa gán, và chỉ gán được đầu việc nào còn đang rảnh tại đúng lúc câu lệnh chạy*. Nhiều cú xin
  vào cùng lúc thì đúng một cú nhận được việc, số còn lại về tay không.
  KHÔNG ĐƯỢC hiện thực bằng **read-then-write** — tức một câu `SELECT` tìm đầu việc đang rảnh rồi một câu
  `UPDATE` gán cho máy.
- **FR-054b**: Người tranh nhau **không phải hai máy khác nhau**. FR-007 buộc mỗi agent vào đúng một chỗ
  làm, nên hai máy không bao giờ nhìn thấy cùng một đầu việc. **Race condition ở đây là một máy gửi hai cú
  xin việc**, và có đúng ba đường sinh ra nó:
  - push tới đúng lúc poll cũng tới nhịp → hai cú gần như đồng thời
  - gói tin trả lời mất giữa đường → daemon không biết cú đầu đã ăn chưa nên gửi lại (Multica dính đúng ca
    này, mã sự cố MUL-4257)
  - hai tiến trình daemon cùng sống trên một máy → lúc nâng cấp (FR-034), hoặc người dùng bật hai lần

  Cả ba đều mang **cùng một tập runtime** nên cùng nhìn thấy đúng những đầu việc đó. Luật FR-054 tồn tại để
  *một máy gửi hai lần thì chỉ ăn một lần*, không phải để hai máy khỏi tranh nhau.
- **FR-054a**: Tính đúng-một-lần này PHẢI nằm ở **server**, KHÔNG ĐƯỢC dựa vào việc daemon tự xếp hàng.
  Lý do không phải là nghi ngờ daemon mà là ba tình huống daemon không tự giải được: gói tin trả lời rơi
  mất nên nó gửi lại mà không biết cú đầu đã ăn chưa; daemon khởi động lại làm mất hàng đợi trong bộ nhớ;
  và lúc nâng cấp có hai bản daemon cùng sống một nhịp (FR-034).
- **FR-055**: Ba lớp đưa việc xuống PHẢI tách bạch vai:
  - **Đẩy** — đường chính, phát mỗi lần có việc mới cho một máy
  - **Poll theo nhịp** — **fallback** khi push không tới nơi; nhịp PHẢI đặt được
  - **Cờ đình trệ** — lưới cuối, chỉ chạm đầu việc đã mất hết động cơ đẩy sống
- **FR-055a**: Tin đẩy xuống daemon CHỈ ĐƯỢC là tín hiệu *"có việc, đi hỏi đi"*. Nó KHÔNG ĐƯỢC là lệnh
  chạy và KHÔNG ĐƯỢC tự khởi động gì. Đây là thứ giữ cho hai tin tới cùng lúc chỉ đẻ ra một lượt chạy: tin
  thừa chỉ dẫn tới một cú xin thừa, mà cú xin thừa thì nhận về tay không.
- **FR-055b**: Cú poll của daemon **KHÔNG ĐƯỢC** ghi bất kỳ dấu hiệu sống nào cho agent. Poll chứng minh
  liên lạc được tới máy; nó KHÔNG chứng minh agent chạy được. Trộn hai thứ này thì máy bật mà CLI đã bị gỡ
  vẫn trông sống mãi, và luật FR-006a không thể thành hiện thực.
- **FR-055c**: Khi xin việc, daemon PHẢI nói luôn **còn nhận thêm được mấy việc**. Server chỉ đưa tối đa
  bằng số ấy và **giữ nguyên phần còn lại ở trạng thái chưa có máy nhận**. Đây là cơ chế làm cho FR-008a
  chạy được mà server không phải tự theo dõi máy nào đang bận tới đâu.
- **FR-055e**: Việc lấy **nhiều đầu việc cùng một lúc** (FR-055c) cũng PHẢI là **atomic compare-and-swap**,
  y như lấy một cái. KHÔNG ĐƯỢC hiện thực bằng "đọc số chỗ trống → chọn N đầu việc → gán" thành nhiều bước
  tách rời, vì như thế race condition ở FR-054b quay lại đúng chỗ vừa chặn.
- **FR-055d**: Poll là **fallback**, không phải đường chính. Nhịp poll PHẢI đặt được và ĐƯỢC PHÉP thưa;
  hệ thống KHÔNG ĐƯỢC rút nhịp poll xuống để bù cho push hỏng — push hỏng thì sửa push.
- **FR-056**: Động cơ đẩy số 1 (*đang có lượt chạy*) PHẢI bật **ngay lúc máy nhận đầu việc**, KHÔNG ĐƯỢC
  đợi tới lúc agent sinh ra dòng chữ đầu tiên. Giữa hai mốc đó là quãng daemon dựng thư mục, đổ kỹ năng và
  bật CLI — bật động cơ muộn là chừa ra đúng cái khe cho vòng quét gọi dậy lần thứ hai.
- **FR-056a**: Động cơ đẩy số 1 PHẢI có đồng hồ. Máy nhận việc rồi chết giữa lúc chuẩn bị thì quá hạn phải
  **thu hồi và trả đầu việc về trạng thái đang rảnh** để máy khác xin được. Động cơ không đồng hồ thì đầu
  việc treo vĩnh viễn ở *đang chạy* mà không có gì đang chạy.
- **FR-056c**: Hạn ở FR-056a PHẢI được đặt **cùng lúc và có quan hệ** với mốc thời gian ở SC-002. Quãng
  daemon dựng thư mục, đổ kỹ năng và bật CLI nằm **bên trong** mốc ấy, nên hạn thu hồi PHẢI lớn hơn thời
  gian chuẩn bị điển hình cộng một biên dư. Đặt hạn ngắn hơn thời gian chuẩn bị thì hệ thống **cướp lại đầu
  việc giữa lúc mọi thứ đang chạy đúng**. Hai con số KHÔNG ĐƯỢC chỉnh độc lập.
- **FR-056b**: Đồng hồ của động cơ số 2 PHẢI được **đặt lại tại thời điểm máy nhận việc**, vì từ mốc đó
  hệ thống có bằng chứng thật (máy nào, lúc nào) thay cho một cái hẹn suông.
- **FR-057**: Hệ thống PHẢI phân biệt được hai hỏng hóc mà hôm nay đang gộp làm một:
  - **chưa máy nào nhận** → agent offline, đi luồng offline đang có
  - **máy nhận rồi nhưng chết giữa lúc chuẩn bị** → thu hồi theo FR-056a, trả đầu việc về kệ
- **FR-058**: Đầu việc đã có máy nhận PHẢI **buộc vào đúng máy ấy**. Cú xin từ một máy khác cho đầu việc ấy
  PHẢI đọc thành "không tìm thấy".
- **FR-059**: Mọi lần ghi từ một lượt chạy về hệ thống PHẢI mang danh tính lượt chạy, và server PHẢI **từ
  chối** cú ghi từ một lượt không còn sở hữu đầu việc. Đây là lưới cho trường hợp không tránh được: đồng hồ
  hai bên lệch nhau nên một máy đã bị thu hồi vẫn tưởng mình còn giữ và vẫn bật agent lên. Chặn được cú ghi
  thì lần chạy thừa ấy không để lại dấu vết nào.
- **FR-060**: Cụm này KHÔNG ĐƯỢC hiểu là mở lại đường **thợ tự nhận việc** đã gỡ ở đặc tả 001. Hai thứ
  khác tầng: đường đã gỡ là **agent thợ tự chọn mình làm việc nào**; cụm này là **khâu vận chuyển** một đầu
  việc đã được Trưởng dự án giao, đi từ server xuống máy. Người giao việc vẫn là Trưởng dự án.

### Từ điển thuật ngữ

Mọi thuật ngữ hệ thống dùng trong đặc tả này đều phải có mặt ở đây. Thuật ngữ có tên tiếng Anh chuẩn thì
**giữ nguyên tiếng Anh**; không được dịch và không được đặt tên mới.

| Thuật ngữ | Nghĩa |
| --- | --- |
| **daemon** | Chương trình chạy nền trên máy người dùng, nối máy đó vào workspace và khởi chạy agent CLI tại chỗ |
| **agent CLI** | Chương trình dòng lệnh của một hãng (Claude Code, Codex, Gemini CLI…) mà daemon bật lên để làm việc |
| **ACP** | Agent Client Protocol — họ giao thức nói JSON-RPC qua luồng chuẩn của tiến trình |
| **MCP** | Model Context Protocol — giao thức các agent CLI dùng để nạp thêm công cụ. Ở đây chỉ dùng ở **mặt công cụ native** của bộ công cụ gọi ngược, nói qua luồng chuẩn và khai theo từng lượt chạy (FR-013a) |
| **token** | Chuỗi bí mật dùng để xác thực. Đặc tả này có hai loại: token của daemon và token của lượt chạy (FR-014a) |
| **push** | Server chủ động gửi tín hiệu xuống daemon. Ở đây push chỉ báo *"có việc, đi hỏi đi"*, không mang việc theo và không phải lệnh chạy (FR-055a) |
| **poll** | Daemon chủ động hỏi server theo nhịp đều. Là **fallback**, không phải đường chính (FR-055d) |
| **fallback** | Đường dự phòng, chỉ chạy khi đường chính không tới nơi |
| **atomic compare-and-swap** | Một câu lệnh duy nhất vừa kiểm điều kiện vừa đổi trạng thái; nhiều bên chạy cùng lúc thì đúng một bên thành công |
| **read-then-write** | Cách viết sai: một câu đọc rồi một câu ghi. Giữa hai câu có chỗ cho bên khác chen vào |
| **race condition** | Hai bên chạy cùng lúc và kết quả phụ thuộc bên nào nhanh hơn; ở đây là hai máy cùng nhận một đầu việc |
| **heartbeat** | Tín hiệu sống daemon phát theo nhịp đều để server biết máy còn đó (FR-004) |
| **workspace** | Không gian làm việc của một tổ chức; ranh giới cô lập dữ liệu (Hiến pháp — Điều I) |

Các thuật ngữ riêng của dự án — **đầu việc**, **lượt chạy**, **chỗ làm**, **động cơ đẩy**, **hiện vật**,
**phiên**, **thư mục làm việc** — định nghĩa ở phần Key Entities ngay dưới đây và ở thiết kế vận hành.

### Key Entities

- **Máy chạy daemon**: một máy vật lý hoặc máy ảo mà một người đã cài daemon lên và nối vào workspace.
  Thuộc tính: tên đọc được, chủ sở hữu, workspace, trạng thái sống/chết, thời điểm phát tín hiệu gần nhất.
- **Chỗ làm**: một cặp (agent CLI có trên máy đó × workspace). Đây là thứ nhận việc. Thuộc tính: loại agent
  CLI, máy, trạng thái sẵn sàng, các khả năng đã hỏi được.
- **Lượt chạy**: một lần agent được khởi chạy cho một đầu việc. Thuộc tính: đầu việc, chỗ làm, phiên,
  trạng thái, thời điểm bắt đầu/kết thúc, lý do gọi dậy. Thư mục làm việc **không** thuộc lượt chạy — nó
  thuộc đầu việc và được mọi lượt của đầu việc ấy dùng chung.
- **Phiên**: mạch hội thoại giữa hệ thống và một agent, gắn với **một đầu việc**. Thuộc tính: đầu việc,
  agent, máy giữ nó, thời điểm chạm gần nhất, còn nối lại được hay không.
- **Đầu việc chưa có máy nhận**: đầu việc đã được xếp cho một lượt chạy nhưng **chưa máy nào cầm**. Ở
  đường thường trạng thái này chỉ tồn tại vài phần nghìn giây. Nó kéo dài ở đúng ba tình huống, và cả ba
  đều là vận hành bình thường chứ không phải hỏng hóc:
  - **máy tắt** — việc giao lúc máy đang gập, nằm chờ tới khi máy bật lại (có thể hàng giờ)
  - **máy đang bận đủ trần** — daemon xin việc nhưng báo hết chỗ, phần dư nằm lại (phút tới chục phút)
  - **tin đẩy rơi mất** — máy đang bật và rảnh nhưng không nhận được tin, nằm chờ tới nhịp poll kế
- **Đầu việc đã có máy nhận**: trạng thái sau khi một máy xin và được server đưa việc. Từ mốc này đầu việc
  thuộc về đúng máy ấy, không đưa cho ai khác, và mang một hạn — quá hạn mà máy không báo đã chạy thì đầu
  việc quay về trạng thái chưa có máy nhận.
- **Thư mục làm việc**: thư mục hiện hành mà agent CLI được khởi chạy bên trong, gắn với **một đầu việc**
  và dùng chung cho mọi lượt chạy của đầu việc ấy. Bắt đầu ở trạng thái **trắng** — không có mã nguồn.
  Là chỗ nháp, có hạn giữ; chỉ thứ agent tự công bố thành hiện vật mới sống sót.
- **Hiện vật**: dùng lại thực thể đang có — thành phẩm đã nằm trong kho dùng chung, không phải file trên
  máy agent.
- **Bộ công cụ gọi ngược**: những việc agent được phép nhờ Armarius làm hộ trong lúc chạy — báo trạng thái,
  công bố hiện vật, để lại bình luận, nộp kế hoạch… Cấp **theo từng lượt chạy**, mang token của lượt ấy, và
  **danh sách công cụ chính là phạm vi** của lượt chạy (FR-013a, FR-013d). Một thứ, hai mặt: gọi được như
  một lệnh, và nói được giao thức nạp công cụ cho CLI nào biết nạp.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Người mới bắt đầu, chưa từng cài, nối được máy của mình vào workspace và thấy chỗ làm sẵn
  sàng **trong vòng 10 phút**, chỉ đọc hướng dẫn có sẵn.
- **SC-002**: Từ lúc hệ thống quyết định gọi dậy đến lúc agent thật sự bắt đầu chạy trên máy, **95% số lần
  dưới 15 giây**.
- **SC-003**: Diễn biến của agent hiện lên màn hình người theo dõi **trong vòng 3 giây** kể từ khi agent
  sinh ra nó, không cần thao tác tải lại.
- **SC-004**: **100%** số đầu việc được đánh dấu xong đều có ít nhất một hiện vật **tải về được từ kho
  dùng chung**. Không có ngoại lệ nào lọt qua.
- **SC-004a**: Cắt mạng giữa một cú công bố rồi cho agent công bố lại — kết quả ra **đúng một** hiện vật,
  không ra hai, và không phải chạy lại lượt.
- **SC-005**: **Không có đầu việc nào** ở trạng thái chưa xong mà mất hết động cơ đẩy quá 5 phút mà không
  nổi cờ đình trệ — kể cả khi làm agent offline đột ngột bằng cách rút phích máy đang chạy nó.
- **SC-006**: Trong cùng một đầu việc, **95%** số lần gọi dậy sau lần đầu nối lại được phiên cũ, với điều
  kiện cùng máy và trong hạn giữ.
- **SC-007**: Mọi lần **không** nối lại được phiên đều gửi cho agent câu báo bắt đầu lại — **100%**, không
  có lần nào im lặng.
- **SC-008**: Thêm một loại agent CLI mới **không sửa một dòng nào** ở tầng nghiệp vụ, và có phép kiểm tự
  động chứng minh điều đó.
- **SC-009**: Một máy chạy được **ít nhất 5 lượt chạy đồng thời** mà không lượt nào bị nhận trùng và không
  lượt nào bị nhầm là treo.
- **SC-010**: Làm agent offline giữa một lượt chạy rồi cho online lại trong khoảng ân hạn — đầu việc
  **không** bị mất và **không** bị chạy trùng, dù lượt chạy cũ được nối tiếp hay bị tuyên chết.
- **SC-011**: Với một agent CLI có lộ đủ dữ liệu, **100%** số lần gọi công cụ trong một lượt chạy đều đọc
  lại được **toàn văn tham số** và **bản rút gọn kết quả**. Không có lần gọi nào biến mất khỏi nhật ký.
- **SC-012**: Sự kiện hiện lên màn hình người theo dõi **trong vòng 3 giây** kể từ khi agent sinh ra nó.
- **SC-013**: Người chủ trả lời được câu *"agent đã làm gì và vì sao nó kết luận như vậy"* **chỉ bằng nhật
  ký trên màn hình**, không cần đăng nhập vào máy nào.
- **SC-014**: Một lượt chạy có **1000 sự kiện** vẫn mở ra và cuộn được mượt; sự kiện lớn không làm treo màn
  hình.
- **SC-015**: **Không có giá trị bí mật nào** lọt lên server ở dạng nguyên bản — chứng minh bằng phép kiểm
  tự động chạy trên dữ liệu có gài sẵn token.

---

## Assumptions

- **Mỗi người mời agent tự chạy daemon trên máy của mình.** Suy ra từ Định vị sản phẩm trong Hiến pháp
  (*"nhiều người ở nhiều team mời agent của mình vào"*) — không có một daemon dùng chung do người vận hành
  workspace chạy hộ.
- **Kho hiện vật dùng chung đã có** và dùng lại được — hôm nay đã lưu được cả tệp lẫn liên kết ngoài. Đặc
  tả này không dựng kho mới.
- **Ranh giới phiên là đầu việc**, khớp với cách hệ thống đang chạy hôm nay. Không đổi sang mức khác.
- **Bốn tác nhân, vòng đời đầu việc, các cổng trạng thái, luật động cơ đẩy và thang phục hồi ba mức giữ
  nguyên.** Đặc tả này chỉ đổi cách Armarius nói chuyện với agent.
- **Chưa có dữ liệu thật cần giữ.** Hệ thống chưa chạy thật với người dùng ngoài, nên đợt này được phép
  xoá sạch dữ liệu sinh ra từ đường cổng ngoài cũ thay vì viết luật chuyển đổi.
- **Agent CLI do người dùng tự cài và tự đăng nhập.** Armarius lái chúng, không phát hành chúng và không
  giữ hộ thông tin đăng nhập của nhà cung cấp mô hình.
- **Mã nguồn và dữ liệu không rời máy người dùng.** Chỉ diễn biến và hiện vật đã chỉ định mới đi lên
  Armarius. Sau chốt 2026-08-21, "diễn biến" gồm toàn văn tham số gọi công cụ nhưng **chỉ bản rút gọn**
  của kết quả công cụ. Lưu ý đánh đổi: công cụ kiểu **ghi file mang nội dung ngay trong tham số**, nên
  chọn lựa này chặn dòng dữ liệu đọc-vào chứ không làm nhật ký sạch hoàn toàn dữ liệu.
- **Máy chạy daemon có thể là Linux, macOS hoặc Windows.** Ràng buộc riêng của Windows (ví dụ quyền tạo
  liên kết tệp) được ghi nhận ở phần Edge Cases và xử ở bước lập kế hoạch.
- **Ba điểm ở Nhóm G chưa chốt** thì chưa lập kế hoạch được, vì mỗi cách chọn ra một khối lượng việc khác
  hẳn nhau.
