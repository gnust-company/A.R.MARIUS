# Research: Onboarding dạy từ thêm máy tới agent đầu tiên (sửa 2026-10-12)

**Đặc tả**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)

Mỗi mục ghi: quyết định, lý do, và những cách đã cân nhắc rồi bỏ. Không còn mục nào chờ chốt.

---

## R1 — Chỉ dẫn mặc định nằm ở đâu

**Quyết định**: người chủ nhà được tạo ra **với sẵn chỉ dẫn mặc định trong chính trường `instructions`**
của nó, tức phần của người dùng. System prompt vẫn ở `system_instructions` như hôm nay. Bước *agent đầu
tiên* chỉ việc đọc `instructions` của Livia ra ô, cho sửa, rồi lưu lại khi bấm xong.

**Lý do**:
- Chỉ có **một nguồn** cho chữ mặc định: hằng số ở backend, cạnh system prompt. Giao diện không giữ bản
  chép nào, nên hai bản không thể lệch nhau (Hiến pháp Điều V).
- Chữ ấy gửi cho agent nên phải bằng tiếng Anh (Điều VII), và backend đã là nơi giữ mọi chữ gửi cho
  agent.
- Không cần mở thêm cửa nào chỉ để hỏi *chữ mặc định là gì*: Livia đã mang sẵn nó.
- Không gian làm việc thứ hai trở đi cũng có cùng chỉ dẫn mặc định, nên trang agent hiện đúng thứ bước
  onboarding sẽ hiện.

**Đã bỏ**:
- *Giao diện tự giữ chữ mặc định*: thành hai nguồn, và là chữ gửi agent nằm ngoài backend.
- *Một cửa trả về chữ mặc định*: thêm một cửa cho một giá trị Livia đã mang sẵn.

**Livia đã có từ trước**: không sửa. Phần `instructions` của chúng đang rỗng và là của người dùng. Những
tài khoản ấy đã đi xong onboarding nên không gặp bước này.

**Bản nháp chữ mặc định** (người chủ duyệt trong PR docs):

```text
Reply in the language the owner writes to you in. Keep answers short and concrete. When something is
unclear, ask one question at a time instead of guessing. Before suggesting which agents to hire, ask
what the owner is trying to get done.
```

Bản nháp này cố ý **không** nhắc lại việc của người chủ nhà, vì việc ấy đã nằm trong system prompt. Nó
chỉ nói *cách* trò chuyện, đúng phần người dùng nên được tự quyết.

---

## R2 — Cửa đặt chỗ cho người chủ nhà

**Quyết định**: một cửa **chỉ dành cho người chủ nhà**:
`POST /v1/workspaces/{workspace_id}/mariuses/{marius_id}/placement`. Body gồm `workplace_id` (bắt buộc) và
`instructions` (tuỳ chọn). Use case là `WorkspaceAgentService.place_host`, viết lại: không còn tự chọn
nữa mà nhận đúng chỗ làm người dùng chọn.

**Vì sao chỉ người chủ nhà, không phải mọi agent chưa có chỗ làm**: gỡ một máy khỏi workspace thì mọi
agent trên máy ấy **mất chỗ làm** (`infrastructure/daemon/cleanup.py`: *"Agents that lived here become
unplaced, not deleted"*). Nếu cửa này nhận mọi agent chưa có chỗ làm, thì nó thành đường đặt lại chỗ cho
agent thường, tức là lén nới FR-007. Người chủ đã chốt FR-007 là *"tạm giữ nguyên không đổi được"*.
Người chủ nhà khác ở chỗ nó là agent duy nhất **được sinh ra** mà chưa có chỗ làm (FR-114), và không gian
làm việc cần nó để dựng dự án bằng hỏi–đáp. Agent không giữ ghế chủ nhà thì cửa trả **409
`placement_is_fixed`**.

**Người chủ nhà mất chỗ làm vì máy bị gỡ** thì lại được chọn runtime qua cửa này. Việc ấy không phải
*chuyển* chỗ, vì dòng gắn cũ đã không còn. Spec có thêm một edge case cho điều này.

**Các luật khác**:
- Đi kèm `instructions` để **lưu cùng một lần** (FR-126 ý 1): không có trạng thái chỉ dẫn đã lưu mà chưa
  có runtime.
- Người chủ nhà đã có chỗ làm thì trả **409 `agent_already_placed`**. Câu trả lời kèm runtime nó đang ở,
  do tầng presentation tra ra (Điều III), để cửa sổ tới sau nói được *Livia đã chạy trên claude ở máy X*
  (FR-127).
- Chỗ làm không thuộc workspace thì trả 404 (Điều I). Chỗ làm chưa sẵn sàng hoặc không còn nhận việc thì
  trả **400 `placement_not_ready`** (FR-125, edge case *runtime tắt trước khi bấm xong*). Cả hai
  mã `placement_not_found` và `placement_not_ready` dùng lại đúng mã mà cửa tạo agent đã trả, nên
  màn hình đã có câu cho chúng.
- Xong việc thì gọi `liveness.placement_changed([id])`, cửa có sẵn từ FR-006e, để kiểm agent ngay.

**Chống đua**: bảng gắn agent với chỗ làm đã ràng buộc **mỗi agent một dòng**. Yêu cầu tới sau đụng
`Conflict` khi ghi, và câu trả lời là đúng 409 `agent_already_placed`, giống cách `place_host` hôm nay xử
lý hai máy cùng đồng bộ.

**Đã bỏ**:
- *Cửa chung cho mọi agent chưa có chỗ làm*: mở FR-007 cho agent thường, như trên.
- *Hai lần gọi* (PATCH chỉ dẫn rồi mới đặt chỗ): sinh đúng trạng thái lưng chừng mà FR-126 cấm.
- *Dùng `PATCH .../mariuses/{id}` với `adapter_type`*: cửa sửa agent không được đổi chỗ làm (FR-007).

---

## R3 — Bỏ tự đặt chỗ

**Quyết định**: xoá `WorkspaceAgentService.place_host` và lời gọi nó trong `sync_workplaces`
(`presentation/api/daemon.py`). Các bài kiểm của T003 về tự đặt chỗ đổi thành bài kiểm khẳng định điều
ngược lại: máy báo runtime **không** làm người chủ nhà có chỗ làm.

**Lý do**: người chủ chốt Q1 = A (2026-10-12). Không tự đặt ở đâu cả, kể cả khi chỉ có một runtime.

**Đã bỏ**: giữ tự đặt khi chỉ có một runtime. Người chủ đã chốt không.

---

## R4 — Đẩy tin cho bước *nối máy*

**Quyết định**:
- Giữ `machine.linked` (có sẵn, phát lúc duyệt máy) cho phần *nối*.
- Thêm `machine.workplaces_reported`, phát mỗi lần một máy đồng bộ danh sách runtime của nó, kể cả lần
  báo `stopping`. Tên đặt ở `infrastructure/events/workspace_trace.py`, cạnh `machine.linked`, vì chữ
  `machine` không được có mặt ở tầng nghiệp vụ (Điều III).
- Payload chỉ có `{"workspace_id"}`: sự kiện là **tín hiệu**, không phải trạng thái (nguyên tắc 1 của
  [push-events.md](../001-van-hanh-du-an/contracts/push-events.md)). Ai nhận thì tự đọc lại.

**Lý do**: daemon chỉ đồng bộ danh sách runtime lúc chạy lên và lúc dừng (`main.go`). Phát mỗi lần đồng
bộ là hai sự kiện cho một vòng đời daemon, không cần lọc gì thêm. Lần báo `stopping` cũng phải phát, vì
danh sách ở bước *agent đầu tiên* phải mất dòng runtime vừa đóng.

**Đã bỏ**:
- *Hỏi vòng*: Điều IV cấm.
- *Dựa vào `marius.online`*: sự kiện ấy chỉ có sau khi đã có agent được đặt chỗ, tức là sau bước này.

---

## R5 — Bước *nối máy* biết mình đang ở đâu

**Quyết định**: trạng thái ba phần lấy từ **dữ liệu trên server**, không lấy từ trí nhớ của tab:
- *nối* xong khi workspace có ít nhất một máy, hoặc tab đã nghe thấy `machine.linked`. Vế sau cần vì từ
  lúc duyệt tới lúc daemon đổi mã lấy giấy tờ mất vài giây, và trong lúc ấy chưa có dòng máy nào;
- *chạy* xong khi có ít nhất một máy đã báo ít nhất một runtime, sẵn sàng hay chưa đều tính.

Mở trang ở bước này thì đọc ngay danh sách máy. Nếu *chạy* đã xong thì sang luôn bước *agent đầu tiên*
(FR-121). Nghe thấy một trong hai sự kiện ở R4 thì đọc lại.

**Lý do**: tải lại trang, hay mở ở máy khác, đều phải ra cùng một chỗ (FR-104).

---

## R6 — Trạng thái onboarding có bốn bước

**Quyết định**:
- `onboarding_step` nhận giá trị 0–4, thay cho 0–3. Chỉ đổi phần kiểm ở `PATCH /auth/me` (`le=4`), cột
  không đổi. `onboarded_at` vẫn là toàn bộ nghĩa của *đã xong*.
- **Duyệt máy không còn đánh dấu xong.** `LinkMachine.tsx` thôi gửi `onboarding_done: true`, và nói tiếp
  lệnh `start` cùng chuyện cửa sổ onboarding đang đợi ở bước sau (FR-106).
- Bấm xong hoặc bỏ qua ở bước bốn thì gửi `onboarding_step: 4, onboarding_done: true`.

**Người đang dở dang lúc triển khai**: người chưa xong và đang ở bước 0–2 thì đi tiếp vào luồng bốn bước,
không cần migration. Người đã xong thì giữ nguyên (Assumption cuối của spec).

---

## R7 — Ẩn skill mặc định

**Quyết định**:
1. `GET /v1/workspaces/{ws}/skills` **không trả** skill có `source == "builtin"`. Đây là cửa cho người
   xem, nên lọc ở đây là đủ cho mọi màn đang và sẽ có: thư viện skill, màn tạo agent, tab skill của
   agent.
2. Migration dữ liệu xoá id của skill dựng sẵn khỏi `mariuses.skill_ids` và tên của chúng khỏi
   `mariuses.skills`. Một số agent có id ấy vì người dùng từng bấm chọn chip trước ngày 2026-09-06.
3. Các cửa ghi (tạo agent, sửa agent, cài skill cho agent) **lẳng lặng bỏ** id của skill dựng sẵn thay
   vì từ chối. Client cũ gửi lên thì cũng không sai gì, chỉ là thừa.
4. Giao diện bỏ tab *Tích hợp sẵn* ở trang Skills và bỏ nhánh chip *luôn bật* ở màn tạo agent.
5. Phía agent **không đổi**: `wake_engine` vẫn gắn skill dựng sẵn vào mọi lượt chạy qua `builtins_for`,
   và vẫn khử trùng theo id.

**Lý do**: người chủ chốt *ẩn hết* (2026-10-12). Bỏ id khỏi `skill_ids` không đổi gì với agent, vì skill
dựng sẵn vẫn tới mọi lượt chạy theo đường riêng của nó. Docstring của `wake_engine` ghi đúng điều này.

**Đã bỏ**:
- *Chỉ lọc ở giao diện*: màn mới nào quên lọc là lộ lại. Lọc ở cửa thì không màn nào phải nhớ.
- *Từ chối id dựng sẵn bằng 400*: bắt client trả giá vì một thứ nó không còn thấy.

---

## R8 — Hiện system prompt và chỉ dẫn mặc định theo Điều VI và VII

**Quyết định**: bước *agent đầu tiên* và trang agent hiện system prompt **nguyên văn tiếng Anh**, đặt
trong một khung có tiêu đề và một dòng giải thích đi qua i18n. Ví dụ bản tiếng Việt: *"Phần này do
Armarius viết, gửi nguyên văn cho agent, không sửa được."* Chỉ dẫn mặc định cũng là tiếng Anh, làm giá
trị khởi đầu của ô chỉ dẫn, kèm một dòng i18n nói rằng người dùng viết thứ tiếng nào cũng được.

**Căn cứ**: Hiến pháp **2.1.0**, *Ngoại lệ: hiện nguyên văn cái agent nhận* của Điều VII. Người chủ chốt
ngày 2026-10-12, sau khi `/speckit-analyze` chỉ ra rằng bản trước của mục này đã **diễn giải lại** hệ quả
của Điều VII, trong khi Hiến pháp không cho diễn giải lại (mã C1, C2). Cách sửa là sửa Hiến pháp, không
phải viết lại lý lẽ. Cả hai chữ đều đủ ba điều kiện của ngoại lệ:
1. System prompt chỉ để đọc. Chỉ dẫn mặc định là giá trị khởi đầu của một ô người dùng sửa được.
2. Tiêu đề, dòng giải thích và nút đi qua i18n.
3. Không chữ nào là câu báo, lý do hay trạng thái.

Trang agent hôm nay (`InstructionsTab.tsx`) đã hiện system prompt đúng cách này. Bước onboarding dùng lại
đúng khối ấy, và thêm dòng giải thích nếu khối ấy chưa có.

**Đã bỏ**: lưu system prompt thành mã rồi dịch cho màn hình. Đó là phương án (a) lúc chốt, và người chủ
không chọn: nó dựng bản chép thứ hai của đúng thứ người dùng muốn xem.

---

## R9 — Bấm xong thì đi đâu

**Quyết định**: theo thứ tự, (1) gọi cửa đặt chỗ ở R2, (2) `PATCH /auth/me` đánh dấu xong, (3) chuyển
tới `/w/:workspaceId/agents/:hostId`. Tab *overview* của trang này có sẵn khung nhắn tin với agent (FR-007p
của 002).

Bước (2) lỗi thì người dùng bấm lại. Bước (1) lúc ấy trả 409 `agent_already_placed`, và giao diện coi đó
là đã xong rồi đi tiếp. Nhờ vậy cả chuỗi chạy lại được mà không sinh gì thừa.

Bỏ qua ở bước bốn thì chỉ làm (2), rồi về trang dự án như hôm nay. Livia ở lại trạng thái chưa có chỗ
làm, và trang của nó có đường chọn (FR-128).

---

## R10 — Thử trong môi trường này

**Quyết định**: kịch bản *hai runtime* dùng **một daemon thật chỉ thấy `claude`**, cộng **một máy giả
lập bằng script**. Máy giả đi qua đúng luồng link và approve, rồi tự báo `PUT /daemon/workplaces` với một
loại CLI thứ hai. Không có binary nào khác được chạy.

**Lý do**: không chạy `gemini` hay `codex` ở môi trường này, kể cả để dò (người chủ đã nhắc ba lần). Báo
danh sách runtime chỉ là một lời khai qua HTTP, đúng cách bộ kiểm hiện có đang dùng
(`link_machine_to`), và đủ để kiểm danh sách chọn, luật chọn sẵn, và việc không tự đặt chỗ.
