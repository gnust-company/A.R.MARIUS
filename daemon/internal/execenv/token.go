package execenv

import (
	"fmt"
	"path/filepath"
	"sort"
	"strings"
)

// The variables one run's own credentials travel in.
//
// Environment variables rather than a file: the run token is minted for this run and dies with
// it (FR-014), and a file would outlive the process that was meant to be the only thing holding
// it. It also means nothing has to be cleaned up afterwards on a machine we do not own.
const (
	// RunTokenVar carries the token that opens exactly this run and nothing else (FR-014a).
	RunTokenVar = "ARMARIUS_RUN_TOKEN"
	// RunIDVar says which run that token belongs to, so a callback does not have to be told
	// twice what it is answering about.
	RunIDVar = "ARMARIUS_RUN_ID"
	// ServerVar is where that token is spendable. The address travels with the credential
	// because a credential whose audience has to be guessed is one that gets sent somewhere it
	// was never meant to go.
	ServerVar = "ARMARIUS_SERVER"
)

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

// homePointer is one variable that tells a CLI where its home is.
type homePointer struct {
	variable string
	// path is relative to the fake home. Empty means the home itself.
	path string
}

// homePointers is how each CLI is told to look in the home built for this run rather than in the
// operator's real one.
//
// Getting this wrong is not a small mistake: a CLI that keeps reading the operator's own home
// would find their sessions, their configuration and, on a shared workplace, the previous
// agent's leftovers — and everything Build lays out would be laid out beside the point.
//
// Gemini CLI is absent for the same reason it is absent from every other table here: unverified
// (FR-039a, task T013).
var homePointers = map[string][]homePointer{
	"claude_code": {{variable: "HOME"}},
	// Codex keeps authentication, configuration and session state under one directory of its
	// own, and reads CODEX_HOME to find it (research §11.1). HOME is redirected as well, so that
	// anything it does not route through CODEX_HOME still lands inside this run's home.
	"codex": {{variable: "HOME"}, {variable: "CODEX_HOME", path: ".codex"}},
}

// EnvSpec is everything the environment for one run is built out of.
type EnvSpec struct {
	CLI  string
	Home string
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
	pointers, known := homePointers[spec.CLI]
	if !known {
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
		RunTokenVar: spec.Credentials.RunToken,
		RunIDVar:    spec.Credentials.RunID,
		ServerVar:   spec.Credentials.Server,
	}
	for _, p := range pointers {
		target := spec.Home
		if p.path != "" {
			target = filepath.Join(spec.Home, filepath.FromSlash(p.path))
		}
		ours[p.variable] = target
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
