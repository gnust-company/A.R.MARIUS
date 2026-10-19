# Quickstart: kiểm onboarding bốn bước trên dịch vụ thật (sửa 2026-10-12)

**Đặc tả**: [spec.md](spec.md) · **Contracts**: [user-surface.md](contracts/user-surface.md),
[push-events.md](contracts/push-events.md)

Mỗi kịch bản dưới đây chạy trên stack thật: giao diện `:3000`, API `:8080`, Postgres trong
`armarius-db-1`. Giao diện được lái bằng Playwright qua `python3` của hệ thống. Bài kiểm đơn vị không
thay được bước này.

## Chuẩn bị

1. **Dựng lại** frontend và backend từ nhánh đang làm. Ghi log dựng ra file, không `| tail`, để lỗi dựng
   không bị nuốt.
2. **Daemon thử**: một thư mục cấu hình riêng, và `PATH` chỉ gồm một thư mục có symlink `claude` cùng
   `/usr/bin:/bin`. Daemon của người chủ (`~/.armarius/`) **không được đụng**.
3. **Máy giả lập** cho kịch bản hai runtime ([research R10](research.md)): một script đi qua link và
   approve như daemon, rồi `PUT /daemon/workplaces` với một loại CLI thứ hai. **Không chạy `gemini` hay
   `codex`**, kể cả để dò.
4. Tài khoản thử dùng email `verify-*@acme.dev`. Xong thì dọn hết. Tài khoản thật của người chủ không
   được đụng.

## Kịch bản

### K1 — Đi hết bốn bước với một runtime (US3, SC-105, SC-107)

1. Đăng ký, qua bước *về bạn* và bước *không gian làm việc*.
2. Bước *nối máy* hiện ba phần *cài*, *nối*, *chạy*, mỗi phần có lệnh chép được.
3. Chạy `login` của daemon thử, rồi duyệt mã ở **cửa sổ thứ hai**. **Mong đợi**: cửa sổ một đánh dấu xong
   *nối* trong vòng 5 giây, không tải lại trang. Cửa sổ hai nói tiếp lệnh `start` và **không** nói là
   onboarding đã xong.
4. Chạy `start`. **Mong đợi**: cửa sổ một tự sang bước *agent đầu tiên* trong vòng 5 giây.
5. **Mong đợi** ở bước này: thấy system prompt chỉ đọc, ô chỉ dẫn có sẵn chỉ dẫn mặc định, runtime claude
   **được chọn sẵn** (chỉ có một), và **không** có skill nào.
6. Sửa một chữ trong ô chỉ dẫn rồi bấm xong. **Mong đợi**: tới trang Livia. Livia trực tuyến. Chỉ dẫn có
   đúng chữ đã sửa. Tin nhắn đầu tiên có trả lời.
7. Đăng xuất rồi đăng nhập lại. **Mong đợi**: không gặp lại onboarding.

### K2 — Hai runtime, người dùng tự chọn (FR-125, SC-106)

1. Như K1 tới bước 4, nhưng thêm **máy giả lập** báo một loại CLI thứ hai.
2. **Mong đợi**: không runtime nào được chọn sẵn, và nút xong bị khoá.
3. Chọn runtime **không** phải cái có id nhỏ nhất rồi bấm xong. **Mong đợi**: trong DB, dòng gắn Livia trỏ
   đúng chỗ làm vừa chọn.

### K3 — Bỏ qua nối máy, chọn runtime sau (FR-100, FR-112, FR-128)

1. Ở bước *nối máy*, bấm bỏ qua. **Mong đợi**: không gặp bước *agent đầu tiên*, vào thẳng trong.
2. Trang Livia: ngoại tuyến, lý do *chưa được chọn runtime*, có đường chọn runtime.
3. Nối máy và chạy daemon thử. **Mong đợi**: Livia **vẫn** chưa có chỗ làm, vì không còn tự đặt chỗ. Danh
   sách chọn trên trang Livia tự có claude, không cần tải lại.
4. Chọn claude. **Mong đợi**: Livia trực tuyến, và đường chọn biến mất.

### K4 — Hai cửa sổ cùng bấm xong (FR-127)

Gửi hai yêu cầu `POST …/placement` gần như cùng lúc, mỗi cái một runtime. **Mong đợi**: một cái 200, một
cái 409 `agent_already_placed` kèm `cli_kind` và `machine_name`. Chỉ có một người chủ nhà, và chỗ làm của
nó là của yêu cầu 200.

### K5 — Runtime tắt trước khi bấm xong (edge case)

Đứng ở bước *agent đầu tiên* rồi dừng daemon thử. **Mong đợi**: danh sách mất dòng claude qua
`machine.workplaces_reported`. Gửi thẳng yêu cầu đặt chỗ với chỗ làm vừa tắt thì nhận 400
`placement_not_ready`, và Livia vẫn chưa có chỗ làm.

### K6 — Skill dựng sẵn ẩn hết, agent vẫn nhận (FR-123, SC-108)

1. Trang Skills không còn mục *Tích hợp sẵn*. Màn tạo agent không có chip *luôn bật*. Tab skill của agent
   không có skill dựng sẵn.
2. `GET …/skills` không có dòng `source = "builtin"`. `GET …/skills/{id dựng sẵn}` trả 404.
3. Giao một lượt chạy cho Livia. **Mong đợi**: lượt chạy vẫn nhận skill *Talking to Armarius* (đọc trong
   thư mục làm việc của lượt chạy, hoặc trong `run_events`).

### K7 — Agent thường mất chỗ làm thì không được đặt lại (research R2)

Tạo một agent thường trên daemon thử, rồi gỡ máy khỏi workspace. Gửi `POST …/placement` cho agent ấy.
**Mong đợi**: 409 `placement_is_fixed`, và trang của nó không có đường chọn runtime.

### K8 — Người đang dở dang lúc triển khai (R6)

Một người dùng có `onboarding_step = 2` và chưa xong. **Mong đợi**: đăng nhập thì vào bước *nối máy* của
luồng bốn bước. Một người đã xong thì không bị kéo vào lại.

## Bộ kiểm tự động phải xanh

- Backend: toàn bộ bộ kiểm (`backend/.venv/bin/python -m pytest`, khoảng 11 phút), và `ruff check`.
- Frontend: `npm run build`, `npx eslint`, `npx vitest run`.
- Daemon: không đổi mã Go. Không cần chạy lại nếu không có thay đổi ở `daemon/`.
