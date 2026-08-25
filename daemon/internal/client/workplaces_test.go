package client

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/discovery"
)

// recorded is what one request looked like on the wire, kept raw so a test can assert about
// the JSON itself and not only about what a decoder made of it.
type recorded struct {
	method string
	auth   string
	body   string
}

func serverThatAnswers(t *testing.T, answer string, status int) (*httptest.Server, *recorded) {
	t.Helper()
	seen := &recorded{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		seen.method = r.Method
		seen.auth = r.Header.Get("Authorization")
		seen.body = string(raw)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(answer))
	}))
	t.Cleanup(server.Close)
	return server, seen
}

func TestSyncWorkplacesSendsTheWholeListUnderTheMachineToken(t *testing.T) {
	server, seen := serverThatAnswers(t, `{"workplaces":[
		{"id":"wp-1","cli_kind":"claude_code","ready":true,"not_ready_reason":null,"machine_name":"gnust-thinkpad"}]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	got, err := session.SyncWorkplaces(context.Background(), WorkplacesRequest{
		Workplaces: []WorkplaceReport{{
			CLIKind:        "claude_code",
			CLIVersion:     "2.1.226",
			ProtocolFamily: "one_shot",
			Capabilities:   discovery.Capabilities{Resumable: true},
		}},
		SymlinkCapable: true,
	})
	if err != nil {
		t.Fatal(err)
	}

	if seen.method != http.MethodPut {
		t.Errorf("method = %s, want PUT — the machine replaces its list, it does not append", seen.method)
	}
	if seen.auth != "Bearer armd_secret" {
		t.Errorf("authorization = %q, want the machine's own token", seen.auth)
	}
	var sent map[string]any
	if err := json.Unmarshal([]byte(seen.body), &sent); err != nil {
		t.Fatalf("the request body was not JSON: %v", err)
	}
	if sent["symlink_capable"] != true {
		t.Error("what the link probe established did not reach the server")
	}
	if len(got.Workplaces) != 1 || got.Workplaces[0].MachineName != "gnust-thinkpad" {
		t.Errorf("the answer came back as %+v", got.Workplaces)
	}
}

// A machine with no agent CLI installed is a real report and has to read as one. `null` says
// the field was left out; `[]` says the machine looked and found nothing.
func TestAMachineWithNoCLIsSendsAnEmptyListNotNull(t *testing.T) {
	server, seen := serverThatAnswers(t, `{"workplaces":[]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	if _, err := session.SyncWorkplaces(context.Background(), WorkplacesRequest{}); err != nil {
		t.Fatal(err)
	}

	if !strings.Contains(seen.body, `"workplaces":[]`) {
		t.Errorf("body = %s, want an empty list rather than null", seen.body)
	}
}

func TestABeatCarriesTheFreeSlotsAndBringsBackTheAnswer(t *testing.T) {
	server, seen := serverThatAnswers(t, `{"pending_work":true,"cancel":["run-2"]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	got, err := session.Beat(context.Background(), BeatRequest{
		FreeSlots: 3,
		Running:   []string{"run-1", "run-2"},
	})
	if err != nil {
		t.Fatal(err)
	}

	if !strings.Contains(seen.body, `"free_slots":3`) {
		t.Errorf("body = %s, want the free-slot count the server needs to hold work back", seen.body)
	}
	if !got.PendingWork || len(got.Cancel) != 1 || got.Cancel[0] != "run-2" {
		t.Errorf("the answer came back as %+v", got)
	}
}

func TestARefusedCallIsAnErrorRatherThanAnEmptyAnswer(t *testing.T) {
	server, _ := serverThatAnswers(t, `{"code":"invalid_machine_token"}`, 401)
	session := Session{Server: server.URL, Token: "armd_stale"}

	if _, err := session.Beat(context.Background(), BeatRequest{}); err == nil {
		t.Fatal("a 401 was read as a successful beat")
	}
}

// `start` on a machine nobody ever linked must say so, and say what to do about it — not fail
// later on a call that reads like a network problem.
func TestAMachineThatWasNeverLinkedIsToldToLogIn(t *testing.T) {
	for name, path := range map[string]string{
		"no file at all": filepath.Join(t.TempDir(), "daemon.json"),
		"a file with only the operator's own settings": writeFile(t, `{"poll_interval":"5s"}`),
	} {
		_, err := LoadCredentials(path)
		if err == nil {
			t.Fatalf("%s: reported credentials that are not there", name)
		}
		if !strings.Contains(err.Error(), "login") {
			t.Errorf("%s: the error does not say what to do: %v", name, err)
		}
	}
}

func TestCredentialsWrittenByLoginAreReadBack(t *testing.T) {
	path := writeFile(t, `{"server":"https://armarius.example","token":"armd_secret","machine_id":"m-1","poll_interval":"5s"}`)

	got, err := LoadCredentials(path)
	if err != nil {
		t.Fatal(err)
	}
	if got.Server != "https://armarius.example" || got.Token != "armd_secret" {
		t.Errorf("read back %+v", got)
	}
}

func writeFile(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "daemon.json")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}
