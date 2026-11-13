package discovery

import (
	"context"
	"encoding/json"
	"errors"
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
