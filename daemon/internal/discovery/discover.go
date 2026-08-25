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
	"os/exec"
	"regexp"
	"time"
)

// Kind names one agent CLI the way the server records it, in `workplaces.cli_kind`.
type Kind string

// The three CLIs of the first release (research §9). Two protocol families are represented
// from the start on purpose, so the boundary between them is forced to be right early rather
// than discovered later around a single family.
const (
	KindGemini     Kind = "gemini"
	KindClaudeCode Kind = "claude_code"
	KindCodex      Kind = "codex"
)

// Family is how the daemon will talk to a CLI once it runs one: over the ACP protocol, or by
// running it once per turn and reading what it prints.
type Family string

// The two families. A new CLI joins one of them; neither the wake path nor anything above the
// adapter contract learns that either exists (FR-035, FR-037).
const (
	FamilyACP     Family = "acp"
	FamilyOneShot Family = "one_shot"
)

// candidate is one CLI this release knows how to look for.
//
// Nothing here is a capability. It is only *where to look* and *how to ask* — every answer
// comes from the binary itself (FR-017).
type candidate struct {
	kind        Kind
	binary      string
	family      Family
	versionArgs []string
}

// candidates is the whole list of CLIs looked for, in the order they are reported.
var candidates = []candidate{
	{kind: KindGemini, binary: "gemini", family: FamilyACP, versionArgs: []string{"--version"}},
	{kind: KindClaudeCode, binary: "claude", family: FamilyOneShot, versionArgs: []string{"--version"}},
	{kind: KindCodex, binary: "codex", family: FamilyOneShot, versionArgs: []string{"--version"}},
}

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
	for _, c := range candidates {
		path, err := opts.LookPath(c.binary)
		if err != nil {
			// Not installed here. The ordinary case for two of the three.
			continue
		}
		version, err := opts.version(ctx, path, c.versionArgs)
		if err != nil {
			result.Skipped = append(result.Skipped, Skipped{
				Kind:   c.kind,
				Path:   path,
				Reason: ReasonNotRunnable,
				Err:    err,
			})
			continue
		}
		result.Found = append(result.Found, Found{
			Kind:    c.kind,
			Family:  c.family,
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
