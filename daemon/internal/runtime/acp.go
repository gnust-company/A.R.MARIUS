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
	// One gate for everything this conversation says, so masking and the tool-result cut hold
	// on this family for the same reason they hold on the other (FR-043a, FR-048a).
	c := &acpConn{
		out:     json.NewEncoder(toAgent),
		in:      newLineReader(fromAgent),
		journal: NewJournal(req, emit),
		cwd:     req.WorkDir,
		outID:   0,
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

	// What the machine has to say about the conversation itself, decided before the turn: the
	// thread aged out, or belonged to a workplace that is gone (FR-025, FR-026, FR-027).
	notice := tell(c.journal, req.Restart)

	if err := c.openSession(ctx, req); err != nil {
		return c.outcome, err
	}
	// And what only became true inside it: the handle was offered and would not load. Found
	// here rather than before the turn, which is exactly why the notice is assembled in two
	// places and sent in one (FR-039a).
	notice = ahead(notice, tell(c.journal, c.refused))
	c.outcome.SessionRefused = c.refused != nil

	var turn struct {
		StopReason string `json:"stopReason"`
	}
	if err := c.call(ctx, "session/prompt", map[string]any{
		"sessionId": c.outcome.Session,
		"prompt":    []any{map[string]any{"type": "text", "text": ahead(notice, req.Message)}},
	}, &turn); err != nil {
		return c.outcome, fmt.Errorf("taking the turn: %w", err)
	}
	return c.outcome, nil
}

// mcpServers is this run's callback tools, in the shape the handshake carries them (FR-013a).
//
// This is the native face for the whole ACP family: a peer is told about its tools when the
// session opens, so there is no file to write and nothing per-CLI to declare. The same list is
// sent when a session is resumed as when one is opened — a resumed conversation is still this
// run, and this run's tools are the ones minted for it.
//
// It answers with an empty list rather than nothing when a run was given no tools, because the
// two mean the same thing here and an absent field would leave the peer guessing which.
func mcpServers(req Request) []map[string]any {
	servers := make([]map[string]any, 0, len(req.ToolServers))
	for _, s := range req.ToolServers {
		declared := map[string]any{"name": s.Name, "command": s.Command}
		if len(s.Args) > 0 {
			declared["args"] = s.Args
		}
		// No env. The peer starts the program as a child of itself, so it inherits the
		// environment this run was built with — which is where the run's own credential already
		// is, and the only place FR-013c allows it to be.
		servers = append(servers, declared)
	}
	return servers
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
			"mcpServers": mcpServers(req),
		}, nil); err == nil {
			return nil
		}
		// Recorded by `tell` along with every other way a thread is lost, so that one shape of
		// event covers all four and the agent is told in the same words whichever happened.
		c.refused = &Restart{Code: RestartRefused, Params: map[string]any{"session": req.Session}}
		c.outcome.Session = ""
	}

	var opened struct {
		SessionID string `json:"sessionId"`
	}
	if err := c.call(ctx, "session/new", map[string]any{
		"cwd":        c.cwd,
		"mcpServers": mcpServers(req),
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
	journal *Journal
	cwd     string
	outID   int
	outcome Outcome
	// refused is set when the handle this run was given would not load — the one way of losing
	// a thread that cannot be known until the turn has already begun (FR-039a).
	refused *Restart
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
		// RawOutput is what the tool gave back. Left raw so it is read, measured and dropped
		// here rather than carried anywhere: the whole of it never leaves this machine
		// (FR-043a), and a field this side decoded into a struct is a field this side is
		// holding onto.
		RawOutput json.RawMessage `json:"rawOutput"`
	} `json:"update"`
}

// resultIn reads what a tool returned out of an ACP update.
//
// Absent is not empty, and this is where that distinction is made for this family: an agent that
// sends no rawOutput has not told us its tool returned nothing, it has told us nothing (FR-047).
func resultIn(raw json.RawMessage) Result {
	if len(raw) == 0 || string(raw) == "null" {
		return Result{}
	}
	var text string
	if json.Unmarshal(raw, &text) == nil {
		return Result{Exposed: true, Body: text}
	}
	// Anything else is structured, and its own JSON is the most faithful rendering of it there
	// is — no field of it is interpreted, so nothing about its shape is assumed.
	return Result{Exposed: true, Body: string(raw), Kind: "json"}
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
		c.journal.Text(update.Update.Content.Text)
	case "agent_thought_chunk":
		c.journal.Thought(update.Update.Content.Text)
	case "tool_call":
		// Arguments only when the CLI actually sent them. An empty map here would read as *the
		// tool was called with nothing*, which is a different fact from *this CLI does not say*
		// — and telling those two apart is the whole of FR-047.
		c.journal.ToolStarted(
			update.Update.ToolCallID, update.Update.Title,
			update.Update.RawInput, update.Update.RawInput != nil,
		)
	case "tool_call_update":
		switch update.Update.Status {
		case "completed", "failed":
			c.journal.ToolCompleted(
				update.Update.ToolCallID,
				update.Update.Status == "failed",
				resultIn(update.Update.RawOutput),
			)
		}
	}
}

// answer replies to something the agent asked of us.
//
// **Permission is refused, because there is nobody here to grant it.** A run happens with no
// person watching, and this daemon was given a machine's credentials, not a patron's judgement.
// Answering *yes* on their behalf would make every unattended run carry an approval nobody gave;
// answering *no* costs the agent one tool call and puts a code in the record saying exactly what
// it wanted. Refusing is the rule rather than a placeholder (FR-013b): this system does not
// promise an approval road, and if one is ever wanted it will arrive as a requirement of its
// own rather than as the missing half of this.
func (c *acpConn) answer(msg rpcMessage) error {
	if msg.Method == "session/request_permission" {
		c.journal.Fail("permission_refused_nobody_to_ask", nil)
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
