# Contract: mặt người dùng (sửa 2026-10-12)

Những cửa HTTP lần sửa này thêm hoặc đổi. Mọi cửa dưới `/v1/workspaces/{workspace_id}/…` đều kiểm chủ sở
hữu như cửa hiện có: không gian làm việc không phải của người gọi thì trả **404**, giống hệt không gian
làm việc không tồn tại (Hiến pháp Điều I).

Lỗi trả về theo khuôn sẵn có: một **mã** kèm tham số, và giao diện dựng câu qua i18n (Điều VII).

---

## 1. Đặt chỗ cho người chủ nhà **[mới]**

`POST /v1/workspaces/{workspace_id}/mariuses/{marius_id}/placement`

Dùng ở bước *agent đầu tiên* (FR-125, FR-126) và ở trang của người chủ nhà khi nó chưa có chỗ làm
(FR-128). Lý do thiết kế: [research.md R2](../research.md).

**Request**

```json
{
  "workplace_id": "7aae5e01-…",
  "instructions": "Reply in the language the owner writes to you in. …"
}
```

| Trường | Bắt buộc | Nghĩa |
|--------|----------|-------|
| `workplace_id` | có | một chỗ làm lấy từ `GET …/workplaces` |
| `instructions` | không | có thì lưu **cùng lần** với việc đặt chỗ, chuỗi rỗng là giá trị thật (chỉ dẫn rỗng); vắng thì giữ nguyên chỉ dẫn hiện có |
| `name` | không | *(thêm 2026-10-26)* tên mới của người chủ nhà, bỏ khoảng trắng hai đầu, 1–200 ký tự; lưu **cùng lần** với việc đặt chỗ; vắng thì giữ nguyên tên |

**200** — trả `MariusOut` như `GET …/mariuses`. `runtime` lúc này đã có giá trị. `status` có thể vẫn
chưa `online`, vì lần kiểm sống chạy ngay sau đó (FR-006e), và kết quả tới bằng sự kiện `marius.online`.

**Lỗi**

| HTTP | Mã | Khi nào | Tham số |
|------|----|---------|---------|
| 404 | `workspace_not_found` | không gian làm việc không phải của người gọi hoặc không tồn tại | — |
| 404 | `agent_not_found` | agent không thuộc không gian làm việc này | — |
| 404 | `placement_not_found` | chỗ làm không thuộc không gian làm việc này | — |
| 409 | `placement_is_fixed` | agent không giữ ghế chủ nhà (FR-007) | — |
| 409 | `agent_already_placed` | người chủ nhà đã có chỗ làm (FR-127) | `cli_kind`, `machine_name` của chỗ đang ở |
| 409 | `agent_name_taken` | *(thêm 2026-10-26)* `name` trùng một agent khác trong không gian làm việc | `name` |
| 400 | `placement_not_ready` | chỗ làm chưa sẵn sàng, hoặc không còn nhận việc | `reason`: mã lý do như `not_ready_reason` |
| 422 | — | thiếu `workplace_id`, `instructions` quá 20000 ký tự | — |

**Bất biến**
- Thành công thì có đúng một dòng gắn người chủ nhà với `workplace_id`, và `instructions` (nếu gửi) đã
  lưu. Thất bại thì **không** thứ nào thay đổi.
- Hai yêu cầu đồng thời: đúng một cái thành công, cái kia trả 409 `agent_already_placed`.

---

## 2. `PATCH /auth/me` **[sửa]**

| Trường | Trước | Sau |
|--------|-------|-----|
| `onboarding_step` | 0–3 | **0–4** |

Ngoài khoảng ấy thì 422, như hôm nay. `onboarding_done: true` vẫn là cách duy nhất đánh dấu xong.

---

## 3. `GET /v1/workspaces/{workspace_id}/skills` **[sửa]**

**Không trả** skill có `source = "builtin"` (FR-123). Thư viện skill, màn tạo agent và tab skill của
agent đều đọc từ đây, nên không màn nào phải tự lọc.

`GET /v1/workspaces/{workspace_id}/skills/{skill_id}` với id của một skill dựng sẵn trả **404**, cùng lý
do: người dùng không có đường nào để biết tới nó.

---

## 4. Các cửa ghi skill của agent **[sửa]**

`POST …/mariuses`, `PATCH …/mariuses/{id}` và `POST …/mariuses/{id}/install-skills` **lẳng lặng bỏ**
mọi id thuộc skill dựng sẵn trong `skill_ids`. Chúng không báo lỗi gì ([research R7](../research.md)).
`MariusOut.skill_ids` và `MariusOut.skills` không bao giờ chứa skill dựng sẵn.

---

## 5. `MariusOut` **[không đổi hình dạng]**

- `system_instructions`: có sẵn, giao diện hiện chỉ đọc (FR-123a).
- `instructions`: người chủ nhà mới tạo thì mang sẵn chỉ dẫn mặc định (FR-124).
- `offline_reason = "not_placed"`: nghĩa không đổi. Câu hiển thị đổi thành *chưa được chọn runtime*
  (FR-128).
- `runtime = null`: dấu hiệu để giao diện hiện đường chọn runtime ở trang người chủ nhà.

---

## 6. Cửa không còn làm việc cũ

`PUT /daemon/workplaces` **thôi** đặt người chủ nhà vào chỗ làm (FR-112). Request và response giữ nguyên.
Cửa này nay phát thêm một sự kiện, xem [push-events.md](push-events.md).
