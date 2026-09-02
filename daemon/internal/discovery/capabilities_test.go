package discovery

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// claudeHelp is the shape of what `claude --help` prints, cut down to the lines the probe
// reads. Copied from claude 2.1.226 on 2026-08-25 rather than invented, so a test passing here
// means something about the real binary.
const claudeHelp = `Usage: claude [options] [command] [prompt]

Options:
  -c, --continue                        Continue the most recent conversation
  -r, --resume [value]                  Resume a conversation by session ID
  --output-format <format>              Output format (only works with --print):
                                        "text" (default), "json" (single
                                        result), or "stream-json" (realtime
                                        streaming)
  --effort <level>                      Effort level for the current session
                                        (low, medium, high, xhigh, max)
  --model <model>                       Model for the current session. Provide
                                        an alias for the latest model (e.g.
                                        'fable', 'opus', or 'sonnet') or a
                                        model's full name (e.g.
                                        'claude-fable-5')
`

func askedWith(printed string, err error) Options {
	return Options{
		Run: func(_ context.Context, _ string, _ ...string) ([]byte, error) {
			if err != nil {
				return nil, err
			}
			return []byte(printed), nil
		},
		// Arranged deliberately, and it is not decoration. Left out, this edge falls back to the
		// real one — and a test naming a Kind whose binary happens to be installed on the machine
		// running it would quietly start that binary and wait several seconds for a handshake.
		// Every test here says which peer it is talking to, or says there is none.
		Handshake: func(context.Context, string, []string, func(io.Writer, io.Reader) error) error {
			return errors.New("no ACP peer was arranged for this test")
		},
		Timeout: time.Second,
	}
}

func TestAOneShotCLIsCapabilitiesComeFromWhatItPrinted(t *testing.T) {
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}

	got := Probe(context.Background(), found, askedWith(claudeHelp, nil))

	if !got.Resumable {
		t.Error("it printed --resume and --continue; resumable should be true")
	}
	if !got.ExposesToolArgs || !got.ExposesToolResult {
		t.Error("it printed stream-json, the form that carries tool calls and their results")
	}
	if len(got.Unanswered) != 0 {
		t.Errorf("everything was asked and answered, yet %+v came back unanswered", got.Unanswered)
	}
}

// The point of FR-017. Same CLI, same name, a build without the resume flag — and the answer
// has to change, because it came from the binary rather than from the name on it.
func TestTheSameCLIWithoutTheFlagIsReportedWithoutTheCapability(t *testing.T) {
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}
	stripped := `Usage: claude [options] [prompt]

Options:
  --output-format <format>   "text" (default)
`

	got := Probe(context.Background(), found, askedWith(stripped, nil))

	if got.Resumable {
		t.Error("nothing in what it printed says it can resume, so nothing may say so here")
	}
	if got.ExposesToolArgs || got.ExposesToolResult {
		t.Error("no streaming form was offered, so no tool call ever reaches the server")
	}
}

// A family the daemon cannot interrogate registers with everything unanswered and a code saying
// why. It does not register with guesses, and it does not fail to register: a CLI with no
// declared capability is still supported, degraded (FR-039a).
//
// Both families of this release now have a probe, so the case is reached through a family that
// does not — which is the state any third family arrives in.
func TestAFamilyWithNoProbeSaysSoRatherThanGuessing(t *testing.T) {
	found := Found{Kind: "something_new", Family: "a_protocol_nobody_here_speaks", Path: "/usr/bin/whatever"}

	got := Probe(context.Background(), found, askedWith("anything at all", nil))

	if got.Resumable || got.ExposesToolArgs || got.ExposesToolResult {
		t.Fatalf("nothing was asked, so nothing may be claimed: %+v", got)
	}
	if len(got.Unanswered) != len(everyCapability) {
		t.Fatalf("want every capability marked unanswered, got %+v", got.Unanswered)
	}
	for _, missing := range got.Unanswered {
		if missing.Reason != ReasonNoProbe {
			t.Errorf("reason = %q, want %q", missing.Reason, ReasonNoProbe)
		}
	}
}

func TestACLIThatRefusesToDescribeItselfIsUnansweredNotAssumed(t *testing.T) {
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}

	got := Probe(context.Background(), found, askedWith("", errors.New("exit status 2")))

	if len(got.Unanswered) != len(everyCapability) {
		t.Fatalf("want every capability marked unanswered, got %+v", got.Unanswered)
	}
	if got.Unanswered[0].Reason != ReasonProbeFailed {
		t.Errorf("reason = %q, want %q", got.Unanswered[0].Reason, ReasonProbeFailed)
	}
}

func TestEveryFoundCLIGetsAskedInOrder(t *testing.T) {
	found := []Found{
		{Kind: agentcli.Gemini, Family: agentcli.FamilyACP, Path: "/usr/local/bin/gemini"},
		{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"},
	}

	got := ProbeAll(context.Background(), found, askedWith(claudeHelp, nil))

	if len(got) != 2 {
		t.Fatalf("want one answer per CLI, got %+v", got)
	}
	if len(got[0].Unanswered) == 0 {
		t.Error("no ACP peer answered for the first one, and that must be said rather than guessed")
	}
	if !got[1].Resumable {
		t.Error("the one-shot one was asked and answered")
	}
}

// ── what a person may pick per agent (T039g, FR-007k, FR-017) ────────────────

func choiceOf(got Capabilities, key string) (Choice, bool) {
	for _, c := range got.Choices {
		if c.Key == key {
			return c, true
		}
	}
	return Choice{}, false
}

func TestWhatAPersonMayPickComesOutOfTheBinaryAndNotOffItsName(t *testing.T) {
	// FR-007k cấm dựng danh sách từ một bảng chép cứng theo tên CLI. Bài này là chỗ luật ấy
	// thành thật: cùng một `Kind`, cùng một đường dẫn, chỉ khác **thứ binary in ra** — và
	// danh sách phải khác theo.
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}

	got := Probe(context.Background(), found, askedWith(claudeHelp, nil))

	effort, offered := choiceOf(got, ChoiceThinkingLevel)
	if !offered {
		t.Fatalf("nó in ra --effort kèm cả dải giá trị mà không ai đọc: %+v", got.Choices)
	}
	if effort.Source != SourceToolDeclared {
		t.Errorf("dải đóng ngoặc là tool nói **hết** bộ, không phải ví dụ: %q", effort.Source)
	}
	want := []string{"low", "medium", "high", "xhigh", "max"}
	if len(effort.Values) != len(want) {
		t.Fatalf("mức nghĩ đọc ra %v, mong %v", effort.Values, want)
	}
	for i, value := range want {
		if effort.Values[i] != value {
			t.Fatalf("mức nghĩ đọc ra %v, mong %v", effort.Values, want)
		}
	}

	model, offered := choiceOf(got, ChoiceModel)
	if !offered {
		t.Fatalf("nó có --model kèm ví dụ mà không ai đọc: %+v", got.Choices)
	}
	if model.Source != SourceToolExamples {
		t.Errorf("ba cái tên trong ngoặc là **ví dụ**, khai thành cả bộ là nói hộ tool: %q", model.Source)
	}
	// Đúng ba alias trong nhóm ngoặc đầu tiên. `claude-fable-5` nằm ở nhóm ngoặc **thứ hai**
	// và không được lọt vào: nó là một tên đầy đủ của hôm nay, bày lên màn là bày một phiên
	// bản sẽ cũ đi.
	if len(model.Values) != 3 {
		t.Fatalf("model đọc ra %v — mong đúng ba alias ở nhóm ngoặc đầu", model.Values)
	}
	for _, value := range model.Values {
		if value == "claude-fable-5" {
			t.Fatalf("vớ luôn tên đầy đủ ở nhóm ngoặc thứ hai: %v", model.Values)
		}
	}
}

func TestATOOLThatSaysNothingAboutASettingIsOfferedNoneRatherThanAnEmptyOne(t *testing.T) {
	// Hai thứ trông giống nhau trên màn và nghĩa ngược nhau: *tool này không có thiết lập ấy*
	// và *có mà không ai đọc nổi giá trị*. Chỉ cái thứ nhất đúng ở đây, nên chỉ nó được hiện.
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}
	bare := "Usage: claude [options]\n\nOptions:\n  -r, --resume [value]   Resume\n"

	got := Probe(context.Background(), found, askedWith(bare, nil))

	if len(got.Choices) != 0 {
		t.Fatalf("không in ra thiết lập nào mà vẫn khai: %+v", got.Choices)
	}
}

func TestABracketedAsideThatIsNotAListIsNotReadAsOne(t *testing.T) {
	// Ngoặc đơn trong trợ giúp phần lớn là câu văn, không phải danh sách. Đọc bừa một câu
	// thành các lựa chọn là bày ra thứ tool chưa từng nói.
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}
	prose := "Usage: claude\n\nOptions:\n  --effort <level>   Effort level (only works with --print)\n"

	got := Probe(context.Background(), found, askedWith(prose, nil))

	if _, offered := choiceOf(got, ChoiceThinkingLevel); offered {
		t.Fatalf("đọc một câu văn thành dải giá trị: %+v", got.Choices)
	}
}

func TestACLIThatCouldNotBeAskedOffersNothingToPick(t *testing.T) {
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}

	got := Probe(context.Background(), found, askedWith("", errors.New("nope")))

	if len(got.Choices) != 0 {
		t.Fatalf("hỏi không được mà vẫn bày ra lựa chọn: %+v", got.Choices)
	}
}

func TestALongerFlagSharingThePrefixDoesNotAnswerForThisOne(t *testing.T) {
	// `--model-set` đứng trước `--model` trong trợ giúp: tìm theo chuỗi thuần sẽ dừng ở cái
	// dài hơn và đọc ngoặc của **nó** thành danh sách model. Không có gì đỏ khi việc này xảy
	// ra — màn hình vẫn bày ra một danh sách, chỉ là danh sách của một cờ khác.
	found := Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}
	shadowed := "Usage: claude\n\nOptions:\n" +
		"  --model-set <name>   Saved set (e.g. 'fast', 'cheap')\n" +
		"  --model <name>       Model (e.g. 'opus', 'sonnet')\n"

	got := Probe(context.Background(), found, askedWith(shadowed, nil))

	choice, offered := choiceOf(got, ChoiceModel)
	if !offered {
		t.Fatalf("không đọc ra model nào: %+v", got.Choices)
	}
	for _, value := range choice.Values {
		if value == "fast" || value == "cheap" {
			t.Fatalf("đọc ngoặc của --model-set thành model: %v", choice.Values)
		}
	}
}

// FR-017 + FR-039a: what a workplace does *not* have is one list with a reason against each
// entry, and the workplace is still a workplace. The reasons matter because they point at
// different people — a CLI that answered no is the vendor's, a probe that could not be run is
// this daemon's, and telling an operator the wrong one sends them to fix the wrong thing.
func TestWhatAWorkplaceLacksIsOneListWithAReasonAgainstEachEntry(t *testing.T) {
	answered := Capabilities{Resumable: true}
	reduced := answered.Reduced()
	if len(reduced) != 2 {
		t.Fatalf("a CLI that answered yes to one of three is missing %v", reduced)
	}
	for _, missing := range reduced {
		if missing.Capability == "resumable" {
			t.Error("a capability the CLI answered yes to was reported as missing")
		}
		if missing.Reason != ReasonDeclaredAbsent {
			t.Errorf("%s is missing for %q, want %q — it was asked and said no",
				missing.Capability, missing.Reason, ReasonDeclaredAbsent)
		}
	}
}

// A CLI nobody could ask keeps the reason it could not be asked. It travels as false either
// way, which is the degraded reading FR-017 requires, but *why* is not the same fact.
func TestACapabilityNobodyCouldAskAboutKeepsWhyNotDeclaredAbsent(t *testing.T) {
	for _, missing := range unanswered(ReasonNoProbe).Reduced() {
		if missing.Reason != ReasonNoProbe {
			t.Errorf("%s is missing for %q, want %q", missing.Capability, missing.Reason, ReasonNoProbe)
		}
	}
}

// A CLI that answered yes to everything has nothing to report, and reports nothing. An empty
// list is what lets a caller say *this workplace runs the whole contract* without inspecting
// three booleans of its own.
func TestAWorkplaceWithTheWholeContractSaysNothing(t *testing.T) {
	whole := Capabilities{Resumable: true, ExposesToolArgs: true, ExposesToolResult: true}
	if reduced := whole.Reduced(); len(reduced) != 0 {
		t.Errorf("a workplace with every capability reported %v as missing", reduced)
	}
}

// Every capability the server is told about is one this list can account for. A fourth added to
// the record without a line in `everyCapability` would be missing from every report of what a
// workplace lacks, and missing quietly.
func TestEveryCapabilityTheServerStoresCanBeReportedMissing(t *testing.T) {
	nothing := Capabilities{}
	if len(nothing.Reduced()) != len(everyCapability) {
		t.Errorf("a CLI that has nothing reported %d missing, want all %d",
			len(nothing.Reduced()), len(everyCapability))
	}
}

// ── the ACP family: the agent's own declaration (T131a, FR-017) ───────────────

// geminiIntroduction is what `gemini 0.56.0` answered on 2026-09-02 when this daemon opened the
// conversation over pipes, with no terminal, on a machine whose Google account is refused
// outright (`IneligibleTierError`). Copied rather than invented, and the refusal matters: the
// handshake completes anyway, which is why a workplace can be asked what it can do without
// anybody having a working account.
const geminiIntroduction = `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,` +
	`"authMethods":[{"id":"oauth-personal","name":"Log in with Google"}],` +
	`"agentInfo":{"name":"gemini-cli","title":"Gemini CLI","version":"0.56.0"},` +
	`"agentCapabilities":{"loadSession":true,"promptCapabilities":{"image":true,"audio":true,` +
	`"embeddedContext":true},"mcpCapabilities":{"http":true,"sse":true}}}}`

// peerSaying is an Options whose ACP peer answers with these lines, in order, and records what it
// was asked.
func peerSaying(lines ...string) (Options, *[]map[string]any) {
	var asked []map[string]any
	opts := askedWith("", nil)
	opts.Handshake = func(_ context.Context, _ string, _ []string, talk func(io.Writer, io.Reader) error) error {
		heard := &capturingWriter{}
		err := talk(heard, strings.NewReader(strings.Join(lines, "\n")+"\n"))
		asked = heard.messages
		return err
	}
	return opts, &asked
}

type capturingWriter struct {
	messages []map[string]any
}

func (w *capturingWriter) Write(p []byte) (int, error) {
	var one map[string]any
	if json.Unmarshal(p, &one) == nil {
		w.messages = append(w.messages, one)
	}
	return len(p), nil
}

func geminiFound() Found {
	return Found{Kind: agentcli.Gemini, Family: agentcli.FamilyACP, Path: "/usr/local/bin/gemini"}
}

// Cái trần của FR-017 trong cả daemon này: không phải một dấu hiệu đọc mò trong trang trợ giúp,
// mà là lời **chính agent tự khai**, bằng đúng giao thức của nó.
func TestAnACPCLIsResumingComesFromItsOwnHandshake(t *testing.T) {
	opts, _ := peerSaying(geminiIntroduction)

	got := Probe(context.Background(), geminiFound(), opts)

	if !got.Resumable {
		t.Error("nó tự khai loadSession: true, mà chỗ làm đăng ký là không nối lại được phiên")
	}
}

// Cùng một tên, cùng một đường dẫn, chỉ khác **bản cài** — và câu trả lời phải đổi theo. Đây là
// chỗ FR-017 thành thật với họ ACP, y như bài tương ứng của họ chạy-một-phát.
func TestTheSameACPCLIThatCannotLoadSessionsIsReportedThatWay(t *testing.T) {
	opts, _ := peerSaying(`{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,` +
		`"agentCapabilities":{"loadSession":false}}}`)

	got := Probe(context.Background(), geminiFound(), opts)

	if got.Resumable {
		t.Fatal("nó nói không nối lại được phiên, không ai được nói hộ nó câu ngược lại")
	}
	// Hỏi rồi nó nói không — đó là sự thật về **chính nó**, khác hẳn hai khả năng dưới.
	if reason := reasonFor(got, string(capResumable)); reason != ReasonDeclaredAbsent {
		t.Errorf("lý do = %q, mong %q", reason, ReasonDeclaredAbsent)
	}
}

// Bài đáng giá nhất của cả đợt này. Cái bắt tay ACP **không có chỗ** để hỏi hai khả năng còn
// lại: chúng đi theo từng lời gọi công cụ, không phải theo lời khai của agent. Ghi thành
// "hỏi rồi nó nói không" là nói hộ agent một câu chưa ai hỏi nó — và người vận hành đọc câu ấy
// sẽ đi tìm một bản cài mới hơn cho một thứ không bản nào có.
func TestWhatTheProtocolCannotAskIsNotReportedAsTheAgentSayingNo(t *testing.T) {
	opts, _ := peerSaying(geminiIntroduction)

	got := Probe(context.Background(), geminiFound(), opts)

	for _, want := range []capability{capExposesToolArgs, capExposesToolResult} {
		if reason := reasonFor(got, string(want)); reason != ReasonNotInProtocol {
			t.Errorf("%s: lý do = %q, mong %q", want, reason, ReasonNotInProtocol)
		}
	}
	if got.ExposesToolArgs || got.ExposesToolResult {
		t.Error("không hỏi được thì không được khai là có — đọc hạ cấp mới là đọc đúng (FR-039a)")
	}
}

// Một agent chưa trả lời xong vẫn nói nhiều thứ khác, và một CLI thì in cả lời chào. Dừng ở
// dòng đầu tiên đọc không ra là hỏng một phép dò vì một câu chào.
func TestABannerAndANotificationDoNotStopTheProbeReading(t *testing.T) {
	opts, _ := peerSaying(
		"Loading extensions...",
		`{"jsonrpc":"2.0","method":"session/update","params":{"update":{}}}`,
		`{"jsonrpc":"2.0","id":99,"result":{"protocolVersion":1,"agentCapabilities":{"loadSession":false}}}`,
		geminiIntroduction,
	)

	got := Probe(context.Background(), geminiFound(), opts)

	if !got.Resumable {
		t.Error("câu trả lời đúng số hiệu nằm sau ba dòng khác, và nó là câu duy nhất được đọc")
	}
}

// Lời **từ chối** không được đọc thành lời **trả lời**. Chỗ hai thứ ấy dễ lẫn nhất là khi agent
// gửi kèm một `result` rỗng: đọc lướt qua chỗ báo lỗi thì cái rỗng ấy thành "hỏi rồi nó nói
// không có khả năng nào", và chỗ làm mang một câu khai chưa ai nói.
func TestAnACPCLIThatWillNotIntroduceItselfIsUnansweredNotAssumed(t *testing.T) {
	opts, _ := peerSaying(`{"jsonrpc":"2.0","id":1,"result":null,` +
		`"error":{"code":-32601,"message":"unknown method"}}`)

	got := Probe(context.Background(), geminiFound(), opts)

	if len(got.Unanswered) != len(everyCapability) {
		t.Fatalf("mong mọi khả năng đều là không hỏi được, nhận %+v", got.Unanswered)
	}
	for _, missing := range got.Unanswered {
		if missing.Reason != ReasonProbeFailed {
			t.Errorf("lý do = %q, mong %q", missing.Reason, ReasonProbeFailed)
		}
	}
}

// Một CLI im lặng không được giữ vòng quét lại. Cả một máy đang đợi được báo có những chỗ làm
// nào, và một binary treo là một daemon không khởi động xong.
func TestACLIThatNeverAnswersDoesNotHoldUpTheSweep(t *testing.T) {
	opts := askedWith("", nil)
	opts.Timeout = 50 * time.Millisecond
	opts.Handshake = func(ctx context.Context, _ string, _ []string, _ func(io.Writer, io.Reader) error) error {
		<-ctx.Done()
		return ctx.Err()
	}

	done := make(chan Capabilities, 1)
	go func() { done <- Probe(context.Background(), geminiFound(), opts) }()

	select {
	case got := <-done:
		if got.Unanswered[0].Reason != ReasonProbeFailed {
			t.Errorf("lý do = %q, mong %q", got.Unanswered[0].Reason, ReasonProbeFailed)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("phép dò không có hạn giờ: một CLI treo giữ cả vòng quét lại")
	}
}

// Hỏi bằng đúng lời mở đầu mà lượt chạy sẽ dùng. Một peer khai về mình **để trả lời** cái nó
// vừa được nghe, nên hỏi bằng một lời giới thiệu khác là cất vào chỗ làm một câu trả lời cho
// câu hỏi không ai hỏi lại nữa.
func TestTheProbeIntroducesThisClientTheWayARunDoes(t *testing.T) {
	opts, asked := peerSaying(geminiIntroduction)

	Probe(context.Background(), geminiFound(), opts)

	if len(*asked) != 1 {
		t.Fatalf("mong đúng một câu hỏi, nhận %+v", *asked)
	}
	opening := (*asked)[0]
	if opening["method"] != "initialize" {
		t.Errorf("câu đầu tiên là %v, mong initialize", opening["method"])
	}
	params, _ := opening["params"].(map[string]any)
	if params["protocolVersion"] != float64(agentcli.ACPVersion) {
		t.Errorf("hỏi ở bản giao thức %v, mong %d", params["protocolVersion"], agentcli.ACPVersion)
	}
}

// Một hàng của họ ACP mà không có gì để khởi động thì không nói lên điều gì về chính CLI ấy —
// đó là chuyện của bảng ở đây, và mã lý do phải chỉ về đúng phía ấy.
func TestAnACPKindTheRegistryDoesNotCarryIsNotGuessedAt(t *testing.T) {
	found := Found{Kind: "acp_cli_nobody_wrote_a_row_for", Family: agentcli.FamilyACP, Path: "/usr/bin/x"}

	got := Probe(context.Background(), found, askedWith("", nil))

	if len(got.Unanswered) != len(everyCapability) {
		t.Fatalf("mong mọi khả năng đều là không hỏi được, nhận %+v", got.Unanswered)
	}
	if got.Unanswered[0].Reason != ReasonNoProbe {
		t.Errorf("lý do = %q, mong %q", got.Unanswered[0].Reason, ReasonNoProbe)
	}
}

// reasonFor is what `Reduced` says about one capability — the same list the operator is shown at
// registration, rather than the raw field, so the tests check what is actually reported.
func reasonFor(got Capabilities, want string) string {
	for _, missing := range got.Reduced() {
		if missing.Capability == want {
			return missing.Reason
		}
	}
	return ""
}

// ── the real edge: a process, two pipes, and a program that answers ───────────

// TestARealProcessIsStartedAndAnswersOverItsOwnPipes chạy **thật**: một chương trình trên đĩa,
// khởi động bằng đúng cạnh mà daemon dùng, nói chuyện qua đúng hai đường ống ấy.
//
// Mọi bài phía trên thay cạnh khởi động bằng đồ giả, nên không bài nào chạm vào `startAndTalk` —
// mà đó lại là mảnh nhiều rủi ro nhất: ống dẫn, hạn chờ cái đuôi tiến trình, và việc **bỏ qua**
// dòng than phiền. Hai thứ được chứng ở đây cùng lúc: nó đọc được câu trả lời, và một chương
// trình gào lỗi ra luồng lỗi vẫn được nghe câu trả lời của nó.
func TestARealProcessIsStartedAndAnswersOverItsOwnPipes(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("kịch bản sh: máy này không chạy được")
	}
	script := filepath.Join(t.TempDir(), "fake-acp-cli")
	body := "#!/bin/sh\n" +
		// Đúng thứ gemini 0.56.0 làm trên máy này: tài khoản bị từ chối, nó ghi cả cục lỗi ra
		// luồng lỗi, rồi vẫn bắt tay bình thường.
		"echo 'Error authenticating: IneligibleTierError' >&2\n" +
		"read -r _\n" +
		"echo '" + geminiIntroduction + "'\n" +
		"while read -r _; do :; done\n"
	if err := os.WriteFile(script, []byte(body), 0o700); err != nil { //nolint:gosec // a test's own scratch script
		t.Fatal(err)
	}

	found := Found{Kind: agentcli.Gemini, Family: agentcli.FamilyACP, Path: script}
	got := Probe(context.Background(), found, Options{Timeout: 10 * time.Second})

	if !got.Resumable {
		t.Fatalf("một chương trình thật đã khai loadSession: true qua ống dẫn thật: %+v", got)
	}
	if reason := reasonFor(got, string(capExposesToolArgs)); reason != ReasonNotInProtocol {
		t.Errorf("lý do = %q, mong %q", reason, ReasonNotInProtocol)
	}
}

// Một chương trình chỉ ngồi im không được giữ vòng quét lại, và lần này là tiến trình thật chứ
// không phải một hàm giả đợi ngữ cảnh.
func TestARealProcessThatNeverAnswersIsGivenUpOn(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("kịch bản sh: máy này không chạy được")
	}
	script := filepath.Join(t.TempDir(), "silent-acp-cli")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nwhile read -r _; do :; done\n"), 0o700); err != nil { //nolint:gosec // a test's own scratch script
		t.Fatal(err)
	}

	found := Found{Kind: agentcli.Gemini, Family: agentcli.FamilyACP, Path: script}
	started := time.Now()
	got := Probe(context.Background(), found, Options{Timeout: 300 * time.Millisecond})

	if took := time.Since(started); took > 10*time.Second {
		t.Fatalf("bỏ cuộc sau %s: một CLI im lặng giữ cả vòng quét lại", took)
	}
	if got.Unanswered[0].Reason != ReasonProbeFailed {
		t.Errorf("lý do = %q, mong %q", got.Unanswered[0].Reason, ReasonProbeFailed)
	}
}
