package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// This file drives `start` itself — the whole command, against a server that answers and a CLI
// that runs — because the thing it is about is not in any package: it is which context the run
// is started on, and that choice exists only in main.go.
//
// Everything is real except the two edges a test cannot have: the server is an httptest handler
// speaking the daemon's own wire format, and the agent CLI is a script on a PATH of this test's
// own making. The daemon does not know either of them is not the real thing.

// fakeServer is the server side of one machine's whole life, for as long as one test needs it.
type fakeServer struct {
	mu sync.Mutex

	// grant is handed out once, on the first ask. A second ask comes back empty, the way a
	// server with nothing left to give answers.
	grant     map[string]any
	handedOut bool

	started      bool
	finished     map[string]any
	deregistered bool
	// runWasOverWhenWeSaidGoodbye is read at the moment the goodbye arrives, not afterwards.
	// Asked later, both facts are true and the order between them — which is the whole promise
	// — has already been lost.
	runWasOverWhenWeSaidGoodbye bool
	events                      int
}

func (f *fakeServer) handler(t *testing.T) http.Handler {
	t.Helper()
	mux := http.NewServeMux()

	mux.HandleFunc("PUT /daemon/workplaces", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Workplaces []map[string]any `json:"workplaces"`
			Stopping   bool             `json:"stopping"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		f.mu.Lock()
		if body.Stopping {
			f.deregistered = true
			f.runWasOverWhenWeSaidGoodbye = f.finished != nil
		}
		f.mu.Unlock()
		reply(w, map[string]any{"workplaces": []map[string]any{{
			"id": "wp-1", "cli_kind": "claude_code", "ready": true,
			"not_ready_reason": "", "machine_name": "testbox",
		}}})
	})

	mux.HandleFunc("POST /daemon/heartbeat", func(w http.ResponseWriter, _ *http.Request) {
		reply(w, map[string]any{"pending_work": false, "cancel": []string{}})
	})

	mux.HandleFunc("POST /daemon/runs/claim", func(w http.ResponseWriter, _ *http.Request) {
		f.mu.Lock()
		runs := []map[string]any{}
		if !f.handedOut {
			f.handedOut = true
			runs = append(runs, f.grant)
		}
		f.mu.Unlock()
		reply(w, map[string]any{"runs": runs})
	})

	mux.HandleFunc("POST /daemon/runs/{id}/start", func(w http.ResponseWriter, _ *http.Request) {
		f.mu.Lock()
		f.started = true
		f.mu.Unlock()
		reply(w, map[string]any{"still_yours": true})
	})

	mux.HandleFunc("POST /daemon/runs/{id}/events", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Events []map[string]any `json:"events"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		f.mu.Lock()
		f.events += len(body.Events)
		f.mu.Unlock()
		reply(w, map[string]any{})
	})

	mux.HandleFunc("POST /daemon/runs/{id}/finish", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		f.mu.Lock()
		f.finished = body
		f.mu.Unlock()
		reply(w, map[string]any{})
	})

	mux.HandleFunc("POST /daemon/tasks/states", func(w http.ResponseWriter, _ *http.Request) {
		reply(w, map[string]any{"tasks": []map[string]any{}})
	})

	// The push road. Held open and silent: this test drives work through the ask loop, which
	// is the road that has to work whether or not a nudge ever arrives (FR-055d).
	mux.HandleFunc("GET /daemon/events", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		<-r.Context().Done()
	})

	return mux
}

func reply(w http.ResponseWriter, body map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(body)
}

// aStubCLI writes a script that answers the three questions the daemon asks a Claude Code
// installation — its version, its own help text, and a turn — and puts it on this test's PATH.
//
// `started` is touched the moment a turn begins and `ended` when it finishes on its own, so a
// test can tell "the agent was cut" from "the agent was let finish" without reading the clock.
func aStubCLI(t *testing.T, turnTakes time.Duration) (started, ended string) {
	t.Helper()
	dir := t.TempDir()
	started = filepath.Join(dir, "started")
	ended = filepath.Join(dir, "ended")

	// Every command is named absolutely and every other step is a shell builtin, because the
	// PATH this script runs under is the one below: a directory holding nothing but this file.
	// A `sleep` that cannot be found does not stop the script — it prints and carries on — and
	// a turn that finishes instantly would let every test in this file pass without proving
	// anything at all.
	nap, err := exec.LookPath("sleep")
	if err != nil {
		t.Skipf("this machine has no sleep(1), which the stub agent needs: %v", err)
	}

	script := fmt.Sprintf(`#!/bin/sh
case "$1" in
  --version) echo "9.9.9 (Claude Code)"; exit 0 ;;
  --help)
    echo "  -r, --resume     resume a session"
    echo "  -c, --continue   continue the last session"
    echo "  --output-format  one of text, json, stream-json"
    echo "  --effort <level> Effort level for the current session (low, medium, high, xhigh, max)"
    echo "  --model <model>  Provide an alias for the latest model (e.g. 'fable', 'opus', or 'sonnet')"
    exit 0 ;;
esac
while read -r _; do :; done
: > %q
%q %.3f
: > %q
echo '{"type":"assistant","session_id":"sess-1","message":{"content":[{"type":"text","text":"done"}]}}'
echo '{"type":"result","session_id":"sess-1","subtype":"success","is_error":false}'
`, started, nap, turnTakes.Seconds(), ended)

	binDir := t.TempDir()
	path := filepath.Join(binDir, "claude")
	if err := os.WriteFile(path, []byte(script), 0o700); err != nil { //nolint:gosec // a test's own scratch script
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir)
	return started, ended
}

// aLinkedMachine writes what `login` would have left behind, pointed at a server of this test's
// own, and returns the config path `start` is given.
func aLinkedMachine(t *testing.T, server string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "daemon.json")
	written, err := json.Marshal(map[string]any{
		"server":       server,
		"token":        "armd_test",
		"workspace_id": "ws-1",
		"machine_id":   "m-1",
		// Short, so a test that has to see two beats does not take half a minute.
		"heartbeat_interval": "1s",
		"poll_interval":      "200ms",
		"drain_patience":     "20s",
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, written, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func waitFor(t *testing.T, what string, ok func() bool) {
	t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if ok() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// aRunningDaemon starts `start` against a server of this test's own and hands back the fake
// server, a way to stop the daemon, and a way to wait for it to have stopped.
func aRunningDaemon(t *testing.T, turnTakes time.Duration) (
	*fakeServer, string, string, func(), func() string,
) {
	t.Helper()
	startedMarker, endedMarker := aStubCLI(t, turnTakes)

	fake := &fakeServer{grant: map[string]any{
		"run_id":           "11111111-1111-1111-1111-111111111111",
		"task_id":          "22222222-2222-2222-2222-222222222222",
		"project_id":       "33333333-3333-3333-3333-333333333333",
		"workplace_id":     "wp-1",
		"run_token":        "armr_test",
		"claim_expires_at": time.Now().Add(2 * time.Minute).Format(time.RFC3339Nano),
		"prompt":           "Do the thing.",
		"skills":           []map[string]any{},
		"runtime_options":  map[string]string{},
		"first_seq":        1,
	}}
	server := httptest.NewServer(fake.handler(t))
	t.Cleanup(server.Close)

	// The agent's callback program: named rather than found beside the binary, which is what
	// this variable is for. Any file will do — nothing in this test asks the agent to call back.
	t.Setenv("ARMARIUS_CALLBACK_PROGRAM", filepath.Join(t.TempDir(), "armarius"))
	if err := os.WriteFile(os.Getenv("ARMARIUS_CALLBACK_PROGRAM"), []byte("#!/bin/sh\n"), 0o700); err != nil { //nolint:gosec // a test's own scratch file
		t.Fatal(err)
	}

	config := aLinkedMachine(t, server.URL)
	ctx, stop := context.WithCancel(context.Background())
	var out bytes.Buffer
	var printed sync.Mutex
	done := make(chan struct{})
	go func() {
		defer close(done)
		printed.Lock()
		w := &lockedWriter{mu: &printed, to: &out}
		printed.Unlock()
		_ = runStart(ctx, []string{"-config", config}, w)
	}()

	wait := func() string {
		select {
		case <-done:
		case <-time.After(30 * time.Second):
			t.Fatal("the daemon never came back after being told to stop")
		}
		printed.Lock()
		defer printed.Unlock()
		return out.String()
	}
	t.Cleanup(func() { stop(); <-done })
	return fake, startedMarker, endedMarker, stop, wait
}

// lockedWriter lets the test read what the daemon printed while it is still printing.
type lockedWriter struct {
	mu *sync.Mutex
	to *bytes.Buffer
}

func (l *lockedWriter) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.to.Write(p)
}

// FR-034: the whole point, and the only place it can be seen. Stopping the daemon stops it
// asking for work; the work it already took is allowed to end the way it was going to end.
//
// Before this, both were the same context, so a stop cut every agent mid-sentence. Nothing
// looked broken — the run still reported — it reported a failure this machine had caused, which
// on an upgrade means every machine in a fleet fails its in-flight work on every release.
func TestStoppingTheDaemonDoesNotCutTheRunItAlreadyTook(t *testing.T) {
	fake, startedMarker, endedMarker, stop, wait := aRunningDaemon(t, 2*time.Second)

	waitFor(t, "the agent to start its turn", func() bool { return exists(startedMarker) })
	if exists(endedMarker) {
		t.Fatal("the agent finished before the daemon was told to stop; the test proves nothing")
	}

	stop()
	printed := wait()

	if !exists(endedMarker) {
		t.Fatal("stopping the daemon cut the agent mid-turn")
	}

	fake.mu.Lock()
	defer fake.mu.Unlock()
	if fake.finished == nil {
		t.Fatal("the run was never reported as over")
	}
	if got := fake.finished["status"]; got != "completed" {
		t.Errorf("the run ended as %v, want completed — the stop must not turn it into a failure", got)
	}
	if !strings.Contains(printed, "Waiting up to") {
		t.Errorf("the operator was not told the stop was waiting on a run:\n%s", printed)
	}
}

// FR-005: and once there is genuinely nothing left running here, the workplaces go back.
func TestTheWorkplacesAreHandedBackOnlyAfterTheLastRunIsDone(t *testing.T) {
	fake, startedMarker, _, stop, wait := aRunningDaemon(t, time.Second)

	waitFor(t, "the agent to start its turn", func() bool { return exists(startedMarker) })
	stop()
	wait()

	fake.mu.Lock()
	defer fake.mu.Unlock()
	if !fake.deregistered {
		t.Fatal("the daemon exited without handing its workplaces back")
	}
	if !fake.runWasOverWhenWeSaidGoodbye {
		t.Error(
			"the workplaces were handed back while a run was still going: " +
				"for that moment this machine reads as gone and is still working",
		)
	}
}

// The bound on the wait is not decoration: an unbounded drain is a stop that never returns, and
// a service manager answers that with SIGKILL — which cuts the run *and* skips the goodbye.
func TestARunThatOutlastsThePatienceIsCutAndSaidOutLoud(t *testing.T) {
	startedMarker, endedMarker := aStubCLI(t, time.Minute)

	fake := &fakeServer{grant: map[string]any{
		"run_id":           "11111111-1111-1111-1111-111111111111",
		"task_id":          "22222222-2222-2222-2222-222222222222",
		"workplace_id":     "wp-1",
		"run_token":        "armr_test",
		"claim_expires_at": time.Now().Add(2 * time.Minute).Format(time.RFC3339Nano),
		"prompt":           "Do the thing.",
		"skills":           []map[string]any{},
		"runtime_options":  map[string]string{},
		"first_seq":        1,
	}}
	server := httptest.NewServer(fake.handler(t))
	t.Cleanup(server.Close)

	t.Setenv("ARMARIUS_CALLBACK_PROGRAM", filepath.Join(t.TempDir(), "armarius"))
	if err := os.WriteFile(os.Getenv("ARMARIUS_CALLBACK_PROGRAM"), []byte("#!/bin/sh\n"), 0o700); err != nil { //nolint:gosec // a test's own scratch file
		t.Fatal(err)
	}

	dir := t.TempDir()
	config := filepath.Join(dir, "daemon.json")
	written, _ := json.Marshal(map[string]any{
		"server": server.URL, "token": "armd_test", "workspace_id": "ws-1", "machine_id": "m-1",
		"heartbeat_interval": "1s", "poll_interval": "200ms",
		// Shorter than the turn, so the drain is the thing that ends this run.
		"drain_patience": "1s",
	})
	if err := os.WriteFile(config, written, 0o600); err != nil {
		t.Fatal(err)
	}

	ctx, stop := context.WithCancel(context.Background())
	var out bytes.Buffer
	var printed sync.Mutex
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = runStart(ctx, []string{"-config", config}, &lockedWriter{mu: &printed, to: &out})
	}()

	waitFor(t, "the agent to start its turn", func() bool { return exists(startedMarker) })
	stop()
	select {
	case <-done:
	case <-time.After(30 * time.Second):
		t.Fatal("the drain never gave up on a run that would not end")
	}

	if exists(endedMarker) {
		t.Fatal("the stub finished, so this test never exercised the patience running out")
	}
	printed.Lock()
	said := out.String()
	printed.Unlock()
	if !strings.Contains(said, "Cutting run") {
		t.Errorf("a run was cut without the operator being told:\n%s", said)
	}

	fake.mu.Lock()
	defer fake.mu.Unlock()
	if !fake.deregistered {
		t.Error("a stop that had to cut a run still owes the server its goodbye")
	}
}
