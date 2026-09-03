package callback

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// Group is which kind of run a command belongs to (FR-013d).
//
// Scope is decided by the toolset a run is handed, not by a permission table consulted at call
// time: a run about one task is given the task commands and never sees the project ones. That is
// the layer the agent can *see*, so it does not go wrong. The server refuses out-of-scope writes
// regardless (FR-059), which is the layer the agent cannot get past.
type Group string

const (
	// GroupTask is what a run about one task may do.
	GroupTask Group = "task"
	// GroupProject is what a run about a project may do — the Leader's set.
	GroupProject Group = "project"
	// GroupWorkspace is what a run about neither may do — the team-building interview, which
	// happens before there is a project to be about (FR-040c).
	GroupWorkspace Group = "workspace"
	// GroupAny is the handful that belong to no scope: who am I, and what is on this disk.
	GroupAny Group = "any"
)

// ParamType is the small set of shapes a parameter can have. Small on purpose: every type here
// has to be expressible as a command-line flag *and* as a JSON schema, and the two faces have to
// mean the same thing by it.
type ParamType string

// The shapes a parameter can have. Three, and no more without a reason: each one has to survive
// being a command-line flag *and* a JSON schema property, and mean the same thing as both.
const (
	TypeString  ParamType = "string"
	TypeBoolean ParamType = "boolean"
	TypeInteger ParamType = "integer"
)

// Param is one input to a command, described once and rendered into both faces.
type Param struct {
	Name        string
	Description string
	Type        ParamType
	Required    bool
}

// Args is what a command was called with, whichever face it arrived through.
type Args map[string]any

// String returns a text argument, or "" when it was not given.
func (a Args) String(name string) string {
	switch v := a[name].(type) {
	case nil:
		return ""
	case string:
		return v
	case bool:
		return strconv.FormatBool(v)
	case float64:
		return strconv.FormatFloat(v, 'f', -1, 64)
	default:
		return fmt.Sprint(v)
	}
}

// Bool returns a yes/no argument. Anything unrecognised reads as false, which is the safe way
// round for every flag in this program: they all default to the less consequential answer.
func (a Args) Bool(name string) bool {
	switch v := a[name].(type) {
	case bool:
		return v
	case string:
		parsed, err := strconv.ParseBool(v)
		return err == nil && parsed
	default:
		return false
	}
}

// Int returns a whole-number argument, falling back when it was not given or cannot be read as
// one. A fallback rather than a refusal: every integer in this program is a limit or a count,
// where the sensible default is a better answer than an error about a typo.
func (a Args) Int(name string, fallback int) int {
	switch v := a[name].(type) {
	case int:
		return v
	case float64:
		return int(v)
	case string:
		parsed, err := strconv.Atoi(strings.TrimSpace(v))
		if err != nil {
			return fallback
		}
		return parsed
	default:
		return fallback
	}
}

// Has reports whether the argument was supplied at all, which is not the same as being non-empty
// — an explicitly empty next action is how a task's next action is cleared.
func (a Args) Has(name string) bool {
	_, ok := a[name]
	return ok
}

// Command is one thing an agent can do, described once.
//
// Both faces are built from this: the command line renders Params as flags, MCP renders them as
// a JSON schema, and neither has a list of its own. That is what makes *one thing, two faces*
// structural rather than a promise somebody has to keep.
type Command struct {
	// Name is what the agent types, and — with spaces turned into underscores — the name of the
	// MCP tool. One name, so a transcript of either face reads the same way.
	Name    string
	Group   Group
	Summary string
	Params  []Param
	Call    func(ctx context.Context, c *Client, args Args) (json.RawMessage, error)
}

// ToolName is this command as MCP names it. MCP tool names may not contain spaces.
func (cmd Command) ToolName() string {
	return strings.ReplaceAll(cmd.Name, " ", "_")
}

// Missing lists the required parameters this call did not supply.
func (cmd Command) Missing(args Args) []string {
	var missing []string
	for _, p := range cmd.Params {
		if p.Required && strings.TrimSpace(args.String(p.Name)) == "" {
			missing = append(missing, p.Name)
		}
	}
	return missing
}

// All is every command this program knows, in every scope.
//
// The single list. `Commands` narrows it to one run's scope, the command line dispatches over
// what that returns, and the MCP face declares exactly the same set.
func All() []Command {
	var all []Command
	all = append(all, sharedCommands()...)
	all = append(all, workdirCommands()...)
	all = append(all, taskCommands()...)
	all = append(all, projectCommands()...)
	all = append(all, onboardingCommands()...)
	sort.Slice(all, func(i, j int) bool { return all[i].Name < all[j].Name })
	return all
}

// Commands is what *this* run may do, decided by what the run is about (FR-013d).
//
// A run that names a task gets the task set; one that names only a project gets the Leader's
// set; one that names neither — the team-building interview (FR-040c) — gets the interview's own
// two, and never the other two sets. A task-level run is deliberately **not** given the project
// set: the Leader's tools are not a superset an ordinary worker happens to inherit.
func Commands(env Environment) []Command {
	group := GroupWorkspace
	switch {
	case env.TaskID != "":
		group = GroupTask
	case env.ProjectID != "":
		group = GroupProject
	}
	var mine []Command
	for _, cmd := range All() {
		if cmd.Group == GroupAny || cmd.Group == group {
			mine = append(mine, cmd)
		}
	}
	return mine
}

// Find returns the command with this name, as either face spells it.
func Find(commands []Command, name string) (Command, bool) {
	for _, cmd := range commands {
		if cmd.Name == name || cmd.ToolName() == name {
			return cmd, true
		}
	}
	return Command{}, false
}

// sharedCommands are the ones that belong to no scope because they are about the caller itself.
func sharedCommands() []Command {
	return []Command{
		{
			Name:    "whoami",
			Group:   GroupAny,
			Summary: "Who Armarius thinks you are, and who else is in this workspace.",
			Call: func(ctx context.Context, c *Client, _ Args) (json.RawMessage, error) {
				return c.Call(ctx, "GET", "/agent/me", nil)
			},
		},
	}
}

// taskPath builds a path under the task this run is about, refusing when it is about none.
func taskPath(c *Client, suffix string) (string, error) {
	if c.Env.TaskID == "" {
		return "", fail(ExitUsage, "this run is not about a task, so there is no task to act on")
	}
	return "/agent/tasks/" + c.Env.TaskID + suffix, nil
}

// projectPath is the same for the project this run is about.
func projectPath(c *Client, suffix string) (string, error) {
	if c.Env.ProjectID == "" {
		return "", fail(ExitUsage, "this run is not about a project, so there is no project to act on")
	}
	return "/agent/projects/" + c.Env.ProjectID + suffix, nil
}

// body drops the fields that were never given, so an omitted optional stays omitted rather than
// arriving as an explicit empty string — which the server would read as *set it to nothing*.
func body(args Args, fields ...string) map[string]any {
	out := map[string]any{}
	for _, f := range fields {
		if args.Has(f) {
			out[f] = args[f]
		}
	}
	return out
}
