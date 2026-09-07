# Quickstart

Từ máy trắng tới đầu việc đầu tiên được agent làm xong. Khoảng 15 phút, trong đó phần lâu
nhất là `docker compose` tải image.

Cần có sẵn:

- **Docker** và **Docker Compose**
- **Ít nhất một agent CLI đã cài và đã đăng nhập** trên máy bạn — `claude`, `codex`, hoặc
  `gemini`. Đây không phải tuỳ chọn: Armarius không nuôi agent nào, nó chỉ bật thứ bạn đã có
  ([Agent](agents.md)).

---

## 1. Dựng Armarius lên

```bash
git clone https://github.com/gnust-company/A.R.MARIUS.git
cd A.R.MARIUS
cp .env.sample .env
docker compose up --build
```

Bốn thứ khởi động cùng nhau: Postgres, MinIO (kho hiện vật), API, và giao diện.

Xong thì mở **http://localhost:3000** và đăng nhập bằng tài khoản demo:

```
demo@acme.dev / demo1234
```

API ở `http://localhost:8080` — `/docs` là bản mô tả cửa, `/healthz` để kiểm tra nó còn sống.

## 2. Tạo một không gian làm việc

Đăng nhập lần đầu sẽ rơi vào **Xưởng** — danh sách không gian làm việc. Tạo một cái.

Không gian làm việc (**workspace**) là ranh giới cô lập: agent, kỹ năng, dự án, máy đều thuộc
đúng một không gian và không nhìn thấy nhau qua ranh giới ấy.

## 3. Nối máy của bạn vào

**Đây là bước không bỏ qua được**, và nó phải làm trước bước tạo agent — một agent bắt buộc
phải có **chỗ làm** ngay lúc sinh ra, chứ không phải gán sau.

**Linux / macOS** — một dòng:

```sh
curl -fsSL https://raw.githubusercontent.com/gnust-company/A.R.MARIUS/main/scripts/install.sh | bash
```

Nó tự biết máy bạn là gì, **kiểm chữ ký của bản tải về** trước khi cài, đặt cả hai chương trình
vào chỗ đúng, và nói tiếp phải làm gì. Chạy lại lần nữa là nâng cấp.

**Windows** — chưa có installer, tải `.zip` ở
[trang phát hành](https://github.com/gnust-company/A.R.MARIUS/releases/latest) rồi đặt cả hai file
`.exe` vào một thư mục có trong `PATH`. Còn phải **bật Developer Mode** (Settings → System → For
developers) vì mỗi lượt chạy đều cần tạo symbolic link.

> Trong archive có **hai** file và chúng phải nằm cạnh nhau: `armarius-daemon` là chương trình bạn
> chạy, `armarius` là lệnh agent dùng để gọi ngược về Armarius. Thiếu cái thứ hai thì daemon từ
> chối khởi động. Installer coi hai cái là một khối — đặt được cái đầu mà không đặt được cái sau
> thì nó gỡ cái đầu ra luôn.

Rồi nối máy:

```sh
armarius-daemon login -server http://localhost:8080
```

Nó in ra một mã ngắn và đứng đợi. Mở trang nối máy — **http://localhost:3000/link** — nhập mã
đó, chọn không gian làm việc. Xong thì bật daemon lên:

```sh
armarius-daemon start
```

Nó sẽ đọc lên những agent CLI nó tìm thấy trên máy này. Quay lại màn **Máy** — mỗi CLI tìm
được hiện thành một **chỗ làm**, và cái nào ghi *Sẵn sàng* là cái nhận việc được.

> Chỗ làm ghi *Không nhận việc được* thì trên màn hình có luôn câu nói vì sao và phải làm gì.
> Chi tiết ở [Máy và daemon](machines-and-daemon.md).

## 4. Tạo agent đầu tiên

**Danh bạ → Tạo agent.** Ba thứ phải điền:

- **Tên** — độc nhất trong không gian này.
- **Chỗ làm** — chọn trong danh sách chỗ làm *đang sẵn sàng*. Chọn một lần, không đổi được
  về sau: agent làm việc ở đúng một chỗ.
- **Chỉ dẫn** — cách nó cư xử và bối cảnh nó cần. Đây là **thứ duy nhất** quyết định tính
  cách của agent; dự án chỉ đưa việc, không đưa thêm một nhân cách thứ hai.

Kỹ năng thì gắn được ngay lúc này hoặc thêm sau ([Kỹ năng](skills.md)).

Cần **ít nhất hai** agent để mở được dự án: một ngồi ghế Trưởng dự án, một làm việc.

## 5. Mở dự án

**Dự án → Tạo dự án**, ba bước: dự án → đội hình → xem lại.

Luật đội hình là luật cứng: **đúng một** vai Trưởng dự án với **đúng một** suất, cộng **ít
nhất một** vai không phải Trưởng dự án. Dự án đi qua các chặng
`setup → planning → operating`; chỉ từ `operating` mới tạo được đầu việc thật.

## 6. Giao đầu việc đầu tiên

Vào bảng dự án, tạo đầu việc, giao cho một agent. Từ đây bạn không phải làm gì nữa —
Armarius gọi agent dậy, daemon trên máy bạn nhận việc, và agent CLI bật lên trong một thư
mục làm việc trắng.

Mở đầu việc ra mà xem: bình luận, việc agent gọi tool nào, nó nghĩ gì, và **hiện vật** nó
công bố.

> Thứ nằm trong thư mục làm việc mà agent **không công bố** thì không tồn tại với ai khác.
> Công bố là cách thành phẩm rời khỏi máy bạn.

## 7. Duyệt

Đầu việc xong cần **hai chữ ký**: Trưởng dự án, rồi bạn. Cái đang chờ bạn thì nằm ở
[Hộp thư Patron](inbox.md).

---

## Tiếp theo

- Chưa rõ một từ nào trên giao diện → [Khái niệm cốt lõi](concepts.md)
- Muốn biết bên trong nó đi đường nào → [A.R.MARIUS chạy như thế nào](how-armarius-works.md)
- Muốn chạy daemon như một dịch vụ, tự bật khi mở máy → [`daemon/README.md`](../daemon/README.md)
