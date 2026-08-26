// Package execenv builds the environment an agent CLI expects to find, and takes it away again
// when nobody needs it any more.
package execenv

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

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
	default:
		return fmt.Sprintf("Lifetime(%d)", int(l))
	}
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

// Layout is everything that has to be in place before a CLI of one kind can run.
//
// **There is no shared store here, and that is the point** (FR-007e). Long-term memory is a
// feature some CLIs happen to have, not a concept Armarius provides: a CLI that has one declares
// a PerAgent entry and gets a directory under its own name, and a CLI that has none causes no
// directory to exist at all. Building one memory store for every CLI would take one vendor's
// feature and make it a law of the platform.
//
// Of the three CLIs in the first round, **none declares long-term memory.** That is the expected
// answer, not a gap: adding one later is a line in this table, not a new concept.
var layouts = map[string][]Entry{
	// Claude Code reads its brief from CLAUDE.md and its skills from .claude/skills, both inside
	// the working directory rather than the home. What it needs from home is the operator's own
	// credentials.
	//
	// Keyed by the name the server uses in `workplaces.cli_kind`, which is the name the daemon is
	// told when it is handed work. A shorter name here would mean a lookup that fails at the one
	// moment it matters — a run arriving for a CLI whose home was declared under another spelling.
	"claude_code": {
		{Path: ".claude.json", Lifetime: Operator, Source: ".claude.json"},
		{Path: ".claude", Lifetime: Operator, Source: ".claude"},
		{Path: ".armarius/sessions", Lifetime: PerTask},
	},

	// Codex keeps its authentication, its configuration and its session state together under one
	// home of its own, which is why it gets a home rather than merely borrowing one.
	"codex": {
		{Path: ".codex/auth.json", Lifetime: Operator, Source: ".codex/auth.json"},
		{Path: ".codex/config.toml", Lifetime: Operator, Source: ".codex/config.toml"},
		{Path: ".codex/sessions", Lifetime: PerTask},
		{Path: ".codex/skills", Lifetime: PerRun},
	},

	// Gemini CLI is deliberately absent. Its context file, its skill directory and whether it can
	// resume a session are all unverified, and the spec forbids writing Gemini code before that
	// research is done (FR-039a, task T013). A guessed layout here would be worse than none.
}

// Spec is everything Build needs to know to put one CLI's home in place.
type Spec struct {
	// CLI is the kind of agent CLI this home is for.
	CLI string
	// Home is the fake home directory to build, normally inside the run's working directory.
	Home string
	// StateRoot is where everything that outlives the working directory is kept.
	StateRoot string
	// OperatorHome is the real home directory of the person running the daemon.
	OperatorHome string
	// AgentID and TaskID key the stores that outlive the run.
	AgentID string
	TaskID  string
}

// Home is the result of building one: where it is, and which long-lived stores it reached into.
type Home struct {
	Path string
	// Stores are the directories outside the working tree that this home now links to, listed so
	// the caller can say what it touched and so a test can check nothing else was created.
	Stores []string
}

// Build puts one CLI's home in place.
//
// Anything that outlives the working directory is **linked**, never copied. Multica learned this
// the hard way with session databases: a copy absorbs the run's writes into a file the next run
// throws away, so the conversation silently loses its last turn. A link cannot have that bug.
//
// If a link cannot be created, Build fails. It does **not** quietly fall back to copying — a
// silent fallback would produce exactly the data loss the link was chosen to prevent, and would
// produce it invisibly.
func Build(spec Spec) (Home, error) {
	entries, ok := layouts[spec.CLI]
	if !ok {
		return Home{}, fmt.Errorf("no home layout is declared for %q", spec.CLI)
	}
	if spec.Home == "" || spec.StateRoot == "" {
		return Home{}, fmt.Errorf("building a home for %s needs both a home path and a state root", spec.CLI)
	}

	if err := os.MkdirAll(spec.Home, 0o700); err != nil {
		return Home{}, fmt.Errorf("creating the home for %s: %w", spec.CLI, err)
	}

	built := Home{Path: spec.Home}
	for _, e := range entries {
		target := filepath.Join(spec.Home, filepath.FromSlash(e.Path))
		if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
			return Home{}, fmt.Errorf("creating %s for %s: %w", e.Path, spec.CLI, err)
		}

		switch e.Lifetime {
		case PerRun:
			if err := os.MkdirAll(target, 0o700); err != nil {
				return Home{}, fmt.Errorf("creating %s for %s: %w", e.Path, spec.CLI, err)
			}

		case PerTask, PerAgent:
			store, err := StorePath(spec.StateRoot, spec.CLI, e.Lifetime, spec.AgentID, spec.TaskID)
			if err != nil {
				return Home{}, fmt.Errorf("%s for %s: %w", e.Path, spec.CLI, err)
			}
			if err := os.MkdirAll(store, 0o700); err != nil {
				return Home{}, fmt.Errorf("creating the %s store for %s: %w", e.Lifetime, spec.CLI, err)
			}
			if err := os.Symlink(store, target); err != nil {
				return Home{}, fmt.Errorf("linking %s to its %s store: %w", e.Path, e.Lifetime, err)
			}
			built.Stores = append(built.Stores, store)

		case Operator:
			// An operator who has never run this CLI has nothing for us to link to, and that is
			// not a failure — it is a CLI they have not logged into yet, which the CLI itself
			// will say far better than we can.
			source := filepath.Join(spec.OperatorHome, filepath.FromSlash(e.Source))
			if _, err := os.Lstat(source); err != nil {
				continue
			}
			if err := os.Symlink(source, target); err != nil {
				return Home{}, fmt.Errorf("linking %s to the operator's own %s: %w", e.Path, e.Source, err)
			}
		}
	}

	sort.Strings(built.Stores)
	return built, nil
}

// StorePath is where a long-lived piece of a CLI's home is kept.
//
// Every path starts with the CLI's own name. Two CLIs never share a store even when they store
// the same kind of thing, because the thing they store is theirs, in their own format, with their
// own idea of what it means.
func StorePath(root, cli string, lt Lifetime, agentID, taskID string) (string, error) {
	if root == "" || cli == "" {
		return "", fmt.Errorf("a store needs both a root and a CLI name")
	}
	switch lt {
	case PerTask:
		if taskID == "" {
			return "", fmt.Errorf("a per-task store needs a task")
		}
		return filepath.Join(root, cli, "sessions", taskID), nil
	case PerAgent:
		if agentID == "" {
			return "", fmt.Errorf("a per-agent store needs an agent")
		}
		return filepath.Join(root, cli, "memory", agentID), nil
	case PerRun, Operator:
		return "", fmt.Errorf("%s does not live in a store", lt)
	default:
		return "", fmt.Errorf("unknown lifetime %s", lt)
	}
}

// KnownCLIs lists the CLIs a home can be built for, in a stable order.
func KnownCLIs() []string {
	names := make([]string, 0, len(layouts))
	for cli := range layouts {
		names = append(names, cli)
	}
	sort.Strings(names)
	return names
}
