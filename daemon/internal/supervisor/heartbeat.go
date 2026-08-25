package supervisor

import (
	"context"
	"time"
)

// DefaultHeartbeatInterval is how often this machine says it is alive.
//
// Fifteen seconds, and the server treats three missed beats in a row as a machine that has gone
// away (FR-004, research.md §3). It lives here as well as in the operator's config file because
// a heartbeat with no interval is not a heartbeat.
const DefaultHeartbeatInterval = 15 * time.Second

// Beat is what this machine says about itself on one tick.
type Beat struct {
	// FreeSlots is how many more runs this machine will take right now. It is advice, not a
	// ceiling: the server keeps its own cap and takes the smaller of the two, so a stale or
	// wrong number here can never get this machine more work than it is allowed (FR-008d).
	// Saying it at all is what lets the server hold work back instead of tracking how busy
	// every machine is (FR-055c).
	FreeSlots int
	// Running is what this machine believes it is running. It is how the server can tell a
	// machine that it has lost work it still thinks it holds.
	Running []string
}

// Reply is what the server answers.
type Reply struct {
	// PendingWork means there is something to claim. It is a nudge to go and ask, never an
	// instruction to run anything (FR-055a).
	PendingWork bool
	// Cancel names runs this machine reported as running and no longer holds. Its writes
	// would be refused anyway (FR-059); being told early saves the work of producing them.
	Cancel []string
}

// HeartbeatOptions is everything the beat needs from the rest of the daemon.
type HeartbeatOptions struct {
	// Interval defaults to DefaultHeartbeatInterval.
	Interval time.Duration
	// State is read fresh on every beat. It must be, not held from startup: the free-slot
	// count is the whole reason the beat carries a number, and a number captured once is a
	// number that is wrong from the second beat onwards.
	State func() Beat
	// Send delivers one beat and brings the answer back.
	Send func(ctx context.Context, beat Beat) (Reply, error)
	// OnReply acts on the answer — going to ask for work, and stopping runs this machine no
	// longer holds. Optional: a beat whose answer nobody acts on is still a beat, and keeping
	// the machine reachable is its first job.
	OnReply func(Reply)
	// Report is told about a beat that did not get through. Optional.
	Report func(error)
	// Sleep waits between beats, returning the context's error if the wait is cut short.
	Sleep func(ctx context.Context, d time.Duration) error
}

// RunHeartbeat beats until the context ends (FR-004).
//
// The first beat goes out immediately rather than after one interval. A machine that has just
// come up is reachable now, and waiting fifteen seconds to say so leaves a window in which the
// server has a linked machine it has never heard from.
//
// A beat that fails is never fatal, and there is deliberately no limit on consecutive failures
// — unlike the login poll, which does have one. The difference is what silence means in each
// case: during login a person is standing there waiting, and a server that never answers must
// end the wait. Here nobody is waiting, and a laptop that lost its wifi for an hour should be
// back in the workspace when the wifi returns, not exited. The server's own missed-beat
// threshold is what draws the conclusion, and it is the only place that conclusion belongs.
func RunHeartbeat(ctx context.Context, opts HeartbeatOptions) error {
	opts = opts.withDefaults()

	for {
		beat := opts.State()
		reply, err := opts.Send(ctx, beat)
		switch {
		case err != nil:
			opts.Report(err)
		case opts.OnReply != nil:
			opts.OnReply(reply)
		}

		if err := opts.Sleep(ctx, opts.Interval); err != nil {
			// The context ended: an orderly stop, not a failure. Handing back the
			// cancellation would make every caller re-classify it.
			return nil
		}
	}
}

func (o HeartbeatOptions) withDefaults() HeartbeatOptions {
	if o.Interval <= 0 {
		o.Interval = DefaultHeartbeatInterval
	}
	if o.State == nil {
		// A machine that cannot say how busy it is says it is full. The server then holds its
		// work rather than handing it to a machine whose state is unknown.
		o.State = func() Beat { return Beat{} }
	}
	if o.Report == nil {
		o.Report = func(error) {}
	}
	if o.Sleep == nil {
		o.Sleep = sleep
	}
	return o
}

// sleep waits, and reports a cancelled context as the error it is.
func sleep(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
