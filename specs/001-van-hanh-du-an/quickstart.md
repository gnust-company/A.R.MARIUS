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
# Phần máy chủ
cd backend && uv run ruff check && uv run mypy armarius && uv run pytest -q
uv run pytest tests/test_migration_schema_parity.py    # lược đồ khớp bản di trú

# Gói riêng của lớp trung gian — BẮT BUỘC khi đổi lược đồ đầu việc hoặc mặt giao tiếp
cd mcp && uv run pytest

# Giao diện
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```

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

Cần **hai người chủ**, mỗi người cấp một thợ vào dự án.

1. Thợ của người chủ A nộp bài; Trưởng dự án tán thành.
   → Đầu việc **chưa** đóng. Mục chờ công nhận rơi vào hộp thư của **A**. Hộp thư của **B** không có gì.
2. A công nhận → đầu việc *xong*, việc phụ thuộc mở khoá.
3. Lặp lại với thợ của B nhưng cho **B từ chối** kèm phản hồi.
   → Đầu việc về *đang làm*, việc kế tiếp là "sửa theo phản hồi", **đúng thợ cũ** được gọi lại.
4. Từ chối thêm hai lần nữa (tổng ba).
   → Trưởng dự án bị kéo vào soát lại đề bài và bộ tiêu chí.
5. A bật công tắc tự động công nhận cho phần của mình.
   → Đầu ra kế tiếp của thợ do A cấp đóng ngay sau khi Trưởng dự án gật; **không** mục nào vào hộp thư;
   nhưng nhật ký đầu việc vẫn ghi A được coi là đã ký, lúc nào.
6. Thử cho **B** tắt công tắc của **A** → từ chối. Thử cho Trưởng dự án đụng vào → từ chối.
7. Với công tắc của A **đang bật**, cho Trưởng dự án đề xuất chuyển sang *bảo trì*.
   → Vẫn phải có mục chờ trong hộp thư A; công tắc **không** tự quyết chuyển giai đoạn.

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

## Kiểm chứng bằng giao diện thật

Sau khi phần máy chủ xanh, **dựng lại vùng chứa giao diện** và lái trình duyệt bằng Playwright qua các mặt:
bảng dự án (giai đoạn, cờ đình trệ, thẻ việc), hộp thư (mục chờ theo loại, bậc nhắc), phòng cộng tác (vết
theo đầu việc), khung chat với Trưởng dự án (trình kế hoạch, ba nút quyết). Không lỗi ở bảng điều khiển
trình duyệt.
