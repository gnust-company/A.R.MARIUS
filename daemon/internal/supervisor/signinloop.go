package supervisor

import (
	"context"
	"time"
)

// Keeping the server's idea of this machine's sign-ins true while the daemon runs (FR-007r).
//
// A machine's workplaces used to be reported once, when the daemon started. Whether anybody is
// signed in to a CLI is not a fact about when the daemon started: a sign-in lapses on a
// Tuesday afternoon, and the person signs in again an hour later, and the daemon is running
// through both. Reported once, the first of those leaves a workplace reading *ready* over a
// CLI that takes nothing, and the second leaves one closed that works — until somebody thinks
// to restart a daemon that is not broken.

// DefaultSignInInterval is how often each CLI is asked again when nothing says otherwise. The
// question is local and costs about a second of one process; five minutes is the longest a
// person who has just signed in is made to wait for their workplace to open by itself. The
// daemon's own setting (`sign_in_interval`) carries the same default.
const DefaultSignInInterval = 5 * time.Minute

// SignInOptions is everything the sign-in loop needs from the rest of the daemon.
type SignInOptions struct {
	// Interval defaults to DefaultSignInInterval.
	Interval time.Duration
	// Ask asks every CLI on this machine that has a way of being asked. Keyed by CLI kind; a
	// CLI that could not be asked is simply absent, and absent is not *no*.
	Ask func(ctx context.Context) map[string]bool
	// Reported is what the server was last told, which is where the loop starts from.
	Reported map[string]bool
	// Tell reports this machine's workplaces again, carrying these answers.
	Tell func(ctx context.Context, answers map[string]bool) error
	// Again makes the loop ask now, and tell whatever it hears even if nothing changed. Sent
	// when the provider has just refused a run's sign-in: the server closed the workplace on
	// that, and this machine's next report is the only thing that opens it again — so it must
	// be sent whether the CLI now says yes or no.
	Again <-chan struct{}
	// Report is told about a report that could not be sent. Optional.
	Report func(error)
	// Tick answers when the next question is due. A field so a test can drive the rhythm;
	// defaults to `time.After`.
	Tick func(d time.Duration) <-chan time.Time
}

// RunSignInLoop asks, and reports when the answer is news, until the context ends.
//
// It does not ask at once: the answers it starts from were asked a moment ago, as part of
// registering. A report that fails is not remembered as sent, so the same news is tried again
// on the next tick rather than lost to one dropped connection.
func RunSignInLoop(ctx context.Context, opts SignInOptions) error {
	opts = opts.withDefaults()
	known := opts.Reported

	for {
		forced := false
		select {
		case <-ctx.Done():
			// An orderly stop, not a failure.
			return nil
		case <-opts.Again:
			forced = true
		case <-opts.Tick(opts.Interval):
		}
		if ctx.Err() != nil {
			return nil
		}
		heard := opts.Ask(ctx)
		if !forced && sameAnswers(known, heard) {
			continue
		}
		if err := opts.Tell(ctx, heard); err != nil {
			opts.Report(err)
			continue
		}
		known = heard
	}
}

// sameAnswers compares two sets of answers, where a CLI missing from one is a difference: it
// went from asked to not asked, or the other way, and the server should hear which.
func sameAnswers(a, b map[string]bool) bool {
	if len(a) != len(b) {
		return false
	}
	for kind, said := range a {
		if now, asked := b[kind]; !asked || now != said {
			return false
		}
	}
	return true
}

func (o SignInOptions) withDefaults() SignInOptions {
	if o.Interval <= 0 {
		o.Interval = DefaultSignInInterval
	}
	if o.Ask == nil {
		o.Ask = func(context.Context) map[string]bool { return nil }
	}
	if o.Tell == nil {
		o.Tell = func(context.Context, map[string]bool) error { return nil }
	}
	if o.Report == nil {
		o.Report = func(error) {}
	}
	if o.Tick == nil {
		o.Tick = time.After
	}
	return o
}
