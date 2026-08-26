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
// Tool results are deliberately absent from this list in content: a tool's full output must
// never leave the machine (FR-043a), and the summarised form — how big it was, what type, the
// opening bytes, how much was cut — is built by the layer that owns the threshold
// (specs/002-daemon-acp-runtime/tasks.md T095). What is emitted here says a tool finished and
// whether it failed, which is true, cheap, and impossible to leak through.
const (
	// EventAgentMessage is text the agent produced (FR-044).
	EventAgentMessage = "agent.message"
	// EventAgentThinking is the agent's reasoning, for the CLIs that expose any (FR-044).
	EventAgentThinking = "agent.thinking"
	// EventToolStarted names a tool the agent called, with its arguments in full (FR-043).
	EventToolStarted = "tool.started"
	// EventToolFinished says that call ended, and whether it ended badly.
	EventToolFinished = "tool.finished"
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
