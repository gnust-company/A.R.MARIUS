package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
)

// maxOutputLine bounds one line of a CLI's stream.
//
// One line can carry a whole tool result, so the bound is generous — and it is still a bound.
// The daemon reads a stream produced on the operator's own machine by a program it started, but
// a program that has gone wrong can print without end, and a reader that grows to meet it is the
// one way this daemon could be made to exhaust the machine's memory.
const maxOutputLine = 8 << 20

// maxStderrTail is how much of a CLI's complaints are kept for the error message. The tail
// rather than the head: a program that fails says why last.
const maxStderrTail = 8 << 10

// invocation is how one CLI of the one-shot family is asked to take a turn.
type invocation struct {
	// flags says how this CLI spells the settings a person may pick (FR-007k). Keyed by the
	// server's name for the setting; a key absent here is a setting this CLI does not take.
	flags map[string]string
	// args builds the command line, without the message.
	args func(req Request) []string
	// prompt is the flag the message is handed over with, for a CLI that is driven that way; empty
	// means standard input. Standard input where the CLI allows it — then the message's length is
	// not the operating system's business and it does not sit in the process table for everyone
	// on a shared machine to read — and a flag where the CLI is driven by one.
	prompt string
	// reader builds what reads one turn's output. A fresh one per turn, because a CLI that
	// streams its text in fragments has to be read with memory of the fragments before.
	reader func() lineReader
}

// lineReader turns a CLI's output into events, one line at a time, and picks up whatever the
// outcome needs. A line it does not recognise produces nothing: these streams carry banners,
// progress and warnings alongside the events, and guessing at an unknown shape would put
// invented facts in a record that is meant to be evidence.
type lineReader interface {
	read(line []byte, journal *Journal, out *Outcome)
	// finish is told the output has ended, so whatever was held back is said now rather than
	// lost with the process.
	finish(journal *Journal, out *Outcome)
}

// eachLine is a reader that needs no memory between lines.
type eachLine func(line []byte, journal *Journal, out *Outcome)

func (f eachLine) read(line []byte, journal *Journal, out *Outcome) { f(line, journal, out) }
func (eachLine) finish(*Journal, *Outcome)                          {}

// oneShots is every CLI this family knows how to run.
var oneShots = map[string]invocation{
	// Claude Code, measured on version 2.1.226 on 2026-08-26.
	//
	//   - `-p` is the non-interactive form, and with no prompt argument it reads the prompt from
	//     standard input.
	//   - `--output-format stream-json` is the only form that carries tool calls with their
	//     arguments; it **requires** `--verbose` in print mode, which the CLI says outright:
	//     "When using --print, --output-format=stream-json requires --verbose".
	//   - `--resume <id>` carries on a conversation by session id (FR-023).
	//   - `--mcp-config <file>` loads this run's own callback tools (FR-013a). Named on the
	//     command line rather than left in the working directory for the CLI to find, because
	//     the file it finds by itself is the project-scoped one and that has to be approved by
	//     somebody sitting there — and nobody is. `--strict-mcp-config` is deliberately **not**
	//     passed: it would also switch off whatever tools the operator configured for their own
	//     installation, which is theirs to decide and is not what FR-013a asks for. What FR-013a
	//     asks for is that *ours* be declared per run and never written into their configuration.
	//   - `--permission-mode bypassPermissions` because nobody is sitting here to grant anything,
	//     and FR-013b says an unattended run is allowed what it asks for. Claude Code in print
	//     mode does not ask: whatever its settings do not already allow is refused in silence, so
	//     the only way to say yes is to start it in the mode that does not need asking. This
	//     replaced an allow-list naming our own tools alone, which left every other step — a
	//     file written, a command run — to whatever the operator happened to have allowed.
	//   - `--disallowed-tools AskUserQuestion` because that tool waits for somebody to answer a
	//     dialog, and with no dialog it comes back empty and the agent carries on guessing. A
	//     question for the person goes through Armarius instead, which ends the turn and wakes
	//     the agent again with the answer (FR-013b).
	"claude_code": {
		// Measured on 2.1.226, and measured **together with the probe that offers them**: the
		// values a person picks come out of `--effort (low, medium, high, xhigh, max)` and
		// `--model ... (e.g. 'fable', 'opus', or 'sonnet')`, which are the same two flags
		// named here. Reading the list from one place and spending it on another is how a
		// screen ends up offering a setting nothing applies.
		flags: map[string]string{"model": "--model", "thinking_level": "--effort"},
		args: func(req Request) []string {
			args := []string{
				"-p", "--output-format", "stream-json", "--verbose",
				"--permission-mode", "bypassPermissions",
				"--disallowed-tools", "AskUserQuestion",
			}
			if req.ToolConfig != "" {
				args = append(args, "--mcp-config", req.ToolConfig)
			}
			if req.Session != "" {
				args = append(args, "--resume", req.Session)
			}
			return args
		},
		reader: func() lineReader { return eachLine(readClaudeCode) },
	},

	// Gemini CLI, one process per turn (FR-039f). Read off the bundle `gemini 0.56.0` ships, not
	// run on the machine this was written on: nobody here has an account it will serve.
	//
	//   - `-p <message>`, the way Multica's daemon drove it before Gemini CLI was dropped there
	//     (`git show 76c58a4ee^:server/pkg/agent/gemini.go`), and the same way the rest of this
	//     command line is spelled. Standard input is left empty: the bundle would put whatever it
	//     finds there in front of `-p`, and a message said twice is not the message.
	//   - `--yolo` approves every tool call without asking (FR-013b). Its `ask_user` dialog needs
	//     no flag to switch off: the bundle drops that tool by itself whenever it runs without a
	//     terminal, which is the whole of what FR-013b asks for here.
	//   - `--output-format stream-json` prints one JSON object per line: `init`, `message`,
	//     `tool_use`, `tool_result`, `error`, `result`.
	//   - `--resume <id>` takes the session id the `init` line carried. An id it cannot find ends
	//     the process before anything is printed, which is the shape the retry in Run looks for.
	//
	// No tool declaration is passed: this mode has no flag naming a file of MCP servers for one
	// run, and the servers it would read from settings are started with every variable whose name
	// looks like a credential stripped out — this run's token among them. The command face does
	// not have that problem, because gemini's shell keeps the environment by default.
	//
	// No settings are spent either: the help text offers no model list to pick from, and a flag
	// with nothing to choose is a setting nobody can reach (choices_test.go holds the two tables
	// to that).
	"gemini": {
		prompt: "-p",
		args: func(req Request) []string {
			args := []string{"--yolo", "--output-format", "stream-json"}
			if req.Session != "" {
				args = append(args, "--resume", req.Session)
			}
			return args
		},
		reader: func() lineReader { return &geminiReader{} },
	},
}

// chosen renders what a person set on this agent into this CLI's own flags (FR-007k).
//
// Sorted, so the command line a run is started with is the same one twice for the same
// choices — a run that cannot be reproduced from its own record is a run nobody can debug.
//
// A setting with no flag here, or set to nothing, contributes nothing. Both are ordinary:
// FR-007k says an unset choice means the tool's own default, and a workplace whose CLI has
// since been replaced by one that takes fewer settings should still run.
// Applied by Run rather than from inside each `args` closure: a closure in the table cannot
// read the table it is being defined in, and threading the flag map through every one of them
// would put the same three lines in each CLI that ever gets added.
func chosen(req Request, flags map[string]string) []string {
	if len(req.Options) == 0 || len(flags) == 0 {
		return nil
	}
	keys := make([]string, 0, len(req.Options))
	for key := range req.Options {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	var args []string
	for _, key := range keys {
		flag, takes := flags[key]
		if !takes || req.Options[key] == "" {
			continue
		}
		args = append(args, flag, req.Options[key])
	}
	return args
}

// OneShot runs the CLIs that take one turn per process: hand them a message, read what they
// print, and they exit (FR-039).
//
// The turn is delivered on standard input and the account of it comes back on standard output,
// which is the whole of the family's protocol. There is no handshake, nothing to negotiate, and
// no way to say anything to the process once it is running — a turn is atomic here, and a run
// that has to be stopped is stopped by ending the process.
type OneShot struct{}

// Run takes one turn (FR-015: events are emitted as they arrive, not gathered up at the end).
func (OneShot) Run(ctx context.Context, req Request, emit Emit) (Outcome, error) {
	shape, known := oneShots[req.CLI]
	if !known {
		return Outcome{}, fmt.Errorf("%q is not a one-shot CLI this daemon knows how to run", req.CLI)
	}
	if req.Binary == "" {
		return Outcome{}, fmt.Errorf("running %s needs the path it was found at", req.CLI)
	}
	if req.WorkDir == "" {
		return Outcome{}, fmt.Errorf("running %s needs the task's working directory", req.CLI)
	}
	if req.Message == "" {
		// An agent started with nothing to do would still look like a working run from every
		// angle: a process appears, events arrive, it ends. Refusing is how that stays visible.
		return Outcome{}, fmt.Errorf("refusing to run %s with nothing to say to it", req.CLI)
	}
	// Everything this run says goes out through one gate: masked, and cut down to what may
	// travel (FR-043a, FR-048a). Built here rather than by the caller so that a runtime cannot
	// be wired up without it.
	journal := NewJournal(req, emit)

	// Said before anything else this turn produces, and in both places at once: the code goes
	// into the run's log, the English goes to the agent ahead of the brief (FR-025, SC-007).
	notice := tell(journal, req.Restart)

	out, err := takeTurn(ctx, req, shape, journal, notice)
	if !refusedTheHandle(ctx, req, journal, err) {
		return out, err
	}

	// The handle was the only thing this turn was told that could be wrong, and the agent never
	// said a word. **Measured, not assumed** (Claude Code 2.1.226): `--resume` with an id it
	// cannot find prints `No conversation found with session ID: …`, exits 1, reports
	// `num_turns: 0` — and echoes the id it was given back as the session, so the handle that
	// just failed is the one that would have been written down for the next wake to try again.
	//
	// This family has no way to be told mid-turn that a load failed, which is how the ACP side
	// learns it. So it is learnt from the outside instead: given a handle, ended badly, nothing
	// heard from the agent. A second start costs one failed process; not doing it costs the run,
	// and then every run after it until the thread ages out — which is exactly the outcome
	// FR-025 exists to prevent (SC-007).
	out.SessionRefused = true
	fresh := req
	fresh.Session = ""
	fresh.Message = req.messageWithoutSession()
	again, err := takeTurn(ctx, fresh, shape, journal,
		ahead(notice, tell(journal, &Restart{
			Code:   RestartRefused,
			Params: map[string]any{"session": req.Session},
		})))
	again.SessionRefused = true
	return again, err
}

// refusedTheHandle says whether a failed turn failed *because of the handle it was given*, as
// closely as this family can be asked.
//
// Three conditions, and each rules out a way of being wrong. **A handle was given**, so there is
// something to blame. **Nothing was heard from the agent**, so nothing was done and nothing will
// be repeated by starting again — an error is not the agent working. And **nothing outside ended
// the run**: a daemon shutting down or a watchdog cutting a silent agent looks like a failure
// from in here, and starting a second process on the way out is the one thing that must not
// happen.
func refusedTheHandle(ctx context.Context, req Request, journal *Journal, err error) bool {
	return err != nil && req.Session != "" && !journal.HeardTheAgent() && ctx.Err() == nil
}

// takeTurn starts the CLI once and reads it to the end.
func takeTurn(
	ctx context.Context, req Request, shape invocation, journal *Journal, notice string,
) (Outcome, error) {
	said := ahead(notice, req.Message)
	args := append(shape.args(req), chosen(req, shape.flags)...)
	if shape.prompt != "" {
		args = append([]string{shape.prompt, said}, args...)
	}
	cmd := newProcess(ctx, req, args)
	if shape.prompt == "" {
		cmd.Stdin = strings.NewReader(said)
	}

	streams, err := plumb(cmd)
	if err != nil {
		return Outcome{}, fmt.Errorf("listening to %s: %w", req.CLI, err)
	}

	if err := cmd.Start(); err != nil {
		streams.takeAway()
		streams.handedOver()
		return Outcome{}, fmt.Errorf("starting %s: %w", req.CLI, err)
	}
	streams.handedOver()

	var (
		out        Outcome
		reading    sync.WaitGroup
		complaints tail
		overflow   atomic.Bool
		reader     = shape.reader()
	)
	reading.Add(2)
	go func() {
		defer reading.Done()
		lines := bufio.NewScanner(streams.out)
		lines.Buffer(make([]byte, 0, 64<<10), maxOutputLine)
		for lines.Scan() {
			line := lines.Bytes()
			if len(line) == 0 || line[0] != '{' {
				continue
			}
			reader.read(line, journal, &out)
		}
		reader.finish(journal, &out)
		if lines.Err() != nil && !errors.Is(lines.Err(), os.ErrClosed) {
			// The stream is unreadable from here on, but the process is still running and is
			// still doing the work. Say so and let it finish: killing a healthy agent because
			// this daemon lost the commentary would turn a gap in the record into lost work.
			overflow.Store(true)
			journal.Fail("output_unreadable", map[string]any{"cli": req.CLI})
		}
	}()
	go func() {
		defer reading.Done()
		_, _ = io.Copy(&complaints, streams.errs)
	}()

	err = cmd.Wait()
	// The tree goes before the last of the output is waited for, and that order is the whole
	// point: something the agent left running holds these pipes open, so waiting first would
	// be waiting on exactly what has to be killed.
	reap(cmd)
	streams.drain(&reading)

	if err != nil {
		return out, fmt.Errorf("%s ended badly: %w%s", req.CLI, err, complaints.suffix())
	}
	if overflow.Load() {
		return out, fmt.Errorf("%s ran to the end, but this machine could not read all of what it said", req.CLI)
	}
	return out, nil
}

// claudeLine is one line of Claude Code's stream-json output.
//
// Message is left raw because its shape is not constant: an assistant turn carries a list of
// content blocks, and other turns carry a bare string. Decoding it separately means the string
// case costs one ignored line instead of throwing away everything else on it.
type claudeLine struct {
	Type      string          `json:"type"`
	Subtype   string          `json:"subtype"`
	SessionID string          `json:"session_id"`
	IsError   bool            `json:"is_error"`
	Usage     map[string]any  `json:"usage"`
	Message   json.RawMessage `json:"message"`
}

type claudeBlocks struct {
	Content []struct {
		Type      string         `json:"type"`
		Text      string         `json:"text"`
		Thinking  string         `json:"thinking"`
		Name      string         `json:"name"`
		ID        string         `json:"id"`
		Input     map[string]any `json:"input"`
		ToolUseID string         `json:"tool_use_id"`
		IsError   bool           `json:"is_error"`
		// Content is what a tool gave back, left raw because its shape is not constant: a
		// string for the simple case, a list of blocks when the tool returned more than text.
		// Raw also means it is never accidentally carried anywhere — it is read here, measured,
		// and dropped (FR-043a).
		Content json.RawMessage `json:"content"`
	} `json:"content"`
}

// resultOf reads what a tool returned out of whichever shape Claude Code sent it in.
//
// Absent is not empty. A CLI that says nothing about a result and a tool that returned nothing
// are two different facts, and the second value here is which one this was (FR-047).
func resultOf(raw json.RawMessage) Result {
	if len(raw) == 0 || string(raw) == "null" {
		return Result{}
	}
	var text string
	if json.Unmarshal(raw, &text) == nil {
		return Result{Exposed: true, Body: text}
	}
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if json.Unmarshal(raw, &blocks) != nil {
		// Some shape nobody here has measured. Saying so is honest; guessing at its fields
		// would put an invented number in a record meant to be evidence.
		return Result{}
	}
	var joined strings.Builder
	kind := ""
	for _, block := range blocks {
		if block.Text != "" {
			joined.WriteString(block.Text)
			continue
		}
		if block.Type != "" && block.Type != "text" {
			kind = block.Type
		}
	}
	return Result{Exposed: true, Body: joined.String(), Kind: kind}
}

// The ending this daemon can currently name: the provider has nothing left to give on the
// login a workplace works under (FR-032, FR-007c).
//
// The server holds the whole closed list — an exhausted quota, a credential that was refused,
// a workplace set up for work it cannot do — and this side may only use words already on it.
// Only the first is spelled here, because only the first has been measured; a constant for an
// ending nobody has watched is an invitation to guess at it.
const failureQuotaExhausted = "quota_exhausted"

// wall is one ending a CLI announces in words, and the code that ending is.
type wall struct {
	// saying is a fragment this daemon has **watched** a CLI print. Matched as a substring
	// rather than a pattern: the sentence around it is one vendor's prose on one day, and the
	// part worth keying on is the part that was seen.
	saying  string
	failure string
}

// walls is what each CLI family has been observed saying, family by family.
//
// **A family with nothing measured has no entry, and that is the design rather than a gap**
// (FR-039, T124a). A verdict here stops a run being retried and puts it in front of a person,
// so a line guessed from documentation would write a fabricated cause into the record that is
// kept as evidence. Reading nothing costs a retry; reading wrong costs the truth.
var walls = map[string][]wall{
	"claude_code": {
		// Measured 2026-09-04 on Claude Code 2.1.252, live, while running the quickstart
		// end to end (T129): thirty-one runs on an account past its allowance each printed
		// exactly one assistant line — `You've hit your session limit · resets 5:50pm
		// (Asia/Ho_Chi_Minh)` — and then exited 1 with `is_error: true` and, notably,
		// `subtype: "success"`. So the *structured* fields do not distinguish this ending
		// from any other bad exit; the sentence is the only place the difference is stated,
		// which is why the table is a table of sentences.
		{saying: "You've hit your session limit", failure: failureQuotaExhausted},
	},
}

// hitAWall reads one thing the agent said for an ending a person has to clear.
//
// First verdict wins and later text cannot overwrite it: a CLI that says why it stopped says it
// once, and anything after that is the same turn winding down.
func hitAWall(cli, said string, out *Outcome) {
	if out.Failure != "" || said == "" {
		return
	}
	for _, known := range walls[cli] {
		if strings.Contains(said, known.saying) {
			out.Failure = known.failure
			return
		}
	}
}

func readClaudeCode(line []byte, journal *Journal, out *Outcome) {
	var parsed claudeLine
	if json.Unmarshal(line, &parsed) != nil {
		return
	}
	// Every line carries the session id, and the first one arrives before the agent has said
	// anything. Taking it from whichever line comes first means a turn that dies halfway still
	// leaves behind the handle needed to carry the conversation on (FR-023).
	if out.Session == "" && parsed.SessionID != "" {
		out.Session = parsed.SessionID
	}

	switch parsed.Type {
	case "assistant", "user":
		var blocks claudeBlocks
		if json.Unmarshal(parsed.Message, &blocks) != nil {
			return
		}
		for _, block := range blocks.Content {
			switch block.Type {
			case "text":
				journal.Text(block.Text)
				hitAWall("claude_code", block.Text, out)
			case "thinking":
				journal.Thought(block.Thinking)
			case "tool_use":
				// Arguments in full, on purpose: FR-043 asks for the whole of them, and it is
				// the *result* that must never leave this machine, not the request.
				journal.ToolStarted(block.ID, block.Name, block.Input, block.Input != nil)
			case "tool_result":
				// What the tool returned stays here (FR-043a). The summary built from it —
				// size, kind, opening bytes, and whether it was cut — is all that travels.
				journal.ToolCompleted(block.ToolUseID, block.IsError, resultOf(block.Content))
			}
		}

	case "result":
		out.Usage = parsed.Usage
		if parsed.IsError {
			journal.Fail("agent_reported_failure", map[string]any{"why": parsed.Subtype})
		}
	}
}

// geminiLine is one line of Gemini CLI's stream-json output, in the fields read here.
//
// Shapes read off the `gemini 0.56.0` bundle (`JsonStreamEventType` and the non-interactive loop
// that emits it), which are also the shapes Multica's reader of this CLI was written against.
type geminiLine struct {
	Type      string `json:"type"`
	SessionID string `json:"session_id"`
	// message
	Role    string `json:"role"`
	Content string `json:"content"`
	// tool_use
	ToolName   string         `json:"tool_name"`
	ToolID     string         `json:"tool_id"`
	Parameters map[string]any `json:"parameters"`
	// tool_result, and result
	Status string `json:"status"`
	// Output is a pointer because absent is not empty (FR-047): the bundle leaves the field out
	// when a tool had nothing to display, and that is not a tool that printed nothing.
	Output *string `json:"output"`
	// error
	Severity string `json:"severity"`
	Message  string `json:"message"`
	// result
	Error *struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	} `json:"error"`
	Stats map[string]any `json:"stats"`
}

// geminiReader reads one turn of Gemini CLI.
//
// It has memory because the agent's words arrive in fragments — every `message` line from the
// agent is marked `delta: true` — and one event per fragment would turn a paragraph into dozens of
// entries in the record. The fragments are held until something else happens (a tool is called,
// the turn ends) and then said as one piece, which is the same grain Claude Code reports text at.
type geminiReader struct {
	said strings.Builder
}

func (g *geminiReader) read(line []byte, journal *Journal, out *Outcome) {
	var parsed geminiLine
	if json.Unmarshal(line, &parsed) != nil {
		return
	}
	// Only `init` carries the id, and it arrives before the agent has said anything — so a turn
	// that dies halfway still leaves behind the handle that carries the conversation on (FR-023).
	if out.Session == "" && parsed.SessionID != "" {
		out.Session = parsed.SessionID
	}

	switch parsed.Type {
	case "message":
		// The bundle also echoes the message it was given, as `role: "user"`. That is ours, not
		// the agent's, and it is already in the record.
		if parsed.Role == "assistant" {
			g.said.WriteString(parsed.Content)
		}
	case "tool_use":
		g.finish(journal, out)
		journal.ToolStarted(parsed.ToolID, parsed.ToolName, parsed.Parameters, parsed.Parameters != nil)
	case "tool_result":
		g.finish(journal, out)
		result := Result{}
		if parsed.Output != nil {
			result = Result{Exposed: true, Body: *parsed.Output}
		}
		journal.ToolCompleted(parsed.ToolID, parsed.Status == "error", result)
	case "error":
		g.finish(journal, out)
		// Warnings are the CLI narrating a retry or a hook, and the next line may well disprove
		// them; only an error is a fact about this turn.
		if parsed.Severity == "error" && parsed.Message != "" {
			journal.Fail("agent_reported_failure", map[string]any{"why": parsed.Message})
		}
	case "result":
		g.finish(journal, out)
		if parsed.Stats != nil {
			out.Usage = parsed.Stats
		}
		// A failed result names its cause only on the fatal path. Otherwise the cause was an
		// `error` line just before it, already recorded, and saying it twice would read as two.
		if parsed.Status == "error" && parsed.Error != nil {
			why := parsed.Error.Message
			if why == "" {
				why = parsed.Error.Type
			}
			journal.Fail("agent_reported_failure", map[string]any{"why": why})
		}
	}
}

// finish says whatever the agent has written since the last thing that was not words.
func (g *geminiReader) finish(journal *Journal, out *Outcome) {
	said := g.said.String()
	g.said.Reset()
	journal.Text(said)
	hitAWall("gemini", said, out)
}

// tail keeps the last bytes written to it and forgets the rest.
type tail struct {
	mu   sync.Mutex
	kept []byte
}

func (t *tail) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.kept = append(t.kept, p...)
	if len(t.kept) > maxStderrTail {
		t.kept = t.kept[len(t.kept)-maxStderrTail:]
	}
	return len(p), nil
}

// suffix is what the CLI complained about, ready to hang off the end of an error, or nothing at
// all if it complained about nothing.
func (t *tail) suffix() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	said := strings.TrimSpace(string(t.kept))
	if said == "" {
		return ""
	}
	return ": " + said
}
