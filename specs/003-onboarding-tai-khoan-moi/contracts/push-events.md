# Contract: sự kiện đẩy (sửa 2026-10-12)

Bổ sung cho [push-events.md của 001](../../001-van-hanh-du-an/contracts/push-events.md), cùng các nguyên
tắc ở đó. Quan trọng nhất là **nguyên tắc 1**: sự kiện là **tín hiệu**, không phải trạng thái. Ai nhận
thì tự đọc lại qua cửa HTTP.

Cả hai sự kiện đi trên **kênh workspace** (`GET /v1/workspaces/{workspace_id}/events`). Tên của chúng nằm
ở `infrastructure/events/workspace_trace.py`, không nằm ở tầng nghiệp vụ, vì chữ `machine` không được có
mặt ở đó (Hiến pháp Điều III).

| Sự kiện | Trạng thái | Khi nào | Mang theo | Ai nghe |
|---------|------------|---------|-----------|---------|
| `machine.linked` | **[có, đổi nghĩa]** | một người duyệt một máy vào workspace | `workspace_id` | bước *nối máy*: đánh dấu xong phần *nối* |
| `machine.workplaces_reported` | **[mới]** | một máy đồng bộ danh sách runtime, kể cả lần báo `stopping` | `workspace_id` | bước *nối máy*: kiểm phần *chạy*; bước *agent đầu tiên* và trang người chủ nhà: đọc lại danh sách runtime |

## `machine.linked` — đổi nghĩa phía người nghe

Sự kiện giữ nguyên. Thứ đổi là việc người nghe làm với nó. Trước đây bước ba nghe thấy thì **kết thúc**
onboarding. Nay nó chỉ đánh dấu xong phần *nối* rồi chỉ sang phần *chạy* (FR-106). Lý do: lúc duyệt, máy
mới có giấy tờ, chưa có runtime nào.

## `machine.workplaces_reported` — mới

- **Phát ở đâu**: ngay sau khi `PUT /daemon/workplaces` ghi xong danh sách. Chỗ phát là nơi cửa ấy hôm
  nay gọi tự đặt chỗ, và lời gọi ấy bị xoá ([research R3](../research.md)).
- **Bao lâu một lần**: daemon chỉ đồng bộ lúc chạy lên và lúc dừng, nên mỗi vòng đời daemon có hai lần.
  Không lọc, không gộp.
- **Vì sao phát cả lúc `stopping`**: danh sách runtime ở bước *agent đầu tiên* phải mất dòng vừa đóng
  (edge case *runtime đã chọn tắt đi trước khi bấm xong*).
- **Vì sao không mang danh sách runtime**: mang thì người nghe có hai nguồn cho một giá trị, và cái trong
  sự kiện cũ đi ngay khi sự kiện kế tiếp tới. `GET …/machines` và `GET …/workplaces` là nguồn duy nhất.

## Không đổi

`marius.online` và `marius.offline` vẫn như cũ. Sau khi người dùng chọn runtime, lần kiểm sống chạy ngay
(FR-006e) và kết quả tới bằng một trong hai sự kiện này. Khung nhắn tin ở trang agent đã nghe chúng sẵn.
