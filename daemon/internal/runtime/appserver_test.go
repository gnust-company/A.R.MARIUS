package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// Bộ kiểm cho họ app-server — họ giao thức của Codex.
//
// Không lượt nào ở đây bật `codex` thật, và đó là lý do `Attend` tách khỏi `Run`: máy viết phần
// này không chạy nổi `codex` một lần nào (thiếu binary nền tảng), nên một giao thức chỉ kiểm được
// bằng cách chạy binary là một giao thức không ai kiểm. Hình dạng từng câu ở đây đọc từ chính
// nguồn của Codex — `codex-rs/app-server-protocol` và `codex-rs/app-server/README.md` — chứ không
// từ tài liệu mô tả lại.

// note is one thing the fake server says while a turn is running.
type note struct {
	method string
	params map[string]any
}

// fakeCodex is an app-server that says only what a test told it to say.
type fakeCodex struct {
	t *testing.T

	// Kịch bản.
	refuseBeforeInitialized bool
	refuseResume            bool
	threadID                string
	notes                   []note
	askMethod               string
	askParams               map[string]any
	turnStatus              string
	turnError               string
	usage                   map[string]any

	// Đo được.
	initialized  bool
	greeted      bool
	cwd          string
	prompt       string
	resumeAsked  string
	excludeTurns bool
	opened       int
	answerToAsk  json.RawMessage
	errorToAsk   *rpcError
}

func (a *fakeCodex) serve(from io.Reader, to io.Writer) {
	enc := json.NewEncoder(to)
	lines := bufio.NewScanner(from)
	lines.Buffer(make([]byte, 0, 8<<10), maxOutputLine)

	reply := func(id json.RawMessage, result any) {
		_ = enc.Encode(rpcMessage{JSONRPC: "2.0", ID: id, Result: mustRaw(result)})
	}
	refuse := func(id json.RawMessage, message string) {
		_ = enc.Encode(rpcMessage{JSONRPC: "2.0", ID: id, Error: &rpcError{Code: -32600, Message: message}})
	}
	notify := func(method string, params map[string]any) {
		_ = enc.Encode(rpcMessage{JSONRPC: "2.0", Method: method, Params: mustRaw(params)})
	}

	thread := a.threadID
	if thread == "" {
		thread = "thr_just_opened"
	}

	for lines.Scan() {
		var msg rpcMessage
		if json.Unmarshal(lines.Bytes(), &msg) != nil {
			continue
		}
		if msg.Method == "initialized" {
			a.initialized = true
			continue
		}
		if msg.Method != "initialize" && a.refuseBeforeInitialized && !a.initialized {
			refuse(msg.ID, "Not initialized")
			continue
		}

		switch msg.Method {
		case "initialize":
			a.greeted = true
			reply(msg.ID, map[string]any{"userAgent": "codex/0.0.0", "codexHome": "/nowhere"})

		case "thread/resume":
			var params struct {
				ThreadID     string `json:"threadId"`
				ExcludeTurns bool   `json:"excludeTurns"`
			}
			_ = json.Unmarshal(msg.Params, &params)
			a.resumeAsked, a.excludeTurns = params.ThreadID, params.ExcludeTurns
			if a.refuseResume {
				refuse(msg.ID, "no such thread")
				continue
			}
			reply(msg.ID, map[string]any{"thread": map[string]any{"id": params.ThreadID}})

		case "thread/start":
			var params struct {
				Cwd string `json:"cwd"`
			}
			_ = json.Unmarshal(msg.Params, &params)
			a.cwd, a.opened = params.Cwd, a.opened+1
			reply(msg.ID, map[string]any{"thread": map[string]any{"id": thread}})

		case "turn/start":
			var params struct {
				Input []struct {
					Text string `json:"text"`
				} `json:"input"`
			}
			_ = json.Unmarshal(msg.Params, &params)
			if len(params.Input) > 0 {
				a.prompt = params.Input[0].Text
			}
			// Trả lời trước, rồi mới làm việc — đó là chỗ họ này khác họ ACP.
			reply(msg.ID, map[string]any{"turn": map[string]any{"id": "turn_1", "status": "inProgress"}})

			for _, said := range a.notes {
				notify(said.method, said.params)
			}
			if a.askMethod != "" {
				params := a.askParams
				if params == nil {
					params = map[string]any{"threadId": thread, "turnId": "turn_1", "itemId": "it_1"}
				}
				_ = enc.Encode(rpcMessage{
					JSONRPC: "2.0",
					ID:      json.RawMessage("900"),
					Method:  a.askMethod,
					Params:  mustRaw(params),
				})
				if lines.Scan() {
					var answer rpcMessage
					if json.Unmarshal(lines.Bytes(), &answer) == nil {
						a.answerToAsk, a.errorToAsk = answer.Result, answer.Error
					}
				}
			}

			status := a.turnStatus
			if status == "" {
				status = "completed"
			}
			done := map[string]any{"id": "turn_1", "status": status}
			if a.turnError != "" {
				done["error"] = map[string]any{"message": a.turnError}
			}
			if a.usage != nil {
				done["usage"] = a.usage
			}
			notify("turn/completed", map[string]any{"threadId": thread, "turn": done})
		}
	}
}

func attend(t *testing.T, agent *fakeCodex, req Request) ([]Event, Outcome, error) {
	t.Helper()
	agent.t = t
	if req.CLI == "" {
		req.CLI = "a-codex-cli"
	}
	if req.WorkDir == "" {
		req.WorkDir = t.TempDir()
	}
	if req.Message == "" {
		req.Message = "Your instructions: be Marin.\n"
	}

	toAgentR, toAgentW := io.Pipe()
	fromAgentR, fromAgentW := io.Pipe()
	served := make(chan struct{})
	go func() {
		defer close(served)
		agent.serve(toAgentR, fromAgentW)
		_ = fromAgentW.Close()
	}()

	// Có hạn, và hạn ấy là một phần của bài kiểm. Lỗi nặng nhất của giao thức này là **treo** —
	// bên kia dừng lại chờ một câu trả lời không tới — nên một bài kiểm không có hạn sẽ báo đúng
	// cái lỗi ấy bằng cách chính nó treo, tức mười phút rồi mới có người biết.
	//
	// Hạn đặt bằng cách **đóng ống**, không bằng huỷ ngữ cảnh, vì huỷ ngữ cảnh không cắt được một
	// lượt đọc đang chờ. Ngoài đời chỗ ấy vẫn thông: ngữ cảnh giết tiến trình CLI, tiến trình chết
	// thì ống đóng, và bên đọc thôi chờ. Ở đây không có tiến trình nào, nên bài kiểm tự làm phần
	// việc ấy — đúng thứ supervisor làm, không phải một đường thoát của riêng bài kiểm.
	overdue := make(chan struct{})
	defer close(overdue)
	go func() {
		select {
		case <-overdue:
		case <-time.After(3 * time.Second):
			_ = fromAgentR.CloseWithError(errors.New("bên kia không trả lời"))
		}
	}()

	var events []Event
	out, err := Attend(context.Background(), toAgentW, fromAgentR, req, func(e Event) {
		events = append(events, e)
	})
	_ = toAgentW.Close()
	_ = fromAgentR.Close()
	<-served
	return events, out, err
}

func started(kind string, fields map[string]any) note {
	return note{method: "item/started", params: map[string]any{"item": merge(map[string]any{"type": kind}, fields)}}
}

func finished(kind string, fields map[string]any) note {
	return note{method: "item/completed", params: map[string]any{"item": merge(map[string]any{"type": kind}, fields)}}
}

func merge(into, from map[string]any) map[string]any {
	for key, value := range from {
		into[key] = value
	}
	return into
}

func TestATurnOpensAThreadInTheTasksDirectoryAndSaysWhatItWasGiven(t *testing.T) {
	agent := &fakeCodex{}
	work := t.TempDir()

	_, out, err := attend(t, agent, Request{WorkDir: work, Message: "the whole brief"})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}

	if agent.cwd != work {
		t.Fatalf("mở mạch ở %s, không phải thư mục của đầu việc %s", agent.cwd, work)
	}
	if agent.prompt != "the whole brief" {
		t.Fatalf("agent nhận được %q", agent.prompt)
	}
	if out.Session != "thr_just_opened" {
		t.Fatalf("mã mạch trả về là %q", out.Session)
	}
}

// Bắt tay là hai tin, không phải một: mọi câu khác trên đường nối ấy bị từ chối *Not initialized*
// cho tới khi thông báo thứ hai tới. Thiếu nó là một daemon nối được rồi bị nói không với mọi thứ.
func TestTheHandshakeIsTwoMessagesAndTheSecondOneIsSent(t *testing.T) {
	agent := &fakeCodex{refuseBeforeInitialized: true}

	_, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một server đòi đủ bắt tay đã từ chối lượt chạy: %v", err)
	}
	if !agent.greeted || !agent.initialized {
		t.Fatalf("bắt tay thiếu: greeted=%v initialized=%v", agent.greeted, agent.initialized)
	}
}

// FR-035, FR-037: ba họ giao thức, một hợp đồng. Không chỗ nào trên gói này phân biệt được lượt
// chạy đã đi đường nào.
func TestWhatCodexSaysComesOutAsTheSameEventsAsTheOtherFamilies(t *testing.T) {
	agent := &fakeCodex{notes: []note{
		finished("agentMessage", map[string]any{"id": "m1", "text": "working on it"}),
		finished("reasoning", map[string]any{"id": "r1", "summary": []string{"thinking"}}),
	}}

	events, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}

	if said := only(t, events, EventAssistantMessage); said.Payload["text"] != "working on it" {
		t.Fatalf("chữ agent nói: %v", said.Payload)
	}
	if thought := only(t, events, EventAssistantThinking); thought.Payload["text"] != "thinking" {
		t.Fatalf("phần suy luận: %v", thought.Payload)
	}
}

func TestACommandTravelsWithItsArgumentsAndThenWithWhatItPrinted(t *testing.T) {
	agent := &fakeCodex{notes: []note{
		started("commandExecution", map[string]any{"id": "c1", "command": "ls -la", "status": "inProgress"}),
		finished("commandExecution", map[string]any{
			"id": "c1", "command": "ls -la", "status": "completed", "aggregatedOutput": "total 0\n",
		}),
	}}

	events, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}

	call := only(t, events, EventToolStarted)
	args, _ := call.Payload["args"].(map[string]any)
	if args["command"] != "ls -la" {
		t.Fatalf("tham số lệnh: %v", call.Payload)
	}
	done := only(t, events, EventToolCompleted)
	if done.Payload["failed"] != false || done.OmissionReason != "" {
		t.Fatalf("lệnh xong mà báo là hỏng hoặc là không nói: %+v", done)
	}
}

// FR-047: *CLI không nói* và *không có gì để nói* là hai chuyện khác nhau. Codex gửi
// `aggregatedOutput` là null khi nó không nói gì về đầu ra của một lệnh, và một bản ghi hiện ra
// như một lệnh chạy xong không in gì là một bản ghi nói sai.
func TestACommandWhoseOutputCodexWithholdsIsNotDressedUpAsACommandThatPrintedNothing(t *testing.T) {
	agent := &fakeCodex{notes: []note{
		started("commandExecution", map[string]any{"id": "c1", "command": "ls", "status": "inProgress"}),
		finished("commandExecution", map[string]any{"id": "c1", "command": "ls", "status": "completed"}),
	}}

	events, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}

	done := only(t, events, EventToolCompleted)
	if done.OmissionReason != NotExposedByCLI {
		t.Fatalf("lý do thiếu đầu ra: %q", done.OmissionReason)
	}
}

// Một lệnh bị từ chối quyền thì **không chạy**, nên bản ghi phải nói là nó hỏng. Hiện ra như một
// bước xong bình thường là bản ghi của một việc chưa từng xảy ra.
func TestACommandTheDaemonRefusedIsRecordedAsHavingGoneWrong(t *testing.T) {
	agent := &fakeCodex{notes: []note{
		finished("commandExecution", map[string]any{"id": "c1", "command": "rm -rf /", "status": "declined"}),
	}}

	events, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}
	if done := only(t, events, EventToolCompleted); done.Payload["failed"] != true {
		t.Fatalf("một lệnh bị từ chối lại hiện ra như xong xuôi: %v", done.Payload)
	}
}

// FR-013b: không có ai ở đây để cho phép, nên không ai cho phép. Codex có đúng từ cho việc ấy —
// `decline` nghĩa là agent bị nói không và **vẫn đi tiếp lượt của nó**.
func TestNobodyIsHereToGrantAnAppServerPermissionSoNobodyDoes(t *testing.T) {
	for _, asked := range []string{
		"item/commandExecution/requestApproval",
		"item/fileChange/requestApproval",
	} {
		agent := &fakeCodex{askMethod: asked}
		events, _, err := attend(t, agent, Request{})
		if err != nil {
			t.Fatalf("%s: một lượt qua app-server: %v", asked, err)
		}
		var answer struct {
			Decision string `json:"decision"`
		}
		if json.Unmarshal(agent.answerToAsk, &answer) != nil || answer.Decision != "decline" {
			t.Fatalf("%s: trả lời xin phép là %s", asked, agent.answerToAsk)
		}
		if refused := only(t, events, EventRunError); refused.Payload["code"] != "permission_refused_nobody_to_ask" {
			t.Fatalf("%s: mã ghi lại: %v", asked, refused.Payload)
		}
	}
}

// Xin quyền được trả lời **bằng chính hình dạng nó hỏi** — một bộ quyền — và bộ ấy rỗng. Trả lời
// sai hình dạng thì server không đọc được câu trả lời, và im lặng thì lượt chạy treo.
func TestAPermissionProfileIsAnsweredWithAnEmptyProfileRatherThanARefusalItCannotRead(t *testing.T) {
	agent := &fakeCodex{
		askMethod: "item/permissions/requestApproval",
		askParams: map[string]any{"permissions": map[string]any{"network": map[string]any{"enabled": true}}},
	}

	_, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}

	var answer struct {
		Permissions map[string]any `json:"permissions"`
		Scope       string         `json:"scope"`
	}
	if json.Unmarshal(agent.answerToAsk, &answer) != nil {
		t.Fatalf("trả lời không đọc được: %s", agent.answerToAsk)
	}
	if len(answer.Permissions) != 0 || answer.Scope != "turn" {
		t.Fatalf("bộ quyền cấp ra: %s", agent.answerToAsk)
	}
}

// Cái phải không bao giờ xảy ra: im lặng. Trên giao thức này server đã dừng lại và đang chờ, nên
// một câu daemon không nhận ra vẫn phải được trả lời — bằng lỗi. Không trả lời không phải là từ
// chối, nó là một lượt chạy treo tới khi có thứ khác giết nó, và từ ngoài nhìn vào thì giống một
// agent đang không làm gì.
func TestARequestThisClientDoesNotKnowIsAnsweredRatherThanIgnored(t *testing.T) {
	agent := &fakeCodex{askMethod: "something/nobodyHereProvides"}

	_, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}
	if agent.errorToAsk == nil {
		t.Fatalf("một câu hỏi lạ không được trả lời gì: result=%s", agent.answerToAsk)
	}
	if agent.errorToAsk.Code != -32601 {
		t.Fatalf("mã lỗi trả về: %d", agent.errorToAsk.Code)
	}
}

// Chỗ khác biệt của họ này, viết thành một bài kiểm: `turn/start` được trả lời **trước khi** việc
// xảy ra, nên mọi thứ agent làm đều tới sau câu trả lời ấy. Một client tưởng câu trả lời là hết
// lượt sẽ ghi lại một lượt chạy rỗng.
func TestTheTurnEndsWhenTheServerSaysSoAndNotWhenTurnStartIsAnswered(t *testing.T) {
	agent := &fakeCodex{notes: []note{
		finished("agentMessage", map[string]any{"id": "m1", "text": "done at last"}),
	}}

	events, _, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}
	if said := only(t, events, EventAssistantMessage); said.Payload["text"] != "done at last" {
		t.Fatalf("việc làm sau câu trả lời turn/start bị bỏ: %v", events)
	}
}

func TestATurnTheServerCallsFailedIsAFailedTurn(t *testing.T) {
	agent := &fakeCodex{turnStatus: "failed", turnError: "the model refused"}

	_, out, err := attend(t, agent, Request{})
	if err == nil {
		t.Fatalf("một lượt hỏng lại báo là xong: %+v", out)
	}
	if !strings.Contains(err.Error(), "the model refused") {
		t.Fatalf("lý do hỏng không đi kèm: %v", err)
	}
	// Không mã hỏng nào được khai: bên này chưa đo được câu chữ nào của CLI này, và một kết thúc
	// không ai phân loại thì server chạy lại chứ không đem ra hỏi người (FR-032a).
	if out.Failure != "" {
		t.Fatalf("khai mã hỏng cho một thứ chưa đo: %q", out.Failure)
	}
}

func TestWhatATurnCostComesBackAsTheServerGaveIt(t *testing.T) {
	agent := &fakeCodex{usage: map[string]any{"inputTokens": float64(11), "outputTokens": float64(4)}}

	_, out, err := attend(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua app-server: %v", err)
	}
	if out.Usage["inputTokens"] != float64(11) || out.Usage["outputTokens"] != float64(4) {
		t.Fatalf("số đo lượt chạy: %v", out.Usage)
	}
}

// FR-025, FR-039a: một mạch không nối lại được thì mở mạch mới kèm câu báo, chứ không phải hỏng.
func TestAThreadThatCannotBeResumedStartsAFreshOneRatherThanFailing(t *testing.T) {
	agent := &fakeCodex{refuseResume: true}

	events, out, err := attend(t, agent, Request{Session: "thr_long_gone"})
	if err != nil {
		t.Fatalf("một mạch chết lại làm hỏng cả lượt chạy: %v", err)
	}
	if agent.resumeAsked != "thr_long_gone" {
		t.Fatalf("không ai hỏi nối lại mạch cũ: %q", agent.resumeAsked)
	}
	if out.Session != "thr_just_opened" || !out.SessionRefused {
		t.Fatalf("mạch sau khi bị từ chối: %q refused=%v", out.Session, out.SessionRefused)
	}
	if lost := only(t, events, EventRunError); lost.Payload["code"] != RestartRefused {
		t.Fatalf("mã ghi lại việc mất mạch: %v", lost.Payload)
	}
	if !strings.Contains(agent.prompt, "Your instructions") {
		t.Fatalf("agent không nhận được việc của nó: %q", agent.prompt)
	}
}

func TestAThreadThatIsResumedIsNotReopened(t *testing.T) {
	agent := &fakeCodex{}

	_, out, err := attend(t, agent, Request{Session: "thr_still_alive"})
	if err != nil {
		t.Fatalf("một lượt nối lại: %v", err)
	}
	if agent.opened != 0 {
		t.Fatalf("nối lại được rồi vẫn mở mạch mới %d lần", agent.opened)
	}
	if out.Session != "thr_still_alive" || out.SessionRefused {
		t.Fatalf("mạch sau khi nối lại: %q refused=%v", out.Session, out.SessionRefused)
	}
	// Không đòi lại toàn bộ bản ghi cũ: mặc định của server là gửi cả lịch sử mạch, mà bên này
	// không đọc dòng nào của nó.
	if !agent.excludeTurns {
		t.Fatalf("nối lại mà vẫn đòi cả lịch sử mạch về để bỏ đi")
	}
}

func TestAnAppServerThatStopsTalkingIsAFailedTurnRatherThanAWaitForever(t *testing.T) {
	_, err := Attend(context.Background(), io.Discard, strings.NewReader(""),
		Request{CLI: "a-codex-cli", WorkDir: t.TempDir(), Message: "anything"}, func(Event) {})
	if err == nil {
		t.Fatalf("một server im lặng lại tính là một lượt chạy xong")
	}
}

func TestRunningAnAppServerAgentWithNothingToSayIsRefused(t *testing.T) {
	_, err := Attend(context.Background(), io.Discard, nil,
		Request{CLI: "a-codex-cli", WorkDir: t.TempDir()}, nil)
	if err == nil {
		t.Fatalf("một lượt chạy không có gì để nói với agent lại được nhận")
	}
}

// Cùng luật với họ ACP: chỉ hàng nào **khai** là họ này, và khai kèm cách bật giao thức, mới được
// bật lên. Đoán cờ là một daemon bật CLI rồi chờ mãi một cái bắt tay không bao giờ tới.
func TestNoAppServerCLIIsStartedBeforeItsRowSaysHowTo(t *testing.T) {
	if _, known := appServerStart("claude_code"); known {
		t.Fatalf("một CLI họ chạy-một-phát lại được bật như app-server")
	}
	if _, known := appServerStart("gemini"); known {
		t.Fatalf("một CLI họ ACP lại được bật như app-server")
	}
	if _, known := appServerStart("nothing-of-the-sort"); known {
		t.Fatalf("một loại CLI không có trong bảng lại bật được")
	}
	flags, known := appServerStart("codex")
	if !known || len(flags) == 0 {
		t.Fatalf("codex không có cách bật giao thức: %v %v", flags, known)
	}
}

// FR-013a: công cụ gọi ngược của lượt chạy này được khai **theo từng lượt** và **không ghi vào
// đâu**. Codex đọc MCP server từ cấu hình, mà cấu hình của nó là của người vận hành — chính tệp
// mà nhà giả của lượt chạy này link thẳng sang. Nên đường duy nhất còn lại là cờ ghi đè một
// lần cho một tiến trình.
func TestThisRunsOwnToolsAreDeclaredOnTheCommandLineAndNowhereElse(t *testing.T) {
	flags := toolFlags(Request{ToolServers: []execenv.ToolServer{
		{Name: "armarius", Command: "/tasks/t1/.armarius/bin/armarius", Args: []string{"mcp"}},
	}})

	said := strings.Join(flags, " ")
	for _, want := range []string{
		`-c mcp_servers.armarius.command="/tasks/t1/.armarius/bin/armarius"`,
		`-c mcp_servers.armarius.args=["mcp"]`,
	} {
		if !strings.Contains(said, want) {
			t.Fatalf("thiếu %q trong %q", want, said)
		}
	}
}

func TestARunGivenNoToolsIsStartedWithTheCommandLineItWouldHaveHadAnyway(t *testing.T) {
	if flags := toolFlags(Request{}); len(flags) != 0 {
		t.Fatalf("một lượt chạy không có công cụ vẫn thêm cờ: %v", flags)
	}
}

// Một đường dẫn có dấu ngoặc kép hay dấu gạch chéo ngược vẫn phải ra một giá trị TOML đọc được.
// Sai chỗ này thì CLI không chạy — ồn ào, nhưng vẫn là một lượt chạy chết vì cách trích dẫn.
func TestAPathWithQuotesInItStillRendersAsAValueCodexCanRead(t *testing.T) {
	flags := toolFlags(Request{ToolServers: []execenv.ToolServer{
		{Name: "armarius", Command: `/tmp/od"d\path/armarius`},
	}})

	value := strings.TrimPrefix(flags[1], "mcp_servers.armarius.command=")
	var back string
	if err := json.Unmarshal([]byte(value), &back); err != nil {
		t.Fatalf("giá trị không đọc lại được: %s", value)
	}
	if back != `/tmp/od"d\path/armarius` {
		t.Fatalf("đường dẫn qua một vòng trích dẫn thành %q", back)
	}
}

// Bài kiểm duy nhất ở đây bật một **tiến trình thật** và nói với nó qua ống thật.
//
// Mọi bài trên gọi `Attend` với hai cái ống trong bộ nhớ, nên chúng không đi qua `Run`: không qua
// chỗ dựng dòng lệnh, không qua chỗ mở ống, không qua chỗ chờ tiến trình chết. Đó đúng là quãng mà
// `codex` thật sẽ đi, và máy này không chạy nổi `codex`. Nên chỗ này thay `codex` bằng một chương
// trình nói đúng giao thức ấy — không phải để giả vờ đã đo được `codex`, mà để cái quãng ống-và-
// tiến-trình được chạy qua một lần bằng thứ thật.
func TestARealProcessIsStartedAndSpokenToDownRealPipes(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("cần python3 để dựng một chương trình nói giao thức")
	}
	work := t.TempDir()
	binary := filepath.Join(work, "codex-stand-in")
	argvSeen := filepath.Join(work, "argv.txt")
	if err := os.WriteFile(binary, []byte(standInAppServer), 0o700); err != nil {
		t.Fatal(err)
	}

	var events []Event
	out, err := AppServer{}.Run(context.Background(), Request{
		CLI:     "codex",
		Binary:  binary,
		WorkDir: work,
		Message: "write hello.txt",
		Env:     []string{"STAND_IN_ARGV=" + argvSeen, "PATH=" + os.Getenv("PATH")},
		ToolServers: []execenv.ToolServer{
			{Name: "armarius", Command: filepath.Join(work, "armarius"), Args: []string{"mcp"}},
		},
	}, func(e Event) { events = append(events, e) })
	if err != nil {
		t.Fatalf("một lượt qua tiến trình thật: %v", err)
	}

	if out.Session != "thr_from_a_real_process" {
		t.Fatalf("mã mạch trả về: %q", out.Session)
	}
	if said := only(t, events, EventAssistantMessage); said.Payload["text"] != "wrote it" {
		t.Fatalf("chữ agent nói: %v", said.Payload)
	}
	// Và dòng lệnh thật sự tới được tiến trình, kèm cả cờ khai công cụ.
	argv, err := os.ReadFile(argvSeen)
	if err != nil {
		t.Fatalf("chương trình không ghi lại dòng lệnh của nó: %v", err)
	}
	for _, want := range []string{"app-server", "--listen", "stdio://", "mcp_servers.armarius.command="} {
		if !strings.Contains(string(argv), want) {
			t.Fatalf("dòng lệnh thiếu %q: %s", want, argv)
		}
	}
}

// standInAppServer nói đủ giao thức cho một lượt chạy: bắt tay, mở mạch, một lượt, một câu, hết.
const standInAppServer = `#!/usr/bin/env python3
import json, os, sys

argv = os.environ.get("STAND_IN_ARGV")
if argv:
    open(argv, "w").write("\n".join(sys.argv[1:]))

def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    heard = json.loads(line)
    method = heard.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": heard["id"], "result": {"userAgent": "stand-in/1"}})
    elif method == "thread/start":
        send({"jsonrpc": "2.0", "id": heard["id"],
              "result": {"thread": {"id": "thr_from_a_real_process"}}})
    elif method == "turn/start":
        send({"jsonrpc": "2.0", "id": heard["id"],
              "result": {"turn": {"id": "turn_1", "status": "inProgress"}}})
        send({"jsonrpc": "2.0", "method": "item/completed",
              "params": {"item": {"type": "agentMessage", "id": "m1", "text": "wrote it"}}})
        send({"jsonrpc": "2.0", "method": "turn/completed",
              "params": {"turn": {"id": "turn_1", "status": "completed"}}})
`
