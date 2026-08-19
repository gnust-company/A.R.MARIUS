# Đặc tả tính năng: Vận hành dự án tự chủ

**Nhánh tính năng**: `spec/001-van-hanh-du-an`

**Ngày tạo**: 2026-07-30

**Trạng thái**: Đã triển khai — đóng lần đầu 2026-08-13 ở T162, mở lại cho Giai đoạn 10 (Hội tụ),
đóng lại 2026-08-18 ở T203, mở lại 2026-08-19 cho Giai đoạn 11 (T204)

**Đầu vào**: Yêu cầu của người chủ: "tôi muốn align toàn bộ prj với feature dự án theo như trong
`THIET-KE-VAN-HANH-DU-AN.md`"

---

## Làm rõ

### Phiên 2026-07-30

- Hỏi: Trưởng dự án phải quay lại xin người chủ duyệt khi thay đổi chạm tới những thứ nào? → Đáp: đúng năm
  thứ — phạm vi, mục tiêu/Bối cảnh, chi phí, thời hạn, tiêu chí công nhận. Mọi thay đổi khác Trưởng dự án tự
  quyết.
- Hỏi: Đầu việc nào thì phải chờ người chủ công nhận kết quả, ngoài việc Trưởng dự án đã duyệt? → Đáp: **bỏ
  cơ chế cờ theo từng việc**. Mặc định **mọi** đầu việc cần hai chữ ký — Trưởng dự án và người chủ đã cấp con
  agent thực hiện việc đó vào dự án ("ai mang agent vào thì chịu trách nhiệm đầu ra của nó"). Kèm một công
  tắc **tự động công nhận** ở cấp dự án, riêng cho từng người chủ: bật thì mọi việc cần chữ ký của người đó
  cho công việc của agent do họ cấp coi như đã ký sẵn, kể cả các bước chuyển trạng thái đầu việc cần họ gật.
- Hỏi: Hết một đợt việc, ai bấm nút chuyển dự án giữa *vận hành* và *bảo trì*? → Đáp: Trưởng dự án **đề
  xuất**, người chủ **quyết**. Chuyển sang *đóng* luôn là quyết định của người chủ. Hệ quả: công tắc tự động
  công nhận **không** thay người chủ ở ba quyết định cấp dự án — duyệt kế hoạch, duyệt thay đổi lớn, chuyển
  giai đoạn (FR-037).
- Hỏi: Một đầu việc điển hình mất bao lâu từ lúc giao tới lúc nộp bài? → Đáp: **vài giờ tới vài ngày**. Giữ
  nguyên bộ ngưỡng thời gian đề xuất (nghi treo 10 phút, quét canh gác mỗi phút, nhịp điều phối 15 phút,
  nhắc người chủ 8 giờ → 24 giờ → 72 giờ).
- Hỏi: Sau khi người chủ đã duyệt kế hoạch, Trưởng dự án có được tự do tạo thêm đầu việc mới không? → Đáp:
  **tự do trong khuôn kế hoạch đã duyệt**. Đầu việc nằm ngoài khuôn đó phải ở lại *nháp/đề xuất* chờ người
  chủ gật, vì nó là một lần nới phạm vi (FR-027, nối với FR-075).

### Phiên 2026-07-31 — vá các lỗ tìm ra khi soi chéo

- Hỏi: "Im lâu" và "sắp trễ" ở FR-052 là bao lâu? → Đáp: *im lâu* vài phút là phải soi — lấy **5 phút**, kèm
  điều kiện không có lượt chạy đang sống để không đè lên ngưỡng nghi treo. *Sắp trễ* lấy bốn mốc **24 giờ,
  12 giờ, 6 giờ, 1 giờ**. Đầu việc không đặt hạn chót thì không tính.
- Hỏi: "Đình trệ" và "mắc kẹt" ở FR-052 với FR-058 là một hay hai thứ? → Đáp: **hai thứ khác hẳn**.
  *Mắc kẹt* = đầu việc đang ở trạng thái *bị chặn* — hợp lệ, có động cơ đẩy đàng hoàng. *Đình trệ* = mất hết
  động cơ đẩy — đây là báo động rằng hệ thống vừa đánh rơi một đầu việc, không phải một trạng thái nghiệp vụ.
  *Sắp trễ* là chuyện thứ ba, thuộc nhịp bình thường của công việc.
- Hỏi: Dự án vào *đóng* thì có phải thông báo toàn đội không? → Đáp: **không cần**. Agent không được đánh
  thức nữa thì tự nhiên hết việc. Chỉ giữ vế lịch sử ở dạng chỉ đọc (FR-005).
- Hỏi: Cấm thợ báo cáo vượt cấp (FR-071) có cứng nhắc quá không? → Đáp: **viết lại cho đúng cách hệ chạy**.
  Thợ chỉ cần biết đầu việc của nó, nộp thành phẩm, và báo cáo trong phòng cộng tác hoặc bình luận của đầu
  việc đó. Trưởng dự án được đánh thức và đọc thay; người chủ thích thì vào đọc, không thì thôi. Không cần
  một lệnh cấm — chỉ cần không mở lối nào cho thợ đi thẳng tới hộp thư người chủ.
- Hỏi: Công tắc `yolo_mode` đang có trong mã thì giữ hay gỡ? → Đáp: **gỡ hẳn**. Nó không liên quan tới tính
  năng này, và việc nó từng làm đã được hai cơ chế chuẩn hơn thay: luật "trong khuôn kế hoạch đã duyệt" cho
  khâu tạo đầu việc, và công tắc tự động công nhận riêng từng người chủ cho khâu ký đầu ra.

### Phiên 2026-08-03 — một người chủ cho mỗi dự án

- Hỏi: Câu chuyện 3 viết theo giả định **nhiều người chủ** cùng cấp agent vào một dự án. Sản phẩm hiện không
  có khái niệm đó — mỗi vùng làm việc có đúng một người sở hữu, mọi lối vào đều kiểm "có phải chủ vùng này
  không", và không có bảng nào ghi ai được tham gia vùng của người khác. Lối mời sẵn có là mời **agent**,
  không phải mời người. Vậy làm gì? → Đáp *(người chủ chốt)*: **tạm thời một người chủ cho mỗi dự án**. Cơ
  chế mời người vào vùng làm việc là **tính năng sau**, không nằm trong đặc tả này.
- Hệ quả: quy tắc **hai chữ ký không đổi** — Trưởng dự án là agent, người chủ là người, hai bên vẫn kiểm được
  nhau. Công tắc tự động công nhận cũng không đổi. Thứ hoãn lại chỉ là phần **định tuyến giữa nhiều người
  chủ**: SC-014, vế "không người chủ nào bật thay người khác" ở FR-038, và bước kiểm "hộp thư người kia không
  có gì".
- Vẫn ghi **ai đã cấp agent vào ghế** ngay từ bây giờ (FR-034), dù hiện luôn ra cùng một người. Không ghi thì
  ngày bật nhiều người chủ, hệ thống phải **đoán ngược** lịch sử ai cấp ai, và bản đoán đó nằm vĩnh viễn
  trong dữ liệu thật — không ai phân biệt được đâu là sự thật, đâu là suy đoán.
- Sửa luôn một câu sai gốc ở mục Giả định: đặc tả này từng ghi tính năng "bám trên nền hạ tầng đã có: vùng
  làm việc, **quyền**…". Phần quyền cho **người** chưa hề có, và chính câu đó đẻ ra toàn bộ giả định nhiều
  người chủ ở trên.

### Phiên 2026-08-16 — hội tụ Giai đoạn 10, nhóm việc thứ nhất

- Hỏi: Vì sao **hai** vòng chạy ngầm cùng đi tìm "đầu việc nào không ai sắp chạm vào"? → Đáp *(người chủ
  chốt)*: **bỏ hẳn loại điểm treo *im lâu* khỏi nhịp điều phối** (FR-052). Chỉ mình nó buộc nhịp điều phối
  phải hỏi câu đó, mà đó đúng là câu vòng quét canh gác (FR-057) sinh ra để trả lời — bằng **động cơ đẩy**
  (FR-056), thứ phân biệt được *"đã gọi người làm nhưng lượt chạy chưa khởi động"* với *"gọi lại mấy lần đều
  không tới được người làm"*. Nhịp điều phối không đọc động cơ đẩy lấy một lần, nên nó đếm nhầm cả hai ca
  đó là im lâu, dù FR-063 nói thẳng ca sau không được tính.

  Trưởng dự án **không mất tin**: thang phục hồi vốn đã gọi nó ở Mức 2, có ngân sách và có ghi sổ. *Im lâu*
  chỉ là con đường thứ hai tới cùng một người với cùng một tin, đi tắt qua thang. Cái giá: Trưởng nghe muộn
  hơn (Mức 2 tới sau khoảng 35 phút thay vì 5 phút) — không đáng kể với nhịp dự án *vài giờ tới vài ngày*,
  đổi lại tin ấy **luôn đúng**. Thay thế cho phiên 2026-07-31, vế ngưỡng *im lâu* = 5 phút.
- Hỏi: Thang phục hồi có được vào Mức 1 khi đầu việc **chưa gán ai** không? → Đáp *(người chủ chốt)*:
  **không** — kiểm trước, không có người phụ trách thì lên thẳng Mức 2, ghi rõ lý do. Mã hiện tại biết là
  không gọi được ai nhưng vẫn đếm đủ ba lần thử rồi mới đi tiếp, tiêu khoảng 35 phút không làm gì. Chép
  thành **FR-059a**: điều kiện vào một nấc phải kiểm được **trước khi** bước vào nấc đó.
- Hỏi: Luật "tám phần cho **mọi** gói tin đánh thức" có hợp lý không? → Đáp *(người chủ chốt)*: **bỏ**. Mỗi
  lần gọi dậy có một mục đích và một người nhận khác nhau; ép chung khuôn là bắt một vai điền vào ô của vai
  khác. Thay bằng **lõi bốn phần** bắt buộc cho mọi lời gọi, cộng phần riêng theo từng loại — **FR-044**,
  **FR-044a**, FR-045 viết lại, SC-005 sửa theo.
- Hỏi: FR-057 ghi vòng quét canh gác rà "mọi đầu việc chưa đóng", nhưng *nháp/đề xuất* và *tồn kho* có nên
  rà không? → Đáp: **không**. Cả hai chưa có ai hứa sẽ chạm vào, quét thì chúng nổi cờ đình trệ ngay lượt
  đầu. FR-057 viết lại thành bốn trạng thái *đang trên bảng*, kèm lý do loại trừ.
- Ba chỗ đặc tả đang đúng nhưng **không có răng**, vá luôn để nửa mã không phải bàn lại:
  - **FR-048a** — hai danh sách cớ đánh thức phải cưỡng chế tại chỗ phát lệnh, không được làm tài liệu suông.
    Hiện chỉ bài kiểm đọc chúng, nên chúng đã trôi khỏi thực tế mà không ai biết.
  - **FR-070a** — phải có lối sửa đầu việc sau khi tạo, và cổng nào áp là do **ai gọi** quyết. Không có lối
    này thì FR-070 chỉ đúng trên giấy.
  - **FR-084a** — câu báo lỗi cũng là chuỗi hiển thị: máy chủ trả mã lỗi và tham số, giao diện dựng câu.
  - Mục Giả định gọi tên **bốn ngưỡng** còn đóng cứng, để "mọi ngưỡng chỉnh được" không còn chỗ lách.

---

## Kịch bản người dùng & kiểm thử *(bắt buộc)*

**Tiêu chí tối thượng — mọi kịch bản dưới đây phục vụ đúng câu này:**

> Người chủ chỉ **bắt buộc** làm hai việc: **DUYỆT** (một kế hoạch hoặc một bước lớn được phép chạy) và
> **CÔNG NHẬN ĐẦU RA** (approve kết quả của một đầu việc, kể cả mốc lớn giữa chừng). Mọi khâu còn lại —
> chẻ việc, giao việc, theo dõi, gỡ vướng, gom kết quả, phục hồi sự cố — do đội agent tự gánh. Ngoài hai
> việc bắt buộc đó, người chủ **được quyền** can thiệp sâu hơn như một người điều phối đồng hành, nhưng đó
> là *tuỳ chọn*, không phải nghĩa vụ.

Bốn tác nhân trong mọi dự án: **người chủ** (con người), **Trưởng dự án** (một agent điều phối), **thợ**
(nhiều agent thực thi), **hệ thống** (nền tảng — giữ trạng thái, đánh thức, chặn cổng, chuyển tin, ghi vết;
không nghĩ hộ, không quyết thay ai).

---

### Câu chuyện 1 — Dự án có giai đoạn và cổng duyệt kế hoạch bắt buộc (Ưu tiên: P1)

Người chủ mở một dự án, khai vai và cấp thợ vào từng ghế. Khi mọi ghế đã có thợ và mọi thợ đều trực tuyến,
dự án tự rời giai đoạn thiết lập, Trưởng dự án được đánh thức lần đầu, trò chuyện với chủ để chốt **Bối cảnh
dự án**, rồi trình một bản kế hoạch. Dự án đứng lại ở cổng duyệt cho tới khi chủ gật. Chủ gật thì dự án vào
vận hành; chưa gật thì chưa một đầu việc thật nào được giao.

**Vì sao ưu tiên này**: Đây là khung xương của mọi thứ còn lại. Không có giai đoạn thì không biết lúc nào
được làm gì; không có cổng duyệt thì đội agent chạy trước khi chủ đồng ý — phá thẳng tiêu chí tối thượng.
Mọi câu chuyện sau đều giả định dự án đã có giai đoạn và Bối cảnh.

**Kiểm thử độc lập**: Tạo một dự án, để trống một ghế → dự án phải nằm ở thiết lập, không đánh thức ai. Cấp
đủ thợ và cho mọi thợ trực tuyến → dự án tự sang lập kế hoạch và Trưởng dự án được gọi dậy đúng một lần. Thử
tạo đầu việc thật lúc này → bị từ chối. Chủ duyệt kế hoạch → dự án sang vận hành và cửa tạo đầu việc mở ra.

**Kịch bản chấp nhận**:

1. **Cho** một dự án còn ghế trống, **khi** hệ thống rà điều kiện chuyển giai đoạn, **thì** dự án vẫn ở
   *thiết lập* và không agent nào bị đánh thức.
2. **Cho** một dự án đã cấp đủ thợ nhưng một thợ đang ngoại tuyến, **khi** hệ thống rà điều kiện, **thì** dự
   án vẫn ở *thiết lập*.
3. **Cho** mọi ghế đã có thợ và mọi thợ đều trực tuyến, **khi** hệ thống rà điều kiện, **thì** dự án chuyển
   sang *lập kế hoạch* và Trưởng dự án nhận một gói tin đánh thức có lý do "dự án vừa đủ đội, cần bạn làm rõ
   Bối cảnh rồi lập kế hoạch".
4. **Cho** dự án đang ở *lập kế hoạch*, **khi** ai đó cố tạo hoặc giao một đầu việc thật, **thì** hệ thống từ
   chối kèm lời báo "kế hoạch chưa được duyệt".
5. **Cho** một bản kế hoạch đang treo ở cổng duyệt, **khi** Trưởng dự án cố tự duyệt bản kế hoạch của chính
   nó, **thì** hệ thống từ chối.
6. **Cho** người chủ chọn *yêu cầu chỉnh* kèm góp ý, **khi** quyết định được ghi nhận, **thì** Trưởng dự án
   được đánh thức lại kèm góp ý và dự án vẫn nằm ở *lập kế hoạch*.
7. **Cho** người chủ chọn *duyệt*, **khi** quyết định được ghi nhận, **thì** dự án chuyển sang *vận hành*,
   mốc duyệt được ghi vết, và Trưởng dự án được đánh thức với việc kế tiếp "chẻ đầu việc và giao thợ".

---

### Câu chuyện 2 — Đầu việc chuẩn hoá với vòng đời và năm cổng chặn (Ưu tiên: P1)

Trưởng dự án chẻ kế hoạch đã duyệt thành các đầu việc. Mỗi đầu việc là một tấm thẻ có bộ trường chuẩn: mã
định danh bất biến, mô tả chi tiết bắt buộc, đúng một người phụ trách, danh sách việc phụ thuộc, một bộ tiêu
chí công nhận đặt trước khi làm, và một chỗ để nộp thành phẩm. Đầu việc đi qua tám trạng thái theo đúng
những đường được phép; hệ thống chặn mọi lối tắt.

**Vì sao ưu tiên này**: Đầu việc là ngôn ngữ chung của cả bốn tác nhân — mọi trao đổi, mọi lần đánh thức,
mọi lần công nhận đều quy về nó. Thiếu một trường quan trọng hoặc hở một cổng là mở đường cho "xong giả" và
đùn đẩy trách nhiệm.

**Kiểm thử độc lập**: Tạo một đầu việc thiếu mô tả chi tiết → không giao được. Gán người thứ hai → bị chặn.
Chuyển sang chờ rà soát khi chưa nộp thành phẩm → bị chặn. Đặt một quan hệ phụ thuộc khép vòng → bị chặn ngay
lúc tạo. Đi đúng đường thì đầu việc chạy trọn từ nháp tới xong và mở khoá đúng các việc phụ thuộc.

**Kịch bản chấp nhận**:

1. **Cho** một đầu việc mới tạo, **khi** hệ thống cấp mã định danh, **thì** mã có dạng *tiền tố tên dự án +
   số thứ tự*, và mọi nỗ lực sửa mã sau đó đều bị từ chối.
2. **Cho** một đầu việc còn trống mô tả chi tiết, **khi** ai đó chuyển nó sang *chờ làm*, **thì** hệ thống từ
   chối kèm lời báo "đầu việc chưa có mô tả chi tiết — không thể giao" và giữ nguyên ở *nháp*.
3. **Cho** một đầu việc đã có người phụ trách, **khi** ai đó gán thêm người thứ hai, **thì** hệ thống từ chối
   kèm lời báo "đầu việc đã có người phụ trách — hãy chuyển giao hoặc chẻ việc".
4. **Cho** một đầu việc còn hai việc phụ thuộc chưa xong, **khi** ai đó chuyển nó sang *chờ làm* hoặc *đang
   làm*, **thì** hệ thống từ chối và liệt kê mã của những việc phải xong trước.
5. **Cho** một đầu việc đang *đang làm* với ô thành phẩm trống, **khi** thợ chuyển nó sang *chờ rà soát*,
   **thì** hệ thống từ chối kèm lời báo "chưa có thành phẩm nộp kèm".
6. **Cho** một đầu việc ở *chờ làm*, *tồn kho* hoặc *nháp*, **khi** ai đó chuyển thẳng sang *xong*, **thì**
   hệ thống từ chối — không có lối tắt bỏ qua rà soát và bằng chứng.
7. **Cho** một đầu việc chuyển vào *bị chặn* hoặc *huỷ* mà không điền lý do, **khi** yêu cầu được gửi,
   **thì** hệ thống từ chối.
8. **Cho** một quan hệ phụ thuộc mới sẽ khép thành vòng, **khi** Trưởng dự án cố tạo nó, **thì** hệ thống từ
   chối ngay tại lúc tạo và nêu rõ vòng đó đi qua những đầu việc nào.
9. **Cho** một đầu việc vừa chuyển sang *xong*, **khi** hệ thống xử lý hệ quả, **thì** mốc hoàn tất được ghi,
   những đầu việc chỉ còn chờ nó được mở khoá, và Trưởng dự án được đánh thức để giao tiếp.
10. **Cho** một đầu việc nằm trong khuôn các hạng mục đã được duyệt, **khi** Trưởng dự án tạo và giao nó,
    **thì** hệ thống cho qua, không cần người chủ gật.
11. **Cho** một đầu việc nằm ngoài khuôn đã duyệt, **khi** Trưởng dự án cố giao nó, **thì** hệ thống giữ nó
    ở *nháp/đề xuất* và đặt một mục chờ duyệt vào hộp thư người chủ.

---

### Câu chuyện 3 — Hai chữ ký cho mọi đầu ra, kèm công tắc tự động công nhận (Ưu tiên: P2)

Thợ nộp thành phẩm và tự khai "xong phần tôi". Trưởng dự án đặt thành phẩm cạnh bộ tiêu chí công nhận rồi
chấm từng dòng. Nhưng Trưởng dự án gật **chưa đủ**: mọi đầu việc còn cần chữ ký của **người chủ đã mang con
agent làm việc đó vào dự án** — ai đưa agent vào thì chịu trách nhiệm cho đầu ra của nó. Người chủ thấy phiền
thì bật **công tắc tự động công nhận** cho phần của mình trong dự án đó; từ lúc ấy chữ ký của họ coi như có
sẵn và dự án chạy không dừng.

> **Phạm vi hiện tại — một người chủ cho mỗi dự án** *(chốt 2026-08-03)*. Sản phẩm chưa có cơ chế mời người
> vào vùng làm việc, nên "người chủ đã cấp agent" hiện luôn ra chính chủ vùng. Quan hệ *ai cấp agent nào* vẫn
> được ghi thật ngay lúc cấp ghế, để ngày mở nhiều người chủ không phải đoán ngược lịch sử. Phần **định tuyến
> giữa nhiều người chủ** hoãn sang tính năng sau; xem mục Làm rõ phiên 2026-08-03.

**Vì sao ưu tiên này**: Đây là chốt "công nhận đầu ra" trong tiêu chí tối thượng, và là cơ chế duy nhất chống
"xong giả". Quy tắc hai chữ ký cho mọi việc là luật đơn giản, không cần ai đoán việc nào đủ lớn để phải xin;
gánh nặng được điều tiết bằng công tắc chứ không bằng phán đoán. Nó xếp sau câu chuyện 2 vì cần bộ trường và
vòng đời đầu việc đã đứng.

**Kiểm thử độc lập**: Một dự án, một người chủ, một thợ. Thợ chạy tới nơi và Trưởng dự án chấm đạt → đầu việc
**chưa** đóng, một mục chờ công nhận rơi vào hộp thư người chủ, và hệ thống chỉ ra được nó rơi vào đó vì
người đó là **người đã cấp thợ**, chứ không phải vì họ tình cờ là chủ vùng làm việc. Người chủ công nhận →
đầu việc *xong*. Bật công tắc tự động công nhận → đầu ra kế tiếp đóng ngay sau khi Trưởng dự án gật, không
mục nào vào hộp thư, nhưng vết vẫn ghi rõ họ được coi là đã ký, lúc nào, cho đầu việc nào.

**Kịch bản chấp nhận**:

1. **Cho** một đầu việc *chờ rà soát*, **khi** Trưởng dự án chấm đạt hết tiêu chí, **thì** đầu việc **chưa**
   đóng — một mục "đầu ra chờ công nhận" xuất hiện trong hộp thư của người chủ đã cấp thợ phụ trách, kèm
   thành phẩm và bộ tiêu chí.
2. **Cho** một đầu ra vừa được Trưởng dự án tán thành, **khi** hệ thống chọn người phải ký, **thì** nó chọn
   theo **quan hệ ai đã cấp thợ đó vào ghế** — quan hệ này được ghi thật lúc cấp ghế và tra ra được, chứ
   không phải suy ra từ "ai là chủ vùng làm việc". *(Với một người chủ, hai đường ra cùng một người; luật vẫn
   phải đi đúng đường đầu, vì đó là thứ ngày mai mở nhiều người chủ sẽ dùng lại nguyên vẹn.)*
3. **Cho** mục chờ công nhận đó, **khi** người chủ chịu trách nhiệm công nhận, **thì** đầu việc chuyển *xong*
   và các việc phụ thuộc được mở khoá.
4. **Cho** một người chủ đã bật công tắc tự động công nhận trong dự án, **khi** Trưởng dự án tán thành một
   đầu ra của agent do người đó cấp, **thì** đầu việc đóng ngay, không mục nào rơi vào hộp thư, và vết ghi rõ
   người đó được coi là đã ký lúc nào cho đầu việc nào.
5. **Cho** công tắc tự động công nhận của một người chủ, **khi** Trưởng dự án cố bật hoặc tắt nó, **thì** hệ
   thống từ chối — công tắc là của người chủ, agent không đụng tới. *(Vế "một người chủ khác cố bật thay"
   hoãn cùng phần nhiều người chủ.)*
6. **Cho** một lần từ chối công nhận kèm phản hồi, **khi** quyết định được ghi nhận, **thì** đầu việc quay về
   *đang làm* (không phải *nháp*, không phải *huỷ*), lý do được ghi vết, việc kế tiếp đặt thành "sửa theo
   phản hồi", và **đúng người thợ cũ** được đánh thức lại.
7. **Cho** một đầu việc đã bị từ chối ba lần, **khi** lần từ chối thứ ba được ghi nhận, **thì** hệ thống kéo
   Trưởng dự án vào soát lại đề bài và bộ tiêu chí công nhận, thay vì để vòng sửa–nộp lặp vô tận.
8. **Cho** một dự án mà mọi đầu việc của đợt đã *xong*, **khi** hệ thống xử lý, **thì** **không** có cổng
   nghiệm thu cấp dự án nào bật lên; thay vào đó người chủ nhận một bản tổng kết đợt kèm các lựa chọn chuyển
   giai đoạn.

---

### Câu chuyện 4 — Gói tin đánh thức đủ ngữ cảnh và gộp lời gọi trùng (Ưu tiên: P2)

Mỗi lần một agent được gọi dậy, nó nhận một phong bì thông tin có bố cục cố định: vai của mình, Bối cảnh dự
án, đầu việc đang nói tới, **lý do gọi dậy** viết thành câu người đọc hiểu, danh bạ đồng đội, tin nhắn mới,
việc kế tiếp đang chờ nó, và nơi nộp thành phẩm. Không phần nào bị bỏ trống âm thầm. Nhiều cớ gọi dồn về cùng
một agent trên cùng một đầu việc thì được gộp thành đúng một lượt.

**Vì sao ưu tiên này**: Agent ngủ giữa các lượt và mất trí nhớ làm việc. Gói tin thiếu ngữ cảnh biến mỗi lần
gọi dậy thành một cuộc dò tìm; gọi trùng thì sinh chạy chồng, nộp trùng, giẫm hỏng dữ liệu.

**Kiểm thử độc lập**: Gọi dậy một thợ vì một đầu việc mới giao → kiểm gói tin có đủ **lõi bốn phần** cộng
phần riêng của lời gọi thợ, phần nào có mặt mà không có nội dung thì ghi "không có" chứ không để trống. Gọi
dậy Trưởng dự án theo nhịp điều phối → cũng đủ lõi bốn phần, nhưng **không** mang các phần chỉ thuộc về lời
gọi thợ. Bắn ba cớ gọi cùng lúc cho một cặp agent–đầu việc → agent chỉ thấy đúng một lần gọi, với lý do gộp
liệt kê đủ ba cớ.

**Kịch bản chấp nhận**:

1. **Cho** bất kỳ lần đánh thức nào, **khi** gói tin được dựng, **thì** nó chứa đủ **lõi bốn phần** cùng phần
   riêng của loại lời gọi đó, và mọi phần có mặt mà rỗng đều ghi rõ "không có".
2. **Cho** bất kỳ lần đánh thức nào, **khi** agent mở gói tin, **thì** phần *lý do gọi dậy* là một câu cụ thể
   (ví dụ "thợ vừa nộp bài đầu việc AR-12, cần bạn rà soát"), không phải một cú thúc trống.
3. **Cho** một agent đang có một lệnh gọi treo cho một đầu việc, **khi** một cớ gọi thứ hai cho đúng cặp đó
   phát sinh, **thì** cớ mới nhập vào lệnh đang treo và mang theo lý do mạnh hơn — **không** sinh lệnh thứ hai.
4. **Cho** một agent đang chạy một lượt trên một đầu việc, **khi** một cớ gọi mới cho đúng cặp đó phát sinh,
   **thì** lượt đang chạy hấp thụ nó; khi lượt kết thúc hệ thống đánh giá lại xem còn cần gọi nữa không rồi
   mới bắn.
5. **Cho** một thợ vừa nộp bài và bóng đã chuyền sang Trưởng dự án, **khi** việc rà soát diễn ra, **thì** thợ
   đó **không** bị đánh thức.
6. **Cho** một agent kết thúc lượt, **khi** nó ngủ, **thì** hệ thống đã lưu *việc kế tiếp* của nó — hoặc chỉ
   rõ bóng đã chuyền cho ai, hoặc mô tả phần còn dở để lần sau tiếp đúng chỗ.

---

### Câu chuyện 5 — Trưởng dự án là quản lý có nhịp điều phối, không phải đồng hồ chờ chuông (Ưu tiên: P3)

Trưởng dự án tự đi rà bảng việc theo một nhịp *có kiểm soát*: trước mỗi nhịp hệ thống tự soi xem có đầu việc
nào sắp trễ, đang mắc kẹt, hay đang chờ quyết định của nó. Có thì gọi dậy kèm danh sách đích danh những điểm
cần nhìn. Không có thì bỏ qua nhịp đó trong im lặng.

**Vì sao ưu tiên này**: Không có nhịp này thì mọi đầu việc chỉ tiến khi có ai đó gõ cửa — dự án đứng im mà
không ai biết. Nhưng nó xếp sau câu chuyện 4 vì phải có gói tin đánh thức chuẩn trước. Đây cũng là vai bị
đánh rơi trong bản thiết kế cũ.

**Kiểm thử độc lập**: Để một dự án chạy trơn tru không có điểm treo → đếm số lần Trưởng dự án bị gọi dậy theo
nhịp phải bằng không. Đẩy một đầu việc sang *bị chặn* → nhịp kế tiếp gọi dậy Trưởng dự án với lý do nêu đích
danh đầu việc đó.

**Kịch bản chấp nhận**:

1. **Cho** một dự án không có đầu việc nào sắp trễ, mắc kẹt hay chờ quyết định, **khi** một nhịp điều phối
   đến hạn, **thì** hệ thống **không** đánh thức Trưởng dự án và nhịp đó trôi qua trong im lặng.
2. **Cho** một dự án có ba điểm treo, **khi** nhịp đến hạn, **thì** Trưởng dự án được gọi dậy đúng một lần
   với lý do liệt kê đủ ba điểm ("đầu việc X đang bị chặn, đầu việc Y sắp trễ, đầu việc Z đang chờ bạn
   quyết").
3. **Cho** một dự án đang chạy trơn tru trong thời gian dài, **khi** hệ thống điều tiết nhịp, **thì** khoảng
   cách giữa các lần rà tự giãn ra; khi xuất hiện dấu hiệu ứ đọng thì nhịp dày trở lại.
4. **Cho** một khoảng thời gian bất kỳ, **khi** đếm số lần Trưởng dự án bị gọi dậy theo nhịp, **thì** con số
   không vượt trần đã đặt.

---

### Câu chuyện 6 — Lưới an toàn: không đầu việc nào được âm thầm chết (Ưu tiên: P3)

Mỗi đầu việc chưa đóng phải trả lời được câu "cái gì sẽ đẩy nó tiến tiếp?" bằng đúng một trong sáu **động cơ
đẩy**. Một vòng quét định kỳ kiểm xem động cơ ấy còn sống không. Mất động cơ thì đầu việc bị nổi cờ **đình
trệ** — và đi vào thang phục hồi ba mức: hệ thống tự gọi lại, Trưởng dự án quyết một hành động, cuối cùng mới
tới người chủ.

**Vì sao ưu tiên này**: Đây là lằn ranh đạo đức của cả hệ thống — thà một đầu việc đứng im *có cờ* để người ta
thấy, còn hơn đứng im *lặng lẽ* rồi bị tưởng là đã xong. Nó xếp sau vì cần vòng đời đầu việc và cơ chế đánh
thức đã đứng vững để bám vào.

**Kiểm thử độc lập**: Giết một lượt chạy giữa chừng → trong vòng một chu kỳ, đầu việc phải bị phát hiện, kéo
về trạng thái làm được, và người phụ trách cũ được gọi lại đúng chỗ đang dở. Làm cho một đầu việc mất hết
động cơ → nó phải mang cờ đình trệ chứ không bao giờ tự nhảy sang *xong*.

**Kịch bản chấp nhận**:

1. **Cho** một đầu việc chưa đóng ở bất kỳ thời điểm quét nào, **khi** hệ thống rà, **thì** nó hoặc gắn đúng
   một động cơ đẩy còn sống, hoặc mang cờ *đình trệ*. Không có khả năng thứ ba.
2. **Cho** một đầu việc mất hết động cơ đẩy, **khi** hệ thống phát hiện, **thì** cờ đình trệ nổi lên kèm lý
   do, đầu việc **không bao giờ** bị chuyển sang *xong*, và nó vào thang phục hồi từ Mức 1.
3. **Cho** một lượt chạy tắt nhịp báo sống quá ngưỡng nghi treo, **khi** cửa sổ ân hạn trôi qua mà vẫn im,
   **thì** hệ thống tuyên treo, đóng lượt chạy ma, kéo đầu việc về *chờ làm*, và gọi lại **đúng người phụ
   trách cũ** trỏ vào việc kế tiếp đã lưu — phần đã làm không mất.
4. **Cho** một đầu việc đã được tự gọi lại đủ trần ba lần cho cùng một nguyên nhân mà vẫn không tiến, **khi**
   hệ thống rà, **thì** nó dừng tự thử và chuyển lên Mức 2, đánh thức Trưởng dự án kèm hồ sơ đã thử.
5. **Cho** một đầu việc có tiến triển thật (nộp thêm, đổi trạng thái tiến lên, báo sống lại), **khi** hệ thống
   ghi nhận, **thì** bộ đếm ngân sách tự phục hồi được đặt lại về không.
6. **Cho** một lần leo lên Mức 3, **khi** thông báo được đẩy vào hộp thư người chủ, **thì** nó kèm hồ sơ đã
   thử (Mức 1 làm gì mấy lần, Mức 2 quyết gì) và nêu **chính xác** điều cần người chủ quyết.
7. **Cho** một lệnh đánh thức không tới được agent, **khi** hệ thống thử lại theo nhịp giãn dần, **thì** đầu
   việc gắn động cơ "đang chờ hành động phục hồi" và **không** bị tính là đình trệ trong suốt thời gian đó.
8. **Cho** một thợ bị tuyên ngoại tuyến, **khi** hệ thống xử lý, **thì** đầu việc về *bị chặn* với lý do
   "người phụ trách ngoại tuyến" và Trưởng dự án được báo để giao lại người.
9. **Cho** Trưởng dự án bị tuyên ngoại tuyến, **khi** hệ thống xử lý, **thì** người chủ được báo thẳng — vì
   không còn ai điều phối.
10. **Cho** một hoặc nhiều mục chờ người chủ vượt ngưỡng nhắc, **khi** hệ thống nhắc, **thì** nó nhắc theo ba
    bậc thưa dần vào hộp thư người chủ, dự án đậu lại đúng chỗ chờ, và Trưởng dự án vẫn cho chạy tiếp mọi
    nhánh không phụ thuộc vào quyết định đang chờ.

---

### Các tình huống biên

- **Ghế trống hoặc thợ chưa lên mạng ở khâu thiết lập** — dự án nằm lại ở *thiết lập*, không đánh thức ai,
  không tạo được đầu việc thật. Không có đường tắt "cho chạy tạm".
- **Một thợ trực tuyến lúc chuyển giai đoạn rồi rớt mạng ngay sau đó** — dự án đã vào *lập kế hoạch* thì không
  bị kéo ngược về *thiết lập*; xử lý theo nhánh agent ngoại tuyến (giao lại người hoặc treo chờ).
- **Người chủ im lặng ở cổng duyệt kế hoạch** — dự án đậu chờ vô thời hạn, nhắc ba bậc thưa dần, **không** tự
  duyệt, **không** tự đánh dấu thất bại.
- **Một phê duyệt khoá toàn bộ dự án** (không còn nhánh độc lập nào để chạy) — hệ thống nhắc rõ rằng dự án
  đang đứng vì chờ người chủ, nhưng tuyệt đối không tự kết luận hộ.
- **Thợ trả việc hoặc hỏi lại thay vì làm** — đây là hành vi lành mạnh, không phải thất bại: đầu việc chuyển
  sang chờ Trưởng dự án xử lý (động cơ đẩy hợp lệ, không đình trệ), Trưởng dự án đổi người, chẻ lại, làm rõ
  đề, hoặc cấp thêm ngữ cảnh.
- **Phụ thuộc khép vòng lọt lưới cổng** — vòng quét phát hiện một chùm đầu việc chỉ chờ lẫn nhau, đánh dấu cả
  chùm là đình trệ để Trưởng dự án phá vòng.
- **Hai đầu việc tranh cùng một thợ hoặc một tài nguyên độc chiếm** — xếp hàng theo độ ưu tiên, rồi hạn chót,
  rồi tuổi đời; việc cũ được nâng dần để không bị bỏ đói. Vòng chờ tài nguyên xử như phụ thuộc vòng.
- **Trưởng dự án đổi kế hoạch giữa chừng** — được phép, nhưng mọi đầu việc bị ảnh hưởng phải về một trạng
  thái có động cơ đẩy hợp lệ; cái nào bỏ thì vào *huỷ* kèm lý do, không để lơ lửng. Nếu thay đổi chạm phạm
  vi, mục tiêu, chi phí, thời hạn hay tiêu chí công nhận thì treo chờ người chủ duyệt lại.
- **Lượt chạy chết vì sự cố hạ tầng** — xử như treo: đầu việc về trạng thái bền cuối cùng đã chốt, gọi lại
  theo việc kế tiếp; không bắt đầu lại từ số không.
- **Thành phẩm biến mất lúc chuẩn bị công nhận** — kéo đầu việc về đúng bước tạo ra thành phẩm đó, ghi vết
  mất mát, giữ lại các phần đã chốt để chỉ làm lại phần thiếu.
- **Dự án kiểu bảo trì không bao giờ có đầu việc cuối** — nó sống ở *bảo trì* tới khi người chủ quyết đóng;
  hệ thống không tự tuyên bất kỳ dự án nào là hoàn thành.
- **Cả cổng liên lạc ra ngoài sập, không đánh thức được ai** — đây là sự cố hạ tầng, báo thẳng người chủ.

---

## Yêu cầu *(bắt buộc)*

### Từ dùng chung, để không hiểu chệch

Chữ **"vòng"** trong tài liệu này gánh **ba nghĩa không liên quan gì nhau**. Đọc nhầm một chỗ là hiểu sai
một luật, nên chúng được gọi bằng ba tên riêng và tài liệu KHÔNG dùng chữ "vòng" trần trụi khi có thể nhầm:

| Gọi là | Nghĩa | Ở đâu |
|---|---|---|
| **vòng rà soát** | một lượt nộp – chấm của một đầu việc | FR-033 → FR-041a |
| **lượt rà** | một lần bộ điều phối hoặc lưới an toàn quét bảng việc | FR-052 → FR-057 |
| **phụ thuộc khép vòng** | quan hệ phụ thuộc quay lại chính nó | FR-032 |

Về **vòng rà soát**: hệ thống KHÔNG đánh số nó và KHÔNG dùng số thứ tự của nó cho bất kỳ quyết định nào
(xem FR-041a). Riêng FR-041 đếm **số lần bị trả về** — đó là một phép đếm trên sổ chữ ký, không phải một số
thứ tự gắn trên từng chữ ký.

### Yêu cầu chức năng

#### A. Dự án và vòng đời giai đoạn

- **FR-001**: Mỗi dự án PHẢI mang đúng một giai đoạn trong năm giá trị: *thiết lập*, *lập kế hoạch*, *vận
  hành*, *bảo trì*, *đóng*.
- **FR-002**: HỆ THỐNG PHẢI giữ dự án ở *thiết lập* cho tới khi mọi ghế đã được cấp thợ VÀ mọi thợ đều đang
  trực tuyến; khi đủ điều kiện, chuyển sang *lập kế hoạch* và đánh thức Trưởng dự án lần đầu.
- **FR-003**: HỆ THỐNG PHẢI từ chối mọi thao tác tạo hoặc giao đầu việc thật khi dự án chưa ở *vận hành* hoặc
  *bảo trì*.
- **FR-004**: Chỉ người chủ được chuyển dự án sang *đóng*. Chuyển giữa *vận hành* và *bảo trì* do Trưởng dự
  án đề xuất và người chủ quyết.
- **FR-005**: KHI dự án chuyển sang *đóng*, HỆ THỐNG PHẢI dừng mọi nhịp đánh thức của dự án đó và giữ toàn
  bộ lịch sử ở dạng chỉ đọc để người chủ xem lại bất cứ lúc nào. KHÔNG cần thông báo cho đội — agent không
  được đánh thức nữa thì tự nhiên hết việc.
- **FR-005a**: KHI dự án chuyển sang *đóng*, HỆ THỐNG PHẢI đánh dấu **hết hiệu lực** mọi mục hộp thư của dự
  án đó còn đang chờ người chủ trả lời, thuộc mọi loại. Dấu này KHÔNG ĐƯỢC dùng chung với dấu *đã xử lý*:
  người chủ chưa hề trả lời, ghi là đã trả lời là ghi sai lịch sử. Mục vẫn nằm lại trong hộp thư và vẫn đọc
  lại được, chỉ thôi được tính vào số đang chờ và thôi bị thang nhắc đòi trả lời. Lý do: một câu hỏi về dự án
  đã đóng là câu hỏi không bao giờ trả lời được, vì mọi hành động của nó đều bị FR-005 từ chối.
- **FR-005b**: Việc **đóng một mục hộp thư** KHÔNG tính là thao tác ghi vào dự án, nên PHẢI làm được kể cả
  khi dự án đã đóng. Nó chỉ dọn hộp thư của chính người chủ, không đổi gì trên đầu việc. Cấm gộp nó vào cùng
  chốt với các hành động ghi vào đầu việc (giao lại, đặt bước tiếp theo, huỷ): gộp một lần đã để lại những
  mục hộp thư không bao giờ dọn được và một con số đang chờ không bao giờ về không.
- **FR-006**: HỆ THỐNG KHÔNG ĐƯỢC tự tuyên bất kỳ dự án nào là hoàn thành. "Dự án xong" chỉ là một quyết định
  chuyển giai đoạn của người chủ.

#### B. Bối cảnh dự án

- **FR-007**: Mỗi dự án PHẢI có một khối **Bối cảnh** gồm: mục tiêu tối hậu, bối cảnh/lý do, các ràng buộc
  cứng, phạm vi, và những nguyên tắc chung mọi agent phải theo.
- **FR-008**: Trưởng dự án PHẢI soạn Bối cảnh ở giai đoạn *lập kế hoạch* thông qua đối thoại với người chủ;
  người chủ duyệt Bối cảnh cùng lúc với kế hoạch.
- **FR-009**: HỆ THỐNG PHẢI đính Bối cảnh đang hiệu lực vào **mọi** gói tin đánh thức gửi tới **mọi** agent
  của dự án.
- **FR-010**: Sửa Bối cảnh theo hướng đổi mục tiêu hoặc phạm vi PHẢI treo chờ người chủ duyệt trước khi có
  hiệu lực.

#### C. Kế hoạch và cổng duyệt

- **FR-011**: Trưởng dự án PHẢI trình một bản kế hoạch (các hạng mục lớn, thứ tự, phụ thuộc, rủi ro thấy
  trước, mốc dự kiến, định nghĩa hoàn thành cho từng hạng mục) kèm Bối cảnh, và một tin nhắn tóm tắt cho
  người chủ.
- **FR-012**: HỆ THỐNG PHẢI chặn dự án chuyển sang *vận hành* cho tới khi người chủ duyệt kế hoạch. Đây là
  cổng bắt buộc, không có ngoại lệ.
- **FR-013**: HỆ THỐNG PHẢI cho người chủ đúng ba lựa chọn tại cổng duyệt: *duyệt*, *yêu cầu chỉnh* (kèm góp
  ý), *hỏi lại*.
- **FR-014**: HỆ THỐNG PHẢI cấm Trưởng dự án tự duyệt kế hoạch của chính nó và tự thay người chủ công nhận
  bất kỳ đầu ra nào.

#### D. Đầu việc — bộ trường

- **FR-015**: Mỗi đầu việc PHẢI mang các trường: mã định danh, tiêu đề, mô tả chi tiết, trạng thái, lý do
  trạng thái, độ ưu tiên, người phụ trách, người chủ chịu trách nhiệm công nhận (suy ra từ người đã cấp
  agent phụ trách vào ghế), việc phụ thuộc, đầu việc cha, định nghĩa hoàn thành, thành phẩm, việc kế tiếp,
  hạn chót, người tạo, mốc tạo, mốc bắt đầu làm, mốc hoàn tất, dự án chứa, nhật ký thay đổi.
- **FR-016**: HỆ THỐNG PHẢI sinh mã định danh dạng *tiền tố tên dự án + số thứ tự* khi tạo đầu việc, và mã đó
  PHẢI bất biến suốt đời đầu việc.
- **FR-017**: Mỗi đầu việc PHẢI có **đúng một** người phụ trách tại mọi thời điểm. Muốn nhiều người cùng làm
  thì chẻ thành nhiều đầu việc con; muốn đổi người thì chuyển giao.
- **FR-018**: Trường *mô tả chi tiết* PHẢI nói rõ đầu việc làm gì và làm thế nào; đây là trường bắt buộc.
  Thợ được bổ sung ghi chú tiến trình nhưng KHÔNG ĐƯỢC sửa yêu cầu gốc.
- **FR-019**: *Định nghĩa hoàn thành* PHẢI là một danh sách tiêu chí đúng/sai kiểm được, do Trưởng dự án đặt
  **trước khi** thợ bắt tay, và PHẢI tách bạch khỏi trường *thành phẩm*. HỆ THỐNG KHÔNG ĐƯỢC gộp hai trường
  này.
- **FR-019a** *(cổng thước đo)*: Trưởng dự án PHẢI **chấm** từng tiêu chí thành *đạt* hoặc *không đạt* khi
  đầu việc đang *chờ rà soát*; mỗi lần chấm *đạt* PHẢI chỉ ra một thành phẩm **của chính đầu việc đó** làm
  bằng chứng. HỆ THỐNG PHẢI từ chối mọi chữ ký tán thành — của Trưởng dự án lẫn của người chủ — khi còn tiêu
  chí *chưa chấm* hoặc *không đạt*, và PHẢI nêu tên những tiêu chí ấy. Từ chối này PHẢI xảy ra **trước khi**
  ghi chữ ký, chứ không phải lúc đóng: chặn ở lúc đóng thì chữ ký đã nằm trong sổ và đầu việc kẹt lại ở *chờ
  rà soát* với đủ hai chữ ký. Bộ tiêu chí **rỗng** đi qua cổng này — bắt buộc phải có tiêu chí là một luật
  khác, đặt ở lúc giao việc.
  *(Không có bước chấm thì FR-019 chỉ tạo ra một bản ghi chú: một danh sách "kiểm được" mà không ai kiểm
  không khác gì ô chữ tự do nó thay thế. Trước T178, hàm chấm điểm có sẵn trong mã nhưng **không lời gọi
  nào**, nên Trưởng dự án ký tán thành mà chưa từng đi qua bộ tiêu chí lấy một dòng.)*
- **FR-020**: *Việc kế tiếp* PHẢI được lưu bền và trả lại kèm trong gói tin mỗi lần agent được đánh thức lại
  trên đầu việc đó.
- **FR-021**: HỆ THỐNG PHẢI tự ghi các trường mã định danh, người tạo, ba mốc thời gian, dự án chứa và nhật
  ký thay đổi; các trường này PHẢI chỉ đọc với mọi tác nhân.

#### E. Đầu việc — vòng đời và cổng chặn

- **FR-022**: Đầu việc PHẢI mang đúng một trong tám trạng thái: *nháp/đề xuất*, *tồn kho*, *chờ làm*, *đang
  làm*, *chờ rà soát*, *bị chặn*, *xong*, *huỷ*. *Xong* và *huỷ* là trạng thái đóng.
- **FR-023**: HỆ THỐNG PHẢI chỉ chấp nhận các chuyển trạng thái hợp lệ; khi bị từ chối PHẢI giữ nguyên trạng
  thái cũ và nêu lý do rõ ràng — chặn thôi, không tự nghĩ hộ cách gỡ.
- **FR-024**: HỆ THỐNG PHẢI từ chối các lối tắt: từ *nháp*, *tồn kho* hoặc *chờ làm* sang thẳng *xong*; từ
  *đang làm* sang thẳng *xong*; từ *nháp* sang thẳng *đang làm*.
- **FR-025** *(cổng phụ thuộc)*: HỆ THỐNG PHẢI chặn một đầu việc vào *chờ làm* hoặc *đang làm* khi danh sách
  việc phụ thuộc còn ít nhất một đầu việc chưa *xong*, và PHẢI liệt kê mã của những việc còn thiếu.
- **FR-026** *(cổng bằng chứng)*: HỆ THỐNG PHẢI chặn một đầu việc vào *chờ rà soát* khi trường thành phẩm còn
  trống.
- **FR-027** *(cổng duyệt)*: Trưởng dự án ĐƯỢC tự tạo và giao ngay những đầu việc nằm **trong khuôn các hạng
  mục đã được người chủ duyệt**. Một đầu việc nằm **ngoài** khuôn đó PHẢI ở lại *nháp/đề xuất* và chỉ được
  rời *nháp* sau khi người chủ duyệt — vì nó là một lần nới phạm vi (nối với FR-075).
- **FR-028** *(cổng một-người)*: HỆ THỐNG PHẢI từ chối gán người thứ hai vào một đầu việc đã có người phụ
  trách.
- **FR-029** *(cổng mô tả)*: HỆ THỐNG PHẢI chặn giao một đầu việc khi mô tả chi tiết còn trống.
- **FR-030**: HỆ THỐNG PHẢI từ chối chuyển vào *bị chặn*, *huỷ*, hoặc trả lại sửa nếu trường lý do trạng thái
  còn trống.
- **FR-031**: KHI một đầu việc chuyển sang *xong*, HỆ THỐNG PHẢI ghi mốc hoàn tất, rà lại và mở khoá những
  đầu việc chỉ còn chờ nó, rồi đánh thức Trưởng dự án để giao tiếp.
- **FR-032**: HỆ THỐNG PHẢI từ chối tạo hoặc sửa một quan hệ phụ thuộc làm khép vòng, ngay tại lúc thao tác,
  và nêu rõ vòng đó đi qua những đầu việc nào.

#### F. Công nhận đầu ra

- **FR-033**: Mỗi đầu việc PHẢI cần **hai chữ ký** mới được đóng: Trưởng dự án, và **người chủ chịu trách
  nhiệm** cho con agent đã thực hiện đầu việc đó. Đây là mặc định áp cho **mọi** đầu việc — không có khái
  niệm cờ bật/tắt theo từng việc.
- **FR-034**: Người chủ chịu trách nhiệm cho một agent là **người đã cấp agent đó vào ghế** trong dự án. HỆ
  THỐNG PHẢI ghi lại quan hệ này ngay lúc cấp ghế và dùng nó để xác định ai phải ký cho đầu ra của agent đó.
  Quy tắc này giữ nguyên trong phạm vi **một người chủ**: quan hệ vẫn phải được ghi thật và tra cứu thật, dù
  hôm nay nó luôn ra chính chủ vùng làm việc. Suy thẳng từ "ai là chủ vùng" là **sai** — nó bỏ mất dữ kiện mà
  ngày mở nhiều người chủ sẽ không còn cách nào dựng lại.
- **FR-035**: SAU khi Trưởng dự án tán thành một đầu ra, HỆ THỐNG PHẢI đẩy đầu ra đó vào hộp thư của **đúng
  người chủ chịu trách nhiệm** và giữ đầu việc chưa đóng cho tới khi người đó công nhận.
- **FR-036**: Mỗi dự án PHẢI có một thiết lập **tự động công nhận** riêng cho từng người chủ tham gia dự án
  đó — khoá theo cặp *(dự án, người chủ)*, kể cả khi cặp đó hiện chỉ có một. KHI một người chủ bật thiết lập
  này, HỆ THỐNG PHẢI coi mọi việc cần chữ ký của người đó **cho công việc
  của các agent do họ cấp** là đã chuẩn thuận sẵn — công nhận đầu ra, và các bước chuyển trạng thái đầu việc
  cần họ gật — và đóng đầu việc ngay sau khi Trưởng dự án tán thành.
- **FR-037**: Thiết lập tự động công nhận KHÔNG ĐƯỢC thay người chủ ở ba quyết định cấp dự án: duyệt kế
  hoạch, duyệt một thay đổi lớn (FR-075), và quyết chuyển giai đoạn. Ba việc đó luôn cần người chủ ra tay
  thật, dù công tắc đang bật.
- **FR-038**: Thiết lập tự động công nhận PHẢI mặc định **tắt**. Chỉ chính người chủ đó được bật hoặc tắt cho
  phần của mình, và Trưởng dự án KHÔNG ĐƯỢC đụng tới nó. *(Vế "không người chủ nào bật thay người khác" hoãn
  cùng phần nhiều người chủ — hiện chưa dựng được tình huống đó.)*
- **FR-039**: KHI tự động công nhận đang bật, HỆ THỐNG PHẢI vẫn ghi vết đầy đủ: ai được coi là đã ký, cho đầu
  việc nào, vào lúc nào — để người chủ xem lại sau. Mọi lần bật/tắt thiết lập cũng PHẢI ghi vết.
- **FR-040**: KHI một đầu ra bị từ chối công nhận (bởi Trưởng dự án hoặc bởi người chủ chịu trách nhiệm), HỆ
  THỐNG PHẢI kéo đầu việc về *đang làm* (không phải *nháp*, không phải *huỷ*), ghi vết lý do, đặt việc kế
  tiếp thành "sửa theo phản hồi", và đánh thức lại đúng thợ đã làm.
- **FR-041**: SAU ba vòng từ chối trên cùng một đầu việc, HỆ THỐNG PHẢI kéo Trưởng dự án vào soát lại đề bài
  và định nghĩa hoàn thành.
- **FR-041a**: Một chữ ký chỉ có giá trị cho **bản thành phẩm đang được rà soát lúc nó được đặt xuống**. KHI
  đầu việc rời *chờ rà soát* mà không sang *xong* hoặc *đã huỷ* — bị trả về, bị kéo tay về *đang làm*, bị
  chặn, hay được **mở lại** sau khi đã đóng — HỆ THỐNG PHẢI đặt lại trạng thái đã-ký của đầu việc đó về
  **chưa ai ký**. Lần nộp sau là một lần rà soát mới, bắt đầu từ số không.

  Ràng buộc đi kèm, quan trọng ngang luật trên: đặt lại **KHÔNG ĐƯỢC** làm mất nội dung rà soát. Ai đã duyệt,
  ai đã trả về, lý do gì, lúc nào — tất cả PHẢI đọc lại được nguyên vẹn (FR-039, FR-040). Thứ được đặt lại
  chỉ là câu trả lời cho "bản *hiện tại* đã ai ký chưa".

  HỆ THỐNG KHÔNG ĐƯỢC trả lời câu hỏi đó bằng cách **suy ra** từ lịch sử ở nhiều nơi. Mọi nơi cần biết PHẢI
  hỏi qua **cùng một cửa**. *(Lý do điều khoản này tồn tại: trước đây "đang ở lần rà soát nào" được suy ra
  bằng cách đếm số lần bị trả về, ba nơi tự đếm, một nơi đếm khác — và đường "rời rà soát không qua cửa từ
  chối" thì không nơi nào đếm cả, nên bản đã sửa đóng lại được bằng chữ ký cho bản trước nó.)*
- **FR-042**: HỆ THỐNG KHÔNG ĐƯỢC có cổng nghiệm thu ở cấp dự án. Việc công nhận diễn ra ở cấp đầu việc;
  chuyển giai đoạn diễn ra ở cấp dự án.
- **FR-043**: KHI cả một đợt việc đã *xong*, HỆ THỐNG PHẢI đánh thức Trưởng dự án soạn bản tổng kết đợt, rồi
  đẩy vào hộp thư người chủ kèm ba lựa chọn: đóng dự án, chuyển bảo trì, hoặc mở đợt việc mới.

#### G. Gói tin đánh thức và điều phối lời gọi

- **FR-044**: Mỗi gói tin đánh thức PHẢI gồm một **lõi bốn phần**, không lời gọi nào được miễn:
  1. **vai của agent trong dự án này**;
  2. **Bối cảnh dự án đã duyệt** — bản đã qua cổng duyệt, không phải cột thô trên bảng dự án (FR-009);
  3. **lý do gọi dậy** (FR-046);
  4. **danh bạ đồng đội kèm trạng thái trực tuyến**.

  Bốn phần này trả lời ba câu mà agent nào cũng phải biết trước khi làm bất cứ việc gì: *mình là ai ở đây*,
  *dự án đang đi đâu*, *tại sao bị gọi lúc này*. Thiếu một cái là agent đoán, mà agent đoán là agent làm sai.
- **FR-044a**: Ngoài lõi, mỗi **loại lời gọi** PHẢI mang thêm đúng phần loại đó cần, và HỆ THỐNG KHÔNG ĐƯỢC
  ép mọi loại dùng chung một khuôn:
  - *gọi thợ vào một đầu việc* — đầu việc đang nói tới kèm mô tả và trạng thái; tin nhắn mới kể từ lượt
    trước; việc kế tiếp đang chờ; nơi nộp thành phẩm và cách báo trạng thái.
  - *gọi Trưởng dự án theo nhịp điều phối* — danh sách điểm treo nêu đích danh từng điểm (FR-054).
  - *gọi Trưởng dự án vì người chủ vừa quyết một điều* — chính quyết định đó, kèm nguyên văn góp ý nếu có.
  - *gọi Trưởng dự án ở Mức 2 của thang phục hồi* — hồ sơ đã thử, và ca nào dẫn tới Mức 2 (FR-059a).

  Vì sao tách: năm trong tám phần của khuôn cũ **vô nghĩa với Trưởng dự án**. Nó bị gọi vì lượt rà tìm ra ba
  điểm treo trên bảng — "đầu việc đang nói tới" là cái nào trong ba? "Việc kế tiếp" của một người điều phối
  là gì? "Nơi nộp thành phẩm" thì càng không. Ép chung khuôn là bắt một vai điền vào ô của vai khác, và một
  ô điền bừa còn tệ hơn một ô không có.
- **FR-045**: Phần nào **có mặt** trong loại lời gọi đó mà không có nội dung PHẢI ghi rõ "không có"; KHÔNG
  ĐƯỢC để trống âm thầm. Luật này KHÔNG buộc một loại lời gọi phải mang phần không thuộc về nó — nó chỉ cấm
  im lặng ở những phần loại đó đã nhận.
- **FR-046**: Phần *lý do gọi dậy* PHẢI là một câu người đọc hiểu nói thẳng vì sao agent bị gọi lúc này.
- **FR-047**: HỆ THỐNG PHẢI đánh thức Trưởng dự án khi và chỉ khi có một trong các cớ: người chủ nhắn hoặc
  hỏi; người chủ duyệt hoặc yêu cầu chỉnh kế hoạch; người chủ công nhận hoặc từ chối một đầu ra; người
  chủ quyết chuyển giai đoạn hoặc mở đợt mới; một thợ báo kẹt; một đầu việc chuyển sang *chờ rà soát*; một
  đầu việc chuyển sang *xong*; một đầu việc thất bại hoặc quá hạn; một nhịp điều phối có điểm treo thật;
  hoặc **bị nhắc tên** trong luồng trao đổi của một đầu việc.
- **FR-048**: HỆ THỐNG PHẢI đánh thức một thợ khi và chỉ khi có một trong các cớ: được giao đầu việc mới; bị
  nhắc tên trong trao đổi; có bình luận mới trên đầu việc mình phụ trách; cần làm tiếp một lượt còn dở; vướng
  của mình đã được gỡ; **đầu ra của mình bị trả về để sửa** (FR-040); **yêu cầu của đầu việc bị người chủ đổi
  giữa chừng** (FR-070a); hoặc **lưới an toàn gọi lại** vì đầu việc mất động cơ đẩy (Mức 1 của thang phục
  hồi, FR-059). Cớ cuối là đường duy nhất để một đầu việc đứng im gọi được thợ dậy: nhịp điều phối (FR-052)
  không còn nhìn chuyện đứng im nữa, và cũng chưa bao giờ gọi thợ.
- **FR-048a**: Hai danh sách khép ở FR-047 và FR-048 PHẢI được **cưỡng chế ngay tại chỗ phát lệnh gọi**,
  không được để làm tài liệu suông. Một cớ không nằm trong danh sách của vai nhận thì lệnh gọi đó bị từ chối
  và ghi lại. Danh sách chỉ có sức nặng khi thêm một cớ mới **buộc** người thêm phải quyết ngay cớ đó gọi ai;
  để nó ngoài đường chạy thì nó trôi khỏi thực tế mà không ai biết. Ba điều kèm theo, để chốt này chặn đúng
  chứ không chặn bừa:
  - **Vai đọc từ công việc, không đọc từ hồ sơ agent**: ai đang giữ đầu việc là thợ của đầu việc ấy, ai ngồi
    ghế trưởng là Trưởng dự án. Một agent đội **cả hai vai** cùng lúc thì được gọi bởi cả hai danh sách —
    Trưởng dự án tự ôm một đầu việc là chuyện hợp lệ, chặn nó là từ chối đúng những lời gọi đúng.
  - **Cớ gọi thẳng tên** (bị nhắc tên) tới được cả hai vai: đây là lời gọi duy nhất do người gửi chọn người
    nhận, nên nó không thuộc riêng vai nào. Người không giữ đầu việc và cũng không dẫn dự án thì **chỉ** cớ
    này lọt tới — đúng tinh thần FR-049.
  - **Từ chối là từ chối lệnh gọi, không phải huỷ việc đang làm**: hành động sinh ra lệnh gọi ấy — bình luận
    vừa gửi, đầu việc vừa chuyển trạng thái — vẫn đứng. Lệnh gọi bị từ chối nằm lại trong sổ lệnh gọi với
    dấu riêng, vì thứ đáng bắt là **nếp lặp lại**, không phải một lần rơi.
- **FR-049**: HỆ THỐNG KHÔNG ĐƯỢC đánh thức một agent chỉ vì dự án có biến động chung — chỉ gọi khi có việc
  thuộc phần của chính nó đang chờ.
- **FR-050**: Với mỗi cặp *(agent, đầu việc)*, HỆ THỐNG PHẢI giữ tối đa **một** lệnh đánh thức đang treo và
  tối đa **một** lượt chạy tại một thời điểm. Cớ mới đến khi đã có lệnh treo thì nhập vào lệnh đó và mang
  theo lý do mạnh hơn; cớ đến khi đang có lượt chạy thì lượt chạy hấp thụ, và hệ thống đánh giá lại nhu cầu
  gọi khi lượt kết thúc.
- **FR-051**: Trước khi kết thúc một lượt, agent PHẢI để lại *việc kế tiếp* — hoặc chỉ rõ bóng đã chuyền cho
  ai, hoặc mô tả cụ thể phần còn dở. HỆ THỐNG PHẢI lưu bền phần này.

#### H. Nhịp điều phối của Trưởng dự án

- **FR-052**: HỆ THỐNG PHẢI chạy một nhịp điều phối định kỳ *có kiểm soát* cho Trưởng dự án: trước mỗi nhịp
  tự soi bảng việc tìm các **điểm treo**. Đúng ba loại, mỗi loại đọc **một trường** trên bảng việc và có một
  định nghĩa kiểm được:
  - *sắp trễ* — đầu việc có hạn chót và thời gian còn lại vừa chạm một trong các mốc cảnh báo. Đầu việc
    **không đặt hạn chót thì không bao giờ tính là sắp trễ**.
  - *mắc kẹt* — đầu việc đang ở trạng thái *bị chặn*.
  - *chờ quyết định của Trưởng dự án* — có một việc đang đợi chính Trưởng dự án ra tay.

  Nhịp này KHÔNG ĐƯỢC hỏi *"có gì sắp chạm vào đầu việc này không"*. Đó là câu hỏi của vòng quét canh gác
  (FR-057), thứ có **động cơ đẩy** (FR-056) để trả lời cho đúng và có thang phục hồi (FR-059) để xử lý câu
  trả lời — trong đó Mức 2 vốn đã gọi chính Trưởng dự án. Nhịp điều phối chỉ đọc những trường nó tự nhìn
  thấy trên bảng: hạn chót, trạng thái, sổ chữ ký.
- **FR-053**: NẾU không có điểm treo nào, HỆ THỐNG KHÔNG ĐƯỢC đánh thức Trưởng dự án; nhịp đó trôi qua trong
  im lặng.
- **FR-054**: NẾU có điểm treo, gói tin PHẢI nêu đích danh từng điểm cần nhìn, không nói chung chung "đến giờ
  rồi".
- **FR-055**: HỆ THỐNG PHẢI đặt trần số lần đánh thức theo nhịp trong một khoảng thời gian, tự giãn nhịp khi
  dự án **chạy trơn tru** và làm dày nhịp khi có **dấu hiệu ứ đọng**. Hai cụm đó không được để hiểu theo cảm
  tính — chúng là hai mặt của **một** phép đếm duy nhất:
  - *chạy trơn tru* = lượt rà tìm thấy **0 điểm treo** (ba loại ở FR-052, không loại nào khác);
  - *có dấu hiệu ứ đọng* = lượt rà tìm thấy **từ 1 điểm treo trở lên**.

  Độ giãn tính theo **số lượt rà liên tiếp** tìm thấy 0 điểm treo. Một lượt có điểm treo xoá sạch chuỗi đó và
  kéo nhịp về dày hơn mức đã đặt. HỆ THỐNG KHÔNG ĐƯỢC dùng bất kỳ thước đo "trơn tru" nào khác — không điểm
  số, không trung bình, không phán đoán.

  **Trần chỉ được phép hoãn, không được phép nuốt.** Hai loại điểm treo *mắc kẹt* và *chờ quyết định* được
  dựng lại từ bảng việc ở mọi lượt rà nên tự chúng thoả điều này. Riêng *sắp trễ* có trí nhớ: một mốc đã
  báo thì không báo lại. Vì vậy HỆ THỐNG chỉ được ghi một mốc hạn chót là **đã báo** khi lượt rà đó thật sự
  **giao được tới tay** Trưởng dự án. *Đã tiêu một lần gọi* KHÔNG đồng nghĩa *đã báo*: lượt rà bị trần chặn,
  lượt rà không có kênh gửi, và lượt rà gọi đi nhưng **không giao được** (Trưởng dự án ngoại tuyến hoặc đang
  giữa một lượt chạy) — cả ba đều KHÔNG ĐƯỢC tiêu mốc nào. Mốc phải còn nguyên cho lượt rà sau.

  Ca *không giao được* phải nói rõ vì dễ tưởng là an toàn: lời gọi có để lại một dòng trong sổ, nhưng **không
  cửa nào trong hệ đọc lại được dòng đó** — mọi phép đọc sổ lệnh gọi đều đòi mã đầu việc, mà lời gọi theo nhịp
  là lời gọi cấp dự án, không gắn đầu việc nào. Chừng nào chưa có mặt đọc cho nó thì ghi mốc là *đã báo* ở ca
  này chính là làm mất mốc.

#### I. Lưới an toàn và thang phục hồi

- **FR-056**: Mỗi đầu việc chưa đóng PHẢI gắn đúng một **động cơ đẩy** trong sáu loại: đang có lượt chạy; đã
  hẹn một lần đánh thức; đang chờ một mốc bên ngoài; đang chờ người chủ; đang bị chặn bởi việc khác; đang chờ
  một hành động phục hồi.
- **FR-057**: HỆ THỐNG PHẢI chạy một vòng quét canh gác định kỳ rà mọi đầu việc **đang trên bảng** — *chờ
  làm*, *đang làm*, *chờ rà soát*, *bị chặn* — kiểm xem động cơ đẩy có tồn tại và còn sống hay không.

  Hai trạng thái chưa đóng nằm **ngoài** vòng quét, và đó là chủ ý chứ không phải bỏ sót: *nháp/đề xuất* là
  đề nghị của Trưởng dự án đang chờ người chủ gật — chưa phải việc đã nhận, chưa ai hứa gì; *tồn kho* là việc
  đã đỗ có chủ ý. Quét hai loại đó thì mọi mục tồn kho nổi cờ đình trệ ngay lượt quét đầu tiên, và một báo
  động lúc nào cũng kêu là một báo động bị tắt.
- **FR-058**: KHI một đầu việc không còn động cơ đẩy sống, HỆ THỐNG PHẢI nổi cờ *đình trệ* kèm lý do, và
  KHÔNG ĐƯỢC chuyển đầu việc đó sang *xong* trong bất kỳ hoàn cảnh nào.

  Cờ *đình trệ* **không phải một trạng thái nghiệp vụ** — nó là báo động rằng hệ thống vừa đánh rơi một đầu
  việc. Trong một hệ chạy đúng nó không bao giờ nổi; nổi tức là có lỗi hoặc có sự cố. Vì vậy nó khác hẳn
  *sắp trễ* (nhịp bình thường của công việc, không ai làm sai) và khác *mắc kẹt* (đầu việc đang ở *bị chặn*,
  một tình trạng hợp lệ có động cơ đẩy đàng hoàng).
- **FR-059**: HỆ THỐNG PHẢI áp thang phục hồi ba mức theo đúng thứ tự, KHÔNG ĐƯỢC nhảy cóc: Mức 1 — hệ thống
  tự gọi lại, giữ nguyên người phụ trách, không quyết gì mới; Mức 2 — Trưởng dự án quyết một hành động phục
  hồi tường minh; Mức 3 — đẩy lên người chủ, chỉ với những quyết định duy nhất người chủ mới quyết được.
- **FR-059a**: Mỗi nấc có một **điều kiện vào**, và HỆ THỐNG PHẢI kiểm điều kiện đó **trước khi** bước vào
  nấc. Điều kiện vào Mức 1 là *đầu việc có người phụ trách* — vì Mức 1 định nghĩa là "hệ tự gọi lại, **giữ
  nguyên người phụ trách**". Đầu việc chưa gán ai thì Mức 1 không có đối tượng để tác động: HỆ THỐNG KHÔNG
  ĐƯỢC tiêu một lần thử nào ở nấc đó, và đầu việc PHẢI vào **thẳng Mức 2**.

  Đây KHÔNG phải nhảy cóc theo nghĩa FR-059 cấm. Nhảy cóc là bỏ qua một nấc **còn có thể chạy**; đây là một
  nấc **không áp dụng được**. Một cái thang bỏ ngân sách vào nấc nó biết chắc là trống thì không còn là
  thang, nó là đồng hồ đếm ngược — và cái giá đúng bằng cả ngân sách Mức 1 (mặc định 3 lần, giãn dần, khoảng
  35 phút) tiêu vào chỗ không ai nghe.

  Lời hỏi Trưởng dự án ở Mức 2 PHẢI nói rõ đầu việc **chưa có người phụ trách**, không được dùng chung câu
  chữ với ca kia. Hai ca dẫn tới Mức 2 cần hai hành động khác hẳn nhau: *gọi mãi người phụ trách không dậy*
  thì Trưởng đổi người hoặc gỡ chặn; *chưa ai được giao* thì Trưởng chỉ cần **giao việc**. Hồ sơ ở Mức 3
  (FR-061) PHẢI giữ được phân biệt đó — đây là ca thứ ba của cùng một luật mà FR-060a đã đặt ra cho *đã hỏi
  tới nơi* với *không gọi được*.
- **FR-060**: Mức 1 PHẢI có trần số lần tự gọi lại cho mỗi nguyên nhân trên mỗi đầu việc, khoảng cách giãn
  dần; bộ đếm PHẢI đặt lại về không khi đầu việc có tiến triển thật.
- **FR-060a**: Mức 2 PHẢI có trần số lần hỏi Trưởng dự án cho mỗi nguyên nhân, khoảng cách giãn dần như Mức 1.
  Trưởng dự án **ngoại tuyến** và Trưởng dự án **trực tuyến mà không phản hồi** PHẢI xử như nhau: cả hai đều là
  *đã hỏi, đầu việc vẫn đứng im*. Hết trần thì leo Mức 3, và hồ sơ PHẢI phân biệt được *đã hỏi tới nơi* với
  *không gọi được*, vì hai điều đó cần người chủ làm hai việc khác nhau.

  Thứ **kết thúc** Mức 2 là đầu việc có động cơ đẩy trở lại, KHÔNG phải lời khai của Trưởng dự án. Một lời khai
  không kèm hành động để lại đúng một đầu việc chết như trước, nên hệ chỉ được ghi nhận điều đối chiếu được
  với bản ghi.
- **FR-060b**: Hai lối vào của Trưởng dự án — *đã quyết hành động phục hồi* và *ngoài tầm xử lý, chuyển người
  chủ* — CHỈ được mở khi đầu việc đang ở Mức 2. Dưới Mức 2 hệ còn đang tự thử và chưa hỏi Trưởng dự án điều gì;
  từ Mức 3 trở lên câu hỏi đã thuộc về người chủ. Mở ngoài cửa sổ đó là phá luật không-nhảy-cóc của FR-059 từ
  phía người trả lời.
- **FR-061**: Mỗi lần leo lên Mức 3, HỆ THỐNG PHẢI kèm hồ sơ đã thử (Mức 1 làm gì mấy lần, Mức 2 hỏi mấy lần và
  có tới nơi không) và nêu chính xác điều cần người chủ quyết.
- **FR-061a**: Mục leo thang Mức 3 PHẢI cho người chủ **hành động ngay tại chỗ** đúng những lựa chọn mà nó nêu
  ra — tối thiểu: giao lại cho người khác, thu hẹp hoặc đổi yêu cầu, và huỷ đầu việc. Hỏi một câu rồi bắt người
  đọc tự đi tìm chỗ trả lời là đẩy phần khó nhất sang cho người mà cả cái thang này sinh ra để tiết kiệm thời
  gian; và đó cũng là chỗ FR-070 bị hụt trên thực tế nếu chỉ có API mà không có lối bấm.

  Kèm theo ba lựa chọn đó PHẢI có lựa chọn thứ tư: **"tôi đã xử lý xong"** — người chủ gỡ kẹt *bên ngoài hệ*
  (bật lại một agent treo, sửa một thứ hỏng ở máy họ) và chỉ cần hệ chạy tiếp như bình thường. Ba lựa chọn kia
  đều là *"hệ ơi làm hộ tôi việc này"*; lựa chọn thứ tư là *"tôi lo xong rồi, tiếp tục đi"*, và đó là một ý
  khác hẳn. Không có nó thì người chủ phải giả vờ chọn một trong ba, hoặc để lá thư mở vô hạn.

  Lựa chọn thứ tư KHÔNG ĐƯỢC tự gọi ai dậy. Nó chỉ làm đúng điều FR-061b và FR-061c đã quy định — xoá nấc
  thang, rồi tính lại — và nếu quả thật chưa có ai sắp chạm vào đầu việc thì vòng quét nhặt lại trong nhịp kế
  tiếp và bắt đầu **từ Mức 1**, tức là gọi đúng người phụ trách một lần. Cho nút tự gọi là dựng bản sao thứ
  hai của Mức 1, và hai bản sao có thể cùng bắn: một cú bấm dựng người phụ trách dậy hai lần cho một sự cố.
  Cái giá phải trả là một khoảng lặng bằng đúng một nhịp quét sau khi bấm, và đó là cái giá đúng.
- **FR-061b**: Việc hết đình trệ PHẢI xoá nấc thang, ngân sách và tất cả — **và KHÔNG ĐƯỢC đụng gì khác**.
  *Vì sao* nó hết đình trệ là chuyện không liên quan: một lần gọi lại ăn, Trưởng dự án ra tay, người chủ nhặt
  lên, bất cứ thứ gì. Cái thang chỉ đo đúng một điều, và điều đó đã xong.

  Đặc biệt, việc hết đình trệ KHÔNG ĐƯỢC đóng mục leo thang. Ràng buộc đó vòng tròn: một mục đang chờ **chính
  nó** là một trong các câu trả lời cho *có gì sắp chạm vào đầu việc này không*, nên đặt thư xong là việc hết
  đình trệ, hết đình trệ thì đóng thư, đóng thư xong lại đình trệ — trong khi ô đã lưu ghi ngược lại và không
  mang mốc hết hạn nào, nên không lượt quét nào ngó tới đầu việc đó nữa. Mục leo thang là của người chủ; chỉ
  người chủ đóng nó.
- **FR-061c**: KHI người chủ xử lý xong mục leo thang, HỆ THỐNG PHẢI **tính lại** xem đầu việc có còn ai sắp
  chạm vào không. Trong lúc mục còn chờ, đầu việc **không** bị coi là đình trệ (một con người có tên đang giữ
  nó) và vì thế nằm ngoài vòng quét — đúng. Ngay khi mục được xử lý, điều đó thôi đúng, mà **không có gì khác
  nhận ra**: ô đã lưu vẫn ghi *đang chờ người chủ* và vẫn không có mốc hết hạn, nên đầu việc không khớp mệnh
  đề nhặt việc nào và không lượt quét nào nhìn lại — đúng cái lỗ mà cả tính năng này sinh ra để bịt, tới bằng
  đường người chủ làm điều hợp lý nhất. Tính lại rồi thì hoặc hành động của họ đã cho đầu việc thứ gì đó thật,
  hoặc chưa và nó thành một lần đình trệ mới **từ Mức 1**.
- **FR-061e**: Câu trả lời của người chủ cho một mục leo thang PHẢI hạ cánh **trọn vẹn hoặc không gì cả**:
  hành động lên đầu việc và việc đóng mục nằm trong **cùng một lần chốt giao dịch**. Và lời gọi ấy PHẢI **lặp
  lại được vô hại** — mục đã xử lý rồi thì lần gọi sau không làm gì.

  Người chủ bấm một lần và ra **một** quyết định, nên nó phải thành **một** sự thật. Chẻ làm hai — làm rồi
  đóng — sinh một quãng có thật, dài bằng cả lượt gửi–nhận thứ hai: mạng chớp, máy chủ đang dựng lại, phiên
  hết hạn. Trong quãng đó đầu việc đã đổi mà câu hỏi vẫn còn, và người chủ thấy báo lỗi thì bấm lại — phản xạ
  đúng đắn nhất — khiến hành động chạy lần thứ hai. Giao lại lần hai gọi người phụ trách dậy thêm một lần cho
  cùng một sự cố, đúng thứ FR-060 sinh ra để tiết kiệm. Huỷ lần hai thì ném lỗi vì *đã huỷ* không đi tiếp đâu
  được, và mục kẹt lại vĩnh viễn ở lối đó.

  Chốt chặn đặt ở **chính mục hộp thư**, và đóng mục đi **trước** trong giao dịch: mục đã đóng nghĩa là quyết
  định đã ghi nhận, nên lần gọi sau dừng ngay chứ không hành động lại. Hỏng ở bất kỳ đâu thì giao dịch cuộn
  lại cả hai nửa và màn hình vẫn giữ nguyên câu hỏi — hướng hỏng duy nhất chấp nhận được, vì hướng còn lại là
  người chủ mất câu hỏi trong khi đầu việc vẫn kẹt.
- **FR-061d**: Mỗi lời gọi đóng mục hộp thư PHẢI nêu rõ **loại** mục mình đóng. Một lời gọi chỉ biết rằng câu
  hỏi *của riêng nó* đã được trả lời; một đầu việc có thể đồng thời giữ mục *chờ công nhận*, mục *hỏi phạm vi*
  và mục *leo thang*, và đóng cả ba vì một cái được giải quyết là nói với người chủ rằng có một quyết định mà
  không ai ra.
- **FR-062**: Mỗi lượt chạy còn hoạt động PHẢI phát tín hiệu báo sống định kỳ. KHI tín hiệu tắt quá ngưỡng
  nghi treo, HỆ THỐNG PHẢI mở một cửa sổ ân hạn và thử gọi nhẹ; nếu vẫn im thì tuyên treo, đóng lượt chạy đó,
  kéo đầu việc về *chờ làm*, và gọi lại đúng người phụ trách trỏ vào việc kế tiếp đã lưu.
- **FR-063**: KHI một lệnh đánh thức không tới được agent, HỆ THỐNG PHẢI thử lại theo nhịp giãn dần và gắn
  động cơ "đang chờ hành động phục hồi" cho đầu việc — không tính là đình trệ. Chỉ tuyên agent ngoại tuyến
  sau một chuỗi thất bại liên tiếp qua một cửa sổ đủ dài.
- **FR-064**: KHI một thợ bị tuyên ngoại tuyến, HỆ THỐNG PHẢI đưa đầu việc về *bị chặn* với lý do "người phụ
  trách ngoại tuyến" và báo Trưởng dự án. KHI Trưởng dự án bị tuyên ngoại tuyến, HỆ THỐNG PHẢI báo thẳng
  người chủ.
- **FR-065**: KHI một hoặc nhiều mục chờ người chủ vượt ngưỡng nhắc, HỆ THỐNG PHẢI nhắc theo ba bậc thưa dần
  vào hộp thư người chủ, giữ dự án đậu lại đúng chỗ chờ, và KHÔNG ĐƯỢC tự đánh dấu xong hay thất bại.
- **FR-066**: TRONG lúc chờ một quyết định của người chủ, Trưởng dự án PHẢI cho chạy tiếp mọi nhánh việc
  không phụ thuộc vào quyết định đó.
- **FR-067**: KHI nhiều đầu việc sẵn sàng cùng cần một thợ hoặc một tài nguyên độc chiếm, HỆ THỐNG PHẢI xếp
  hàng theo thứ tự: độ ưu tiên, rồi hạn chót, rồi tuổi đời — với cơ chế nâng dần việc cũ để không đầu việc
  nào bị bỏ đói.
- **FR-068**: SAU mọi lần khởi động lại, HỆ THỐNG PHẢI dựng lại động cơ đẩy cho từng đầu việc từ trạng thái
  bền đã chốt gần nhất; lượt chạy hỏng giữa chừng xử như treo.
- **FR-069**: KHI phát hiện thành phẩm đã mất hoặc hỏng lúc chuẩn bị công nhận, HỆ THỐNG PHẢI kéo đầu việc về
  đúng bước tạo ra thành phẩm đó, ghi vết mất mát, và giữ lại các phần đã chốt để chỉ làm lại phần thiếu.

#### J. Ranh giới vai trò và quyền hạn

- **FR-070**: Người chủ PHẢI có quyền can thiệp trực tiếp ở mức tương đương Trưởng dự án — bình luận, giao
  hoặc sửa một đầu việc, đổi ưu tiên, bố trí thợ. Đây là quyền, không phải nghĩa vụ.
- **FR-070a**: PHẢI có một lối **sửa đầu việc sau khi tạo** — tiêu đề, mô tả chi tiết, độ ưu tiên, hạn chót,
  tiêu chí công nhận. Cổng nào áp là do **ai gọi** quyết, không phải do trường nào bị chạm:
  - **người chủ** sửa thẳng, có hiệu lực ngay — đây chính là quyền FR-070 nói tới;
  - **Trưởng dự án** chạm vào một trong năm thứ lớn (phạm vi, mục tiêu/Bối cảnh, chi phí, thời hạn, tiêu chí
    công nhận) thì thay đổi **treo chờ người chủ duyệt**, không vào thẳng (FR-075); chạm thứ khác thì tự
    quyết;
  - **người phụ trách** chỉ được thêm ghi chú tiến trình, KHÔNG ĐƯỢC sửa yêu cầu gốc (FR-018).

  Không có lối này thì FR-070 chỉ đúng trên giấy: người chủ đặt sai một hạn chót lúc tạo là phải huỷ đầu việc
  rồi tạo lại, mất cả bình luận, thành phẩm và vết.
- **FR-071**: Thợ giao tiếp **qua đầu việc** — bình luận và phòng cộng tác của chính đầu việc nó phụ trách,
  cộng với thành phẩm nó nộp. HỆ THỐNG KHÔNG ĐƯỢC cho thợ đặt bất cứ thứ gì thẳng vào hộp thư người chủ.
  Trưởng dự án được đánh thức khi có trao đổi mới và đọc thay; người chủ đọc nếu muốn, không bắt buộc.
- **FR-072**: HỆ THỐNG PHẢI cấm thợ tự nhận việc ngoài đầu việc được giao và tự đổi phạm vi đầu việc.
- **FR-073**: HỆ THỐNG KHÔNG ĐƯỢC tự lập kế hoạch, tự chẻ việc, tự chọn thợ, tự duyệt hay tự công nhận đầu ra
  thay bất kỳ ai; cũng KHÔNG ĐƯỢC sửa nội dung của các bên khi chuyển tin.
- **FR-074**: Trưởng dự án PHẢI được tự quyết các thay đổi nội bộ (chẻ nhỏ hơn, đổi thứ tự, đổi người, đổi
  cách làm cùng một đích) mà không hỏi người chủ.
- **FR-075**: Thay đổi chạm tới **phạm vi**, **mục tiêu/Bối cảnh**, **chi phí**, **thời hạn**, hoặc **tiêu chí
  công nhận** PHẢI treo chờ người chủ duyệt lại trước khi có hiệu lực.
- **FR-076**: KHI Trưởng dự án tái hoạch định, HỆ THỐNG PHẢI bắt chuyển tiếp sạch: mọi đầu việc bị ảnh hưởng
  phải về một trạng thái có động cơ đẩy hợp lệ; cái nào bỏ thì vào *huỷ* kèm lý do — không đầu việc nào được
  mồ côi.

#### K. Hiển thị, ghi vết và ràng buộc nền

- **FR-077**: HỆ THỐNG PHẢI gom mọi thứ cần người chủ để mắt (kế hoạch chờ duyệt, câu hỏi chờ đáp, đầu ra chờ
  công nhận, cảnh báo leo thang, nhắc nhở) vào **hộp thư người chủ**.
- **FR-078**: HỆ THỐNG PHẢI cung cấp một kênh đối thoại hai chiều giữa người chủ và Trưởng dự án, và một
  **bảng dự án** trình toàn cảnh đầu việc, trạng thái, tiến độ.
- **FR-079**: HỆ THỐNG PHẢI ghi vết mọi tin nhắn, mọi lần chuyển trạng thái, mọi quyết định duyệt/công nhận,
  mọi lần giao việc và mọi lần đánh thức, theo dòng thời gian tra cứu được.
- **FR-080**: Trạng thái và sự kiện PHẢI được đẩy về giao diện; giao diện KHÔNG ĐƯỢC hỏi vòng để biết trạng
  thái *(Hiến pháp IV)*.
- **FR-080a**: Mọi thay đổi trạng thái mà giao diện đang hiển thị PHẢI có một tin đẩy tương ứng, và giao
  diện nhận tin rồi **đọc lại** dữ liệu chứ KHÔNG dựng trạng thái từ nội dung tin. Không được để một giá
  trị trên màn hình chỉ đúng lại sau khi tải lại trang. FR-080 mới cấm *hỏi vòng*; chỗ hụt thứ ba là
  **không hỏi mà cũng không được báo** — nhìn giống "đang yên" y hệt như hỏi vòng bị treo
  *(Hiến pháp IV, hợp đồng `contracts/push-events.md` nguyên tắc 1)*.
- **FR-081**: Mọi truy vấn dữ liệu của tính năng này PHẢI giới hạn trong workspace của người gọi; truy cập
  chéo workspace PHẢI trả về "không tìm thấy" *(Hiến pháp I)*.
- **FR-082**: Ngữ cảnh của agent (vai, đồng đội, đánh thức, lời nhắc vai) PHẢI lấy theo vai trong **dự án**
  đang làm, KHÔNG ĐƯỢC lấy theo thuộc tính ở tầng workspace *(Hiến pháp V)*.
- **FR-083**: Tầng nghiệp vụ KHÔNG ĐƯỢC nhánh mã theo từng loại agent; mọi khác biệt runtime nằm sau một hợp
  đồng chung *(Hiến pháp III)*.
- **FR-084**: Mọi chuỗi hiển thị PHẢI đi qua cơ chế đa ngôn ngữ, và tiếng Việt hiển thị PHẢI đủ dấu *(Hiến
  pháp VI)*.
- **FR-084a**: **Câu báo lỗi cũng là chuỗi hiển thị.** Mặt giao tiếp PHẢI trả **mã lỗi và tham số**; giao
  diện dựng câu qua cơ chế đa ngôn ngữ. HỆ THỐNG KHÔNG ĐƯỢC trả một câu đã dựng sẵn rồi hiện thẳng lên màn
  hình.

  Nói riêng ra vì đây là con đường duy nhất khiến hai thứ tiếng nằm cạnh nhau trên **cùng một màn** dù mọi
  chuỗi trong giao diện đều đã sạch: chuỗi lỗi không sinh ra ở giao diện nên mọi lần rà chuỗi cứng đều đi
  qua nó mà không thấy.

### Thực thể chính

- **Dự án** — vật chứa cấp cao: tên, mô tả, giai đoạn (một trong năm), Bối cảnh, bản kế hoạch và trạng thái
  duyệt của nó, danh sách ghế, lịch sử chuyển giai đoạn. Thuộc đúng một workspace.
- **Bối cảnh dự án** — khối mục tiêu chung: mục tiêu tối hậu, lý do, ràng buộc cứng, phạm vi, nguyên tắc
  chung. Có phiên bản và trạng thái duyệt; đính vào mọi gói tin đánh thức.
- **Bản kế hoạch** — các hạng mục lớn, thứ tự, phụ thuộc, rủi ro, mốc dự kiến, định nghĩa hoàn thành theo
  hạng mục; kèm trạng thái ở cổng duyệt (đang trình, được duyệt, bị yêu cầu chỉnh).
- **Ghế** — một vai cần có trong dự án, người thợ được cấp vào đó, và **người chủ đã cấp** — người này chịu
  trách nhiệm công nhận đầu ra của con agent ngồi ghế ấy. Ghế mang trạng thái trực tuyến; điều kiện rời giai
  đoạn thiết lập đọc từ tập ghế này.
- **Thiết lập tự động công nhận** — một công tắc theo cặp *(dự án, người chủ)*: bật thì mọi việc cần chữ ký
  của người chủ đó trong dự án ấy coi như đã chuẩn thuận sẵn. Mặc định tắt; chỉ chính người đó đổi được; mọi
  lần đổi đều ghi vết.
- **Đầu việc** — đơn vị công việc nhỏ nhất, mang bộ trường ở FR-015, thuộc đúng một dự án, có đúng một người
  phụ trách, một trạng thái trong tám, và một động cơ đẩy khi chưa đóng.
- **Tiêu chí công nhận** — một dòng trong định nghĩa hoàn thành: một khẳng định đúng/sai kiểm được, trỏ tới
  loại bằng chứng tương ứng. Đặt trước khi làm, bất biến trong lúc làm.
- **Thành phẩm** — vật thể xem được do thợ nộp: tài liệu, đường dẫn kết quả, bản mẫu, ảnh chụp, số đo, kết
  quả kiểm thử. Bắt buộc trước khi rời *đang làm*.
- **Động cơ đẩy** — thứ sẽ làm một đầu việc chưa đóng tiến tiếp; đúng một trong sáu loại, kèm dấu hiệu còn
  sống hay đã tắt.
- **Lệnh đánh thức** — một yêu cầu gọi dậy nhận diện theo bộ ba *(agent, đầu việc, lý do)*; tối đa một lệnh
  treo cho mỗi cặp agent–đầu việc.
- **Gói tin đánh thức** — phong bì ngữ cảnh trao cho agent lúc gọi dậy: lõi bốn phần cộng phần riêng theo
  loại lời gọi.
- **Lượt chạy** — một phiên làm việc của agent trên một đầu việc; phát tín hiệu báo sống định kỳ; tối đa một
  lượt tại một thời điểm cho mỗi cặp agent–đầu việc.
- **Mục hộp thư người chủ** — một thứ cần người chủ để mắt: chờ duyệt, chờ trả lời, chờ công nhận, cảnh báo
  leo thang; mang bậc nhắc đã gửi.
- **Vết hoạt động** — bản ghi bất biến theo dòng thời gian: ai làm gì, lúc nào, vì sao.

---

## Tiêu chí thành công *(bắt buộc)*

### Kết quả đo được

- **SC-001**: Chạy trọn một dự án từ mở tới đóng, số thao tác **bắt buộc** của người chủ chỉ gồm: nêu mục
  tiêu, cấp thợ vào ghế, duyệt kế hoạch, công nhận đầu ra của các agent do mình cấp (bằng không nếu đã bật
  tự động công nhận), trả lời khi được hỏi, quyết chuyển giai đoạn. Không có khâu điều phối nào bắt buộc rơi
  vào tay người chủ.
- **SC-002**: Tại mọi thời điểm quét, 100% đầu việc chưa đóng hoặc gắn đúng một động cơ đẩy còn sống, hoặc
  mang cờ đình trệ. Không tồn tại đầu việc đứng im mà không có cờ.
- **SC-003**: 0 đầu việc đạt trạng thái *xong* mà không có thành phẩm đính kèm.
- **SC-004**: 0 đầu việc có nhiều hơn một người phụ trách tại bất kỳ thời điểm nào.
- **SC-005**: 100% gói tin đánh thức có đủ **lõi bốn phần**, và đủ phần riêng của loại lời gọi đó; mọi phần
  có mặt mà rỗng đều ghi rõ "không có" thay vì để trống.
- **SC-006**: Trong một đợt chạy thử có bắn cớ gọi chồng nhau, 0 trường hợp một cặp agent–đầu việc có quá một
  lượt chạy đồng thời hoặc quá một lệnh đánh thức treo.
- **SC-007**: Một lượt chạy tắt tiếng được phát hiện, tuyên treo và đưa về guồng trong vòng 15 phút, và phần
  việc đã làm trước đó không bị mất.
- **SC-008**: Trong một dự án chạy trơn tru không có điểm treo, số lần Trưởng dự án bị đánh thức theo nhịp
  điều phối bằng 0.
- **SC-009**: Khi một đầu việc được công nhận, mọi đầu việc chỉ còn chờ nó được chuyển sang chờ làm và giao
  đi mà người chủ không phải chạm vào.
- **SC-010**: Người chủ nhận không quá 3 lời nhắc cho cùng một mục chờ trong 72 giờ đầu.
- **SC-011**: Người chủ mở lại lịch sử một dự án đã đóng và dựng lại được đầy đủ ai làm gì, lúc nào, vì sao —
  không hành động quan trọng nào thiếu vết.
- **SC-012**: 100% trường hợp thử truy cập tài nguyên của workspace khác trả về "không tìm thấy".
- **SC-013**: 0 chuỗi hiển thị nằm ngoài cơ chế đa ngôn ngữ; 0 chuỗi tiếng Việt thiếu dấu trên giao diện.
- **SC-014** *(hoãn — chờ tính năng mời người vào vùng làm việc)*: Trong một dự án có nhiều người chủ cùng
  cấp agent, 100% mục chờ công nhận rơi đúng vào hộp thư của người đã cấp agent thực hiện đầu việc đó; 0
  trường hợp lẫn sang người chủ khác. Không đo được trong phạm vi một người chủ; giữ nguyên câu chữ để ngày
  mở nhiều người chủ có sẵn thước đo. Thay bằng **SC-014b** cho phạm vi hiện tại.
- **SC-014b**: 100% mục chờ công nhận được định tuyến bằng quan hệ **ai đã cấp agent vào ghế** đọc từ dữ
  liệu, 0 trường hợp suy thẳng từ "ai là chủ vùng làm việc"; và 100% ghế được cấp đều có ghi người cấp.

---

## Giả định

**Về phạm vi**

- Bản đặc tả này mô tả **cơ chế vận hành**, không bàn tới chất lượng sản phẩm mà đội agent làm ra.
- Đây là mô tả **trạng thái đích**. Mã nguồn hiện có sẽ được khảo sát ở bước thiết kế (`/speckit-plan`) để
  biết phần nào đã đúng, phần nào lệch, phần nào chưa có — bản đặc tả này không giả định gì về hiện trạng.
- Tính năng bám trên nền hạ tầng đã có của sản phẩm: vùng làm việc, danh tính agent, kho hiện vật dùng chung,
  và lớp trung gian đứng ra chuyển lệnh đánh thức tới agent.
- **Quyền cho *người* thì chưa có** *(sửa 2026-08-03 — câu trên trước đây ghi nhầm là đã có)*. Mỗi vùng làm
  việc có đúng một người sở hữu; không có cơ chế mời người thứ hai vào. Vì vậy đặc tả này nằm trong phạm vi
  **một người chủ cho mỗi dự án**; phần nhiều người chủ là tính năng sau. Xem mục Làm rõ phiên 2026-08-03.

**Bốn điểm tài liệu gốc để ngỏ — đã lấy chính đề xuất trong tài liệu làm mặc định, chờ người chủ chốt lại**

- ~~**Ranh giới "thay đổi lớn"** (FR-075)~~ — **đã chốt 2026-07-30**: đúng năm thứ (phạm vi, mục tiêu/Bối
  cảnh, chi phí, thời hạn, tiêu chí công nhận). Xem mục Làm rõ.
- ~~**Mặc định cờ *cần Chủ đồng-approve*** (FR-033)~~ — **đã chốt 2026-07-30, khác đề xuất ban đầu**: bỏ hẳn
  cơ chế cờ theo từng việc; mọi đầu việc cần hai chữ ký, và gánh nặng điều tiết bằng công tắc tự động công
  nhận theo từng người chủ. Xem mục Làm rõ và FR-033 đến FR-039.
- ~~**Ai kích chuyển giai đoạn giữa vận hành và bảo trì** (FR-004)~~ — **đã chốt 2026-07-30**: Trưởng dự án
  đề xuất, người chủ quyết; chuyển sang đóng luôn là của người chủ. Xem mục Làm rõ.
- ~~**Các ngưỡng thời gian**~~ — **đã chốt 2026-07-30** (nhịp dự án: mỗi đầu việc vài giờ tới vài ngày): giữ
  nguyên bộ mặc định gợi ý trong tài liệu gốc — nhịp báo sống 60 giây; vòng quét canh
  gác 60 giây; ngưỡng nghi treo 10 phút; ân hạn 2 phút; hết hạn một lần gọi 20 giây; nhịp thử lại 30 giây →
  1 phút → 2 phút → 4 phút → 8 phút; tuyên ngoại tuyến sau 5 lần thất bại liên tiếp trong khoảng 15 phút;
  trần tự phục hồi Mức 1 là 3 lần; trần vòng từ chối công nhận là 3 lần; nhắc người chủ ở 8 giờ → 24 giờ →
  72 giờ rồi thưa dần. Riêng **nhịp điều phối** tài liệu gốc không cho số — lấy mặc định: rà mỗi 15 phút,
  trần 4 lần đánh thức theo nhịp trong một giờ, giãn tối đa lên 2 giờ khi dự án chạy trơn tru. Mọi ngưỡng
  PHẢI chỉnh được, không đóng cứng — **kể cả bốn cái dễ bị bỏ quên** vì chúng là trần chứ không phải nhịp:
  trần độ giãn (8 lần), trần khoảng cách giữa hai lượt rà (2 giờ), sàn khoảng cách (60 giây), và trần số lần
  hỏi Trưởng dự án ở Mức 2 (3 lần). Trần Mức 1 vốn đã chỉnh được; bốn cái này phải ngang hàng với nó.
  - **"Giãn tối đa lên 2 giờ" chịu cả hai trần cùng lúc** — làm rõ 2026-08-06, vì mỗi trần một mình đều sai
    ở một đầu của dải cấu hình. Độ giãn KHÔNG ĐƯỢC vượt **8 lần** nhịp đã đặt, **và** KHÔNG ĐƯỢC vượt **2
    giờ**. Chỉ có bội số thì dự án đặt nhịp 1 giờ sẽ giãn thành 8 giờ; chỉ có con số tuyệt đối thì dự án đặt
    nhịp 1 phút — tức người vận hành đang nói "theo sát việc này" — bị kéo ra 120 lần. Ngoại lệ duy nhất:
    dự án tự đặt nhịp **rộng hơn 2 giờ** thì giữ nguyên nhịp của nó; trần này chặn *độ giãn*, không được
    phép rà dày hơn mức người vận hành yêu cầu.
- **Ngưỡng của điểm treo *sắp trễ*** — chốt 2026-07-31, tài liệu gốc không có: bốn mốc cảnh báo trước hạn
  chót là **24 giờ, 12 giờ, 6 giờ, 1 giờ**, mỗi mốc báo đúng một lần. Hạn chót là trường không bắt buộc, nên
  đầu việc không đặt hạn chót thì **không bao giờ** tính là sắp trễ.
  - Ngưỡng *im lâu* (5 phút) đã bỏ cùng với loại điểm treo đó — xem phiên làm rõ 2026-08-16. Hai loại điểm
    treo còn lại đọc thẳng trạng thái và sổ chữ ký nên không cần ngưỡng thời gian nào.

**Mặc định hợp lý khác**

- Một dự án có **đúng một** Trưởng dự án tại một thời điểm.
- Một thợ có thể giữ nhiều đầu việc nhưng chỉ chạy **một lượt** tại một thời điểm.
- "Trực tuyến" của một agent do nền tảng tự xác định, không dựa vào agent tự khai.
- Lịch sử của dự án đã đóng giữ vĩnh viễn ở dạng chỉ đọc, không tự dọn.

---

## Đóng đợt (2026-08-13, T162)

Đặc tả chuyển từ *Nháp* sang *Đã triển khai*. Mọi yêu cầu trong tài liệu này đã có mã chạy và có bài kiểm
canh. Cổng cuối đóng sạch: máy chủ 702 bài kiểm xanh, rà mã giao diện thoát 0, kiểm kiểu sạch — đo ở T173,
và không một dòng mã nào đổi kể từ lần đo đó tới lúc đóng.

**Điểm lệch còn tồn**: không có. Hai phần sau là **quyết định phạm vi** đã ghi trong thân đặc tả, không
phải nợ:

- Phần nhiều người chủ cho một dự án hoãn sang tính năng sau (mục Làm rõ phiên 2026-08-03).
- Cơ chế mời người vào vùng làm việc là tính năng sau, không nằm trong đặc tả này.

**Đọc lại 2026-08-18**: câu "không có điểm lệch còn tồn" ở trên chỉ đúng với những gì lượt đóng ấy nhìn
thấy. Sau nó còn hai mươi lăm việc nữa — xem mục dưới.

---

## Đóng lại (2026-08-18, T203)

Lượt đóng 13/08 là **sớm**. Giai đoạn 10 mở sau nó và chạy tới T203, tất cả hai mươi lăm việc đều là chỗ
mã làm khác điều đặc tả đã ghi, không việc nào là tính năng mới.

**Mười ba việc đầu (T179–T191)** ra từ lượt rà lại toàn bộ 89 yêu cầu ngày 16/08. **Mười hai việc còn
lại đến sau lượt rà đó**, từ ba nguồn mà một lượt rà đặc tả-với-mã không thể thấy trước:

- **Lộ ra khi làm một việc khác trong cùng đợt.** Vá một chỗ là thấy chỗ kế bên hở cùng kiểu: T195 và
  T196 là hệ quả của T187, T197 là hệ quả của T196, một trong ba việc T198–T200 tìm ra khi làm T194.
- **Chỉ hiện khi dựng dịch vụ thật lên chạy.** T192, T193 và T201 — không lượt đọc mã nào thấy được,
  phải gọi thật qua mặt giao tiếp mới lộ ra.
- **Người rà bản vá nêu.** Hai việc trong T198–T200 (PR #206), rồi T202 và một nửa T201 (PR #209).
- **Luật thêm vào sau.** Hiến pháp lên 1.1.0 ngày 16/08 — **sau** lượt rà cùng ngày — sinh ra T194 rồi
  T203. Lúc rà, điều luật ấy chưa tồn tại, nên không lượt rà nào có thể kể nó vào.

**Bài học ghi lại để khỏi lặp**: đầu ra của một lượt rà là **một mẫu**, không phải toàn bộ mặt phẳng. Nó
so hai tài liệu nên chỉ thấy chỗ hai bên nói khác nhau; nó mù chỗ đặc tả chưa nói gì, chỗ chỉ hiện khi
dịch vụ chạy thật, và luật ra đời sau nó.

**Cổng đóng lần này**: 860 bài kiểm máy chủ xanh · rà mã máy chủ sạch · kiểm kiểu đúng mốc 150 · rà mã
giao diện thoát 0 · bảng việc 203/203, không dòng nào mở.

**Khác lần trước ở chỗ nào**: mỗi lớp lỗi đóng lại lần này đều kèm một bài kiểm **quét toàn bộ mã nguồn**,
không phải một bài kiểm cho một chỗ vừa vá — `test_error_is_a_code_not_a_sentence.py` cho lời từ chối mang
mã, `test_the_agents_packet_is_english.py` cho chữ máy chủ đọc lại vào gói tin gửi agent,
`test_stall_verdict_is_a_code.py` cho câu tuyên đình trệ. Ba lớp ấy không sinh thêm vi phạm âm thầm được
nữa. Lớp nào chưa có bài quét thì vẫn hở, và đó là chỗ việc mới sẽ còn ra.

**Điểm lệch còn tồn**: không có *trong những chỗ lượt này nhìn tới* — xem mục dưới.

## Mở lại (2026-08-19, T204)

Câu cuối mục trên viết: *"Lớp nào chưa có bài quét thì vẫn hở, và đó là chỗ việc mới sẽ còn ra."* Một
ngày sau thì đúng như vậy, và chỗ hở lần này không phải mã — là **tờ hướng dẫn**.

`backend/static/skills/armarius-http/SKILL.md` là thứ duy nhất một agent chạy bằng curl đọc để biết
gọi cửa nào. Nó vẫn dạy `POST /agent/tasks/{id}/claim`, cửa đã gỡ ở T061 theo FR-072, và vẫn để câu ấy
làm luật số một. Nó kể 6 cửa trên 25 cửa có thật, không cửa nào thuộc phần Trưởng dự án — nên một
Trưởng dự án chạy bằng kỹ năng này không ký nổi, mà `done` thì đòi đủ hai chữ ký.

**Vì sao không lượt nào bắt được**, và đây mới là chỗ đáng ghi: tệp ấy chưa bao giờ nằm trong đường
quét của ai. T003 rà "mọi nơi gọi `claim`" ở `mcp/src/`, `frontend/src/` và
`backend/armarius/presentation/`; tệp kỹ năng ở `backend/static/`, ngoài cả ba. Lượt hội tụ so đặc tả
với **mã**, mà tệp này là tài liệu. Lượt quét tiếng Anh T203 soi hai ô của gói tin đánh thức, không
soi tệp kỹ năng. Ba lượt rà, ba đường quét, và tệp ấy lọt qua cả ba vì mỗi đường đều được vẽ quanh
*mã nguồn*.

**Bài học nối vào bài học lần trước**: một lớp chỉ đóng được khi có phép quét **đi từ nguồn sự thật
ra**, không phải đi từ danh sách chỗ đang nhìn vào. `test_the_http_skill_names_real_routes.py` đọc
bảng route thật của app rồi soi hai chiều, nên nó bắt cả cửa bị gỡ lẫn cửa thêm mới mà không ai dạy.

**Còn hở, đã biết, chưa làm**: `backend/static/skills/armarius-mcp/SKILL.md` mắc đúng bệnh — nó dạy
`enroll`, `enrollment_code` và `claim_task`, ba thứ đã gỡ ở #97 và T061. Bộ công cụ MCP thì đúng; chỉ
tờ hướng dẫn sai. Để riêng vì bộ kiểm của `mcp/` chạy tách khỏi máy chủ, nên phép quét tương ứng phải
dựng ở đó.
