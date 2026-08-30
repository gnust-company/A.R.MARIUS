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
	// args builds the command line. The message is never one of them — it goes in on standard
	// input, so that its length is not the operating system's business and so that it does not
	// sit in the process table for everyone on a shared machine to read.
	args func(req Request) []string
	// read turns one line of the CLI's output into events, and picks up whatever the outcome
	// needs. A line it does not recognise produces nothing: these streams carry banners,
	// progress and warnings alongside the events, and guessing at an unknown shape would put
	// invented facts in a record that is meant to be evidence.
	read func(line []byte, emit Emit, out *Outcome)
}

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
	//   - `--allowed-tools mcp__<server>` is what makes the declaration usable, and it was
	//     **measured, not assumed**: declared and not allowed, the tools appear in the agent's
	//     list, the agent calls one, and the call comes back denied — nobody is sitting here to
	//     grant it. This does not answer a permission question on the patron's behalf (FR-013b):
	//     it names the toolset this run was *given*, which is the scope decision itself
	//     (FR-013d). Handing an agent a set of tools and then refusing every use of them is not
	//     a stricter reading of the rule, it is a run that cannot report what it did. Only our
	//     own server is named; everything the agent asks to do in the world is untouched.
	"claude_code": {
		// Measured on 2.1.226, and measured **together with the probe that offers them**: the
		// values a person picks come out of `--effort (low, medium, high, xhigh, max)` and
		// `--model ... (e.g. 'fable', 'opus', or 'sonnet')`, which are the same two flags
		// named here. Reading the list from one place and spending it on another is how a
		// screen ends up offering a setting nothing applies.
		flags: map[string]string{"model": "--model", "thinking_level": "--effort"},
		args: func(req Request) []string {
			args := []string{"-p", "--output-format", "stream-json", "--verbose"}
			if req.ToolConfig != "" {
				args = append(args, "--mcp-config", req.ToolConfig)
			}
			if granted := grantedTools(req); len(granted) > 0 {
				args = append(args, "--allowed-tools", strings.Join(granted, " "))
			}
			if req.Session != "" {
				args = append(args, "--resume", req.Session)
			}
			return args
		},
		read: readClaudeCode,
	},

	// Codex. **Not measured** — the copy installed where this was written is missing its
	// platform binary and will not run at all, so every line below comes from the published
	// interface rather than from a run (research §9, task T130).
	//
	// It errs the way the capability probe errs: towards doing less. An argument that turns out
	// to be wrong makes the CLI refuse to start, which is loud; a reader that turns out to be
	// wrong recognises nothing and emits nothing, which is a quiet record rather than a false
	// one.
	"codex": {
		args: func(req Request) []string {
			if req.Session != "" {
				return []string{"exec", "resume", req.Session, "--json", "-"}
			}
			return []string{"exec", "--json", "-"}
		},
		read: readCodex,
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

// grantedTools names the tool servers this run was handed, in the form a CLI's allow-list uses.
//
// Derived from the declaration itself rather than written out again, so that the set a run is
// allowed to use and the set it was given are the same set by construction. A second list here
// would be a second answer to what this agent may do, and the two would part company on the day
// a server is added.
func grantedTools(req Request) []string {
	granted := make([]string, 0, len(req.ToolServers))
	for _, server := range req.ToolServers {
		if server.Name == "" {
			continue
		}
		granted = append(granted, "mcp__"+server.Name)
	}
	return granted
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
	if emit == nil {
		emit = func(Event) {}
	}

	cmd := newProcess(ctx, req, append(shape.args(req), chosen(req, shape.flags)...))
	cmd.Stdin = strings.NewReader(req.Message)

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
			shape.read(line, emit, &out)
		}
		if lines.Err() != nil && !errors.Is(lines.Err(), os.ErrClosed) {
			// The stream is unreadable from here on, but the process is still running and is
			// still doing the work. Say so and let it finish: killing a healthy agent because
			// this daemon lost the commentary would turn a gap in the record into lost work.
			overflow.Store(true)
			emit(Event{Type: EventRunError, Payload: map[string]any{
				"code": "output_unreadable",
				"cli":  req.CLI,
			}})
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
	} `json:"content"`
}

func readClaudeCode(line []byte, emit Emit, out *Outcome) {
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
				if block.Text != "" {
					emit(Event{Type: EventAssistantMessage, Payload: map[string]any{"text": block.Text}})
				}
			case "thinking":
				if block.Thinking != "" {
					emit(Event{Type: EventAssistantThinking, Payload: map[string]any{"text": block.Thinking}})
				}
			case "tool_use":
				// Arguments in full, on purpose: FR-043 asks for the whole of them, and it is
				// the *result* that must never leave this machine, not the request.
				emit(Event{Type: EventToolStarted, Payload: map[string]any{
					"call": block.ID,
					"name": block.Name,
					"args": block.Input,
				}})
			case "tool_result":
				// No content. What the tool returned stays here (FR-043a); the summary that may
				// travel — size, type, opening bytes, how much was cut — is built by the layer
				// that owns the threshold (task T095).
				emit(Event{Type: EventToolCompleted, Payload: map[string]any{
					"call":   block.ToolUseID,
					"failed": block.IsError,
				}})
			}
		}

	case "result":
		out.Usage = parsed.Usage
		if parsed.IsError {
			emit(Event{Type: EventRunError, Payload: map[string]any{
				"code": "agent_reported_failure",
				"why":  parsed.Subtype,
			}})
		}
	}
}

// codexLine is one line of Codex's `--json` output, **as published rather than as measured**
// (see the note on the codex entry above).
type codexLine struct {
	Type     string `json:"type"`
	ThreadID string `json:"thread_id"`
	Item     struct {
		Type    string `json:"type"`
		ID      string `json:"id"`
		Text    string `json:"text"`
		Command string `json:"command"`
	} `json:"item"`
}

func readCodex(line []byte, emit Emit, out *Outcome) {
	var parsed codexLine
	if json.Unmarshal(line, &parsed) != nil {
		return
	}
	if out.Session == "" && parsed.ThreadID != "" {
		out.Session = parsed.ThreadID
	}
	if parsed.Type != "item.completed" {
		return
	}
	switch parsed.Item.Type {
	case "agent_message":
		if parsed.Item.Text != "" {
			emit(Event{Type: EventAssistantMessage, Payload: map[string]any{"text": parsed.Item.Text}})
		}
	case "reasoning":
		if parsed.Item.Text != "" {
			emit(Event{Type: EventAssistantThinking, Payload: map[string]any{"text": parsed.Item.Text}})
		}
	case "command_execution":
		emit(Event{Type: EventToolStarted, Payload: map[string]any{
			"call": parsed.Item.ID,
			"name": "command",
			"args": map[string]any{"command": parsed.Item.Command},
		}})
	}
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
