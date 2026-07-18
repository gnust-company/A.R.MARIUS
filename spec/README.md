# Armarius — Đặc tả (Spec)

> Đây là **nguồn sự thật có thẩm quyền** của dự án Armarius. Khi tài liệu ở đây và mã nguồn
> mâu thuẫn nhau, **tài liệu này đúng** — mã nguồn phải được sửa cho khớp (hoặc tài liệu phải
> được cập nhật trước, theo quy trình bên dưới). Toàn bộ đặc tả viết bằng **tiếng Việt**.

---

## 1. Vì sao có thư mục này

Trước đây dự án có hai tầng tài liệu, không tầng nào có thẩm quyền:

- Ý định gốc (tiếng Việt): `MY_DEMAND.md`, `PROJECT_DESCRIPTION.md` — brainstorm, không phải đặc tả thi hành.
- Thiết kế phái sinh (tiếng Anh): `docs/HLD.md`, `docs/LLD.md`, `docs/API_CONTRACT.md`, `docs/FE_UX.md`,
  `docs/ARCHITECTURE.md` — **đóng băng từ cuối tháng 6 / đầu tháng 7**, trong khi mã nguồn chạy
  tiếp qua hàng loạt thay đổi lớn (mời agent kiểu mới, chat với Leader, liveness kiểu mới...).

Hậu quả: mã nguồn trôi khỏi tài liệu, không có cơ chế nào phát hiện. Cứ sửa một lỗi lại lộ ra
mã nguồn làm khác thiết kế. Thư mục `spec/` sinh ra để **chấm dứt tình trạng đó** bằng cách áp dụng
**Spec Driven Development (phát triển dẫn dắt bởi đặc tả)**.

## 2. Spec Driven Development là gì (áp dụng ở đây)

Nguyên tắc: **đặc tả đi trước, mã nguồn theo sau và phải chứng minh mình khớp đặc tả.**

Vòng làm việc cho mọi thay đổi hành vi:

```
Muốn đổi gì đó
   └─► 1. Sửa ĐẶC TẢ trong spec/ trước (mô tả hành vi mới + tiêu chí nghiệm thu)
       └─► 2. Lập kế hoạch (những chỗ mã nguồn cần đụng)
           └─► 3. Chia việc nhỏ
               └─► 4. Viết mã
                   └─► 5. Kiểm chứng mã KHỚP đặc tả (test + chạy thật)
```

Không một thay đổi hành vi nào được gộp (merge) nếu nó không đi kèm sửa mục đặc tả tương ứng.
Đây là điều biến `spec/` từ "tài liệu để đọc" thành "tài liệu thi hành".

## 3. Trạng thái hiện tại: bản nền "đúng như đang chạy"

Bản đặc tả đầu tiên này là **bản nền phản ánh mã nguồn ngày 18/07/2026** (không phải mơ ước tương lai).
Với mỗi vùng, đặc tả ghi rõ một trong hai nhãn:

- **[ĐÚNG-NHƯ-CODE]** — đặc tả chép đúng hành vi mã nguồn đang chạy. Không cần sửa code.
- **[ĐÍCH-CẦN-SỬA]** — mã nguồn hiện làm sai; đặc tả ghi hành vi **đúng**, và mã nguồn sẽ được
  sửa cho khớp ở giai đoạn sau (ghi rõ "Giai đoạn 2").

Nhờ vậy ta không trộn lẫn "đang có" với "muốn có".

## 4. Mục lục

| File | Nội dung |
|---|---|
| [00-intent.md](00-intent.md) | Armarius là gì / không là gì; định vị sản phẩm; các nguyên tắc bất biến. |
| [01-domain.md](01-domain.md) | Mô hình miền: các thực thể, quan hệ, và máy trạng thái (FSM). |
| [02-invite.md](02-invite.md) | Mời agent kiểu vận-hành-viên (operator-invite): nhập gateway + khoá, cấp token ngay, không có bước duyệt. |
| [03-roster-wake.md](03-roster-wake.md) | Vai trò / ghế / cấp ghế; mô hình đánh thức (wake) theo **dự án**. |
| [04-liveness.md](04-liveness.md) | Sống/chết của agent: tín hiệu thiết lập, sức khoẻ gateway duy trì. |
| [05-task-leaderchat.md](05-task-leaderchat.md) | Vòng đời task (một người phụ trách); thêm task tay; Chat với Leader; chế độ YOLO. |
| [06-artifacts-sse.md](06-artifacts-sse.md) | Kho hiện vật dùng chung (MinIO) + cổng "Done"; các kênh sự kiện đẩy về trình duyệt. |
| [07-api-contract.md](07-api-contract.md) | Danh mục điểm cuối (endpoint) API thật. |
| [08-fe-ux.md](08-fe-ux.md) | Kiến trúc thông tin + màn hình phía giao diện (React 19, không mock). |

## 5. Quy ước viết đặc tả

- **Tiếng Việt, đủ dấu.** Thuật ngữ tiếng Anh chỉ giữ khi là tên định danh kỹ thuật (tên endpoint,
  tên cột), và luôn kèm giải thích tiếng Việt.
- Mỗi vùng hành vi có phần **"Tiêu chí nghiệm thu"** — điều kiện quan sát được để coi là đúng.
  Đây là cầu nối sang test.
- Ghi nhãn **[ĐÚNG-NHƯ-CODE]** / **[ĐÍCH-CẦN-SỬA]** ở đầu mỗi mục có liên quan.

## 6. Quan hệ với `docs/` cũ

Sau khi bản nền này hoàn tất, thư mục `docs/` (tiếng Anh) được **đánh dấu là đã lỗi thời (archived)**;
không đọc `docs/` để hiểu hành vi hiện tại nữa. Chúng được giữ lại chỉ để tra cứu lịch sử thiết kế.
