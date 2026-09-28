package runtime

import (
	"path/filepath"
	"strings"
	"testing"
)

// Bộ kiểm cho Gemini CLI chạy một lần mỗi lượt (FR-039f).
//
// Không bài nào bật `gemini` thật. Các dòng dưới đây dựng theo đúng những gì bundle `gemini 0.56.0`
// in ra ở chế độ `--output-format stream-json` (`JsonStreamEventType` và vòng không tương tác phát ra
// nó), cũng là những dòng daemon của Multica đọc khi còn chạy Gemini CLI.
const (
	geminiInit = `{"type":"init","timestamp":"2026-09-28T07:00:00.000Z","session_id":"8a3c1f0e-5b2d-4c7a-9e41-0d6f2b9c7a11","model":"auto-gemini-3"}`
	geminiEcho = `{"type":"message","timestamp":"2026-09-28T07:00:00.100Z","role":"user","content":"Your instructions: be Marin."}`
	geminiSay1 = `{"type":"message","timestamp":"2026-09-28T07:00:01.000Z","role":"assistant","content":"Reading ","delta":true}`
	geminiSay2 = `{"type":"message","timestamp":"2026-09-28T07:00:01.100Z","role":"assistant","content":"the task.","delta":true}`
	geminiCall = `{"type":"tool_use","timestamp":"2026-09-28T07:00:02.000Z","tool_name":"run_shell_command","tool_id":"run_shell_command-1759042802000-0","parameters":{"command":"armarius task show"}}`
	geminiDone = `{"type":"tool_result","timestamp":"2026-09-28T07:00:03.000Z","tool_id":"run_shell_command-1759042802000-0","status":"success","output":"Task T-1: write the report"}`
	geminiSay3 = `{"type":"message","timestamp":"2026-09-28T07:00:04.000Z","role":"assistant","content":"Done.","delta":true}`
	geminiEnd  = `{"type":"result","timestamp":"2026-09-28T07:00:05.000Z","status":"success","stats":{"total_tokens":130,"input_tokens":100,"output_tokens":30,"cached":0,"input":100,"duration_ms":5000,"tool_calls":1,"models":{}}}`
)

// geminiSays is a fake Gemini CLI that records its arguments, NUL-separated so a message with a
// line break in it stays one argument, and what reached its standard input, then prints lines.
func geminiSays(t *testing.T, lines ...string) (cli, args, stdin string) {
	t.Helper()
	dir := t.TempDir()
	args, stdin = filepath.Join(dir, "args"), filepath.Join(dir, "stdin")
	script := `printf '%s\0' "$@" > ` + args + `
cat > ` + stdin + `
`
	for _, line := range lines {
		script += "echo '" + line + "'\n"
	}
	return fakeCLI(t, script), args, stdin
}

func argsOf(t *testing.T, path string) []string {
	t.Helper()
	return strings.Split(strings.TrimSuffix(readFile(t, path), "\x00"), "\x00")
}

// Thông điệp đi bằng `-p`, y như daemon của Multica chạy gemini, và đầu vào chuẩn để trống: bundle
// đặt bất cứ thứ gì đọc được ở đó lên trước `-p`, nên gửi cả hai là agent đọc thông điệp hai lần.
func TestGeminiIsHandedItsMessageWithPAndNothingOnStandardInput(t *testing.T) {
	cli, args, stdin := geminiSays(t, geminiInit, geminiEnd)
	message := "Your instructions: be Marin.\nThe project: Apollo.\n"

	if _, _, err := aTurn(t, Request{CLI: "gemini", Binary: cli, Message: message}); err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	got := argsOf(t, args)
	want := []string{"-p", message, "--yolo", "--output-format", "stream-json"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("gemini được khởi chạy bằng %q, mong %q", got, want)
	}
	if said := readFile(t, stdin); said != "" {
		t.Fatalf("đầu vào chuẩn không trống: %q", said)
	}
}

// Mã phiên đi ra từ dòng `init`, và lần sau đi vào lại bằng `--resume` (FR-023).
func TestGeminiCarriesOnTheSessionItsInitLineGave(t *testing.T) {
	cli, args, _ := geminiSays(t, geminiInit, geminiEnd)

	_, out, err := aTurn(t, Request{CLI: "gemini", Binary: cli, Session: "an-earlier-session"})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	if got := strings.Join(argsOf(t, args), " "); !strings.Contains(got, "--resume an-earlier-session") {
		t.Fatalf("phiên cũ không được nối lại: %q", got)
	}
	if out.Session != "8a3c1f0e-5b2d-4c7a-9e41-0d6f2b9c7a11" {
		t.Fatalf("mã phiên trả về là %q", out.Session)
	}
}

// FR-035, FR-037: cùng một hợp đồng cho mọi CLI. Chữ của agent tới theo từng mảnh và được gom lại
// thành một đoạn trước mỗi việc khác nó làm; thông điệp gemini in lại (`role: user`) là của ta, không
// phải của agent, nên không vào bản ghi.
func TestWhatGeminiDoesComesOutAsTheSameEventsAsTheOtherCLIs(t *testing.T) {
	cli, _, _ := geminiSays(t,
		geminiInit, geminiEcho, geminiSay1, geminiSay2, geminiCall, geminiDone, geminiSay3, geminiEnd)

	events, out, err := aTurn(t, Request{CLI: "gemini", Binary: cli})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	var kinds []string
	for _, e := range events {
		kinds = append(kinds, e.Type)
	}
	want := []string{EventAssistantMessage, EventToolStarted, EventToolCompleted, EventAssistantMessage}
	if strings.Join(kinds, " ") != strings.Join(want, " ") {
		t.Fatalf("các diễn biến là %v, mong %v", kinds, want)
	}
	if said := events[0].Payload["text"]; said != "Reading the task." {
		t.Fatalf("các mảnh chữ không được gom thành một đoạn: %q", said)
	}
	if said := events[3].Payload["text"]; said != "Done." {
		t.Fatalf("đoạn cuối là %q", said)
	}
	call := events[1].Payload
	if call["name"] != "run_shell_command" || call["call"] != "run_shell_command-1759042802000-0" {
		t.Fatalf("lượt gọi công cụ: %v", call)
	}
	if args, _ := call["args"].(map[string]any); args["command"] != "armarius task show" {
		t.Fatalf("tham số gọi công cụ không đi đủ: %v", call)
	}
	if done := events[2].Payload; done["failed"] != false || done["bytes"] != len("Task T-1: write the report") {
		t.Fatalf("kết quả công cụ: %v", done)
	}
	if out.Usage["input_tokens"] != float64(100) {
		t.Fatalf("số token của lượt: %v", out.Usage)
	}
}

// Vắng không phải rỗng (FR-047): bundle bỏ hẳn trường `output` khi công cụ không có gì để hiện, và
// đó không phải một công cụ in ra chuỗi rỗng.
func TestAToolResultGeminiDidNotDisplayIsNotAnEmptyOne(t *testing.T) {
	cli, _, _ := geminiSays(t, geminiInit,
		`{"type":"tool_use","timestamp":"t","tool_name":"write_file","tool_id":"w-1","parameters":{"file_path":"a.md"}}`,
		`{"type":"tool_result","timestamp":"t","tool_id":"w-1","status":"error","error":{"type":"TOOL_EXECUTION_ERROR","message":"denied"}}`,
		geminiEnd)

	events, _, err := aTurn(t, Request{CLI: "gemini", Binary: cli})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	done := only(t, events, EventToolCompleted)
	if done.OmissionReason != NotExposedByCLI {
		t.Fatalf("lý do thiếu đầu ra: %q", done.OmissionReason)
	}
	if done.Payload["failed"] != true {
		t.Fatalf("công cụ hỏng mà sự kiện không nói: %v", done.Payload)
	}
}

// Cảnh báo là CLI kể chuyện thử lại hay một hook, và dòng sau có thể nói ngược lại; chỉ lỗi mới là sự
// thật của lượt này. Một lỗi rồi dòng `result` hỏng không kèm nguyên nhân là **một** chuyện, không
// phải hai.
func TestGeminiErrorsAreRecordedOnceAndItsWarningsNotAtAll(t *testing.T) {
	cli, _, _ := geminiSays(t, geminiInit,
		`{"type":"error","timestamp":"t","severity":"warning","message":"Retrying after a rate limit"}`,
		`{"type":"error","timestamp":"t","severity":"error","message":"Model stream ended with an invalid chunk"}`,
		`{"type":"result","timestamp":"t","status":"error","stats":{"total_tokens":0}}`)

	events, _, err := aTurn(t, Request{CLI: "gemini", Binary: cli})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	failed := only(t, events, EventRunError)
	if failed.Payload["code"] != "agent_reported_failure" ||
		failed.Payload["why"] != "Model stream ended with an invalid chunk" {
		t.Fatalf("lỗi ghi lại: %v", failed.Payload)
	}
}

// Đường hỏng nặng: bundle in một dòng `result` mang nguyên nhân rồi thoát.
func TestAFatalGeminiResultNamesItsCause(t *testing.T) {
	cli, _, _ := geminiSays(t, geminiInit,
		`{"type":"result","timestamp":"t","status":"error","error":{"type":"FatalAuthenticationError","message":"Please set an Auth method"},"stats":{"total_tokens":0}}`)

	events, _, err := aTurn(t, Request{CLI: "gemini", Binary: cli})
	if err != nil {
		t.Fatalf("chạy một lượt: %v", err)
	}

	if failed := only(t, events, EventRunError); failed.Payload["why"] != "Please set an Auth method" {
		t.Fatalf("lỗi ghi lại: %v", failed.Payload)
	}
}

// Một mã phiên gemini không tìm thấy làm nó thoát trước khi in gì (`invalidSessionIdentifier`). Đó
// đúng là hình dạng Run nhận ra: chạy lại không kèm mã ấy, bằng bản thông điệp có lịch sử (FR-025,
// FR-040c), và báo cho máy thôi đưa lại mã chết.
func TestAGeminiSessionItCannotFindIsStartedAgainWithoutIt(t *testing.T) {
	dir := t.TempDir()
	args := filepath.Join(dir, "args")
	cli := fakeCLI(t, `case "$*" in *--resume*) echo 'Error resuming session: Invalid session identifier' >&2; exit 1;; esac
printf '%s\0' "$@" > `+args+`
echo '`+geminiInit+`'
echo '`+geminiSay3+`'
echo '`+geminiEnd+`'`)

	_, out, err := aTurn(t, Request{
		CLI: "gemini", Binary: cli, Session: "a-dead-session",
		Message:      "Their message: and now?",
		FreshMessage: "Conversation so far: Patron: hello. Their message: and now?",
	})
	if err != nil {
		t.Fatalf("chạy lại không kèm mã phiên mà vẫn hỏng: %v", err)
	}

	if !out.SessionRefused {
		t.Fatal("mã phiên chết không được báo, lần sau máy sẽ đưa lại đúng nó")
	}
	if out.Session != "8a3c1f0e-5b2d-4c7a-9e41-0d6f2b9c7a11" {
		t.Fatalf("phiên dùng cho lượt này là %q", out.Session)
	}
	got := argsOf(t, args)
	if strings.Contains(strings.Join(got, " "), "--resume") {
		t.Fatalf("lần chạy lại vẫn kèm mã phiên: %q", got)
	}
	if len(got) < 2 || got[0] != "-p" || !strings.Contains(got[1], "Patron: hello") {
		t.Fatalf("lần chạy lại không được kể lại lịch sử: %q", got)
	}
}
