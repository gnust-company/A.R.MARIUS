package runtime

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	goos "runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
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

func TestToolArgumentsTravelInFullAndOnlyASummaryOfTheResultDoes(t *testing.T) {
	// FR-043 asks for the whole of the arguments; FR-043a says only a **summary** of the result
	// may leave — its size, its kind, and an opening slice cut to the threshold. So the tail is
	// what has to be proven to stay home, and the tail is where the recognisable string goes: a
	// test that puts it at the front would pass on a build that sends everything.
	const tail = "SECRET-IN-THE-TAIL"
	whole := strings.Repeat("a", DefaultResultLimit) + tail
	call := `{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_1","name":"read_file","input":{"path":"/etc/hosts"}}]},"session_id":"s"}`
	answer := `{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_1","is_error":false,"content":"` + whole + `"}]},"session_id":"s"}`
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
	if strings.Contains(string(written), tail) {
		t.Fatalf("phần đuôi của kết quả rời khỏi máy: %s", written)
	}
	if finished.Payload["bytes"] != len(whole) {
		t.Fatalf("kích thước thật không được ghi lại: %v, phải là %d", finished.Payload["bytes"], len(whole))
	}
	if !finished.Truncated {
		t.Fatal("cắt rồi mà không nói là đã cắt — người đọc tưởng đó là toàn bộ kết quả (FR-043b)")
	}
	if finished.OmissionReason != TruncatedByPolicy {
		t.Fatalf("lý do thiếu: %q", finished.OmissionReason)
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

func TestThisRunsOwnToolsAreNamedOnTheCommandLine(t *testing.T) {
	// FR-013a asks for the native tool face to be declared **per run**. Claude Code takes a file
	// on the command line, which is what makes that possible: the file it would otherwise find
	// by itself is the project-scoped one, and that has to be approved by somebody sitting at
	// the machine — where nobody is.
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	declared := filepath.Join(t.TempDir(), "mcp.json")
	if _, _, err := aTurn(t, Request{Binary: cli, ToolConfig: declared}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	got := readFile(t, seen)
	if !strings.Contains(got, "--mcp-config "+declared) {
		t.Fatalf("bộ công cụ của lượt chạy không được khai: %q", got)
	}
	// The operator's own tools are theirs. FR-013a says ours must be declared per run and never
	// written into their configuration; it does not say theirs must be switched off.
	if strings.Contains(got, "--strict-mcp-config") {
		t.Fatalf("công cụ của người dùng bị tắt mà không ai yêu cầu: %q", got)
	}
}

func TestARunGivenNoToolsAsksForNoFile(t *testing.T) {
	// A CLI whose loader is not known still runs, and still has the command face. Naming an
	// empty path would make it refuse to start at all.
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	if _, _, err := aTurn(t, Request{Binary: cli}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}
	if got := readFile(t, seen); strings.Contains(got, "--mcp-config") {
		t.Fatalf("khai một tệp không có: %q", got)
	}
}

func TestToolsThatWereHandedOverAreAlsoAllowedToBeUsed(t *testing.T) {
	// Đo thật, không suy đoán (claude 2.1.226, 2026-08-29): khai mà không cho phép thì công cụ
	// **hiện ra** trong danh sách của agent, agent gọi, và lời gọi trả về *permission denied* —
	// không có ai ngồi đây mà cấp. Một bộ công cụ được trao rồi bị chặn mọi lần dùng là một lượt
	// chạy không báo cáo lại được gì.
	//
	// Danh sách cho phép lấy từ chính lời khai, nên phạm vi được trao và phạm vi được dùng là
	// một (FR-013d) — và **chỉ** máy chủ công cụ của ta, không đụng thứ agent xin làm ngoài đời
	// (FR-013b).
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	_, _, err := aTurn(t, Request{
		Binary:      cli,
		ToolConfig:  filepath.Join(t.TempDir(), "mcp.json"),
		ToolServers: []execenv.ToolServer{{Name: "armarius", Command: "/anywhere"}},
	})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	got := readFile(t, seen)
	if !strings.Contains(got, "--allowed-tools mcp__armarius") {
		t.Fatalf("công cụ được trao mà không được phép dùng: %q", got)
	}
}

func TestARunWithNoToolsAllowsNothingExtra(t *testing.T) {
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	if _, _, err := aTurn(t, Request{Binary: cli}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}
	if got := readFile(t, seen); strings.Contains(got, "--allowed-tools") {
		t.Fatalf("cho phép một thứ không ai trao: %q", got)
	}
}

func TestWhatThePersonPickedReachesTheCLIAsItsOwnFlags(t *testing.T) {
	// FR-007k, chặng cuối. Server gửi xuống **tên chung** (`model`, `thinking_level`); chỉ
	// bên này biết CLI ấy gọi chúng là `--model` và `--effort`. Hai cái tên trong bảng đây là
	// đúng hai cái cờ phép dò đã đọc dải giá trị ra — đọc danh sách ở một chỗ rồi tiêu ở chỗ
	// khác là cách một màn hình bày ra thiết lập chẳng áp vào đâu.
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	_, _, err := aTurn(t, Request{
		Binary:  cli,
		Options: map[string]string{"model": "opus", "thinking_level": "high"},
	})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	got := readFile(t, seen)
	if !strings.Contains(got, "--model opus") {
		t.Fatalf("model người dùng chọn không tới CLI: %q", got)
	}
	if !strings.Contains(got, "--effort high") {
		t.Fatalf("mức nghĩ người dùng chọn không tới CLI: %q", got)
	}
}

func TestASettingThisCLIHasNoFlagForIsDroppedRatherThanGuessedAt(t *testing.T) {
	// Chỗ làm khai gì thì người dùng chọn nấy, nhưng binary trên máy có thể đã bị thay bằng
	// bản nhận ít cờ hơn. Chạy trên mặc định vẫn hơn từ chối khởi chạy — và đoán một cái cờ
	// thì CLI từ chối start, cả lượt chạy hỏng vì một thiết lập không ai cần tới.
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" > `+seen+`
echo '`+doneLine+`'`)

	if _, _, err := aTurn(t, Request{
		Binary:  cli,
		Options: map[string]string{"service_tier": "priority", "model": ""},
	}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	got := readFile(t, seen)
	if strings.Contains(got, "service_tier") || strings.Contains(got, "priority") {
		t.Fatalf("bịa ra một cái cờ cho thiết lập CLI này không có: %q", got)
	}
	if strings.Contains(got, "--model") {
		t.Fatalf("bỏ trống mà vẫn truyền cờ — mất mặc định của chính CLI: %q", got)
	}
}

func TestTheSameChoicesProduceTheSameCommandLineTwice(t *testing.T) {
	// Một lượt chạy không dựng lại được từ chính bản ghi của nó là một lượt chạy không ai gỡ
	// rối được. Thứ tự duyệt map trong Go là ngẫu nhiên, nên đây không phải chuyện thẩm mỹ.
	seen := filepath.Join(t.TempDir(), "args")
	cli := fakeCLI(t, `echo "$@" >> `+seen+`
echo '`+doneLine+`'`)
	options := map[string]string{"model": "opus", "thinking_level": "high"}

	for range 6 {
		if _, _, err := aTurn(t, Request{Binary: cli, Options: options}); err != nil {
			t.Fatalf("chạy một lượt: %v", err)
		}
	}

	lines := strings.Split(strings.TrimSpace(readFile(t, seen)), "\n")
	for i, line := range lines {
		if line != lines[0] {
			t.Fatalf("lượt %d ra dòng lệnh khác lượt đầu:\n%q\n%q", i, lines[0], line)
		}
	}
}

// ── một handle bị CLI từ chối ────────────────────────────────────────────────

// Đo thật, Claude Code 2.1.226: `--resume` với một id nó không tìm thấy in
// `No conversation found with session ID: …`, thoát 1, báo `num_turns: 0`, và **trả lại chính
// cái id ấy** ở trường `session_id`. Họ chạy-một-phát không có đường nào để được báo giữa lượt
// rằng phiên không nạp được — bên ACP học điều đó qua một lời từ chối của giao thức — nên phải
// học từ bên ngoài: đã đưa handle, kết thúc tệ, và không nghe agent nói gì.
const refusedLine = `{"type":"result","subtype":"error_during_execution","is_error":true,"num_turns":0,"session_id":"00000000-dead-beef-0000-000000000000","errors":["No conversation found with session ID: 00000000-dead-beef-0000-000000000000"]}`

// resumeRefusingCLI hỏng khi được đưa `--resume`, chạy bình thường khi không.
func resumeRefusingCLI(t *testing.T, tally string) string {
	t.Helper()
	return fakeCLI(t, `cat >> `+tally+`.stdin
echo "$@" >> `+tally+`.args
for arg in "$@"; do
  if [ "$arg" = "--resume" ]; then
    echo '`+refusedLine+`'
    exit 1
  fi
done
echo '`+initLine+`'
echo '`+sayLine+`'
echo '`+doneLine+`'`)
}

// FR-025 cho **cả hai** họ giao thức, không riêng ACP: mất mạch thì mở mạch mới và nói ra.
func TestAHandleTheCLIRefusesStartsAFreshTurnRatherThanFailingTheRun(t *testing.T) {
	tally := filepath.Join(t.TempDir(), "seen")
	events, out, err := aTurn(t, Request{
		Binary:  resumeRefusingCLI(t, tally),
		Session: "00000000-dead-beef-0000-000000000000",
	})
	if err != nil {
		t.Fatalf("lượt chạy hỏng hẳn thay vì mở mạch mới: %v", err)
	}
	if !out.SessionRefused {
		t.Error("kết quả không nói rằng handle đã bị từ chối")
	}
	if out.Session != "76342bdf-65bf-4ff5-b7ad-88f612dc929f" {
		t.Errorf("handle mang về là %q — phải là mạch **mới**, không phải cái vừa bị từ chối", out.Session)
	}

	var announced bool
	for _, e := range events {
		if e.Type == EventRunError && e.Payload["code"] == RestartRefused {
			announced = true
		}
	}
	if !announced {
		t.Error("nhật ký không có dòng nào nói mạch cũ đã mất")
	}

	// Và agent phải **đọc** được câu ấy, không chỉ có nó trong nhật ký (SC-007).
	stdin, readErr := os.ReadFile(tally + ".stdin")
	if readErr != nil {
		t.Fatal(readErr)
	}
	if !strings.Contains(string(stdin), "new conversation") {
		t.Errorf("agent không hề được báo là đang bắt đầu lại; nó đọc: %q", stdin)
	}
}

// Lần thứ hai chạy **không** kèm `--resume`. Nếu vẫn kèm thì nó hỏng đúng như lần đầu, và cả
// phép thử lại chỉ là hỏng hai lần thay vì một.
func TestTheSecondAttemptDoesNotCarryTheHandleThatJustFailed(t *testing.T) {
	tally := filepath.Join(t.TempDir(), "seen")
	if _, _, err := aTurn(t, Request{
		Binary:  resumeRefusingCLI(t, tally),
		Session: "00000000-dead-beef-0000-000000000000",
	}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}
	args, err := os.ReadFile(tally + ".args")
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(args)), "\n")
	if len(lines) != 2 {
		t.Fatalf("CLI được chạy %d lần, mong đúng hai", len(lines))
	}
	if !strings.Contains(lines[0], "--resume") {
		t.Errorf("lần đầu không hề mang handle: %q", lines[0])
	}
	if strings.Contains(lines[1], "--resume") {
		t.Errorf("lần thử lại vẫn mang đúng cái handle vừa hỏng: %q", lines[1])
	}
}

// Ranh giới quan trọng nhất của phép thử lại: một lượt chạy đã **làm gì đó** thì không bao giờ
// chạy lại. Một lỗi không phải là agent đang làm việc; một dòng agent nói ra thì có.
func TestATurnTheAgentActuallyWorkedInIsNeverRunTwice(t *testing.T) {
	tally := filepath.Join(t.TempDir(), "seen")
	cli := fakeCLI(t, `echo "$@" >> `+tally+`.args
echo '`+initLine+`'
echo '`+sayLine+`'
exit 1`)

	if _, _, err := aTurn(t, Request{Binary: cli, Session: "sess-abc"}); err == nil {
		t.Fatal("một lượt chạy hỏng giữa chừng lại báo là xong")
	}
	args, err := os.ReadFile(tally + ".args")
	if err != nil {
		t.Fatal(err)
	}
	if lines := strings.Split(strings.TrimSpace(string(args)), "\n"); len(lines) != 1 {
		t.Errorf("CLI được chạy %d lần — agent đã nói rồi thì chạy lại là làm lại việc nó đã làm",
			len(lines))
	}
}

// Không có handle thì không có gì để đổ lỗi, và không có gì để thử lại.
func TestAFailingTurnThatWasGivenNoHandleIsNotRunTwice(t *testing.T) {
	tally := filepath.Join(t.TempDir(), "seen")
	cli := fakeCLI(t, `echo "$@" >> `+tally+`.args
exit 1`)

	if _, _, err := aTurn(t, Request{Binary: cli}); err == nil {
		t.Fatal("một lượt chạy hỏng lại báo là xong")
	}
	args, err := os.ReadFile(tally + ".args")
	if err != nil {
		t.Fatal(err)
	}
	if lines := strings.Split(strings.TrimSpace(string(args)), "\n"); len(lines) != 1 {
		t.Errorf("CLI được chạy %d lần, mong đúng một", len(lines))
	}
}

// Bị dừng từ bên ngoài — daemon tắt, hoặc chó canh cắt một agent im lặng — nhìn từ trong đây
// giống hệt một lần hỏng. Khởi động một tiến trình thứ hai trên đường ra là đúng thứ không được
// phép xảy ra.
func TestARunEndedFromOutsideIsNotStartedAgain(t *testing.T) {
	tally := filepath.Join(t.TempDir(), "seen")
	cli := fakeCLI(t, `echo "$@" >> `+tally+`.args
sleep 30`)

	ctx, stop := context.WithCancel(context.Background())
	go func() { time.Sleep(150 * time.Millisecond); stop() }()
	_, err := OneShot{}.Run(ctx, Request{
		CLI: "claude_code", Binary: cli, WorkDir: t.TempDir(),
		Message: "Your instructions: be Marin.\n", Session: "sess-abc",
		Env: []string{"PATH=" + os.Getenv("PATH")},
	}, func(Event) {})
	if err == nil {
		t.Fatal("một lượt chạy bị cắt lại báo là xong")
	}
	args, readErr := os.ReadFile(tally + ".args")
	if readErr != nil {
		t.Fatal(readErr)
	}
	if lines := strings.Split(strings.TrimSpace(string(args)), "\n"); len(lines) != 1 {
		t.Errorf("CLI được chạy %d lần trên đường daemon tắt", len(lines))
	}
}

// ── Which wall a run hit, when the CLI said so (T124a, FR-032a, FR-007c) ─────
//
// The shape below is the one measured live on 2026-09-04, running the quickstart end to end on
// Claude Code 2.1.252 with an account past its allowance: one assistant line naming the limit,
// then a `result` line whose structured fields say **nothing** about which wall it was —
// `is_error: true` beside `subtype: "success"` — and exit 1. So the sentence is the only place
// the difference is stated, and these tests hold the daemon to reading exactly that and no more.

const (
	limitLine = `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text",` +
		`"text":"You've hit your session limit · resets 5:50pm (Asia/Ho_Chi_Minh)"}]},"session_id":"s"}`
	badResultLine = `{"type":"result","subtype":"success","is_error":true,"session_id":"s"}`
)

// sayingCLI writes a program that prints these lines and then exits with this code.
//
// Through a file rather than through the shell: the measured sentence carries an apostrophe and
// a pair of brackets, and a shell script that quotes them wrong fails as a *syntax error* — a
// green-looking failure that measures the quoting instead of the reading.
func sayingCLI(t *testing.T, exit int, lines ...string) string {
	t.Helper()
	said := filepath.Join(t.TempDir(), "said")
	if err := os.WriteFile(said, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		t.Fatalf("viết ra thứ CLI sẽ in: %v", err)
	}
	return fakeCLI(t, "cat "+said+"\nexit "+strconv.Itoa(exit))
}

func TestAnExhaustedQuotaIsReportedAsSomethingAPersonHasToClear(t *testing.T) {
	cli := sayingCLI(t, 1, limitLine, badResultLine)

	_, out, err := aTurn(t, Request{Binary: cli})
	if err == nil {
		t.Fatal("CLI thoát 1 mà lượt chạy vẫn coi là xong")
	}
	if out.Failure != "quota_exhausted" {
		t.Fatalf("không đọc ra cạn hạn mức: %q", out.Failure)
	}
}

func TestAnEndingThisFamilyHasNotBeenWatchedSayingIsLeftUnclassified(t *testing.T) {
	// FR-039's rule, applied to the failure side: a line nobody measured produces nothing.
	// Guessing here writes a fabricated cause into the record kept as evidence, and stops a
	// run being retried on the strength of it.
	const unseen = `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text",` +
		`"text":"Error: your monthly allowance is spent."}]},"session_id":"s"}`
	cli := sayingCLI(t, 1, unseen, badResultLine)

	_, out, err := aTurn(t, Request{Binary: cli})
	if err == nil {
		t.Fatal("CLI thoát 1 mà lượt chạy vẫn coi là xong")
	}
	if out.Failure != "" {
		t.Fatalf("đoán ra một lý do chưa từng đo được: %q", out.Failure)
	}
}

func TestACLIFamilyWithNothingMeasuredNamesNoWall(t *testing.T) {
	// Codex has never been run here at all (research §9, T130), so it has no table — and a
	// family with no table must answer *no verdict*, not fall through to another family's.
	var out Outcome
	hitAWall("codex", "You've hit your session limit · resets 5:50pm", &out)
	if out.Failure != "" {
		t.Fatalf("họ CLI chưa đo được lại nói ra một lý do: %q", out.Failure)
	}
}

func TestTheFirstWallNamedIsTheOneKept(t *testing.T) {
	// A CLI that says why it stopped says it once; everything after is the turn winding down.
	//
	// Seeded with a verdict this table could never produce, so an overwrite is *visible*: a
	// guard checked against the value it would be replaced with measures nothing.
	out := Outcome{Failure: "credential_rejected"}
	hitAWall("claude_code", "You've hit your session limit", &out)
	if out.Failure != "credential_rejected" {
		t.Fatalf("lý do đầu tiên bị ghi đè thành %q", out.Failure)
	}
}
