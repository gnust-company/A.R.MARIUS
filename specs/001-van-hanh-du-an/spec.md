# Đặc tả tính năng: Vận hành dự án tự chủ

**Nhánh tính năng**: `spec/001-van-hanh-du-an`

**Ngày tạo**: 2026-07-30

**Trạng thái**: Nháp

**Đầu vào**: Yêu cầu của người chủ: "tôi muốn align toàn bộ prj với feature dự án theo như trong
`THIET-KE-VAN-HANH-DU-AN.md`"

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

---

### Câu chuyện 3 — Công nhận đầu ra hai tầng qua hộp thư người chủ (Ưu tiên: P2)

Thợ nộp thành phẩm và tự khai "xong phần tôi". Trưởng dự án đặt thành phẩm cạnh bộ tiêu chí công nhận rồi
chấm từng dòng. Với đầu việc thường, Trưởng dự án gật là đóng. Với đầu việc có bật cờ **cần Chủ đồng-approve**
— các mốc lớn, các bàn giao — kết quả được đẩy vào hộp thư người chủ và chỉ đóng khi chủ gật.

**Vì sao ưu tiên này**: Đây là chốt "công nhận đầu ra" trong tiêu chí tối thượng, và là cơ chế duy nhất chống
"xong giả". Nó xếp sau câu chuyện 2 vì cần bộ trường và vòng đời đầu việc đã đứng.

**Kiểm thử độc lập**: Cho một đầu việc không bật cờ chạy tới nơi → Trưởng dự án gật là đóng, chủ không bị làm
phiền. Bật cờ trên một đầu việc khác → sau khi Trưởng dự án tán thành, đầu việc vẫn chưa đóng, một mục xuất
hiện trong hộp thư người chủ; chủ gật thì mới đóng. Từ chối ba lần liên tiếp → Trưởng dự án bị kéo vào soát
lại đề bài.

**Kịch bản chấp nhận**:

1. **Cho** một đầu việc *chờ rà soát* không bật cờ, **khi** Trưởng dự án chấm đạt hết tiêu chí, **thì** đầu
   việc chuyển *xong* ngay, không có mục nào rơi vào hộp thư người chủ.
2. **Cho** một đầu việc *chờ rà soát* có bật cờ, **khi** Trưởng dự án tán thành, **thì** đầu việc **chưa**
   đóng, một mục "đầu ra chờ công nhận" xuất hiện trong hộp thư người chủ kèm thành phẩm và bộ tiêu chí.
3. **Cho** mục chờ công nhận đó, **khi** người chủ approve, **thì** đầu việc chuyển *xong* và các việc phụ
   thuộc được mở khoá.
4. **Cho** một lần từ chối approve kèm phản hồi, **khi** quyết định được ghi nhận, **thì** đầu việc quay về
   *đang làm* (không phải *nháp*, không phải *huỷ*), lý do được ghi vết, việc kế tiếp đặt thành "sửa theo
   phản hồi", và **đúng người thợ cũ** được đánh thức lại.
5. **Cho** một đầu việc đã bị từ chối ba lần, **khi** lần từ chối thứ ba được ghi nhận, **thì** hệ thống kéo
   Trưởng dự án vào soát lại đề bài và bộ tiêu chí công nhận, thay vì để vòng sửa–nộp lặp vô tận.
6. **Cho** một dự án mà mọi đầu việc của đợt đã *xong*, **khi** hệ thống xử lý, **thì** **không** có cổng
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

**Kiểm thử độc lập**: Gọi dậy một thợ vì một đầu việc mới giao → kiểm gói tin có đủ tám phần, phần nào không
có nội dung thì ghi "không có" chứ không để trống. Bắn ba cớ gọi cùng lúc cho một cặp agent–đầu việc → agent
chỉ thấy đúng một lần gọi, với lý do gộp liệt kê đủ ba cớ.

**Kịch bản chấp nhận**:

1. **Cho** bất kỳ lần đánh thức nào, **khi** gói tin được dựng, **thì** nó chứa đủ tám phần và mọi phần rỗng
   đều ghi rõ "không có".
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
nào im lâu, sắp trễ, đang chờ quyết định của nó, hay đang mắc kẹt. Có thì gọi dậy kèm danh sách đích danh
những điểm cần nhìn. Không có thì bỏ qua nhịp đó trong im lặng.

**Vì sao ưu tiên này**: Không có nhịp này thì mọi đầu việc chỉ tiến khi có ai đó gõ cửa — dự án đứng im mà
không ai biết. Nhưng nó xếp sau câu chuyện 4 vì phải có gói tin đánh thức chuẩn trước. Đây cũng là vai bị
đánh rơi trong bản thiết kế cũ.

**Kiểm thử độc lập**: Để một dự án chạy trơn tru không có điểm treo → đếm số lần Trưởng dự án bị gọi dậy theo
nhịp phải bằng không. Làm một đầu việc im quá ngưỡng → nhịp kế tiếp gọi dậy Trưởng dự án với lý do nêu đích
danh đầu việc đó.

**Kịch bản chấp nhận**:

1. **Cho** một dự án không có đầu việc nào im lâu, sắp trễ, mắc kẹt hay chờ quyết định, **khi** một nhịp
   điều phối đến hạn, **thì** hệ thống **không** đánh thức Trưởng dự án và nhịp đó trôi qua trong im lặng.
2. **Cho** một dự án có ba điểm treo, **khi** nhịp đến hạn, **thì** Trưởng dự án được gọi dậy đúng một lần
   với lý do liệt kê đủ ba điểm ("đầu việc X im hai ngày, đầu việc Y sắp trễ, đầu việc Z đang chờ bạn quyết").
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
- **FR-005**: KHI dự án chuyển sang *đóng*, HỆ THỐNG PHẢI dừng mọi nhịp đánh thức của dự án đó, thông báo
  toàn đội, và giữ toàn bộ lịch sử ở dạng chỉ đọc để người chủ xem lại bất cứ lúc nào.
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
  các đầu ra có cờ.

#### D. Đầu việc — bộ trường

- **FR-015**: Mỗi đầu việc PHẢI mang các trường: mã định danh, tiêu đề, mô tả chi tiết, trạng thái, lý do
  trạng thái, độ ưu tiên, người phụ trách, việc phụ thuộc, đầu việc cha, định nghĩa hoàn thành, cờ *cần Chủ
  đồng-approve*, thành phẩm, việc kế tiếp, hạn chót, người tạo, mốc tạo, mốc bắt đầu làm, mốc hoàn tất, dự án
  chứa, nhật ký thay đổi.
- **FR-016**: HỆ THỐNG PHẢI sinh mã định danh dạng *tiền tố tên dự án + số thứ tự* khi tạo đầu việc, và mã đó
  PHẢI bất biến suốt đời đầu việc.
- **FR-017**: Mỗi đầu việc PHẢI có **đúng một** người phụ trách tại mọi thời điểm. Muốn nhiều người cùng làm
  thì chẻ thành nhiều đầu việc con; muốn đổi người thì chuyển giao.
- **FR-018**: Trường *mô tả chi tiết* PHẢI nói rõ đầu việc làm gì và làm thế nào; đây là trường bắt buộc.
  Thợ được bổ sung ghi chú tiến trình nhưng KHÔNG ĐƯỢC sửa yêu cầu gốc.
- **FR-019**: *Định nghĩa hoàn thành* PHẢI là một danh sách tiêu chí đúng/sai kiểm được, do Trưởng dự án đặt
  **trước khi** thợ bắt tay, và PHẢI tách bạch khỏi trường *thành phẩm*. HỆ THỐNG KHÔNG ĐƯỢC gộp hai trường
  này.
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
- **FR-027** *(cổng duyệt)*: Một đầu việc do Trưởng dự án đề xuất và được đánh dấu cần người chủ đồng ý CHỈ
  được rời *nháp* sau khi người chủ duyệt.
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

- **FR-033**: Mỗi đầu việc PHẢI mang một cờ *cần Chủ đồng-approve* do Trưởng dự án đặt khi chẻ việc.
- **FR-034**: Với đầu việc **không** bật cờ, Trưởng dự án công nhận là đủ để đóng.
- **FR-035**: Với đầu việc **có** bật cờ, sau khi Trưởng dự án tán thành, HỆ THỐNG PHẢI đẩy đầu ra vào hộp thư
  người chủ và giữ đầu việc chưa đóng cho tới khi người chủ công nhận. Cờ này áp cho cả các mốc lớn giữa
  chừng, không riêng đầu ra cuối.
- **FR-036**: KHI một đầu ra bị từ chối công nhận, HỆ THỐNG PHẢI kéo đầu việc về *đang làm* (không phải *nháp*,
  không phải *huỷ*), ghi vết lý do, đặt việc kế tiếp thành "sửa theo phản hồi", và đánh thức lại đúng thợ đã
  làm.
- **FR-037**: SAU ba vòng từ chối trên cùng một đầu việc, HỆ THỐNG PHẢI kéo Trưởng dự án vào soát lại đề bài
  và định nghĩa hoàn thành.
- **FR-038**: HỆ THỐNG KHÔNG ĐƯỢC có cổng nghiệm thu ở cấp dự án. Việc công nhận diễn ra ở cấp đầu việc;
  chuyển giai đoạn diễn ra ở cấp dự án.
- **FR-039**: KHI cả một đợt việc đã *xong*, HỆ THỐNG PHẢI đánh thức Trưởng dự án soạn bản tổng kết đợt, rồi
  đẩy vào hộp thư người chủ kèm ba lựa chọn: đóng dự án, chuyển bảo trì, hoặc mở đợt việc mới.

#### G. Gói tin đánh thức và điều phối lời gọi

- **FR-040**: Mỗi gói tin đánh thức PHẢI gồm đủ tám phần: vai của agent trong dự án; Bối cảnh dự án; đầu việc
  đang nói tới cùng mô tả và trạng thái; lý do gọi dậy; danh bạ đồng đội kèm trạng thái trực tuyến; tin nhắn
  mới kể từ lượt trước; việc kế tiếp đang chờ; nơi nộp thành phẩm và cách báo trạng thái.
- **FR-041**: Phần nào của gói tin không có nội dung PHẢI ghi rõ "không có"; KHÔNG ĐƯỢC để trống âm thầm.
- **FR-042**: Phần *lý do gọi dậy* PHẢI là một câu người đọc hiểu nói thẳng vì sao agent bị gọi lúc này.
- **FR-043**: HỆ THỐNG PHẢI đánh thức Trưởng dự án khi và chỉ khi có một trong các cớ: người chủ nhắn hoặc
  hỏi; người chủ duyệt hoặc yêu cầu chỉnh kế hoạch; người chủ công nhận hoặc từ chối một đầu ra có cờ; người
  chủ quyết chuyển giai đoạn hoặc mở đợt mới; một thợ báo kẹt; một đầu việc chuyển sang *chờ rà soát*; một
  đầu việc chuyển sang *xong*; một đầu việc thất bại hoặc quá hạn; hoặc một nhịp điều phối có điểm treo thật.
- **FR-044**: HỆ THỐNG PHẢI đánh thức một thợ khi và chỉ khi có một trong các cớ: được giao đầu việc mới; bị
  nhắc tên trong trao đổi; có bình luận mới trên đầu việc mình phụ trách; cần làm tiếp một lượt còn dở; vướng
  của mình đã được gỡ; hoặc bị nhắc vì im lâu.
- **FR-045**: HỆ THỐNG KHÔNG ĐƯỢC đánh thức một agent chỉ vì dự án có biến động chung — chỉ gọi khi có việc
  thuộc phần của chính nó đang chờ.
- **FR-046**: Với mỗi cặp *(agent, đầu việc)*, HỆ THỐNG PHẢI giữ tối đa **một** lệnh đánh thức đang treo và
  tối đa **một** lượt chạy tại một thời điểm. Cớ mới đến khi đã có lệnh treo thì nhập vào lệnh đó và mang
  theo lý do mạnh hơn; cớ đến khi đang có lượt chạy thì lượt chạy hấp thụ, và hệ thống đánh giá lại nhu cầu
  gọi khi lượt kết thúc.
- **FR-047**: Trước khi kết thúc một lượt, agent PHẢI để lại *việc kế tiếp* — hoặc chỉ rõ bóng đã chuyền cho
  ai, hoặc mô tả cụ thể phần còn dở. HỆ THỐNG PHẢI lưu bền phần này.

#### H. Nhịp điều phối của Trưởng dự án

- **FR-048**: HỆ THỐNG PHẢI chạy một nhịp điều phối định kỳ *có kiểm soát* cho Trưởng dự án: trước mỗi nhịp
  tự soi bảng việc tìm các điểm treo (im lâu, sắp trễ, chờ quyết định của Trưởng dự án, mắc kẹt).
- **FR-049**: NẾU không có điểm treo nào, HỆ THỐNG KHÔNG ĐƯỢC đánh thức Trưởng dự án; nhịp đó trôi qua trong
  im lặng.
- **FR-050**: NẾU có điểm treo, gói tin PHẢI nêu đích danh từng điểm cần nhìn, không nói chung chung "đến giờ
  rồi".
- **FR-051**: HỆ THỐNG PHẢI đặt trần số lần đánh thức theo nhịp trong một khoảng thời gian, tự giãn nhịp khi
  dự án chạy trơn tru và làm dày nhịp khi có dấu hiệu ứ đọng.

#### I. Lưới an toàn và thang phục hồi

- **FR-052**: Mỗi đầu việc chưa đóng PHẢI gắn đúng một **động cơ đẩy** trong sáu loại: đang có lượt chạy; đã
  hẹn một lần đánh thức; đang chờ một mốc bên ngoài; đang chờ người chủ; đang bị chặn bởi việc khác; đang chờ
  một hành động phục hồi.
- **FR-053**: HỆ THỐNG PHẢI chạy một vòng quét canh gác định kỳ rà mọi đầu việc chưa đóng, kiểm xem động cơ
  đẩy có tồn tại và còn sống hay không.
- **FR-054**: KHI một đầu việc không còn động cơ đẩy sống, HỆ THỐNG PHẢI nổi cờ *đình trệ* kèm lý do, và
  KHÔNG ĐƯỢC chuyển đầu việc đó sang *xong* trong bất kỳ hoàn cảnh nào.
- **FR-055**: HỆ THỐNG PHẢI áp thang phục hồi ba mức theo đúng thứ tự, KHÔNG ĐƯỢC nhảy cóc: Mức 1 — hệ thống
  tự gọi lại, giữ nguyên người phụ trách, không quyết gì mới; Mức 2 — Trưởng dự án quyết một hành động phục
  hồi tường minh; Mức 3 — đẩy lên người chủ, chỉ với những quyết định duy nhất người chủ mới quyết được.
- **FR-056**: Mức 1 PHẢI có trần số lần tự gọi lại cho mỗi nguyên nhân trên mỗi đầu việc, khoảng cách giãn
  dần; bộ đếm PHẢI đặt lại về không khi đầu việc có tiến triển thật.
- **FR-057**: Mỗi lần leo lên Mức 3, HỆ THỐNG PHẢI kèm hồ sơ đã thử (Mức 1 làm gì mấy lần, Mức 2 quyết gì) và
  nêu chính xác điều cần người chủ quyết.
- **FR-058**: Mỗi lượt chạy còn hoạt động PHẢI phát tín hiệu báo sống định kỳ. KHI tín hiệu tắt quá ngưỡng
  nghi treo, HỆ THỐNG PHẢI mở một cửa sổ ân hạn và thử gọi nhẹ; nếu vẫn im thì tuyên treo, đóng lượt chạy đó,
  kéo đầu việc về *chờ làm*, và gọi lại đúng người phụ trách trỏ vào việc kế tiếp đã lưu.
- **FR-059**: KHI một lệnh đánh thức không tới được agent, HỆ THỐNG PHẢI thử lại theo nhịp giãn dần và gắn
  động cơ "đang chờ hành động phục hồi" cho đầu việc — không tính là đình trệ. Chỉ tuyên agent ngoại tuyến
  sau một chuỗi thất bại liên tiếp qua một cửa sổ đủ dài.
- **FR-060**: KHI một thợ bị tuyên ngoại tuyến, HỆ THỐNG PHẢI đưa đầu việc về *bị chặn* với lý do "người phụ
  trách ngoại tuyến" và báo Trưởng dự án. KHI Trưởng dự án bị tuyên ngoại tuyến, HỆ THỐNG PHẢI báo thẳng
  người chủ.
- **FR-061**: KHI một hoặc nhiều mục chờ người chủ vượt ngưỡng nhắc, HỆ THỐNG PHẢI nhắc theo ba bậc thưa dần
  vào hộp thư người chủ, giữ dự án đậu lại đúng chỗ chờ, và KHÔNG ĐƯỢC tự đánh dấu xong hay thất bại.
- **FR-062**: TRONG lúc chờ một quyết định của người chủ, Trưởng dự án PHẢI cho chạy tiếp mọi nhánh việc
  không phụ thuộc vào quyết định đó.
- **FR-063**: KHI nhiều đầu việc sẵn sàng cùng cần một thợ hoặc một tài nguyên độc chiếm, HỆ THỐNG PHẢI xếp
  hàng theo thứ tự: độ ưu tiên, rồi hạn chót, rồi tuổi đời — với cơ chế nâng dần việc cũ để không đầu việc
  nào bị bỏ đói.
- **FR-064**: SAU mọi lần khởi động lại, HỆ THỐNG PHẢI dựng lại động cơ đẩy cho từng đầu việc từ trạng thái
  bền đã chốt gần nhất; lượt chạy hỏng giữa chừng xử như treo.
- **FR-065**: KHI phát hiện thành phẩm đã mất hoặc hỏng lúc chuẩn bị công nhận, HỆ THỐNG PHẢI kéo đầu việc về
  đúng bước tạo ra thành phẩm đó, ghi vết mất mát, và giữ lại các phần đã chốt để chỉ làm lại phần thiếu.

#### J. Ranh giới vai trò và quyền hạn

- **FR-066**: Người chủ PHẢI có quyền can thiệp trực tiếp ở mức tương đương Trưởng dự án — bình luận, giao
  hoặc sửa một đầu việc, đổi ưu tiên, bố trí thợ. Đây là quyền, không phải nghĩa vụ.
- **FR-067**: HỆ THỐNG PHẢI cấm thợ báo cáo vượt cấp thẳng lên người chủ hoặc tự xin người chủ duyệt.
- **FR-068**: HỆ THỐNG PHẢI cấm thợ tự nhận việc ngoài đầu việc được giao và tự đổi phạm vi đầu việc.
- **FR-069**: HỆ THỐNG KHÔNG ĐƯỢC tự lập kế hoạch, tự chẻ việc, tự chọn thợ, tự duyệt hay tự công nhận đầu ra
  thay bất kỳ ai; cũng KHÔNG ĐƯỢC sửa nội dung của các bên khi chuyển tin.
- **FR-070**: Trưởng dự án PHẢI được tự quyết các thay đổi nội bộ (chẻ nhỏ hơn, đổi thứ tự, đổi người, đổi
  cách làm cùng một đích) mà không hỏi người chủ.
- **FR-071**: Thay đổi chạm tới **phạm vi**, **mục tiêu/Bối cảnh**, **chi phí**, **thời hạn**, hoặc **tiêu chí
  công nhận** PHẢI treo chờ người chủ duyệt lại trước khi có hiệu lực.
- **FR-072**: KHI Trưởng dự án tái hoạch định, HỆ THỐNG PHẢI bắt chuyển tiếp sạch: mọi đầu việc bị ảnh hưởng
  phải về một trạng thái có động cơ đẩy hợp lệ; cái nào bỏ thì vào *huỷ* kèm lý do — không đầu việc nào được
  mồ côi.

#### K. Hiển thị, ghi vết và ràng buộc nền

- **FR-073**: HỆ THỐNG PHẢI gom mọi thứ cần người chủ để mắt (kế hoạch chờ duyệt, câu hỏi chờ đáp, đầu ra chờ
  công nhận, cảnh báo leo thang, nhắc nhở) vào **hộp thư người chủ**.
- **FR-074**: HỆ THỐNG PHẢI cung cấp một kênh đối thoại hai chiều giữa người chủ và Trưởng dự án, và một
  **bảng dự án** trình toàn cảnh đầu việc, trạng thái, tiến độ.
- **FR-075**: HỆ THỐNG PHẢI ghi vết mọi tin nhắn, mọi lần chuyển trạng thái, mọi quyết định duyệt/công nhận,
  mọi lần giao việc và mọi lần đánh thức, theo dòng thời gian tra cứu được.
- **FR-076**: Trạng thái và sự kiện PHẢI được đẩy về giao diện; giao diện KHÔNG ĐƯỢC hỏi vòng để biết trạng
  thái *(Hiến pháp IV)*.
- **FR-077**: Mọi truy vấn dữ liệu của tính năng này PHẢI giới hạn trong workspace của người gọi; truy cập
  chéo workspace PHẢI trả về "không tìm thấy" *(Hiến pháp I)*.
- **FR-078**: Ngữ cảnh của agent (vai, đồng đội, đánh thức, lời nhắc vai) PHẢI lấy theo vai trong **dự án**
  đang làm, KHÔNG ĐƯỢC lấy theo thuộc tính ở tầng workspace *(Hiến pháp V)*.
- **FR-079**: Tầng nghiệp vụ KHÔNG ĐƯỢC nhánh mã theo từng loại agent; mọi khác biệt runtime nằm sau một hợp
  đồng chung *(Hiến pháp III)*.
- **FR-080**: Mọi chuỗi hiển thị PHẢI đi qua cơ chế đa ngôn ngữ, và tiếng Việt hiển thị PHẢI đủ dấu *(Hiến
  pháp VI)*.

### Thực thể chính

- **Dự án** — vật chứa cấp cao: tên, mô tả, giai đoạn (một trong năm), Bối cảnh, bản kế hoạch và trạng thái
  duyệt của nó, danh sách ghế, lịch sử chuyển giai đoạn. Thuộc đúng một workspace.
- **Bối cảnh dự án** — khối mục tiêu chung: mục tiêu tối hậu, lý do, ràng buộc cứng, phạm vi, nguyên tắc
  chung. Có phiên bản và trạng thái duyệt; đính vào mọi gói tin đánh thức.
- **Bản kế hoạch** — các hạng mục lớn, thứ tự, phụ thuộc, rủi ro, mốc dự kiến, định nghĩa hoàn thành theo
  hạng mục; kèm trạng thái ở cổng duyệt (đang trình, được duyệt, bị yêu cầu chỉnh).
- **Ghế** — một vai cần có trong dự án và người thợ được cấp vào đó; mang trạng thái trực tuyến. Điều kiện
  rời giai đoạn thiết lập đọc từ tập ghế này.
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
- **Gói tin đánh thức** — phong bì ngữ cảnh tám phần trao cho agent lúc gọi dậy.
- **Lượt chạy** — một phiên làm việc của agent trên một đầu việc; phát tín hiệu báo sống định kỳ; tối đa một
  lượt tại một thời điểm cho mỗi cặp agent–đầu việc.
- **Mục hộp thư người chủ** — một thứ cần người chủ để mắt: chờ duyệt, chờ trả lời, chờ công nhận, cảnh báo
  leo thang; mang bậc nhắc đã gửi.
- **Vết hoạt động** — bản ghi bất biến theo dòng thời gian: ai làm gì, lúc nào, vì sao.

---

## Tiêu chí thành công *(bắt buộc)*

### Kết quả đo được

- **SC-001**: Chạy trọn một dự án từ mở tới đóng, số thao tác **bắt buộc** của người chủ chỉ gồm: nêu mục
  tiêu, cấp thợ vào ghế, duyệt kế hoạch, công nhận các đầu ra có cờ, trả lời khi được hỏi, quyết chuyển giai
  đoạn. Không có khâu điều phối nào bắt buộc rơi vào tay người chủ.
- **SC-002**: Tại mọi thời điểm quét, 100% đầu việc chưa đóng hoặc gắn đúng một động cơ đẩy còn sống, hoặc
  mang cờ đình trệ. Không tồn tại đầu việc đứng im mà không có cờ.
- **SC-003**: 0 đầu việc đạt trạng thái *xong* mà không có thành phẩm đính kèm.
- **SC-004**: 0 đầu việc có nhiều hơn một người phụ trách tại bất kỳ thời điểm nào.
- **SC-005**: 100% gói tin đánh thức có đủ tám phần; mọi phần rỗng đều ghi rõ "không có" thay vì để trống.
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

---

## Giả định

**Về phạm vi**

- Bản đặc tả này mô tả **cơ chế vận hành**, không bàn tới chất lượng sản phẩm mà đội agent làm ra.
- Đây là mô tả **trạng thái đích**. Mã nguồn hiện có sẽ được khảo sát ở bước thiết kế (`/speckit-plan`) để
  biết phần nào đã đúng, phần nào lệch, phần nào chưa có — bản đặc tả này không giả định gì về hiện trạng.
- Tính năng bám trên nền hạ tầng đã có của sản phẩm: workspace, quyền, danh tính agent, kho hiện vật dùng
  chung, và lớp trung gian đứng ra chuyển lệnh đánh thức tới agent.

**Bốn điểm tài liệu gốc để ngỏ — đã lấy chính đề xuất trong tài liệu làm mặc định, chờ người chủ chốt lại**

- **Ranh giới "thay đổi lớn"** (FR-071): lấy đúng năm thứ — phạm vi, mục tiêu/Bối cảnh, chi phí, thời hạn,
  tiêu chí công nhận. Mọi thay đổi khác Trưởng dự án tự quyết.
- **Mặc định cờ *cần Chủ đồng-approve*** (FR-033): mặc định **tắt**; Trưởng dự án bật cho các mốc lớn (bàn
  giao một hạng mục, kết quả cuối) và cho những đầu việc người chủ đánh dấu.
- **Ai kích chuyển giai đoạn giữa vận hành và bảo trì** (FR-004): Trưởng dự án **đề xuất**, người chủ
  **quyết**. Chuyển sang đóng luôn là quyết định của người chủ.
- **Các ngưỡng thời gian**: lấy bộ mặc định gợi ý trong tài liệu gốc — nhịp báo sống 60 giây; vòng quét canh
  gác 60 giây; ngưỡng nghi treo 10 phút; ân hạn 2 phút; hết hạn một lần gọi 20 giây; nhịp thử lại 30 giây →
  1 phút → 2 phút → 4 phút → 8 phút; tuyên ngoại tuyến sau 5 lần thất bại liên tiếp trong khoảng 15 phút;
  trần tự phục hồi Mức 1 là 3 lần; trần vòng từ chối công nhận là 3 lần; nhắc người chủ ở 8 giờ → 24 giờ →
  72 giờ rồi thưa dần. Riêng **nhịp điều phối** tài liệu gốc không cho số — lấy mặc định: rà mỗi 15 phút,
  trần 4 lần đánh thức theo nhịp trong một giờ, giãn tối đa lên 2 giờ khi dự án chạy trơn tru. Mọi ngưỡng
  PHẢI chỉnh được, không đóng cứng.

**Mặc định hợp lý khác**

- Một dự án có **đúng một** Trưởng dự án tại một thời điểm.
- Một thợ có thể giữ nhiều đầu việc nhưng chỉ chạy **một lượt** tại một thời điểm.
- "Trực tuyến" của một agent do nền tảng tự xác định, không dựa vào agent tự khai.
- Lịch sử của dự án đã đóng giữ vĩnh viễn ở dạng chỉ đọc, không tự dọn.
