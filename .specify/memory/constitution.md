<!--
Sync Impact Report
- Phiên bản: (chưa có) → 1.0.0
- Loại bump: MAJOR — phê chuẩn lần đầu (first ratification).
- Nguyên tắc thêm: I. Đa tenant nghiêm ngặt; II. Cổng Done; III. Trung lập adapter;
  IV. Đẩy không hỏi-vòng; V. Góc nhìn dự án; VI. Tiếng Việt cho người dùng.
- Phần thêm: "Định vị sản phẩm", "Governance".
- Nguồn chắt: ý định gốc (MY_DEMAND.md, PROJECT_DESCRIPTION.md) và 00-intent (đã dỡ sang _archive/spec-v1/).
- TODO: không có.
-->

# Armarius Constitution

## Core Principles

### I. Đa tenant nghiêm ngặt
Mọi đọc/ghi dữ liệu PHẢI giới hạn trong workspace của người gọi. Truy cập chéo workspace PHẢI trả về
"không tìm thấy" (404) — không được rò rỉ sự tồn tại của tài nguyên thuộc workspace khác.

Lý do: nhiều team dùng chung cùng hạ tầng; lỗi tách tenant là lỗi bảo mật nghiêm trọng, không phải lỗi
chức năng.

### II. Cổng Done — không hiện vật thì chưa xong
Một task KHÔNG ĐƯỢC rời trạng thái "đang làm" nếu chưa đẩy hiện vật đầu ra (artifact) vào kho dùng chung.
Cấm coi task "xong" khi kết quả chỉ nằm ở máy cục bộ của agent.

Lý do: chặn căn bệnh "agent làm xong nhưng để kết quả ở máy nó" — lỗi chí mạng của các hệ đa-agent.

### III. Trung lập adapter
Tầng nghiệp vụ KHÔNG ĐƯỢC nhánh mã theo từng loại agent. Mọi khác biệt giữa các runtime (Hermes, OpenClaw,
Claude local…) PHẢI nằm sau một hợp đồng adapter chung; hệ thống đối xử mọi agent như nhau.

Lý do: không bó buộc một nhà cung cấp; thêm loại agent mới không được đụng tới tầng nghiệp vụ.

### IV. Đẩy, không hỏi-vòng
Trạng thái và sự kiện PHẢI được đẩy về trình duyệt qua kênh sự kiện. Giao diện KHÔNG ĐƯỢC hỏi-vòng (poll)
để biết trạng thái.

Lý do: hỏi-vòng tốn tài nguyên và chậm; đẩy cho khả năng theo dõi theo thời gian thực.

### V. Góc nhìn dự án
Khi làm việc trong một dự án, ngữ cảnh của agent (vai trò, đồng đội, wake, prompt) PHẢI theo vai trò trong
dự án đó — KHÔNG ĐƯỢC dùng thuộc tính ở tầng workspace.

Lý do: cùng một agent có thể giữ vai khác nhau giữa các dự án; ngữ cảnh phải bám đúng dự án đang làm.

### VI. Tiếng Việt cho người dùng
Mọi chuỗi hiển thị với người dùng PHẢI đi qua cơ chế i18n (Việt/Anh). Tiếng Việt hiển thị PHẢI đủ dấu —
tiếng Việt không dấu là "rác", không được đưa ra giao diện.

Lý do: người dùng cuối là người Việt; chất lượng ngôn ngữ là phần thấy được của chất lượng sản phẩm.

## Định vị sản phẩm

Armarius là nơi làm việc dùng chung: nhiều người ở nhiều team mời agent của mình vào, agent tự nhận việc,
hỏi/đáp các bên, cộng tác ngang hàng, đẩy kết quả vào kho chung — còn con người chỉ giám sát và phê duyệt.
Khẩu hiệu: **"Bạn giao việc. Chúng cộng tác. Bạn theo dõi."**

Armarius KHÔNG phải công cụ vận hành cả công ty: không có CEO/Goal/sơ đồ tổ chức, chỉ có **Dự án** và bộ
vai trò. Armarius tự sở hữu vòng đánh thức (wake) và cơ chế sống/chết (liveness) — không phụ thuộc heartbeat
của runtime ngoài.

## Governance

- Hiến pháp này là tầng **bất biến**: mọi đặc tả chi tiết, mọi quyết định kỹ thuật PHẢI tuân. Một tính năng
  đi ngược nguyên tắc ở đây thì **tính năng đó sai**, không phải nguyên tắc.
- Chỉ sửa Hiến pháp khi định vị sản phẩm đổi. Phiên bản hoá theo ngữ nghĩa:
  - **MAJOR**: bỏ hoặc định nghĩa lại nguyên tắc.
  - **MINOR**: thêm nguyên tắc/phần, mở rộng hướng dẫn thực chất.
  - **PATCH**: làm rõ chữ nghĩa, sửa lỗi chính tả, tinh chỉnh không đổi nghĩa.
- Mọi thay đổi hành vi của hệ thống đi qua quy trình spec-kit:
  `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`.
  Nguyên tắc: **đặc tả đi trước, mã theo sau và phải chứng minh khớp đặc tả.**
- Mọi PR PHẢI xác nhận tuân Hiến pháp; thay đổi phức tạp PHẢI giải trình lý do.

**Version**: 1.0.0 | **Ratified**: 2026-07-29 | **Last Amended**: 2026-07-29
