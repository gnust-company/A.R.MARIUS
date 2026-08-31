package client

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"text/tabwriter"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/discovery"
)

// The `status` command answers, on the machine itself, what state that machine is in (FR-005a).
//
// It asks the server nothing, and that is the whole point. The Machines screen on the web can
// only ever say a machine has gone *quiet*, and four different things look identical from
// there: the machine is off, the daemon died, the token expired, or the agent CLI was
// uninstalled. Three of those four are only distinguishable from inside the machine, and the
// fourth — the machine being off — is the one case where nobody can run this command at all.
//
// So every answer here comes from three local sources, and none of them is the network:
//
//   - the config file `login` wrote — which server and workspace this machine belongs to;
//   - a state file `start` writes and keeps fresh — the process holding this machine open, and
//     what the server last said about its workplaces;
//   - a live sweep of this machine's PATH — which agent CLIs are here *now*, which is what
//     turns "gemini is registered" plus "gemini is gone" into a visible contradiction.

// stateFile is the name `start` leaves beside the config file. It holds no secret — the token
// stays in the config file — but it is written 0600 anyway, because it names the workspace and
// machine this box belongs to and there is no reason for other accounts to read that.
const stateFile = "state.json"

// RunState is what a running daemon leaves on disk for `status` to read.
type RunState struct {
	PID       int       `json:"pid"`
	StartedAt time.Time `json:"started_at"`
	// Workplaces is the server's own last answer, kept verbatim. `status` must be able to say
	// what the server thinks while the server is unreachable, which is exactly the case where
	// asking it would fail.
	Workplaces []RegisteredWorkplace `json:"workplaces"`
	// LastBeatOKAt and LastBeatError are refreshed every beat. Without them a daemon whose
	// token expired looks identical to a healthy one: the process is up, the workplaces read
	// ready, and nothing at all is reaching the server.
	LastBeatOKAt  time.Time `json:"last_beat_ok_at"`
	LastBeatError string    `json:"last_beat_error"`
	// LeavingAt is written the moment this daemon is told to stop, and it is what turns an
	// upgrade from a race into a handover: the daemon starting up reads it to tell a process
	// that is finishing its last runs from one that intends to keep running (FR-034).
	//
	// It is a moment rather than a flag because the difference between *stopping* and *stopping
	// for the last twenty minutes* is the difference between waiting and investigating, and a
	// boolean cannot say which one an operator is looking at.
	LeavingAt time.Time `json:"leaving_at,omitempty"`
}

// Leaving reports whether the daemon that wrote this state is on its way out.
func (s RunState) Leaving() bool { return !s.LeavingAt.IsZero() }

// ProcessAlive reports whether a process id is still running on this machine.
//
// Exported because the daemon that is starting up has to ask it about the daemon that is
// stopping, and that question is asked from the supervisor rather than from here.
func ProcessAlive(pid int) bool { return processAlive(pid) }

// StatePath is where the state file sits for a given config file — beside it, never inside it.
// The config file is shared with the operator's own settings and is theirs to edit; this one
// is machine-written and churns every beat.
func StatePath(configPath string) string {
	return filepath.Join(filepath.Dir(configPath), stateFile)
}

// SaveState writes the state file, replacing whatever was there.
func SaveState(path string, state RunState) error {
	encoded, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("encoding %s: %w", path, err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("creating %s: %w", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, encoded, 0o600); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	return nil
}

// RemoveState clears the state file on the way out.
//
// A file still present with a process that is gone therefore means something specific: the
// daemon did not shut down in an orderly way. `status` says so rather than only reporting the
// process as absent, because the two have different causes and different fixes.
func RemoveState(path string) { _ = os.Remove(path) }

// LoadState reads the state file. A missing one is not an error: it means no daemon has run on
// this machine since the last clean stop.
func LoadState(path string) (RunState, bool, error) {
	raw, err := os.ReadFile(path) //nolint:gosec // written by this program, beside the operator's own config
	if errors.Is(err, os.ErrNotExist) {
		return RunState{}, false, nil
	}
	if err != nil {
		return RunState{}, false, fmt.Errorf("reading %s: %w", path, err)
	}
	var state RunState
	if err := json.Unmarshal(raw, &state); err != nil {
		return RunState{}, false, fmt.Errorf("%s is not readable as JSON: %w", path, err)
	}
	return state, true, nil
}

// FoundCLI is one agent CLI as this machine sees it right now.
type FoundCLI struct {
	Kind    string `json:"kind"`
	Version string `json:"version"`
	Path    string `json:"path"`
	// Unusable is a code when the binary is here and will not run, and empty otherwise.
	Unusable string `json:"unusable,omitempty"`
	Detail   string `json:"detail,omitempty"`
}

// Status is the whole answer, in the shape `-json` prints it.
type Status struct {
	ConfigPath  string `json:"config_path"`
	Linked      bool   `json:"linked"`
	Server      string `json:"server,omitempty"`
	WorkspaceID string `json:"workspace_id,omitempty"`
	MachineID   string `json:"machine_id,omitempty"`

	DaemonRunning bool `json:"daemon_running"`
	DaemonPID     int  `json:"daemon_pid,omitempty"`
	// The two timestamps are pointers so that "never" is an absent field rather than the year
	// one. `omitzero` would say the same thing in fewer characters, but it arrived in Go 1.24
	// and this module builds from 1.23 — a tag the toolchain does not know is ignored in
	// silence, which is the worst of both.
	StartedAt *time.Time `json:"started_at,omitempty"`
	// StoppedUncleanly is true when a state file was left behind by a process that is gone.
	StoppedUncleanly bool `json:"stopped_uncleanly"`
	// DaemonLeaving is true while the daemon is winding down: it has stopped asking for work
	// and is finishing what it already holds (FR-034). Worth its own answer because a daemon
	// that has been *stopping* for twenty minutes and one that is running normally look the
	// same from every other line of this report.
	DaemonLeaving bool       `json:"daemon_leaving"`
	LeavingAt     *time.Time `json:"leaving_at,omitempty"`
	LastBeatOKAt  *time.Time `json:"last_beat_ok_at,omitempty"`
	LastBeatError string     `json:"last_beat_error,omitempty"`

	CLIs       []FoundCLI            `json:"clis"`
	Workplaces []RegisteredWorkplace `json:"workplaces"`
}

// StatusOptions hands in the edges, so a test can describe a machine it does not have.
type StatusOptions struct {
	ConfigPath string
	// Discovery is passed straight to the sweep; the zero value asks this machine's real PATH.
	Discovery discovery.Options
	// Alive reports whether a process id is still running here. Defaults to the real check.
	Alive func(pid int) bool
	// Now defaults to time.Now.
	Now func() time.Time
}

// Report assembles the answer. It never fails on a machine that is simply not set up: "no
// token here" and "no daemon running" are answers to the question, not errors.
func Report(ctx context.Context, opts StatusOptions) (Status, error) {
	if opts.Alive == nil {
		opts.Alive = processAlive
	}
	if opts.Now == nil {
		opts.Now = time.Now
	}

	status := Status{ConfigPath: opts.ConfigPath}
	if creds, err := LoadCredentials(opts.ConfigPath); err == nil {
		status.Linked = true
		status.Server = creds.Server
		status.WorkspaceID = creds.WorkspaceID
		status.MachineID = creds.MachineID
	}

	state, present, err := LoadState(StatePath(opts.ConfigPath))
	if err != nil {
		// A state file that cannot be read is a real fault, unlike one that is not there.
		return Status{}, err
	}
	if present {
		status.DaemonPID = state.PID
		status.StartedAt = whenSet(state.StartedAt)
		status.LastBeatOKAt = whenSet(state.LastBeatOKAt)
		status.LastBeatError = state.LastBeatError
		status.Workplaces = state.Workplaces
		status.DaemonRunning = opts.Alive(state.PID)
		status.StoppedUncleanly = !status.DaemonRunning
		status.DaemonLeaving = state.Leaving()
		status.LeavingAt = whenSet(state.LeavingAt)
	}
	if status.Workplaces == nil {
		status.Workplaces = []RegisteredWorkplace{}
	}

	swept := discovery.Discover(ctx, opts.Discovery)
	status.CLIs = make([]FoundCLI, 0, len(swept.Found)+len(swept.Skipped))
	for _, found := range swept.Found {
		status.CLIs = append(status.CLIs, FoundCLI{
			Kind:    string(found.Kind),
			Version: found.Version,
			Path:    found.Path,
		})
	}
	for _, broken := range swept.Skipped {
		detail := ""
		if broken.Err != nil {
			detail = broken.Err.Error()
		}
		status.CLIs = append(status.CLIs, FoundCLI{
			Kind:     string(broken.Kind),
			Path:     broken.Path,
			Unusable: broken.Reason,
			Detail:   detail,
		})
	}
	return status, nil
}

// WriteJSON prints the machine-readable half of FR-005a.
func (s Status) WriteJSON(w io.Writer) error {
	encoder := json.NewEncoder(w)
	encoder.SetIndent("", "  ")
	return encoder.Encode(s)
}

// WriteText prints the half a person reads.
func (s Status) WriteText(w io.Writer, now time.Time) {
	if !s.Linked {
		say(w, "Machine:    not linked — run `armarius-daemon login -server <url>` first\n")
		say(w, "Config:     %s\n", s.ConfigPath)
	} else {
		say(w, "Machine:    %s\n", s.MachineID)
		say(w, "Workspace:  %s\n", s.WorkspaceID)
		say(w, "Server:     %s\n", s.Server)
	}

	switch {
	case s.DaemonRunning && s.DaemonLeaving:
		// Not a fault, and said plainly so nobody restarts it on top of itself. This machine
		// is not taking new work and is waiting on the runs it already took (FR-034).
		say(w, "Daemon:     stopping (pid %d, finishing its runs since %s)\n",
			s.DaemonPID, stamp(s.LeavingAt))
	case s.DaemonRunning:
		say(w, "Daemon:     running (pid %d, up since %s)\n", s.DaemonPID, stamp(s.StartedAt))
	case s.StoppedUncleanly && s.DaemonLeaving:
		// It was doing the right thing and was destroyed anyway, which on a service-managed
		// machine usually means the stop timeout is shorter than the runs on this box.
		say(w, "Daemon:     not running — a daemon was killed at %s while it was still stopping\n",
			stamp(s.LeavingAt))
	case s.StoppedUncleanly:
		say(w, "Daemon:     not running — a daemon started %s did not shut down cleanly\n", stamp(s.StartedAt))
	default:
		say(w, "Daemon:     not running\n")
	}
	switch {
	case s.LastBeatError != "":
		// The case the whole command exists for: the process is up and nothing it says is
		// reaching the server.
		say(w, "Last beat:  failing — %s\n", s.LastBeatError)
	case s.LastBeatOKAt != nil:
		say(w, "Last beat:  %s ago\n", now.Sub(*s.LastBeatOKAt).Round(time.Second))
	}

	say(w, "\nAgent CLIs on this machine now:\n")
	if len(s.CLIs) == 0 {
		say(w, "  (none found on PATH)\n")
	}
	table := tabwriter.NewWriter(w, 2, 4, 2, ' ', 0)
	for _, cli := range s.CLIs {
		if cli.Unusable != "" {
			say(table, "  %s\t\t%s\t%s: %s\n", cli.Kind, cli.Path, cli.Unusable, cli.Detail)
			continue
		}
		say(table, "  %s\t%s\t%s\t\n", cli.Kind, cli.Version, cli.Path)
	}
	_ = table.Flush()

	say(w, "\nWorkplaces, as the server last answered:\n")
	if len(s.Workplaces) == 0 {
		say(w, "  (none registered — no daemon has run here yet)\n")
		return
	}
	registered := tabwriter.NewWriter(w, 2, 4, 2, ' ', 0)
	for _, workplace := range s.Workplaces {
		state := "ready"
		if !workplace.Ready {
			state = "not ready (" + workplace.NotReadyReason + ")"
		}
		say(registered, "  %s\t%s\t%s\n", workplace.CLIKind, state, workplace.MachineName)
	}
	_ = registered.Flush()
}

// whenSet turns a timestamp nobody has written yet into an absent one.
func whenSet(at time.Time) *time.Time {
	if at.IsZero() {
		return nil
	}
	return &at
}

// stamp renders a timestamp for a person, saying so plainly when there is none.
func stamp(at *time.Time) string {
	if at == nil {
		return "at an unknown time"
	}
	return at.Format(time.RFC3339)
}
