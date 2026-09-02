// Package discovery finds the agent CLIs installed on this machine and asks each one what it
// can do.
//
// The two halves are deliberately separate files. Finding a CLI is a question about *this
// machine* — is the binary there, and does it run at all. Asking what it can do is a question
// about *the CLI*, and the answer has to come from the binary rather than from its name
// (FR-017): a Claude Code built without `--resume` and one with it share a name and are not
// the same workplace.
package discovery

import (
	"context"
	"fmt"
	"io"
	"os/exec"
	"regexp"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// Kind names one agent CLI the way the server records it, in `workplaces.cli_kind`.
//
// The registry's type rather than this package's. It was declared here once, beside a candidate
// table that repeated the binary name and the protocol family of every CLI — and holding a
// second copy of facts that belong to the kind of CLI, rather than to the act of looking for
// one, is how a kind ends up known under two slightly different descriptions in two files.
type Kind = agentcli.Kind

// Family is how the daemon will talk to a CLI once it runs one: over the ACP protocol, or by
// running it once per turn and reading what it prints. The registry's, for the same reason Kind
// is.
type Family = agentcli.Family

// Found is one agent CLI that is present on this machine and runs.
type Found struct {
	Kind    Kind
	Family  Family
	Path    string
	Version string
}

// Skipped is a binary that is on PATH but would not run.
//
// It exists as its own thing rather than as a Found with a flag because the difference decides
// whether a workplace is offered at all: a CLI that cannot answer `--version` cannot run a
// task either, and registering it would be taking work and failing quietly — the exact thing
// FR-033 forbids.
type Skipped struct {
	Kind Kind
	Path string
	// Reason is a code, never a sentence (Constitution VII).
	Reason string
	Err    error
}

// Reasons a binary that is present is nevertheless not offered as a workplace.
const (
	// ReasonNotRunnable: the binary is on PATH and will not run.
	ReasonNotRunnable = "cli_not_runnable"
)

// Result is everything one sweep of this machine learned.
type Result struct {
	Found   []Found
	Skipped []Skipped
}

// Options are the edges of the outside world, handed in so a test can describe a machine it
// does not have.
type Options struct {
	// LookPath finds a binary on this machine's PATH. Defaults to exec.LookPath.
	LookPath func(binary string) (string, error)
	// Run executes a discovered binary and returns everything it wrote, on either stream.
	// Combined on purpose: a CLI that prints its version to stderr is not a broken CLI.
	Run func(ctx context.Context, path string, args ...string) ([]byte, error)
	// Handshake starts a discovered binary that speaks a protocol and hands the two streams to
	// `talk`, which asks its question and reads the answer. Defaults to startAndTalk.
	//
	// A second edge rather than a shape of the first, because the two ask different things of
	// the program. `Run` waits for a program to finish and hands back what it printed; an ACP
	// peer does not finish — it starts and waits to be spoken to. A probe built on `Run` would
	// start a CLI that is waiting for a question and then wait for it to exit, and both sides
	// would wait until the timeout.
	Handshake func(ctx context.Context, path string, args []string, talk func(to io.Writer, from io.Reader) error) error
	// Timeout bounds one such call. A CLI that hangs on `--version` must not hold up the
	// sweep — the machine still has other CLIs, and the server is waiting to hear about them.
	Timeout time.Duration
}

// defaultTimeout is generous for a program that only has to print its own version, and short
// enough that three hung CLIs still leave the daemon starting inside a minute.
const defaultTimeout = 15 * time.Second

// Discover sweeps this machine for the agent CLIs of this release (FR-002).
//
// Every candidate is looked at; one that is absent is not news and is not reported. One that
// is present but broken *is* news, and travels back in Skipped so the operator can be told
// why their machine offers fewer workplaces than they expected.
func Discover(ctx context.Context, opts Options) Result {
	opts = opts.withDefaults()

	result := Result{}
	for _, c := range agentcli.All() {
		path, err := opts.LookPath(c.Binary)
		if err != nil {
			// Not installed here. The ordinary case for two of the three.
			continue
		}
		version, err := opts.version(ctx, path, c.VersionArgs)
		if err != nil {
			result.Skipped = append(result.Skipped, Skipped{
				Kind:   c.Kind,
				Path:   path,
				Reason: ReasonNotRunnable,
				Err:    err,
			})
			continue
		}
		result.Found = append(result.Found, Found{
			Kind:    c.Kind,
			Family:  c.Family,
			Path:    path,
			Version: version,
		})
	}
	return result
}

// versionPattern matches the first dotted number in whatever a CLI prints about itself, which
// is where every one of them puts its version — `0.56.0`, `2.1.226 (Claude Code)`, and the
// `v1.2.3` some builds prefer all give up the same substring.
var versionPattern = regexp.MustCompile(`\d+\.\d+(?:\.\d+)*`)

// version runs a CLI's own version command and reads the number out of the answer.
//
// A run that fails is an error: it means the binary cannot execute here. An answer with no
// recognisable number is not — the CLI ran, which is what the workplace needs, and an unknown
// version is a blank field rather than a reason to hide a working CLI.
func (o Options) version(ctx context.Context, path string, args []string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, o.Timeout)
	defer cancel()

	out, err := o.Run(ctx, path, args...)
	if err != nil {
		return "", fmt.Errorf("%s %v: %w", path, args, err)
	}
	return versionPattern.FindString(string(out)), nil
}

// withDefaults fills in the edges a caller did not care to supply.
func (o Options) withDefaults() Options {
	if o.LookPath == nil {
		o.LookPath = exec.LookPath
	}
	if o.Run == nil {
		o.Run = runBinary
	}
	if o.Handshake == nil {
		o.Handshake = startAndTalk
	}
	if o.Timeout <= 0 {
		o.Timeout = defaultTimeout
	}
	return o
}

// runBinary executes one of this machine's own agent CLIs.
//
// The path always comes from exec.LookPath over this machine's PATH and the arguments from the
// table above, so there is no caller-supplied string reaching a shell here — and there is no
// shell either.
func runBinary(ctx context.Context, path string, args ...string) ([]byte, error) {
	out, err := exec.CommandContext(ctx, path, args...).CombinedOutput() //nolint:gosec // this machine's own CLI, from PATH, with arguments from the table above
	if err != nil {
		// A CLI that failed usually said why on one of its streams; carrying that back
		// turns "codex is missing" into "codex is missing its platform binary".
		return nil, fmt.Errorf("%w: %s", err, firstLine(out))
	}
	return out, nil
}

// handshakeGrace bounds the tail of a CLI that has been told the conversation is over.
//
// `Wait` does not return while anything still holds the pipes open, and an agent CLI is a program
// that starts programs. Without a bound, one forgotten child turns "ask this CLI what it can do"
// into a daemon that never finishes starting. Short, because by this point the answer is already
// in hand and nothing further is wanted from it.
const handshakeGrace = 3 * time.Second

// startAndTalk starts one of this machine's own CLIs in its protocol and holds a conversation
// with it over its standard streams.
//
// **Its complaints are not the conversation.** gemini 0.56.0 writes a whole authentication
// failure to its error stream — the account this daemon was tested against is refused outright —
// and answers the handshake anyway. A probe that read that stream as failure would report a
// perfectly capable installation as unaskable because somebody's quota ran out.
//
// **The exit status after a completed handshake is not news either.** What was asked was
// answered; a CLI that then exits badly on the way out has not unsaid it. Only a conversation
// that failed is reported as a failure.
func startAndTalk(ctx context.Context, path string, args []string, talk func(to io.Writer, from io.Reader) error) error {
	cmd := exec.CommandContext(ctx, path, args...) //nolint:gosec // this machine's own CLI, found on PATH, with arguments from the registry row
	cmd.Stderr = io.Discard
	cmd.WaitDelay = handshakeGrace

	toAgent, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("speaking to %s: %w", path, err)
	}
	fromAgent, err := cmd.StdoutPipe()
	if err != nil {
		_ = toAgent.Close()
		return fmt.Errorf("listening to %s: %w", path, err)
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("starting %s: %w", path, err)
	}

	asked := talk(toAgent, fromAgent)
	// Closing our end is how an ACP peer is told the conversation is over; it then exits by
	// itself. Ending the process instead would be indistinguishable, from its side, from the
	// machine dying.
	_ = toAgent.Close()
	_ = cmd.Wait()
	return asked
}

// firstLine keeps a failure readable: a broken CLI can print a whole stack trace, and the line
// that says what went wrong is the first one.
func firstLine(out []byte) string {
	for i, b := range out {
		if b == '\n' {
			return string(out[:i])
		}
	}
	if len(out) == 0 {
		return "(no output)"
	}
	return string(out)
}
