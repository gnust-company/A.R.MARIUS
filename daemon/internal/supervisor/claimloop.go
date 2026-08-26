package supervisor

import (
	"context"
	"time"
)

// DefaultClaimInterval is how often this machine asks for work when nothing has nudged it.
//
// Five seconds, and it is meant to be **slow** rather than fast. Asking is the fallback road,
// not the main one: the main one is the server saying *there is work, go and ask*, and this
// rhythm exists for the times that message does not arrive (FR-055, FR-055d). Most asks find
// an empty shelf, which is exactly why the pace can afford to be unhurried.
const DefaultClaimInterval = 5 * time.Second

// Grant is one run this machine has been handed.
//
// Deliberately not the client's own type: this package decides *when* to ask and what to do
// with an answer, and it should not have to be edited the day the wire format gains a field.
type Grant struct {
	RunID       string
	TaskID      string
	WorkplaceID string
	RunToken    string
	Expires     time.Time
}

// ClaimOptions is everything the ask loop needs from the rest of the daemon.
type ClaimOptions struct {
	// Interval defaults to DefaultClaimInterval. It is the operator's to set, and it is
	// **never** shortened by this loop. A failing push is fixed by fixing the push; speeding
	// up the fallback to cover for it hides the fault and costs every machine the difference
	// forever (FR-055d).
	Interval time.Duration
	// Nudge carries *there is work, go and ask*. It brings the next ask forward and changes
	// nothing else — not the rhythm, and not what an ask is allowed to take. That is what
	// keeps two nudges arriving together from producing two runs: the second ask simply comes
	// back empty-handed (FR-055a).
	Nudge <-chan struct{}
	// Capacity is how many more runs this machine will take, read fresh on every ask. Zero
	// means do not ask at all — an ask from a full machine is a round trip that can only come
	// back with nothing, and the server would be right to give it nothing (FR-008).
	Capacity func() int
	// Workplaces is what this machine can run work on, read fresh for the same reason: a CLI
	// can be uninstalled while the daemon is running.
	Workplaces func() []string
	// Claim asks the server, and comes back with what it was given.
	Claim func(ctx context.Context, workplaces []string, most int) ([]Grant, error)
	// OnGranted is handed each run, one at a time. Optional only so the loop can be tested;
	// a daemon that claims work and does nothing with it is worse than one that never asked.
	OnGranted func(ctx context.Context, grant Grant)
	// Report is told about an ask that did not get through. Optional.
	Report func(error)
	// Tick answers when the next ask is due. A channel rather than a blocking wait because
	// a nudge has to be able to win the race against it, and a wait that has to be abandoned
	// mid-flight would leave a goroutine behind on every nudge. Defaults to `time.After`.
	Tick func(d time.Duration) <-chan time.Time
}

// RunClaimLoop asks for work until the context ends (FR-053, FR-055).
//
// The first ask goes out immediately. A daemon that has just come up may be coming back from
// a crash, and work it dropped is sitting on the shelf waiting to be taken again; making it
// wait out one interval first would add that delay to a recovery, which is the moment it is
// least welcome.
//
// A failed ask is never fatal and there is deliberately no limit on consecutive failures, for
// the same reason the beat has none: nobody is standing there waiting, and a laptop that lost
// its wifi for an hour should come back to work when the wifi does. What it must not do is
// react to failure by asking harder — see `Interval`.
func RunClaimLoop(ctx context.Context, opts ClaimOptions) error {
	opts = opts.withDefaults()

	for {
		opts.askOnce(ctx)
		if !opts.wait(ctx) {
			// The context ended: an orderly stop, not a failure.
			return nil
		}
	}
}

// askOnce asks for work at most once, and may decide not to ask at all.
func (o ClaimOptions) askOnce(ctx context.Context) {
	room := o.Capacity()
	if room <= 0 {
		return
	}
	places := o.Workplaces()
	if len(places) == 0 {
		// Nothing on this machine can run anything — no CLI found, or every workplace not
		// ready. There is no work that could be handed here even in principle.
		return
	}
	granted, err := o.Claim(ctx, places, room)
	if err != nil {
		o.Report(err)
		return
	}
	if o.OnGranted == nil {
		return
	}
	for _, grant := range granted {
		o.OnGranted(ctx, grant)
	}
}

// wait holds until the next ask is due, or until something says to ask now. False means the
// context ended.
//
// The nudge and the tick are two ways to reach the same next ask, never two asks. Whichever
// arrives first ends this wait, and the wait after it is a full interval again — the rhythm is
// not what a nudge changes (FR-055d). A nil nudge channel blocks forever, which is exactly the
// behaviour wanted when nobody is pushing: the tick is then the only way out.
func (o ClaimOptions) wait(ctx context.Context) bool {
	select {
	case <-ctx.Done():
		return false
	case <-o.Nudge:
		return true
	case <-o.Tick(o.Interval):
		return ctx.Err() == nil
	}
}

func (o ClaimOptions) withDefaults() ClaimOptions {
	if o.Interval <= 0 {
		o.Interval = DefaultClaimInterval
	}
	if o.Capacity == nil {
		// A machine that cannot say how much room it has is treated as having none. The
		// alternative — guessing it is free — hands work to a machine in an unknown state.
		o.Capacity = func() int { return 0 }
	}
	if o.Workplaces == nil {
		o.Workplaces = func() []string { return nil }
	}
	if o.Claim == nil {
		o.Claim = func(context.Context, []string, int) ([]Grant, error) { return nil, nil }
	}
	if o.Report == nil {
		o.Report = func(error) {}
	}
	if o.Tick == nil {
		o.Tick = func(d time.Duration) <-chan time.Time { return time.After(d) }
	}
	return o
}
