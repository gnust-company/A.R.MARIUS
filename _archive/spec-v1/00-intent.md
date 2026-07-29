# 00 — Ý định sản phẩm

> Chắt từ `MY_DEMAND.md` và `PROJECT_DESCRIPTION.md` (ý định gốc, tiếng Việt). Đây là tầng **bất biến**:
> các nguyên tắc dưới đây định hình mọi quyết định; nếu một tính năng đi ngược một nguyên tắc ở đây,
> tính năng đó sai, không phải nguyên tắc.

---

## 1. Một câu định vị

**Armarius là một nơi làm việc dùng chung, nơi nhiều người ở nhiều team mời agent của mình vào,
agent tự nhận việc — hỏi/đáp với các bên — cộng tác ngang hàng với agent khác — đẩy kết quả vào kho
chung, còn con người chỉ giám sát và phê duyệt.**

Khẩu hiệu: **"Bạn giao việc. Chúng cộng tác. Bạn theo dõi."**

## 2. Armarius LÀ gì

- **Nơi làm việc dùng chung (workspace) đa dự án.** Một workspace chứa nhiều dự án, mỗi dự án là một
  đơn vị công việc độc lập với bộ vai trò (roster) riêng.
- **Cộng tác là tính năng lõi.** Agent phải **biết về nhau** trong phạm vi dự án, nhắc tên (mention)
  nhau, trao đổi — chứ không phải mạnh ai nấy làm.
- **Kết quả luôn nằm trong kho chung.** Căn bệnh chí mạng của các hệ đa-agent khác — *agent làm xong
  nhưng để kết quả ở máy nó* — bị chặn từ thiết kế: một task **không thể** coi là "xong" nếu chưa
  đẩy hiện vật (artifact) đầu ra vào kho dùng chung.
- **Trung lập với loại agent.** Không bó buộc một nhà cung cấp. Mọi runtime (Hermes, OpenClaw,
  Claude local...) được bọc sau **một hợp đồng adapter chung**; hệ thống đối xử với mọi loại agent
  như nhau.
- **Armarius tự sở hữu vòng đánh thức (wake) và cơ chế sống/chết (liveness).** Không phụ thuộc
  heartbeat của runtime bên ngoài — vì đó chính là chỗ hai sản phẩm tham chiếu bị hỏng.

## 3. Armarius KHÔNG là gì

- **Không phải "vận hành cả công ty".** Bỏ hẳn khái niệm CEO / Goal / sơ đồ tổ chức. Chỉ có
  **Dự án** + **Roster (yêu cầu vai trò/kỹ năng)**. Bài toán là **cộng tác giữa các team**, không phải
  điều hành một doanh nghiệp.
- **Không bó buộc một loại agent** (không chỉ OpenClaw như Mission Control).
- **Không phụ thuộc heartbeat của runtime ngoài** (điểm yếu của Mission Control: một instance quá tải
  bị treo mà mình không kiểm soát được).

## 4. Bài học từ hai sản phẩm tham chiếu

**Giữ lại từ Paperclip:**
- Adapter cho từng loại agent (đối xử mọi agent như nhau).
- Mỗi task là một phiên làm việc (session) bền, cho phép agent làm liên tục qua nhiều lần đánh thức.
- Cơ chế mời + cài kỹ năng (skill) để onboard agent chuẩn hoá.

**Giữ lại từ OpenClaw Mission Control:**
- Có một khu chat chung trong dự án để người + agent cùng trao đổi.
- Đơn giản; phê duyệt/giám sát là tính năng hạng nhất.

**Sửa các lỗi của cả hai:**
- Agent không biết về nhau → **Danh bạ agent + nhắc tên + luồng trao đổi ngang** là tính năng lõi.
- Không có kho chung, agent tạo file ở máy nó → **Kho hiện vật dùng chung là bắt buộc**; "xong" chỉ
  hợp lệ khi đầu ra nằm trong kho.
- Phụ thuộc heartbeat ngoài → **Armarius tự chủ liveness**.

## 5. Các vai người & agent

- **Patron (người chủ):** con người giám sát. Giao việc bằng lời, phê duyệt, theo dõi. Không tự điền
  chi tiết task.
- **Leader (agent trưởng dự án):** một agent giữ ghế trưởng của dự án. Là đầu mối Patron trò chuyện để
  định hướng và tạo việc; điều phối các worker.
- **Worker (agent thợ):** agent giữ các ghế vai trò khác trong dự án, nhận và thực thi task.
- **Workspace Agent (agent quản gia workspace):** một agent được chỉ định để dẫn dắt việc onboarding
  (lập dự án qua hội thoại). Tuỳ chọn.

## 6. Ba khoảnh khắc chữ ký của sản phẩm

Mọi thứ khác chỉ để phục vụ ba khoảnh khắc này:

1. **Giao việc qua Leader** — Patron nói mong muốn, Leader shape thành task.
2. **Cộng tác** — các agent cùng làm, trao đổi trong luồng của task.
3. **Theo dõi (trace)** — Patron xem diễn tiến chạy thật của agent theo thời gian thực.

## 7. Những nguyên tắc bất biến (mọi đặc tả chi tiết phải tuân)

1. **Đa tenant nghiêm ngặt:** mọi đọc/ghi giới hạn trong workspace của người gọi; truy cập chéo
   workspace là "không tìm thấy" (404).
2. **Cổng "Done" chống-file-ở-local:** không có hiện vật đầu ra thì task không rời khỏi trạng thái
   đang-làm.
3. **Trung lập adapter:** không nhánh mã theo từng loại agent ở tầng nghiệp vụ; mọi khác biệt nằm sau
   hợp đồng adapter.
4. **Đẩy, không hỏi-vòng (push, not poll):** trạng thái/sự kiện được đẩy về trình duyệt qua kênh sự
   kiện, không để giao diện hỏi-vòng.
5. **Góc nhìn dự án:** khi làm việc trong một dự án, ngữ cảnh (vai trò của mình, đồng đội, wake,
   prompt) phải theo **vai trò của dự án đó** — không dùng thuộc tính ở tầng workspace.
6. **Tiếng Việt cho người dùng:** mọi chuỗi hiển thị đi qua cơ chế i18n (Việt/Anh), đủ dấu.
