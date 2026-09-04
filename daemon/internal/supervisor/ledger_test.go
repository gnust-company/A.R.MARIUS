package supervisor

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/client"
)

// Reporting is the one hop between what a run concluded and what the server is told, and it is
// a hop of pure copying — which is exactly the kind that goes wrong without anything failing.
// A field left out here reads, from every angle inside this package, like a field the run never
// produced.

func finishSeenByTheServer(t *testing.T, done Conclusion) map[string]any {
	t.Helper()
	var body string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		body = string(raw)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{}`))
	}))
	t.Cleanup(server.Close)

	reporting := Reporting{Session: client.Session{Server: server.URL, Token: "armd_secret"}}
	if err := reporting.Finish(context.Background(), "run-1", done); err != nil {
		t.Fatalf("khép lượt chạy: %v", err)
	}
	var sent map[string]any
	if err := json.Unmarshal([]byte(body), &sent); err != nil {
		t.Fatalf("thân yêu cầu không phải JSON: %q", body)
	}
	return sent
}

func TestTheVerdictIsOnTheWireAndNotOnlyInThisPackage(t *testing.T) {
	sent := finishSeenByTheServer(t, Conclusion{
		Status:  Failed,
		Error:   "claude_code ended badly: exit status 1",
		Failure: "quota_exhausted",
	})

	if sent["failure"] != "quota_exhausted" {
		t.Fatalf("lý do không đi lên máy chủ: %v", sent)
	}
	// Beside the prose, not instead of it: one is what a policy branches on, the other is what
	// a person reads.
	if got, _ := sent["error"].(string); !strings.Contains(got, "exit status 1") {
		t.Fatalf("câu kể của máy này biến mất: %v", sent)
	}
	if sent["status"] != Failed {
		t.Fatalf("trạng thái sai: %v", sent)
	}
}

func TestAnEndingWithNoVerdictSendsNoSuchFieldAtAll(t *testing.T) {
	// Empty means *no verdict*, and the server retries an ending nobody classified. Sending an
	// empty string would be a third thing neither side has a meaning for.
	sent := finishSeenByTheServer(t, Conclusion{Status: Completed})

	if _, there := sent["failure"]; there {
		t.Fatalf("không có lý do nào mà vẫn gửi trường ấy: %v", sent)
	}
}
