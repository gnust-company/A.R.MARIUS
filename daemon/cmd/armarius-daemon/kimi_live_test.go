package main

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
	"github.com/gnust-company/armarius-daemon/internal/runtime"
)

// liveKimi is the path of a Kimi Code binary this test may run **turns** on.
//
// Unset, the test is skipped: it runs two real turns on whoever is signed in to that binary,
// in the operator's real home as far as their sign-in goes. It is here because a row filled in
// from reading is a row nobody has run (FR-039a), and the set-up it checks — the home, the
// brief, the skills, the tools, the environment, the conversation — is assembled by the same
// calls a run makes, not by a script written beside them.
const liveKimi = "ARMARIUS_LIVE_KIMI_BINARY"

type liveTurn struct {
	text      string
	started   []runtime.Event
	completed []runtime.Event
	errors    []runtime.Event
	outcome   runtime.Outcome
}

// takeLiveTurn sets one run up the way supervisor.prepare does and takes one turn on it.
func takeLiveTurn(
	t *testing.T, binary, workDir, stateRoot, operatorHome, callback, runID, message, session string,
) liveTurn {
	t.Helper()
	cli := string(agentcli.Kimi)

	home, err := execenv.RunHome(workDir, runID)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(home) })
	if _, err := execenv.Build(execenv.Spec{
		CLI: cli, Home: home, StateRoot: stateRoot, OperatorHome: operatorHome, TaskID: "task-live",
	}); err != nil {
		t.Fatalf("building the home: %v", err)
	}
	if _, err := execenv.WriteContextFile(cli, workDir, message); err != nil {
		t.Fatalf("writing the brief: %v", err)
	}
	if _, err := execenv.WriteSkills(cli, workDir, home, []execenv.Skill{{
		Name: "armarius-canary-plum-otter",
		Files: map[string]string{"SKILL.md": "---\nname: armarius-canary-plum-otter\n" +
			"description: A canary skill placed to measure skill discovery.\n---\n\nSay plum otter.\n"},
	}}); err != nil {
		t.Fatalf("writing the skills: %v", err)
	}
	tools, err := execenv.PlaceTools(execenv.ToolsSpec{CLI: cli, WorkDir: workDir, Program: callback})
	if err != nil {
		t.Fatalf("placing the tools: %v", err)
	}
	const runToken = "armr_live_measurement_only" //nolint:gosec // G101: a made-up token for a server that is not there
	env, err := execenv.Environ(execenv.EnvSpec{
		CLI: cli, Home: home, WorkDir: workDir, ToolsDir: tools.Dir,
		// What a daemon started with next to nothing would hand on, plus a KIMI_CODE_HOME it
		// must not let through.
		Inherited: []string{
			"PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
			"KIMI_CODE_HOME=" + filepath.Join(operatorHome, ".kimi-code"),
		},
		Credentials: execenv.Credentials{RunID: runID, RunToken: runToken, Server: "http://127.0.0.1:9"},
	})
	if err != nil {
		t.Fatalf("building the environment: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()

	var turn liveTurn
	turn.outcome, err = runtime.ACP{}.Run(ctx, runtime.Request{
		CLI: cli, Binary: binary, WorkDir: workDir, Env: env,
		Message: message, Session: session,
		ToolServers: tools.Servers, Secrets: []string{runToken},
	}, func(e runtime.Event) {
		switch e.Type {
		case runtime.EventAssistantMessage:
			text, _ := e.Payload["text"].(string)
			turn.text += text
		case runtime.EventToolStarted:
			turn.started = append(turn.started, e)
		case runtime.EventToolCompleted:
			turn.completed = append(turn.completed, e)
		case runtime.EventRunError:
			turn.errors = append(turn.errors, e)
		}
	})
	if err != nil {
		t.Fatalf("the turn did not finish (failure %q): %v", turn.outcome.Failure, err)
	}

	// The sign-in is still the operator's own, linked: whatever was renewed went to them.
	if info, err := os.Lstat(filepath.Join(home, ".kimi-code", "credentials")); err != nil ||
		info.Mode()&os.ModeSymlink == 0 {
		t.Errorf("the credentials directory in the run's home is no longer a link (%v)", err)
	}
	if carried, err := execenv.CarryBack(cli, home, operatorHome); err != nil || len(carried) != 0 {
		t.Errorf("carried %v back (%v); nothing on this row is carried", carried, err)
	}
	return turn
}

func TestLiveKimiTakesATurnAndCarriesTheConversationOn(t *testing.T) {
	binary := os.Getenv(liveKimi)
	if binary == "" {
		t.Skipf("set %s to a Kimi Code binary to run two real turns on it", liveKimi)
	}
	operatorHome, err := os.UserHomeDir()
	if err != nil {
		t.Fatal(err)
	}

	// The callback program a run is handed, built from this tree.
	callback := filepath.Join(t.TempDir(), "armarius")
	building, built := context.WithTimeout(context.Background(), 2*time.Minute)
	defer built()
	if out, err := exec.CommandContext(building, "go", "build", "-o", callback, "../armarius").CombinedOutput(); err != nil {
		t.Fatalf("building the callback program: %v\n%s", err, out)
	}

	root := t.TempDir()
	workDir, stateRoot := filepath.Join(root, "work", "task-live"), filepath.Join(root, "stores")
	if err := os.MkdirAll(workDir, 0o700); err != nil {
		t.Fatal(err)
	}

	// What must not change in the operator's own installation, read before and after.
	index := filepath.Join(operatorHome, ".kimi-code", "session_index.jsonl")
	before, _ := os.ReadFile(index) //nolint:gosec // the operator's own file, read to compare its length only

	first := takeLiveTurn(t, binary, workDir, stateRoot, operatorHome, callback, "run-live-1",
		"Do these three things and keep the answer short. "+
			"1. Tell me the exact name of the skill available to you whose name starts with armarius-canary. "+
			"2. Run the shell command `echo hello-from-kimi` and tell me what it printed. "+
			"3. Tell me the exact names of the tools you have whose name contains whoami.", "")
	t.Logf("turn 1 said: %q", first.text)
	t.Logf("turn 1 session %q, %d call(s) started, %d completed, %d error event(s)",
		first.outcome.Session, len(first.started), len(first.completed), len(first.errors))

	if first.outcome.Session == "" {
		t.Error("the turn left no session to carry on")
	}
	if !strings.Contains(first.text, "armarius-canary-plum-otter") {
		t.Error("the skill written for this run was not offered to the agent")
	}
	if !strings.Contains(first.text, "whoami") {
		t.Error("the callback tools declared when the session opened were not offered to the agent")
	}
	ran := false
	for _, call := range first.started {
		args, _ := call.Payload["args"].(map[string]any)
		command, _ := args["command"].(string)
		t.Logf("call %v %v args=%v omitted=%q", call.Payload["call"], call.Payload["name"], args, call.OmissionReason)
		ran = ran || strings.Contains(command, "echo hello-from-kimi")
	}
	if !ran {
		t.Error("no recorded call carries the command the agent was asked to run")
	}
	printed := false
	for _, call := range first.completed {
		opening, _ := call.Payload["opening"].(string)
		printed = printed || strings.Contains(opening, "hello-from-kimi")
	}
	if !printed {
		t.Error("no recorded result carries what the command printed")
	}

	// A second run on the same task: a home of its own, the same store behind it.
	second := takeLiveTurn(t, binary, workDir, stateRoot, operatorHome, callback, "run-live-2",
		"Which shell command did you run in your previous turn? Answer with the command only.",
		first.outcome.Session)
	t.Logf("turn 2 said: %q", second.text)

	if second.outcome.Session != first.outcome.Session || second.outcome.SessionRefused {
		t.Errorf("the second turn went on session %q (refused: %v), want %q carried on",
			second.outcome.Session, second.outcome.SessionRefused, first.outcome.Session)
	}
	if !strings.Contains(second.text, "echo hello-from-kimi") {
		t.Error("the agent did not remember the turn before")
	}
	if strings.Contains(second.text, "armarius-canary-plum-otter") {
		t.Error("the first turn's answer was recorded again as the second turn's")
	}

	after, _ := os.ReadFile(index) //nolint:gosec // as above
	if len(after) != len(before) {
		t.Errorf("the operator's own session index grew by %d bytes: a run wrote about itself "+
			"into their installation", len(after)-len(before))
	}
}
