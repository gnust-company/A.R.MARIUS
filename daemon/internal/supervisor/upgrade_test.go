package supervisor

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
)

// a predecessor a test can describe and then change its mind about.
type predecessor struct {
	state client.RunState
	there bool
	alive bool
	reads int
}

func (p *predecessor) read() (client.RunState, bool, error) { p.reads++; return p.state, p.there, nil }
func (p *predecessor) isAlive(int) bool                     { return p.alive }

func TestAMachineWithNoDaemonOnItStartsAtOnce(t *testing.T) {
	prior := &predecessor{}
	if err := WaitForPredecessor(context.Background(), HandoverOptions{
		Read:  prior.read,
		Alive: prior.isAlive,
		Self:  99,
	}); err != nil {
		t.Fatalf("starting on an empty machine returned %v", err)
	}
}

// The state file is removed on an orderly stop, so a file over a process that is gone means the
// daemon before this one was killed. There is nothing to wait for.
func TestAStateFileLeftByAKilledDaemonIsNotAPredecessor(t *testing.T) {
	prior := &predecessor{state: client.RunState{PID: 4242}, there: true, alive: false}
	if err := WaitForPredecessor(context.Background(), HandoverOptions{
		Read:  prior.read,
		Alive: prior.isAlive,
		Self:  99,
	}); err != nil {
		t.Fatalf("starting after a killed daemon returned %v", err)
	}
}

// FR-034, FR-054a: two daemons on one machine each report their own free slots and each ask for
// work on the same workplaces, so the machine quietly runs up to twice the ceiling its operator
// set. Neither process is doing anything wrong, which is what makes it invisible afterwards.
func TestASecondDaemonRefusesToRunBesideOneThatIsStaying(t *testing.T) {
	prior := &predecessor{state: client.RunState{PID: 4242}, there: true, alive: true}

	err := WaitForPredecessor(context.Background(), HandoverOptions{
		Read:  prior.read,
		Alive: prior.isAlive,
		Self:  99,
		Sleep: func(context.Context, time.Duration) error {
			t.Error("the second daemon waited for a daemon that is not leaving")
			return nil
		},
	})

	if !errors.Is(err, ErrAnotherDaemonIsRunning) {
		t.Fatalf("a second start returned %v, want a refusal", err)
	}
	if !strings.Contains(err.Error(), "4242") {
		t.Errorf("the refusal does not name the process holding the machine: %v", err)
	}
}

// The upgrade itself: stop the old daemon, swap the binary, start the new one. The old one is
// finishing the runs it already took, and the new one waits rather than registering on top of it.
func TestAnArrivingDaemonWaitsForOneThatIsOnItsWayOut(t *testing.T) {
	clock := &testClock{at: time.Unix(0, 0)}
	prior := &predecessor{
		state: client.RunState{PID: 4242, LeavingAt: time.Unix(0, 0)},
		there: true,
		alive: true,
	}
	told := 0

	err := WaitForPredecessor(context.Background(), HandoverOptions{
		Read: func() (client.RunState, bool, error) {
			if prior.reads >= 2 {
				prior.there = false
			}
			return prior.read()
		},
		Alive:    prior.isAlive,
		Self:     99,
		Patience: time.Minute,
		Check:    time.Second,
		Waiting:  func(int) { told++ },
		Now:      clock.now,
		Sleep:    clock.advance(time.Second),
	})

	if err != nil {
		t.Fatalf("waiting for a leaving daemon returned %v", err)
	}
	if told != 1 {
		t.Errorf("the operator was told %d times that the start is waiting, want once", told)
	}
}

func TestAPredecessorThatNeverGoesIsGivenUpOnRatherThanWaitedForForever(t *testing.T) {
	clock := &testClock{at: time.Unix(0, 0)}
	prior := &predecessor{
		state: client.RunState{PID: 4242, LeavingAt: time.Unix(0, 0)},
		there: true,
		alive: true,
	}

	err := WaitForPredecessor(context.Background(), HandoverOptions{
		Read:     prior.read,
		Alive:    prior.isAlive,
		Self:     99,
		Patience: 10 * time.Second,
		Check:    time.Second,
		Now:      clock.now,
		Sleep:    clock.advance(time.Second),
	})

	if err == nil {
		t.Fatal("a predecessor that never left was waited for forever")
	}
	if !strings.Contains(err.Error(), "4242") {
		t.Errorf("giving up did not name the process still there: %v", err)
	}
}

// A daemon restarted so fast the operating system handed it the same process id must not decide
// it is its own predecessor and wait for itself.
func TestADaemonIsNeverItsOwnPredecessor(t *testing.T) {
	prior := &predecessor{state: client.RunState{PID: 99}, there: true, alive: true}
	if err := WaitForPredecessor(context.Background(), HandoverOptions{
		Read:  prior.read,
		Alive: prior.isAlive,
		Self:  99,
	}); err != nil {
		t.Fatalf("a daemon waited for itself: %v", err)
	}
}

// The number an arriving daemon waits is derived from what the outgoing one is entitled to
// spend, so raising the drain on a machine raises this without the operator knowing it exists.
func TestTheWaitIsLongerThanEverythingThePredecessorMaySpend(t *testing.T) {
	for _, drain := range []time.Duration{DefaultDrainPatience, 30 * time.Minute} {
		if got := HandoverPatience(drain); got <= drain+DefaultGoodbyeGrace {
			t.Errorf(
				"HandoverPatience(%s) = %s, want more than the %s the predecessor may spend",
				drain, got, drain+DefaultGoodbyeGrace,
			)
		}
	}
	if HandoverPatience(0) != HandoverPatience(DefaultDrainPatience) {
		t.Error("an unset drain gives a different wait from the default drain")
	}
}
