// Command armarius-daemon is the half of Armarius that lives on the operator's own machine.
//
// The server never reaches in here. It publishes work and this program comes and asks for it.
// That direction is the whole design: a laptop behind a closed lid, a home router or a company
// firewall needs no inbound port for the agents on it to do their jobs.
//
// Three subcommands cover the whole life of a machine:
//
//	login   link this machine to a workspace, once, by approving a code in the browser
//	start   stay up: announce the CLIs found here, ask for work, run it, report back
//	status  say what this machine currently knows about itself, then exit
//
// `start` is where the three roads meet: it says this machine is alive on a beat, holds the push
// road open so it hears about work the moment there is any, asks for that work on its own rhythm
// when nothing has said anything, and runs whatever it is handed.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	gosys "runtime"
	"sync"
	"syscall"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/config"
	"github.com/gnust-company/armarius-daemon/internal/discovery"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
	"github.com/gnust-company/armarius-daemon/internal/runtime"
	"github.com/gnust-company/armarius-daemon/internal/supervisor"
)

// Stamped by the linker when a release is cut; see .goreleaser.yml at the repository root.
var (
	version = "dev"
	commit  = "none"
	date    = "unknown"
)

// A command is one subcommand of armarius-daemon.
//
// out is where the subcommand writes everything a person is meant to read, its own flag usage
// included, so that a test can hand it a buffer instead of a terminal.
type command struct {
	name    string
	summary string
	run     func(ctx context.Context, args []string, out io.Writer) error
}

// commands is the single source of truth for what this program can do: the dispatch in run and
// the help text both read from it, so neither can drift away from the other.
var commands = []command{
	{
		name:    "login",
		summary: "link this machine to a workspace by approving a code in the browser",
		run:     runLogin,
	},
	{
		name:    "start",
		summary: "run the daemon: announce this machine, ask for work, execute it",
		run:     runStart,
	},
	{
		name:    "status",
		summary: "print what this machine knows about itself, then exit",
		run:     runStatus,
	},
}

func main() {
	// A signal cancels the context instead of killing the process outright. `start` will be
	// holding both child CLI processes and a claim on work the server handed out, and each of
	// those has to be given back rather than abandoned.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := run(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		emit(os.Stderr, "armarius-daemon: %v\n", err)
		os.Exit(1)
	}
}

// run is main with its edges handed in, so the whole dispatch is reachable from a test.
func run(ctx context.Context, args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		printUsage(stderr)
		return errors.New("no subcommand given")
	}

	switch args[0] {
	case "help", "-h", "-help", "--help":
		printUsage(stdout)
		return nil
	case "version", "-version", "--version":
		emit(stdout, "armarius-daemon %s (commit %s, built %s)\n", version, commit, date)
		return nil
	}

	for _, c := range commands {
		if c.name == args[0] {
			err := c.run(ctx, args[1:], stdout)
			// `-h` on a subcommand is a request, not a failure: flag has already written the
			// usage out and there is nothing left to report.
			if errors.Is(err, flag.ErrHelp) {
				return nil
			}
			return err
		}
	}

	printUsage(stderr)
	return fmt.Errorf("unknown subcommand %q", args[0])
}

func printUsage(w io.Writer) {
	emit(w, "armarius-daemon runs Armarius agents on this machine.\n\nUsage:\n\n\tarmarius-daemon <command> [flags]\n\nCommands:\n\n")
	for _, c := range commands {
		emit(w, "\t%-8s %s\n", c.name, c.summary)
	}
	emit(w, "\thelp     print this text\n")
	emit(w, "\tversion  print the build this binary was cut from\n\n")
	emit(w, "Run \"armarius-daemon <command> -h\" for the flags of one command.\n")
}

// emit writes text a person is meant to read. A failed write to a terminal or to a pipe that has
// already been closed leaves nothing worth reporting — there is no second stream left to report
// it on — so the error is dropped here, once and on purpose, instead of at every call site.
func emit(w io.Writer, format string, args ...any) {
	_, _ = fmt.Fprintf(w, format, args...)
}

func runLogin(ctx context.Context, args []string, out io.Writer) error {
	fs := newFlagSet("login", out)
	server := fs.String("server", "", "base URL of the Armarius server this machine belongs to")
	config := fs.String("config", defaultConfigPath(), "where to write this machine's token")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *server == "" {
		return errors.New("login: -server is required")
	}
	_, err := client.Login(ctx, client.LoginOptions{
		Server:     *server,
		ConfigPath: *config,
		Platform:   gosys.GOOS,
		Version:    version,
		Out:        out,
	})
	return err
}

// runStart brings this machine online: it works out what it can run, tells the server, and then
// stays up asking for work and running it until it is stopped.
//
// Three loops run at once and none of them owns the others. The beat says this machine is
// reachable (FR-004). The push road carries *there is work, come and ask* (FR-055). The ask loop
// is the one that actually takes work, on its own unhurried rhythm, whether or not anything
// nudged it — which is what makes the push road an optimisation rather than a dependency
// (FR-055d). Losing any one of them degrades this machine; losing all three stops it, and the
// server notices that on its own.
func runStart(ctx context.Context, args []string, out io.Writer) error {
	fs := newFlagSet("start", out)
	configPath := fs.String("config", defaultConfigPath(), "path to this machine's daemon configuration")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *configPath == "" {
		return errors.New("start: -config must not be empty")
	}

	settings, err := config.Load(*configPath)
	if err != nil {
		return err
	}
	creds, err := client.LoadCredentials(*configPath)
	if err != nil {
		return err
	}
	session := client.Session{Server: creds.Server, Token: creds.Token}

	// What this machine can link is established by linking, once, on the disk the daemon's own
	// state lives on — the same filesystem every agent home will be built on (research §5).
	links := execenv.ProbeLinks(ctx, filepath.Dir(*configPath), execenv.LinkOptions{})
	if !links.SymlinkCapable() {
		emit(out, "This machine cannot create symbolic links, so its workplaces will be registered as not ready.\n")
	}

	swept := discovery.Discover(ctx, discovery.Options{})
	for _, broken := range swept.Skipped {
		// A CLI that is installed and will not run is the difference between a machine with two
		// workplaces and one with three, and the operator is the only one who can fix it.
		emit(out, "Skipping %s at %s (%s): %v\n", broken.Kind, broken.Path, broken.Reason, broken.Err)
	}

	reported := make([]client.WorkplaceReport, 0, len(swept.Found))
	for _, found := range swept.Found {
		reported = append(reported, client.WorkplaceReport{
			CLIKind:        string(found.Kind),
			CLIVersion:     found.Version,
			ProtocolFamily: string(found.Family),
			Capabilities:   discovery.Probe(ctx, found, discovery.Options{}),
		})
	}

	registered, err := session.SyncWorkplaces(ctx, client.WorkplacesRequest{
		Workplaces:     reported,
		SymlinkCapable: links.SymlinkCapable(),
	})
	if err != nil {
		return err
	}
	for _, workplace := range registered.Workplaces {
		state := "ready"
		if !workplace.Ready {
			state = "not ready (" + workplace.NotReadyReason + ")"
		}
		emit(out, "%s on %s: %s\n", workplace.CLIKind, workplace.MachineName, state)
	}

	// From here on this machine has a running daemon, and `status` has to be able to say so
	// without asking the server — which is the whole point of it (FR-005a). The state file is
	// written now and refreshed on every beat, so a daemon whose token expired stops looking
	// identical to a healthy one.
	statePath := client.StatePath(*configPath)
	state := client.RunState{
		PID:        os.Getpid(),
		StartedAt:  time.Now(),
		Workplaces: registered.Workplaces,
	}
	if err := client.SaveState(statePath, state); err != nil {
		return err
	}
	// Removed on the way out, so a file still present with no process behind it means one
	// specific thing: the daemon was killed rather than stopped.
	defer client.RemoveState(statePath)

	// What this machine can actually run, keyed the way work arrives: by workplace id. A
	// workplace the server knows about but this daemon cannot drive is left out, and the ask
	// loop below never asks for work there — see runtime.Supported.
	places := workplacesOnThisMachine(registered.Workplaces, swept.Found)
	// Said only for the CLIs this build genuinely cannot drive, and not for a workplace that
	// simply is not ready: one is a gap in this program, the other is a machine reporting
	// honestly about itself, and telling the operator the wrong one sends them to fix the wrong
	// thing.
	for _, workplace := range registered.Workplaces {
		_, canRun := places[workplace.ID]
		if !canRun && workplace.Ready && !runtime.Supported(workplace.CLIKind) {
			emit(out, "Not asking for work on %s: this build cannot drive it yet.\n", workplace.CLIKind)
		}
	}

	// Refused before a single run is asked for, rather than per run. A daemon missing the
	// callback program can still register workplaces, still be handed work, and still start an
	// agent — the agent would simply be holding instructions naming a command that is not there,
	// and every call it made would fail as *command not found*, which nothing on either side
	// reports. Better to be a machine that visibly will not start.
	callback, err := callbackProgram()
	if err != nil {
		return err
	}

	held := &supervisor.Runs{}
	work := supervisor.RunOptions{
		WorkRoot:        filepath.Join(filepath.Dir(*configPath), "work"),
		StateRoot:       filepath.Join(filepath.Dir(*configPath), "stores"),
		OperatorHome:    operatorHome(),
		Server:          creds.Server,
		DaemonToken:     creds.Token,
		CallbackProgram: callback,
		Workplace: func(id string) (supervisor.Workplace, bool) {
			place, known := places[id]
			return place, known
		},
		Runtime: runtimeFor,
		Ledger:  supervisor.Reporting{Session: session},
		Runs:    held,
		Report:  func(err error) { emit(out, "run: %v\n", err) },
	}

	// One buffered slot, deliberately: a nudge already waiting means an ask is already coming,
	// and a second one would only make that ask happen twice (FR-055a).
	nudges := make(chan struct{}, 1)
	var running sync.WaitGroup

	go func() {
		err := session.WatchEvents(ctx, client.WatchOptions{
			Nudge:  nudges,
			Report: func(err error) { emit(out, "push road: %v\n", err) },
		})
		if err != nil && ctx.Err() == nil {
			emit(out, "push road closed: %v\n", err)
		}
	}()

	go func() {
		_ = supervisor.RunClaimLoop(ctx, supervisor.ClaimOptions{
			Interval: settings.PollInterval.Duration(),
			Nudge:    nudges,
			Capacity: func() int { return settings.MaxConcurrentRuns - held.Count() },
			Workplaces: func() []string {
				ids := make([]string, 0, len(places))
				for id := range places {
					ids = append(ids, id)
				}
				return ids
			},
			Claim: func(ctx context.Context, workplaces []string, most int) ([]supervisor.Grant, error) {
				answered, err := session.ClaimRuns(ctx, client.ClaimRequest{
					WorkplaceIDs: workplaces, Max: most,
				})
				if err != nil {
					return nil, err
				}
				return grantsFrom(answered.Runs), nil
			},
			OnGranted: func(ctx context.Context, grant supervisor.Grant) {
				// On its own goroutine: the ask loop is what decides when to ask next, and a
				// machine with room for five runs that stops asking while the first one runs
				// has a ceiling of one.
				running.Add(1)
				go func() {
					defer running.Done()
					work.Do(ctx, grant)
				}()
			},
			Report: func(err error) { emit(out, "asking for work: %v\n", err) },
		})
	}()

	emit(out, "Beating every %s. Stop with Ctrl-C.\n", settings.HeartbeatInterval)
	err = supervisor.RunHeartbeat(ctx, supervisor.HeartbeatOptions{
		Interval: settings.HeartbeatInterval.Duration(),
		State: func() supervisor.Beat {
			// Read fresh on every beat rather than captured once: the free-slot count is the
			// whole reason the beat carries a number (FR-055c).
			return supervisor.Beat{
				FreeSlots: settings.MaxConcurrentRuns - held.Count(),
				Running:   held.IDs(),
			}
		},
		OnReply: func(reply supervisor.Reply) {
			for _, runID := range reply.Cancel {
				// Work this machine reported as running and no longer holds. Its writes would
				// be refused anyway (FR-059); stopping now saves producing them.
				if held.Cancel(runID) {
					emit(out, "Stopping run %s: this machine no longer holds it.\n", runID)
				}
			}
			if reply.PendingWork {
				select {
				case nudges <- struct{}{}:
				default:
				}
			}
		},
		Send: func(ctx context.Context, beat supervisor.Beat) (supervisor.Reply, error) {
			answered, err := session.Beat(ctx, client.BeatRequest{
				FreeSlots: beat.FreeSlots,
				Running:   beat.Running,
			})
			if err != nil {
				state.LastBeatError = err.Error()
			} else {
				state.LastBeatOKAt = time.Now()
				state.LastBeatError = ""
			}
			// A state file that cannot be written is not worth ending a healthy daemon over:
			// the machine is doing its job, and the only thing lost is this machine's own
			// account of it.
			if saveErr := client.SaveState(statePath, state); saveErr != nil {
				emit(out, "could not record this machine's state: %v\n", saveErr)
			}
			if err != nil {
				return supervisor.Reply{}, err
			}
			return supervisor.Reply{
				PendingWork: answered.PendingWork,
				Cancel:      answered.Cancel,
			}, nil
		},
		Report: func(err error) { emit(out, "heartbeat: %v\n", err) },
	})

	// Runs still going when the beat stops are runs this machine is holding, and holding them
	// is a promise. Each one is already being cancelled by the same context that ended the
	// beat; what is waited for here is the last thing each of them does — telling the server
	// how it ended, which is what revokes its token and puts the task back in motion (FR-014b,
	// FR-030a). Abandoning that leaves a run marked *running* on a machine that has exited.
	running.Wait()
	return err
}

// workplacesOnThisMachine pairs what the server now holds with what was actually found here.
//
// The server answers with ids and kinds; the path to the binary and which protocol family it
// belongs to are facts only this machine has. A workplace this build cannot drive is left out
// entirely rather than included and refused later — see runtime.Supported for why that
// distinction is not cosmetic.
func workplacesOnThisMachine(
	registered []client.RegisteredWorkplace, found []discovery.Found,
) map[string]supervisor.Workplace {
	here := make(map[string]discovery.Found, len(found))
	for _, cli := range found {
		here[string(cli.Kind)] = cli
	}

	places := make(map[string]supervisor.Workplace, len(registered))
	for _, workplace := range registered {
		cli, present := here[workplace.CLIKind]
		if !present || !workplace.Ready || !runtime.Supported(workplace.CLIKind) {
			continue
		}
		places[workplace.ID] = supervisor.Workplace{
			CLI:    workplace.CLIKind,
			Family: string(cli.Family),
			Binary: cli.Path,
		}
	}
	return places
}

// runtimeFor answers which protocol family runs a workplace of one kind (FR-035, FR-039).
func runtimeFor(family string) (runtime.Runtime, bool) {
	switch discovery.Family(family) {
	case discovery.FamilyOneShot:
		return runtime.OneShot{}, true
	case discovery.FamilyACP:
		return runtime.ACP{}, true
	default:
		return nil, false
	}
}

// grantsFrom turns what the server handed over into what the supervisor runs.
func grantsFrom(granted []client.GrantedRun) []supervisor.Grant {
	grants := make([]supervisor.Grant, 0, len(granted))
	for _, run := range granted {
		skills := make([]execenv.Skill, 0, len(run.Skills))
		for _, skill := range run.Skills {
			skills = append(skills, execenv.Skill{Name: skill.Name, Files: skill.Files})
		}
		grants = append(grants, supervisor.Grant{
			RunID:          run.RunID,
			TaskID:         run.TaskID,
			ProjectID:      run.ProjectID,
			RuntimeOptions: run.RuntimeOptions,
			WorkplaceID:    run.WorkplaceID,
			RunToken:       run.RunToken,
			Expires:        run.ClaimExpiresAt,
			Prompt:         run.Prompt,
			Skills:         skills,
			FirstSeq:       run.FirstSeq,
		})
	}
	return grants
}

// callbackProgram finds the program agents call Armarius back with (FR-013a).
//
// Next to this daemon, because the two are one release in one archive: that answer survives the
// operator moving the installation, renaming its directory, or keeping two versions side by
// side. Looking it up on the search path would find whichever copy happened to be first there,
// which on a developer's machine is regularly last week's build.
//
// The environment override exists for exactly that case — running a daemon straight out of a
// build directory — and is not a supported way to install: it names a program, not a credential,
// and nothing about it is read from a run.
func callbackProgram() (string, error) {
	if named := os.Getenv("ARMARIUS_CALLBACK_PROGRAM"); named != "" {
		// #nosec G703 -- naming a program is what this variable is for, and it is set by the
		// operator running this daemon, who could as easily have replaced the file itself.
		if _, err := os.Stat(named); err != nil {
			return "", fmt.Errorf("ARMARIUS_CALLBACK_PROGRAM names %s, which is not there: %w", named, err)
		}
		return named, nil
	}
	self, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("finding where this daemon is installed: %w", err)
	}
	beside := execenv.CallbackBeside(self)
	if _, err := os.Stat(beside); err != nil {
		return "", fmt.Errorf(
			"the %s program is not installed beside this daemon (looked at %s): the two ship "+
				"together, and an agent cannot call Armarius back without it: %w",
			execenv.CallbackProgram, beside, err,
		)
	}
	return beside, nil
}

// operatorHome is the real home of the person running this daemon, linked into each run's home
// so an agent finds the CLI credentials they already set up (execenv.Build).
//
// An empty answer is not a failure: a machine with no discoverable home directory simply has no
// operator installation to link to, and every CLI in that state says so far better than this
// program could.
func operatorHome() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return home
}

// runStatus answers, here on this machine, what state this machine is in (FR-005a).
//
// It exits 0 whether or not a daemon is running: "nothing is running here" is the answer to
// the question, not a failure to answer it. What went wrong, if anything, is in the answer.
func runStatus(ctx context.Context, args []string, out io.Writer) error {
	fs := newFlagSet("status", out)
	configPath := fs.String("config", defaultConfigPath(), "path to this machine's daemon configuration")
	asJSON := fs.Bool("json", false, "print the answer as JSON rather than for a person to read")
	if err := fs.Parse(args); err != nil {
		return err
	}

	status, err := client.Report(ctx, client.StatusOptions{ConfigPath: *configPath})
	if err != nil {
		return err
	}
	if *asJSON {
		return status.WriteJSON(out)
	}
	status.WriteText(out, time.Now())
	return nil
}

// newFlagSet builds a flag set that reports errors to out and never calls os.Exit, so that a
// bad flag travels back up as an error like any other failure.
func newFlagSet(name string, out io.Writer) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(out)
	return fs
}

// defaultConfigPath is where `login` leaves the machine token for `start` to pick up. Falling
// back to a relative path keeps the program usable on a machine with no discoverable home
// directory instead of refusing to start over a detail the operator can simply override.
func defaultConfigPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(".armarius", "daemon.json")
	}
	return filepath.Join(home, ".armarius", "daemon.json")
}
