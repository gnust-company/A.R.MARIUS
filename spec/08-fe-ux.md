# 08 — Kiến trúc thông tin & màn hình giao diện (Frontend)

> Bản đồ màn hình và luồng đi của web app. Phản ánh code `frontend/` ngày 18/07/2026.
> **Thay thế** `docs/FE_UX.md` cũ (mô tả thời còn dữ liệu giả/MOCK).
>
> Nhãn: **[ĐÚNG-NHƯ-CODE]** trừ khi ghi khác.

---

## 1. Nền tảng kỹ thuật  [ĐÚNG-NHƯ-CODE]

- **React 19.2 + Vite 7 + TypeScript**, định tuyến bằng **react-router 7**, style bằng **Tailwind 3.4**
  (kèm bộ component kiểu shadcn trong `src/components/ui/`, và `Modal` tự viết cho logic nghiệp vụ).
- **Chat với Leader dựng trên `@assistant-ui/react`** (không "vẽ lại bánh xe"); composer tự viết cho logic
  miền.
- **Chạy hoàn toàn trên API thật** — không còn dữ liệu giả. Tên `useMockStore`/`mockStore.ts` **chỉ là tên
  cũ giữ lại**, không còn cơ chế mock/`VITE_MOCK`/`isMock` (đã gỡ). **[ĐÍCH-CẦN-SỬA] nhẹ:** đổi tên
  `mockStore`/`useMockStore` cho khỏi gây hiểu nhầm (dọn khi tiện, Giai đoạn 2).
- **Thẩm mỹ "Scriptorium"** — nền giấy da/gỗ ấm (ví dụ `#1a1410`), có `VellumPanel`, `DropCap` (chữ cái đầu
  trang trí) tạo cảm giác bản thảo chép tay.

---

## 2. Kiến trúc thông tin (định tuyến URL)  [ĐÚNG-NHƯ-CODE]

Ba tầng URL:

### 2.1 Ngoài workspace

| Đường dẫn | Màn hình | Ghi chú |
|---|---|---|
| `/` | `Landing` | trang giới thiệu cuộn phim (mặc định) |
| `/login` | `Login` | đăng nhập / đăng ký |
| `/workspaces` | `Workspaces` | bệ phóng chọn workspace (không có sidebar) |

### 2.2 Trong workspace — `/w/:workspaceId/*` (bọc bởi `Layout` + `Sidebar`)

Mọi trang trong workspace **mang `workspaceId` trên URL** để refresh cứng khôi phục đúng workspace + kỹ năng
của nó. Dựng link bằng `wsHref()`.

| Đường dẫn (dưới `/w/:workspaceId/`) | Màn hình | Việc |
|---|---|---|
| `projects` | `Projects` | danh sách dự án (thẻ dự án kèm số ghế đã lấp) |
| `projects/new` | `CreateProject` | tạo dự án + roster |
| `projects/:id` | `ProjectBoard` | **bảng công việc (kanban)** của dự án; nút "+" thêm task theo cột |
| `projects/:id/roster` | `Roster` | roster: role + ghế + agent ngồi ghế (kèm liveness) |
| `agents` · `agents/:id` | `Directory` · `AgentDetail` | danh bạ agent workspace + chi tiết + **mời agent** |
| `skills` · `skills/:id` | `Skills` · `SkillEditor` | Skill Shop + soạn kỹ năng |
| `inbox` | `Inbox` | hộp thư/nhắc việc |
| `account` | `Account` | tài khoản |
| `tasks/:id` | `CollaborationRoom` | **phòng cộng tác** của một task: thread, @mention, hiện vật, trace |

### 2.3 Đường dẫn cũ đã nghỉ (#82)  [ĐÚNG-NHƯ-CODE]

`projects/:id/commission` và `projects/:id/leader-chat` **chuyển hướng** về bảng dự án. Commission (tab
riêng) đã bỏ; Chat với Leader chuyển thành **bong bóng nổi** (§3).

---

## 3. Chat với Leader = bong bóng nổi (chỉ cấp dự án)  [ĐÚNG-NHƯ-CODE]

`components/LeaderChatWidget.tsx` (+ `LeaderChatPanel.tsx`). UX cuối cùng (#82):

- **Bong bóng nổi góc dưới-phải**, **chỉ xuất hiện ở cấp dự án** — gắn trên `ProjectBoard`
  (`{projectId && <LeaderChatWidget projectId={projectId} />}`). Không có ở cấp workspace.
- Bấm mở một **panel lớn**. Dựng trên `@assistant-ui/react` (markdown + chạy chữ streaming).
- Bám kênh SSE `leader-chat:{project_id}`: tin Patron, câu trả lời Leader chạy chữ, và trạng thái
  `idle`/`thinking`/`failed` (khoá ô nhập khi `thinking`). Leader offline ⇒ chat bị vô hiệu (xem
  [05-task-leaderchat.md](05-task-leaderchat.md) §3).
- (Dock kiểu VS Code từng thử rồi **bỏ**; chốt phương án bong bóng.)

---

## 4. Nguyên tắc giao diện  [ĐÚNG-NHƯ-CODE]

- **Đẩy, không hỏi-vòng:** các màn hình trực tiếp (board, phòng cộng tác, chat Leader, danh bạ liveness) bám
  SSE (`src/lib/sse.ts`) với nối lại `Last-Event-ID`, không hỏi-vòng.
- **Tiếng Việt đủ dấu:** mọi chuỗi hiển thị qua cơ chế i18n (`i18n/{vi,en}.ts`); tiếng Việt phải đủ dấu (ASCII
  không dấu bị coi là lỗi). Xem quy ước ở bộ nhớ dự án.
- **Liveness hiển thị realtime:** thẻ agent/ghế đổi màu theo trạng thái sống/chết đẩy từ `ws:{workspace_id}`.

---

## 5. Tiêu chí nghiệm thu

**Đúng-như-code:**

1. Refresh cứng ở bất kỳ trang trong workspace ⇒ khôi phục đúng workspace (nhờ `workspaceId` trên URL).
2. Bong bóng Chat với Leader **chỉ** thấy khi đang ở một dự án (`projects/:id`), không thấy ở cấp workspace.
3. Mở đường dẫn cũ `.../commission` hoặc `.../leader-chat` ⇒ tự chuyển về bảng dự án.
4. Câu trả lời Leader chạy chữ trong panel; khi `thinking` ô nhập bị khoá; Leader offline ⇒ chat vô hiệu.
5. Không còn nhánh mã mock nào chạy (mọi dữ liệu đến từ API thật).

**Đích Giai đoạn 2:** đổi tên `mockStore`/`useMockStore`; gỡ mã giao diện liên quan commission còn sót (nếu có).
