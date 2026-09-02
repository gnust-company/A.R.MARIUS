package discovery

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
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
	// Choices are the settings a person picks per agent, and what this tool takes for each
	// (FR-007k). Absent means this tool was not asked or offers none — which is a workplace
	// whose agents run on the tool's own defaults, not a broken one.
	Choices []Choice `json:"choices,omitempty"`
}

// Choice is one setting a person picks per agent, and the values this tool accepts for it.
//
// **Which settings exist is the tool's answer, not a fixed pair.** Claude Code takes a model
// and an effort level; Codex adds a service tier. Storing two named columns would give the
// third nowhere to go and buy a second migration the day it is asked for, so what travels is a
// list the tool fills in.
//
// `Source` is the honesty field, and it is not decoration: FR-007k bans deciding a tool's
// abilities from the name on its binary, and the way to keep that honest is to say where every
// list came from. A tool that starts enumerating properly moves from one source to another with
// no schema change and no screen change.
type Choice struct {
	// Key names the setting. The screen builds its own label from it (Constitution VI).
	Key string `json:"key"`
	// Values are what this tool takes. Empty means the tool did not say — the person still
	// leaves it blank and gets the tool's own default (FR-007k).
	Values []string `json:"values,omitempty"`
	// Source says how those values were arrived at. A screen that shows a complete set the
	// same way it shows three examples is telling the person something untrue.
	Source string `json:"source"`
}

// The settings a person picks per agent (FR-007k).
const (
	ChoiceModel         = "model"
	ChoiceThinkingLevel = "thinking_level"
)

// Where a list of values came from. Codes, never sentences (Constitution VII).
const (
	// SourceToolDeclared: the tool printed the whole set. Safe to offer as the only options.
	SourceToolDeclared = "tool_declared"
	// SourceToolExamples: the tool named some by way of example and did not claim they are
	// all. Offer them, and let the person type something else.
	SourceToolExamples = "tool_examples"
	// SourceKnownNames: this daemon carries the set for a tool that will not enumerate. The
	// list this may be trusted for is the machine's, not the server's — the server never gets
	// to decide what a CLI can do from its name (FR-017, Điều III).
	SourceKnownNames = "known_names"
)

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
	// ReasonDeclaredAbsent: the CLI was asked, answered, and its own account of itself does not
	// have this. The only one of these that is a fact about the CLI rather than about the asking.
	ReasonDeclaredAbsent = "not_declared"
	// ReasonNotInProtocol: the CLI was asked everything its protocol allows asking, and this
	// capability is not among the things that protocol lets an agent declare.
	//
	// A fourth reason rather than reusing `not_declared`, and the difference is not a nicety.
	// `not_declared` says *this agent has not got this*, which an operator reads as a weaker
	// installation and a reason to look for a newer build. Here the agent was never asked,
	// because there is no field in the handshake to ask with — and no build of any agent in the
	// family will ever answer differently. Saying `not_declared` would be putting a sentence in
	// the agent's mouth about a question nobody put to it.
	//
	// It is also not `no_probe_for_family`: that one says this daemon has no way to interrogate
	// the family, and here it has, and did.
	ReasonNotInProtocol = "not_in_protocol"
)

// Reduced is every capability this workplace does not have, and why it does not have it.
//
// One list rather than two, because the difference between *asked and said no* and *could not
// be asked* changes who should do something about it, not whether the workplace runs. Both are
// the degraded reading FR-017 describes, and FR-039a is explicit that degraded is still
// supported: a workplace missing every one of these is still offered work, and still does it.
//
// What it is for is the other half of that sentence — **degraded, and said out loud**. A
// capability quietly absent is a workplace that behaves differently from its neighbour for a
// reason nobody on this machine was ever told.
func (c Capabilities) Reduced() []Unanswered {
	unasked := make(map[string]string, len(c.Unanswered))
	for _, u := range c.Unanswered {
		unasked[u.Capability] = u.Reason
	}
	answered := map[capability]bool{
		capResumable:         c.Resumable,
		capExposesToolArgs:   c.ExposesToolArgs,
		capExposesToolResult: c.ExposesToolResult,
	}

	var reduced []Unanswered
	for _, want := range everyCapability {
		if answered[want] {
			continue
		}
		reason := ReasonDeclaredAbsent
		if why, never := unasked[string(want)]; never {
			reason = why
		}
		reduced = append(reduced, Unanswered{Capability: string(want), Reason: reason})
	}
	return reduced
}

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
	// offers is what a person may pick per agent, and how to read the accepted values out of
	// the same self-description (FR-007k).
	offers []choiceQuestion
}

// readAs says how the values for one choice are read out of a tool's own account of itself.
type readAs string

const (
	// wholeSet: the tool printed its values as a bare comma-separated list inside brackets —
	// `--effort <level> ... (low, medium, high, xhigh, max)`. That is the tool stating the
	// complete set.
	wholeSet readAs = "whole-set"
	// examples: the tool quoted a few by way of illustration — `(e.g. 'fable', 'opus', or
	// 'sonnet')`. Reading those as the complete set would put words in the tool's mouth.
	examples readAs = "examples"
	// carried: the tool says nothing and this daemon supplies the names.
	carried readAs = "carried"
)

// choiceQuestion is how one pickable setting is asked about.
//
// `after` names the flag the values sit next to, and everything is read out of the **first
// bracketed group following it** — not a window of bytes, which is what an earlier draft of
// this used and which happened to be right only because the help text wrapped where it did.
// Anchoring on the first group is a rule; a byte count is a coincidence waiting to be reflowed.
type choiceQuestion struct {
	key string
	how readAs
	// after is the flag whose bracketed group holds the values. Unused when how is `carried`.
	after string
	// names is the set for `carried`, and is ignored otherwise.
	names []string
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
	agentcli.ClaudeCode: {
		args: []string{"--help"},
		proves: map[capability][]string{
			capResumable:         {"--resume", "--continue"},
			capExposesToolArgs:   {"stream-json"},
			capExposesToolResult: {"stream-json"},
		},
		// Measured on claude 2.1.226, 2026-08-29. Both lists come out of the binary; **no
		// table of model names is carried here**, which is the strongest form of FR-007k this
		// tool allows.
		//
		//   --effort <level>    Effort level for the current session
		//                       (low, medium, high, xhigh, max)
		//
		//   --model <model>     ... Provide an alias for the latest model
		//                       (e.g. 'fable', 'opus', or 'sonnet') ...
		//
		// The effort list is the whole set and is offered as such. The model aliases are the
		// tool's own examples and are offered as examples — a full model name is accepted too,
		// and a screen that presented three suggestions as the only three would be wrong on
		// the day a fourth ships.
		offers: []choiceQuestion{
			{key: ChoiceThinkingLevel, how: wholeSet, after: "--effort"},
			{key: ChoiceModel, how: examples, after: "--model"},
		},
	},
	agentcli.Codex: {
		args: []string{"--help"},
		proves: map[capability][]string{
			capResumable:         {"resume"},
			capExposesToolArgs:   {"--json"},
			capExposesToolResult: {"--json"},
		},
	},
}

// FlagRead answers, for one kind of CLI, which flag each pickable setting's values were read
// out of — `{"thinking_level": "--effort", "model": "--model"}`.
//
// Exported for one reason and it is worth stating: the part that *starts* a CLI has its own
// table saying which flag each setting is spent on, and the two have to be the same flag. Read
// the list off `--effort` and spend it on something else and nothing fails — a person picks a
// value, it applies to nothing, and the screen looks right the whole time. This is what lets a
// test hold the two tables against each other instead of trusting that nobody renamed one.
func FlagRead(kind Kind) map[string]string {
	question, known := selfDescriptions[kind]
	if !known {
		return nil
	}
	flags := map[string]string{}
	for _, offer := range question.offers {
		if offer.after != "" {
			flags[offer.key] = offer.after
		}
	}
	return flags
}

// prober asks one discovered CLI what it can do.
type prober func(ctx context.Context, found Found, opts Options) (Capabilities, error)

// probers is how each protocol family is asked.
//
// A family with no entry here is not a bug and not a lie: its CLIs register with every
// capability unanswered and a code saying so, which is exactly the degraded-but-supported state
// FR-039a describes. Both families of this release are here now; a third one arriving before
// anybody has written its probe would register that way, rather than with guesses.
var probers = map[Family]prober{
	agentcli.FamilyOneShot: probeSelfDescription,
	agentcli.FamilyACP:     probeHandshake,
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
		Choices:           offered(described, question.offers),
	}, nil
}

// bracketedAfter is the first bracketed group following a flag in a tool's self-description.
//
// Anchored on the flag and then on the first `(`, rather than on a window of bytes: help text
// wraps where the terminal says it wraps, and a rule that survives reflowing is the only kind
// worth writing down. Nothing found is an empty string, which every caller reads as *the tool
// did not say* — the same safe direction the marker lists err in.
func bracketedAfter(described, flag string) string {
	rest, found := afterFlag(described, flag)
	if !found {
		return ""
	}
	open := strings.Index(rest, "(")
	if open < 0 {
		return ""
	}
	close := strings.Index(rest[open:], ")")
	if close < 0 {
		return ""
	}
	return rest[open+1 : open+close]
}

// afterFlag is what follows a flag, and only where the flag name actually ends.
//
// Searching for the text alone would find "--model" inside "--model-set" and then read that
// other flag's bracket as this one's answer. What ends a flag name is the character after it,
// so keep looking until one does.
func afterFlag(described, flag string) (string, bool) {
	for at := 0; at < len(described); {
		found := strings.Index(described[at:], flag)
		if found < 0 {
			return "", false
		}
		ends := at + found + len(flag)
		if ends == len(described) || !continuesName(described[ends]) {
			return described[ends:], true
		}
		at = ends
	}
	return "", false
}

func continuesName(c byte) bool {
	return c == '-' || c == '_' ||
		(c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')
}

// wholeSetIn reads a bare comma-separated list, and refuses anything that is not one.
//
// The shape is the check: `low, medium, high` is a list of values, `e.g. 'fable', 'opus'` is a
// sentence about values, and a bracketed aside about anything else is neither. Refusing what
// does not fit means the worst this can do is offer nothing, never offer nonsense as if the
// tool had said it.
var bareValue = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]*$`)

func wholeSetIn(group string) []string {
	parts := strings.Split(group, ",")
	if len(parts) < 2 {
		return nil
	}
	values := make([]string, 0, len(parts))
	for _, part := range parts {
		value := strings.TrimSpace(part)
		if !bareValue.MatchString(value) {
			return nil
		}
		values = append(values, value)
	}
	return values
}

// quoted pulls the tool's own examples out of a bracketed aside.
var quoted = regexp.MustCompile(`'([A-Za-z0-9][A-Za-z0-9._-]*)'`)

func examplesIn(group string) []string {
	var values []string
	for _, found := range quoted.FindAllStringSubmatch(group, -1) {
		values = append(values, found[1])
	}
	return values
}

// offered turns what one tool printed into the settings a person may pick for an agent.
//
// A question that comes back with nothing is **left out entirely** rather than reported with an
// empty list. The two would look alike on a screen and mean opposite things: a setting this
// tool does not have, versus a setting whose values nobody could read. Only the first is true
// here, and only the first should be shown.
func offered(described string, questions []choiceQuestion) []Choice {
	var choices []Choice
	for _, q := range questions {
		var (
			values []string
			source string
		)
		switch q.how {
		case carried:
			values, source = q.names, SourceKnownNames
		case wholeSet:
			values, source = wholeSetIn(bracketedAfter(described, q.after)), SourceToolDeclared
		case examples:
			values, source = examplesIn(bracketedAfter(described, q.after)), SourceToolExamples
		}
		if len(values) == 0 {
			continue
		}
		choices = append(choices, Choice{Key: q.key, Values: values, Source: source})
	}
	return choices
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

// ── the ACP family: ask the agent, in the agent's own protocol ────────────────

// acpDeclaration is what an ACP agent says about itself when the conversation opens.
//
// **One field of the three is in here, and that is the finding rather than an omission.** An ACP
// agent declares `loadSession` and nothing that answers whether it shows the arguments a tool was
// called with, or what that tool gave back. Those two are not properties an agent declares at all
// in this protocol: they travel per tool call, in `session/update`, and the run path already reads
// each one on its own merits — an update carrying no `rawInput` is recorded as *this CLI did not
// say*, never as *the tool was called with nothing* (FR-047).
//
// So the honest answer for those two is neither true nor false but `not_in_protocol`, and the
// place that must not be tempted is right here: writing `true` for them because ACP agents
// generally do send tool calls would be exactly the guess FR-017 forbids, dressed as a reading.
type acpDeclaration struct {
	// ProtocolVersion is what the agent will actually speak. Read but not acted on, the same way
	// the run path reads it: the two must at least agree in that, so that the day one of them
	// starts refusing a version the other accepts, the difference is visible here.
	ProtocolVersion   int `json:"protocolVersion"`
	AgentCapabilities struct {
		LoadSession bool `json:"loadSession"`
	} `json:"agentCapabilities"`
}

// probeHandshake asks an ACP CLI what it can do by opening the conversation it was built for.
//
// This is the strongest form of FR-017 available anywhere in this daemon: not a marker read out
// of help text, but the agent's own declaration, in its own protocol, from the binary installed
// on this machine. Two builds of the same CLI can answer differently, and the workplace follows
// the one that is about to do the work.
//
// **The price is a process start.** A sweep already runs every CLI once for its version; an ACP
// CLI is now started twice. Measured against gemini 0.56.0 on 2026-09-02: the handshake answers
// in about 3.5s and the process exits by itself about 0.2s after its input is closed. That is
// paid once, when the daemon starts, and it buys a workplace that carries conversations on
// instead of losing them.
func probeHandshake(ctx context.Context, found Found, opts Options) (Capabilities, error) {
	row, known := agentcli.Lookup(string(found.Kind))
	if !known || len(row.ProtocolArgs) == 0 {
		// A CLI of this family with nothing to start it with cannot be spoken to — and that is a
		// fact about what has been written down here, not about the CLI.
		return unanswered(ReasonNoProbe), nil
	}

	ctx, cancel := context.WithTimeout(ctx, opts.Timeout)
	defer cancel()

	var declared acpDeclaration
	err := opts.Handshake(ctx, found.Path, row.ProtocolArgs, func(to io.Writer, from io.Reader) error {
		return openConversation(ctx, to, from, &declared)
	})
	if err != nil {
		return Capabilities{}, err
	}
	return Capabilities{
		Resumable: declared.AgentCapabilities.LoadSession,
		Unanswered: []Unanswered{
			{Capability: string(capExposesToolArgs), Reason: ReasonNotInProtocol},
			{Capability: string(capExposesToolResult), Reason: ReasonNotInProtocol},
		},
	}, nil
}

// openConversation puts the one question a probe has to the agent, and reads its answer.
//
// **It introduces this client exactly as the run path does**, and that is the whole reason the
// answer is worth anything. What a peer declares, it declares in reply to what it was told about
// its counterpart; asked as one client and then run as another, what is stored against the
// workplace is an answer to a question nobody asks again.
func openConversation(ctx context.Context, to io.Writer, from io.Reader, into *acpDeclaration) error {
	const askID = 1
	if err := json.NewEncoder(to).Encode(map[string]any{
		"jsonrpc": "2.0",
		"id":      askID,
		"method":  "initialize",
		"params": map[string]any{
			"protocolVersion": agentcli.ACPVersion,
			// The same words the run path opens with: this client offers the agent no file
			// access and no terminal of its own (FR-013a).
			"clientCapabilities": map[string]any{
				"fs": map[string]any{"readTextFile": false, "writeTextFile": false},
			},
		},
	}); err != nil {
		return fmt.Errorf("asking the agent to introduce itself: %w", err)
	}

	lines := bufio.NewScanner(from)
	lines.Buffer(make([]byte, 0, 8<<10), maxHandshakeLine)
	for lines.Scan() {
		if err := ctx.Err(); err != nil {
			return err
		}
		line := lines.Bytes()
		if len(line) == 0 || line[0] != '{' {
			// CLIs print banners. A line that is not a JSON object cannot be the answer, and
			// stopping at one would fail a probe over a greeting.
			continue
		}
		var msg struct {
			ID     json.RawMessage `json:"id"`
			Result json.RawMessage `json:"result"`
			Error  *struct {
				Code    int    `json:"code"`
				Message string `json:"message"`
			} `json:"error"`
		}
		if json.Unmarshal(line, &msg) != nil || string(msg.ID) != strconv.Itoa(askID) {
			// Notifications, and answers to questions nobody asked. An agent may say several
			// things before it answers, and none of them is what was asked for.
			continue
		}
		if msg.Error != nil {
			return fmt.Errorf("the agent refused to introduce itself: %s (%d)",
				msg.Error.Message, msg.Error.Code)
		}
		if err := json.Unmarshal(msg.Result, into); err != nil {
			return fmt.Errorf("reading what the agent said about itself: %w", err)
		}
		return nil
	}
	if err := lines.Err(); err != nil {
		return fmt.Errorf("listening for the agent: %w", err)
	}
	return fmt.Errorf("the agent stopped talking without introducing itself")
}

// maxHandshakeLine bounds the one line a probe reads. Far smaller than the bound a run uses: a
// run carries whatever an agent writes, and this carries an introduction — gemini 0.56.0's is
// under a kilobyte. A bound generous enough for a run would let a CLI that answers with a
// gigabyte of nonsense take the daemon down at startup.
const maxHandshakeLine = 256 << 10
