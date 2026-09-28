package update

import (
	"context"
	"fmt"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"
)

// The rhythms of the two roads (FR-008n).
const (
	// DefaultInitialDelay is how long after starting the first look happens. A daemon coming up
	// has registered its workplaces and is asking for work; a call to the release page on top of
	// that buys nothing, and two minutes still puts a fresh install onto the newest release
	// within minutes rather than hours.
	DefaultInitialDelay = 2 * time.Minute
	// DefaultPullInterval is how often a newer release is looked for.
	DefaultPullInterval = 6 * time.Hour
	// DefaultReloadInterval bounds how long an operator waits after replacing the program
	// themselves. It is not about release cadence — that is the pull interval's — and a busy
	// machine defers to the next tick, so the wait is really *the first tick that is both due and
	// idle*; ten minutes keeps that tolerable.
	DefaultReloadInterval = 10 * time.Minute
	// probeTimeout bounds asking the program on disk for its version. The point is to stop a
	// wedged binary from parking the loop, not to police a slow disk.
	probeTimeout = 10 * time.Second
)

// Options is one daemon's auto-update loop.
type Options struct {
	// Version is what this process was built as, and Executable is the file it was started from:
	// the one a newer release replaces, and the one a restart runs.
	Version    string
	Executable string

	// Pull and Reload switch the two roads on (FR-008n: both, unless the operator says not).
	Pull           bool
	PullInterval   time.Duration
	Reload         bool
	ReloadInterval time.Duration
	InitialDelay   time.Duration

	// Releases is where a newer release is looked for and fetched from.
	Releases Releases

	// Idle stops the daemon asking for work and answers true only if nothing is held and nothing
	// is on its way in; Busy undoes a pause that did not end in a restart. Together they are the
	// one guarantee this loop gives: it never restarts over a run (FR-034).
	Idle func() bool
	Busy func()
	// Restart hands the daemon over to the program on disk. Called at most once; the loop ends
	// after it.
	Restart func()
	// Say writes one line to the daemon's log.
	Say func(format string, args ...any)

	// Seams for tests. Nil takes the real thing.
	Latest  func(ctx context.Context) (string, error)
	Install func(ctx context.Context, tag string) error
	OnDisk  func(ctx context.Context) (string, error)
	Tick    func(d time.Duration) <-chan time.Time
}

func (o Options) withDefaults() Options {
	if o.PullInterval <= 0 {
		o.PullInterval = DefaultPullInterval
	}
	if o.ReloadInterval <= 0 {
		o.ReloadInterval = DefaultReloadInterval
	}
	if o.InitialDelay <= 0 {
		o.InitialDelay = DefaultInitialDelay
	}
	if o.Say == nil {
		o.Say = func(string, ...any) {}
	}
	if o.Idle == nil {
		o.Idle = func() bool { return false }
	}
	if o.Busy == nil {
		o.Busy = func() {}
	}
	if o.Latest == nil {
		o.Latest = o.Releases.Latest
	}
	if o.Install == nil {
		o.Install = func(ctx context.Context, tag string) error {
			return Install(ctx, o.Releases, tag, Target{
				Dir: filepath.Dir(o.Executable), GOOS: runtime.GOOS, GOARCH: runtime.GOARCH,
			})
		}
	}
	if o.OnDisk == nil {
		o.OnDisk = func(ctx context.Context) (string, error) { return versionOf(ctx, o.Executable) }
	}
	if o.Tick == nil {
		o.Tick = time.After
	}
	return o
}

// Run keeps this daemon on the newest release until the context ends or it restarts.
//
// Both roads run on this one goroutine, which is what keeps them from racing each other into a
// restart. Every tick is silent when there is nothing to do; a daemon runs for weeks, and its log
// should say what happened, not that nothing did.
func Run(ctx context.Context, opts Options) {
	opts = opts.withDefaults()
	pull := opts.Pull
	switch {
	case !pull:
		opts.Say("Auto-update is off.")
	case !IsRelease(opts.Version):
		// Said once, here, rather than on every tick.
		opts.Say("Auto-update skipped: %q is a build from source, not a release.", opts.Version)
		pull = false
	}
	if !pull && !opts.Reload {
		return
	}

	nextPull, nextReload := opts.Tick(opts.InitialDelay), opts.Tick(opts.InitialDelay)
	if !pull {
		nextPull = nil
	}
	if !opts.Reload {
		nextReload = nil
	}
	for {
		select {
		case <-ctx.Done():
			return
		case <-nextPull:
			if opts.tryPull(ctx) {
				return
			}
			nextPull = opts.Tick(opts.PullInterval)
		case <-nextReload:
			if opts.tryReload(ctx) {
				return
			}
			nextReload = opts.Tick(opts.ReloadInterval)
		}
	}
}

// tryPull looks for a newer release and, when this machine is idle, puts it in place and restarts
// into it. It answers whether it restarted. Nothing here ever stops the daemon: a look that fails
// today is looked again at the next tick.
func (o Options) tryPull(ctx context.Context) bool {
	latest, err := o.Latest(ctx)
	if err != nil {
		o.Say("Auto-update: %v. Trying again in %s.", err, o.PullInterval)
		return false
	}
	if !Newer(latest, o.Version) {
		return false
	}
	if !o.Idle() {
		o.Say("Auto-update: %s is out; waiting until no run is going to take it.", latest)
		return false
	}
	o.Say("Auto-update: installing %s over %s.", latest, o.Version)
	if err := o.Install(ctx, latest); err != nil {
		o.Busy()
		o.Say("Auto-update: %v. Trying again in %s.", err, o.PullInterval)
		return false
	}
	o.Say("Auto-update: %s is in place; restarting into it.", latest)
	o.Restart()
	return true
}

// tryReload restarts into the program on disk once that is no longer this version — the road an
// upgrade takes when somebody else put it there (FR-008n). A version that cannot be read is never
// taken for a change: the file is most likely unreadable during the very replacement this looks
// for, and "could not tell" is no reason to restart.
func (o Options) tryReload(ctx context.Context) bool {
	onDisk, err := o.OnDisk(ctx)
	if err != nil || onDisk == "" || o.Version == "" {
		if err != nil {
			o.Say("Auto-reload: could not read the version of %s: %v.", o.Executable, err)
		}
		return false
	}
	if onDisk == o.Version {
		return false
	}
	if !o.Idle() {
		o.Say("Auto-reload: %s on disk is %s, this is %s; waiting until no run is going.",
			o.Executable, onDisk, o.Version)
		return false
	}
	o.Say("Auto-reload: %s on disk is %s, this is %s; restarting into it.", o.Executable, onDisk, o.Version)
	o.Restart()
	return true
}

// versionOf asks a program on disk which version it is.
func versionOf(ctx context.Context, program string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, probeTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, program, "--version") //nolint:gosec // this daemon's own executable
	// The kill on timeout reaches the process, not whatever it may have left holding the pipe.
	cmd.WaitDelay = 2 * time.Second
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("running %s --version: %w", program, err)
	}
	return VersionIn(string(out)), nil
}
