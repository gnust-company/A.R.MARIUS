package main

import (
	"bytes"
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/config"
	"github.com/gnust-company/armarius-daemon/internal/discovery"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
	"github.com/gnust-company/armarius-daemon/internal/supervisor"
)

// dispatch runs the command line and hands back what a person would have seen on each stream.
func dispatch(t *testing.T, args ...string) (stdout, stderr string, err error) {
	t.Helper()
	var out, errOut bytes.Buffer
	err = run(context.Background(), args, &out, &errOut)
	return out.String(), errOut.String(), err
}

func TestHelpListsEverySubcommand(t *testing.T) {
	stdout, _, err := dispatch(t, "help")
	if err != nil {
		t.Fatalf("help returned an error: %v", err)
	}
	// The help text is generated from the command table, so this also proves no command can be
	// added to the table and left undocumented.
	for _, c := range commands {
		if !strings.Contains(stdout, c.name) {
			t.Errorf("help does not mention the %q command", c.name)
		}
		if !strings.Contains(stdout, c.summary) {
			t.Errorf("help does not describe the %q command", c.name)
		}
	}
}

func TestVersionPrintsTheBuildStamp(t *testing.T) {
	stdout, _, err := dispatch(t, "version")
	if err != nil {
		t.Fatalf("version returned an error: %v", err)
	}
	if !strings.Contains(stdout, version) {
		t.Errorf("version output %q does not contain the version %q", stdout, version)
	}
}

func TestNoSubcommandIsRefusedAndExplained(t *testing.T) {
	stdout, stderr, err := dispatch(t)
	if err == nil {
		t.Fatal("an empty command line was accepted")
	}
	if stdout != "" {
		t.Errorf("usage went to stdout on failure: %q", stdout)
	}
	if !strings.Contains(stderr, "Usage:") {
		t.Errorf("the operator was not shown how to use the program: %q", stderr)
	}
}

func TestUnknownSubcommandNamesWhatWasNotUnderstood(t *testing.T) {
	_, _, err := dispatch(t, "shutdown")
	if err == nil {
		t.Fatal("an unknown subcommand was accepted")
	}
	if !strings.Contains(err.Error(), "shutdown") {
		t.Errorf("the error does not say which word was not understood: %v", err)
	}
}

// Every declared subcommand must be reachable. A command sitting in the table that dispatch
// cannot reach would show up in help and then do nothing at all.
func TestEverySubcommandIsReachable(t *testing.T) {
	for _, c := range commands {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := dispatch(t, c.name, "-h")
			if err != nil {
				t.Fatalf("-h on %q returned an error: %v", c.name, err)
			}
		})
	}
}

// Asking a subcommand for help is a request, not a mistake: it must succeed and describe the
// flags, so an operator can find out what to pass before passing anything.
func TestSubcommandHelpDescribesItsFlags(t *testing.T) {
	stdout, _, err := dispatch(t, "login", "-h")
	if err != nil {
		t.Fatalf("login -h returned an error: %v", err)
	}
	if !strings.Contains(stdout, "-server") {
		t.Errorf("login -h does not mention the -server flag: %q", stdout)
	}
}

func TestLoginRefusesToRunWithoutAServer(t *testing.T) {
	_, _, err := dispatch(t, "login")
	if err == nil {
		t.Fatal("login ran without being told which server to link to")
	}
	if !strings.Contains(err.Error(), "-server") {
		t.Errorf("the error does not name the missing flag: %v", err)
	}
}

// Every subcommand this program declares is now built, so none of them may still answer with
// the not-built-yet notice. The check is over the declared list rather than a written-out one,
// so a fourth subcommand added later without its behaviour is caught here.
func TestNoSubcommandStillReportsItselfUnbuilt(t *testing.T) {
	for _, c := range commands {
		if strings.Contains(c.summary, "not built") {
			t.Errorf("%s still describes itself as unbuilt", c.name)
		}
	}
}

// `status` answers rather than fails. A machine nobody has linked is a state to report, not an
// error: reporting it is the entire job (FR-005a).
func TestStatusAnswersOnAMachineThatWasNeverLinked(t *testing.T) {
	out, _, err := dispatch(t, "status", "-config", filepath.Join(t.TempDir(), "daemon.json"))
	if err != nil {
		t.Fatalf("status failed instead of answering: %v", err)
	}
	if !strings.Contains(out, "not linked") {
		t.Errorf("status did not say the machine is not linked:\n%s", out)
	}
	if !strings.Contains(out, "not running") {
		t.Errorf("status did not say whether a daemon is running:\n%s", out)
	}
}

// The machine-readable half of FR-005a. It has to parse, and it has to carry the same answers
// the person-readable half gives.
func TestStatusAlsoAnswersInAFormAMachineCanRead(t *testing.T) {
	out, _, err := dispatch(t, "status", "-json", "-config", filepath.Join(t.TempDir(), "daemon.json"))
	if err != nil {
		t.Fatalf("status -json failed: %v", err)
	}
	var answered map[string]any
	if err := json.Unmarshal([]byte(out), &answered); err != nil {
		t.Fatalf("status -json did not print JSON: %v\n%s", err, out)
	}
	if answered["linked"] != false || answered["daemon_running"] != false {
		t.Errorf("the JSON disagrees with the text: %v", answered)
	}
}

// `start` is built as far as registering this machine and beating (T033–T038). Pointed at a
// config file that holds no token, it must refuse on the missing token rather than at the door.
func TestStartRefusesAMachineThatWasNeverLinked(t *testing.T) {
	_, _, err := dispatch(t, "start", "-config", filepath.Join(t.TempDir(), "daemon.json"))
	if err == nil {
		t.Fatal("start reported success on a machine with no token")
	}
	if !strings.Contains(err.Error(), "login") {
		t.Errorf("the error does not tell the operator to link the machine first: %v", err)
	}
}

// `login` is built (T030), so it must no longer answer with the not-built-yet notice. Given a
// server that does not resolve it has to fail on the call itself — proof that it got as far as
// trying, rather than stopping at the door.
func TestLoginActuallyGoesAndTalksToTheServer(t *testing.T) {
	_, _, err := dispatch(t, "login", "-server", "https://armarius.invalid", "-config", filepath.Join(t.TempDir(), "daemon.json"))
	if err == nil {
		t.Fatal("login reported success against a server that does not exist")
	}
	if !strings.Contains(err.Error(), "/daemon/link/start") {
		t.Errorf("login failed somewhere other than the call it exists to make: %v", err)
	}
}

func TestDefaultConfigPathIsUnderTheArmariusDirectory(t *testing.T) {
	got := defaultConfigPath()
	if !strings.Contains(got, ".armarius") || !strings.HasSuffix(got, "daemon.json") {
		t.Errorf("default config path %q is not ~/.armarius/daemon.json", got)
	}
}

func TestTheSweepAsksTheSameRegisterTheRunnerWritesTo(t *testing.T) {
	// FR-022 holds only while these two are the same object. A fresh `&supervisor.Runs{}` here
	// compiles, runs, reports nothing, and deletes the working directory of a live agent — so
	// the identity is asserted rather than left to whoever edits `start` next.
	held := &supervisor.Runs{}
	work := supervisor.RunOptions{
		WorkRoot:  "/var/armarius/work",
		StateRoot: "/var/armarius/stores",
		Runs:      held,
	}

	sweeper := housekeeping(config.Defaults(), work, client.Session{})

	if sweeper.Runs != execenv.RunHolder(held) {
		t.Fatal("vòng quét hỏi một sổ khác cái sổ lượt chạy ghi vào")
	}
	if sweeper.WorkRoot != work.WorkRoot || sweeper.StateRoot != work.StateRoot {
		t.Fatalf("vòng quét nhìn vào chỗ khác: %s, %s", sweeper.WorkRoot, sweeper.StateRoot)
	}
}

func TestTheSweepTakesTheRetentionsTheOperatorSet(t *testing.T) {
	// FR-021 and FR-027 both say the retention is settable. A collector built from the
	// defaults instead of from the file would leave every one of those settings inert.
	settings := config.Defaults()
	settings.WorkDirRetention = config.Duration(90 * time.Minute)
	settings.SessionRetention = config.Duration(48 * time.Hour)
	settings.OrphanRetention = config.Duration(30 * 24 * time.Hour)

	sweeper := housekeeping(settings, supervisor.RunOptions{Runs: &supervisor.Runs{}}, client.Session{})

	if sweeper.WorkDirRetention != 90*time.Minute {
		t.Errorf("work_dir_retention = %s", sweeper.WorkDirRetention)
	}
	if sweeper.SessionRetention != 48*time.Hour {
		t.Errorf("session_retention = %s", sweeper.SessionRetention)
	}
	if sweeper.OrphanRetention != 30*24*time.Hour {
		t.Errorf("orphan_retention = %s", sweeper.OrphanRetention)
	}
}

func TestTheWatchdogIsBuiltFromTheRegistryRatherThanLeftOnItsDefault(t *testing.T) {
	// The supervisor has always been able to take a threshold of each CLI's own, and until this
	// was wired nothing ever handed it one: `RunOptions` filled in a watchdog with no overrides
	// and every CLI on every machine ran on the base. That compiles, runs, and is
	// indistinguishable from the wiring working — so what the watchdog was built from is
	// asserted here (FR-031, FR-031a).
	watchdog, err := silenceWatchdog(agentcli.Silences())
	if err != nil {
		t.Fatalf("máy không dựng nổi bộ canh im lặng của chính nó: %v", err)
	}
	for _, row := range agentcli.All() {
		want := supervisor.DefaultSilenceThreshold
		if row.Silence > 0 {
			want = row.Silence
		}
		if got := watchdog.Threshold(string(row.Kind)); got != want {
			t.Errorf("%s bị cắt ở %s, mong %s", row.Kind, got, want)
		}
	}
	if pulled := watchdog.Loosened(); len(pulled) != 0 {
		t.Errorf("bảng đặc tính có mục bị siết lại mà máy vẫn chạy im: %v", pulled)
	}
}

func TestALooseThresholdIsPulledBackOnTheVeryPathTheMachineUses(t *testing.T) {
	// FR-031a, driven down the path `start` takes rather than against the watchdog alone. The
	// registry declares no thresholds today — agentcli says so out loud — so this hands the
	// same function a table that tries to switch the safety net off, and proves the machine
	// would clamp it and say so rather than run under it.
	watchdog, err := silenceWatchdog(map[string]time.Duration{
		"claude_code": supervisor.DefaultSilenceThreshold + time.Hour,
		"codex":       time.Minute,
	})
	if err != nil {
		t.Fatalf("silenceWatchdog trả về lỗi: %v", err)
	}
	if got := watchdog.Threshold("claude_code"); got != supervisor.DefaultSilenceThreshold {
		t.Errorf("một mục nới rộng được nhận: cắt ở %s, mong %s", got, supervisor.DefaultSilenceThreshold)
	}
	if got := watchdog.Threshold("codex"); got != time.Minute {
		t.Errorf("một mục siết chặt bị bỏ qua: cắt ở %s, mong %s", got, time.Minute)
	}
	if pulled := watchdog.Loosened(); len(pulled) != 1 || pulled[0].CLI != "claude_code" {
		t.Errorf("mục bị siết lại không được nói ra: %v", pulled)
	}
}

func TestAWorkplaceCarriesTheAnswerItsOwnBinaryGave(t *testing.T) {
	// FR-017 forbids deciding what a CLI can do from its name, so the answer has to travel from
	// the probe to the run. It used to stop at the server: capabilities were reported and never
	// read again, and every workplace on this machine was driven as though it had said yes to
	// everything.
	registered := []client.RegisteredWorkplace{
		{ID: "wp-1", CLIKind: "claude_code", Ready: true},
		{ID: "wp-2", CLIKind: "codex", Ready: true},
	}
	found := []discovery.Found{
		{Kind: agentcli.ClaudeCode, Family: agentcli.FamilyOneShot, Path: "/usr/bin/claude"},
		{Kind: agentcli.Codex, Family: agentcli.FamilyOneShot, Path: "/usr/local/bin/codex"},
	}
	answers := map[string]discovery.Capabilities{
		"claude_code": {Resumable: true},
		// The same kind of CLI, on a machine whose copy answered otherwise. This is the case the
		// name-based lookup would get wrong.
		"codex": {Resumable: false},
	}

	places := workplacesOnThisMachine(registered, found, answers)
	if len(places) != 2 {
		t.Fatalf("có %d chỗ làm, mong 2: %+v", len(places), places)
	}
	if !places["wp-1"].Resumable {
		t.Error("chỗ làm khai nối lại được mà lại mang câu trả lời ngược")
	}
	if places["wp-2"].Resumable {
		t.Error("chỗ làm khai không nối lại được vẫn được ghi là nối lại được")
	}
}

func TestAWorkplaceThisBuildCannotDriveIsLeftOut(t *testing.T) {
	// Gemini is installed, ready, and its row is blank on purpose (T013). Leaving it in the map
	// would mean asking for work there, winning a run that fails during setup, and being offered
	// the same run again — forever, a slot at a time.
	places := workplacesOnThisMachine(
		[]client.RegisteredWorkplace{{ID: "wp-1", CLIKind: "gemini", Ready: true}},
		[]discovery.Found{{Kind: agentcli.Gemini, Family: agentcli.FamilyACP, Path: "/usr/local/bin/gemini"}},
		map[string]discovery.Capabilities{"gemini": {}},
	)
	if len(places) != 0 {
		t.Errorf("máy nhận việc ở chỗ làm nó chưa lái được: %+v", places)
	}
}
