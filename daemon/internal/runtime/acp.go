package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sync"
)

// acpProtocolVersion is the version of the Agent Client Protocol this daemon speaks.
const acpProtocolVersion = 1

// acpFlags is what each ACP CLI is started with to make it speak the protocol instead of
// talking to a person.
//
// **Empty, and that is the correct content today.** The only ACP CLI of the first release is
// Gemini CLI, and its invocation may not be written before the probe has actually been run
// against it (FR-039a, task T013): what is known about its flag comes from a help page, not from
// a session, and a guess written here would be a daemon that starts a CLI and then waits forever
// for a handshake that was never going to come.
//
// The conversation below is not waiting on that answer, and that is the point of keeping the two
// apart. What ACP is — how a session opens, what an update looks like, who answers a permission
// request — is a fact about the protocol, and it is settled and tested here. What turns one
// particular CLI into an ACP peer is a fact about that CLI, and it arrives with T117 as a single
// line in this table.
var acpFlags = map[string][]string{}

// ACP runs the CLIs that hold a conversation over their own standard streams: JSON-RPC in, JSON-
// RPC out, for as long as the turn lasts (FR-039).
//
// The difference from the one-shot family is not the wire format, it is who may speak. A one-
// shot CLI is handed a message and prints an account of what it did; an ACP peer can stop
// mid-turn and ask something back. Everything above this package sees neither — both families
// come out as the same events under the same contract (FR-035, FR-037).
type ACP struct{}

// Run takes one turn over ACP.
func (ACP) Run(ctx context.Context, req Request, emit Emit) (Outcome, error) {
	flags, known := acpFlags[req.CLI]
	if !known {
		return Outcome{}, fmt.Errorf("%q is not an ACP CLI this daemon knows how to start", req.CLI)
	}
	if req.Binary == "" {
		return Outcome{}, fmt.Errorf("running %s needs the path it was found at", req.CLI)
	}
	if req.WorkDir == "" {
		return Outcome{}, fmt.Errorf("running %s needs the task's working directory", req.CLI)
	}

	cmd := newProcess(ctx, req, flags)

	toAgent, err := cmd.StdinPipe()
	if err != nil {
		return Outcome{}, fmt.Errorf("speaking to %s: %w", req.CLI, err)
	}
	// The same pipes the one-shot family owns, for the same reason: an ACP peer starts
	// programs too, and one of them holding this pipe open is what would make waiting for the
	// CLI a wait with no end (see `pipes`).
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
		reading    sync.WaitGroup
		complaints tail
	)
	reading.Add(1)
	go func() {
		defer reading.Done()
		_, _ = io.Copy(&complaints, streams.errs)
	}()

	out, talkErr := Converse(ctx, toAgent, streams.out, req, emit)
	// Closing our end is how an ACP peer is told the conversation is over; it then exits by
	// itself. Ending the process instead would be indistinguishable, from its side, from the
	// machine dying — and some of these CLIs write their session out on the way down.
	_ = toAgent.Close()
	waitErr := cmd.Wait()
	reap(cmd)
	streams.drain(&reading)

	if talkErr != nil {
		return out, fmt.Errorf("%s: %w%s", req.CLI, talkErr, complaints.suffix())
	}
	if waitErr != nil {
		return out, fmt.Errorf("%s ended badly: %w%s", req.CLI, waitErr, complaints.suffix())
	}
	return out, nil
}

// Converse runs one whole turn over an already-open pair of streams.
//
// Separate from Run so that the protocol can be exercised against a peer that is not a CLI at
// all. That is not only a convenience for tests: the one ACP CLI of this release is the one
// nobody has been able to run yet, so a protocol that could only be tested by running it would
// be a protocol nobody had tested.
func Converse(ctx context.Context, toAgent io.Writer, fromAgent io.Reader, req Request, emit Emit) (Outcome, error) {
	if req.Message == "" {
		return Outcome{}, fmt.Errorf("refusing to run %s with nothing to say to it", req.CLI)
	}
	if emit == nil {
		emit = func(Event) {}
	}
	c := &acpConn{
		out:   json.NewEncoder(toAgent),
		in:    newLineReader(fromAgent),
		emit:  emit,
		cwd:   req.WorkDir,
		outID: 0,
	}

	var handshake struct {
		ProtocolVersion int `json:"protocolVersion"`
	}
	if err := c.call(ctx, "initialize", map[string]any{
		"protocolVersion": acpProtocolVersion,
		// Said plainly rather than left out: this client offers the agent no file access and no
		// terminal of its own. An agent told that reaches for its own, which is what we want —
		// it is running in the task's directory with the operator's own credentials, and a file
		// road through this daemon would be a second, unaudited one (FR-013a).
		"clientCapabilities": map[string]any{
			"fs": map[string]any{"readTextFile": false, "writeTextFile": false},
		},
	}, &handshake); err != nil {
		return c.outcome, fmt.Errorf("opening the conversation: %w", err)
	}

	if err := c.openSession(ctx, req); err != nil {
		return c.outcome, err
	}

	var turn struct {
		StopReason string `json:"stopReason"`
	}
	if err := c.call(ctx, "session/prompt", map[string]any{
		"sessionId": c.outcome.Session,
		"prompt":    []any{map[string]any{"type": "text", "text": req.Message}},
	}, &turn); err != nil {
		return c.outcome, fmt.Errorf("taking the turn: %w", err)
	}
	return c.outcome, nil
}

// openSession carries the old conversation on if there is one, and starts a new one otherwise.
//
// A CLI that cannot load the session it was given is **not** a failure: FR-039a says a missing
// capability is still support, and FR-025 says the answer is a new session with a note. So a
// refused load falls through to a new session rather than ending the run — the work gets done,
// and the record says the thread was lost.
func (c *acpConn) openSession(ctx context.Context, req Request) error {
	if req.Session != "" {
		c.outcome.Session = req.Session
		if err := c.call(ctx, "session/load", map[string]any{
			"sessionId":  req.Session,
			"cwd":        c.cwd,
			"mcpServers": []any{},
		}, nil); err == nil {
			return nil
		}
		c.emit(Event{Type: EventRunError, Payload: map[string]any{
			"code":    "session_not_resumed",
			"session": req.Session,
		}})
		c.outcome.Session = ""
	}

	var opened struct {
		SessionID string `json:"sessionId"`
	}
	if err := c.call(ctx, "session/new", map[string]any{
		"cwd":        c.cwd,
		"mcpServers": []any{},
	}, &opened); err != nil {
		return fmt.Errorf("opening a session: %w", err)
	}
	if opened.SessionID == "" {
		return fmt.Errorf("the agent opened a session and did not say which")
	}
	c.outcome.Session = opened.SessionID
	return nil
}

// acpConn is one conversation: a place to write requests, a place to read whatever comes back,
// and what has been learned so far.
//
// Single-threaded on purpose. There is never more than one outstanding call — a turn is one
// question with one answer — so the reader can simply run until it sees the answer, handling
// everything that arrives in the meantime. A dispatcher with a table of pending calls would be
// more general and would have a whole class of bug this cannot have.
type acpConn struct {
	out     *json.Encoder
	in      *bufio.Scanner
	emit    Emit
	cwd     string
	outID   int
	outcome Outcome
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

func (e rpcError) Error() string { return fmt.Sprintf("%s (%d)", e.Message, e.Code) }

type rpcMessage struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method,omitempty"`
	Params  json.RawMessage `json:"params,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

// call asks one question and reads until its answer arrives, dealing with everything the agent
// says on the way.
func (c *acpConn) call(ctx context.Context, method string, params any, result any) error {
	c.outID++
	id := c.outID
	if err := c.out.Encode(rpcMessage{
		JSONRPC: "2.0",
		ID:      json.RawMessage(fmt.Sprintf("%d", id)),
		Method:  method,
		Params:  mustRaw(params),
	}); err != nil {
		return fmt.Errorf("asking %s: %w", method, err)
	}

	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		if !c.in.Scan() {
			if err := c.in.Err(); err != nil {
				return fmt.Errorf("reading the answer to %s: %w", method, err)
			}
			return fmt.Errorf("the agent stopped talking before answering %s", method)
		}
		line := c.in.Bytes()
		if len(line) == 0 || line[0] != '{' {
			continue
		}
		var msg rpcMessage
		if json.Unmarshal(line, &msg) != nil {
			continue
		}

		switch {
		case msg.Method != "" && len(msg.ID) == 0:
			c.notified(msg)
		case msg.Method != "":
			if err := c.answer(msg); err != nil {
				return err
			}
		case string(msg.ID) == fmt.Sprintf("%d", id):
			if msg.Error != nil {
				return *msg.Error
			}
			if result == nil || len(msg.Result) == 0 {
				return nil
			}
			if err := json.Unmarshal(msg.Result, result); err != nil {
				return fmt.Errorf("reading the answer to %s: %w", method, err)
			}
			return nil
		}
		// An answer to a question nobody asked is dropped. It cannot be the one being waited
		// for, and treating it as one would mean a stale reply could end the wrong wait.
	}
}

// sessionUpdate is the one notification that carries the work.
type sessionUpdate struct {
	Update struct {
		Kind    string `json:"sessionUpdate"`
		Content struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
		ToolCallID string         `json:"toolCallId"`
		Title      string         `json:"title"`
		Status     string         `json:"status"`
		RawInput   map[string]any `json:"rawInput"`
	} `json:"update"`
}

func (c *acpConn) notified(msg rpcMessage) {
	if msg.Method != "session/update" {
		return
	}
	var update sessionUpdate
	if json.Unmarshal(msg.Params, &update) != nil {
		return
	}

	switch update.Update.Kind {
	case "agent_message_chunk":
		if update.Update.Content.Text != "" {
			c.emit(Event{Type: EventAssistantMessage, Payload: map[string]any{"text": update.Update.Content.Text}})
		}
	case "agent_thought_chunk":
		if update.Update.Content.Text != "" {
			c.emit(Event{Type: EventAssistantThinking, Payload: map[string]any{"text": update.Update.Content.Text}})
		}
	case "tool_call":
		payload := map[string]any{"call": update.Update.ToolCallID, "name": update.Update.Title}
		// Arguments only when the CLI actually sent them. An empty map here would read as *the
		// tool was called with nothing*, which is a different fact from *this CLI does not say*
		// — and telling those two apart is the whole of FR-047.
		if update.Update.RawInput != nil {
			payload["args"] = update.Update.RawInput
		}
		c.emit(Event{Type: EventToolStarted, Payload: payload})
	case "tool_call_update":
		switch update.Update.Status {
		case "completed", "failed":
			c.emit(Event{Type: EventToolCompleted, Payload: map[string]any{
				"call":   update.Update.ToolCallID,
				"failed": update.Update.Status == "failed",
			}})
		}
	}
}

// answer replies to something the agent asked of us.
//
// **Permission is refused, because there is nobody here to grant it.** A run happens with no
// person watching, and this daemon was given a machine's credentials, not a patron's judgement.
// Answering *yes* on their behalf would make every unattended run carry an approval nobody gave;
// answering *no* costs the agent one tool call and puts a code in the record saying exactly what
// it wanted. Which of those is right for an unattended run is a product decision that has not
// been made yet — task T131 in specs/002-daemon-acp-runtime/tasks.md — and until it is, the
// refusal is the answer that cannot do damage.
func (c *acpConn) answer(msg rpcMessage) error {
	if msg.Method == "session/request_permission" {
		c.emit(Event{Type: EventRunError, Payload: map[string]any{"code": "permission_refused_nobody_to_ask"}})
		return c.out.Encode(rpcMessage{
			JSONRPC: "2.0",
			ID:      msg.ID,
			Result:  mustRaw(map[string]any{"outcome": map[string]any{"outcome": "cancelled"}}),
		})
	}
	// Everything else is something this client said it could not do during the handshake. The
	// error is the honest answer, and it is one the protocol already has a code for.
	return c.out.Encode(rpcMessage{
		JSONRPC: "2.0",
		ID:      msg.ID,
		Error:   &rpcError{Code: -32601, Message: "this client does not provide " + msg.Method},
	})
}

func mustRaw(v any) json.RawMessage {
	raw, err := json.Marshal(v)
	if err != nil {
		// Everything marshalled here is built a few lines above out of strings, numbers and
		// maps of the same. There is no input that reaches this.
		return json.RawMessage(`null`)
	}
	return raw
}

func newLineReader(r io.Reader) *bufio.Scanner {
	lines := bufio.NewScanner(r)
	lines.Buffer(make([]byte, 0, 64<<10), maxOutputLine)
	return lines
}
