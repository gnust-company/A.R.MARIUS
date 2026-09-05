// Package agentcli is what this daemon knows about each kind of agent CLI, one row per kind.
//
// It exists because of a promise made above it. FR-037 says that adding a kind of agent CLI
// touches the bottom layer and nothing else, and that was true of every layer except this one:
// which file a CLI reads its brief out of, which directory it looks in for skills, what its
// home has to hold, which variable points at that home, what binary to look for and under which
// protocol family — each of those lived in a table of its own, in a file of its own. Adding one
// CLI meant finding all of them, and a table missed is not a compile error. It is a daemon that
// starts, registers the workplace, runs the agent, and hands it an empty brief.
//
// What is deliberately **not** here is the acting. Building a home is execenv's, starting a CLI
// is runtime's, deciding when one has gone quiet for too long is the watchdog's. A row is a
// fact; what to do about it belongs to whoever does it.
//
// Nor is any capability here, and that one is a rule rather than a preference. FR-017 says what
// a CLI can do is answered by the binary installed on this machine — never by the name of it in
// a table — so a `resumable: true` in this file would be precisely the table FR-017 exists to
// forbid. Those answers come from discovery's probe, and they are about one installation on one
// machine rather than about a kind of tool.
package agentcli

import "time"

// Kind is a kind of agent CLI, spelled the way the server spells it in `workplaces.cli_kind`.
//
// The server's spelling and no other. This is the name a run arrives under, so a shorter or
// prettier name here would be a lookup that fails at the one moment it matters.
type Kind string

// The kinds of the first release (research §9).
const (
	Gemini     Kind = "gemini"
	ClaudeCode Kind = "claude_code"
	Codex      Kind = "codex"
)

// Family is how the daemon talks to a CLI once it runs one.
type Family string

// The three families. A new CLI joins one of them; neither the wake path nor anything above the
// adapter contract learns that any of them exists (FR-035, FR-037).
//
// Two of the three speak JSON-RPC down the same pipes, and they are still two families rather
// than one: a shared wire format is not a shared vocabulary. An ACP peer and a Codex app-server
// share not one method name between them, so a client that knew only "JSON-RPC over stdio"
// would be a client that could open the pipe and then say nothing either side understood.
const (
	// FamilyACP holds a JSON-RPC conversation over its own standard streams.
	FamilyACP Family = "acp"
	// FamilyOneShot is run once per turn and prints an account of what it did.
	FamilyOneShot Family = "one_shot"
	// FamilyAppServer holds a JSON-RPC conversation in Codex's own vocabulary: a thread is
	// opened, a turn is started, and the work arrives as notifications until the turn is
	// declared over (FR-039d).
	FamilyAppServer Family = "app_server"
)

// ACPVersion is the version of the Agent Client Protocol this daemon speaks.
//
// It sits beside the family rather than inside whoever uses it because **two** parts of this
// daemon open an ACP conversation: the one that asks a CLI what it can do, and the one that runs
// a turn. What a peer declares about itself is declared *for a protocol version*, so an answer
// obtained under one version is only an answer about the run if the run speaks the same one.
// Two constants would let that stop being true without anything failing.
const ACPVersion = 1

// Lifetime says how long one piece of a CLI's home is meant to last.
type Lifetime int

const (
	// PerRun is written fresh for every run and dies with the working directory. Skills are the
	// clearest case: they are regenerated each time so a stale copy can never be picked up.
	PerRun Lifetime = iota

	// PerTask outlives each run but belongs to one task. Session state lives here, so the next
	// wake on the same task carries on the same conversation (FR-023) even though the run that
	// started it is long gone.
	PerTask

	// PerAgent outlives every task the agent ever works on. This is where a CLI's long-term
	// memory would live — for the CLIs that have such a thing.
	PerAgent

	// Operator points into the operator's own installation: the credentials and configuration
	// they set up themselves. We link to it so the agent does not have to log in again, and we
	// never write it and never delete it.
	Operator

	// OperatorTree is the operator's own directory linked in **child by child** rather than
	// whole, so that a few names inside it can be ours.
	//
	// The direction is the point. Everything the operator has becomes visible by default, and
	// the only names left out are the ones this layout declares a path for — so a file the
	// vendor adds next release is theirs without anybody editing this table, while the session
	// store stays on our side of the line. Linking the whole directory is simpler and is what
	// this did before; it also meant every session a CLI wrote landed in the operator's real
	// home, where no retention of ours could ever reach it (FR-027).
	OperatorTree
)

func (l Lifetime) String() string {
	switch l {
	case PerRun:
		return "per-run"
	case PerTask:
		return "per-task"
	case PerAgent:
		return "per-agent"
	case Operator:
		return "operator"
	case OperatorTree:
		return "operator-tree"
	default:
		return "lifetime(" + itoa(int(l)) + ")"
	}
}

// itoa keeps this package free of fmt, which is worth a few lines: a table of facts that
// imports a formatter invites sentences into it, and sentences are the one thing a table of
// codes must not grow (Constitution VII).
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var digits [20]byte
	at := len(digits)
	for n > 0 {
		at--
		digits[at] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		at--
		digits[at] = '-'
	}
	return string(digits[at:])
}

// Entry is one path inside the fake home a CLI is given for a run.
type Entry struct {
	// Path is where the CLI expects to find it, relative to the fake home.
	Path string
	// Lifetime decides whether it is a real directory in the working tree or a link out to
	// something that outlives it.
	Lifetime Lifetime
	// Source is the path inside the operator's real home that an Operator entry points at.
	// Meaningless for every other lifetime.
	Source string
}

// Skills is where one CLI looks for skills, and which directory that path hangs off.
type Skills struct {
	Path string
	// InHome is true when the CLI looks under its home rather than under the working directory.
	// Not a detail: the working directory belongs to one task, the home is built for one run,
	// and putting skills in the wrong one changes how long they live.
	InHome bool
}

// EnvVar is one variable a CLI needs set that is not about where its home is.
//
// Kept apart from HomeVars because the two answer different questions and fail differently. A
// home pointer aimed wrong sends a CLI to read somebody else's installation; one of these
// missing turns a feature off. Both are facts about the CLI, and neither is a credential —
// nothing here may carry a secret, which is why it is a plain pair rather than a lookup.
type EnvVar struct {
	Name  string
	Value string
}

// HomeVar is one variable that tells a CLI where its home is.
type HomeVar struct {
	Variable string
	// Path is relative to the fake home. Empty means the home itself.
	Path string
}

// CLI is everything this daemon knows about one kind of agent CLI.
type CLI struct {
	Kind   Kind
	Family Family

	// Binary is the name to look for on the search path, and VersionArgs is how it is asked
	// which version it is. Neither is a capability: they are where to look and how to ask, and
	// every answer comes from the binary itself (FR-017).
	Binary      string
	VersionArgs []string

	// ProtocolArgs is what this CLI is started with to make it speak its family's protocol
	// rather than talk to a person. Empty for the one-shot family, which has no protocol to be
	// switched into — such a CLI is handed a message and prints an account of what it did.
	//
	// Not a capability either, for the reason above: this is how to address the binary, and
	// everything the binary then says about itself is its own (FR-017). It is here rather than
	// beside the code that starts a run because both halves of the ACP road need it — the probe
	// that asks a CLI what it can do has to start it the same way the run will, or it is asking
	// a different program than the one that gets the work.
	ProtocolArgs []string

	// ContextFile is the file this CLI opens of its own accord at the start of a session.
	//
	// This is the whole of Multica's trick and the reason the daemon writes a file instead of
	// sending a message: **do not teach the agent a new way to be told things**. The brief goes
	// where the agent already looks, so it needs to know nothing about Armarius to receive it.
	ContextFile string

	// Skills is where this CLI goes looking for skills of its own accord — same principle as
	// the context file: write where it already looks.
	Skills Skills

	// Home is everything that has to be in place before a CLI of this kind can run.
	//
	// **There is no shared store here, and that is the point** (FR-007e). Long-term memory is a
	// feature some CLIs happen to have, not a concept Armarius provides: a CLI that has one
	// declares a PerAgent entry and gets a directory under its own name, and a CLI that has
	// none causes no directory to exist at all. Building one memory store for every CLI would
	// take one vendor's feature and make it a law of the platform. Of the three kinds below,
	// **none declares long-term memory**, which is the expected answer rather than a gap.
	Home []Entry

	// HomeVars is how this CLI is told to look in the home built for this run rather than in
	// the operator's real one.
	//
	// Getting this wrong is not a small mistake: a CLI that keeps reading the operator's own
	// home would find their sessions, their configuration and, on a shared workplace, the
	// previous agent's leftovers — and everything laid out for the run would be laid out beside
	// the point.
	HomeVars []HomeVar

	// Env is what this CLI needs set beyond being pointed at its home.
	//
	// Ordered rather than a map, so the environment a run is started with is the same twice for
	// the same CLI: a run that cannot be reproduced from its own record is a run nobody can
	// debug.
	Env []EnvVar

	// Silence is how long a run on this kind of CLI may say nothing before it is treated as
	// hung, when that differs from the machine's own threshold. Zero means the machine's.
	//
	// It may only ever be **tighter** than the base, and the watchdog enforces that rather than
	// trusting it (FR-031a): no CLI's entry may switch off the safety net covering every CLI.
	//
	// **Every row leaves this at zero today, and that is the correct content.** A tighter
	// threshold is a claim about how long a particular tool goes quiet while still working, and
	// nobody has measured that for any of these. A number invented here would end runs that
	// were fine, which is the one failure the base threshold is generous precisely to avoid.
	Silence time.Duration
}

// The facts a row has to carry before a run can be set up on that kind of CLI. Codes, never
// sentences: whoever reports one builds the sentence in the reader's own language
// (Constitution VI, Constitution VII).
const (
	FactContextFile = "context_file"
	FactSkillsDir   = "skills_dir"
	FactHomeLayout  = "home_layout"
	FactHomeVars    = "home_vars"
	// FactProtocolArgs is asked of the families that hold a conversation. A one-shot CLI has
	// nothing to switch into, so an empty ProtocolArgs is the right content there and a
	// missing fact here.
	FactProtocolArgs = "protocol_args"
)

// rows is the whole table, in the order machines report their workplaces in.
//
// The order is part of the contract, not an accident of how a map iterates: two heartbeats that
// disagree about the order of the same three workplaces look like a machine whose CLIs keep
// changing.
var rows = []CLI{
	// Gemini CLI. **Every line below was read off the binary installed on a machine, not off a
	// web page** — `gemini 0.56.0`, 2026-08-31, `daemon/scripts/probe-gemini-acp.mjs` plus the
	// bundle it ships (see research §9.2). That distinction is the whole of FR-039a: what is
	// forbidden is guessing, not writing.
	//
	// What the probe reached, and what it did not, matters for reading this row. The ACP
	// handshake **completed** with the process started by another program and no terminal, and
	// Gemini declared its own capabilities in it — so the failure this row was held back for,
	// a daemon waiting forever on a handshake that was never coming, is measured not to happen.
	// What could not be reached was a prompt: Google refuses this account outright
	// (`IneligibleTierError`, `UNSUPPORTED_CLIENT` on the individual free tier). So the four
	// paths below are read from the shipped source rather than watched being used, and the day
	// a working account exists they are the first thing to check.
	{
		Kind:        Gemini,
		Family:      FamilyACP,
		Binary:      "gemini",
		VersionArgs: []string{"--version"},
		// `--acp` rather than `--experimental-acp`: the binary's own help calls the older
		// spelling deprecated and names this one. Both were measured to work, so the older one
		// remains the fallback if a build ever refuses this.
		ProtocolArgs: []string{"--acp"},
		// `"GEMINI.md"` and `contextFileName` in the bundle. Project-level, in the working
		// directory, which is why the trust variable below is not optional.
		ContextFile: "GEMINI.md",
		// The **personal** skills directory, inside the home, rather than the project one.
		// Both exist; this one is read without asking anybody's permission, while the project
		// directory sits behind the same trust gate the brief does. The home is built fresh for
		// each run, so it also gives skills the lifetime they should have had anyway — and one
		// agent's skills cannot be sitting there when the next agent runs (FR-007b).
		Skills: Skills{Path: ".gemini/skills", InHome: true},
		Home: []Entry{
			// Child by child, so the operator's login comes along and the two directories
			// Gemini writes into stay ours — same reason Claude Code's `.claude` is linked
			// this way (T109).
			{Path: ".gemini", Lifetime: OperatorTree, Source: ".gemini"},
			// `~/.gemini/tmp/<project>/chats/session-*.jsonl` is where a conversation lives,
			// which makes it the thing FR-023 carries between wakes and FR-027 ages out.
			// Measured: the probe left one there under its own workspace name.
			{Path: ".gemini/tmp", Lifetime: PerTask},
			// Command history. Kept out of the operator's real home deliberately and not kept
			// at all: it is the agent's typing, not theirs, and nothing reads it back.
			{Path: ".gemini/history", Lifetime: PerRun},
			{Path: ".gemini/skills", Lifetime: PerRun},
		},
		// HOME and nothing else. `GEMINI_DIR` is a **constant** in the bundle rather than a
		// variable it reads, so there is no second lever here: redirect the home or reach
		// nothing.
		HomeVars: []HomeVar{{Variable: "HOME"}},
		// The gate the probe found, and the reason a row filled in without it would have been
		// the silent failure this table exists to prevent. Gemini will not read project-level
		// configuration out of a folder nobody has trusted — and the daemon makes a fresh
		// folder for every task, which nobody ever has. Untrusted, it says so on its error
		// stream and carries on with the brief unread.
		//
		// The variable is checked before the on-disk list (`checkPathTrust` in the bundle), so
		// it settles the question without editing a file the operator owns.
		Env: []EnvVar{{Name: "GEMINI_CLI_TRUST_WORKSPACE", Value: "true"}},
	},

	// Claude Code reads its brief from CLAUDE.md and its skills from .claude/skills, both
	// inside the working directory rather than the home. What it needs from home is the
	// operator's own credentials.
	{
		Kind:        ClaudeCode,
		Family:      FamilyOneShot,
		Binary:      "claude",
		VersionArgs: []string{"--version"},
		ContextFile: "CLAUDE.md",
		Skills:      Skills{Path: ".claude/skills"},
		Home: []Entry{
			{Path: ".claude.json", Lifetime: Operator, Source: ".claude.json"},
			// Child by child, not whole, and `projects` is the reason (T109). Claude Code keeps
			// a task's transcript in `$HOME/.claude/projects/<the working directory, escaped>`,
			// so while `.claude` was one link out to the operator's real home every session
			// this daemon ever opened was written there and stayed there: `.armarius/sessions`
			// was declared per-task and nobody wrote it, the sweep swept an empty directory,
			// and the fourteen-day keeping in FR-027 was never once applied to Claude Code.
			{Path: ".claude", Lifetime: OperatorTree, Source: ".claude"},
			{Path: ".claude/projects", Lifetime: PerTask},
		},
		HomeVars: []HomeVar{{Variable: "HOME"}},
	},

	// Codex keeps its authentication, its configuration and its session state together under
	// one home of its own, which is why it gets a home rather than merely borrowing one, and
	// reads CODEX_HOME to find it (research §11.1). HOME is redirected as well, so that
	// anything it does not route through CODEX_HOME still lands inside this run's home.
	{
		Kind:   Codex,
		Family: FamilyAppServer,
		Binary: "codex",
		// `app-server` is Codex's own interface for programs rather than people, and stdio is
		// its default transport: newline-delimited JSON-RPC 2.0 down the pipes this daemon
		// already owns. Named in full anyway rather than relying on the default, because a
		// default is a thing that changes without anybody's release note.
		ProtocolArgs: []string{"app-server", "--listen", "stdio://"},
		VersionArgs:  []string{"--version"},
		ContextFile:  "AGENTS.md",
		Skills:       Skills{Path: ".codex/skills", InHome: true},
		Home: []Entry{
			{Path: ".codex/auth.json", Lifetime: Operator, Source: ".codex/auth.json"},
			{Path: ".codex/config.toml", Lifetime: Operator, Source: ".codex/config.toml"},
			{Path: ".codex/sessions", Lifetime: PerTask},
			{Path: ".codex/skills", Lifetime: PerRun},
		},
		HomeVars: []HomeVar{{Variable: "HOME"}, {Variable: "CODEX_HOME", Path: ".codex"}},
	},
}

// index is the same rows, reachable by the name a run arrives under.
var index = func() map[Kind]CLI {
	byKind := make(map[Kind]CLI, len(rows))
	for _, row := range rows {
		byKind[row.Kind] = row
	}
	return byKind
}()

// All is every kind this daemon knows of, in the order workplaces are reported in.
func All() []CLI {
	all := make([]CLI, len(rows))
	copy(all, rows)
	return all
}

// Lookup is the row for one kind, by the name the server spells it with.
func Lookup(kind string) (CLI, bool) {
	row, known := index[Kind(kind)]
	return row, known
}

// Undeclared is what a row leaves blank of the facts a run needs, as codes.
//
// A kind nobody has heard of leaves all of them blank, which is the same answer as a row with
// nothing filled in — and it should be. Both mean the same thing to whoever asked: there is
// nothing here to set a run up from.
func Undeclared(kind string) []string {
	row, known := Lookup(kind)
	if !known {
		return []string{FactContextFile, FactSkillsDir, FactHomeLayout, FactHomeVars}
	}
	return row.Undeclared()
}

// Undeclared is what this row leaves blank of the facts a run needs, as codes.
func (c CLI) Undeclared() []string {
	var missing []string
	if c.ContextFile == "" {
		missing = append(missing, FactContextFile)
	}
	if c.Skills.Path == "" {
		missing = append(missing, FactSkillsDir)
	}
	if len(c.Home) == 0 {
		missing = append(missing, FactHomeLayout)
	}
	if len(c.HomeVars) == 0 {
		missing = append(missing, FactHomeVars)
	}
	// A conversational row with nothing to start the CLI with is the same shape of silent
	// failure as a row with no context file: the machine registers the workplace, asks for
	// work, wins a run, and only then finds it has no way to make the binary speak a protocol.
	if c.Family != FamilyOneShot && len(c.ProtocolArgs) == 0 {
		missing = append(missing, FactProtocolArgs)
	}
	return missing
}

// Ready says whether a run can be set up on this kind at all.
//
// Not the same question as *is it installed* — that one is discovery's, and its answer is what
// the machine reports as a workplace (FR-002). This one is about what has been written down
// here, and every row of this release now answers yes.
//
// It matters because of what a machine does with the answer. Asking for work at a workplace
// this daemon cannot set up wins a run that fails during setup, and a run that fails during
// setup goes back on the shelf and is offered to the same machine again (FR-007, FR-056a) —
// forever, a slot at a time. Not asking leaves the task where it is, which is visibly stuck
// rather than invisibly churning.
func Ready(kind string) bool {
	return len(Undeclared(kind)) == 0
}

// Silences is every per-CLI silence threshold that differs from the machine's own, keyed the
// way a run arrives. Empty today, and the comment on CLI.Silence says why.
func Silences() map[string]time.Duration {
	thresholds := map[string]time.Duration{}
	for _, row := range rows {
		if row.Silence > 0 {
			thresholds[string(row.Kind)] = row.Silence
		}
	}
	return thresholds
}
