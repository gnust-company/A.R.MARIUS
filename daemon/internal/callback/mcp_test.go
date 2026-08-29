package callback

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
)

// speak drives the MCP face the way a CLI's tool loader does: line-delimited JSON-RPC over
// stdio. Nothing here reaches into the registry — the point is to count what an agent on the
// other end of the pipe would actually see.
func speak(t *testing.T, env Environment, requests ...string) []map[string]any {
	t.Helper()
	var out bytes.Buffer
	code := ServeMCP(
		context.Background(),
		env,
		strings.NewReader(strings.Join(requests, "\n")+"\n"),
		&out,
		&bytes.Buffer{},
	)
	if code != ExitOK {
		t.Fatalf("the server ended with %d", code)
	}
	var answers []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if line == "" {
			continue
		}
		var answer map[string]any
		if err := json.Unmarshal([]byte(line), &answer); err != nil {
			t.Fatalf("the server wrote something that is not JSON-RPC: %q", line)
		}
		answers = append(answers, answer)
	}
	return answers
}

func toolNames(t *testing.T, answer map[string]any) []string {
	t.Helper()
	result, ok := answer["result"].(map[string]any)
	if !ok {
		t.Fatalf("tools/list did not come back with a result: %v", answer)
	}
	listed, ok := result["tools"].([]any)
	if !ok {
		t.Fatalf("tools/list came back without a tools array: %v", result)
	}
	names := make([]string, 0, len(listed))
	for _, entry := range listed {
		tool, ok := entry.(map[string]any)
		if !ok {
			t.Fatalf("a tool is not an object: %v", entry)
		}
		name, ok := tool["name"].(string)
		if !ok || name == "" {
			t.Fatalf("a tool has no name: %v", tool)
		}
		if _, has := tool["inputSchema"]; !has {
			t.Fatalf("tool %q has no inputSchema — a CLI would load it and find nothing to call", name)
		}
		names = append(names, name)
	}
	return names
}

// ── the two faces are one thing (T139, FR-013a) ──────────────────────────────

func TestBothFacesOfferExactlyTheSameCommands(t *testing.T) {
	// This is the test that keeps *one thing, two faces* from quietly becoming two
	// installations with two lists. Add a command and forget a face, and this goes red — which
	// is the only reason the promise is worth anything, because both faces are generated from
	// one list and nothing but a test can stop somebody writing a second one.
	for _, env := range []Environment{
		{Server: "http://x", RunToken: "armr_run_x", TaskID: "t", ProjectID: "p"},
		{Server: "http://x", RunToken: "armr_run_x", ProjectID: "p"},
		{Server: "http://x", RunToken: "armr_run_x"},
	} {
		answers := speak(t, env, `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
		if len(answers) != 1 {
			t.Fatalf("wanted one answer, got %d", len(answers))
		}
		seen := toolNames(t, answers[0])

		wanted := map[string]bool{}
		for _, cmd := range Commands(env) {
			wanted[cmd.ToolName()] = true
		}

		// Counted, not merely compared: research-multica §7 records the failure this guards
		// against — a config envelope of the wrong shape saves perfectly well and yields
		// **zero** tools, with one warning in a log nobody reads. A test that only checked
		// names would pass on an empty list.
		if len(seen) != len(wanted) {
			t.Fatalf("the agent sees %d tools and the run has %d commands: %v", len(seen), len(wanted), seen)
		}
		if len(seen) == 0 {
			t.Fatal("the agent sees no tools at all")
		}
		for _, name := range seen {
			if !wanted[name] {
				t.Fatalf("MCP offers %q, which this run's command list does not have", name)
			}
			delete(wanted, name)
		}
		for name := range wanted {
			t.Fatalf("the command list has %q and MCP does not offer it", name)
		}
	}
}

func TestTheToolsAnAgentSeesAreTheOnesItsRunIsAbout(t *testing.T) {
	// The toolset **is** the scope (FR-013d): a run about one task is not handed the Leader's
	// tools and then refused — it is never handed them.
	worker := speak(t,
		Environment{Server: "http://x", RunToken: "armr_run_x", TaskID: "t", ProjectID: "p"},
		`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
	for _, name := range toolNames(t, worker[0]) {
		if strings.HasPrefix(name, "project_") {
			t.Fatalf("a run about one task was offered %q", name)
		}
	}

	leader := speak(t,
		Environment{Server: "http://x", RunToken: "armr_run_x", ProjectID: "p"},
		`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
	for _, name := range toolNames(t, leader[0]) {
		if strings.HasPrefix(name, "task_") {
			t.Fatalf("a run about a project was offered %q, which needs a task it does not have", name)
		}
	}
}

// ── the protocol itself (T139) ───────────────────────────────────────────────

func TestInitializeAnswersInARevisionTheClientAskedForWhenWeKnowIt(t *testing.T) {
	answers := speak(t,
		Environment{Server: "http://x", RunToken: "armr_run_x", TaskID: "t"},
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}`)

	result := answers[0]["result"].(map[string]any)
	if result["protocolVersion"] != "2025-06-18" {
		t.Fatalf("answered in %v", result["protocolVersion"])
	}
	if _, ok := result["capabilities"].(map[string]any)["tools"]; !ok {
		t.Fatalf("the server did not say it has tools: %v", result["capabilities"])
	}
}

func TestAnUnknownRevisionIsAnsweredInOursRatherThanEchoedBack(t *testing.T) {
	// Echoing back whatever was asked for is the worse of the two failures: the client goes on
	// to use a feature this server does not have, and finds out one call later.
	answers := speak(t,
		Environment{Server: "http://x", RunToken: "armr_run_x", TaskID: "t"},
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"1999-01-01"}}`)

	if got := answers[0]["result"].(map[string]any)["protocolVersion"]; got != protocolVersion {
		t.Fatalf("answered in %v, wanted %s", got, protocolVersion)
	}
}

func TestANotificationIsNeverAnswered(t *testing.T) {
	answers := speak(t,
		Environment{Server: "http://x", RunToken: "armr_run_x", TaskID: "t"},
		`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
		`{"jsonrpc":"2.0","id":7,"method":"ping"}`)

	if len(answers) != 1 {
		t.Fatalf("wanted exactly one answer, got %d: %v", len(answers), answers)
	}
	if answers[0]["id"].(float64) != 7 {
		t.Fatalf("answered the wrong message: %v", answers[0])
	}
}

func TestCallingATool(t *testing.T) {
	server := armarius(t)
	answers := speak(t, server.env(),
		`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"task_comment","arguments":{"body":"hello"}}}`)

	result := answers[0]["result"].(map[string]any)
	if result["isError"] != false {
		t.Fatalf("a call that worked came back as an error: %v", result)
	}
	if server.path != "/agent/tasks/task-1/comment" {
		t.Fatalf("the call went to %s", server.path)
	}
	text := result["content"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(text, `"ok":true`) {
		t.Fatalf("the server's answer did not reach the agent: %q", text)
	}
}

func TestARefusalIsAToolErrorAndNotAProtocolError(t *testing.T) {
	// The distinction is the protocol's and it matters: a JSON-RPC error says the call could not
	// be made, while a tool error says it was made and Armarius said no — and only the second
	// is something the agent can read and act on.
	server := armarius(t)
	server.status = 409
	server.answer = `{"detail":"A task closes only with both signatures.","code":"task_needs_signatures","params":{}}`

	answers := speak(t, server.env(),
		`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"task_status","arguments":{"status":"done"}}}`)

	if _, isProtocolError := answers[0]["error"]; isProtocolError {
		t.Fatalf("a refusal came back as a protocol error: %v", answers[0])
	}
	result := answers[0]["result"].(map[string]any)
	if result["isError"] != true {
		t.Fatalf("a refusal did not come back marked as one: %v", result)
	}
	text := result["content"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(text, "task_needs_signatures") {
		t.Fatalf("the agent cannot tell which rule said no: %q", text)
	}
}

func TestAToolThisRunDoesNotHaveIsNamedRatherThanMerelyRefused(t *testing.T) {
	answers := speak(t,
		Environment{Server: "http://x", RunToken: "armr_run_x", TaskID: "t", ProjectID: "p"},
		`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"project_queue","arguments":{}}}`)

	result := answers[0]["result"].(map[string]any)
	if result["isError"] != true {
		t.Fatalf("a run about one task was allowed a Leader's tool: %v", result)
	}
	text := result["content"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(text, "project_queue") {
		t.Fatalf("the refusal does not say what was asked for: %q", text)
	}
}

func TestAnUnknownMethodIsAProtocolError(t *testing.T) {
	answers := speak(t,
		Environment{Server: "http://x", RunToken: "armr_run_x", TaskID: "t"},
		`{"jsonrpc":"2.0","id":1,"method":"resources/list"}`)

	if answers[0]["error"] == nil {
		t.Fatalf("an unknown method was answered as if it worked: %v", answers[0])
	}
}
