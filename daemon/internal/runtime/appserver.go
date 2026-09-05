package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// appServerStart is what a Codex-family CLI is started with to make it speak to a program
// instead of to a person, read off the row for that kind — the same row, and the same flag,
// that the capability probe starts the binary with (FR-017).
func appServerStart(kind string) ([]string, bool) {
	row, known := agentcli.Lookup(kind)
	if !known || row.Family != agentcli.FamilyAppServer || len(row.ProtocolArgs) == 0 {
		return nil, false
	}
	return row.ProtocolArgs, true
}

// AppServer runs Codex, which holds a conversation the way the ACP family does and does not
// share a single method name with it (FR-039d).
//
// That is the whole reason this is a family of its own rather than a dialect of the other one.
// Both send newline-delimited JSON-RPC 2.0 down the same two pipes, so a reader looking only at
// the wire would call them the same thing; but where ACP says `session/new` this one says
// `thread/start`, where ACP ends a turn by answering the request that began it this one ends a
// turn by announcing `turn/completed`, and where ACP asks permission with one method this one
// asks with four. A client that knew "JSON-RPC over stdio" and nothing else could open the pipe
// and then say nothing the other side understood.
//
// The one difference that shapes this file: **the turn is not the answer to a question.**
// `turn/start` replies immediately with a turn that has not run yet, and the work arrives
// afterwards as notifications until the server says the turn is over. So the loop here waits on
// a fact rather than on a reply, and a call is just the special case of waiting for one.
type AppServer struct{}

// Run takes one turn against a Codex app-server.
func (AppServer) Run(ctx context.Context, req Request, emit Emit) (Outcome, error) {
	flags, known := appServerStart(req.CLI)
	if !known {
		return Outcome{}, fmt.Errorf("%q is not an app-server CLI this daemon knows how to start", req.CLI)
	}
	if req.Binary == "" {
		return Outcome{}, fmt.Errorf("running %s needs the path it was found at", req.CLI)
	}
	if req.WorkDir == "" {
		return Outcome{}, fmt.Errorf("running %s needs the task's working directory", req.CLI)
	}

	// Built into a slice of its own rather than appended onto the row's: `flags` is the table's
	// own array, and appending to a shared slice is the kind of aliasing that stays invisible
	// until the day it does not.
	started := make([]string, 0, len(flags)+4)
	started = append(started, flags...)
	started = append(started, toolFlags(req)...)

	cmd := newProcess(ctx, req, started)

	toAgent, err := cmd.StdinPipe()
	if err != nil {
		return Outcome{}, fmt.Errorf("speaking to %s: %w", req.CLI, err)
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
		reading    sync.WaitGroup
		complaints tail
	)
	reading.Add(1)
	go func() {
		defer reading.Done()
		_, _ = io.Copy(&complaints, streams.errs)
	}()

	out, talkErr := Attend(ctx, toAgent, streams.out, req, emit)
	// Closing our end is how the app-server is told the conversation is over; it exits by
	// itself. Ending the process instead would be indistinguishable, from its side, from the
	// machine dying — and this one writes its thread out on the way down.
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

// toolFlags declares this run's callback tools to a Codex-family CLI (FR-013a).
//
// This family has nowhere else to put them. An ACP peer is told about its tools when the session
// opens; Claude Code is handed a file named on its command line. Codex has neither: MCP servers
// are *configuration* to it, and its configuration is the operator's own — the very file this
// run's home links straight through to theirs. Writing ours in there would be this daemon editing
// an operator's installation, which FR-013a forbids outright.
//
// So they are declared the way Codex's own command line allows one setting to be overridden for
// one process: `-c <dotted key>=<TOML value>`. That adds an entry beside whatever the operator
// configured, for this process only, and changes nothing on disk. A run given no tools adds no
// flags, which is the same command line the CLI would have been started with anyway.
func toolFlags(req Request) []string {
	flags := make([]string, 0, 4*len(req.ToolServers))
	for _, server := range req.ToolServers {
		at := "mcp_servers." + server.Name
		flags = append(flags, "-c", at+".command="+asTOML(server.Command))
		if len(server.Args) > 0 {
			flags = append(flags, "-c", at+".args="+asTOML(server.Args))
		}
		// No env, for the reason the ACP handshake sends none: the server is started as a child
		// of the CLI, so it inherits the environment this run was built with — which is where
		// this run's credential already is, and the only place FR-013c allows it to be.
	}
	return flags
}

// asTOML renders one value for the right-hand side of a `-c` override.
//
// JSON, deliberately. A TOML basic string and a JSON string are the same syntax for everything
// Go's encoder emits, and an array of them is a TOML array — so the standard library's escaping
// is correct here, and a hand-rolled quoter would be a second escaping implementation guarding
// a path where getting it wrong means a CLI that will not start.
func asTOML(value any) string {
	rendered, err := json.Marshal(value)
	if err != nil {
		// Only strings and slices of strings reach this.
		return `""`
	}
	return string(rendered)
}

// Attend runs one whole turn over an already-open pair of streams.
//
// Separate from Run for the same reason Converse is: the protocol can then be exercised against
// a peer that is not a CLI, which is the only way it gets tested at all on a machine whose Codex
// will not start.
func Attend(ctx context.Context, toAgent io.Writer, fromAgent io.Reader, req Request, emit Emit) (Outcome, error) {
	if req.Message == "" {
		return Outcome{}, fmt.Errorf("refusing to run %s with nothing to say to it", req.CLI)
	}
	c := &appConn{
		out:     json.NewEncoder(toAgent),
		in:      newLineReader(fromAgent),
		journal: NewJournal(req, emit),
		cwd:     req.WorkDir,
	}

	if err := c.call(ctx, "initialize", map[string]any{
		"clientInfo": map[string]any{
			"name":    appServerClient,
			"title":   "Armarius",
			"version": appServerClientVersion,
		},
	}, nil); err != nil {
		return c.outcome, fmt.Errorf("opening the conversation: %w", err)
	}
	// The handshake is two messages, not one: every other method on this connection is
	// refused with *Not initialized* until this notification has been sent. Skipping it is a
	// daemon that connects successfully and is then told no to everything it asks.
	if err := c.notify("initialized", map[string]any{}); err != nil {
		return c.outcome, fmt.Errorf("opening the conversation: %w", err)
	}

	notice := tell(c.journal, req.Restart)

	if err := c.openThread(ctx, req); err != nil {
		return c.outcome, err
	}
	notice = ahead(notice, tell(c.journal, c.refused))
	c.outcome.SessionRefused = c.refused != nil

	if err := c.call(ctx, "turn/start", map[string]any{
		"threadId": c.outcome.Session,
		"input":    []any{map[string]any{"type": "text", "text": ahead(notice, req.Message)}},
	}, nil); err != nil {
		return c.outcome, fmt.Errorf("taking the turn: %w", err)
	}
	// And now the part that has no equivalent in the other family: the turn was accepted, not
	// performed. Everything the agent does arrives from here on as notifications, and the only
	// authority on the turn being over is the server saying so.
	if err := c.hear(ctx, "the turn to end", func() bool { return c.turnOver }); err != nil {
		return c.outcome, err
	}
	if c.trouble != "" {
		return c.outcome, fmt.Errorf("the turn ended badly: %s", c.trouble)
	}
	return c.outcome, nil
}

// appServerClient is how this daemon names itself in the handshake. Codex records the name
// against the account's compliance log, so it says who is actually driving rather than
// borrowing the name of an editor.
const (
	appServerClient = "armarius_daemon"
	// appServerClientVersion is the handshake's version field. It names the protocol shape
	// this client speaks, not the daemon's build: the server reads it to decide what it may
	// send back, and tying it to a build number would change that answer on every release.
	appServerClientVersion = "1"
)

// openThread carries the old conversation on if there is one, and starts a fresh one otherwise.
//
// A thread that will not resume is **not** a failure, for the same reason it is not one on the
// ACP road: FR-039a says a missing capability is still support, and FR-025 says the answer is a
// new conversation with a note. The work gets done and the record says the thread was lost.
func (c *appConn) openThread(ctx context.Context, req Request) error {
	if req.Session != "" {
		c.outcome.Session = req.Session
		var resumed thread
		// excludeTurns, because the default is for the server to hand back the entire
		// reconstructed history of the thread, and this side reads none of it. Asking for it
		// would be paying to move a transcript across a pipe so it could be dropped.
		if err := c.call(ctx, "thread/resume", map[string]any{
			"threadId":     req.Session,
			"cwd":          c.cwd,
			"excludeTurns": true,
		}, &resumed); err == nil && resumed.Thread.ID != "" {
			c.outcome.Session = resumed.Thread.ID
			return nil
		}
		c.refused = &Restart{Code: RestartRefused, Params: map[string]any{"session": req.Session}}
		c.outcome.Session = ""
	}

	var opened thread
	// Nothing is sent about approvals, the sandbox, or the model's permissions, and that is
	// deliberate: those are settings of the operator's own Codex, and answering them here would
	// be this daemon deciding on their behalf what an unattended agent may do (FR-013b).
	if err := c.call(ctx, "thread/start", map[string]any{"cwd": c.cwd}, &opened); err != nil {
		return fmt.Errorf("opening a thread: %w", err)
	}
	if opened.Thread.ID == "" {
		return fmt.Errorf("the agent opened a thread and did not say which")
	}
	c.outcome.Session = opened.Thread.ID
	return nil
}

// thread is the shape both thread/start and thread/resume answer with.
type thread struct {
	Thread struct {
		ID string `json:"id"`
	} `json:"thread"`
}

// appConn is one conversation: a place to write, a place to read, and what has been learned.
//
// Single-threaded for the same reason acpConn is, and with one addition: what is being waited
// for is a predicate rather than an id, because on this protocol the thing worth waiting for is
// usually not a reply.
type appConn struct {
	out     *json.Encoder
	in      *bufio.Scanner
	journal *Journal
	cwd     string
	outID   int
	outcome Outcome

	// refused is set when the thread this run was given would not resume.
	refused *Restart
	// waiting is the id of the call in flight; answered and reply are how it comes back.
	waiting  int
	answered bool
	reply    rpcMessage
	// turnOver and trouble are what the turn's own ending said.
	turnOver bool
	trouble  string
}

// call asks one question and waits for its answer, dealing with everything said on the way.
func (c *appConn) call(ctx context.Context, method string, params any, result any) error {
	c.outID++
	c.waiting, c.answered, c.reply = c.outID, false, rpcMessage{}
	if err := c.out.Encode(rpcMessage{
		JSONRPC: "2.0",
		ID:      json.RawMessage(fmt.Sprintf("%d", c.outID)),
		Method:  method,
		Params:  mustRaw(params),
	}); err != nil {
		return fmt.Errorf("asking %s: %w", method, err)
	}
	if err := c.hear(ctx, "an answer to "+method, func() bool { return c.answered }); err != nil {
		return err
	}
	if c.reply.Error != nil {
		return *c.reply.Error
	}
	if result == nil || len(c.reply.Result) == 0 {
		return nil
	}
	if err := json.Unmarshal(c.reply.Result, result); err != nil {
		return fmt.Errorf("reading the answer to %s: %w", method, err)
	}
	return nil
}

// notify sends a notification, which by definition has no answer to wait for.
func (c *appConn) notify(method string, params any) error {
	if err := c.out.Encode(rpcMessage{JSONRPC: "2.0", Method: method, Params: mustRaw(params)}); err != nil {
		return fmt.Errorf("saying %s: %w", method, err)
	}
	return nil
}

// hear reads and dispatches until settled says the wait is over.
//
// The wait ends on a fact this side has learned, never on a message having arrived: the reply
// to a call and the end of a turn are both facts, and everything in between — items starting,
// items finishing, permission being asked for — is handled and does not end anything.
func (c *appConn) hear(ctx context.Context, what string, settled func() bool) error {
	for !settled() {
		if err := ctx.Err(); err != nil {
			return err
		}
		if !c.in.Scan() {
			if err := c.in.Err(); err != nil {
				return fmt.Errorf("reading %s: %w", what, err)
			}
			return fmt.Errorf("the agent stopped talking before %s", what)
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
			if err := c.asked(msg); err != nil {
				return err
			}
		case string(msg.ID) == fmt.Sprintf("%d", c.waiting) && !c.answered:
			c.answered, c.reply = true, msg
		}
		// An answer to a question nobody asked is dropped: it cannot be the one being waited
		// for, and treating it as one would let a stale reply end the wrong wait.
	}
	return nil
}

// item is the one notification shape that carries work, in the fields this side reads.
//
// The pointers are the point. Codex sends `aggregatedOutput` as null when it has nothing to say
// about a command's output, and absent is not empty (FR-047): a command whose output this side
// never saw must be recorded as *not revealed*, not as *a command that printed nothing*.
type item struct {
	Item struct {
		Type      string          `json:"type"`
		ID        string          `json:"id"`
		Status    string          `json:"status"`
		Text      string          `json:"text"`
		Summary   []string        `json:"summary"`
		Content   []string        `json:"content"`
		Command   string          `json:"command"`
		Output    *string         `json:"aggregatedOutput"`
		Changes   json.RawMessage `json:"changes"`
		Server    string          `json:"server"`
		Tool      string          `json:"tool"`
		Arguments map[string]any  `json:"arguments"`
		Result    json.RawMessage `json:"result"`
	} `json:"item"`
}

// ended says whether an item's status is one this side should record as having gone wrong.
//
// Declined counts. A command the daemon refused permission for did not run, and a record that
// showed it as an ordinary completed step would be a record of work that never happened.
func ended(status string) bool { return status == "failed" || status == "declined" }

func (c *appConn) notified(msg rpcMessage) {
	switch msg.Method {
	case "item/started", "item/completed":
		c.itemMoved(msg)
	case "turn/completed":
		c.turnEnded(msg)
	case "error":
		c.wentWrong(msg)
	}
}

func (c *appConn) itemMoved(msg rpcMessage) {
	var moved item
	if json.Unmarshal(msg.Params, &moved) != nil {
		return
	}
	it := moved.Item
	started := msg.Method == "item/started"

	switch it.Type {
	case "commandExecution":
		if started {
			c.journal.ToolStarted(it.ID, "command", map[string]any{"command": it.Command}, true)
			return
		}
		c.journal.ToolCompleted(it.ID, ended(it.Status), sawOutput(it.Output))
	case "fileChange":
		if started {
			// Arguments only when they were actually sent, so *the CLI does not say* stays
			// distinguishable from *there was nothing to say* (FR-047).
			c.journal.ToolStarted(it.ID, "patch", changed(it.Changes), it.Changes != nil)
			return
		}
		// A file change carries its outcome in its status and no output of its own, so there
		// is nothing here to expose and saying so is the honest record.
		c.journal.ToolCompleted(it.ID, ended(it.Status), Result{})
	case "mcpToolCall":
		if started {
			c.journal.ToolStarted(it.ID, calledTool(it.Server, it.Tool), it.Arguments, it.Arguments != nil)
			return
		}
		c.journal.ToolCompleted(it.ID, ended(it.Status), resultIn(it.Result))
	case "agentMessage":
		if !started && it.Text != "" {
			c.journal.Text(it.Text)
		}
	case "reasoning":
		if !started {
			if said := strings.TrimSpace(strings.Join(append(it.Summary, it.Content...), "\n")); said != "" {
				c.journal.Thought(said)
			}
		}
	}
}

// calledTool renders the two fields Codex keeps apart into the one name an event carries.
//
// Composed rather than picking one: the tool name alone is ambiguous the moment two servers
// offer the same one, and the server alone does not say what was called.
func calledTool(server, tool string) string {
	if server == "" {
		return tool
	}
	return server + "/" + tool
}

// changed renders a file change's own description of itself, without reading into it.
func changed(raw json.RawMessage) map[string]any {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	return map[string]any{"changes": raw}
}

// sawOutput turns what a command said into a result, keeping absent apart from empty.
func sawOutput(output *string) Result {
	if output == nil {
		return Result{}
	}
	return Result{Exposed: true, Body: *output}
}

func (c *appConn) turnEnded(msg rpcMessage) {
	var done struct {
		Turn struct {
			Status string         `json:"status"`
			Usage  map[string]any `json:"usage"`
			Error  struct {
				Message string `json:"message"`
			} `json:"error"`
		} `json:"turn"`
	}
	if json.Unmarshal(msg.Params, &done) != nil {
		return
	}
	c.turnOver = true
	if done.Turn.Usage != nil {
		c.outcome.Usage = done.Turn.Usage
	}
	// A turn that was interrupted or failed is a turn that did not do the work, and the run has
	// to end badly or the task moves on as though it had. No failure code is attached: this
	// side has never measured a sentence from this CLI, and the server's own rule is that an
	// ending nobody classified is retried rather than put in front of a person (FR-032a).
	switch done.Turn.Status {
	case "failed", "interrupted":
		c.trouble = done.Turn.Error.Message
		if c.trouble == "" {
			c.trouble = done.Turn.Status
		}
	}
}

// wentWrong records a protocol-level complaint, and only the terminal ones.
//
// A retrying error is the server saying it is having another go, which is not yet a fact about
// this turn; recording it would put a reason in the record that the next second disproves.
func (c *appConn) wentWrong(msg rpcMessage) {
	var trouble struct {
		WillRetry bool `json:"willRetry"`
		Error     struct {
			Message string `json:"message"`
		} `json:"error"`
		Message string `json:"message"`
	}
	if json.Unmarshal(msg.Params, &trouble) != nil || trouble.WillRetry {
		return
	}
	said := trouble.Error.Message
	if said == "" {
		said = trouble.Message
	}
	if said != "" {
		c.journal.Fail("agent_reported_failure", map[string]any{"why": said})
	}
}

// asked replies to something the app-server asked of us.
//
// **Permission is refused, for the reason it is refused on the other family** (FR-013b): a run
// happens with no person watching, and this daemon holds a machine's credentials rather than a
// patron's judgement. Codex's own vocabulary has the right word for it — `decline` means the
// agent is told no and carries on with the turn, which costs it one step and puts a code in the
// record saying exactly what it wanted.
//
// What must never happen here is silence. On this protocol the server has stopped and is
// waiting for an answer, so a request this daemon does not recognise has to be answered with an
// error rather than ignored: an unanswered approval is not a refusal, it is a turn that hangs
// until something else kills it, and from outside that looks like an agent doing nothing.
func (c *appConn) asked(msg rpcMessage) error {
	switch msg.Method {
	case "item/commandExecution/requestApproval", "item/fileChange/requestApproval":
		c.journal.Fail("permission_refused_nobody_to_ask", nil)
		return c.answer(msg.ID, map[string]any{"decision": "decline"})
	case "item/permissions/requestApproval":
		// Answered in the shape it was asked in — a profile of what is granted — and granting
		// nothing. An empty profile is this daemon's refusal written in the server's own terms.
		c.journal.Fail("permission_refused_nobody_to_ask", nil)
		return c.answer(msg.ID, map[string]any{"permissions": map[string]any{}, "scope": "turn"})
	case "mcpServer/elicitation/request":
		c.journal.Fail("permission_refused_nobody_to_ask", nil)
		return c.answer(msg.ID, map[string]any{"action": "decline"})
	}
	return c.out.Encode(rpcMessage{
		JSONRPC: "2.0",
		ID:      msg.ID,
		Error:   &rpcError{Code: -32601, Message: "this client does not provide " + msg.Method},
	})
}

func (c *appConn) answer(id json.RawMessage, result any) error {
	return c.out.Encode(rpcMessage{JSONRPC: "2.0", ID: id, Result: mustRaw(result)})
}
