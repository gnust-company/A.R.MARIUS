package execenv

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

const credentials = ".claude/.credentials.json"

// claudeHome builds a real Claude Code home over an operator who is signed in.
func claudeHome(t *testing.T) (home, operator string) {
	t.Helper()
	root := t.TempDir()
	operator = filepath.Join(root, "operator")
	home = filepath.Join(root, "work", ".armarius", "home")
	write(t, filepath.Join(operator, credentials), `{"claudeAiOauth":{"refreshToken":"first"}}`)
	// Signed in a while ago, as an operator's file is by the time a run renews it.
	old := time.Now().Add(-time.Hour)
	if err := os.Chtimes(filepath.Join(operator, credentials), old, old); err != nil {
		t.Fatal(err)
	}
	if _, err := Build(Spec{
		CLI: string(agentcli.ClaudeCode), Home: home, StateRoot: filepath.Join(root, "stores"),
		OperatorHome: operator, AgentID: "agent", TaskID: "task",
	}); err != nil {
		t.Fatalf("building the home: %v", err)
	}
	return home, operator
}

func write(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
}

func readBack(t *testing.T, path string) string {
	t.Helper()
	body, err := os.ReadFile(path) //nolint:gosec // a path inside this test's own directory
	if err != nil {
		t.Fatal(err)
	}
	return string(body)
}

// renewAsClaudeCodeDoes writes the way the 2.1.322 binary writes its credentials: a file
// staged beside the name, then renamed over it.
func renewAsClaudeCodeDoes(t *testing.T, path, body string) {
	t.Helper()
	staged := path + ".tmp.4f1c"
	if err := os.WriteFile(staged, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(staged, path); err != nil {
		t.Fatal(err)
	}
}

func isLink(t *testing.T, path string) bool {
	t.Helper()
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	return info.Mode()&os.ModeSymlink != 0
}

// The whole reason this file exists, shown rather than asserted: a renewal inside a run never
// reaches the operator's home on its own.
func TestARenewalInsideARunLandsOnTheLinkNotThroughIt(t *testing.T) {
	home, operator := claudeHome(t)
	inHome := filepath.Join(home, credentials)
	if !isLink(t, inHome) {
		t.Fatal("the home was not built with the sign-in linked in")
	}

	renewAsClaudeCodeDoes(t, inHome, `{"claudeAiOauth":{"refreshToken":"second"}}`)

	if isLink(t, inHome) {
		t.Fatal("the rename wrote through the link; nothing here needs carrying back")
	}
	if got := readBack(t, filepath.Join(operator, credentials)); got != `{"claudeAiOauth":{"refreshToken":"first"}}` {
		t.Fatalf("the operator's file changed by itself: %s", got)
	}
}

func TestARenewedSignInIsCarriedBackAndTheLinkPutBack(t *testing.T) {
	home, operator := claudeHome(t)
	inHome := filepath.Join(home, credentials)
	renewed := `{"claudeAiOauth":{"refreshToken":"second"}}`
	renewAsClaudeCodeDoes(t, inHome, renewed)

	carried, err := CarryBack(string(agentcli.ClaudeCode), home, operator)

	if err != nil {
		t.Fatalf("carrying back: %v", err)
	}
	if len(carried) != 1 || carried[0] != credentials {
		t.Errorf("carried %v, want just the sign-in", carried)
	}
	theirs := filepath.Join(operator, credentials)
	if got := readBack(t, theirs); got != renewed {
		t.Errorf("the operator's sign-in is still the spent one: %s", got)
	}
	info, err := os.Stat(theirs)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("the operator's sign-in is readable as %v, want owner only", info.Mode().Perm())
	}
	if !isLink(t, inHome) {
		t.Error("the link was not put back, so a second renewal would be lost like the first")
	}
	// The run goes on reading the same sign-in, now through the link again.
	if got := readBack(t, inHome); got != renewed {
		t.Errorf("the run now reads %s", got)
	}
	if left, _ := filepath.Glob(filepath.Join(operator, ".claude", ".armarius-carry-*")); len(left) != 0 {
		t.Errorf("staging files left in the operator's home: %v", left)
	}
}

func TestASignInNobodyRewroteIsLeftAlone(t *testing.T) {
	home, operator := claudeHome(t)
	before, err := os.Stat(filepath.Join(operator, credentials))
	if err != nil {
		t.Fatal(err)
	}

	carried, err := CarryBack(string(agentcli.ClaudeCode), home, operator)

	if err != nil || len(carried) != 0 {
		t.Fatalf("carried %v (%v) from a run that renewed nothing", carried, err)
	}
	after, err := os.Stat(filepath.Join(operator, credentials))
	if err != nil {
		t.Fatal(err)
	}
	if !after.ModTime().Equal(before.ModTime()) {
		t.Error("the operator's file was rewritten although nothing changed")
	}
}

// A CLI that signed out inside one run has not signed the operator out.
func TestASignInRemovedInsideARunDoesNotRemoveTheOperators(t *testing.T) {
	home, operator := claudeHome(t)
	if err := os.Remove(filepath.Join(home, credentials)); err != nil {
		t.Fatal(err)
	}

	carried, err := CarryBack(string(agentcli.ClaudeCode), home, operator)

	if err != nil || len(carried) != 0 {
		t.Fatalf("carried %v (%v)", carried, err)
	}
	if got := readBack(t, filepath.Join(operator, credentials)); got == "" {
		t.Error("the operator was signed out by a run")
	}
}

// The operator signed in again while the run was going: theirs is the newer truth, and the
// run's copy must not overwrite it.
func TestAnOperatorWhoSignedInSinceKeepsTheirOwn(t *testing.T) {
	home, operator := claudeHome(t)
	inHome := filepath.Join(home, credentials)
	renewAsClaudeCodeDoes(t, inHome, `{"claudeAiOauth":{"refreshToken":"second"}}`)
	theirs := filepath.Join(operator, credentials)
	write(t, theirs, `{"claudeAiOauth":{"refreshToken":"signed-in-again"}}`)
	later := time.Now().Add(time.Minute)
	if err := os.Chtimes(theirs, later, later); err != nil {
		t.Fatal(err)
	}

	carried, err := CarryBack(string(agentcli.ClaudeCode), home, operator)

	if err != nil || len(carried) != 0 {
		t.Fatalf("carried %v (%v) over a newer sign-in", carried, err)
	}
	if got := readBack(t, theirs); got != `{"claudeAiOauth":{"refreshToken":"signed-in-again"}}` {
		t.Errorf("the operator's newer sign-in was overwritten: %s", got)
	}
	if !isLink(t, inHome) {
		t.Error("the link was not put back")
	}
}

// Whatever is in the home, the operator's sign-in is never traded for something that is not one.
func TestSomethingThatIsNotASignInIsNeverCarried(t *testing.T) {
	home, operator := claudeHome(t)
	renewAsClaudeCodeDoes(t, filepath.Join(home, credentials), `{"claudeAiOauth":`)

	carried, err := CarryBack(string(agentcli.ClaudeCode), home, operator)

	if err != nil || len(carried) != 0 {
		t.Fatalf("carried %v (%v)", carried, err)
	}
	if got := readBack(t, filepath.Join(operator, credentials)); got != `{"claudeAiOauth":{"refreshToken":"first"}}` {
		t.Errorf("the operator's sign-in was replaced with a broken file: %s", got)
	}
}

// An operator whose own file is a link (a dotfiles manager) keeps the link.
func TestAnOperatorsOwnLinkIsWrittenThroughNotReplaced(t *testing.T) {
	home, operator := claudeHome(t)
	theirs := filepath.Join(operator, credentials)
	kept := filepath.Join(filepath.Dir(operator), "dotfiles", "credentials.json")
	write(t, kept, readBack(t, theirs))
	old := time.Now().Add(-time.Hour)
	if err := os.Chtimes(kept, old, old); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(theirs); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(kept, theirs); err != nil {
		t.Fatal(err)
	}
	renewed := `{"claudeAiOauth":{"refreshToken":"second"}}`
	renewAsClaudeCodeDoes(t, filepath.Join(home, credentials), renewed)

	if _, err := CarryBack(string(agentcli.ClaudeCode), home, operator); err != nil {
		t.Fatal(err)
	}

	if !isLink(t, theirs) {
		t.Error("the operator's own link was replaced by a file")
	}
	if got := readBack(t, kept); got != renewed {
		t.Errorf("the file behind the operator's link reads %s", got)
	}
}

func TestACLIThatDeclaresNothingHasNothingCarried(t *testing.T) {
	carried, err := CarryBack(string(agentcli.Gemini), t.TempDir(), t.TempDir())
	if err != nil || len(carried) != 0 {
		t.Fatalf("carried %v (%v)", carried, err)
	}
}
