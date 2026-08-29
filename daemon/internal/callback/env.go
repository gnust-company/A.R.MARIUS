// Package callback is the one thing an agent calls Armarius back with, and both of its faces.
//
// A run cannot reach the server directly: the credential that opens it is minted per run and
// dies with it (FR-014), and nothing about it is the agent's to configure. So the daemon hands
// the run a program that already knows where to call and what to call with, and the agent simply
// runs it.
//
// **One thing, two faces** (FR-013a). The same list of commands is offered twice:
//
//   - as a plain command line, which every agent CLI can run, including the ones with no way to
//     load tools at all. This is the baseline: no CLI is left out.
//   - as an MCP server over stdio, declared per run, for the CLIs that do load tools.
//
// They are two faces and not two installations. Two installations are two lists of what an agent
// can do, and they drift apart on the day somebody adds a command to one of them — so both are
// generated from `Commands()` below, and `mcp_test.go` fails if a face is ever built from
// anything else.
package callback

import (
	"fmt"
	"os"
	"strings"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// Environment is what a run was told about itself, read from the environment and nowhere else.
type Environment struct {
	Server   string
	RunToken string
	RunID    string
	// TaskID and ProjectID are empty when this run is not about one (FR-013d). Empty is a real
	// answer here, not a missing value: a Leader's run has no task, and the interview has
	// neither.
	TaskID    string
	ProjectID string
}

// Lookup is how the environment is read, handed in so a test does not have to mutate the
// process's own. Normally os.Getenv.
type Lookup func(string) string

// FromEnvironment reads what this run was given.
//
// **The credential comes from the environment and from nothing else** (FR-013c). Not from a
// flag, not from a file, not from a prompt. Two reasons, and each one is enough on its own:
// FR-043 records the arguments of every tool call *in full*, so a credential in an argument is a
// credential written into the server's own record of the run; and on the machine itself, every
// other process belonging to the same user can read anybody's command line.
func FromEnvironment(get Lookup) Environment {
	if get == nil {
		get = os.Getenv
	}
	return Environment{
		Server:    strings.TrimRight(get(execenv.ServerVar), "/"),
		RunToken:  get(execenv.RunTokenVar),
		RunID:     get(execenv.RunIDVar),
		TaskID:    get(execenv.TaskIDVar),
		ProjectID: get(execenv.ProjectIDVar),
	}
}

// Usable reports whether this environment can reach the server at all, and says what is missing
// when it cannot.
func (e Environment) Usable() error {
	var missing []string
	if e.Server == "" {
		missing = append(missing, execenv.ServerVar)
	}
	if e.RunToken == "" {
		missing = append(missing, execenv.RunTokenVar)
	}
	if len(missing) == 0 {
		return nil
	}
	return fmt.Errorf(
		"this run was not given %s, so it cannot call Armarius back",
		strings.Join(missing, " or "),
	)
}

// looksLikeACredential is the shape of a run token, used only to recognise one where it must
// never appear.
const looksLikeACredential = "armr_run_"

// RefuseCredentialsInArguments fails when a credential was passed on the command line.
//
// The rule it enforces is FR-013c, and it is enforced rather than merely documented because the
// cost of a slip is permanent: the arguments of this call are recorded whole (FR-043), and a
// token written into a record cannot be taken out of it again. Redaction (FR-048) is a safety
// net for what escapes by surprise, not a place to lean on for a leak that is designed in.
//
// Two things are refused. A flag that asks to carry a credential is refused even when empty,
// because accepting the flag at all is how the habit starts. A value that has the shape of a run
// token is refused wherever it appears, which catches the agent that passed one without a flag.
func RefuseCredentialsInArguments(args []string) error {
	for _, arg := range args {
		name := strings.TrimLeft(arg, "-")
		if before, _, found := strings.Cut(name, "="); found {
			name = before
		}
		switch strings.ToLower(name) {
		case "token", "run-token", "runtoken", "auth", "authorization", "bearer":
			return fmt.Errorf(
				"%s takes no credential: the run token is read from %s, never from an argument",
				arg, execenv.RunTokenVar,
			)
		}
		if strings.Contains(arg, looksLikeACredential) {
			return fmt.Errorf(
				"refusing an argument that carries a run token — it is read from %s, and an "+
					"argument is written into this run's record in full",
				execenv.RunTokenVar,
			)
		}
	}
	return nil
}
