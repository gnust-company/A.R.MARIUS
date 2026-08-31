package execenv

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// The variables one run's own credentials travel in.
//
// Environment variables rather than a file: the run token is minted for this run and dies with
// it (FR-014), and a file would outlive the process that was meant to be the only thing holding
// it. It also means nothing has to be cleaned up afterwards on a machine we do not own.
const (
	// RunTokenVar carries the token that opens exactly this run and nothing else (FR-014a).
	// The name of a variable, not a secret: what goes in it is minted per run by the server.
	RunTokenVar = "ARMARIUS_RUN_TOKEN" //nolint:gosec // a variable's name, not a credential
	// RunIDVar says which run that token belongs to, so a callback does not have to be told
	// twice what it is answering about.
	RunIDVar = "ARMARIUS_RUN_ID"
	// ServerVar is where that token is spendable. The address travels with the credential
	// because a credential whose audience has to be guessed is one that gets sent somewhere it
	// was never meant to go.
	ServerVar = "ARMARIUS_SERVER"
)

// The two identifiers a run is about, when it is about them (FR-013d).
//
// Neither is a credential and neither decides anything on the server's side: the run token
// already says which task and which project this run may touch. What they decide is here — the
// set of commands the callback program offers this agent. They are also why the agent never
// passes an identifier of its own: one it had to go looking for is one it could find somebody
// else's copy of.
//
// Which of them is set is what says what kind of run this is: both for a task-level run, only
// the project for a Leader's, neither for the team-building interview (FR-040c).
const (
	TaskIDVar    = "ARMARIUS_TASK_ID"
	ProjectIDVar = "ARMARIUS_PROJECT_ID"
)

// WorkDirVar names the task's working directory (FR-010).
//
// The agent is started in it, so most of the time this says what the agent could have worked out
// for itself. It is told anyway because the one command that needs it — what have I changed here
// (FR-020a) — is asked after the agent has been working, by which point it may be anywhere: a
// build ran in a subdirectory, a repository was cloned and entered. Answering *what changed*
// about wherever the process happens to be standing would answer a different question, quietly.
const WorkDirVar = "ARMARIUS_WORKDIR"

// searchPathIn finds the search path in an inherited environment and answers under which name it
// was spelled there.
//
// The name matters as much as the value. Windows spells it Path as often as PATH and treats the
// two as one variable, so adding our own PATH beside an inherited Path would leave the child
// holding two spellings of one thing; everywhere else they are two different variables and only
// one of them means anything, so matching loosely would capture a variable that is not the
// search path at all.
func searchPathIn(inherited []string) (name, value string) {
	for _, entry := range inherited {
		n, v, ok := strings.Cut(entry, "=")
		if !ok {
			continue
		}
		if n == "PATH" || (runtime.GOOS == "windows" && strings.EqualFold(n, "PATH")) {
			return n, v
		}
	}
	return "PATH", ""
}

// Credentials is what a run is allowed to speak with, and what it must never be given.
type Credentials struct {
	RunID    string
	RunToken string
	Server   string

	// DaemonToken is this machine's own token, and it is passed in **so that it can be kept
	// out**. It speaks for the whole machine — every workplace on it and every agent bound to
	// them — while a run token opens one run, so handing it to an agent turns one compromised
	// run into every run this machine will ever hold (FR-014c). Optional: a caller that does not
	// supply it loses the scrub, not the rest of the guarantee.
	DaemonToken string
}

// EnvSpec is everything the environment for one run is built out of.
type EnvSpec struct {
	CLI  string
	Home string
	// TaskID and ProjectID are what this run is about, and either may be empty (FR-013d).
	// They are not credentials and they decide nothing on the server's side — the run token
	// already says what this run may touch. What they decide is on *this* side: which
	// commands the callback program offers the agent. Leaving them out is not a smaller
	// version of setting them; it is telling the agent this run is about nothing, and the
	// whole task and project command sets vanish without a word.
	TaskID    string
	ProjectID string
	// WorkDir is the task's working directory, and ToolsDir is the directory inside it holding
	// the callback program (FR-013a). ToolsDir goes to the **front** of the search path: the
	// agent is told to call Armarius back by a bare name, and a name resolved from anywhere else
	// on a machine we do not own is a different program answering to it.
	WorkDir  string
	ToolsDir string
	// Inherited is the environment this daemon is running in, normally os.Environ(). It is
	// passed in rather than read here so a test can hand over an environment that contains the
	// things this function exists to remove.
	Inherited   []string
	Credentials Credentials
}

// Environ builds the environment one run's CLI is started with (FR-014, FR-014c).
//
// **A missing run token is a refusal, not a fallback.** Minting is the server's job and it can
// fail; when it does, the answer is to give the run back and let it be handed out again, never
// to start the agent with some other credential that happens to be lying around. Multica put
// that rule in writing only after falling into it (MUL-3292), and the shape of the fall is worth
// keeping in mind: nothing looks wrong at the time, because the agent runs perfectly well with a
// token that is too powerful.
//
// The daemon's own token is then scrubbed out of what is inherited, by value. Refusing to *add*
// it is the easy half and would be enough if environments only ever contained what this function
// put there; an operator who exported their token to run a one-off command has one in theirs,
// and the child would inherit it without a single line of this code being wrong.
func Environ(spec EnvSpec) ([]string, error) {
	// Getting this wrong is not a small mistake: a CLI still reading the operator's own home
	// would find their sessions, their configuration and, on a shared workplace, the previous
	// agent's leftovers — so a kind the registry declares no variables for is refused rather
	// than started with everything laid out beside the point.
	row, known := agentcli.Lookup(spec.CLI)
	if !known || len(row.HomeVars) == 0 {
		return nil, fmt.Errorf("no home variables are declared for %q", spec.CLI)
	}
	if spec.Home == "" {
		return nil, fmt.Errorf("building the environment for %s needs a home to point it at", spec.CLI)
	}
	if spec.Credentials.RunToken == "" {
		return nil, fmt.Errorf("refusing to start %s without a token of this run's own", spec.CLI)
	}
	if spec.Credentials.DaemonToken != "" && spec.Credentials.RunToken == spec.Credentials.DaemonToken {
		return nil, fmt.Errorf("refusing to start %s: the run was handed this machine's own token", spec.CLI)
	}

	ours := map[string]string{
		RunTokenVar:  spec.Credentials.RunToken,
		RunIDVar:     spec.Credentials.RunID,
		ServerVar:    spec.Credentials.Server,
		TaskIDVar:    spec.TaskID,
		ProjectIDVar: spec.ProjectID,
		WorkDirVar:   spec.WorkDir,
	}
	if spec.ToolsDir != "" {
		name, inheritedPath := searchPathIn(spec.Inherited)
		ours[name] = spec.ToolsDir
		if inheritedPath != "" {
			ours[name] = spec.ToolsDir + string(os.PathListSeparator) + inheritedPath
		}
	}
	for _, p := range row.HomeVars {
		target := spec.Home
		if p.Path != "" {
			target = filepath.Join(spec.Home, filepath.FromSlash(p.Path))
		}
		ours[p.Variable] = target
	}

	env := make([]string, 0, len(spec.Inherited)+len(ours))
	for _, entry := range spec.Inherited {
		name, value, ok := strings.Cut(entry, "=")
		if !ok {
			continue
		}
		if _, mine := ours[name]; mine {
			// Whatever this said, it was not about this run. A stale value here is the one that
			// would be hardest to notice, because everything downstream would still find a
			// token where it expected one.
			continue
		}
		if spec.Credentials.DaemonToken != "" && strings.Contains(value, spec.Credentials.DaemonToken) {
			continue
		}
		env = append(env, entry)
	}

	added := make([]string, 0, len(ours))
	for name, value := range ours {
		if value == "" {
			// A variable set to nothing is worse than an absent one: code that checks for
			// presence finds it, and code that checks for a value does not.
			continue
		}
		added = append(added, name+"="+value)
	}
	sort.Strings(added)
	return append(env, added...), nil
}
