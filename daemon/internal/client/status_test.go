package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/discovery"
)

// aMachineWith describes a machine this test does not have: which CLIs are on its PATH, and
// which process ids on it are still alive.
func aMachineWith(configPath string, installed map[string]string, alive map[int]bool) StatusOptions {
	return StatusOptions{
		ConfigPath: configPath,
		Discovery: discovery.Options{
			LookPath: func(binary string) (string, error) {
				path, ok := installed[binary]
				if !ok {
					return "", errors.New("not found in PATH")
				}
				return path, nil
			},
			Run: func(context.Context, string, ...string) ([]byte, error) {
				return []byte("1.2.3"), nil
			},
			Timeout: time.Second,
		},
		Alive: func(pid int) bool { return alive[pid] },
		Now:   func() time.Time { return time.Date(2026, 8, 25, 12, 0, 0, 0, time.UTC) },
	}
}

func linkedConfig(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "daemon.json")
	if err := SaveCredentials(path, Credentials{
		Server:      "https://armarius.example",
		Token:       "armd_secret",
		MachineID:   "m-1",
		WorkspaceID: "ws-1",
	}); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestAMachineNobodyLinkedSaysSoRatherThanFailing(t *testing.T) {
	config := filepath.Join(t.TempDir(), "daemon.json")

	got, err := Report(context.Background(), aMachineWith(config, nil, nil))
	if err != nil {
		t.Fatalf("a machine that was never set up is an answer, not a failure: %v", err)
	}

	if got.Linked || got.DaemonRunning {
		t.Errorf("nothing is set up here, yet status said %+v", got)
	}
	var text bytes.Buffer
	got.WriteText(&text, time.Now())
	if !strings.Contains(text.String(), "login") {
		t.Errorf("the answer does not say what to do about it:\n%s", text.String())
	}
}

func TestARunningDaemonIsReportedAsRunning(t *testing.T) {
	config := linkedConfig(t)
	started := time.Date(2026, 8, 25, 11, 0, 0, 0, time.UTC)
	beat := time.Date(2026, 8, 25, 11, 59, 55, 0, time.UTC)
	save(t, config, RunState{
		PID:          4242,
		StartedAt:    started,
		LastBeatOKAt: beat,
		Workplaces: []RegisteredWorkplace{
			{ID: "wp-1", CLIKind: "claude_code", Ready: true, MachineName: "gnust-thinkpad"},
		},
	})

	got, err := Report(context.Background(), aMachineWith(config, map[string]string{"claude": "/usr/bin/claude"}, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}

	if !got.Linked || got.WorkspaceID != "ws-1" {
		t.Errorf("the workspace this machine belongs to did not come through: %+v", got)
	}
	if !got.DaemonRunning || got.DaemonPID != 4242 {
		t.Errorf("a live process was reported as %+v", got)
	}
	if got.StoppedUncleanly {
		t.Error("a running daemon was reported as one that crashed")
	}
	var text bytes.Buffer
	got.WriteText(&text, time.Date(2026, 8, 25, 12, 0, 0, 0, time.UTC))
	if !strings.Contains(text.String(), "5s ago") {
		t.Errorf("the answer does not say how long since the server last heard from here:\n%s", text.String())
	}
}

// A state file with no process behind it means one specific thing, because the file is removed
// on a clean stop: the daemon was killed rather than stopped.
func TestAStateFileWithNoProcessBehindItReadsAsAnUncleanStop(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{PID: 4242, StartedAt: time.Now().Add(-time.Hour)})

	got, err := Report(context.Background(), aMachineWith(config, nil, map[int]bool{4242: false}))
	if err != nil {
		t.Fatal(err)
	}

	if got.DaemonRunning {
		t.Fatal("a dead process was reported as running")
	}
	if !got.StoppedUncleanly {
		t.Error("a leftover state file is how an unclean stop is visible at all")
	}
}

// The case this whole command exists for. From the web, a machine whose token expired looks
// exactly like a machine that was switched off: both simply stop saying anything. Here the
// process is plainly up and the reason nothing arrives is plainly stated.
func TestADaemonThatIsUpButNotGettingThroughSaysWhy(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{
		PID:           4242,
		StartedAt:     time.Now().Add(-time.Hour),
		LastBeatError: "https://armarius.example/daemon/heartbeat answered 401 Unauthorized",
	})

	got, err := Report(context.Background(), aMachineWith(config, nil, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}

	if !got.DaemonRunning {
		t.Fatal("the process is up; status must not call it dead")
	}
	var text bytes.Buffer
	got.WriteText(&text, time.Now())
	if !strings.Contains(text.String(), "401") {
		t.Errorf("the answer does not say why nothing is reaching the server:\n%s", text.String())
	}
}

// The other case only this command can settle: the machine is up and beating, and an agent CLI
// was uninstalled underneath it. The live sweep and the server's last answer disagree, and
// both are shown, which is what makes the disagreement visible at all.
func TestACLIRemovedUnderneathAWorkingDaemonIsVisible(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{
		PID:          4242,
		StartedAt:    time.Now().Add(-time.Hour),
		LastBeatOKAt: time.Now(),
		Workplaces: []RegisteredWorkplace{
			{ID: "wp-1", CLIKind: "claude_code", Ready: true, MachineName: "box"},
			{ID: "wp-2", CLIKind: "gemini", Ready: true, MachineName: "box"},
		},
	})

	// Only claude is on this machine now. gemini went away since the daemon started.
	got, err := Report(context.Background(), aMachineWith(config, map[string]string{"claude": "/usr/bin/claude"}, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}

	here := map[string]bool{}
	for _, cli := range got.CLIs {
		here[cli.Kind] = true
	}
	if here["gemini"] {
		t.Fatal("gemini is not on this machine; the sweep must not report it")
	}
	if len(got.Workplaces) != 2 {
		t.Fatalf("the server's last answer must be shown as it was, got %+v", got.Workplaces)
	}
	var text bytes.Buffer
	got.WriteText(&text, time.Now())
	printed := text.String()
	if strings.Count(printed, "gemini") != 1 {
		t.Errorf("gemini should appear once — registered, and not here now:\n%s", printed)
	}
	if !strings.Contains(printed, "claude_code") {
		t.Errorf("the CLI that is still here is missing from the answer:\n%s", printed)
	}
}

// A binary on PATH that will not run is the third way a machine quietly offers less than it
// looks like it does, so it has to be named here too.
func TestABrokenCLIIsNamedWithItsReason(t *testing.T) {
	config := linkedConfig(t)
	opts := aMachineWith(config, map[string]string{"codex": "/usr/local/bin/codex"}, nil)
	opts.Discovery.Run = func(context.Context, string, ...string) ([]byte, error) {
		return nil, errors.New("exit status 1: Missing optional dependency")
	}

	got, err := Report(context.Background(), opts)
	if err != nil {
		t.Fatal(err)
	}

	if len(got.CLIs) != 1 || got.CLIs[0].Unusable == "" {
		t.Fatalf("a broken CLI must be reported as broken, got %+v", got.CLIs)
	}
	var text bytes.Buffer
	got.WriteText(&text, time.Now())
	if !strings.Contains(text.String(), "cli_not_runnable") {
		t.Errorf("the answer does not say why codex offers no workplace:\n%s", text.String())
	}
}

// The state file sits beside a config file holding a token that speaks for the whole machine.
// It must never become a second copy of that token.
func TestTheStateFileNeverHoldsTheToken(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{PID: 1, StartedAt: time.Now()})

	raw, err := os.ReadFile(StatePath(config))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "armd_") {
		t.Fatalf("the state file carries a machine token:\n%s", raw)
	}
	info, err := os.Stat(StatePath(config))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("state file mode = %v, want 0600", info.Mode().Perm())
	}
}

func TestAStoppedDaemonLeavesNoStateFile(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{PID: 1, StartedAt: time.Now()})

	RemoveState(StatePath(config))

	got, err := Report(context.Background(), aMachineWith(config, nil, nil))
	if err != nil {
		t.Fatal(err)
	}
	if got.StoppedUncleanly {
		t.Error("a daemon that removed its own state file stopped cleanly")
	}
	if got.DaemonRunning {
		t.Error("nothing is running here")
	}
}

// FR-005a wants both halves, and they have to agree.
func TestTheJSONAnswerCarriesTheSameFactsAsTheText(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{
		PID:          4242,
		StartedAt:    time.Date(2026, 8, 25, 11, 0, 0, 0, time.UTC),
		LastBeatOKAt: time.Date(2026, 8, 25, 11, 59, 55, 0, time.UTC),
		Workplaces:   []RegisteredWorkplace{{ID: "wp-1", CLIKind: "gemini", Ready: false, NotReadyReason: "cli_removed"}},
	})

	got, err := Report(context.Background(), aMachineWith(config, nil, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}

	var encoded bytes.Buffer
	if err := got.WriteJSON(&encoded); err != nil {
		t.Fatal(err)
	}
	var answered map[string]any
	if err := json.Unmarshal(encoded.Bytes(), &answered); err != nil {
		t.Fatalf("the machine-readable half is not JSON: %v", err)
	}
	if answered["linked"] != true || answered["daemon_running"] != true {
		t.Errorf("the JSON disagrees with the text: %v", answered)
	}
	if answered["workspace_id"] != "ws-1" {
		t.Errorf("workspace_id = %v", answered["workspace_id"])
	}
	places, _ := answered["workplaces"].([]any)
	if len(places) != 1 {
		t.Fatalf("the workplaces did not survive the encoding: %v", answered["workplaces"])
	}
}

// A machine that never beat must not claim it beat in the year one.
func TestATimestampNobodyWroteIsAbsentRatherThanTheYearOne(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{PID: 4242, StartedAt: time.Now()})

	got, err := Report(context.Background(), aMachineWith(config, nil, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}

	var encoded bytes.Buffer
	if err := got.WriteJSON(&encoded); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(encoded.String(), "0001-01-01") {
		t.Errorf("a timestamp nobody wrote was printed as a real one:\n%s", encoded.String())
	}
}

// The real check, on this machine's own process ids. Both answers have to be right, or every
// verdict about a daemon being alive is a coin toss.
func TestTheLivenessCheckTellsThisProcessFromOneThatIsGone(t *testing.T) {
	if !processAlive(os.Getpid()) {
		t.Error("this very process was reported as not running")
	}
	// Process id 0 is never a user process on any platform this builds for.
	if processAlive(0) {
		t.Error("a process id that cannot exist was reported as running")
	}
}

func save(t *testing.T, configPath string, state RunState) {
	t.Helper()
	if err := SaveState(StatePath(configPath), state); err != nil {
		t.Fatal(err)
	}
}
