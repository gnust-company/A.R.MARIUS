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

import (
	"context"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

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
	// Restart says this turn begins a new conversation where the last one was meant to be
	// carried on, and why (FR-025, FR-026, FR-027). Nil is the ordinary case: either the thread
	// was picked up, or this is the first turn on the task and there was nothing to pick up.
	//
	// Not folded into Message, on purpose. The message is the server's — assembled there,
	// recorded there before it was sent, and nothing here may compose any part of it (FR-011a).
	// This is one sentence from the machine about the machine, and it travels beside the
	// message so that the agent reads both with neither rewritten.
	Restart *Restart
	// ToolConfig is the file this run's callback tools were declared in, for the CLIs that read
	// one, and ToolServers is that same declaration for the family that carries it inline in its
	// handshake (FR-013a).
	//
	// Two fields for one declaration, and they cannot drift: both come out of a single call to
	// execenv.PlaceTools, which is where the declaration is made. What differs is only how each
	// family is able to receive it — a file named on a command line, or an argument in a
	// handshake — and a CLI that can receive neither still has the command face, which is why
	// both being empty is a run that works rather than a run without tools.
	ToolConfig  string
	ToolServers []execenv.ToolServer
	// Options is what a person set on this agent, by the **server's** name for each setting
	// — `model`, `thinking_level`, and whatever a tool adds to that (FR-007k).
	//
	// Turning those names into flags happens per CLI, in the tables below, and that is the
	// point of them arriving unconverted: the side that knows a setting is called `--effort`
	// on one tool and something else on the next is the side that already knows how to start
	// each tool. A setting this CLI has no flag for is dropped, not guessed at — the person
	// chose it against what the workplace offered, and if that no longer matches the binary
	// installed here, refusing to start would be a worse answer than running on the default.
	Options map[string]string
	// Secrets are the values this run holds that must never leave the machine inside anything
	// it says — its own token and this machine's (FR-048, FR-048a). Passed in rather than read
	// back out of Env, because the guarantee is *these exact strings*, and a list rebuilt by
	// guessing which variables looked sensitive would be a pattern wearing a guarantee's name.
	Secrets []string
	// ResultLimit is how many bytes of a tool result may travel. Zero takes DefaultResultLimit,
	// which is what an ordinary run wants; the field exists because FR-043a says the threshold
	// is settable, and a threshold nobody can reach is not one.
	ResultLimit int
}

// Event is one thing that happened while the agent worked.
//
// Type is a code, never a sentence: whatever reads it later builds the sentence in the reader's
// own language (Constitution VI, Constitution VII).
type Event struct {
	Type    string
	Payload map[string]any

	// What follows is about the record rather than about the thing that happened, which is why
	// it sits beside the payload instead of inside it: the store keeps these in columns of their
	// own so a reader can ask *show me what was cut* without opening every payload, and so a
	// screen can say *something is missing here, and here is why* rather than drawing a gap.
	//
	// Nothing sets these except the journal in events.go. A reader that fills them in by hand
	// is a reader claiming its output was masked or summarised when it was not.

	// Truncated says the payload carries an opening slice rather than the whole thing (FR-043b).
	Truncated bool
	// OriginalBytes is how big the thing was before any of that, so *cut* comes with *how much*.
	OriginalBytes int
	// OmissionReason is why something is missing: TruncatedByPolicy or NotExposedByCLI (FR-047).
	OmissionReason string
	// Redacted says a secret was masked out of this event before it left the machine (FR-048).
	Redacted bool
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
	// SessionRefused says the handle this turn was given would not load, so the conversation
	// began again. Reported rather than merely announced to the agent, because the machine has
	// to stop offering that handle: a run that then fails for some other reason leaves nothing
	// new to write down, and the next wake would pick the same dead handle straight back up
	// (FR-025, FR-027).
	SessionRefused bool
	// Usage is whatever the CLI said the turn cost, passed on as it was given. Not interpreted
	// here: every CLI counts in its own units, and averaging them into a shape of our own would
	// be inventing a number nobody measured.
	Usage map[string]any
	// Failure is which wall this turn hit, as one of the server's closed codes, when the CLI
	// said so plainly enough to be sure (FR-032a, FR-007c). Empty is the ordinary answer and
	// the safe one: the server retries an ending nobody classified, and asks a person about an
	// ending a machine was certain of. A guess here spends somebody's attention on a hiccup.
	Failure string
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
// Two halves, and both are needed. The registry has to declare what a run of this kind is set
// up from — the brief's file, the skills directory, the home and the variable pointing at it —
// and this package has to know how to start one. Neither implies the other: a row can be filled
// in for a CLI nobody has written an invocation for, and an invocation is useless against a row
// that cannot say where the brief goes.
//
// Not the same question as *is it installed* — that one is discovery's, and its answer is what
// the machine reports as a workplace (FR-002). This one is about what has been written here.
//
// The two families answer the second half from different places, and the asymmetry is real
// rather than untidy. A one-shot CLI needs an invocation written by hand for it, because every
// one of them has its own flags and its own way of printing what it did. An ACP CLI needs one
// flag and nothing else: the conversation after that is the protocol's, identical for every peer
// that speaks it. So for that family the whole of "can this be started" is the row.
//
// It matters because of what a machine does with the answer. Asking for work at a workplace
// this daemon cannot drive wins a run that fails during setup, and a run that fails during
// setup goes back on the shelf and is offered to the same machine again (FR-007, FR-056a) —
// forever, a slot at a time. Not asking leaves the task where it is, which is visibly stuck
// rather than invisibly churning.
func Supported(cli string) bool {
	return agentcli.Ready(cli) && startable(cli)
}

// startable says whether this package knows how to start a CLI of this kind, whichever family.
func startable(cli string) bool {
	if _, oneShot := oneShots[cli]; oneShot {
		return true
	}
	if _, acp := acpStart(cli); acp {
		return true
	}
	_, appServer := appServerStart(cli)
	return appServer
}
