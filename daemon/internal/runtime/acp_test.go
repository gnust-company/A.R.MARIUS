package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// fakeAgent is an ACP peer that is not a CLI at all.
//
// No CLI of this release runs over ACP — Gemini CLI, the only one that did, runs once per turn
// since FR-039f — so a protocol tested only by running one would be a protocol nobody had tested.
type fakeAgent struct {
	t *testing.T

	// what it will do
	loadFails     bool
	updates       []map[string]any
	askPermission bool
	// permissionOptions are what the permission request offers, in ACP's own shape.
	permissionOptions []map[string]any
	silentAfter       string

	// what it saw
	cwd              string
	offeredTools     []map[string]any
	loaded           string
	prompt           string
	permissionAnswer json.RawMessage
	permissionError  *rpcError
}

func (a *fakeAgent) serve(in io.Reader, out io.Writer) {
	a.t.Helper()
	lines := bufio.NewScanner(in)
	enc := json.NewEncoder(out)

	reply := func(id json.RawMessage, result any) {
		if err := enc.Encode(rpcMessage{JSONRPC: "2.0", ID: id, Result: mustRaw(result)}); err != nil {
			a.t.Errorf("agent giả trả lời hỏng: %v", err)
		}
	}

	for lines.Scan() {
		var msg rpcMessage
		if json.Unmarshal(lines.Bytes(), &msg) != nil {
			continue
		}
		if msg.Method == "" {
			// An answer to something this peer asked.
			a.permissionAnswer = msg.Result
			continue
		}
		if msg.Method == a.silentAfter {
			return
		}

		switch msg.Method {
		case "initialize":
			reply(msg.ID, map[string]any{"protocolVersion": agentcli.ACPVersion})

		case "session/new":
			var params struct {
				CWD        string           `json:"cwd"`
				MCPServers []map[string]any `json:"mcpServers"`
			}
			_ = json.Unmarshal(msg.Params, &params)
			a.cwd = params.CWD
			a.offeredTools = params.MCPServers
			reply(msg.ID, map[string]any{"sessionId": "session-just-opened"})

		case "session/load":
			var params struct {
				SessionID string `json:"sessionId"`
			}
			_ = json.Unmarshal(msg.Params, &params)
			a.loaded = params.SessionID
			if a.loadFails {
				_ = enc.Encode(rpcMessage{JSONRPC: "2.0", ID: msg.ID, Error: &rpcError{
					Code: -32000, Message: "no such session",
				}})
				continue
			}
			reply(msg.ID, map[string]any{})

		case "session/prompt":
			var params struct {
				Prompt []struct {
					Text string `json:"text"`
				} `json:"prompt"`
			}
			_ = json.Unmarshal(msg.Params, &params)
			if len(params.Prompt) > 0 {
				a.prompt = params.Prompt[0].Text
			}
			for _, update := range a.updates {
				_ = enc.Encode(rpcMessage{
					JSONRPC: "2.0",
					Method:  "session/update",
					Params:  mustRaw(map[string]any{"sessionId": "session-just-opened", "update": update}),
				})
			}
			if a.askPermission {
				_ = enc.Encode(rpcMessage{
					JSONRPC: "2.0",
					ID:      json.RawMessage("900"),
					Method:  "session/request_permission",
					Params: mustRaw(map[string]any{
						"sessionId": "session-just-opened",
						"options":   a.permissionOptions,
						"toolCall":  map[string]any{"toolCallId": "call-1", "status": "pending"},
					}),
				})
				// The answer arrives as the next thing the client says.
				if lines.Scan() {
					var answer rpcMessage
					if json.Unmarshal(lines.Bytes(), &answer) == nil {
						a.permissionAnswer, a.permissionError = answer.Result, answer.Error
					}
				}
			}
			reply(msg.ID, map[string]any{"stopReason": "end_turn"})
		}
	}
}

func talkTo(t *testing.T, agent *fakeAgent, req Request) ([]Event, Outcome, error) {
	t.Helper()
	agent.t = t
	if req.CLI == "" {
		req.CLI = "an-acp-cli"
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

	var events []Event
	out, err := Converse(context.Background(), toAgentW, fromAgentR, req, func(e Event) {
		events = append(events, e)
	})
	_ = toAgentW.Close()
	_ = fromAgentR.Close()
	<-served
	return events, out, err
}

func TestATurnOpensASessionInTheTasksDirectoryAndSaysWhatItWasGiven(t *testing.T) {
	agent := &fakeAgent{}
	work := t.TempDir()

	_, out, err := talkTo(t, agent, Request{WorkDir: work, Message: "the whole brief"})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if agent.cwd != work {
		t.Fatalf("phiên mở ở %s, không phải thư mục của đầu việc %s", agent.cwd, work)
	}
	if agent.prompt != "the whole brief" {
		t.Fatalf("agent nhận được %q", agent.prompt)
	}
	if out.Session != "session-just-opened" {
		t.Fatalf("mã phiên trả về là %q", out.Session)
	}
}

func TestWhatTheAgentSaysOverACPComesOutAsTheSameEventsAsTheOtherFamily(t *testing.T) {
	// FR-035, FR-037: two protocol families, one contract. Nothing above this package may be
	// able to tell which road a run took.
	agent := &fakeAgent{updates: []map[string]any{
		{"sessionUpdate": "agent_message_chunk", "content": map[string]any{"type": "text", "text": "working on it"}},
		{"sessionUpdate": "agent_thought_chunk", "content": map[string]any{"type": "text", "text": "thinking"}},
	}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if said := only(t, events, EventAssistantMessage); said.Payload["text"] != "working on it" {
		t.Fatalf("chữ agent nói: %v", said.Payload)
	}
	if thought := only(t, events, EventAssistantThinking); thought.Payload["text"] != "thinking" {
		t.Fatalf("phần suy luận: %v", thought.Payload)
	}
}

func TestACallWhoseArgumentsTheCLIWithholdsIsNotDressedUpAsACallWithNone(t *testing.T) {
	// Gemini's ACP messages carry no `rawInput` at all (research §9.1). An empty map here would
	// read as *called with nothing*, which is a different fact from *this CLI does not say* —
	// telling those two apart is the whole of FR-047.
	agent := &fakeAgent{updates: []map[string]any{
		{"sessionUpdate": "tool_call", "toolCallId": "call-1", "title": "read_file"},
	}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	started := only(t, events, EventToolStarted)
	if _, dressed := started.Payload["args"]; dressed {
		t.Fatalf("CLI không nói tham số mà sự kiện vẫn khai có: %v", started.Payload)
	}
}

func TestArgumentsTheCLIDoesSendTravelInFull(t *testing.T) {
	agent := &fakeAgent{updates: []map[string]any{
		{
			"sessionUpdate": "tool_call", "toolCallId": "call-1", "title": "read_file",
			"rawInput": map[string]any{"path": "/etc/hosts"},
		},
		{"sessionUpdate": "tool_call_update", "toolCallId": "call-1", "status": "failed"},
	}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	args, ok := only(t, events, EventToolStarted).Payload["args"].(map[string]any)
	if !ok || args["path"] != "/etc/hosts" {
		t.Fatalf("tham số gọi công cụ không đi đủ: %v", args)
	}
	if failed := only(t, events, EventToolCompleted).Payload["failed"]; failed != true {
		t.Fatalf("công cụ hỏng mà sự kiện không nói: %v", failed)
	}
}

// The options a real ACP peer offers for a tool call it wants confirmed, in the order gemini 0.56.0
// listed them: the session-wide and permanent grants first, then the one-off allow and reject.
var offeredForAToolCall = []map[string]any{
	{"optionId": "proceed_always", "name": "Allow for this session", "kind": "allow_always"},
	{"optionId": "proceed_always_and_save", "name": "Allow for all future sessions", "kind": "allow_always"},
	{"optionId": "proceed_once", "name": "Allow", "kind": "allow_once"},
	{"optionId": "cancel", "name": "Reject", "kind": "reject_once"},
}

// selected reads which option an answer picked, or empty when it picked none.
func selected(t *testing.T, raw json.RawMessage) string {
	t.Helper()
	var answered struct {
		Outcome struct {
			Outcome  string `json:"outcome"`
			OptionID string `json:"optionId"`
		} `json:"outcome"`
	}
	if json.Unmarshal(raw, &answered) != nil || answered.Outcome.Outcome != "selected" {
		return ""
	}
	return answered.Outcome.OptionID
}

// FR-013b (sửa 2026-09-28): không có ai ở đây để hỏi, nên lời xin được đồng ý — nhưng **một lần**.
// Lựa chọn "luôn luôn" được CLI ghi vào cấu hình của người vận hành và sống lâu hơn đầu việc, nên
// daemon không bao giờ tự chọn nó, dù nó đứng đầu danh sách.
func TestAPermissionAskedOverACPIsGrantedOnceNeverAlways(t *testing.T) {
	agent := &fakeAgent{askPermission: true, permissionOptions: offeredForAToolCall}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if picked := selected(t, agent.permissionAnswer); picked != "proceed_once" {
		t.Fatalf("chọn %q trong lời xin phép, mong proceed_once: %s", picked, agent.permissionAnswer)
	}
	for _, e := range events {
		if e.Type == EventRunError {
			t.Fatalf("đồng ý mà vẫn ghi lỗi: %v", e.Payload)
		}
	}
}

// Chỉ được mời "luôn luôn" thì daemon từ chối **đúng việc ấy** — `reject_once`, không huỷ cả lượt —
// và bản ghi nói vì sao.
func TestOfferedOnlyAnAlwaysGrantOnlyThatActionIsRefused(t *testing.T) {
	agent := &fakeAgent{askPermission: true, permissionOptions: []map[string]any{
		{"optionId": "proceed_always", "kind": "allow_always"},
		{"optionId": "cancel", "kind": "reject_once"},
	}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if picked := selected(t, agent.permissionAnswer); picked != "cancel" {
		t.Fatalf("chọn %q, mong cancel (reject_once): %s", picked, agent.permissionAnswer)
	}
	if refused := only(t, events, EventRunError); refused.Payload["code"] != "permission_refused_nobody_to_ask" {
		t.Fatalf("từ chối mà không để lại dấu: %v", refused.Payload)
	}
}

// Không có gì chọn được một cách trung thực thì câu trả lời là lỗi của giao thức — không bịa ra
// một kết quả, và không im lặng để agent treo.
func TestAnAskWithNothingSelectableIsAnsweredWithAProtocolError(t *testing.T) {
	agent := &fakeAgent{askPermission: true, permissionOptions: []map[string]any{
		{"optionId": "proceed_always", "kind": "allow_always"},
		{"optionId": "never", "kind": "reject_always"},
	}}

	if _, _, err := talkTo(t, agent, Request{}); err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if agent.permissionError == nil {
		t.Fatalf("không có lựa chọn nào hợp lệ mà vẫn trả kết quả: %s", agent.permissionAnswer)
	}
}

func TestASessionThatCannotBeCarriedOnStartsANewOneRatherThanFailing(t *testing.T) {
	// FR-039a: a missing capability is still support. FR-025: the answer is a new session with
	// a note, not a run that refuses to happen.
	agent := &fakeAgent{loadFails: true}

	events, out, err := talkTo(t, agent, Request{Session: "an-old-session"})
	if err != nil {
		t.Fatalf("nối lại phiên hỏng làm hỏng cả lượt chạy: %v", err)
	}

	if agent.loaded != "an-old-session" {
		t.Fatalf("không hề thử nối lại phiên cũ: %q", agent.loaded)
	}
	if out.Session != "session-just-opened" {
		t.Fatalf("phiên dùng cho lượt này là %q", out.Session)
	}
	if lost := only(t, events, EventRunError); lost.Payload["code"] != "session_not_resumed" {
		t.Fatalf("mất mạch cũ mà không để lại dấu: %v", lost.Payload)
	}
}

// Một lượt chat nối phiên chỉ mang câu mới; phiên không nạp được thì agent phải đọc bản có lịch
// sử, không thì nó bắt đầu lại mà không biết gì về cuộc trò chuyện (FR-040c).
func TestASessionThatWillNotLoadIsToldTheHistoryInstead(t *testing.T) {
	agent := &fakeAgent{loadFails: true}

	if _, _, err := talkTo(t, agent, Request{
		Session:      "an-old-session",
		Message:      "Their message: and now?",
		FreshMessage: "Conversation so far: Patron: hello. Their message: and now?",
	}); err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}
	if !strings.Contains(agent.prompt, "Patron: hello") {
		t.Fatalf("phiên không nạp được mà agent không được kể lại lịch sử: %q", agent.prompt)
	}
}

func TestASessionThatLoadsIsToldOnlyWhatIsNew(t *testing.T) {
	agent := &fakeAgent{}

	if _, _, err := talkTo(t, agent, Request{
		Session:      "an-old-session",
		Message:      "Their message: and now?",
		FreshMessage: "Conversation so far: Patron: hello. Their message: and now?",
	}); err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}
	if strings.Contains(agent.prompt, "Patron: hello") {
		t.Fatalf("phiên nạp được mà agent vẫn bị kể lại lịch sử: %q", agent.prompt)
	}
}

func TestASessionThatIsCarriedOnIsNotReopened(t *testing.T) {
	agent := &fakeAgent{}

	_, out, err := talkTo(t, agent, Request{Session: "an-old-session"})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if agent.cwd != "" {
		t.Fatal("phiên cũ nối lại được mà vẫn mở thêm một phiên mới")
	}
	if out.Session != "an-old-session" {
		t.Fatalf("lượt chạy đi tiếp trên phiên %q", out.Session)
	}
}

func TestAnAgentThatStopsTalkingIsAFailedTurnRatherThanAWaitForever(t *testing.T) {
	agent := &fakeAgent{silentAfter: "session/prompt"}

	if _, _, err := talkTo(t, agent, Request{}); err == nil {
		t.Fatal("agent im bặt giữa lượt mà lượt chạy vẫn coi là xong")
	}
}

func TestRunningAnACPAgentWithNothingToSayIsRefused(t *testing.T) {
	_, err := Converse(context.Background(), io.Discard, nil, Request{CLI: "an-acp-cli", WorkDir: t.TempDir()}, nil)
	if err == nil {
		t.Fatal("chạy agent mà không có gì để nói với nó")
	}
}

func TestNoCLIOfThisReleaseIsStartedAsAnACPPeer(t *testing.T) {
	// No row is ACP: Gemini CLI runs once per turn since FR-039f, Claude Code always has. Started
	// as a peer, either would wait for a handshake that was never coming.
	for _, cli := range []string{"gemini", "claude_code"} {
		if _, err := (ACP{}).Run(context.Background(), Request{
			CLI: cli, Binary: "/bin/true", WorkDir: t.TempDir(), Message: "hello",
		}, nil); err == nil {
			t.Fatalf("%s được khởi chạy như một peer ACP dù chưa ai dò nó", cli)
		}
	}
}

func TestAnACPPeerIsOfferedThisRunsOwnToolsWhenTheSessionOpens(t *testing.T) {
	// The native tool face for this whole family (FR-013a). There is no file to write and
	// nothing per-CLI to declare: a peer is told about its tools in the handshake, so the
	// declaration is per run by construction.
	agent := &fakeAgent{}
	program := filepath.Join(t.TempDir(), "armarius")

	_, _, err := talkTo(t, agent, Request{
		WorkDir: t.TempDir(),
		Message: "the whole brief",
		ToolServers: []execenv.ToolServer{
			{Name: "armarius", Command: program, Args: []string{"mcp"}},
		},
	})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if len(agent.offeredTools) != 1 {
		t.Fatalf("agent được mời %d bộ công cụ, mong đúng một: %v", len(agent.offeredTools), agent.offeredTools)
	}
	offered := agent.offeredTools[0]
	if offered["name"] != "armarius" || offered["command"] != program {
		t.Fatalf("bộ công cụ được khai không phải của lượt chạy này: %v", offered)
	}
	// No credential in the handshake: `env` is there, because the schema requires it, and empty.
	// The peer starts the program as its own child, so it inherits the environment this run was
	// built with — the only place FR-013c allows the token to be.
	if env, carried := offered["env"].([]any); !carried || len(env) != 0 {
		t.Fatalf("mong env là danh sách rỗng, nhận %v", offered["env"])
	}
}

// ACP v1's `McpServerStdio` requires all four of `name`, `command`, `args`, `env`, and a peer that
// checks its input refuses the whole session over one missing — gemini 0.56.0 answered `-32603`
// (T182). So a server with no arguments is still declared with an empty list, not without one.
func TestEveryToolServerIsDeclaredInAllFourFields(t *testing.T) {
	agent := &fakeAgent{}

	_, _, err := talkTo(t, agent, Request{
		ToolServers: []execenv.ToolServer{{Name: "armarius", Command: "/somewhere/armarius"}},
	})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	if len(agent.offeredTools) != 1 {
		t.Fatalf("mong đúng một bộ công cụ: %v", agent.offeredTools)
	}
	for _, field := range []string{"name", "command", "args", "env"} {
		if _, declared := agent.offeredTools[0][field]; !declared {
			t.Errorf("thiếu trường %q mà schema ACP bắt buộc: %v", field, agent.offeredTools[0])
		}
	}
	if args, _ := agent.offeredTools[0]["args"].([]any); args == nil || len(args) != 0 {
		t.Errorf("mong args là danh sách rỗng, nhận %v", agent.offeredTools[0]["args"])
	}
}

func TestARunGivenNoToolsOffersAnEmptyListRatherThanNothing(t *testing.T) {
	agent := &fakeAgent{}
	if _, _, err := talkTo(t, agent, Request{WorkDir: t.TempDir(), Message: "hi"}); err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}
	if agent.offeredTools == nil || len(agent.offeredTools) != 0 {
		t.Fatalf("mong một danh sách rỗng, nhận %v", agent.offeredTools)
	}
}
