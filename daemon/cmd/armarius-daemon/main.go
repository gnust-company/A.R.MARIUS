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
// `login` and `start` are built. `status` is not, and until it is it fails loudly rather than
// pretending to have done its job — the task that builds it is named in the refusal.
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
	"runtime"
	"syscall"

	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/config"
	"github.com/gnust-company/armarius-daemon/internal/discovery"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
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
		Platform:   runtime.GOOS,
		Version:    version,
		Out:        out,
	})
	return err
}

// runStart brings this machine online: it works out what it can run, tells the server, and
// keeps saying it is there until it is stopped.
//
// Asking for work is not here yet — that is the claim loop and the push channel, T052 and T054
// in specs/002-daemon-acp-runtime/tasks.md. Until they land, a machine that runs this is a
// machine the server can see and hand nothing to, which is a real and safe state: work with
// nowhere to go simply waits, which is what FR-008a asks for anyway.
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

	emit(out, "Beating every %s. Stop with Ctrl-C.\n", settings.HeartbeatInterval)
	return supervisor.RunHeartbeat(ctx, supervisor.HeartbeatOptions{
		Interval: settings.HeartbeatInterval.Duration(),
		State: func() supervisor.Beat {
			// Nothing runs on this machine yet, so every slot is free. The count is read here
			// on every beat rather than captured once, which is what will keep it true the
			// moment the claim loop starts holding runs.
			return supervisor.Beat{FreeSlots: settings.MaxConcurrentRuns}
		},
		Send: func(ctx context.Context, beat supervisor.Beat) (supervisor.Reply, error) {
			answered, err := session.Beat(ctx, client.BeatRequest{
				FreeSlots: beat.FreeSlots,
				Running:   beat.Running,
			})
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
}

func runStatus(_ context.Context, args []string, out io.Writer) error {
	fs := newFlagSet("status", out)
	fs.Bool("json", false, "print the answer as JSON rather than for a person to read")
	if err := fs.Parse(args); err != nil {
		return err
	}
	return notImplemented("status", "T038a")
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

// notImplemented reports a subcommand that is declared but not yet built, naming the tasks that
// will build it. It is an error rather than a friendly notice on purpose: a supervisor that runs
// `armarius-daemon start` has to see a non-zero exit instead of believing the daemon came up.
func notImplemented(name, tasks string) error {
	return fmt.Errorf("%s is not built yet — see %s in specs/002-daemon-acp-runtime/tasks.md", name, tasks)
}
