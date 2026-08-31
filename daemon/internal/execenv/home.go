// Package execenv builds the environment an agent CLI expects to find, and takes it away again
// when nobody needs it any more.
package execenv

import (
	"fmt"
	"os"
	"path"
	"path/filepath"
	"sort"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// Lifetime says how long one piece of a CLI's home is meant to last.
//
// The registry's type, along with the layouts that use it: how long a CLI's session state has to
// survive is a fact about that CLI. What lives here is the putting of it in place, which is this
// package's whole job.
type Lifetime = agentcli.Lifetime

// Entry is one path inside the fake home a CLI is given for a run. The registry's, with Lifetime.
type Entry = agentcli.Entry

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
	row, known := agentcli.Lookup(spec.CLI)
	if !known || len(row.Home) == 0 {
		return Home{}, fmt.Errorf("no home layout is declared for %q", spec.CLI)
	}
	entries := row.Home
	if spec.Home == "" || spec.StateRoot == "" {
		return Home{}, fmt.Errorf("building a home for %s needs both a home path and a state root", spec.CLI)
	}

	if err := os.MkdirAll(spec.Home, 0o700); err != nil {
		return Home{}, fmt.Errorf("creating the home for %s: %w", spec.CLI, err)
	}

	built := Home{Path: spec.Home}
	ours := claimedPaths(entries)
	for _, e := range entries {
		target := filepath.Join(spec.Home, filepath.FromSlash(e.Path))
		if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
			return Home{}, fmt.Errorf("creating %s for %s: %w", e.Path, spec.CLI, err)
		}

		switch e.Lifetime {
		case agentcli.PerRun:
			if err := os.MkdirAll(target, 0o700); err != nil {
				return Home{}, fmt.Errorf("creating %s for %s: %w", e.Path, spec.CLI, err)
			}

		case agentcli.PerTask, agentcli.PerAgent:
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

		case agentcli.Operator:
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

		case agentcli.OperatorTree:
			if err := linkTheirChildren(spec, e, target, ours); err != nil {
				return Home{}, err
			}
		}
	}

	sort.Strings(built.Stores)
	return built, nil
}

// claimedPaths is every path inside this home that the layout says is ours.
//
// Read once, before anything is built, so that an OperatorTree entry gives the same answer
// wherever it sits in the table. A rule that depended on the order of two lines would be a rule
// the next person reorders by accident.
func claimedPaths(entries []Entry) map[string]bool {
	claimed := make(map[string]bool, len(entries))
	for _, e := range entries {
		if e.Lifetime != agentcli.OperatorTree {
			claimed[path.Clean(e.Path)] = true
		}
	}
	return claimed
}

// linkTheirChildren links each child of one of the operator's directories into the fake home,
// leaving out the names this layout has claimed.
//
// An operator with no such directory is skipped in silence, for the same reason a missing
// Operator file is: it is a CLI they have not logged into yet, and the CLI says so far better
// than we could. The directory is still created — the names we own live inside it.
func linkTheirChildren(spec Spec, e Entry, target string, ours map[string]bool) error {
	if err := os.MkdirAll(target, 0o700); err != nil {
		return fmt.Errorf("creating %s for %s: %w", e.Path, spec.CLI, err)
	}
	source := filepath.Join(spec.OperatorHome, filepath.FromSlash(e.Source))
	children, err := os.ReadDir(source)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("reading the operator's own %s: %w", e.Source, err)
	}
	for _, child := range children {
		if ours[path.Join(e.Path, child.Name())] {
			continue
		}
		link := filepath.Join(target, child.Name())
		// Ours may already be here if it was built first. Whoever declared it wins: this
		// branch only ever adds what the operator has and we did not ask for.
		if _, err := os.Lstat(link); err == nil {
			continue
		}
		if err := os.Symlink(filepath.Join(source, child.Name()), link); err != nil {
			return fmt.Errorf("linking %s to the operator's own %s: %w",
				path.Join(e.Path, child.Name()), path.Join(e.Source, child.Name()), err)
		}
	}
	return nil
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
	case agentcli.PerTask:
		if taskID == "" {
			return "", fmt.Errorf("a per-task store needs a task")
		}
		return filepath.Join(root, cli, "sessions", taskID), nil
	case agentcli.PerAgent:
		if agentID == "" {
			return "", fmt.Errorf("a per-agent store needs an agent")
		}
		return filepath.Join(root, cli, "memory", agentID), nil
	case agentcli.PerRun, agentcli.Operator:
		return "", fmt.Errorf("%s does not live in a store", lt)
	default:
		return "", fmt.Errorf("unknown lifetime %s", lt)
	}
}

// KnownCLIs lists the CLIs a home can be built for, in a stable order.
//
// A kind the registry knows of but declares no home layout for is left out, and that is the
// point of asking rather than listing: the sweep that reclaims stores walks this, and a kind
// with no layout has no store for it to walk.
func KnownCLIs() []string {
	var names []string
	for _, row := range agentcli.All() {
		if len(row.Home) > 0 {
			names = append(names, string(row.Kind))
		}
	}
	sort.Strings(names)
	return names
}
