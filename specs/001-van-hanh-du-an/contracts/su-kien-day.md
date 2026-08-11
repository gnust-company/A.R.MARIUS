# Dòng sự kiện đẩy

Một chiều, máy chủ đẩy về trình duyệt. Hiến pháp IV cấm giao diện hỏi vòng để biết trạng thái.

Hai kênh đã chạy: theo **lượt chạy** và theo **đầu việc**. Cần thêm hai kênh phạm vi rộng hơn.

| Kênh | Trạng thái | Ai nghe |
|---|---|---|
| Theo lượt chạy | **[có]** | Màn hình theo dõi một lượt agent chạy |
| Theo đầu việc | **[có]** | Phòng cộng tác của một đầu việc |
| **Theo dự án** | **[mới]** | Bảng dự án — đổi giai đoạn, đổi trạng thái đầu việc, cờ đình trệ |
| **Theo người chủ** | **[mới]** | Hộp thư — mục mới, mục được giải quyết, lời nhắc |

## Sự kiện cần thêm

### Kênh dự án

| Sự kiện | Khi nào | Mang theo |
|---|---|---|
| `du-an.doi-giai-doan` | Dự án đổi giai đoạn | Giai đoạn trước, sau, ai quyết |
| `ke-hoach.trinh` | Trưởng dự án trình kế hoạch | Phiên bản kế hoạch |
| `ke-hoach.quyet` | Người chủ quyết ở cổng duyệt | Duyệt, yêu cầu chỉnh, hay hỏi lại |
| `dau-viec.doi-trang-thai` | Mọi lần đổi trạng thái | Mã đầu việc, trước, sau, lý do |
| `dau-viec.dinh-tre` | Nổi hoặc gỡ cờ đình trệ | Mã đầu việc, lý do mất động cơ |
| `dau-viec.mo-khoa` | Một đầu việc xong, mở khoá việc phụ thuộc | Danh sách mã vừa mở khoá |
| `cong-nhan.ky` | Một chữ ký được ghi | Loại người ký, kết quả, có phải ký tự động không |
| `nhip-dieu-phoi.quet` | Xong **mỗi** lượt rà của nhịp điều phối, kể cả lượt không thấy gì | Mốc rà, số điểm treo, có gọi Trưởng dự án không |

Lượt rà không thấy gì **vẫn phải bắn**. Khối "lượt rà gần nhất" trên bảng dự án sinh ra để phân biệt *dự án
đang yên* với *vòng điều phối đã chết*, mà hai thứ đó nhìn giống hệt nhau nếu chỉ có lượt rà thấy-việc mới
lên tiếng. Thiếu sự kiện này thì bảng chỉ còn một cách giữ khối đó đúng: hỏi lại theo đồng hồ — đúng thứ
Hiến pháp IV cấm, và đúng thứ nó đã làm trước Đợt 9.

### Kênh người chủ

| Sự kiện | Khi nào | Mang theo |
|---|---|---|
| `hop-thu.muc-moi` | Một mục chờ xuất hiện | Loại, dự án, đầu việc liên quan |
| `hop-thu.da-giai-quyet` | Mục được xử lý | Định danh mục |
| `hop-thu.nhac` | Một bậc nhắc được gửi | Định danh mục, bậc thứ mấy |
| `leo-thang.muc-3` | Một việc leo lên người chủ | Hồ sơ đã thử, điều cần quyết |

## Nguyên tắc

1. **Sự kiện là tín hiệu, không phải nguồn sự thật.** Trình duyệt nhận sự kiện rồi đọc lại phần dữ liệu cần;
   không dựng trạng thái chỉ từ dòng sự kiện.
2. **Mất kết nối phải bù được.** Mỗi sự kiện mang số thứ tự để nối lại sau khi đứt, theo đúng cách kênh đầu
   việc đang làm.
3. **Giới hạn theo workspace.** Người nghe chỉ nhận sự kiện của workspace mình; không rò rỉ sự tồn tại của
   dự án thuộc workspace khác.
4. **Không đẩy nội dung nhạy cảm.** Sự kiện mang định danh và nhãn, không mang toàn văn thành phẩm.
