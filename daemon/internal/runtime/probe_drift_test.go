package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"reflect"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
	"github.com/gnust-company/armarius-daemon/internal/discovery"
)

// TestTheProbeAndTheRunIntroduceThisClientIdentically canh **mối nối** thứ hai giữa hai package,
// cùng hình dạng với bài canh cờ đọc-giá-trị ở choices_test.go.
//
// Hai bên cùng mở một cuộc hội thoại ACP: bên dò hỏi chỗ làm này làm được gì, bên chạy giao việc
// cho nó. Một peer khai về mình **để trả lời** cái nó vừa nghe — lời giới thiệu của phía bên kia
// là một phần câu hỏi. Nên hỏi bằng một lời giới thiệu rồi chạy bằng một lời khác thì câu trả lời
// cất vào chỗ làm là câu trả lời cho một câu hỏi không ai hỏi lại nữa, và **không có gì hỏng cả**:
// chỗ làm vẫn đăng ký, việc vẫn chạy, chỉ là khai một khả năng của một cuộc hội thoại khác.
//
// So **hành vi** chứ không so hai cái bảng: mỗi bên được chạy thật với một peer giả, rồi lấy đúng
// dòng nó gửi ra so với nhau. Một hằng số dùng chung chỉ canh được phần ai cũng nhớ chép.
func TestTheProbeAndTheRunIntroduceThisClientIdentically(t *testing.T) {
	fromTheProbe := introductionFromProbe(t)
	fromTheRun := introductionFromRun(t)

	if !reflect.DeepEqual(fromTheProbe, fromTheRun) {
		t.Errorf("bên dò mở lời bằng\n  %v\nbên chạy mở lời bằng\n  %v", fromTheProbe, fromTheRun)
	}
	if fromTheProbe["protocolVersion"] != float64(agentcli.ACPVersion) {
		t.Errorf("bản giao thức = %v, mong %d", fromTheProbe["protocolVersion"], agentcli.ACPVersion)
	}
}

// introductionFromProbe runs the real probe against a peer that answers one handshake.
func introductionFromProbe(t *testing.T) map[string]any {
	t.Helper()

	var opening map[string]any
	// Written to and read from separately, so what the probe itself sends is what is read back.
	said, hears := io.Pipe()
	opts := discovery.Options{}
	opts.Handshake = func(_ context.Context, _ string, _ []string, talk func(io.Writer, io.Reader) error) error {
		answers, replies := io.Pipe()
		go func() {
			opening = firstParams(t, said)
			_, _ = replies.Write([]byte(`{"jsonrpc":"2.0","id":1,` +
				`"result":{"protocolVersion":1,"agentCapabilities":{"loadSession":true}}}` + "\n"))
			_ = replies.Close()
		}()
		err := talk(hears, answers)
		_ = hears.Close()
		return err
	}

	got := discovery.Probe(context.Background(), discovery.Found{
		Kind: agentcli.Gemini, Family: agentcli.FamilyACP, Path: "/usr/local/bin/gemini",
	}, opts)
	if !got.Resumable {
		t.Fatalf("phép dò không đọc được câu trả lời, nên dòng nó gửi chưa chắc là dòng thật: %+v", got)
	}
	return opening
}

// introductionFromRun runs the real conversation against a peer that answers everything.
func introductionFromRun(t *testing.T) map[string]any {
	t.Helper()

	said, hears := io.Pipe()
	answers, replies := io.Pipe()

	var opening map[string]any
	go func() {
		lines := bufio.NewScanner(said)
		enc := json.NewEncoder(replies)
		first := true
		for lines.Scan() {
			var msg rpcMessage
			if json.Unmarshal(lines.Bytes(), &msg) != nil {
				continue
			}
			if first {
				first = false
				_ = json.Unmarshal(msg.Params, &opening)
			}
			switch msg.Method {
			case "initialize":
				_ = enc.Encode(rpcMessage{JSONRPC: "2.0", ID: msg.ID,
					Result: mustRaw(map[string]any{"protocolVersion": agentcli.ACPVersion})})
			case "session/new":
				_ = enc.Encode(rpcMessage{JSONRPC: "2.0", ID: msg.ID,
					Result: mustRaw(map[string]any{"sessionId": "s1"})})
			case "session/prompt":
				_ = enc.Encode(rpcMessage{JSONRPC: "2.0", ID: msg.ID,
					Result: mustRaw(map[string]any{"stopReason": "end_turn"})})
			}
		}
		_ = replies.Close()
	}()

	_, err := Converse(context.Background(), hears, answers, Request{
		CLI: string(agentcli.Gemini), WorkDir: t.TempDir(), Message: "hello",
	}, func(Event) {})
	_ = hears.Close()
	if err != nil {
		t.Fatalf("cuộc hội thoại thật hỏng, nên dòng nó gửi chưa chắc là dòng thật: %v", err)
	}
	return opening
}

// firstParams reads the params of the first JSON-RPC message written to a stream.
func firstParams(t *testing.T, from io.Reader) map[string]any {
	t.Helper()

	lines := bufio.NewScanner(from)
	for lines.Scan() {
		var msg struct {
			Method string         `json:"method"`
			Params map[string]any `json:"params"`
		}
		if json.Unmarshal(lines.Bytes(), &msg) != nil {
			continue
		}
		if msg.Method != "initialize" {
			continue
		}
		return msg.Params
	}
	return nil
}
