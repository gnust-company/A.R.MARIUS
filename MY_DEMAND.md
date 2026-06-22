## Giới thiệu về dự án:
### 1. Bối cảnh
- Hiên nay, xu thế sẽ là mỗi người or mỗi team sẽ sở hữu nhưng agent chuyên biệt như OpenClaw, Hermes hay Claude Code
- Công việc của họ đó là, nhận task từ các nền tảng (Jira/Linear/...), trao đổi với các bên liên quan, nhận task, lấy thông tin và prompt cho agent thực thi, bao giờ agent làm thấy oke thì họ sẽ action, update task và cứ thế vòng lặp cho từng task
- Chúng tôi nhận thấy đây là 1 pattern lặp đi lặp lại và ta có thể platform hóa nó!

### 2. Mong muốn
- Hy vọng có 1 nơi làm việc tập trung, nơi con người đóng vai trò giám sát, invite các agent của mình vào và chỉ việc giám sát => Approve, các agent tự động nhận task, đặt câu hỏi cho các bên liên quan, trả lời câu hỏi từ các bên.

## Các thử nghiệm:

### 1. Paperclip AI:
- Đã thử nghiệm với paperclip và thấy nó vô cùng sát với nhu cầu, tuy nhiên nó tồn tại một số điẻm yêu và không phù hợp với nhu cầu của ta:
  - Dành cho người có nhiều local agent, vì các adapter của họ chỉ support local agent, openclaw gateway thi vẫn đang dev nhưng nó không phải main
  - Bài toán khác nhau, của họ là dành cho người muốn vận hành cả 1 công ty, còn chúng tôi muốn sự collaboration giữa các team, điều đó dẫn đến các logic như là Thiết lập CEO, Goal,... là không cần thiết.
  - Các agent chưa biết về nhau, tôi thử nghiệm thì ông CEO tự tạo task xong làm luôn, phải mention và hỏi thì ông mới đi tìm member
  - Các agent cũng ai làm việc nấy không có sự trao đổi
  - Không có 1 workspace chung nhưng trong task có phần attachment, nhưng agent cũng không push kết quả của mình vào đó mà toàn tạo file ở local xong báo done task để con khác làm nhưng con khác cũng chả biết kết quả đó thể nào vì file ở local con kia
- Điểm thích:
  - Có thể mời OpenClaw agent vào, tôi có custom để enable cho phép mời OpenClaw Agent vào thì nó gen ra 1 prompt invite, agent sẽ follow theo để xin vào hệ thống, install skill và lưu token
  - Adapter cho từng loại agent, điều này giúp ta deal với các loại agent là như nhau, không phân biệt hay phải xử lý riêng biệt với Claude riêng, OpenClaw riêng

### 2. OpenClaw Mission Control
- Đây là một dự án dùng để quản lý các agent trên OpenClaw, tôi đã dùng thử và thấy có vài điểm không phù hợp: 
  - Chỉ dùng cho Openclaw, khó scale cho các loại agent khác
  - Bài tóan khác, tương tự như paperclip nhưng quy mô nhỏ hơn, quản lý theo tưng gateway, mỗi dự án 1 gateway để có thể dễ dàng tạo agent từ gateway agent và leaeder agent => không phải bài toán mình nhắm tới
  - không có workspace chung, agent thi vẫn có xu hương tạo file kết quả ở local, không ai biết cả =>cái này phải tùy chỉnh ở platform chứ không trách agent được
  - Phụ thuộc vào cơ chế Heartbeat của Openclaw chứ không phải của mình, dẫn đến hiện trạng 1 instance openclaw có quá nhiều agent và nó đang bị hang thì mình không kiểm soát được, nhiều khi cái heartbet của openclaw cũng không work vì 1 số nguyên nhân chả rõ
- Điểm thích:
  - Có 1 board chat chung trong project để chatting với các agent
  - Đơn giản, dễ dùng

## Next Step

### Ý tưởng hệ thống
- Bài toán của tôi như đã mô tả, đó là khi mà công tác với nhau thì ta sẽ mời các agent của mình vào hệ thông chung, nhưng tôi thực sự chưa có ý tưởng vì nó vừa to nhưng lại vừa đơn giản
- Ta cần phải brainstorming kỹ bài toán này

### Chắt lọc từ những thử nghiệm
- Việc mời và cài skill của PaperClip
- Adapter cho từng agent type (tôi đề cao Hermes và Openclaw trước, riêng Hermes phải xem xem có support gateway hay websocket không, tính khả thi của nó)
- Mối task là 1 session như PaperClip
- Onboarding dự án như Opencalw Mission Control nhưng không phải cho agent hỏi mà ta sẽ fix và control, kiểu như cần nhửng role nào, kỹ năng nào, thì khi agent tham gia ứng tuyển phải đáp ứng được điều đó mới được

### Chắt lọc Technique
- PaperClip Adapter cho OpenClaw Gateway và tôi muốn mình cũng có thể support cho cả Hermes Agent Gateway or Websocket thay vì mỗi local (cần check tính khả thi)
- Cách Paperclip tạo session cho mỗi task, làm sao họ làm được? Logic liên kết giữa task và các session của agent là gì?