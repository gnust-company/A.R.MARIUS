<!--
Sync Impact Report
- Phiên bản: 1.0.1 → 1.1.0
- Loại bump: MINOR — thêm một nguyên tắc mới (VII), không sửa và không bỏ nguyên tắc nào.
- Phần thêm: **VII. Gói tin gửi agent dùng tiếng Anh.** Điều VI đã đặt luật cho chữ hiển thị với
  người dùng, nhưng chưa điều nào nói chữ hệ thống gửi cho *agent* dùng thứ tiếng gì. Mã vốn đã
  làm đúng — gói tin đánh thức viết toàn tiếng Anh — nên đây là luật đuổi theo mã, trừ mấy câu
  *lý do gọi dậy* các đợt gần đây viết bằng tiếng Việt rồi nhét vào giữa một gói tin tiếng Anh.
  Người chủ chốt ngày 2026-08-16, khi thấy câu lý do gọi dậy hiện lẫn hai thứ tiếng trên màn hình
  agent (T193).
- Nguyên tắc sửa: không có. Phần bớt: không có. TODO: không có.
-->

<!--
Sync Impact Report (1.0.1)
- Phiên bản: 1.0.0 → 1.0.1
- Loại bump: PATCH — làm rõ chữ nghĩa Nguyên tắc II cho khớp ý định vốn có; không nguyên tắc nào
  được thêm, bớt, hay đổi mục đích.
- Nguyên tắc sửa: II. Cổng Done — mốc cưỡng chế nêu rõ là **đánh dấu "xong"**, thay cho chữ "rời
  trạng thái đang làm". Chữ cũ đọc theo mặt chữ thì cấm cả *đang làm → bị chặn* và *đang làm →
  chờ làm*, điều chưa bao giờ là ý định và mã cưỡng chế cũng chưa bao giờ làm vậy
  (ARTIFACT_REQUIRED_STATUSES vốn chỉ gồm hai trạng thái *chờ rà soát* và *xong*). Phát hiện ở
  bước soi chéo đặc tả 001 (mã V1), người chủ chốt ngày 2026-07-31.
- Bổ sung: một câu nói rõ nguyên tắc này đặt **sàn**, không đặt trần — đặc tả tính năng được dựng
  cổng sớm hơn nhưng không được hạ thấp hơn mốc "xong". Ghi điều này để việc FR-026 chặn ngay lối
  vào vòng rà soát là một lựa chọn hợp lệ chứ không phải vượt rào.
- Phần thêm / bớt: không có.
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
Một task KHÔNG ĐƯỢC đánh dấu "xong" nếu chưa đẩy **hiện vật đầu ra** — sản phẩm thật mà task ấy sinh ra —
vào kho dùng chung. Cấm coi task "xong" khi kết quả chỉ nằm ở máy cục bộ của agent.

Nguyên tắc này đặt **sàn**, không đặt trần: một đặc tả tính năng ĐƯỢC dựng cổng sớm hơn — chẳng hạn chặn
ngay lối vào vòng rà soát — nhưng KHÔNG ĐƯỢC hạ thấp hơn mốc "xong".

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

### VII. Tiếng Anh cho agent
Mọi chữ **hệ thống** sinh ra rồi gửi cho agent — lời gọi dậy, lời nhắc, mô tả công cụ, câu hướng dẫn —
PHẢI viết bằng tiếng Anh. Chữ do **người** nhập (bối cảnh dự án, tiêu đề và mô tả đầu việc, bình luận)
giữ nguyên thứ tiếng người viết, không dịch.

Hệ quả: một câu vừa gửi cho agent vừa hiện lên màn hình thì KHÔNG ĐƯỢC lưu sẵn thành câu. Phải lưu **mã
lý do kèm tham số**, rồi mỗi phía tự dựng câu: tiếng Anh cho agent, qua cơ chế i18n cho người dùng.

Lý do: agent không có ngôn ngữ giao diện để chọn, nên chữ gửi cho nó phải cố định một thứ tiếng; trộn hai
thứ tiếng trong một gói tin làm mô hình yếu đọc sai. Điều này KHÔNG mâu thuẫn Điều VI — hai điều nói về
hai người đọc khác nhau.

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

**Version**: 1.1.0 | **Ratified**: 2026-07-29 | **Last Amended**: 2026-08-16
