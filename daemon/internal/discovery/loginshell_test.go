package discovery

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// A CLI the daemon's own search path does not have is looked for where the operator's shell
// would find it (FR-002a). Kimi Code is the case this was measured on: its installer puts it in
// `~/.kimi-code/bin` and adds that to PATH in `~/.bashrc`, which a daemon never reads.
func TestACLIOffTheDaemonsPathIsFoundWhereTheOperatorsShellFindsIt(t *testing.T) {
	m := &machine{
		installed: map[string]string{"claude": "/usr/bin/claude"},
		answers: map[string]string{
			"/usr/bin/claude":                    "2.1.322 (Claude Code)",
			"/home/operator/.kimi-code/bin/kimi": "2.5.3",
		},
	}
	opts := m.options()
	var asked [][]string
	opts.Elsewhere = func(_ context.Context, binaries []string) map[string]string {
		asked = append(asked, binaries)
		return map[string]string{"kimi": "/home/operator/.kimi-code/bin/kimi"}
	}

	got := Discover(context.Background(), opts)

	if len(got.Found) != 2 || got.Found[0].Kind != agentcli.ClaudeCode || got.Found[1].Kind != agentcli.Kimi {
		t.Fatalf("found %+v, want claude from the path and kimi from the shell, in the table's order", got.Found)
	}
	kimi := got.Found[1]
	if kimi.Path != "/home/operator/.kimi-code/bin/kimi" || kimi.Version != "2.5.3" {
		t.Errorf("kimi = %+v: the path the shell gave is the one that has to be run", kimi)
	}
	// One question for everything missing, and only for what is missing: the question starts
	// somebody's shell and runs their startup files.
	want := [][]string{{"gemini", "codex", "kimi"}}
	if !reflect.DeepEqual(asked, want) {
		t.Errorf("the shell was asked %v, want %v", asked, want)
	}
}

func TestTheShellIsNotAskedWhenNothingIsMissing(t *testing.T) {
	m := &machine{installed: map[string]string{}, answers: map[string]string{}}
	for _, row := range agentcli.All() {
		m.installed[row.Binary] = "/usr/bin/" + row.Binary
		m.answers["/usr/bin/"+row.Binary] = "1.0.0"
	}
	opts := m.options()
	opts.Elsewhere = func(context.Context, []string) map[string]string {
		t.Error("every CLI was on the path and the operator's shell was started anyway")
		return nil
	}

	Discover(context.Background(), opts)
}

// A binary the shell placed and that will not run is news in the same way one on the path is.
func TestACLITheShellFoundThatWillNotRunIsReportedAsBroken(t *testing.T) {
	m := &machine{
		installed: map[string]string{},
		failures:  map[string]error{"/opt/kimi/kimi": errors.New("exec format error")},
	}
	opts := m.options()
	opts.Elsewhere = func(context.Context, []string) map[string]string {
		return map[string]string{"kimi": "/opt/kimi/kimi"}
	}

	got := Discover(context.Background(), opts)

	if len(got.Found) != 0 || len(got.Skipped) != 1 || got.Skipped[0].Kind != agentcli.Kimi {
		t.Fatalf("found %+v, skipped %+v", got.Found, got.Skipped)
	}
}

// A caller that describes a search path of its own has described the whole machine. Defaulting
// the shell in beside it would have a test — or a `status` asked about a machine that is not
// this one — answered by whatever is installed where the code happens to run.
func TestDescribingTheSearchPathLeavesTheRealShellOut(t *testing.T) {
	described := Options{LookPath: func(string) (string, error) { return "", errors.New("not found") }}.withDefaults()
	if described.Elsewhere != nil {
		t.Error("a described search path got the real login shell as well")
	}
	if real := (Options{}).withDefaults(); real.Elsewhere == nil {
		t.Error("the real search path has nowhere else to look")
	}
}

// What the shell prints is the operator's startup files talking as much as it is the answer.
func TestOnlyAnAbsolutePathThatRunsIsTakenFromWhatTheShellPrinted(t *testing.T) {
	runnable := func(path string) (string, error) {
		if path == "/gone/with/the/shell/gemini" {
			return "", errors.New("no such file")
		}
		return path, nil
	}
	out := strings.Join([]string{
		"Welcome back! You have new mail.",
		"kimi\t/home/operator/.kimi-code/bin/kimi",
		"codex\tcodex: aliased to npx codex",
		"gemini\t/gone/with/the/shell/gemini",
		"rm -rf\t/bin/rm",
		"",
	}, "\n")

	got := placed(out, runnable)

	want := map[string]string{"kimi": "/home/operator/.kimi-code/bin/kimi"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("placed %v, want %v", got, want)
	}
}

func TestOnlyABareNameIsWrittenIntoTheScript(t *testing.T) {
	for _, name := range []string{"kimi", "kiro-cli", "cursor_agent", "a.b"} {
		if !bareName(name) {
			t.Errorf("%q was refused", name)
		}
	}
	for _, name := range []string{"", "kimi; rm -rf ~", "$(id)", "a b", "../kimi", "kimi\n"} {
		if bareName(name) {
			t.Errorf("%q would be written into a shell script as it is", name)
		}
	}
}

// The script itself, run by a real POSIX shell — not as a login shell, so nobody's startup
// files are involved — against a directory holding one program. It also has to work when the
// shell's own search path holds nothing else at all, which is the daemon's situation and the
// reason the script splits paths without `dirname`.
func TestTheScriptPlacesAProgramEvenWithNothingElseOnThePath(t *testing.T) {
	sh, err := exec.LookPath("sh")
	if err != nil {
		t.Skipf("this machine has no sh: %v", err)
	}
	dir := t.TempDir()
	program := filepath.Join(dir, "kimi")
	if err := os.WriteFile(program, []byte("#!/bin/sh\n"), 0o700); err != nil { //nolint:gosec // a test's own scratch program
		t.Fatal(err)
	}
	real, err := filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatal(err)
	}

	cmd := exec.CommandContext(context.Background(), sh, "-c", whereScript([]string{"kimi", "a-cli-nobody-installed"})) //nolint:gosec // a script built from fixed names
	cmd.Env = []string{"PATH=" + dir}
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("the script failed in sh: %v", err)
	}

	got := placed(string(out), func(path string) (string, error) { return path, nil })
	want := map[string]string{"kimi": filepath.Join(real, "kimi")}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("placed %v from %q, want %v", got, out, want)
	}
}

func TestNoShellMeansNothingFoundRatherThanAnError(t *testing.T) {
	t.Setenv("SHELL", "")
	if got := askLoginShell(context.Background(), []string{"kimi"}); len(got) != 0 {
		t.Errorf("found %v with no shell to ask", got)
	}
	t.Setenv("SHELL", "/usr/bin/fish")
	if got := askLoginShell(context.Background(), []string{"kimi"}); len(got) != 0 {
		t.Errorf("found %v by handing a POSIX script to a shell that is not one", got)
	}
}
