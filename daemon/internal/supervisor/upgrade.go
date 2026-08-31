package supervisor

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
)

// handoverSlack is what the arriving daemon allows on top of everything the outgoing one is
// entitled to spend. Not tuning: the two processes are reading the same clock through a file,
// and a wait that expires the instant the predecessor's own budget does would call a daemon
// that is exiting on time a daemon that overstayed.
const handoverSlack = 30 * time.Second

// HandoverPatience is how long a starting daemon waits for the one it is replacing.
//
// Derived from the outgoing daemon's own budget rather than picked, because that budget is what
// the predecessor is entitled to spend: it lets its runs finish (`drain`), then says goodbye,
// then exits. A patience shorter than that sum would give up on a predecessor doing exactly what
// it was asked to do, and the two daemons would then be running at once — which is the one
// outcome this whole file exists to prevent (FR-034, FR-054a).
//
// So an operator who lengthens the drain on their machine lengthens this by the same amount,
// without having to know this number exists.
func HandoverPatience(drain time.Duration) time.Duration {
	if drain <= 0 {
		drain = DefaultDrainPatience
	}
	return drain + DefaultGoodbyeGrace + handoverSlack
}

// ErrAnotherDaemonIsRunning is the answer when this machine already has a daemon that is not
// going anywhere.
//
// Refusing to start is the right answer rather than the cautious one. Two daemons on one config
// each report their own free slots and each ask for work on the same workplaces, so the machine
// quietly runs up to twice the ceiling its operator set (FR-008) — and neither process is doing
// anything wrong, which is what makes it so hard to see afterwards.
var ErrAnotherDaemonIsRunning = errors.New("another daemon is already running on this machine")

// HandoverOptions is what an arriving daemon needs in order to find out whether it is alone.
type HandoverOptions struct {
	// Read returns the state file the previous daemon left, and whether there was one. Handed
	// in rather than read here so a test can drive a predecessor that changes its mind.
	Read func() (client.RunState, bool, error)
	// Alive answers whether a process id is still running. Defaults to the real check.
	Alive func(pid int) bool
	// Self is this process's own id, so a state file naming us is not mistaken for a rival.
	Self int
	// Patience defaults to DefaultHandoverPatience.
	Patience time.Duration
	// Check is how often the state file is looked at again. Defaults to a second.
	Check time.Duration
	// Waiting is told, once, that this daemon is holding the door for the one on its way out.
	Waiting func(pid int)
	// Now and Sleep are the clock and the wait, injected for tests.
	Now   func() time.Time
	Sleep func(ctx context.Context, d time.Duration) error
}

// WaitForPredecessor holds a starting daemon back until the one before it has gone (FR-034).
//
// An upgrade is three steps — stop the old daemon, replace the binary, start the new one — and
// only the first of them is slow, because a daemon that is stopping is finishing the runs it
// already took. If the new process registers its workplaces in the middle of that, three things
// go wrong at once: the machine offers twice the slots it is allowed, both processes ask for the
// same work, and the outgoing daemon's goodbye arrives *after* the newcomer's registration and
// takes every workplace back down (FR-005). The machine ends up registered as having nothing.
//
// So the arriving daemon reads what the outgoing one wrote down, and there are exactly three
// answers worth telling apart:
//
//   - **Nothing there, or a state file with no process behind it.** Nobody holds this machine.
//     The second case also says something the operator wants to know — the previous daemon was
//     killed rather than stopped — and it is reported rather than passed over in silence.
//   - **A process that is on its way out.** This is the upgrade. Wait for it.
//   - **A process that is not going anywhere.** This is a second start, not an upgrade, and
//     waiting for it would be waiting forever. Refuse, and name the process holding the machine.
func WaitForPredecessor(ctx context.Context, opts HandoverOptions) error {
	opts = opts.withDefaults()

	deadline := opts.Now().Add(opts.Patience)
	told := false
	for {
		prior, holding, err := opts.predecessor()
		if err != nil {
			return err
		}
		if !holding {
			return nil
		}
		if !prior.Leaving() {
			return fmt.Errorf("%w (process %d)", ErrAnotherDaemonIsRunning, prior.PID)
		}
		if !told {
			opts.Waiting(prior.PID)
			told = true
		}
		if !opts.Now().Before(deadline) {
			return fmt.Errorf(
				"the daemon already on this machine (process %d) was still stopping after %s",
				prior.PID, opts.Patience,
			)
		}
		if err := opts.Sleep(ctx, opts.Check); err != nil {
			return err
		}
	}
}

// predecessor reads the state file and decides whether anybody is actually behind it.
//
// A file naming a process that is gone is not a predecessor. It is the trace of one that was
// killed — the state file is removed on an orderly stop, so its presence over a dead process id
// means exactly that — and there is nothing to wait for.
func (o HandoverOptions) predecessor() (client.RunState, bool, error) {
	state, found, err := o.Read()
	if err != nil {
		return client.RunState{}, false, err
	}
	if !found || state.PID == o.Self {
		return client.RunState{}, false, nil
	}
	if !o.Alive(state.PID) {
		return client.RunState{}, false, nil
	}
	return state, true, nil
}

func (o HandoverOptions) withDefaults() HandoverOptions {
	if o.Read == nil {
		o.Read = func() (client.RunState, bool, error) { return client.RunState{}, false, nil }
	}
	if o.Alive == nil {
		o.Alive = client.ProcessAlive
	}
	if o.Patience <= 0 {
		o.Patience = HandoverPatience(DefaultDrainPatience)
	}
	if o.Check <= 0 {
		o.Check = time.Second
	}
	if o.Waiting == nil {
		o.Waiting = func(int) {}
	}
	if o.Now == nil {
		o.Now = time.Now
	}
	if o.Sleep == nil {
		o.Sleep = sleep
	}
	return o
}
