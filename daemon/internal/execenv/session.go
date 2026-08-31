package execenv

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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

// Thread is what this machine remembers of one task's conversation, so that the next wake on the
// same task carries it on rather than starting again (FR-023).
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

// RecallThread answers what may be carried on in this working directory, and why not when not.
//
// **The keeping is enforced here and not only by the sweep**, and that is what this call is
// for. The sweep runs on a clock of its own — hours apart, and not at all while the machine is
// off — so a wake can perfectly well land on a session a day past its keeping that no sweep has
// reached yet. A handle handed to a CLI whose store was swept underneath it is the worst of the
// two answers: the CLI either refuses to start or opens a new conversation and says nothing,
// and the run's record shows a thread that was carried on when it was not (FR-027, FR-025).
//
// A missing file is not an error and not a failure. It is the first run on this task.
func RecallThread(workDir string, now time.Time, keep time.Duration) (Thread, Verdict, error) {
	if workDir == "" {
		return Thread{}, ThreadNone, fmt.Errorf("recalling a thread needs a working directory")
	}
	if keep <= 0 {
		keep = DefaultSessionRetention
	}

	// #nosec G304 -- the path is this daemon's own constant under a directory this daemon made;
	// the caller is the run flow, and the only part of it that came off the wire is the task id,
	// which WorkDir already refused to let name anything but a single segment.
	raw, err := os.ReadFile(filepath.Join(workDir, filepath.FromSlash(threadFile)))
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

// RememberThread writes down the conversation this run leaves behind, for the next wake on the
// same task to pick up (FR-023).
//
// Called with what the CLI itself said it called the conversation. A run that produced no handle
// — a CLI that cannot resume, or one that failed before it opened anything — leaves what was
// already remembered alone: overwriting it with nothing would throw away a thread the *next*
// run could still have carried on, over a single bad turn.
func RememberThread(workDir string, thread Thread) error {
	if workDir == "" {
		return fmt.Errorf("remembering a thread needs a working directory")
	}
	if thread.Handle == "" {
		return nil
	}
	path := filepath.Join(workDir, filepath.FromSlash(threadFile))
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
func ForgetThread(workDir string) error {
	if workDir == "" {
		return fmt.Errorf("forgetting a thread needs a working directory")
	}
	err := os.Remove(filepath.Join(workDir, filepath.FromSlash(threadFile)))
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("forgetting the thread of %s: %w", workDir, err)
	}
	return nil
}
