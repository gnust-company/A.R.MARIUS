package execenv_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

func write(t *testing.T, path, body string) string {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatalf("making room for %s: %v", path, err)
	}
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("writing %s: %v", path, err)
	}
	return path
}

func listed(list execenv.ChangeList) map[string]bool {
	seen := map[string]bool{}
	for _, f := range list.Files {
		seen[f.Path] = true
	}
	return seen
}

func TestTheAgentSeesWhatItMadeAndNotWhatItWasHanded(t *testing.T) {
	// The whole of FR-020a in one case. The working directory starts empty, so everything in it
	// is either something the agent produced — which it may want to publish — or something this
	// daemon put there for it, which it certainly does not.
	workDir := t.TempDir()

	brief := write(t, filepath.Join(workDir, "CLAUDE.md"), "your brief")
	skills := filepath.Join(workDir, ".claude", "skills")
	write(t, filepath.Join(skills, "armarius", "SKILL.md"), "how to call back")
	tools, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI: "claude_code", WorkDir: workDir, Program: aCallbackProgram(t),
	})
	if err != nil {
		t.Fatalf("placing the callback program: %v", err)
	}
	if err := execenv.RecordPlaced(workDir, []string{brief, skills, tools.Dir, tools.ConfigFile}); err != nil {
		t.Fatalf("recording what was placed: %v", err)
	}

	write(t, filepath.Join(workDir, "report.md"), "what I found")
	write(t, filepath.Join(workDir, "out", "build.log"), "it compiled")

	list, err := execenv.Changes(workDir, 0)
	if err != nil {
		t.Fatalf("listing changes: %v", err)
	}
	seen := listed(list)

	for _, mine := range []string{"report.md", "out/build.log"} {
		if !seen[mine] {
			t.Fatalf("the agent is not shown %s, which it wrote: %v", mine, seen)
		}
	}
	for _, ours := range []string{
		"CLAUDE.md",
		".claude/skills/armarius/SKILL.md",
		".armarius/bin/armarius",
		".armarius/mcp.json",
		".armarius/placed.json",
	} {
		if seen[ours] {
			t.Fatalf("the agent is shown %s, which this daemon put there: %v", ours, seen)
		}
	}
	if list.Total != 2 {
		t.Fatalf("counted %d files, expected only the agent's two: %v", list.Total, seen)
	}
}

func TestWhatIsUnderOurOwnDirectoryIsNeverTheAgentsWork(t *testing.T) {
	// `.armarius` holds the run homes as well as the program and the record, and a run home is
	// full of links out to the operator's own installation. It is skipped whether or not
	// anything was written down — the record can be missing, and this still cannot leak.
	workDir := t.TempDir()
	write(t, filepath.Join(workDir, ".armarius", "home", "run-1", ".claude.json"), "{}")
	write(t, filepath.Join(workDir, "note.txt"), "mine")

	list, err := execenv.Changes(workDir, 0)
	if err != nil {
		t.Fatalf("listing changes: %v", err)
	}
	if seen := listed(list); !seen["note.txt"] || list.Total != 1 {
		t.Fatalf("expected only the agent's own file, got %v", seen)
	}
}

func TestALinkIsCountedAndNeverFollowed(t *testing.T) {
	// A run's home links out to stores that are not in here, and an agent may make links of its
	// own. Following one would walk out of the working directory and report somebody else's
	// files as this agent's work.
	workDir := t.TempDir()
	outside := t.TempDir()
	write(t, filepath.Join(outside, "somebody-elses.txt"), "not yours")
	if err := os.Symlink(outside, filepath.Join(workDir, "elsewhere")); err != nil {
		t.Fatalf("making a link: %v", err)
	}
	write(t, filepath.Join(workDir, "mine.txt"), "mine")

	list, err := execenv.Changes(workDir, 0)
	if err != nil {
		t.Fatalf("listing changes: %v", err)
	}
	seen := listed(list)
	if seen["elsewhere/somebody-elses.txt"] {
		t.Fatalf("the walk followed a link out of the working directory: %v", seen)
	}
	if !seen["mine.txt"] {
		t.Fatalf("the agent's own file went missing: %v", seen)
	}
}

func TestTheNewestWorkComesFirstAndTheCountStillTellsTheTruth(t *testing.T) {
	// What an agent is about to publish is almost always what it has just finished writing, so
	// the order is not cosmetic. And a limit cuts the list without cutting the count: an agent
	// shown three of forty files must be able to tell that it has forty.
	workDir := t.TempDir()
	base := time.Now().Add(-time.Hour)
	for i, name := range []string{"first.txt", "second.txt", "third.txt", "fourth.txt"} {
		path := write(t, filepath.Join(workDir, name), name)
		when := base.Add(time.Duration(i) * time.Minute)
		if err := os.Chtimes(path, when, when); err != nil {
			t.Fatalf("setting the time on %s: %v", name, err)
		}
	}

	list, err := execenv.Changes(workDir, 2)
	if err != nil {
		t.Fatalf("listing changes: %v", err)
	}
	if list.Total != 4 {
		t.Fatalf("the count says %d, but four files were written", list.Total)
	}
	if len(list.Files) != 2 {
		t.Fatalf("asked for two, was given %d", len(list.Files))
	}
	if list.Files[0].Path != "fourth.txt" || list.Files[1].Path != "third.txt" {
		t.Fatalf("the most recent work is not first: %v", listed(list))
	}
}

func TestAnEmptyWorkingDirectoryIsAnAnswerNotAFailure(t *testing.T) {
	list, err := execenv.Changes(t.TempDir(), 0)
	if err != nil {
		t.Fatalf("an agent that has made nothing yet was given an error: %v", err)
	}
	if list.Total != 0 || len(list.Files) != 0 {
		t.Fatalf("found something in an empty directory: %+v", list)
	}
}
