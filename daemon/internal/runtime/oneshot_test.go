package runtime

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	goos "runtime"
	"strings"
	"testing"
	"time"
)

// The three lines below are the real shapes, copied from a run of claude 2.1.226 on 2026-08-26.
// Written out rather than summarised: a parser tested against a shape somebody remembered is a
// parser tested against nothing.
const (
	initLine = `{"type":"system","subtype":"init","cwd":"/tmp","session_id":"76342bdf-65bf-4ff5-b7ad-88f612dc929f","model":"claude-opus-5"}`
	sayLine  = `{"type":"assistant","message":{"model":"claude-opus-5","role":"assistant","content":[{"type":"text","text":"ok"}]},"session_id":"76342bdf-65bf-4ff5-b7ad-88f612dc929f"}`
	doneLine = `{"is_error":false,"num_turns":1,"session_id":"76342bdf-65bf-4ff5-b7ad-88f612dc929f","usage":{"input_tokens":2,"output_tokens":4},"subtype":"success","result":"ok","type":"result"}`
)

// fakeCLI writes a program that behaves like an agent CLI and answers the path to it.
func fakeCLI(t *testing.T, script string) string {
	t.Helper()
	if goos.GOOS == "windows" {
		t.Skip("chương trình giả trong bài kiểm này viết bằng shell")
	}
	path := filepath.Join(t.TempDir(), "fake-cli")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+script), 0o700); err != nil { //nolint:gosec // a test's own scratch program
		t.Fatalf("dựng CLI giả: %v", err)
	}
	return path
}

// aTurn runs one turn against a fake CLI and collects everything it emitted.
func aTurn(t *testing.T, req Request) ([]Event, Outcome, error) {
	t.Helper()
	if req.CLI == "" {
		req.CLI = "claude_code"
	}
	if req.WorkDir == "" {
		req.WorkDir = t.TempDir()
	}
	if req.Message == "" {
		req.Message = "Your instructions: be Marin.\n"
	}
	req.Env = append(req.Env, "PATH="+os.Getenv("PATH"))

	var events []Event
	out, err := OneShot{}.Run(context.Background(), req, func(e Event) { events = append(events, e) })
	return events, out, err
}

func TestTheMessageReachesTheAgentWithoutPassingThroughTheProcessTable(t *testing.T) {
	// On standard input, not as an argument. Two reasons, and the second is the one that keeps
	// mattering as briefs grow: a message on the command line is visible to everyone on a shared
	// machine through `ps`, and its length is the operating system's business.
	seen := filepath.Join(t.TempDir(), "seen")
	cli := fakeCLI(t, `cat > `+seen+`.stdin
echo "$@" > `+seen+`.args
echo '`+doneLine+`'`)

	message := "Your instructions: be Marin.\nThe project: Apollo.\n"
	if _, _, err := aTurn(t, Request{Binary: cli, Message: message}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	if got := readFile(t, seen+".stdin"); got != message {
		t.Fatalf("agent nhận được %q", got)
	}
	if got := readFile(t, seen+".args"); strings.Contains(got, "Marin") {
		t.Fatalf("thông điệp đi qua dòng lệnh: %q", got)
	}
}

func TestWhatTheAgentSaysArrivesWhileItIsStillWorking(t *testing.T) {
	// FR-015: events travel during the run, not gathered up at the end. Measured rather than
	// asserted about the code — the whole point is what a person watching would see.
	cli := fakeCLI(t, `echo '`+initLine+`'
echo '`+sayLine+`'
sleep 0.4
echo '`+doneLine+`'`)

	var firstAt time.Time
	started := time.Now()
	_, err := OneShot{}.Run(context.Background(), Request{
		CLI: "claude_code", Binary: cli, WorkDir: t.TempDir(), Message: "hello",
		Env: []string{"PATH=" + os.Getenv("PATH")},
	}, func(Event) {
		if firstAt.IsZero() {
			firstAt = time.Now()
		}
	})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	if firstAt.IsZero() {
		t.Fatal("không có diễn biến nào tới nơi")
	}
	if waited := time.Since(started); waited-firstAt.Sub(started) < 300*time.Millisecond {
		t.Fatalf("diễn biến chỉ tới khi lượt chạy đã xong: sự kiện đầu sau %s, cả lượt %s",
			firstAt.Sub(started), waited)
	}
}

func TestTheSessionHandleComesBackSoTheNextRunCanCarryOn(t *testing.T) {
	// FR-023. Taken from whichever line carries it first, so a turn that dies halfway still
	// leaves the handle behind.
	cli := fakeCLI(t, `echo '`+initLine+`'
exit 1`)

	_, out, err := aTurn(t, Request{Binary: cli})
	if err == nil {
		t.Fatal("CLI hỏng giữa chừng mà lượt chạy vẫn coi là xong")
	}
	if out.Session != "76342bdf-65bf-4ff5-b7ad-88f612dc929f" {
		t.Fatalf("mã phiên là %q", out.Session)
	}
}

func TestCarryingOnAConversationIsAskedForOnTheCommandLine(t *testing.T) {
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	if _, _, err := aTurn(t, Request{Binary: cli, Session: "an-old-session"}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	if got := readFile(t, seen); !strings.Contains(got, "--resume an-old-session") {
		t.Fatalf("không xin nối lại phiên cũ: %q", got)
	}
}

func TestANewConversationDoesNotAskToResumeAnything(t *testing.T) {
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	if _, _, err := aTurn(t, Request{Binary: cli}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	if got := readFile(t, seen); strings.Contains(got, "--resume") {
		t.Fatalf("phiên mới mà vẫn xin nối lại: %q", got)
	}
}

func TestToolArgumentsTravelInFullAndToolResultsDoNotTravelAtAll(t *testing.T) {
	// FR-043 asks for the whole of the arguments; FR-043a says the *result* must never leave
	// this machine. The summary that may travel is built by the layer that owns the threshold
	// (task T095), so nothing of the result belongs in the event at this point.
	const call = `{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_1","name":"read_file","input":{"path":"/etc/hosts"}}]},"session_id":"s"}`
	const answer = `{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_1","is_error":false,"content":"127.0.0.1 localhost SECRET"}]},"session_id":"s"}`
	cli := fakeCLI(t, `echo '`+call+`'
echo '`+answer+`'
echo '`+doneLine+`'`)

	events, _, err := aTurn(t, Request{Binary: cli})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	started := only(t, events, EventToolStarted)
	if started.Payload["name"] != "read_file" {
		t.Fatalf("tên công cụ: %v", started.Payload["name"])
	}
	args, ok := started.Payload["args"].(map[string]any)
	if !ok || args["path"] != "/etc/hosts" {
		t.Fatalf("tham số gọi công cụ không đi đủ: %v", started.Payload["args"])
	}

	finished := only(t, events, EventToolCompleted)
	written, err := json.Marshal(finished.Payload)
	if err != nil {
		t.Fatalf("đọc lại phần thân: %v", err)
	}
	if strings.Contains(string(written), "SECRET") {
		t.Fatalf("toàn văn kết quả công cụ rời khỏi máy: %s", written)
	}
}

func TestTheAgentsOwnWordsAreKept(t *testing.T) {
	cli := fakeCLI(t, `echo '`+sayLine+`'
echo '`+doneLine+`'`)

	events, out, err := aTurn(t, Request{Binary: cli})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	if said := only(t, events, EventAssistantMessage); said.Payload["text"] != "ok" {
		t.Fatalf("chữ agent nói: %v", said.Payload["text"])
	}
	if out.Usage["output_tokens"] == nil {
		t.Fatalf("không giữ lại lượt chạy tốn bao nhiêu: %v", out.Usage)
	}
}

func TestAnAgentThatReportsItFailedIsRecordedRatherThanHidden(t *testing.T) {
	const failed = `{"type":"result","subtype":"error_during_execution","is_error":true,"session_id":"s"}`
	cli := fakeCLI(t, `echo '`+failed+`'`)

	events, _, err := aTurn(t, Request{Binary: cli})
	if err != nil {
		// Running it worked; the agent's own answer is what went badly, and that is a record,
		// not a broken run.
		t.Fatalf("chạy một lượt: %v", err)
	}
	if wrong := only(t, events, EventRunError); wrong.Payload["why"] != "error_during_execution" {
		t.Fatalf("lý do hỏng: %v", wrong.Payload)
	}
}

func TestWhatTheCLIComplainedAboutIsInTheError(t *testing.T) {
	cli := fakeCLI(t, `echo "not logged in" >&2
exit 3`)

	_, _, err := aTurn(t, Request{Binary: cli})
	if err == nil {
		t.Fatal("CLI thoát với mã lỗi mà lượt chạy vẫn coi là xong")
	}
	if !strings.Contains(err.Error(), "not logged in") {
		t.Fatalf("lỗi không nói CLI kêu gì: %v", err)
	}
}

func TestLinesThisFamilyDoesNotRecogniseProduceNothing(t *testing.T) {
	// These streams carry banners, progress and warnings alongside the events. Guessing at an
	// unknown shape would put invented facts into a record meant to be evidence.
	cli := fakeCLI(t, `echo "Welcome to the CLI!"
echo '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning"}}'
echo '{'
echo '`+doneLine+`'`)

	events, _, err := aTurn(t, Request{Binary: cli})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}
	if len(events) != 0 {
		t.Fatalf("dòng lạ vẫn đẻ ra %d diễn biến: %v", len(events), events)
	}
}

func TestACLIThisFamilyDoesNotKnowIsRefused(t *testing.T) {
	// Gemini CLI is the ACP family's, and unverified besides (T013).
	if _, _, err := aTurn(t, Request{CLI: "gemini", Binary: fakeCLI(t, "exit 0")}); err == nil {
		t.Fatal("CLI không thuộc họ này mà vẫn chạy được")
	}
}

func TestRunningAnAgentWithNothingToSayIsRefused(t *testing.T) {
	// It would look like a working run from every angle: a process appears, it ends.
	_, err := OneShot{}.Run(context.Background(), Request{
		CLI: "claude_code", Binary: fakeCLI(t, "exit 0"), WorkDir: t.TempDir(),
	}, nil)
	if err == nil {
		t.Fatal("chạy agent mà không có gì để nói với nó")
	}
}

func TestTheAgentWorksInTheTasksDirectory(t *testing.T) {
	work := t.TempDir()
	seen := filepath.Join(t.TempDir(), "cwd")
	cli := fakeCLI(t, `pwd > `+seen+`
echo '`+doneLine+`'`)

	if _, _, err := aTurn(t, Request{Binary: cli, WorkDir: work}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	got := strings.TrimSpace(readFile(t, seen))
	if resolved, err := filepath.EvalSymlinks(work); err == nil {
		work = resolved
	}
	if got != work {
		t.Fatalf("agent chạy ở %s, không phải thư mục của đầu việc %s", got, work)
	}
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	raw, err := os.ReadFile(path) //nolint:gosec // a path this test just made up
	if err != nil {
		t.Fatalf("đọc %s: %v", path, err)
	}
	return string(raw)
}

// only answers the single event of one type, and fails when there is not exactly one.
func only(t *testing.T, events []Event, kind string) Event {
	t.Helper()
	var found []Event
	for _, e := range events {
		if e.Type == kind {
			found = append(found, e)
		}
	}
	if len(found) != 1 {
		t.Fatalf("mong đúng một %s, có %d: %v", kind, len(found), events)
	}
	return found[0]
}
