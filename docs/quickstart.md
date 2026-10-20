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

## 2. Bốn bước đầu

Đăng nhập lần đầu, Armarius dẫn bạn qua **bốn bước**, mỗi bước một màn: *về bạn*, *không gian làm
việc*, *nối máy*, *agent đầu tiên*. Bỏ dở giữa chừng thì lần sau vào lại đúng bước đang dở, kể cả
khi mở ở máy khác. Đi xong rồi thì không gặp lại nữa.

Hai bước đầu hỏi tên hiển thị của bạn và tên cho **không gian làm việc** (**workspace**) đã được tạo
sẵn lúc đăng ký. Không gian làm việc là ranh giới cô lập: agent, kỹ năng, dự án, máy đều thuộc đúng
một không gian và không nhìn thấy nhau qua ranh giới ấy.

Hai bước sau là mục 3 và mục 4 dưới đây. Màn hình đưa sẵn từng lệnh để chép, nên bạn chỉ cần đọc
tiếp ở đây khi muốn biết lệnh ấy làm gì.

## 3. Nối máy của bạn vào

Agent chạy trên máy của bạn, không phải máy của Armarius, nên phải có một máy được nối vào trước khi
có agent nào chạy được. Bước *nối máy* có ba phần — **cài**, **nối**, **chạy** — và tự đánh dấu xong
từng phần khi hệ thống thấy nó xong, không cần tải lại trang. Phần *chạy* xong thì màn hình tự sang
bước *agent đầu tiên*.

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
armarius-daemon login -server http://localhost:3000
```

> **Đưa cho nó đúng địa chỉ bạn mở Armarius** — ở đây là `:3000`. Trang web phục vụ luôn cả API
> bên dưới cùng một origin, nên một địa chỉ đủ cho cả hai việc.
>
> **Đừng đưa cổng API (`:8080`).** Nó trả lời API được, nhưng **không phục vụ trang phê duyệt**:
> daemon sẽ mở `http://localhost:8080/link?code=…` và bạn nhận về một trang 404. Cổng ấy không có
> giao diện, chỉ có cửa API.

Nó **tự mở trang phê duyệt** ra, với mã đã nằm sẵn trên địa chỉ — bạn chỉ cần nhìn tên máy, chọn
không gian làm việc rồi bấm **Đồng ý**. Không phải chép mã đi đâu cả.

Trang phê duyệt mở trong **một cửa sổ khác**. Duyệt xong thì cửa sổ onboarding tự đánh dấu xong phần
*nối* và chỉ sang phần *chạy*. Duyệt máy **chưa** phải là xong: lúc ấy máy mới có giấy tờ, chưa có
runtime nào.

> Còn bước bấm đồng ý thì **không** bỏ, và đó là chủ ý: một mã lộ ra — trong log, trong ảnh chụp
> màn hình, trong một tin nhắn — mà tự vào được thì là một máy lạ vào thẳng không gian làm việc
> của bạn. Trang ấy hiện tên máy đang hỏi để bạn nhận ra nó, và chỉ có thế.

**Máy không có desktop** — server nối qua SSH, container, máy không màn hình — thì không có gì mở
được, nên daemon in địa chỉ với mã ra và bạn mở nó ở bất cứ máy nào khác. Muốn thế kể cả khi có
desktop thì thêm `-no-browser` (hoặc đặt `ARMARIUS_NO_BROWSER=1`).

Xong thì bật daemon lên:

```sh
armarius-daemon start
```

**Đừng bỏ bước này.** `login` chỉ *nối* máy; `start` mới là thứ **dò agent CLI và khai chúng
thành runtime**. Nối mà không chạy `start` thì màn Máy hiện máy của bạn mà không có runtime nào,
và không agent nào tạo được.

Nó sẽ đọc lên những agent CLI nó tìm thấy trên máy này, và báo chúng lên thành **runtime**. Cửa
sổ onboarding nghe thấy và tự sang bước *agent đầu tiên*. Ngoài onboarding, mỗi runtime hiện ở màn
**Máy**, và cái nào ghi *Sẵn sàng* là cái nhận việc được.

`start` **chạy nền liên tục** — Ctrl-C là tắt, và tắt thì các runtime chuyển sang *Daemon trên máy
này đã tắt*. Muốn nó tự bật khi mở máy thì xem mục *Running it as a service* trong
[`daemon/README.md`](../daemon/README.md).

> Một runtime ghi *Không nhận việc được* thì trên màn hình có luôn câu nói vì sao và phải làm gì.
> Chi tiết ở [Máy và daemon](machines-and-daemon.md).

## 4. Agent đầu tiên: người chủ nhà

Mỗi không gian làm việc có sẵn một agent tên **Livia**, gọi là **người chủ nhà**. Nó giúp bạn dựng
dự án và chọn agent để thuê. Bước *agent đầu tiên* không tạo agent mới, mà dựng Livia lên. Bước này
hiện bốn thứ:

- **Tên** của nó.
- **System prompt** — phần chữ Armarius viết, làm nên một người chủ nhà. Nó hiện nguyên văn bằng
  tiếng Anh, vì đó đúng là thứ agent nhận. Bạn đọc được, nhưng không sửa và không xoá được.
- **Chỉ dẫn** — có sẵn một chỉ dẫn mặc định, bạn sửa thoải mái, xoá trắng cũng được. Viết thứ tiếng
  nào cũng được. Chữ trong ô lúc bạn bấm xong là chữ được lưu, và về sau sửa tiếp ở trang của agent.
  Đây là **thứ duy nhất** của bạn quyết định tính cách của agent: dự án chỉ đưa việc, không đưa thêm
  một nhân cách thứ hai.
- **Runtime** — danh sách runtime đang sẵn sàng, mỗi dòng có loại agent CLI và tên máy. Có đúng một
  runtime thì nó được chọn sẵn. Có từ hai trở lên thì bạn phải chọn, Armarius không chọn hộ. Runtime
  chưa sẵn sàng vẫn hiện, kèm lý do, nhưng không chọn được.

Bấm xong thì Livia được đặt vào runtime ấy, Armarius kiểm ngay xem nó sống chưa, và đưa bạn tới trang
của nó, nơi có khung nhắn tin với nó.

> **Runtime chọn một lần là xong.** Agent làm việc ở đúng một chỗ, suốt đời. Runtime ấy tắt thì
> agent ngoại tuyến, Armarius không tự chuyển nó sang máy khác.

Bước này không có danh sách kỹ năng nào. Mọi agent đều tự mang sẵn những kỹ năng để làm việc được với
Armarius, và chúng không hiện ở đâu cả ([Kỹ năng](skills.md)).

**Bỏ qua bước này** — hoặc bỏ qua cả bước nối máy — cũng được. Livia ở lại với lý do *chưa được chọn
runtime*, và trang của nó có sẵn chỗ chọn runtime cho nó, bất cứ lúc nào
([Agent](agents.md#người-chủ-nhà-chưa-có-runtime)).

Cần **ít nhất hai** agent để mở được dự án: một ngồi ghế Trưởng dự án, một làm việc. Agent thứ hai
trở đi thì tạo ở **Danh bạ → Tạo agent**: tên, runtime, chỉ dẫn, và kỹ năng nếu muốn.

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
