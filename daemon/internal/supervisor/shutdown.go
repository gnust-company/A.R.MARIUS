package supervisor

import (
	"context"
	"fmt"
	"time"
)

// How a daemon leaves. Both numbers are ceilings on waiting, never schedules.
const (
	// DefaultDrainPatience is how long a stopping daemon lets the runs it is already holding
	// finish before it cuts them (FR-034).
	//
	// Sixty seconds, and the number is chosen against the thing that will actually kill this
	// process: systemd's `TimeoutStopSec` defaults to 90 seconds, after which the unit is sent
	// SIGKILL. A patience longer than that would never be honoured — the drain would be
	// half-done when the process was destroyed, which is worse than a bounded drain because it
	// also leaves the state file behind and makes an orderly stop look like a crash. An
	// operator who wants longer turns must raise both numbers, and daemon/README.md says so.
	DefaultDrainPatience = 60 * time.Second

	// DefaultGoodbyeGrace is how long the last call to the server is given (FR-005).
	//
	// Short on purpose: handing the workplaces back is an optimisation over the heartbeat
	// threshold, not a duty. A server that cannot be reached in ten seconds will notice this
	// machine has stopped beating soon enough on its own, and a stop that hangs waiting to say
	// goodbye is a worse failure than a stop that leaves quietly.
	DefaultGoodbyeGrace = 10 * time.Second
)

// DrainOptions is everything the wind-down needs to know about the work still in flight.
type DrainOptions struct {
	// Held answers what this machine is still running. Read repeatedly, never captured.
	Held func() []string
	// Patience defaults to DefaultDrainPatience. It is how long the drain waits, not how long
	// a run is allowed to take: a run that finishes in a second is waited on for a second.
	Patience time.Duration
	// Check is how often Held is asked. Defaults to a second.
	Check time.Duration
	// Waiting is told, once, that the stop is going to take a moment and why. Optional.
	Waiting func(running []string, patience time.Duration)
	// Now is the clock. Injected so a test does not have to wait out a patience.
	Now func() time.Time
	// Sleep waits between looks. Injected for the same reason.
	Sleep func(ctx context.Context, d time.Duration) error
}

// Drain waits for the runs this machine is holding to finish, and reports what would not
// (FR-034).
//
// **This is the half of an upgrade that stops it cutting work.** Replacing the daemon means
// stopping the old process, and until now stopping it meant cancelling the context every run
// was started on — the agent's turn died mid-sentence, and what the run reported was a failure
// this machine caused. The loops still stop at once; the work already taken is given the time
// to end the way it was going to end anyway.
//
// The wait is bounded, and the bound is not caution. An unbounded drain hands the operator a
// stop command that never returns, and a service manager answers that with SIGKILL — which cuts
// the run *and* skips everything after this. What is still running when the patience runs out
// is returned rather than raised: the caller cuts it, and a run cut here is a run whose hold
// lapses and whose task goes back through the recovery path that exists for exactly this
// (FR-056a).
//
// Returns the runs that were still going. Empty means everything ended on its own.
func Drain(ctx context.Context, opts DrainOptions) []string {
	opts = opts.withDefaults()

	running := opts.Held()
	if len(running) == 0 {
		return nil
	}
	opts.Waiting(running, opts.Patience)

	// **Not the caller's context, for the same reason Leave does not use it.** By the time a
	// drain runs, the context that ended the daemon has been cancelled — that cancellation is
	// what got us here — so a wait on it returns at once. The bound this function is supposed
	// to hold would then be a bound it never reaches: every run cut immediately, and a line
	// printed saying it had been given a minute.
	//
	// So the only thing that ends this wait is the patience, which is what the operator set it
	// for.
	waiting := context.WithoutCancel(ctx)

	deadline := opts.Now().Add(opts.Patience)
	for {
		if running = opts.Held(); len(running) == 0 {
			return nil
		}
		if !opts.Now().Before(deadline) {
			return running
		}
		if err := opts.Sleep(waiting, opts.Check); err != nil {
			// The wait itself failed. Whatever is still held is still held, and saying so is
			// the only honest answer.
			return opts.Held()
		}
	}
}

func (o DrainOptions) withDefaults() DrainOptions {
	if o.Held == nil {
		o.Held = func() []string { return nil }
	}
	if o.Patience <= 0 {
		o.Patience = DefaultDrainPatience
	}
	if o.Check <= 0 {
		o.Check = time.Second
	}
	if o.Waiting == nil {
		o.Waiting = func([]string, time.Duration) {}
	}
	if o.Now == nil {
		o.Now = time.Now
	}
	if o.Sleep == nil {
		o.Sleep = sleep
	}
	return o
}

// LeaveOptions is what saying goodbye needs.
type LeaveOptions struct {
	// Deregister hands this machine's workplaces back. It gets a context of its own — see
	// Leave — so it must not close over the one that ended the daemon.
	Deregister func(ctx context.Context) error
	// Grace defaults to DefaultGoodbyeGrace.
	Grace time.Duration
}

// Leave tells the server this machine's workplaces are no longer open (FR-005).
//
// Without it, a stopped daemon is indistinguishable from a laptop that was closed: both simply
// stop beating, and every agent on the machine stays *online* until the missed-beat threshold
// runs out. That gap is time in which work is handed to a machine that is not there, and every
// run it produces has to be taken back.
//
// **The context is deliberately not the caller's.** By the time this runs, the context that
// ended the daemon has been cancelled — that cancellation is what got us here — and any call
// made on it fails before a packet leaves the machine. A goodbye that always fails is worse
// than none: it looks in the code exactly like a goodbye that works. So the deadline here is
// this function's own, and the only thing it inherits from the caller's context is its values.
func Leave(ctx context.Context, opts LeaveOptions) error {
	if opts.Deregister == nil {
		return nil
	}
	if opts.Grace <= 0 {
		opts.Grace = DefaultGoodbyeGrace
	}
	said, cancel := context.WithTimeout(context.WithoutCancel(ctx), opts.Grace)
	defer cancel()

	if err := opts.Deregister(said); err != nil {
		return fmt.Errorf("handing this machine's workplaces back: %w", err)
	}
	return nil
}
