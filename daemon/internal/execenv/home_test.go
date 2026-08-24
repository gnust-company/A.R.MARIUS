package execenv

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func buildSpec(t *testing.T, cli string) Spec {
	t.Helper()
	root := t.TempDir()
	return Spec{
		CLI:          cli,
		Home:         filepath.Join(root, "work", "task-1", "home"),
		StateRoot:    filepath.Join(root, "state"),
		OperatorHome: filepath.Join(root, "operator"),
		AgentID:      "agent-1",
		TaskID:       "task-1",
	}
}

func TestAHomeIsBuiltWhereItWasAskedFor(t *testing.T) {
	spec := buildSpec(t, "claude")
	home, err := Build(spec)
	if err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}
	if home.Path != spec.Home {
		t.Errorf("home built at %s, want %s", home.Path, spec.Home)
	}
	if info, err := os.Stat(spec.Home); err != nil || !info.IsDir() {
		t.Fatalf("the home directory is not there: %v", err)
	}
}

// What outlives the run is linked out, never copied: a copy of a session database absorbs the
// run's writes into a file the next run throws away.
func TestWhatOutlivesTheRunIsALinkNotACopy(t *testing.T) {
	spec := buildSpec(t, "claude")
	home, err := Build(spec)
	if err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}

	link := filepath.Join(spec.Home, ".armarius", "sessions")
	info, err := os.Lstat(link)
	if err != nil {
		t.Fatalf("the session directory is not there: %v", err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Fatal("the session directory is a real directory — a copy, not a link")
	}

	target, err := os.Readlink(link)
	if err != nil {
		t.Fatalf("could not read the link: %v", err)
	}
	want, err := StorePath(spec.StateRoot, "claude", PerTask, spec.AgentID, spec.TaskID)
	if err != nil {
		t.Fatalf("StorePath returned an error: %v", err)
	}
	if target != want {
		t.Errorf("the session link points at %s, want %s", target, want)
	}
	if info, err := os.Stat(want); err != nil || !info.IsDir() {
		t.Fatalf("the store the link points at does not exist: %v", err)
	}
	if len(home.Stores) != 1 || home.Stores[0] != want {
		t.Errorf("the reported stores are %v, want just %s", home.Stores, want)
	}
}

// Everything outside the working tree begins with the CLI's own name. There is no shared store,
// which is the whole of FR-007e.
func TestNoTwoCLIsEverShareAStore(t *testing.T) {
	seen := map[string]string{}
	for _, cli := range KnownCLIs() {
		for _, lt := range []Lifetime{PerTask, PerAgent} {
			path, err := StorePath("/state", cli, lt, "agent-1", "task-1")
			if err != nil {
				t.Fatalf("StorePath(%s, %s): %v", cli, lt, err)
			}
			if !strings.HasPrefix(path, filepath.Join("/state", cli)+string(filepath.Separator)) {
				t.Errorf("the %s store of %s is at %s, which is not under its own name", lt, cli, path)
			}
			if other, clash := seen[path]; clash {
				t.Errorf("%s and %s share the store %s", cli, other, path)
			}
			seen[path] = cli
		}
	}
}

// FR-007e: long-term memory is a feature some CLIs happen to have, not something Armarius
// provides. None of the first round declares one, and no store should exist for it.
func TestNoCLIInTheFirstRoundClaimsLongTermMemory(t *testing.T) {
	for cli, entries := range layouts {
		for _, e := range entries {
			if e.Lifetime == PerAgent {
				t.Errorf("%s declares a per-agent store at %s — if that is intended, it needs its own retention", cli, e.Path)
			}
		}
	}

	spec := buildSpec(t, "codex")
	home, err := Build(spec)
	if err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}
	for _, store := range home.Stores {
		if strings.Contains(store, string(filepath.Separator)+"memory"+string(filepath.Separator)) {
			t.Errorf("a memory store was created at %s although no CLI asked for one", store)
		}
	}
}

// Guessing Gemini's layout before T013 has run would be worse than having none.
func TestGeminiHasNoLayoutUntilItHasBeenRunForReal(t *testing.T) {
	for _, cli := range KnownCLIs() {
		if cli == "gemini" {
			t.Fatal("a layout was written for gemini before the research task that verifies it")
		}
	}
	if _, err := Build(buildSpec(t, "gemini")); err == nil {
		t.Fatal("a home was built for gemini")
	}
}

func TestAnUnknownCLIIsRefusedByName(t *testing.T) {
	_, err := Build(buildSpec(t, "notepad"))
	if err == nil {
		t.Fatal("a home was built for a CLI nobody declared")
	}
	if !strings.Contains(err.Error(), "notepad") {
		t.Errorf("the error does not name the CLI: %v", err)
	}
}

// An operator who has never logged into this CLI has nothing to link to. That is a CLI they have
// not set up yet, not a failure of ours.
func TestOperatorFilesThatDoNotExistAreSimplySkipped(t *testing.T) {
	spec := buildSpec(t, "codex")
	if _, err := Build(spec); err != nil {
		t.Fatalf("Build failed because the operator has never run codex: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(spec.Home, ".codex", "auth.json")); err == nil {
		t.Error("a link was made to an operator file that does not exist")
	}
}

func TestOperatorFilesThatExistAreLinkedIn(t *testing.T) {
	spec := buildSpec(t, "codex")
	auth := filepath.Join(spec.OperatorHome, ".codex", "auth.json")
	if err := os.MkdirAll(filepath.Dir(auth), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(auth, []byte(`{"not":"a real token"}`), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := Build(spec); err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}
	got, err := os.Readlink(filepath.Join(spec.Home, ".codex", "auth.json"))
	if err != nil {
		t.Fatalf("the operator's credentials were not linked in: %v", err)
	}
	if got != auth {
		t.Errorf("the link points at %s, want %s", got, auth)
	}
}

// A link that cannot be made is an error. It must never become a copy behind the operator's back.
func TestALinkThatCannotBeMadeIsAnErrorNotAQuietCopy(t *testing.T) {
	spec := buildSpec(t, "claude")
	blocked := filepath.Join(spec.Home, ".armarius", "sessions")
	if err := os.MkdirAll(filepath.Dir(blocked), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(blocked, []byte("something is already here"), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err := Build(spec)
	if err == nil {
		t.Fatal("Build reported success although the session link could not be made")
	}
	if !strings.Contains(err.Error(), "sessions") {
		t.Errorf("the error does not say what could not be linked: %v", err)
	}
}

func TestAStoreNeedsSomethingToBeKeyedBy(t *testing.T) {
	cases := map[string]struct {
		lt      Lifetime
		agentID string
		taskID  string
	}{
		"a per-task store with no task":   {PerTask, "agent-1", ""},
		"a per-agent store with no agent": {PerAgent, "", "task-1"},
		"a per-run thing has no store":    {PerRun, "agent-1", "task-1"},
		"the operator's own files":        {Operator, "agent-1", "task-1"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := StorePath("/state", "claude", c.lt, c.agentID, c.taskID); err == nil {
				t.Fatalf("%s was given a store path", name)
			}
		})
	}
}
