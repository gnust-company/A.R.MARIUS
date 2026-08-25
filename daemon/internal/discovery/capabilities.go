package discovery

import (
	"context"
	"strings"
)

// capability names one thing the server needs to know about a workplace before it hands it
// work (contracts/daemon-api.md §2).
type capability string

const (
	capResumable         capability = "resumable"
	capExposesToolArgs   capability = "exposes_tool_args"
	capExposesToolResult capability = "exposes_tool_result"
)

// every capability, in the order they are reported. A map alone would report them in a
// different order on every run, and a workplace whose stored capabilities churn on each
// heartbeat looks like a workplace that keeps changing.
var everyCapability = []capability{capResumable, capExposesToolArgs, capExposesToolResult}

// Capabilities is what one CLI answered about itself.
//
// The three booleans are what the server stores. `Unanswered` carries the ones nobody could
// ask — because FR-017 lets a CLI *lack* a capability, but never lets the daemon pretend it
// asked. An unanswered capability travels as `false`, which is the degraded reading, and
// degraded is still supported (FR-039a).
type Capabilities struct {
	Resumable         bool         `json:"resumable"`
	ExposesToolArgs   bool         `json:"exposes_tool_args"`
	ExposesToolResult bool         `json:"exposes_tool_result"`
	Unanswered        []Unanswered `json:"unanswered,omitempty"`
}

// Unanswered is one capability nobody could ask about, and why.
//
// Both fields are codes rather than sentences: the screen builds the sentence through i18n
// (Constitution VI + VII).
type Unanswered struct {
	Capability string `json:"capability"`
	Reason     string `json:"reason"`
}

// Why a capability went unasked.
const (
	// ReasonNoProbe: this build has no way to interrogate a CLI of this protocol family. It
	// is a statement about the daemon, not about the CLI.
	ReasonNoProbe = "no_probe_for_family"
	// ReasonProbeFailed: the CLI was asked and would not answer.
	ReasonProbeFailed = "probe_failed"
)

// selfDescription is how one CLI is asked to describe itself, and which strings in that
// description count as the CLI declaring a capability.
//
// The markers are the *question*, not the answer. What counts as proof is a fact about one
// CLI's own vocabulary; whether the proof is there is decided by what the binary on this
// machine actually printed. That is the whole distinction FR-017 draws — a marker list that
// is wrong or out of date can only ever produce a *false negative*, which is a workplace
// reported as less capable than it is, never one reported as more.
type selfDescription struct {
	args   []string
	proves map[capability][]string
}

// selfDescriptions is the one-shot family's question, per CLI.
//
// Verified against the real binaries on 2026-08-25 where they run:
//   - claude 2.1.226 prints `-r, --resume`, `-c, --continue`, and `--output-format ...
//     "stream-json"`, the streaming form that carries tool calls with their full input and
//     their results.
//   - codex could not be verified: the copy on the development machine is missing its
//     platform binary and will not run at all, so it never reaches a probe. Its markers are
//     read from the published interface and, per the note above, err towards saying less.
var selfDescriptions = map[Kind]selfDescription{
	KindClaudeCode: {
		args: []string{"--help"},
		proves: map[capability][]string{
			capResumable:         {"--resume", "--continue"},
			capExposesToolArgs:   {"stream-json"},
			capExposesToolResult: {"stream-json"},
		},
	},
	KindCodex: {
		args: []string{"--help"},
		proves: map[capability][]string{
			capResumable:         {"resume"},
			capExposesToolArgs:   {"--json"},
			capExposesToolResult: {"--json"},
		},
	},
}

// prober asks one discovered CLI what it can do.
type prober func(ctx context.Context, found Found, opts Options) (Capabilities, error)

// probers is how each protocol family is asked.
//
// A family with no entry here is not a bug and not a lie: its CLIs register with every
// capability unanswered and a code saying so, which is exactly the degraded-but-supported
// state FR-039a describes. The ACP family joins this map when the daemon can speak ACP over
// standard streams — T066 in specs/002-daemon-acp-runtime/tasks.md. Answering for it before
// then would mean guessing, and a guess written into a workplace is indistinguishable from an
// answer once it is stored.
var probers = map[Family]prober{
	FamilyOneShot: probeSelfDescription,
}

// Probe asks one discovered CLI what it can do (FR-017).
//
// It never fails: a CLI that cannot be asked is still a CLI, and the answer is a workplace
// with unanswered capabilities rather than no workplace at all.
func Probe(ctx context.Context, found Found, opts Options) Capabilities {
	opts = opts.withDefaults()

	ask, known := probers[found.Family]
	if !known {
		return unanswered(ReasonNoProbe)
	}
	answered, err := ask(ctx, found, opts)
	if err != nil {
		return unanswered(ReasonProbeFailed)
	}
	return answered
}

// ProbeAll asks every CLI found on this machine, in the order they were found.
func ProbeAll(ctx context.Context, found []Found, opts Options) []Capabilities {
	opts = opts.withDefaults()

	answers := make([]Capabilities, 0, len(found))
	for _, one := range found {
		answers = append(answers, Probe(ctx, one, opts))
	}
	return answers
}

// probeSelfDescription asks a one-shot CLI to describe itself and reads the answer.
//
// There is no handshake in this family — a one-shot CLI is a program that runs and exits, not
// a peer that negotiates — so the interrogation is the one it does support: its own account of
// what it accepts. That is still the binary answering. What is banned is answering from the
// name on the binary (FR-017), and this does not.
func probeSelfDescription(ctx context.Context, found Found, opts Options) (Capabilities, error) {
	question, known := selfDescriptions[found.Kind]
	if !known {
		return unanswered(ReasonNoProbe), nil
	}

	ctx, cancel := context.WithTimeout(ctx, opts.Timeout)
	defer cancel()

	out, err := opts.Run(ctx, found.Path, question.args...)
	if err != nil {
		return Capabilities{}, err
	}
	described := string(out)

	answered := map[capability]bool{}
	for _, want := range everyCapability {
		for _, marker := range question.proves[want] {
			if strings.Contains(described, marker) {
				answered[want] = true
				break
			}
		}
	}
	return Capabilities{
		Resumable:         answered[capResumable],
		ExposesToolArgs:   answered[capExposesToolArgs],
		ExposesToolResult: answered[capExposesToolResult],
	}, nil
}

// unanswered builds the answer for a CLI that could not be asked at all: every capability
// missing, each carrying the same reason.
func unanswered(reason string) Capabilities {
	missing := make([]Unanswered, 0, len(everyCapability))
	for _, want := range everyCapability {
		missing = append(missing, Unanswered{Capability: string(want), Reason: reason})
	}
	return Capabilities{Unanswered: missing}
}
