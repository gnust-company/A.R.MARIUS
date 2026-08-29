package callback

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// How a call ends, as a number the agent's shell can branch on.
//
// The classes are chosen by *what the agent should do next*, which is the only question an exit
// code can usefully answer:
//
//	0  it worked
//	1  Armarius refused — read the message on stdout and do something different
//	2  the command was used wrongly — fix the call itself
//	3  this run cannot call back at all — nobody here can fix it (FR-014f)
//	4  Armarius could not be reached — the same call may well work in a moment
//
// 3 and 4 are apart on purpose. Both look like "it did not go through", and the difference is
// whether trying again is worth anything: a revoked token fails identically every time, and
// retrying it is how a run burns its recovery budget on a wall (FR-014f).
const (
	ExitOK        = 0
	ExitRefused   = 1
	ExitUsage     = 2
	ExitNoRun     = 3
	ExitUnreached = 4
)

// maxAnswer bounds what is read back, for the reason the daemon's own client bounds it: every
// answer here is a short JSON object, and reading an unbounded body is the one way this program
// could be made to exhaust the machine it is a guest on.
const maxAnswer = 1 << 20

// Failure is an error that knows which exit code it deserves.
type Failure struct {
	Code int
	Err  error
	// Body is what the server said, kept so the caller can print the refusal itself rather than
	// a summary of it. Armarius refusals carry a code and its parameters, and an agent that is
	// told only the English sentence cannot branch on which rule said no (FR-084a).
	Body json.RawMessage
}

func (f *Failure) Error() string { return f.Err.Error() }
func (f *Failure) Unwrap() error { return f.Err }

func fail(code int, format string, args ...any) *Failure {
	return &Failure{Code: code, Err: fmt.Errorf(format, args...)}
}

// Client calls Armarius on behalf of one run.
type Client struct {
	Env  Environment
	HTTP *http.Client
}

// NewClient builds the client one run speaks through.
//
// The timeout is here rather than left to the caller because every command in this program is a
// short request against one server, and a call with no deadline is one that can hold an agent
// still for as long as a network is willing to stay silent.
func NewClient(env Environment) *Client {
	return &Client{Env: env, HTTP: &http.Client{Timeout: 30 * time.Second}}
}

// Call makes one request as this run and hands back what the server said.
//
// The answer comes back as raw JSON rather than decoded into something: this program's job is to
// carry an answer to the agent, not to have opinions about its shape, and every field it dropped
// on the way would be a field the agent could not act on.
func (c *Client) Call(ctx context.Context, method, path string, body any) (json.RawMessage, error) {
	if err := c.Env.Usable(); err != nil {
		return nil, &Failure{Code: ExitNoRun, Err: err}
	}

	var payload io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return nil, fail(ExitUsage, "could not encode the request: %w", err)
		}
		payload = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.Env.Server+path, payload)
	if err != nil {
		return nil, fail(ExitUsage, "could not build the request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.Env.RunToken)
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fail(ExitUnreached, "could not reach Armarius at %s: %w", c.Env.Server, err)
	}
	defer func() { _ = resp.Body.Close() }()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxAnswer))
	if err != nil {
		return nil, fail(ExitUnreached, "could not read the answer from Armarius: %w", err)
	}
	if !json.Valid(raw) {
		raw = nil
	}

	switch {
	case resp.StatusCode < 300:
		return raw, nil
	case resp.StatusCode >= 500:
		return nil, &Failure{
			Code: ExitUnreached,
			Err:  fmt.Errorf("Armarius answered %s", resp.Status), //nolint:staticcheck // Armarius is a name, not a sentence opening
			Body: raw,
		}
	case isRunOver(raw):
		// The run this token opened is over, or was never open. Nothing the agent does will
		// change that, and nothing on this machine can mint another one — so this is a person's
		// problem, and saying so is what keeps the recovery ladder off it (FR-014f).
		return nil, &Failure{
			Code: ExitNoRun,
			Err:  fmt.Errorf("this run is no longer open, so Armarius will not take anything from it"),
			Body: raw,
		}
	default:
		return nil, &Failure{
			Code: ExitRefused,
			Err:  fmt.Errorf("Armarius refused: %s", refusalText(raw, resp.Status)), //nolint:staticcheck // Armarius is a name
			Body: raw,
		}
	}
}

// runOverCode is what the server calls a token that opens no run. It reads as *not found* rather
// than *forbidden* on purpose — a dead token and a token that never existed answer identically
// (Constitution I) — so the code, not the status, is what tells this program which of the two
// four-hundreds it is looking at.
const runOverCode = "run_not_found"

type refusal struct {
	Code   string `json:"code"`
	Detail string `json:"detail"`
}

func isRunOver(raw []byte) bool {
	var r refusal
	if len(raw) == 0 || json.Unmarshal(raw, &r) != nil {
		return false
	}
	return r.Code == runOverCode
}

func refusalText(raw []byte, status string) string {
	var r refusal
	if len(raw) > 0 && json.Unmarshal(raw, &r) == nil && r.Detail != "" {
		return r.Detail
	}
	return status
}
