package supervisor

import (
	"context"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// Asking is execenv.TaskStates backed by the real server.
//
// A type of its own, like Reporting, so the translation between the wire's shapes and this
// program's lives in one file — and so that the sweep, which only ever needs to ask one
// question, does not get handed something that can also claim runs and finish them.
type Asking struct {
	Session client.Session
}

// Lookup asks what this workspace knows about the tasks a machine has directories for.
func (a Asking) Lookup(
	ctx context.Context, taskIDs []string,
) (map[string]execenv.TaskState, error) {
	answered, err := a.Session.TaskStates(ctx, taskIDs)
	if err != nil {
		return nil, err
	}
	states := make(map[string]execenv.TaskState, len(answered))
	for id, task := range answered {
		states[id] = execenv.TaskState{Closed: task.Closed, LastActivity: task.LastActivity}
	}
	return states, nil
}

// SweepOptions is everything the housekeeping loop needs from the rest of the daemon.
type SweepOptions struct {
	// Interval defaults to execenv.DefaultSweepInterval. Two hours: often enough that a
	// machine does not fill up, rare enough that the sweep costs nothing (FR-021).
	Interval time.Duration
	// Sweep looks once at everything on disk and reclaims what has aged out.
	Sweep func(ctx context.Context, now time.Time) (execenv.Report, error)
	// Now is the clock, injected so a test does not have to wait out a retention.
	Now func() time.Time
	// Swept is told what one sweep did. Optional — but a collector that deletes things and
	// says nothing is indistinguishable from one that is not running.
	Swept func(execenv.Report)
	// Report is told about a sweep that could not finish. Optional.
	Report func(error)
	// Tick answers when the next sweep is due. A field so a test can drive the rhythm;
	// defaults to `time.After`.
	Tick func(d time.Duration) <-chan time.Time
}

// RunSweepLoop reclaims disk on a beat until the context ends (FR-021, FR-021a, FR-027).
//
// **The first sweep runs immediately.** A machine coming back from a week switched off is the
// case this exists for, and making it wait out a full interval first adds that delay to
// precisely the moment there is most to reclaim. Sweeping again on every restart costs nothing:
// nothing is removed before its retention has passed, so an extra sweep either finds work that
// was already due or finds none.
//
// A failed sweep is never fatal, and there is no limit on consecutive failures. The usual
// reason one fails is that the server could not be reached to ask about tasks — a laptop off
// wifi — and the right response to that is to try again on the next beat, holding on to
// everything in the meantime.
func RunSweepLoop(ctx context.Context, opts SweepOptions) error {
	opts = opts.withDefaults()

	for {
		opts.sweepOnce(ctx)
		select {
		case <-ctx.Done():
			// An orderly stop, not a failure.
			return nil
		case <-opts.Tick(opts.Interval):
			if ctx.Err() != nil {
				return nil
			}
		}
	}
}

func (o SweepOptions) sweepOnce(ctx context.Context) {
	report, err := o.Sweep(ctx, o.Now())
	if err != nil {
		// The report is still handed on. A sweep that failed part-way has usually already
		// removed something, and what it removed is exactly the thing an operator staring at
		// a full disk needs to be told about.
		o.Swept(report)
		o.Report(err)
		return
	}
	o.Swept(report)
}

func (o SweepOptions) withDefaults() SweepOptions {
	if o.Interval <= 0 {
		o.Interval = execenv.DefaultSweepInterval
	}
	if o.Sweep == nil {
		o.Sweep = func(context.Context, time.Time) (execenv.Report, error) {
			return execenv.Report{}, nil
		}
	}
	if o.Now == nil {
		o.Now = time.Now
	}
	if o.Swept == nil {
		o.Swept = func(execenv.Report) {}
	}
	if o.Report == nil {
		o.Report = func(error) {}
	}
	if o.Tick == nil {
		o.Tick = func(d time.Duration) <-chan time.Time { return time.After(d) }
	}
	return o
}
