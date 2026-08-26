package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
	"sync"
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
	"claude_code": {
		args: func(req Request) []string {
			args := []string{"-p", "--output-format", "stream-json", "--verbose"}
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

	// CommandContext ends the CLI itself when the context does. Whatever the CLI has started
	// underneath it is not covered here — cleaning up the tree is the supervisor's job, and it
	// is the supervisor that knows a run is over (task T067).
	cmd := exec.CommandContext(ctx, req.Binary, shape.args(req)...) //nolint:gosec // the path is what discovery found on this machine
	cmd.Dir = req.WorkDir
	cmd.Env = req.Env
	cmd.Stdin = strings.NewReader(req.Message)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return Outcome{}, fmt.Errorf("reading what %s says: %w", req.CLI, err)
	}
	var complaints tail
	cmd.Stderr = &complaints

	if err := cmd.Start(); err != nil {
		return Outcome{}, fmt.Errorf("starting %s: %w", req.CLI, err)
	}

	var (
		out      Outcome
		reading  sync.WaitGroup
		overflow bool
	)
	reading.Add(1)
	go func() {
		defer reading.Done()
		lines := bufio.NewScanner(stdout)
		lines.Buffer(make([]byte, 0, 64<<10), maxOutputLine)
		for lines.Scan() {
			line := lines.Bytes()
			if len(line) == 0 || line[0] != '{' {
				continue
			}
			shape.read(line, emit, &out)
		}
		if lines.Err() != nil {
			// The stream is unreadable from here on, but the process is still running and is
			// still doing the work. Say so and let it finish: killing a healthy agent because
			// this daemon lost the commentary would turn a gap in the record into lost work.
			overflow = true
			emit(Event{Type: EventRunError, Payload: map[string]any{
				"code": "output_unreadable",
				"cli":  req.CLI,
			}})
		}
	}()

	// Waited for before Wait: Wait closes the pipe, and closing it under the reader would end
	// the record a few events early on a run that was about to finish normally.
	reading.Wait()
	err = cmd.Wait()
	if err != nil {
		return out, fmt.Errorf("%s ended badly: %w%s", req.CLI, err, complaints.suffix())
	}
	if overflow {
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
					emit(Event{Type: EventAgentMessage, Payload: map[string]any{"text": block.Text}})
				}
			case "thinking":
				if block.Thinking != "" {
					emit(Event{Type: EventAgentThinking, Payload: map[string]any{"text": block.Thinking}})
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
				emit(Event{Type: EventToolFinished, Payload: map[string]any{
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
			emit(Event{Type: EventAgentMessage, Payload: map[string]any{"text": parsed.Item.Text}})
		}
	case "reasoning":
		if parsed.Item.Text != "" {
			emit(Event{Type: EventAgentThinking, Payload: map[string]any{"text": parsed.Item.Text}})
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
