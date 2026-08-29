# Hợp đồng: agent ↔ server trong một lượt chạy

**Feature**: 002 | **Phase**: 1

Đây là bề mặt agent gọi ngược về Armarius trong lúc chạy. Nó **không phải bề mặt mới** — nhóm route
`/agent/*` đã có sẵn. Tệp này chỉ ghi những gì đổi khi chuyển sang daemon.

Xác thực bằng **token của lượt chạy**, thứ daemon nhét vào agent qua biến môi trường. Token này:
- chỉ mở đúng **một đầu việc**, không mở cả máy;
- **hết hiệu lực khi lượt chạy khép lại** (FR-014b);
- **không bao giờ** là token của daemon, kể cả khi đúc hỏng (FR-014c).

**Hai câu trả lời khi cú gọi không đi lọt**, và chúng khác nhau (dựng ở T135):

| Tình huống | Trả về | Mã lý do |
| --- | --- | --- |
| Không trình gì cả | `401` | `missing_bearer_token` |
| Token không mở lượt chạy nào — chưa từng có, **hoặc** đã thu hồi | `404` | `run_not_found` |
| Chạm sang đầu việc / dự án ngoài phạm vi lượt chạy | `404` | `task_not_found` / `project_not_found` |

Hai dòng dưới đọc y hệt nhau từ ngoài, và đó là chủ ý: không-phải-của-bạn và không-tồn-tại không được
phân biệt (Điều I), nên ai cầm một chuỗi đã chết cũng không xác nhận được nó từng mở thứ gì. Thứ phân biệt
chúng là **mã lý do**, và daemon cần đúng mã ấy để xếp *token đã chết* vào loại lỗi cần người xử thay vì
thử lại (FR-014f).

**Một ngoại lệ, có hạn**: hai lối `/agent/onboarding/*` còn nhận token sống lâu, vì buổi phỏng vấn chưa đi
đường nhận việc nên chưa có lượt chạy nào để đúc token cho nó. Cửa tạm ấy chết cùng FR-040c (T048a).

---

## Đổi so với hôm nay

### Không đổi

Toàn bộ đường hiện có giữ nguyên: bình luận, nhắc tên, đổi trạng thái đầu việc, ghi hành động kế tiếp, hỏi
lại, trả việc. Đặc tả này **không thêm quyền nào cho agent** và không mở lại đường thợ tự nhận việc đã gỡ
(FR-060).

### `POST /agent/artifacts` — thêm tính chịu được gọi lặp

> Đường dẫn thật khi hiện thực (T084): `POST /agent/tasks/{task_id}/artifact` — đường đã
> có từ trước, giữ nguyên để không đổi bề mặt agent đang dùng; `task_id` đi trong đường
> dẫn thay vì thân tin. Ngữ nghĩa dưới đây không đổi.

```json
→ { "task_id": "…", "logical_name": "report.pdf", "content": "<base64 | multipart>" }
← 201 { "artifact_id": "…", "created": true  }    ← lần đầu
← 200 { "artifact_id": "…", "created": false }    ← đẩy lại y hệt: KHÔNG đẻ bản trùng
← 201 { "artifact_id": "…", "created": true, "version": 2 }   ← cùng tên, nội dung khác
```

Khoá là `(task_id, logical_name, content_hash)` — xem [research §6](../research.md).

Đẩy hỏng giữa chừng thì **gọi lại, không giới hạn số lần**, kể cả ở một lượt chạy sau, vì thư mục làm việc
sống theo đầu việc nên tệp vẫn còn đó (FR-020b).

### `GET /agent/skills` và `GET /agent/skills/{slug}` — **gỡ**

Kỹ năng không còn do agent tự lấy về. Chúng đi xuống trong gói nhận việc và **daemon ghi thẳng vào thư mục
kỹ năng native của CLI** trước khi agent đọc dòng đầu tiên (FR-011b, FR-011c). Hai route này được gỡ cùng
với vòng xác nhận đã-cài-xong còn dở dang từ đợt trước — daemon ghi tệp trực tiếp thì không còn gì để xác
nhận.

Kèm theo: tờ hướng dẫn agent không được dạy lệnh cài kỹ năng nữa.

### *Thứ đã đổi trong thư mục làm việc* — **một lệnh trả lời tại chỗ, KHÔNG phải route server**

```json
← { "changed": [ { "path": "report.pdf", "bytes": 20481, "modified_at": "…" } ] }
```

Agent hỏi **để biết mình có gì mà công bố**. Đây là thông tin, **không phải công bố tự động** (FR-020a);
daemon không tự dò và không tự đẩy (FR-018).

**Sửa 2026-08-29 — bản trước ghi nó là `GET /agent/workdir/changes` trên bề mặt này, và đó là chỗ sai.**
Câu hỏi này là câu **duy nhất** trong cả hợp đồng mà dữ liệu **không nằm ở server**: nó nằm trên đĩa của
chính cái máy đang chạy agent. Đặt nó thành route server thì server phải đi hỏi ngược xuống daemon — mà
daemon là bên **xin việc**, không phải bên phục vụ (FR-053, FR-055). Không có đường ấy, và dựng nó là lộn
ngược cả chặng một.

Nay nó là **một lệnh của bộ công cụ gọi ngược** (FR-013a), trả lời ngay tại máy, **không đi lên server và
không cần token**. Nó vẫn nằm trong hợp đồng này vì nó là thứ agent gọi; nhưng nó nằm ở **mặt lệnh**, không
ở bề mặt agent↔server.

### Cổng Done — không đổi, chỉ nhắc

Agent chuyển đầu việc rời *đang làm* mà chưa công bố hiện vật nào thì **bị chặn ở tầng công cụ** kèm mã lý
do đọc được, và đầu việc vẫn giữ một động cơ đẩy sống (FR-019). Luật này cũng phải có mặt **trong tờ hướng
dẫn gửi agent** — dặn không thay cho chặn.

---

## Ranh giới phải giữ

| Agent **được** | Agent **không được** |
| --- | --- |
| Công bố hiện vật của đầu việc mình đang làm | Đọc hay ghi đầu việc khác |
| Hỏi xem mình đã đổi gì trong thư mục làm việc | Bảo daemon tự đẩy hộ |
| Bình luận, hỏi lại, trả việc | Tự chọn việc cho mình (FR-060) |
| Ghi hành động kế tiếp | Tự đánh dấu *xong* khi chưa có hiện vật |

Chạm sang đầu việc khác hoặc workspace khác đều trả `404` (Điều I).
