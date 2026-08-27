package execenv

import (
	"fmt"
	"os"
	"path/filepath"
)

// contextFiles says which file each CLI reads its brief out of without being asked to.
//
// This is the whole of Multica's trick and the reason the daemon writes a file instead of
// sending a message: **do not teach the agent a new way to be told things**. Every one of these
// CLIs already opens a file of its own accord at the start of a session, so putting the brief
// there means the agent needs to know nothing about Armarius to receive it — no flag, no
// protocol, no first turn spent explaining itself.
//
// Gemini CLI is deliberately absent. Which file it reads is unverified, and a guess here would
// be a file written where nothing looks (FR-039a, task T013).
var contextFiles = map[string]string{
	"claude_code": "CLAUDE.md",
	"codex":       "AGENTS.md",
}

// WriteContextFile puts the server's message where cli will find it on its own (FR-011a).
//
// The daemon composes none of this. The message is built on the server, out of the agent's own
// instructions and the project's context, because those are the rules that live there and
// cannot be checked out here (Constitution V, Constitution VII). What this function decides is
// only *which file*, and that is a fact about the CLI, not about the work.
//
// Refuses an empty message rather than writing an empty file. The two are not the same thing to
// whoever reads it next: an empty context file reads exactly like a correct one, so an agent
// handed one starts work believing it has been told everything there is to tell.
//
// Returns the path written.
func WriteContextFile(cli, workDir, message string) (string, error) {
	name, ok := contextFiles[cli]
	if !ok {
		return "", fmt.Errorf("no context file is declared for %q", cli)
	}
	if workDir == "" {
		return "", fmt.Errorf("writing the brief for %s needs a working directory", cli)
	}
	if message == "" {
		return "", fmt.Errorf("refusing to write an empty brief for %s", cli)
	}

	path := filepath.Join(workDir, name)
	if err := os.MkdirAll(workDir, 0o700); err != nil {
		return "", fmt.Errorf("creating the working directory for %s: %w", cli, err)
	}
	// Taken away before it is written, never opened for truncation. Two things fall out of
	// that: the file is this run's message and only this run's, even though the working
	// directory is shared by every run of the same task (FR-010); and whatever was there
	// before cannot redirect the write, because a link is removed rather than followed.
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return "", fmt.Errorf("clearing the previous brief for %s: %w", cli, err)
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600) //nolint:gosec // the path is this table's, joined onto a directory this process made
	if err != nil {
		return "", fmt.Errorf("creating the brief for %s: %w", cli, err)
	}
	if _, err := f.WriteString(message); err != nil {
		_ = f.Close()
		return "", fmt.Errorf("writing the brief for %s: %w", cli, err)
	}
	// Closed here rather than deferred, and its error is the caller's. A write that only fails
	// on close — a disk noticing it is full at the last moment — would otherwise be reported as
	// a brief written perfectly, and the agent would begin on half of its instructions with
	// nothing anywhere saying so.
	if err := f.Close(); err != nil {
		return "", fmt.Errorf("finishing the brief for %s: %w", cli, err)
	}
	return path, nil
}
