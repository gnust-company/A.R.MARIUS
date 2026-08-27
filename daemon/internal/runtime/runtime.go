// Package runtime runs one agent CLI for one turn and turns what it does into events.
//
// There are two protocol families and exactly one contract over both (FR-035, FR-037). A CLI
// that runs once per turn and prints what happened, and a CLI that holds a JSON-RPC conversation
// over its own standard streams, are not alike in any respect except the one that matters here:
// they are handed a message and they produce a stream of things that happened. Everything above
// this package sees only that.
//
// The contract is deliberately narrow. Deciding *what to say* is the server's (FR-011a),
// deciding *where the agent works* is execenv's, and deciding *when to give up on it* is the
// watchdog's. What is left — start it, read it, say how it ended — is what lives here.
package runtime

import "context"

// Request is one turn of work, as far as running it is concerned.
type Request struct {
	// CLI is the kind of agent CLI, spelled the way the server spells it in `workplaces.cli_kind`.
	CLI string
	// Binary is the path discovery found it at. Passed in rather than looked up again, so the
	// CLI that runs is the one this machine registered a workplace for.
	Binary string
	// WorkDir is the task's directory (FR-010). The CLI is started in it, and every relative
	// path the agent uses is relative to it.
	WorkDir string
	// Env is the whole environment the CLI is started with, as built by execenv.Environ. Whole,
	// rather than a few additions: what a run may see is a decision with a rule behind it
	// (FR-014c), and a rule enforced in one place is a rule.
	Env []string
	// Message is what the agent is told this turn — built by the server, in English, recorded by
	// the server before it was ever sent (FR-011a, FR-012a). Nothing here composes any part of
	// it, and nothing here may abbreviate it.
	Message string
	// Session is the handle of the conversation to carry on, empty to start a new one (FR-023).
	// A CLI that cannot resume ignores it and opens a new session, which is a supported outcome
	// rather than a failure (FR-039a).
	Session string
}

// Event is one thing that happened while the agent worked.
//
// Type is a code, never a sentence: whatever reads it later builds the sentence in the reader's
// own language (Constitution VI, Constitution VII).
type Event struct {
	Type    string
	Payload map[string]any
}

// The events both families produce.
//
// **These are the names the rest of the system already writes down.** A run's events are stored
// under their type and read back by the screen that replays the run (FR-016, FR-046), and that
// reader was here first. A second vocabulary for the same five facts would not be a naming
// preference — it would be runs through this road showing up blank on a screen that renders
// every other run perfectly, which is the kind of fault that looks like an empty task rather
// than like a bug. One name per fact, chosen from the side that has the readers.
//
// Tool results are deliberately absent from this list in content: a tool's full output must
// never leave the machine (FR-043a), and the summarised form — how big it was, what type, the
// opening bytes, how much was cut — is built by the layer that owns the threshold
// (specs/002-daemon-acp-runtime/tasks.md T095). What is emitted here says a tool finished and
// whether it failed, which is true, cheap, and impossible to leak through.
const (
	// EventAssistantMessage is text the agent produced (FR-044).
	EventAssistantMessage = "assistant.message"
	// EventAssistantThinking is the agent's reasoning, for the CLIs that expose any (FR-044).
	EventAssistantThinking = "assistant.thinking"
	// EventToolStarted names a tool the agent called, with its arguments in full (FR-043).
	EventToolStarted = "tool.started"
	// EventToolCompleted says that call ended, and whether it ended badly.
	EventToolCompleted = "tool.completed"
	// EventRunError is anything that went wrong (FR-044).
	EventRunError = "run.error"
)

// Outcome is how one turn ended.
type Outcome struct {
	// Session is the handle to hand back next time. Empty means this CLI gave none, which is
	// what starting a fresh conversation next time will look like (FR-025).
	Session string
	// Usage is whatever the CLI said the turn cost, passed on as it was given. Not interpreted
	// here: every CLI counts in its own units, and averaging them into a shape of our own would
	// be inventing a number nobody measured.
	Usage map[string]any
}

// Emit is handed each event as it happens, in the order it happened.
//
// Called from the goroutine reading the CLI, so it must not block for long: a slow sink is a
// stalled agent. Sending events on to the server is somebody else's problem, and it is one
// with a queue in it.
type Emit func(Event)

// Runtime runs one turn.
//
// Returning an error means the turn did not finish. It does **not** mean the agent was wrong or
// that the work failed — an agent that finishes its turn and reports it could not do the job
// returns no error at all, because running it worked exactly as intended.
type Runtime interface {
	Run(ctx context.Context, req Request, emit Emit) (Outcome, error)
}

// Supported answers whether this daemon can actually drive a CLI of this kind.
//
// Not the same question as *is it installed* — that one is discovery's, and its answer is what
// the machine reports as a workplace (FR-002). This one is about what has been written here,
// and today the honest answer for Gemini CLI is no: its invocation may not be written before it
// has been probed (FR-039a, task T013).
//
// It matters because of what a machine does with the answer. Asking for work at a workplace
// this daemon cannot drive wins a run that fails during setup, and a run that fails during
// setup goes back on the shelf and is offered to the same machine again (FR-007, FR-056a) —
// forever, a slot at a time. Not asking leaves the task where it is, which is visibly stuck
// rather than invisibly churning.
func Supported(cli string) bool {
	if _, oneShot := oneShots[cli]; oneShot {
		return true
	}
	_, acp := acpFlags[cli]
	return acp
}
