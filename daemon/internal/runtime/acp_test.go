package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"testing"
)

// fakeAgent is an ACP peer that is not a CLI at all.
//
// The one ACP CLI of this release is the one nobody has been able to run yet (T013), so a
// protocol tested only by running one would be a protocol nobody had tested.
type fakeAgent struct {
	t *testing.T

	// what it will do
	loadFails     bool
	updates       []map[string]any
	askPermission bool
	silentAfter   string

	// what it saw
	cwd              string
	loaded           string
	prompt           string
	permissionAnswer json.RawMessage
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
			reply(msg.ID, map[string]any{"protocolVersion": acpProtocolVersion})

		case "session/new":
			var params struct {
				CWD string `json:"cwd"`
			}
			_ = json.Unmarshal(msg.Params, &params)
			a.cwd = params.CWD
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
					Params:  mustRaw(map[string]any{"sessionId": "session-just-opened"}),
				})
				// The answer arrives as the next thing the client says.
				if lines.Scan() {
					var answer rpcMessage
					if json.Unmarshal(lines.Bytes(), &answer) == nil {
						a.permissionAnswer = answer.Result
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

func TestNobodyIsHereToGrantPermissionSoNobodyDoes(t *testing.T) {
	// The daemon holds a machine's credentials, not a patron's judgement. Saying yes on their
	// behalf would put an approval nobody gave on every unattended run (task T131).
	agent := &fakeAgent{askPermission: true}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("một lượt qua ACP: %v", err)
	}

	var answered struct {
		Outcome struct {
			Outcome string `json:"outcome"`
		} `json:"outcome"`
	}
	if json.Unmarshal(agent.permissionAnswer, &answered) != nil || answered.Outcome.Outcome != "cancelled" {
		t.Fatalf("câu trả lời cho lời xin phép: %s", agent.permissionAnswer)
	}
	if refused := only(t, events, EventRunError); refused.Payload["code"] != "permission_refused_nobody_to_ask" {
		t.Fatalf("lời xin phép bị từ chối mà không để lại dấu: %v", refused.Payload)
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

func TestNoACPCLIIsStartedBeforeItHasActuallyBeenProbed(t *testing.T) {
	// The invocation table is empty on purpose. Gemini CLI's ACP flag is known from a help page
	// rather than from a session, and T013 forbids writing its code before the probe has run —
	// a guess here would be a daemon that starts a CLI and waits forever for a handshake that
	// was never coming.
	for _, cli := range []string{"gemini", "claude_code"} {
		if _, err := (ACP{}).Run(context.Background(), Request{
			CLI: cli, Binary: "/bin/true", WorkDir: t.TempDir(), Message: "hello",
		}, nil); err == nil {
			t.Fatalf("%s được khởi chạy như một peer ACP dù chưa ai dò nó", cli)
		}
	}
}
