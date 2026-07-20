# 04 — Sống/chết của agent (liveness)

> Armarius **tự sở hữu** việc xác định một agent còn sống hay không — không phụ thuộc heartbeat của runtime
> ngoài (đây là điểm yếu của sản phẩm tham chiếu, xem [00-intent.md](00-intent.md) §4).

---

## 1. Mô hình: "tín hiệu thiết lập, sức khoẻ gateway duy trì"

Không có điểm cuối heartbeat. Hai lực giữ một agent ở trạng thái ONLINE:

- **Tín hiệu (signal) — *thiết lập* sự hiện diện.** Bất kỳ liên lạc thật nào từ agent: gọi `GET /agent/me`,
  trả lời một task, hay gateway đáp một lượt chạy. Mọi tín hiệu đi qua `LivenessEngine.record_signal` ⇒
  đặt ONLINE và **reset** toàn bộ đồng hồ probe/backoff.
- **Sức khoẻ gateway — *duy trì* sự hiện diện qua khoảng lặng.** Khi agent im quá ngưỡng T1, engine bắn
  **một** probe *rẻ* tới **gateway** của agent (`adapter.test_environment(adapter_config)` — thử
  `/v1/capabilities` → `/healthz` → `/health`), **không** đánh thức agent (không tốn token LLM). Gateway
  khoẻ = bằng chứng rẻ "agent vẫn tới được", giữ agent ONLINE thay vì rớt OFFLINE oan.

**Điểm cốt lõi (khác với "probe = ping agent"):** probe **hỏi gateway**, không hỏi agent. Đánh đổi được
chấp nhận: gateway khoẻ chỉ chứng minh *gateway* sống, chưa chắc đúng agent đó sống; một lần wake-task thật
thất bại sẽ sửa lại trạng thái ngoài luồng. `GatewayHealthLivenessProbe` còn **gộp cache** các probe cùng
gateway trong ~15s, nên N agent sau một Hermes chỉ tốn một cuộc gọi sức khoẻ/chu kỳ.

---

## 2. Máy trạng thái

Lõi thuần: `domain/services/liveness_fsm.py`. Bao ngoài (đồng hồ + I/O + lưu): `application/use_cases/liveness.py::LivenessEngine`.

```
ONLINE ──im quá T1──► CHECKING ──probe gateway──► (đáp) ONLINE
                          │
                    3 lần trượt (cách nhau ~T2)
                          ▼
OFFLINE ──chờ R, rồi 2R, 4R… (trần)──► CHECKING ──► …

WORKING ──lượt chạy quá hung_after──► HUNG ──(probe gateway khoẻ)──► ONLINE
```

Các trạng thái quan sát được (`Marius.liveness`):

| Trạng thái | Nghĩa |
|---|---|
| `ONLINE` | có tín hiệu gần đây |
| `WORKING` | đang chạy một lượt (bản thân lượt = tín hiệu; không probe khi đang chạy) |
| `CHECKING` | đã im quá T1, đang trong chu kỳ probe |
| `OFFLINE` | trượt đủ số lần; đang chờ backoff để probe lại |
| `HUNG` | lượt chạy treo quá `hung_after`; **không** phải ngõ cụt — chia chung đường hồi phục với OFFLINE |

### 2.1 Tham số (mặc định)

`LivenessConfig`: T1 (`idle_timeout`) = 90s; T2 (`probe_window`, cách giữa các probe) = 30s;
số lần trượt tối đa = 3; R (`retry_base`) = 60s; trần backoff (`retry_max`) = 30 phút; hệ số nhân = 2.0;
`hung_after` (ngưỡng treo lượt) = 20 phút.

### 2.2 Đồng hồ chạy nền

`LivenessWatchdog` là vòng lặp nền: mỗi `interval_seconds` (mặc định 30s) gọi `tick_all` → với **mọi
workspace**, `LivenessEngine.tick` đẩy **mọi Marius** đi một nhịp: lập kế hoạch → (nếu tới hạn) bắn probe →
gập kết quả lại. Giao dịch cơ sở dữ liệu **không** bị giữ mở trong lúc chờ probe.

### 2.3 Chuyển WORKING và finalise

- Khi WakeEngine (và LeaderChatService) bắt đầu một lượt ⇒ `begin_turn` đặt `WORKING`, ghi `turn_started_at`
  để watchdog đo "im lặng kể từ khi bắt đầu lượt" (stream đang chạy không bị báo HUNG oan).
- Liveness phản ánh **khả năng tới được**, không phải kết quả run: một run kết thúc (dù COMPLETED, FAILED
  hay TIMED_OUT) nghĩa là runtime đã đáp lại ⇒ agent **rảnh trở lại**. HUNG chỉ dành cho watchdog (lượt đi
  vào im lặng), không bao giờ do một status không-COMPLETED — nếu không, một task chỉ đơn giản fail sẽ kẹt
  agent "offline" mãi.

---

## 3. Điều kiện kích hoạt dự án dựa trên liveness

`all_seated_online` yêu cầu **mọi** agent ngồi ghế ở trạng thái **ONLINE** (đúng nghĩa `Liveness.ONLINE`,
không tính `WORKING`). Đây là cổng để dự án chuyển `setup → active` (xem [03-roster-wake.md](03-roster-wake.md) §1.3).

---

## 4. Trạng thái "rảnh giữa các lượt" — dùng lại `ONLINE`

Sau khi một lượt chạy kết thúc, `WakeEngine._finalise` đặt `marius.liveness = ONLINE` (`last_seen_at` vừa
được bump = một tín hiệu, nên đúng nghĩa online). Không có trạng thái "rảnh" riêng: "rảnh giữa các lượt"
chính là `ONLINE`, và được **duy trì bằng sức khoẻ gateway** qua nhánh `ONLINE` của watchdog (im quá T1 →
CHECKING → probe) như mọi trạng thái online khác. Với Chat với Leader, `_AVAILABLE` = `{ONLINE, WORKING,
CHECKING}`.

---

## 5. Tiêu chí nghiệm thu

1. Agent gọi `GET /agent/me` một lần ⇒ ONLINE, đồng hồ probe/backoff reset.
2. Agent im quá T1 mà gateway vẫn khoẻ ⇒ vẫn ONLINE (probe gateway đỡ), **không** rớt OFFLINE.
3. Gateway ngừng đáp đủ 3 lần cách ~T2 ⇒ agent OFFLINE; sau đó re-probe theo backoff R, 2R, 4R… trần 30 phút.
4. Lượt chạy treo quá 20 phút ⇒ HUNG, rồi một probe gateway khoẻ kéo về ONLINE (HUNG không phải ngõ cụt).
5. Probe **không** gửi prompt/không tốn token cho agent (chỉ gọi endpoint sức khoẻ gateway).
6. Một lượt chạy kết thúc (dù COMPLETED/FAILED/TIMED_OUT) ⇒ agent về **ONLINE**, và watchdog tiếp tục duy
   trì qua nhánh ONLINE.
