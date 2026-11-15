package discovery

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os/exec"
	"strings"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// Asking a CLI whether anybody is signed in to it (FR-007r).
//
// *Ready* used to mean one thing: the binary answered `--version`. That is true of a CLI whose
// sign-in lapsed a week ago, and a workplace like that takes work and fails every run at its
// first line — measured 2026-11-11, with the Machines screen reading *ready* throughout. The
// question the screen is really asking has a cheaper answer than a failed run: the CLI knows
// whether it is signed in, and says so without starting a turn.

// SignIn is what a CLI said when it was asked.
//
// Three values, and the third is the one that matters. A CLI that cannot be asked — it has no
// such command, the command failed to start, the answer was not the shape that was measured —
// is *unknown*, and unknown is reported as nothing at all. Reading it as signed out would close
// a working workplace on a guess; reading it as signed in would be claiming something nobody
// checked.
type SignIn int

const (
	// SignInUnknown means the CLI was not asked, or its answer could not be read.
	SignInUnknown SignIn = iota
	// SignedIn means the CLI said somebody is signed in.
	SignedIn
	// SignedOut means the CLI said nobody is.
	SignedOut
)

// Reported is the answer as it travels to the server: true, false, or left out.
func (s SignIn) Reported() *bool {
	switch s {
	case SignedIn:
		yes := true
		return &yes
	case SignedOut:
		no := false
		return &no
	default:
		return nil
	}
}

// String is for this daemon's own log.
func (s SignIn) String() string {
	switch s {
	case SignedIn:
		return "signed in"
	case SignedOut:
		return "signed out"
	default:
		return "sign-in unknown"
	}
}

// AskSignIn asks one discovered CLI whether anybody is signed in to it.
//
// It never fails, for the same reason Probe never does: a CLI that cannot be asked is still a
// CLI, and the answer is *unknown* rather than no workplace.
func AskSignIn(ctx context.Context, found Found, opts Options) SignIn {
	opts = opts.withDefaults()

	row, known := agentcli.Lookup(string(found.Kind))
	if known && row.SignInMethod != "" {
		return askOverProtocol(ctx, found, opts, row.SignInMethod)
	}
	if !known || len(row.SignInArgs) == 0 || row.SignInCommand == "" {
		return SignInUnknown
	}
	// The binary's own help has to list the command first (see agentcli.CLI.SignInCommand).
	// Asked every time rather than remembered: a CLI updates itself under a running daemon.
	helpCtx, helped := context.WithTimeout(ctx, opts.Timeout)
	help, err := opts.Run(helpCtx, found.Path, "--help")
	helped()
	if err != nil || !listsCommand(string(help), row.SignInCommand) {
		return SignInUnknown
	}

	ctx, cancel := context.WithTimeout(ctx, opts.Timeout)
	defer cancel()

	said, err := opts.Answer(ctx, found.Path, row.SignInArgs...)
	if err != nil {
		return SignInUnknown
	}
	// A pointer, so that an object without the field is told apart from one that says false.
	var answer struct {
		LoggedIn *bool `json:"loggedIn"`
	}
	if json.Unmarshal(said, &answer) != nil || answer.LoggedIn == nil {
		return SignInUnknown
	}
	if *answer.LoggedIn {
		return SignedIn
	}
	return SignedOut
}

// acpAuthRequired is the protocol's own code for *nobody is signed in* (`auth_required`).
const acpAuthRequired = -32000

// terminalAuth is the kind of sign-in a person completes in a terminal of their own.
const terminalAuth = "terminal"

// askOverProtocol asks an ACP agent whether anybody is signed in, in the agent's own protocol
// (FR-007t).
//
// For the CLIs that have no command to ask with. The conversation is opened the way a probe
// opens it, and then the agent is sent `authenticate` for the method its row names. Measured on
// kimi 2.5.3, 2026-11-15: an empty result in a signed-in home, `-32000 Authentication required`
// in a home nobody had signed in to, each in under a tenth of a second, with no session opened
// and no file written.
//
// **`authenticate` is not a question on every agent**, and that is what the two checks before it
// are for. On one that signs in through this client it may well begin a sign-in. So it is sent
// only for a method the row names — a row that names one has had this measured — and only when
// the agent's own handshake lists that method as one a person completes in a terminal: an agent
// that sends a person to a terminal to sign in has nothing left for `authenticate` to do but
// say whether they did. A binary that stops listing it is not asked, and is reported as unknown.
func askOverProtocol(ctx context.Context, found Found, opts Options, method string) SignIn {
	if len(found.ProtocolArgs) == 0 {
		return SignInUnknown
	}
	ctx, cancel := context.WithTimeout(ctx, opts.Timeout)
	defer cancel()

	answer := SignInUnknown
	_ = opts.Handshake(ctx, found.Path, found.ProtocolArgs, func(to io.Writer, from io.Reader) error {
		talk := newACPTalk(to, from)
		var declared acpDeclaration
		if err := talk.introduce(ctx, &declared); err != nil {
			return err
		}
		if !declared.signsInAtATerminal(method) {
			return nil
		}
		_, err := talk.ask(ctx, "authenticate", map[string]any{"methodId": method})
		var refused acpRefusal
		switch {
		case err == nil:
			answer = SignedIn
		case errors.As(err, &refused) && refused.Code == acpAuthRequired:
			answer = SignedOut
		}
		// Any other refusal, a pipe that broke, a timeout: the agent was not heard to say
		// either thing, and *unknown* is the only answer that claims nothing.
		return nil
	})
	return answer
}

// signsInAtATerminal says whether the agent itself lists this method, as a terminal sign-in.
func (d acpDeclaration) signsInAtATerminal(method string) bool {
	for _, listed := range d.AuthMethods {
		if listed.ID == method && listed.Type == terminalAuth {
			return true
		}
	}
	return false
}

// listsCommand reads a CLI's help for a command of this name: a line whose first word it is.
//
// The first word of a line and nothing looser. Claude Code's help mentions "auth" in the
// description of three unrelated options, and a search for the word anywhere would find the
// command in a build that does not have it.
func listsCommand(help, command string) bool {
	for _, line := range strings.Split(help, "\n") {
		fields := strings.Fields(line)
		if len(fields) > 1 && fields[0] == command {
			return true
		}
	}
	return false
}

// answerOf runs one of this machine's own CLIs and returns what it printed, **whatever its
// exit status**.
//
// Not `runBinary`, which treats a bad exit as a CLI that will not run. Here the bad exit is
// half of the answer: Claude Code prints `"loggedIn": false` and exits 1, and a caller that
// threw the output away on a non-zero status could only ever hear *yes*.
func answerOf(ctx context.Context, path string, args ...string) ([]byte, error) {
	out, err := exec.CommandContext(ctx, path, args...).Output() //nolint:gosec // this machine's own CLI, from PATH, with arguments from the registry row
	var exited *exec.ExitError
	if err != nil && !errors.As(err, &exited) {
		// It did not run at all, or was cut off by the timeout.
		return nil, err
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	return out, nil
}
