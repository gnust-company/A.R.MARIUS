package execenv

import (
	"fmt"
	"os"
	"path/filepath"
)

// WorkDir puts the working directory for one task in place and answers where it is (FR-010).
//
// **Named after the task, not the run.** Every run of the same task comes back to the same
// directory, because a session is tied to the directory it was opened in: most agent CLIs key
// their session state on the working directory, so resuming one somewhere else either finds no
// session at all or finds one whose every remembered path now points at nothing (FR-010a). Two
// different tasks get two different directories even when the same agent works on both
// (FR-010b) — that is what the name being the task id buys.
//
// **Nothing is emptied here.** The directory is the task's, and what a previous run left in it
// is the task's too: notes, downloads, a half-finished file the next run is meant to carry on
// from. The things that must not survive a run — the brief and the skills — are removed and
// rewritten by the code that owns them, each at the moment it writes.
//
// It starts blank in the sense FR-041 means: Armarius puts no source code in it and manages no
// branch. An agent that needs a repository clones it with its own credentials, which is also the
// only way it could — the credentials are the agent's, not ours.
func WorkDir(root, taskID string) (string, error) {
	return dirUnder(root, taskID, "task")
}

// TurnDir is the working directory for a run that is about **no task** — the team-building
// interview (FR-040c).
//
// Named after the run, and that is the whole difference from WorkDir. A task's directory is
// shared by every run of that task on purpose, because a session is tied to the directory it was
// opened in and the next run has to find it (FR-010a). A turn about no task has nothing to find:
// what it is carrying on from is a conversation the *server* holds, replayed into the message of
// every turn, so a directory kept for it would be kept for nobody. The caller takes it away when
// the turn ends; the disk sweep is the backstop for a daemon that died before it could.
func TurnDir(root, runID string) (string, error) {
	return dirUnder(root, runID, "run")
}

func dirUnder(root, name, what string) (string, error) {
	if root == "" {
		return "", fmt.Errorf("a working directory needs a root to sit under")
	}
	// The id arrives from the server, over the wire, and is about to become a path component on
	// somebody else's machine. Anything that could climb out of the root, or name the root
	// itself, is refused rather than cleaned: cleaning answers *where would this land*, which is
	// only useful once compared, and the comparison is the half that gets forgotten.
	if !safeSegment(name) {
		return "", fmt.Errorf("%s %q cannot name a working directory", what, name)
	}

	path := filepath.Join(root, name)
	switch info, err := os.Lstat(path); {
	case err == nil && info.Mode()&os.ModeSymlink != 0:
		// A link here would send the whole run — the brief, the skills, everything the agent
		// writes — wherever the link points, which on this machine could be the operator's own
		// home. It is also not something a previous run of ours could have left: we only ever
		// make a real directory, so a link means something else made it.
		return "", fmt.Errorf("refusing to work in %s: it is a link, not a directory", path)
	case err == nil && !info.IsDir():
		return "", fmt.Errorf("refusing to work in %s: it is not a directory", path)
	case err != nil && !os.IsNotExist(err):
		return "", fmt.Errorf("inspecting %s: %w", path, err)
	}

	if err := os.MkdirAll(path, 0o700); err != nil {
		return "", fmt.Errorf("creating the working directory for %s %s: %w", what, name, err)
	}
	return path, nil
}

// RunHome is where the fake home for one run goes, inside that run's working directory.
//
// One home per run, and the run takes it away when it ends. Inside the working directory rather
// than beside it, so that a daemon killed mid-run leaves nothing stranded: the sweep already
// asks two questions about every task directory — is anyone holding it, has it been quiet long
// enough — and a home that lives inside one is answered by both without the sweep having to
// learn that homes exist (FR-021).
//
// What must outlive the run is not in here. Session state is a link out to the per-task store
// (see Build), so taking the home away leaves the conversation where the next run will look for
// it (FR-023).
func RunHome(workDir, runID string) (string, error) {
	if workDir == "" {
		return "", fmt.Errorf("a home needs a working directory to sit in")
	}
	if !safeSegment(runID) {
		return "", fmt.Errorf("run %q cannot name a home", runID)
	}
	return filepath.Join(workDir, ".armarius", "home", runID), nil
}
