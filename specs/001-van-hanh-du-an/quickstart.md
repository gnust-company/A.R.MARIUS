# Kiểm chứng: Vận hành dự án tự chủ

**Giai đoạn 1** của [plan.md](./plan.md) · Đặc tả: [spec.md](./spec.md)

Đây là hướng dẫn **chạy thật để tự kiểm chứng**, không phải tài liệu cài đặt. Luật của dự án: xong việc thì
phải dựng dịch vụ thật lên và tự chứng minh — "biên dịch sạch" không tính là xong.

## Chuẩn bị

Giao diện ở cổng 3000, máy chủ ở cổng 8080, cơ sở dữ liệu Postgres — dựng bằng docker compose. Sửa phần máy
chủ thì **dựng lại vùng chứa máy chủ**; sửa giao diện thì **dựng lại vùng chứa giao diện** (không có nạp
nóng qua vùng chứa).

Cần có sẵn: một workspace, ít nhất **hai** người chủ (để kiểm việc định tuyến chữ ký), và đủ agent để cấp
vào mọi ghế.

## Lệnh kiểm tự động

```bash
# Phần máy chủ — chạy từng lệnh, KHÔNG nối bằng && (xem lưu ý về mốc nền bên dưới)
cd backend
uv run ruff check                                      # phải sạch
uv run mypy armarius                                   # thoát 1 — đối chiếu số lỗi với mốc nền
uv run pytest -q
uv run pytest tests/test_migration_schema_parity.py    # lược đồ khớp bản di trú

# Gói riêng của lớp trung gian — BẮT BUỘC khi đổi lược đồ đầu việc hoặc mặt giao tiếp
cd mcp && uv run pytest

# Giao diện — cũng chạy từng lệnh
cd frontend
npm run lint                                           # từ T173 là cổng đỏ/xanh: phải thoát 0
npx tsc -b --force                                     # KHÔNG dùng `tsc --noEmit`, xem lưu ý bên dưới
npm run build
```

**Lưu ý về lệnh kiểm kiểu giao diện**: `npx tsc --noEmit` ở đây **không kiểm gì cả** và luôn thoát 0.
`tsconfig.json` khai `"files": []` rồi chỉ trỏ sang `tsconfig.app.json` với `tsconfig.node.json`, mà chế độ
`--noEmit` không đi theo các nhánh trỏ đó. Phải dùng chế độ dựng theo nhánh trỏ — `tsc -b` — thì mới thật
sự kiểm; `--force` để không bỏ qua nhờ bộ nhớ đệm của lần dựng trước. Lệnh `npm run build` bên dưới cũng
chạy `tsc -b`, nên nó mới là chỗ kiểm kiểu thật sự đang diễn ra.

**Lưu ý về mốc nền**: `mypy armarius` **luôn thoát mã 1** vì dự án mang sẵn một lượng lỗi có từ trước, ghi ở
bảng T002 trong [khao-sat-du-lieu.md](./khao-sat-du-lieu.md). Nó **không phải cổng đỏ/xanh** mà là cổng
*không được tăng*: so số đo với mốc nền, tăng thì mới là hỏng. (`npm run lint` từng cùng loại với nó, mốc
nền 50; **từ T173 nó về 0 và thành cổng đỏ/xanh thật**.) Vì vậy đừng nối các lệnh bằng `&&` — nối thì
`mypy` cắt ngang, và bộ kiểm máy chủ, kiểm kiểu giao diện, dựng bản phát hành sẽ **không bao giờ chạy tới**
trong khi người chạy tưởng đã kiểm đủ.

**Rà mã sạch không có nghĩa là bộ biên dịch React chạy.** Ba điều luật `react-hooks` chỉ bắt được trường
hợp lớp ghi nhớ *viết tay* không giữ được; những cú pháp bộ biên dịch chưa hạ được thì chúng im lặng đi qua,
và thành phần đó lặng lẽ không được tối ưu. Muốn biết thật thì chạy bộ biên dịch lên toàn bộ `frontend/src`
và đếm sự kiện biên dịch hỏng — mốc sau T173 ghi ở bảng T002 trong
[khao-sat-du-lieu.md](./khao-sat-du-lieu.md): **357 hàm được tối ưu, 2 lần bỏ cuộc, cả hai trong một thành
phần dựng sẵn không màn nào dùng**.

**Lưu ý về kiểm thử hiện có**: siết bảng chuyển trạng thái sẽ làm đỏ vài bài kiểm đang dựa vào đường
*đang làm → xong*. Đó là **đỏ đúng** — sửa bài kiểm theo luật mới, không nới luật cho bài kiểm xanh.

---

## Kịch bản 1 — Giai đoạn và cổng duyệt kế hoạch *(Câu chuyện 1)*

1. Tạo một dự án, khai ba vai, **để trống một ghế**.
   → Dự án phải nằm ở *thiết lập*. Không agent nào bị gọi dậy. Thử tạo một đầu việc → bị từ chối.
2. Cấp đủ thợ vào mọi ghế nhưng cho một thợ ngoại tuyến.
   → Vẫn ở *thiết lập*.
3. Cho mọi thợ trực tuyến.
   → Dự án tự sang *lập kế hoạch*; Trưởng dự án được gọi dậy **đúng một lần**, lý do nói rõ "dự án vừa đủ
   đội, cần bạn làm rõ Bối cảnh rồi lập kế hoạch".
4. Thử tạo một đầu việc thật lúc này → từ chối kèm lý do "kế hoạch chưa được duyệt".
5. Để Trưởng dự án trình Bối cảnh và kế hoạch. Thử cho chính nó duyệt → từ chối.
6. Người chủ chọn *yêu cầu chỉnh* kèm góp ý.
   → Trưởng dự án được gọi lại kèm góp ý; dự án vẫn ở *lập kế hoạch*.
7. Người chủ *duyệt*.
   → Dự án sang *vận hành*; mốc duyệt có trong vết; Trưởng dự án được gọi dậy với việc kế tiếp "chẻ đầu việc
   và giao thợ".

## Kịch bản 2 — Năm cổng chặn *(Câu chuyện 2)*

Với một dự án đang *vận hành*:

| Thử | Kỳ vọng |
|---|---|
| Tạo đầu việc rồi giao khi mô tả chi tiết còn trống | Từ chối, giữ ở *nháp* |
| Gán người thứ hai vào một đầu việc đã có người | Từ chối, gợi ý chuyển giao hoặc chẻ việc |
| Đưa vào *chờ làm* khi còn hai việc phụ thuộc chưa xong | Từ chối, **liệt kê mã** hai việc đó |
| Chuyển sang *chờ rà soát* khi chưa nộp thành phẩm | Từ chối |
| Chuyển thẳng *đang làm → xong* | **Từ chối** — đây là chỗ khác luật cũ |
| Vào *bị chặn* mà không điền lý do | Từ chối |
| Tạo cạnh phụ thuộc khép vòng | Từ chối ngay lúc tạo, nêu vòng đi qua đâu |
| Tạo đầu việc **trong khuôn** hạng mục đã duyệt | Cho qua, giao ngay |
| Tạo đầu việc **ngoài khuôn** | Ở lại *nháp*, mục chờ duyệt vào hộp thư người chủ |

Rồi cho một đầu việc chạy trọn đường đúng → kiểm mốc hoàn tất được ghi, việc phụ thuộc được mở khoá, và
Trưởng dự án được gọi dậy để giao tiếp.

## Kịch bản 3 — Hai chữ ký và công tắc tự động *(Câu chuyện 3)*

Một dự án, **một người chủ** (phạm vi hiện tại — xem Làm rõ phiên 2026-08-03), một thợ do người đó cấp ghế.

0. Trước khi thợ bắt tay, đặt cho đầu việc một bộ tiêu chí công nhận hai dòng. Thợ nộp bài, rồi cho Trưởng dự
   án **ký ngay khi chưa chấm dòng nào** (FR-019a).
   → Bị từ chối, và lời từ chối **gọi tên** hai tiêu chí còn thiếu. Đọc lại danh sách chữ ký: phải **rỗng** —
   từ chối trước khi ghi, không phải ghi rồi rút.
   → Chấm *đạt* mà không chỉ ra thành phẩm → từ chối. Chỉ sang thành phẩm của đầu việc khác → *không tìm thấy*.
   → Cho **thợ** tự chấm việc mình làm → *không tìm thấy*; chấm là việc của ghế Trưởng dự án.
1. Chấm đạt hết tiêu chí, rồi Trưởng dự án tán thành.
   → Số `đạt/tổng` trên thẻ ở bảng dự án và trên thanh trong phòng cộng tác tự đổi sau mỗi lần chấm, **không
   tải lại trang** (FR-080a).
   → Đầu việc **chưa** đóng. Mục chờ công nhận rơi vào hộp thư người chủ.
   → Kiểm ngay tại đây: mục đó được định tuyến bằng quan hệ **ai đã cấp thợ vào ghế** đọc từ dữ liệu — ghế
   phải có ghi người cấp, và người cấp đó là người nhận mục. Không được suy thẳng từ "ai là chủ vùng".
2. Người chủ công nhận → đầu việc *xong*, việc phụ thuộc mở khoá, vết ghi đủ hai chữ ký.
3. Với một đầu việc khác, cho người chủ **từ chối** kèm phản hồi.
   → Đầu việc về *đang làm*, việc kế tiếp là "sửa theo phản hồi", **đúng thợ cũ** được gọi lại.
4. Từ chối thêm hai lần nữa (tổng ba).
   → Trưởng dự án bị kéo vào soát lại đề bài và bộ tiêu chí.
5. Người chủ bật công tắc tự động công nhận cho phần của mình.
   → Đầu ra kế tiếp đóng ngay sau khi Trưởng dự án gật; **không** mục nào vào hộp thư; nhưng nhật ký đầu việc
   vẫn ghi người chủ được coi là đã ký, lúc nào.
6. Thử cho Trưởng dự án bật hoặc tắt công tắc đó → từ chối.
7. Với công tắc **đang bật**, cho Trưởng dự án đề xuất chuyển sang *bảo trì*.
   → Vẫn phải có mục chờ trong hộp thư người chủ; công tắc **không** tự quyết chuyển giai đoạn.

**Hoãn tới tính năng mời người vào vùng làm việc**: bước kiểm "hộp thư của người chủ kia không có gì" và bước
"một người chủ cố tắt công tắc của người khác". Cả hai cần người chủ thứ hai, hiện chưa dựng được.

## Kịch bản 4 — Gói tin đánh thức và gộp lời gọi *(Câu chuyện 4)*

1. Giao một đầu việc cho một thợ, đọc gói tin nó nhận.
   → Đủ **tám phần**. **Bối cảnh dự án có mặt** (đây là phần đang thiếu). Phần nào rỗng ghi rõ "không có".
   Nơi nộp thành phẩm là một mục riêng, không lẫn trong đoạn hướng dẫn.
2. Bắn ba cớ gọi gần như cùng lúc cho **cùng** một cặp thợ–đầu việc (một bình luận mới, một lần nhắc tên,
   một lần nhắc vì im lâu).
   → Thợ chỉ thấy **một** lần gọi, lý do gộp liệt kê đủ ba cớ. Chỉ **một** lượt chạy.
3. Trong lúc một lượt đang chạy, bắn thêm một cớ.
   → Lượt đang chạy hấp thụ; khi lượt kết thúc, hệ thống đánh giá lại xem còn cần gọi không rồi mới bắn.
4. **Khởi động lại vùng chứa máy chủ giữa lúc có lệnh treo**, rồi bắn lại cớ đó.
   → Vẫn chỉ một lệnh treo. Đây là chỗ cơ chế cũ (bộ nhớ tiến trình) hỏng.
5. Thợ nộp bài, bóng chuyền sang Trưởng dự án rà.
   → Thợ **không** bị gọi dậy vì việc rà soát đó.

## Kịch bản 5 — Nhịp điều phối *(Câu chuyện 5)*

1. Để một dự án chạy trơn tru, không đầu việc nào im lâu, sắp trễ, mắc kẹt hay chờ quyết định.
   → Đếm số lần Trưởng dự án bị gọi dậy theo nhịp: phải bằng **không**. Nhịp trôi qua trong im lặng.
2. Làm cho ba đầu việc rơi vào ba tình cảnh khác nhau (một im quá ngưỡng, một sắp trễ, một chờ quyết định).
   → Nhịp kế tiếp gọi Trưởng dự án **đúng một lần**, lý do nêu **đích danh cả ba**.
3. Để dự án chạy trơn tru một thời gian dài → khoảng cách giữa các lần rà tự giãn. Tạo ứ đọng → nhịp dày lại.
4. Đếm số lần gọi theo nhịp trong một giờ → không vượt trần đã đặt.

## Kịch bản 6 — Lưới an toàn *(Câu chuyện 6)*

1. **Treo**: cho một lượt chạy tắt tiếng quá ngưỡng nghi treo.
   → Qua cửa sổ ân hạn vẫn im → tuyên treo, đóng lượt chạy ma, đầu việc về *chờ làm*, **đúng người phụ trách
   cũ** được gọi lại trỏ vào việc kế tiếp. Phần đã làm không mất.
2. **Mất động cơ**: ép một đầu việc vào tình trạng không còn động cơ đẩy nào sống.
   → Cờ đình trệ nổi kèm lý do. Đầu việc **không bao giờ** tự nhảy sang *xong*.
3. **Cạn ngân sách**: để một đầu việc bị tự gọi lại đủ ba lần mà không tiến.
   → Dừng tự thử, leo Mức 2: Trưởng dự án được gọi kèm hồ sơ đã thử.
4. **Đặt lại bộ đếm**: cho đầu việc có tiến triển thật (nộp thêm, đổi trạng thái tiến lên).
   → Bộ đếm về không.
5. **Ngoại tuyến**: ngắt một thợ.
   → Thử lại theo nhịp giãn dần; suốt thời gian đó đầu việc gắn động cơ *chờ hành động phục hồi* và **không**
   bị tính đình trệ. Sau chuỗi thất bại → tuyên ngoại tuyến, đầu việc về *bị chặn* với lý do "người phụ trách
   ngoại tuyến", Trưởng dự án được báo.
6. **Trưởng dự án ngoại tuyến** → người chủ được báo thẳng.
7. **Người chủ im lặng**: để một mục chờ vượt ngưỡng nhắc.
   → Nhắc ba bậc thưa dần vào hộp thư. Dự án đậu đúng chỗ chờ, không tự đánh dấu xong hay thất bại. Trưởng
   dự án vẫn cho chạy tiếp các nhánh không phụ thuộc vào quyết định đang chờ.
8. **Khởi động lại**: dựng lại vùng chứa máy chủ.
   → Mọi đầu việc chưa đóng có lại động cơ đẩy đúng, dựng từ trạng thái bền cuối cùng.

## Kiểm chứng ràng buộc Hiến pháp

| Nguyên tắc | Cách kiểm |
|---|---|
| Đa tenant | Đọc một đầu việc của workspace khác bằng thẻ định danh của workspace này → *không tìm thấy*, không phải *không có quyền* |
| Cổng Done | Không đầu việc nào đạt *xong* mà không có thành phẩm — rà toàn bộ dữ liệu sau khi chạy các kịch bản |
| Trung lập adapter | Tra tầng nghiệp vụ, không có nhánh mã theo loại agent |
| Đẩy không hỏi vòng | Mở bảng dự án, xem lưu lượng mạng: không có vòng lặp hỏi lại; trạng thái đổi thì giao diện tự cập nhật |
| Góc nhìn dự án | Cùng một agent giữ hai vai ở hai dự án → gói tin đánh thức mỗi bên nêu đúng vai của dự án đó |
| Tiếng Việt | Rà giao diện: không chuỗi cứng ngoài cơ chế đa ngôn ngữ, không chuỗi thiếu dấu |

**Ba lưu ý khi chạy bảng này** — đều là chỗ đã làm sai một lần ở T160, và cái sai đọc lên y hệt cái đúng:

1. **Đa tenant**: đừng liệt kê lối đi bằng tay. Lấy tài liệu mô tả giao diện của dịch vụ **đang chạy** làm
   danh sách rồi gọi từng lối bằng thẻ của tenant kia. Kiểm bằng tay chỉ tìm ra lối mình nghĩ ra được; T160
   liệt kê tay ra bốn lối và bỏ sót ba.
2. **Đẩy không hỏi vòng**: lọc lưu lượng theo **đường dẫn**, không theo cổng. Trình duyệt gọi máy chủ qua
   chính cổng đã phục vụ giao diện, nên lọc theo cổng máy chủ sẽ đếm ra **0 lượt** — trông hệt một kết quả
   đạt, trong khi thật ra không đo gì. Và đo đủ hai vế: không hỏi vòng là một vế, **đổi dữ liệu từ ngoài
   trình duyệt rồi xem trang có tự đổi không** là vế kia.
3. **Tiếng Việt**: đổi ngôn ngữ sang tiếng Việt **trước khi** quét. Ứng dụng mặc định tiếng Anh, quét thẳng
   là đi tìm lỗi thiếu dấu ở nơi không có tiếng Việt.

## Kiểm chứng bằng giao diện thật

Sau khi phần máy chủ xanh, **dựng lại vùng chứa giao diện** và lái trình duyệt bằng Playwright qua các mặt:
bảng dự án (giai đoạn, cờ đình trệ, thẻ việc), hộp thư (mục chờ theo loại, bậc nhắc), phòng cộng tác (vết
theo đầu việc), khung chat với Trưởng dự án (trình kế hoạch, ba nút quyết). Không lỗi ở bảng điều khiển
trình duyệt.
