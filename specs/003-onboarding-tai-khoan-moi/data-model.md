# Data Model: Onboarding dạy từ thêm máy tới agent đầu tiên (sửa 2026-10-12)

**Đặc tả**: [spec.md](spec.md) · **Research**: [research.md](research.md)

**Không có bảng mới và không có cột mới.** Lần sửa này đổi khoảng giá trị của một trường, đổi giá trị
khởi đầu của một trường khác, và dọn một ít dữ liệu cũ.

---

## Người dùng: trạng thái onboarding

| Trường | Trước | Sau |
|--------|-------|-----|
| `users.onboarding_step` | 0–3; xong thì là 3 | **0–4**; xong thì là 4 |
| `users.onboarded_at` | có giá trị nghĩa là đã xong | không đổi |

Các bước, theo số:

| Số | Bước | Ghi chú |
|----|------|---------|
| 0 | *về bạn* | không bỏ qua được |
| 1 | *không gian làm việc* | không bỏ qua được |
| 2 | *nối máy* | bỏ qua được; bỏ qua thì bỏ luôn bước 3 |
| 3 | *agent đầu tiên* | **mới**; bỏ qua được |
| 4 | đã xong | đi cùng `onboarded_at` |

**Chuyển trạng thái**

```text
0 ──lưu tên──▶ 1 ──đổi tên workspace──▶ 2 ──máy báo runtime──▶ 3 ──đặt chỗ cho Livia──▶ 4 (xong)
                                         │                       │
                                         └──bỏ qua──▶ 4 (xong)   └──bỏ qua──▶ 4 (xong)
```

- Xong là **một chiều**, như hôm nay: gửi `onboarding_done: false` thì được nhận và không làm gì.
- Duyệt máy **không** chuyển trạng thái nào (FR-106 sửa lại).
- Bước 2 có ba phần *cài*, *nối*, *chạy*. Ba phần ấy **không lưu**: chúng suy ra từ dữ liệu máy mỗi lần
  đọc (research R5). Lưu chúng là giữ bản chép thứ hai của một sự thật đã có trên bảng `machines` và
  `workplaces`.

---

## Người chủ nhà (`mariuses`, ghế chủ nhà)

| Trường | Trước | Sau |
|--------|-------|-----|
| `system_instructions` | việc của người chủ nhà, tiếng Anh, không cửa nào sửa | không đổi; **hiện ra** chỉ đọc ở bước 3 (FR-123a) |
| `instructions` | rỗng lúc tạo | **chỉ dẫn mặc định** lúc tạo, tiếng Anh, người dùng sửa được (FR-124, research R1) |
| `adapter_type` | tự điền khi tự đặt chỗ | điền lúc **người dùng** đặt chỗ lần đầu |

Người chủ nhà đã có từ trước thì giữ nguyên cả hai trường chữ. Không có migration nào cho chúng.

**Vòng đời chỗ làm**

```text
tạo cùng workspace ──▶ CHƯA CÓ CHỖ LÀM ──người dùng chọn runtime (một lần)──▶ CÓ CHỖ LÀM
  (offline, not_placed)                                                         (kiểm sống ngay, FR-006e)
```

- Từ *CÓ CHỖ LÀM* không có mũi tên nào sang một chỗ làm khác (FR-007). Đường duy nhất đi ra là **máy
  của nó bị gỡ** khỏi workspace: dòng gắn mất, người chủ nhà về *CHƯA CÓ CHỖ LÀM*, và người dùng chọn
  lại được (FR-128, research R2).
- Máy báo runtime **không** tạo ra mũi tên nào (FR-112 sửa lại, research R3).
- Agent **thường** mất chỗ làm vì máy bị gỡ thì **không** được đặt lại qua cửa này (409
  `placement_is_fixed`).

---

## Gắn agent với chỗ làm (`agent_workplace_bindings`)

Không đổi cấu trúc. Ràng buộc *mỗi agent một dòng* sẵn có là thứ chặn hai cửa sổ cùng đặt chỗ cho một agent
(FR-127): lần ghi tới sau đụng ràng buộc, và cửa trả 409 `agent_already_placed`.

Một chỗ làm **nhận được agent** khi: thuộc đúng workspace, `ready`, và có loại CLI chở việc. Đây đúng là
điều kiện `place_host` đang dùng, chuyển sang cửa đặt chỗ mới.

---

## Skill dựng sẵn

| Chỗ | Trước | Sau |
|-----|-------|-----|
| `skills` (dòng có `source = "builtin"`) | hiện trong thư viện, tab *Tích hợp sẵn* | vẫn gieo vào mọi workspace; **không** trả ra cho người xem |
| `mariuses.skill_ids` | có thể chứa id dựng sẵn (người dùng từng bấm chọn chip) | **không** chứa id dựng sẵn |
| `mariuses.skills` (tên, chép theo `skill_ids`) | có thể chứa tên dựng sẵn | **không** chứa tên dựng sẵn |
| Lượt chạy của agent | dựng sẵn luôn đi kèm, khử trùng theo id | không đổi |

**Migration dữ liệu**: với mỗi agent, bỏ khỏi `skill_ids` mọi id thuộc một skill `source = "builtin"`
cùng workspace, và bỏ tên tương ứng khỏi `skills`. `downgrade` **không** gắn lại. Skill dựng sẵn vẫn tới
mọi lượt chạy theo đường riêng, nên gắn lại cũng không đổi gì.
