package discovery

import (
	"context"
	"errors"
	"testing"
	"time"
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
		Timeout: time.Second,
	}
}

func TestAOneShotCLIsCapabilitiesComeFromWhatItPrinted(t *testing.T) {
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}

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
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}
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

// A family the daemon cannot yet interrogate registers with everything unanswered and a code
// saying why. It does not register with guesses, and it does not fail to register: a CLI with
// no declared capability is still supported, degraded (FR-039a).
func TestAFamilyWithNoProbeSaysSoRatherThanGuessing(t *testing.T) {
	found := Found{Kind: KindGemini, Family: FamilyACP, Path: "/usr/local/bin/gemini"}

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
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}

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
		{Kind: KindGemini, Family: FamilyACP, Path: "/usr/local/bin/gemini"},
		{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"},
	}

	got := ProbeAll(context.Background(), found, askedWith(claudeHelp, nil))

	if len(got) != 2 {
		t.Fatalf("want one answer per CLI, got %+v", got)
	}
	if len(got[0].Unanswered) == 0 {
		t.Error("the ACP one cannot be asked yet and must say so")
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
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}

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
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}
	bare := "Usage: claude [options]\n\nOptions:\n  -r, --resume [value]   Resume\n"

	got := Probe(context.Background(), found, askedWith(bare, nil))

	if len(got.Choices) != 0 {
		t.Fatalf("không in ra thiết lập nào mà vẫn khai: %+v", got.Choices)
	}
}

func TestABracketedAsideThatIsNotAListIsNotReadAsOne(t *testing.T) {
	// Ngoặc đơn trong trợ giúp phần lớn là câu văn, không phải danh sách. Đọc bừa một câu
	// thành các lựa chọn là bày ra thứ tool chưa từng nói.
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}
	prose := "Usage: claude\n\nOptions:\n  --effort <level>   Effort level (only works with --print)\n"

	got := Probe(context.Background(), found, askedWith(prose, nil))

	if _, offered := choiceOf(got, ChoiceThinkingLevel); offered {
		t.Fatalf("đọc một câu văn thành dải giá trị: %+v", got.Choices)
	}
}

func TestACLIThatCouldNotBeAskedOffersNothingToPick(t *testing.T) {
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}

	got := Probe(context.Background(), found, askedWith("", errors.New("nope")))

	if len(got.Choices) != 0 {
		t.Fatalf("hỏi không được mà vẫn bày ra lựa chọn: %+v", got.Choices)
	}
}

func TestALongerFlagSharingThePrefixDoesNotAnswerForThisOne(t *testing.T) {
	// `--model-set` đứng trước `--model` trong trợ giúp: tìm theo chuỗi thuần sẽ dừng ở cái
	// dài hơn và đọc ngoặc của **nó** thành danh sách model. Không có gì đỏ khi việc này xảy
	// ra — màn hình vẫn bày ra một danh sách, chỉ là danh sách của một cờ khác.
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}
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
