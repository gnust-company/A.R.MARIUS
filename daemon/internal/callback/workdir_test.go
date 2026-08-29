package callback

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ── what is on this disk (T088, FR-020a, FR-018) ─────────────────────────────

func TestWhatTheAgentChangedIsAnsweredHereAndNeverLeavesTheMachine(t *testing.T) {
	// The one question in the whole set whose answer is not the server's to give: it is on the
	// disk of the machine running the agent. Proved by answering it with **no server at all** —
	// no address, no token, nothing that could have been asked.
	workDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(workDir, "report.md"), []byte("done"), 0o600); err != nil {
		t.Fatalf("writing the agent's file: %v", err)
	}

	code, out, errs := run(t, Environment{RunID: "run-1", TaskID: "task-1", WorkDir: workDir},
		"workdir", "changes")
	if code != ExitOK {
		t.Fatalf("exit %d (%s), wanted %d", code, errs, ExitOK)
	}

	var answer struct {
		Total int `json:"total"`
		Files []struct {
			Path string `json:"path"`
		} `json:"changed"`
	}
	if err := json.Unmarshal([]byte(out), &answer); err != nil {
		t.Fatalf("the answer is not readable JSON: %q", out)
	}
	if answer.Total != 1 || len(answer.Files) != 1 || answer.Files[0].Path != "report.md" {
		t.Fatalf("the agent was not shown the file it wrote: %q", out)
	}
}

func TestTheDaemonListsWhatIsThereAndPublishesNoneOfIt(t *testing.T) {
	// FR-018 draws the line: the working directory is a desk, not a shelf, and the road out of
	// it runs one way and only when the agent takes it. So this command reaches no server —
	// and if it ever did, this test would catch it, because there is one here to reach.
	server := armarius(t)
	workDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(workDir, "build.zip"), []byte("PK"), 0o600); err != nil {
		t.Fatalf("writing the agent's file: %v", err)
	}

	env := server.env()
	env.WorkDir = workDir
	if code, _, errs := run(t, env, "workdir", "changes"); code != ExitOK {
		t.Fatalf("exit %d (%s)", code, errs)
	}
	if server.method != "" {
		t.Fatalf("looking at this machine's own disk called out to %s %s", server.method, server.path)
	}
}

func TestARunWithNoWorkingDirectorySaysSoRatherThanAnsweringAboutSomewhereElse(t *testing.T) {
	// A run that was given no directory must not quietly answer about wherever this process
	// happens to be standing — which, for an agent that has moved into a repository it cloned,
	// would be a confident answer to a different question.
	code, _, errs := run(t, Environment{RunID: "run-1", TaskID: "task-1"}, "workdir", "changes")
	if code != ExitUsage {
		t.Fatalf("exit %d, wanted a usage refusal (%d)", code, ExitUsage)
	}
	if !strings.Contains(errs, "working directory") {
		t.Fatalf("the refusal does not say what is missing: %q", errs)
	}
}

func TestTheDiskQuestionBelongsToEveryRunWhateverItIsAbout(t *testing.T) {
	// GroupAny, and deliberately: a Leader's run and the team-building interview both work in a
	// directory, and neither is about a task. Scope is decided by what a run may *reach*
	// (FR-013d), and this reaches nothing.
	for _, env := range []Environment{
		{RunID: "run-1", TaskID: "task-1"},
		{RunID: "run-1", ProjectID: "project-1"},
		{RunID: "run-1"},
	} {
		if _, found := Find(Commands(env), "workdir changes"); !found {
			t.Fatalf("a run about %+v cannot ask what is on its own disk", env)
		}
	}
}
