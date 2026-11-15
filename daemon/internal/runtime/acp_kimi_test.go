package runtime

import (
	"reflect"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// What follows is the ACP road held to what Kimi Code 2.5.3 was measured doing on 2026-11-15
// (FR-039g, FR-039h). The frames are the ones that binary sent during one real turn — asked to
// run `echo hello-from-kimi` — with nothing changed but the session id.

// kimiRunsACommand is one tool call as kimi 2.5.3 tells it: announced with no arguments, the
// arguments written out a frame at a time, `rawInput` once the call is cleared to run, and what
// the command printed when it is done.
var kimiRunsACommand = []map[string]any{
	{
		"sessionUpdate": "tool_call", "toolCallId": "0:tool_bJtd", "title": "Bash",
		"kind": "execute", "status": "pending",
		"content": []any{map[string]any{"type": "content", "content": map[string]any{"type": "text", "text": ""}}},
	},
	{
		"sessionUpdate": "tool_call_update", "toolCallId": "0:tool_bJtd", "status": "in_progress",
		"content": []any{map[string]any{"type": "content", "content": map[string]any{"type": "text", "text": `{"command": "`}}},
	},
	{
		"sessionUpdate": "tool_call_update", "toolCallId": "0:tool_bJtd", "status": "in_progress",
		"content": []any{map[string]any{"type": "content", "content": map[string]any{
			"type": "text", "text": `{"command": "echo hello-from-kimi"}`,
		}}},
	},
	{
		"sessionUpdate": "tool_call_update", "toolCallId": "0:tool_bJtd",
		"title": "Running: echo hello-from-kimi", "kind": "execute", "status": "in_progress",
		"rawInput": map[string]any{"command": "echo hello-from-kimi"},
		"content": []any{map[string]any{"type": "content", "content": map[string]any{
			"type": "text", "text": `{"command":"echo hello-from-kimi"}`,
		}}},
	},
	{
		"sessionUpdate": "tool_call_update", "toolCallId": "0:tool_bJtd", "status": "completed",
		"content": []any{map[string]any{"type": "content", "content": map[string]any{
			"type": "text", "text": "hello-from-kimi\n",
		}}},
		"rawOutput": "hello-from-kimi\n",
	},
}

// The row has to be one this package starts, and starts as a peer: `kimi acp`.
func TestKimiIsStartedAsAnACPPeer(t *testing.T) {
	kind := string(agentcli.Kimi)

	flags, peer := acpStart(kind)
	if !peer || !reflect.DeepEqual(flags, []string{"acp"}) {
		t.Fatalf("kimi is started with %v (as a peer: %v), want [acp]", flags, peer)
	}
	if _, oneShot := oneShots[kind]; oneShot {
		t.Fatal("kimi can also be run once per turn: two answers to how its runs go")
	}
	if !Supported(kind) {
		t.Fatalf("kimi is not drivable; its row is missing %v", agentcli.Undeclared(kind))
	}
}

// A call announced without its arguments is recorded once they are known, not before. Recorded
// at the announcement it would read as a call whose arguments this CLI hides, on a CLI that
// sends every one of them.
func TestAKimiToolCallIsRecordedWithTheArgumentsThatArriveAfterIt(t *testing.T) {
	agent := &fakeAgent{updates: kimiRunsACommand}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}

	started := only(t, events, EventToolStarted)
	if started.OmissionReason != "" {
		t.Fatalf("the call was recorded as hiding its arguments: %+v", started)
	}
	if started.Payload["name"] != "Bash" || started.Payload["call"] != "0:tool_bJtd" {
		t.Fatalf("the call was recorded as %v", started.Payload)
	}
	args, _ := started.Payload["args"].(map[string]any)
	if args["command"] != "echo hello-from-kimi" {
		t.Fatalf("arguments = %v, want the command it ran", started.Payload["args"])
	}

	done := only(t, events, EventToolCompleted)
	if done.Payload["failed"] != false || done.Payload["opening"] != "hello-from-kimi\n" {
		t.Fatalf("the call's ending was recorded as %v", done.Payload)
	}
}

// A tool call's `content` is a list where a message's is a single block. Read as one shape, the
// other fails to parse and the whole update is dropped — which would be every tool call.
func TestAToolCallCarryingAListOfContentIsNotDropped(t *testing.T) {
	agent := &fakeAgent{updates: []map[string]any{
		kimiRunsACommand[0], kimiRunsACommand[4],
		{"sessionUpdate": "agent_message_chunk", "content": map[string]any{"type": "text", "text": "done"}},
	}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}

	only(t, events, EventToolStarted)
	only(t, events, EventToolCompleted)
	if said := only(t, events, EventAssistantMessage); said.Payload["text"] != "done" {
		t.Fatalf("what the agent said: %v", said.Payload)
	}
}

// `rawInput` never came, but the agent wrote the arguments out while composing the call. That
// text is the arguments when it is a JSON object, the same reading Multica's daemon makes.
func TestArgumentsWrittenOutButNeverSentAsRawInputAreStillTheArguments(t *testing.T) {
	agent := &fakeAgent{updates: []map[string]any{
		kimiRunsACommand[0], kimiRunsACommand[2],
		{"sessionUpdate": "tool_call_update", "toolCallId": "0:tool_bJtd", "status": "failed"},
	}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}

	args, _ := only(t, events, EventToolStarted).Payload["args"].(map[string]any)
	if args["command"] != "echo hello-from-kimi" {
		t.Fatalf("arguments = %v", args)
	}
	if only(t, events, EventToolCompleted).Payload["failed"] != true {
		t.Fatal("a failed call was not recorded as failed")
	}
}

// Text that is not the arguments is not dressed up as them (FR-047).
func TestACallThatNeverSaysItsArgumentsIsRecordedAsNotSayingThem(t *testing.T) {
	agent := &fakeAgent{updates: []map[string]any{
		{
			"sessionUpdate": "tool_call", "toolCallId": "call-9", "title": "Read", "status": "pending",
			"content": []any{map[string]any{"type": "content", "content": map[string]any{
				"type": "text", "text": "Preparing to read a file",
			}}},
		},
		{"sessionUpdate": "tool_call_update", "toolCallId": "call-9", "status": "completed"},
	}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}

	started := only(t, events, EventToolStarted)
	if _, dressed := started.Payload["args"]; dressed || started.OmissionReason != NotExposedByCLI {
		t.Fatalf("prose was recorded as arguments: %+v", started)
	}
}

// A call still waiting when the turn ends was still made, and comes before the end rather than
// vanishing with it.
func TestACallTheTurnEndedOnIsStillRecorded(t *testing.T) {
	agent := &fakeAgent{updates: []map[string]any{kimiRunsACommand[0], kimiRunsACommand[2]}}

	events, _, err := talkTo(t, agent, Request{})
	if err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}

	args, _ := only(t, events, EventToolStarted).Payload["args"].(map[string]any)
	if args["command"] != "echo hello-from-kimi" {
		t.Fatalf("the unfinished call was recorded with %v", args)
	}
}

// An agent that declares `session/resume` is asked to resume, as Multica's daemon asks Kimi.
func TestAnAgentThatDeclaresResumeIsResumedRatherThanLoaded(t *testing.T) {
	agent := &fakeAgent{declaresResume: true}

	_, out, err := talkTo(t, agent, Request{Session: "session_bd681d8f"})
	if err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}

	if agent.resumed != "session_bd681d8f" || agent.loaded != "" {
		t.Fatalf("resumed %q, loaded %q; want it resumed and not loaded", agent.resumed, agent.loaded)
	}
	if out.Session != "session_bd681d8f" || agent.cwd != "" {
		t.Fatalf("the turn went on session %q (opened a new one: %v)", out.Session, agent.cwd != "")
	}
}

// One that does not is loaded, which is the only word it has for it.
func TestAnAgentThatOnlyLoadsIsStillLoaded(t *testing.T) {
	agent := &fakeAgent{}

	if _, _, err := talkTo(t, agent, Request{Session: "an-old-session"}); err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}
	if agent.loaded != "an-old-session" || agent.resumed != "" {
		t.Fatalf("loaded %q, resumed %q", agent.loaded, agent.resumed)
	}
}

// What an agent recites while picking a session up is the turn before, not this one. kimi 2.5.3
// answered `session/load` with every message and tool call of the earlier turn; written down,
// that is a run claiming last turn's work as its own.
func TestAnOldConversationRecitedBeforeThePromptIsNotThisTurnsWork(t *testing.T) {
	agent := &fakeAgent{
		recites: append([]map[string]any{
			{"sessionUpdate": "user_message_chunk", "content": map[string]any{"type": "text", "text": "earlier question"}},
			{"sessionUpdate": "agent_message_chunk", "content": map[string]any{"type": "text", "text": "earlier answer"}},
		}, kimiRunsACommand...),
		updates: []map[string]any{
			{"sessionUpdate": "agent_message_chunk", "content": map[string]any{"type": "text", "text": "this turn"}},
		},
	}

	events, _, err := talkTo(t, agent, Request{Session: "an-old-session"})
	if err != nil {
		t.Fatalf("a turn over ACP: %v", err)
	}

	if said := only(t, events, EventAssistantMessage); said.Payload["text"] != "this turn" {
		t.Fatalf("recorded %v", said.Payload)
	}
	for _, event := range events {
		if event.Type == EventToolStarted || event.Type == EventToolCompleted {
			t.Fatalf("a tool call from the earlier turn was recorded again: %v", event.Payload)
		}
	}
}

// `auth_required` is the protocol's own code, and the one ending on this road that is named
// (FR-032a). Measured on kimi 2.5.3 in a home nobody had signed in to.
func TestAnAgentNobodyIsSignedInToEndsTheRunAsCredentialRejected(t *testing.T) {
	agent := &fakeAgent{nobodySignedIn: true}

	_, out, err := talkTo(t, agent, Request{})
	if err == nil {
		t.Fatal("a session that would not open was reported as a finished turn")
	}
	if out.Failure != failureCredentialRejected {
		t.Fatalf("failure = %q, want %q", out.Failure, failureCredentialRejected)
	}
}

// The same code on the way to resuming is the same ending: the resume is refused, the new
// session is refused, and the reason is the sign-in rather than the session.
func TestBeingSignedOutWhileResumingIsStillCredentialRejected(t *testing.T) {
	agent := &fakeAgent{declaresResume: true, nobodySignedIn: true}

	_, out, err := talkTo(t, agent, Request{Session: "session_bd681d8f"})
	if err == nil || out.Failure != failureCredentialRejected {
		t.Fatalf("err = %v, failure = %q", err, out.Failure)
	}
}

// Any other refusal is not classified. A session that will not load answers with a code too,
// and reading every code as a wall would put a person in front of a run that only needed a
// fresh conversation.
func TestAnyOtherRefusalIsLeftUnclassified(t *testing.T) {
	agent := &fakeAgent{silentAfter: "session/prompt"}

	_, out, err := talkTo(t, agent, Request{})
	if err == nil || out.Failure != "" {
		t.Fatalf("err = %v, failure = %q; want a failed turn nobody classified", err, out.Failure)
	}
}
