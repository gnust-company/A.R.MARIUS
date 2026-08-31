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
	"syscall"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
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

	// Before a single workplace is registered. A daemon that is on its way out is still holding
	// runs and is still going to hand its workplaces back when it is done — registering on top
	// of that would double this machine's slots for the length of the drain and then be undone
	// by the outgoing daemon's goodbye (FR-034, FR-005).
	statePath := client.StatePath(*configPath)
	err = supervisor.WaitForPredecessor(ctx, supervisor.HandoverOptions{
		Read:     func() (client.RunState, bool, error) { return client.LoadState(statePath) },
		Self:     os.Getpid(),
		Patience: supervisor.HandoverPatience(settings.DrainPatience.Duration()),
		Waiting: func(pid int) {
			emit(out, "Waiting for the daemon already on this machine (process %d) to finish its runs.\n", pid)
		},
	})
	if err != nil {
		return err
	}

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

	// Kept as well as sent. What a CLI answered about itself decides how this machine runs it —
	// a workplace that cannot carry a conversation on must not be handed a handle to carry one
	// (FR-017) — and until now the answer went to the server and nowhere else, so every
	// workplace on this machine was driven as though it had said yes to everything.
	answers := make(map[string]discovery.Capabilities, len(swept.Found))
	reported := make([]client.WorkplaceReport, 0, len(swept.Found))
	for _, found := range swept.Found {
		answered := discovery.Probe(ctx, found, discovery.Options{})
		answers[string(found.Kind)] = answered
		reported = append(reported, client.WorkplaceReport{
			CLIKind:        string(found.Kind),
			CLIVersion:     found.Version,
			ProtocolFamily: string(found.Family),
			Capabilities:   answered,
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
		// Degraded, and said out loud (FR-017, FR-039a). A capability missing is not a broken
		// workplace and does not stop work being offered here — but it does mean this workplace
		// behaves differently from its neighbour, and an operator who is never told that has no
		// way to tell a CLI that cannot resume from one that keeps losing its thread.
		for _, missing := range answers[workplace.CLIKind].Reduced() {
			emit(out, "  %s runs without %s (%s), which is supported and does less.\n",
				workplace.CLIKind, missing.Capability, missing.Reason)
		}
	}

	// From here on this machine has a running daemon, and `status` has to be able to say so
	// without asking the server — which is the whole point of it (FR-005a). The state file is
	// written now and refreshed on every beat, so a daemon whose token expired stops looking
	// identical to a healthy one.
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
	places := workplacesOnThisMachine(registered.Workplaces, swept.Found, answers)
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

	// Built here rather than left to the supervisor's own default, and that is the whole of
	// T119: the watchdog has always been able to take a threshold of each CLI's own, and until
	// now nothing ever handed it one — every CLI on every machine ran on the base, and the
	// tighten-only rule guarded a table nobody filled in.
	watchdog, err := silenceWatchdog(agentcli.Silences())
	if err != nil {
		return err
	}
	// A threshold pulled back to the base is said, never quietly applied. A CLI whose entry
	// asked for more room than the base allows is a machine running under a rule its operator
	// does not think is in force (FR-031a).
	for _, pulled := range watchdog.Loosened() {
		emit(out, "%s\n", pulled)
	}

	held := &supervisor.Runs{}
	work := supervisor.RunOptions{
		WorkRoot:         filepath.Join(filepath.Dir(*configPath), "work"),
		StateRoot:        filepath.Join(filepath.Dir(*configPath), "stores"),
		OperatorHome:     operatorHome(),
		Server:           creds.Server,
		DaemonToken:      creds.Token,
		CallbackProgram:  callback,
		SessionRetention: settings.SessionRetention.Duration(),
		Workplace: func(id string) (supervisor.Workplace, bool) {
			place, known := places[id]
			return place, known
		},
		Runtime:  runtimeFor,
		Ledger:   supervisor.Reporting{Session: session},
		Runs:     held,
		Watchdog: watchdog,
		Report:   func(err error) { emit(out, "run: %v\n", err) },
	}

	// **Runs do not stop when the daemon is told to stop** (FR-034). Every loop below is on
	// `ctx` and ends the moment a signal arrives; the work already taken is on a context of its
	// own, and the only things that end it are a run finishing, the server taking it back, or
	// the drain below running out of patience.
	//
	// Before this, the two were the same context, and stopping the daemon cut every agent
	// mid-sentence — which is exactly what an upgrade does to a machine: stop, swap the binary,
	// start. The run still reported, so nothing looked broken; it reported a failure this
	// machine had caused.
	runCtx, endRuns := context.WithCancel(context.WithoutCancel(ctx))
	defer endRuns()

	// One buffered slot, deliberately: a nudge already waiting means an ask is already coming,
	// and a second one would only make that ask happen twice (FR-055a).
	nudges := make(chan struct{}, 1)

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
			OnGranted: func(_ context.Context, grant supervisor.Grant) {
				// On its own goroutine: the ask loop is what decides when to ask next, and a
				// machine with room for five runs that stops asking while the first one runs
				// has a ceiling of one.
				//
				// `runCtx`, deliberately not the context the ask loop was called with. That one
				// dies with the loop, and the run has to outlive the loop that fetched it.
				go work.Do(runCtx, grant)
			},
			Report: func(err error) { emit(out, "asking for work: %v\n", err) },
		})
	}()

	sweeper := housekeeping(settings, work, session)
	go func() {
		_ = supervisor.RunSweepLoop(ctx, supervisor.SweepOptions{
			Interval: settings.SweepInterval.Duration(),
			Sweep:    sweeper.Sweep,
			Swept: func(report execenv.Report) {
				if len(report.Removed) == 0 && len(report.Kept) == 0 {
					// Nothing on disk at all. A machine that has run nothing yet is not
					// worth a line every two hours.
					return
				}
				// The count of what was left alone goes out too, and not only the deletions:
				// a sweep that keeps everything and says nothing is indistinguishable from a
				// sweep that is not running, which is the state an operator staring at a full
				// disk most needs to be able to rule out.
				emit(out, "Swept: reclaimed %d, kept %d.\n", len(report.Removed), len(report.Kept))
				for _, path := range report.Removed {
					emit(out, "  reclaimed %s\n", path)
				}
			},
			Report: func(err error) { emit(out, "reclaiming disk: %v\n", err) },
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

	// From here on the daemon is leaving. Written down first, and before anything is waited
	// for, because the daemon that replaces this one reads exactly this to tell a process
	// finishing its last runs from one that means to keep running (FR-034).
	state.LeavingAt = time.Now()
	if saveErr := client.SaveState(statePath, state); saveErr != nil {
		emit(out, "could not record that this machine is stopping: %v\n", saveErr)
	}

	// Runs still going when the beat stops are runs this machine is holding, and holding them
	// is a promise. They are given the time to end the way they were going to end, and only
	// what is still going after that is cut — a cut run's hold lapses and its task goes back
	// through the recovery path that exists for it (FR-056a), which is a real cost and the
	// reason the wait comes first.
	stillRunning := supervisor.Drain(ctx, supervisor.DrainOptions{
		Held:     held.IDs,
		Patience: settings.DrainPatience.Duration(),
		Waiting: func(runs []string, patience time.Duration) {
			emit(out, "Stopping. Waiting up to %s for %d run(s) to finish.\n", patience, len(runs))
		},
	})
	for _, runID := range stillRunning {
		emit(out, "Cutting run %s: it was still going after %s.\n", runID, settings.DrainPatience)
	}
	endRuns()

	// Said last, when there is genuinely nothing left running here. Without it a stopped daemon
	// is indistinguishable from a closed laptop — both simply stop beating — and every agent on
	// this machine stays online until the missed-beat threshold runs out, which is time in which
	// work is handed to a machine that is not there (FR-005).
	if leaveErr := supervisor.Leave(ctx, supervisor.LeaveOptions{
		Deregister: session.Deregister,
	}); leaveErr != nil {
		// Not fatal, and not silent. Failing to say goodbye costs the threshold's worth of
		// delay and nothing else; hiding it would leave an operator wondering why their
		// machine's agents took three beats to go offline.
		emit(out, "could not hand this machine's workplaces back: %v\n", leaveErr)
	}
	return err
}

// workplacesOnThisMachine pairs what the server now holds with what was actually found here.
//
// The server answers with ids and kinds; the path to the binary and which protocol family it
// belongs to are facts only this machine has. A workplace this build cannot drive is left out
// entirely rather than included and refused later — see runtime.Supported for why that
// distinction is not cosmetic.
func workplacesOnThisMachine(
	registered []client.RegisteredWorkplace,
	found []discovery.Found,
	answers map[string]discovery.Capabilities,
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
			CLI:       workplace.CLIKind,
			Family:    string(cli.Family),
			Binary:    cli.Path,
			Resumable: answers[workplace.CLIKind].Resumable,
		}
	}
	return places
}

// runtimeFor answers which protocol family runs a workplace of one kind (FR-035, FR-039).
func runtimeFor(family string) (runtime.Runtime, bool) {
	switch agentcli.Family(family) {
	case agentcli.FamilyOneShot:
		return runtime.OneShot{}, true
	case agentcli.FamilyACP:
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
// silenceWatchdog builds the watchdog that decides a run has stopped producing anything.
//
// A function rather than three words inside the start-up path, for the same reason housekeeping
// below is one: what it is handed is the argument. A watchdog built with no per-CLI thresholds
// compiles, runs, and cuts every run at the base — which is exactly what this machine did before
// anything read the registry, and is indistinguishable from the wiring working.
//
// The declarations come in rather than being read here, so that the tighten-only rule can be
// driven down this exact path with a table that tries to break it. The registry declares none
// today, which is a thing a test says out loud in agentcli; a table nobody can hand a bad entry
// to is a rule nobody can prove is enforced.
func silenceWatchdog(declared map[string]time.Duration) (*supervisor.Watchdog, error) {
	return supervisor.NewWatchdog(supervisor.DefaultSilenceThreshold, declared)
}

// housekeeping is the disk sweep, built from the same options the runner was built from.
//
// It takes `supervisor.RunOptions` rather than the four values it reads out of it, and that is
// the point: FR-022 holds only while the sweep asks the *same* register the runner writes to,
// and while both look at the *same* two directories. Handing this function a fresh
// `&supervisor.Runs{}`, or a work root spelled a second time, would compile, run, and delete a
// live agent's working directory.
func housekeeping(
	settings config.Config, work supervisor.RunOptions, session client.Session,
) execenv.Collector {
	return execenv.Collector{
		WorkRoot:         work.WorkRoot,
		StateRoot:        work.StateRoot,
		Tasks:            supervisor.Asking{Session: session},
		Runs:             work.Runs,
		WorkDirRetention: settings.WorkDirRetention.Duration(),
		SessionRetention: settings.SessionRetention.Duration(),
		OrphanRetention:  settings.OrphanRetention.Duration(),
	}
}

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
