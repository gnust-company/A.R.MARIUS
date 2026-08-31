package supervisor

import (
	"context"
	"errors"
	"testing"
	"time"
)

// a clock a test can push forward without waiting.
type testClock struct{ at time.Time }

func (c *testClock) now() time.Time { return c.at }

func (c *testClock) advance(d time.Duration) func(context.Context, time.Duration) error {
	return func(context.Context, time.Duration) error {
		c.at = c.at.Add(d)
		return nil
	}
}

func TestNothingRunningIsStoppedAtOnce(t *testing.T) {
	waited := false
	left := Drain(context.Background(), DrainOptions{
		Held:  func() []string { return nil },
		Sleep: func(context.Context, time.Duration) error { waited = true; return nil },
	})

	if len(left) != 0 {
		t.Errorf("a machine holding nothing reported %v left running", left)
	}
	if waited {
		t.Error("a machine holding nothing still waited out a drain")
	}
}

// FR-034: an upgrade stops the daemon. The work it had already taken finishes.
func TestTheRunsAlreadyTakenAreWaitedFor(t *testing.T) {
	clock := &testClock{at: time.Unix(0, 0)}
	looks := 0
	told := 0

	left := Drain(context.Background(), DrainOptions{
		Held: func() []string {
			looks++
			if looks >= 3 {
				return nil
			}
			return []string{"run-1"}
		},
		Patience: time.Minute,
		Check:    time.Second,
		Waiting:  func([]string, time.Duration) { told++ },
		Now:      clock.now,
		Sleep:    clock.advance(time.Second),
	})

	if len(left) != 0 {
		t.Errorf("a run that finished on its own was reported as cut: %v", left)
	}
	if told != 1 {
		t.Errorf("the operator was told %d times that the stop would take a moment, want once", told)
	}
}

// The wait is bounded. An unbounded one hands the operator a stop that never returns, and a
// service manager answers that with SIGKILL — which cuts the run anyway and skips the goodbye.
func TestARunThatOutlastsThePatienceIsHandedBackToTheCaller(t *testing.T) {
	clock := &testClock{at: time.Unix(0, 0)}

	left := Drain(context.Background(), DrainOptions{
		Held:     func() []string { return []string{"run-1", "run-2"} },
		Patience: 10 * time.Second,
		Check:    time.Second,
		Now:      clock.now,
		Sleep:    clock.advance(time.Second),
	})

	if len(left) != 2 {
		t.Fatalf("the drain reported %v still running, want both runs", left)
	}
	if elapsed := clock.at.Sub(time.Unix(0, 0)); elapsed < 10*time.Second {
		t.Errorf("the drain gave up after %s, want it to wait out the whole 10s patience", elapsed)
	}
}

func TestAWaitCutShortReportsWhatWasStillRunning(t *testing.T) {
	left := Drain(context.Background(), DrainOptions{
		Held:     func() []string { return []string{"run-1"} },
		Patience: time.Hour,
		Sleep:    func(context.Context, time.Duration) error { return context.Canceled },
	})

	if len(left) != 1 || left[0] != "run-1" {
		t.Errorf("a drain cut short reported %v, want the run it was still holding", left)
	}
}

// FR-005: the goodbye is the whole point of this call, and by the time it runs the context that
// ended the daemon has already been cancelled. Using it would make every goodbye fail — and look
// in the code exactly like a goodbye that works.
func TestTheGoodbyeIsNotSentOnTheContextThatEndedTheDaemon(t *testing.T) {
	stopped, cancel := context.WithCancel(context.Background())
	cancel()

	var seen error
	err := Leave(stopped, LeaveOptions{
		Deregister: func(ctx context.Context) error { seen = ctx.Err(); return nil },
	})

	if err != nil {
		t.Fatalf("Leave returned %v", err)
	}
	if seen != nil {
		t.Errorf("the goodbye was handed an already-cancelled context: %v", seen)
	}
}

func TestTheGoodbyeGivesUpRatherThanHangingTheStop(t *testing.T) {
	var deadline time.Time
	err := Leave(context.Background(), LeaveOptions{
		Grace: 3 * time.Second,
		Deregister: func(ctx context.Context) error {
			deadline, _ = ctx.Deadline()
			return nil
		},
	})

	if err != nil {
		t.Fatalf("Leave returned %v", err)
	}
	if deadline.IsZero() {
		t.Fatal("the goodbye was given no deadline, so a hung server hangs the stop")
	}
	if left := time.Until(deadline); left > 3*time.Second {
		t.Errorf("the goodbye was given %s, want no more than the 3s grace", left)
	}
}

func TestAGoodbyeThatDidNotArriveIsReportedRatherThanSwallowed(t *testing.T) {
	refused := errors.New("connection refused")
	err := Leave(context.Background(), LeaveOptions{
		Deregister: func(context.Context) error { return refused },
	})

	if !errors.Is(err, refused) {
		t.Errorf("Leave returned %v, want the failure it met", err)
	}
}
