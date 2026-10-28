package discovery

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// claudeCatalogReply is what claude 2.1.301 answered on 2026-10-26, cut to the rows that matter
// here and kept in the order it gave them. Copied from the real binary rather than invented.
var claudeCatalogReply = `{"type":"system","subtype":"init","session_id":"x"}` + "\n" + oneLine(`
{"type":"control_response","response":{"subtype":"success","request_id":"armarius-list-models","response":{"models":[
{"value":"default","resolvedModel":"claude-opus-5-5","displayName":"Default (recommended)","supportsEffort":true,"supportedEffortLevels":["low","medium","high","xhigh","max"]},
{"value":"opus","resolvedModel":"claude-opus-5-5","displayName":"Opus 5.5","supportsEffort":true,"supportedEffortLevels":["low","medium","high","xhigh","max"]},
{"value":"sonnet","resolvedModel":"claude-sonnet-5-5","displayName":"Sonnet 5.5","supportsEffort":true,"supportedEffortLevels":["low","medium","high","xhigh","max"]},
{"value":"claude-sonnet-5-5","resolvedModel":"claude-sonnet-5-5","displayName":"Sonnet 5.5","supportsEffort":true,"supportedEffortLevels":["low","medium","high","xhigh","max"]},
{"value":"claude-haiku-4-5-20251001","resolvedModel":"claude-haiku-4-5-20251001","displayName":"Haiku 4.5","supportsEffort":false},
{"value":"claude-opus-4-6","resolvedModel":"claude-opus-4-6","displayName":"Opus 4.6","supportsEffort":true,"supportedEffortLevels":["low","medium","high","max"]},
{"value":"fable","resolvedModel":"claude-fable-5-1","displayName":"Fable 5.1","disabled":true,"description":"Update to use Fable 5.1"}
]}}}`)

// oneLine joins a reply written across lines for reading into the single line the CLI sends:
// the stream is one JSON object per line, and a fixture that breaks that would test a parser
// for a format nobody speaks.
func oneLine(reply string) string {
	return strings.ReplaceAll(strings.TrimSpace(reply), "\n", "") + "\n"
}

// catalogPeer is a Claude Code that answers the catalog request with `reply`, and remembers
// how it was started and what it was asked.
type catalogPeer struct {
	reply  string
	failed error
	path   string
	args   []string
	asked  bytes.Buffer
	closed bool
}

func (p *catalogPeer) Write(b []byte) (int, error) { return p.asked.Write(b) }
func (p *catalogPeer) Close() error                { p.closed = true; return nil }

func (p *catalogPeer) options() Options {
	opts := askedWith(claudeHelp, nil)
	opts.Handshake = func(_ context.Context, path string, args []string, talk func(io.Writer, io.Reader) error) error {
		p.path, p.args = path, args
		if p.failed != nil {
			return p.failed
		}
		return talk(p, strings.NewReader(p.reply))
	}
	return opts
}

var claudeFound = Found{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"}

func TestClaudeIsAskedForItsModelsTheWayItsOwnPickerIs(t *testing.T) {
	peer := &catalogPeer{reply: claudeCatalogReply}
	got := Probe(context.Background(), claudeFound, peer.options())

	if peer.path != "/usr/bin/claude" {
		t.Fatalf("hỏi nhầm binary: %q", peer.path)
	}
	want := []string{"--print", "--verbose", "--input-format", "stream-json", "--output-format", "stream-json", "--strict-mcp-config"}
	if strings.Join(peer.args, " ") != strings.Join(want, " ") {
		t.Fatalf("mở claude bằng %v, mong %v", peer.args, want)
	}
	var request struct {
		Type      string `json:"type"`
		RequestID string `json:"request_id"`
		Request   struct {
			Subtype string `json:"subtype"`
		} `json:"request"`
	}
	if err := json.Unmarshal(bytes.TrimSpace(peer.asked.Bytes()), &request); err != nil {
		t.Fatalf("thứ gửi đi không phải một dòng JSON: %q", peer.asked.String())
	}
	if request.Type != "control_request" || request.Request.Subtype != "list_models" || request.RequestID != catalogRequestID {
		t.Fatalf("hỏi sai câu: %+v", request)
	}
	if !peer.closed {
		t.Fatal("không đóng đầu vào sau câu hỏi: claude sẽ đợi thêm tin nhắn tới hết giờ")
	}

	model, offered := choiceOf(got, ChoiceModel)
	if !offered {
		t.Fatalf("có danh sách mà không ai đưa lên: %+v", got.Choices)
	}
	if model.Source != SourceToolListed {
		t.Errorf("danh sách hỏi được là tool liệt kê, không phải ví dụ: %q", model.Source)
	}
	// Lưu tên đã phân giải, khử trùng: `default` và `opus` cùng chạy claude-opus-5-5, alias
	// `sonnet` và tên đầy đủ của nó là một model. Dòng bị
	// khoá (`fable` ở bản này) không được thành một lựa chọn.
	values := []string{"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5-20251001", "claude-opus-4-6"}
	if strings.Join(model.Values, ",") != strings.Join(values, ",") {
		t.Fatalf("giá trị %v, mong %v", model.Values, values)
	}
	if model.Labels["claude-opus-5-5"] != "Opus 5.5" || model.Labels["claude-haiku-4-5-20251001"] != "Haiku 4.5" {
		t.Errorf("tên đọc được không đi theo: %v", model.Labels)
	}
	if got := model.Narrows["claude-opus-4-6"][ChoiceThinkingLevel]; strings.Join(got, ",") != "low,medium,high,max" {
		t.Errorf("Opus 4.6 không nhận xhigh mà vẫn được cho: %v", got)
	}

	// Model không nhận mức nào phải đi lên thành **danh sách rỗng**, không phải null: null thì
	// server đọc thành *không nói gì*, và cho chọn đúng thứ model ấy không chạy được.
	encoded, _ := json.Marshal(model)
	if !strings.Contains(string(encoded), `"claude-haiku-4-5-20251001":{"thinking_level":[]}`) {
		t.Fatalf("Haiku 4.5 phải thu hẹp mức về rỗng: %s", encoded)
	}

	effort, _ := choiceOf(got, ChoiceThinkingLevel)
	if effort.Source != SourceToolDeclared || len(effort.Values) != 5 {
		t.Errorf("danh sách mức vẫn đọc từ --effort như cũ: %+v", effort)
	}
}

func TestAnOldClaudeThatDoesNotKnowTheRequestKeepsTheExamplesFromItsHelp(t *testing.T) {
	refused := `{"type":"control_response","response":{"subtype":"error","request_id":"armarius-list-models","error":"Unsupported control request subtype: list_models"}}` + "\n"
	got := Probe(context.Background(), claudeFound, (&catalogPeer{reply: refused}).options())

	model, offered := choiceOf(got, ChoiceModel)
	if !offered || model.Source != SourceToolExamples || len(model.Values) != 3 {
		t.Fatalf("CLI cũ phải giữ ba cái tên ví dụ của --help: %+v", model)
	}
	if len(model.Labels) != 0 || len(model.Narrows) != 0 {
		t.Errorf("ví dụ không có nhãn hay luật thu hẹp nào: %+v", model)
	}
}

func TestACatalogThatCannotBeHadNeverLeavesThePersonWithLessThanTheHelp(t *testing.T) {
	cases := map[string]*catalogPeer{
		"không mở được":          {failed: errors.New("exec: no such file")},
		"kết thúc không trả lời": {reply: `{"type":"system","subtype":"init"}` + "\n"},
		"trả lời không đọc được": {reply: "{not json\n"},
		"trả lời của câu khác":   {reply: strings.ReplaceAll(claudeCatalogReply, catalogRequestID, "someone-else")},
		"danh sách rỗng":         {reply: `{"type":"control_response","response":{"subtype":"success","request_id":"armarius-list-models","response":{"models":[]}}}` + "\n"},
		"chỉ có dòng bị khoá":    {reply: `{"type":"control_response","response":{"subtype":"success","request_id":"armarius-list-models","response":{"models":[{"value":"fable","resolvedModel":"claude-fable-5-1","disabled":true}]}}}` + "\n"},
	}
	for name, peer := range cases {
		t.Run(name, func(t *testing.T) {
			got := Probe(context.Background(), claudeFound, peer.options())
			model, offered := choiceOf(got, ChoiceModel)
			if !offered || model.Source != SourceToolExamples {
				t.Fatalf("phải quay về ví dụ của --help: %+v", got.Choices)
			}
			if !got.Resumable {
				t.Error("hỏi danh sách hỏng không được kéo theo các khả năng đọc từ --help")
			}
		})
	}
}

func TestTheDefaultRowIsKeptOnlyWhenNoOtherRowNamesItsModel(t *testing.T) {
	only := oneLine(`
{"type":"control_response","response":{"subtype":"success","request_id":"armarius-list-models","response":{"models":[
{"value":"default","resolvedModel":"claude-sonnet-5-5","displayName":"Default","supportsEffort":true,"supportedEffortLevels":["low"]},
{"value":"haiku","resolvedModel":"claude-haiku-5-5","displayName":"Haiku 5.5","supportsEffort":true}
]}}}`)
	got := Probe(context.Background(), claudeFound, (&catalogPeer{reply: only}).options())
	model, _ := choiceOf(got, ChoiceModel)
	if strings.Join(model.Values, ",") != "claude-haiku-5-5,claude-sonnet-5-5" {
		t.Fatalf("model mặc định không ai khác gọi tên thì phải giữ lại: %v", model.Values)
	}
	// Nhận mức mà không nói mức nào: không thu hẹp gì, chứ không phải khoá hết.
	if _, narrowed := model.Narrows["claude-haiku-5-5"]; narrowed {
		t.Errorf("không nói mức nào thì không được thu hẹp: %v", model.Narrows)
	}
}

func TestGeminiIsNotAskedForACatalogItDoesNotHave(t *testing.T) {
	peer := &catalogPeer{reply: claudeCatalogReply}
	found := Found{Kind: agentcli.Gemini, Family: agentcli.FamilyOneShot, Path: "/usr/bin/gemini"}
	Probe(context.Background(), found, peer.options())
	if peer.path != "" {
		t.Fatalf("gemini không có câu hỏi này mà vẫn bị mở ra: %q", peer.path)
	}
}
