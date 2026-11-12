package execenv

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// threadFile is where one task's conversation handle is kept, inside that task's own working
// directory.
//
// **Beside the work, not beside the CLI's own store**, and FR-010a is the reason. The session
// boundary is the working-directory boundary — most CLIs key their session state on the
// directory it was opened in — so keeping the handle there makes that boundary one fact instead
// of two ids that happen to match. It also means the handle is reclaimed by exactly the rules
// that reclaim the work it is about, with nothing new for the sweep to learn (FR-021).
//
// Under `.armarius` because that subtree is already this daemon's own: a run's home is built in
// it. Nothing a CLI lists ever sees this file, which matters — the alternative was to put it in
// the store a CLI reads, where a stray entry is a project the agent thinks it has.
const threadFile = ".armarius/thread.json"

// threadsDir holds one note per agent, for a working directory more than one agent works in.
//
// A task's directory is shared on purpose — the tester opens the files the builder wrote — but
// a conversation is not something to share. Keyed on the directory alone, the second agent woken
// on a task carried on the first one's session: it read the other's reasoning as its own past,
// answered under two names, and the model changing between turns threw the prompt cache away
// each time (measured 2026-11-12: three agents, one session, on both tasks of a project).
// FR-050 already counts by the pair *(agent, task)*; this is the same pair, kept on disk.
const threadsDir = ".armarius/threads"

// threadPath is where the note for one agent's conversation in one working directory lives.
//
// No agent named is the note this daemon wrote before it was told whose run it was holding — a
// server that has not learned to say. That file is still read and written for such a run, so an
// old server keeps what it had; a run that does name its agent never reads it, because what is
// in it may be somebody else's conversation.
func threadPath(workDir, agent string) (string, error) {
	if workDir == "" {
		return "", fmt.Errorf("a thread needs a working directory")
	}
	if agent == "" {
		return filepath.Join(workDir, filepath.FromSlash(threadFile)), nil
	}
	// One segment and nothing else: the name came off the wire, and a name that could climb is
	// a name that could put this file anywhere on the machine.
	if agent == "." || agent == ".." || strings.ContainsAny(agent, `/\`) || filepath.Base(agent) != agent {
		return "", fmt.Errorf("agent %q cannot name a thread", agent)
	}
	return filepath.Join(workDir, filepath.FromSlash(threadsDir), agent+".json"), nil
}

// Thread is what this machine remembers of one agent's conversation about one task, so that the
// next wake of that agent on that task carries it on rather than starting again (FR-023,
// FR-023a).
//
// The handle is opaque and it is the CLI's, not ours: `--resume <this>` for one family,
// `session/load` for the other. Nothing here reads into it.
type Thread struct {
	// Handle is what the CLI called the conversation the last time it ran.
	Handle string `json:"handle"`
	// Workplace is the workplace this conversation was opened at. Kept so a machine that was
	// rebuilt and registered again does not carry on a thread that belonged to the old one
	// (FR-026) — the ids differ, and that difference is the only evidence available.
	Workplace string `json:"workplace"`
	// OpenedAt is when the conversation began; LastUsedAt when it was last carried on. Two
	// times rather than one because the keeping in FR-027 counts idleness, and a thread worked
	// on daily for a month is not an old thread.
	OpenedAt   time.Time `json:"opened_at"`
	LastUsedAt time.Time `json:"last_used_at"`
}

// Verdict is what may be done with what was remembered.
//
// Codes, not sentences: whoever has to tell the agent builds the sentence in the one language
// an agent is written to (Constitution VII), and whoever writes it to the run's log keeps the
// code and its parts instead (FR-084a).
type Verdict string

const (
	// ThreadUsable means carry it on.
	ThreadUsable Verdict = "usable"
	// ThreadNone means nothing was remembered. The ordinary first run on a task, and **not** a
	// restart — there is nothing to have restarted from, so nobody is told anything (FR-025).
	ThreadNone Verdict = "none"
	// ThreadExpired means remembered, but past its keeping (FR-027).
	ThreadExpired Verdict = "session_expired"
	// ThreadUnreadable means something is there and it is not a thread this daemon wrote.
	ThreadUnreadable Verdict = "session_unreadable"
)

// RecallThread answers what this agent may carry on in this working directory, and why not when
// not. `agent` is whose run this is; empty only for a server that does not say (see threadPath).
//
// **The keeping is enforced here and not only by the sweep**, and that is what this call is
// for. The sweep runs on a clock of its own — hours apart, and not at all while the machine is
// off — so a wake can perfectly well land on a session a day past its keeping that no sweep has
// reached yet. A handle handed to a CLI whose store was swept underneath it is the worst of the
// two answers: the CLI either refuses to start or opens a new conversation and says nothing,
// and the run's record shows a thread that was carried on when it was not (FR-027, FR-025).
//
// A missing file is not an error and not a failure. It is the first run on this task.
func RecallThread(workDir, agent string, now time.Time, keep time.Duration) (Thread, Verdict, error) {
	path, err := threadPath(workDir, agent)
	if err != nil {
		return Thread{}, ThreadNone, fmt.Errorf("recalling a thread: %w", err)
	}
	if keep <= 0 {
		keep = DefaultSessionRetention
	}

	// #nosec G304 -- the path is this daemon's own constant under a directory this daemon made;
	// the caller is the run flow, and the only part of it that came off the wire is the task id,
	// which WorkDir already refused to let name anything but a single segment.
	raw, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Thread{}, ThreadNone, nil
		}
		return Thread{}, ThreadUnreadable, nil
	}

	var thread Thread
	if err := json.Unmarshal(raw, &thread); err != nil || thread.Handle == "" {
		// Not an error travelling up: there is exactly one thing to do about a note this
		// daemon cannot read, and it is the same thing it does about a note that is missing —
		// open a new conversation. The difference is that this one is worth telling the agent
		// about, which is why it is a verdict of its own and not silence.
		return Thread{}, ThreadUnreadable, nil
	}
	if now.Sub(thread.LastUsedAt) >= keep {
		return thread, ThreadExpired, nil
	}
	return thread, ThreadUsable, nil
}

// RememberThread writes down the conversation this run leaves behind, for the next wake of the
// same agent on the same task to pick up (FR-023, FR-023a).
//
// Called with what the CLI itself said it called the conversation. A run that produced no handle
// — a CLI that cannot resume, or one that failed before it opened anything — leaves what was
// already remembered alone: overwriting it with nothing would throw away a thread the *next*
// run could still have carried on, over a single bad turn.
func RememberThread(workDir, agent string, thread Thread) error {
	path, err := threadPath(workDir, agent)
	if err != nil {
		return fmt.Errorf("remembering a thread: %w", err)
	}
	if thread.Handle == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("making room for the thread of %s: %w", workDir, err)
	}
	body, err := json.Marshal(thread)
	if err != nil {
		return fmt.Errorf("writing down the thread of %s: %w", workDir, err)
	}
	// Written whole and moved into place. A note half-written is a note that reads as
	// unreadable on the next wake, which costs a conversation that was perfectly good.
	tmp := path + ".new"
	if err := os.WriteFile(tmp, body, 0o600); err != nil {
		return fmt.Errorf("writing down the thread of %s: %w", workDir, err)
	}
	if err := os.Rename(tmp, path); err != nil {
		return fmt.Errorf("putting the thread of %s in place: %w", workDir, err)
	}
	return nil
}

// ForgetThread drops what was remembered about a task's conversation.
//
// Called when a handle was offered and refused: the thread it names is gone on the CLI's side,
// so keeping it here only guarantees that the next wake offers the same dead handle and fails
// the same way. A run that then fails for some other reason writes nothing new, which is exactly
// the case this covers — the note has to be taken away rather than merely overwritten later.
//
// A note that is not there is not a failure. It is the state this call is trying to reach.
func ForgetThread(workDir, agent string) error {
	path, err := threadPath(workDir, agent)
	if err != nil {
		return fmt.Errorf("forgetting a thread: %w", err)
	}
	err = os.Remove(path)
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("forgetting the thread of %s: %w", workDir, err)
	}
	return nil
}
