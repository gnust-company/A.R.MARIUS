package client

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// asksRecorded answers every ask with the same body and keeps every list of names it was sent.
func asksRecorded(t *testing.T, answer string, status int) (*httptest.Server, *[][]string) {
	t.Helper()
	var asked [][]string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var sent TaskStatesRequest
		if err := json.Unmarshal(raw, &sent); err != nil {
			t.Errorf("the ask was not JSON: %v", err)
		}
		asked = append(asked, sent.TaskIDs)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(answer))
	}))
	t.Cleanup(server.Close)
	return server, &asked
}

func TestAskingAboutTasksCarriesTheMachineTokenAndReadsWhatCameBack(t *testing.T) {
	server, seen := serverThatAnswers(t, `{"tasks":[
		{"task_id":"task-1","closed":true,"last_activity":"2026-08-20T10:00:00Z"},
		{"task_id":"task-2","closed":false,"last_activity":"2026-08-30T10:00:00Z"}]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	states, err := session.TaskStates(context.Background(), []string{"task-1", "task-2"})
	if err != nil {
		t.Fatalf("asking: %v", err)
	}

	if seen.method != http.MethodPost {
		t.Errorf("method = %s, want POST — the list of names travels in the body", seen.method)
	}
	if seen.auth != "Bearer armd_secret" {
		t.Errorf("authorization = %q, want this machine's own token", seen.auth)
	}
	if !states["task-1"].Closed {
		t.Error("task-1 came back closed and was read as open")
	}
	if states["task-2"].Closed {
		t.Error("task-2 came back open and was read as closed")
	}
	want := time.Date(2026, 8, 20, 10, 0, 0, 0, time.UTC)
	if !states["task-1"].LastActivity.Equal(want) {
		t.Errorf("last activity = %s, want %s", states["task-1"].LastActivity, want)
	}
}

func TestANameTheServerDidNotMentionStaysMissingRatherThanBecomingAnOpenTask(t *testing.T) {
	// The one shape that would make a directory immortal: filling in a zero value for a name
	// the server did not answer about gives the sweep a task that is open and never closes,
	// and an open task is kept forever. Absence has to survive as absence — that is what
	// puts the directory on the orphan clock instead (FR-021a).
	server, _ := serverThatAnswers(t, `{"tasks":[]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	states, err := session.TaskStates(context.Background(), []string{"long-gone"})
	if err != nil {
		t.Fatalf("asking: %v", err)
	}
	if _, present := states["long-gone"]; present {
		t.Fatalf("a name the server never mentioned came back as a state: %#v", states)
	}
}

func TestAMachineWithMoreDirectoriesThanOneAskCarriesAsksMoreThanOnce(t *testing.T) {
	server, asked := asksRecorded(t, `{"tasks":[]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	names := make([]string, tasksPerAsk+3)
	for i := range names {
		names[i] = fmt.Sprintf("task-%d", i)
	}
	if _, err := session.TaskStates(context.Background(), names); err != nil {
		t.Fatalf("asking: %v", err)
	}

	if len(*asked) != 2 {
		t.Fatalf("asked %d times, want 2 — the ceiling is the server's and this side splits for it", len(*asked))
	}
	if got := len((*asked)[0]); got != tasksPerAsk {
		t.Errorf("first ask carried %d names, want %d", got, tasksPerAsk)
	}
	if got := len((*asked)[1]); got != 3 {
		t.Errorf("second ask carried %d names, want 3", got)
	}
	// Every name asked about exactly once: a split that drops or repeats a name is a split
	// that leaves a directory unaccounted for.
	seen := map[string]int{}
	for _, batch := range *asked {
		for _, name := range batch {
			seen[name]++
		}
	}
	if len(seen) != len(names) {
		t.Fatalf("asked about %d distinct names, want %d", len(seen), len(names))
	}
	for name, times := range seen {
		if times != 1 {
			t.Fatalf("%s was asked about %d times", name, times)
		}
	}
}

func TestAskingAboutNothingMakesNoCallAtAll(t *testing.T) {
	server, asked := asksRecorded(t, `{"tasks":[]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	states, err := session.TaskStates(context.Background(), nil)
	if err != nil {
		t.Fatalf("asking: %v", err)
	}
	if len(*asked) != 0 {
		t.Errorf("a machine with nothing on disk still called the server %d times", len(*asked))
	}
	if len(states) != 0 {
		t.Errorf("states = %#v, want empty", states)
	}
}

func TestOneFailedBatchFailsTheWholeLookupRatherThanReturningHalfOfIt(t *testing.T) {
	// A partial map is worse than no map. The sweep reads absence as *the server does not
	// know this task*, so names in a batch that never arrived would age out on the orphan
	// clock for a reason that has nothing to do with them.
	var asks int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		asks++
		w.Header().Set("Content-Type", "application/json")
		if asks == 1 {
			_, _ = w.Write([]byte(`{"tasks":[{"task_id":"task-0","closed":true,"last_activity":"2026-08-20T10:00:00Z"}]}`))
			return
		}
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{}`))
	}))
	t.Cleanup(server.Close)
	session := Session{Server: server.URL, Token: "armd_secret"}

	names := make([]string, tasksPerAsk+1)
	for i := range names {
		names[i] = fmt.Sprintf("task-%d", i)
	}
	states, err := session.TaskStates(context.Background(), names)
	if err == nil {
		t.Fatal("a failed batch came back as a successful lookup")
	}
	if states != nil {
		t.Fatalf("a failed lookup handed back %d states", len(states))
	}
	if !strings.Contains(err.Error(), "500") {
		t.Errorf("the failure does not say what the server answered: %v", err)
	}
}
