package supervisor

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

// asks records what the loop asked for, and stops it after a given number of asks so a test
// finishes in microseconds rather than in half a minute.
type asks struct {
	mu       sync.Mutex
	rooms    []int
	places   [][]string
	waited   []time.Duration
	failures []error
	granted  []Grant
	stopAt   int
	cancel   context.CancelFunc
	capacity int
	answer   []Grant
	claimErr error
}

func (a *asks) options() ClaimOptions {
	return ClaimOptions{
		Interval: 5 * time.Second,
		Capacity: func() int {
			a.mu.Lock()
			defer a.mu.Unlock()
			return a.capacity
		},
		Workplaces: func() []string { return []string{"wp-1", "wp-2"} },
		Claim: func(_ context.Context, places []string, most int) ([]Grant, error) {
			a.mu.Lock()
			a.rooms = append(a.rooms, most)
			a.places = append(a.places, places)
			count := len(a.rooms)
			a.mu.Unlock()
			if count >= a.stopAt {
				a.cancel()
			}
			return a.answer, a.claimErr
		},
		OnGranted: func(_ context.Context, grant Grant) {
			a.mu.Lock()
			defer a.mu.Unlock()
			a.granted = append(a.granted, grant)
		},
		Report: func(err error) {
			a.mu.Lock()
			defer a.mu.Unlock()
			a.failures = append(a.failures, err)
		},
		Tick: func(d time.Duration) <-chan time.Time {
			a.mu.Lock()
			a.waited = append(a.waited, d)
			a.mu.Unlock()
			due := make(chan time.Time, 1)
			due <- time.Now()
			return due
		},
	}
}

// Coming up may be coming back from a crash, with work this machine dropped sitting on the
// shelf. Waiting out an interval first adds that delay to a recovery.
func TestTheFirstAskGoesOutBeforeTheFirstWait(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	a := &asks{stopAt: 1, cancel: cancel, capacity: 2}

	if err := RunClaimLoop(ctx, a.options()); err != nil {
		t.Fatalf("an orderly stop is not a failure: %v", err)
	}
	if len(a.rooms) != 1 {
		t.Fatalf("expected exactly one ask, got %d", len(a.rooms))
	}
	if len(a.waited) != 1 {
		t.Fatalf("the wait belongs after the ask, not before it: %v", a.waited)
	}
}

// FR-055d, and the one rule about this loop that is easy to break with good intentions. A
// push that stops arriving makes the fallback look too slow, and the obvious fix — ask more
// often — hides the broken push and charges every machine for it forever. Failures, empty
// answers and nudges all leave the rhythm exactly where the operator set it.
func TestTheRhythmNeverChanges(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	nudge := make(chan struct{}, 1)
	a := &asks{stopAt: 5, cancel: cancel, capacity: 1, claimErr: errors.New("no route to host")}
	opts := a.options()
	opts.Nudge = nudge
	nudge <- struct{}{}

	if err := RunClaimLoop(ctx, opts); err != nil {
		t.Fatalf("an orderly stop is not a failure: %v", err)
	}

	if len(a.failures) == 0 {
		t.Fatal("an ask that failed should have been reported")
	}
	for i, waited := range a.waited {
		if waited != 5*time.Second {
			t.Fatalf("wait %d was %s; the loop rewrote the operator's rhythm", i, waited)
		}
	}
}

// The number the machine reports is the number it is asked with. Asking for more than there
// is room for would put the machine over its own limit the moment the server believed it.
func TestAnAskNeverWantsMoreThanThereIsRoomFor(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	a := &asks{stopAt: 1, cancel: cancel, capacity: 3}

	_ = RunClaimLoop(ctx, a.options())

	if a.rooms[0] != 3 {
		t.Fatalf("asked for %d with room for 3", a.rooms[0])
	}
}

// A full machine asking is a round trip that can only come back empty. The server would be
// right to give it nothing, so the honest thing is not to ask.
func TestAFullMachineDoesNotAskAtAll(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	a := &asks{stopAt: 1, cancel: cancel, capacity: 0}
	opts := a.options()
	opts.Tick = func(time.Duration) <-chan time.Time {
		cancel()
		return make(chan time.Time)
	}

	_ = RunClaimLoop(ctx, opts)

	if len(a.rooms) != 0 {
		t.Fatalf("a full machine asked anyway: %v", a.rooms)
	}
}

// Nothing installed, or everything not ready. There is no work that could be handed here even
// in principle, so the ask has nothing to be about.
func TestAMachineWithNowhereToRunDoesNotAsk(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	a := &asks{stopAt: 1, cancel: cancel, capacity: 4}
	opts := a.options()
	opts.Workplaces = func() []string { return nil }
	opts.Tick = func(time.Duration) <-chan time.Time {
		cancel()
		return make(chan time.Time)
	}

	_ = RunClaimLoop(ctx, opts)

	if len(a.rooms) != 0 {
		t.Fatalf("asked with nowhere to put the answer: %v", a.rooms)
	}
}

// Both readings are taken fresh on every ask. A CLI can be uninstalled and a run can finish
// while the daemon is up, and a count captured at startup is wrong from the second ask on.
func TestRoomAndPlacesAreReadFreshEveryTime(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	a := &asks{stopAt: 3, cancel: cancel, capacity: 3}
	opts := a.options()
	opts.Capacity = func() int {
		a.mu.Lock()
		defer a.mu.Unlock()
		// One fewer with every ask, so a remembered reading is tellable from a fresh one.
		return 3 - len(a.rooms)
	}

	_ = RunClaimLoop(ctx, opts)

	if len(a.rooms) < 3 {
		t.Fatalf("expected three asks, got %v", a.rooms)
	}
	if a.rooms[0] != 3 || a.rooms[1] != 2 || a.rooms[2] != 1 {
		t.Fatalf("the room was read once and remembered: %v", a.rooms)
	}
}

// A nudge means *there is work, go and ask* — it brings the next ask forward and carries
// nothing else. Two nudges arriving together therefore make two asks, and the second comes
// back empty-handed, which is what keeps them from making two runs (FR-055a).
func TestANudgeBringsTheNextAskForward(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	nudge := make(chan struct{}, 2)
	nudge <- struct{}{}
	nudge <- struct{}{}
	a := &asks{stopAt: 3, cancel: cancel, capacity: 1}
	opts := a.options()
	opts.Nudge = nudge
	// A tick that never fires: every ask after the first can only have been brought forward
	// by a nudge.
	opts.Tick = func(d time.Duration) <-chan time.Time {
		a.mu.Lock()
		a.waited = append(a.waited, d)
		a.mu.Unlock()
		return make(chan time.Time)
	}

	_ = RunClaimLoop(ctx, opts)

	if len(a.rooms) != 3 {
		t.Fatalf("two nudges should have produced two more asks, got %d", len(a.rooms))
	}
}

// Every run handed over is passed on, one at a time. A loop that claimed work and quietly
// dropped some of it would leave runs held by a machine that is not running them, and the
// hold would have to time out before anyone noticed.
func TestEveryRunHandedOverIsPassedOn(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	a := &asks{
		stopAt:   1,
		cancel:   cancel,
		capacity: 2,
		answer: []Grant{
			{RunID: "run-1", RunToken: "armr_run_a"},
			{RunID: "run-2", RunToken: "armr_run_b"},
		},
	}

	_ = RunClaimLoop(ctx, a.options())

	if len(a.granted) != 2 {
		t.Fatalf("expected both runs to be passed on, got %d", len(a.granted))
	}
	if a.granted[0].RunID != "run-1" || a.granted[1].RunID != "run-2" {
		t.Fatalf("runs arrived in the wrong order: %v", a.granted)
	}
}

// A machine that cannot say how much room it has is treated as having none. Guessing it is
// free hands work to a machine in an unknown state.
func TestAMachineThatCannotSayItsRoomIsTreatedAsFull(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	asked := false
	err := RunClaimLoop(ctx, ClaimOptions{
		Interval: time.Second,
		Claim: func(context.Context, []string, int) ([]Grant, error) {
			asked = true
			return nil, nil
		},
		Tick: func(time.Duration) <-chan time.Time {
			cancel()
			return make(chan time.Time)
		},
	})
	if err != nil {
		t.Fatalf("an orderly stop is not a failure: %v", err)
	}
	if asked {
		t.Fatal("asked for work without knowing whether there was room for it")
	}
}
