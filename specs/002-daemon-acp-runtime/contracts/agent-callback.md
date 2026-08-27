# Hợp đồng: agent ↔ server trong một lượt chạy

**Feature**: 002 | **Phase**: 1

Đây là bề mặt agent gọi ngược về Armarius trong lúc chạy. Nó **không phải bề mặt mới** — nhóm route
`/agent/*` đã có sẵn. Tệp này chỉ ghi những gì đổi khi chuyển sang daemon.

Xác thực bằng **token của lượt chạy**, thứ daemon nhét vào agent qua biến môi trường. Token này:
- chỉ mở đúng **một đầu việc**, không mở cả máy;
- **hết hiệu lực khi lượt chạy khép lại** (FR-014b);
- **không bao giờ** là token của daemon, kể cả khi đúc hỏng (FR-014c).

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

### `GET /agent/workdir/changes` — mới

```json
← 200 { "changed": [ { "path": "report.pdf", "bytes": 20481, "modified_at": "…" } ] }
```

Daemon liệt kê những gì đã đổi trong thư mục làm việc **để agent biết mình có gì mà công bố**. Đây là
thông tin, **không phải công bố tự động** (FR-020a). Daemon không tự dò và không tự đẩy (FR-018).

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
