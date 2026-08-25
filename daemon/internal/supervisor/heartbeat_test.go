package supervisor

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

// beats collects what a heartbeat sent, and stops it after a given number of beats so a test
// finishes in microseconds rather than in minutes.
type beats struct {
	mu       sync.Mutex
	sent     []Beat
	waited   []time.Duration
	failures []error
	stopAt   int
	cancel   context.CancelFunc
	reply    Reply
	sendErr  error
}

func (b *beats) options() HeartbeatOptions {
	return HeartbeatOptions{
		Interval: 15 * time.Second,
		State: func() Beat {
			b.mu.Lock()
			defer b.mu.Unlock()
			// One slot fewer with every beat, so a test can tell a fresh reading from a
			// remembered one.
			return Beat{FreeSlots: 5 - len(b.sent)}
		},
		Send: func(_ context.Context, beat Beat) (Reply, error) {
			b.mu.Lock()
			b.sent = append(b.sent, beat)
			count := len(b.sent)
			b.mu.Unlock()
			if count >= b.stopAt {
				b.cancel()
			}
			return b.reply, b.sendErr
		},
		Report: func(err error) {
			b.mu.Lock()
			defer b.mu.Unlock()
			b.failures = append(b.failures, err)
		},
		Sleep: func(ctx context.Context, d time.Duration) error {
			b.mu.Lock()
			b.waited = append(b.waited, d)
			b.mu.Unlock()
			if ctx.Err() != nil {
				return ctx.Err()
			}
			return nil
		},
	}
}

// A machine that has just come up is reachable now. Waiting one interval before saying so
// leaves the server holding a linked machine it has never heard from.
func TestTheFirstBeatGoesOutBeforeTheFirstWait(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	b := &beats{stopAt: 1, cancel: cancel}

	if err := RunHeartbeat(ctx, b.options()); err != nil {
		t.Fatalf("an orderly stop is not a failure: %v", err)
	}

	if len(b.sent) != 1 {
		t.Fatalf("want one beat, got %d", len(b.sent))
	}
	if len(b.waited) != 1 || b.waited[0] != 15*time.Second {
		t.Errorf("waits = %v, want the one interval after the beat", b.waited)
	}
}

// The free-slot count is the whole reason the beat carries a number (FR-055c). A number read
// once at startup is wrong from the second beat onwards, and the server would hand work to a
// machine that filled up ten minutes ago.
func TestFreeSlotsAreReadFreshOnEveryBeat(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	b := &beats{stopAt: 3, cancel: cancel}

	_ = RunHeartbeat(ctx, b.options())

	if len(b.sent) != 3 {
		t.Fatalf("want three beats, got %d", len(b.sent))
	}
	for i, want := range []int{5, 4, 3} {
		if b.sent[i].FreeSlots != want {
			t.Errorf("beat %d carried %d free slots, want %d — the count was not re-read", i, b.sent[i].FreeSlots, want)
		}
	}
}

// A laptop that loses its wifi for an hour must be back in the workspace when the wifi returns.
// The conclusion that a machine is gone belongs to the server's missed-beat threshold and to
// nowhere else.
func TestABeatThatFailsIsReportedAndTheHeartKeepsBeating(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	b := &beats{stopAt: 4, cancel: cancel, sendErr: errors.New("dial tcp: network is unreachable")}

	if err := RunHeartbeat(ctx, b.options()); err != nil {
		t.Fatalf("a machine off the network is not a daemon that should exit: %v", err)
	}

	if len(b.sent) != 4 {
		t.Errorf("want the beat to have carried on, got %d beats", len(b.sent))
	}
	if len(b.failures) != 4 {
		t.Errorf("want every failed beat reported, got %d", len(b.failures))
	}
}

func TestTheAnswerIsHandedOn(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	b := &beats{stopAt: 1, cancel: cancel, reply: Reply{PendingWork: true, Cancel: []string{"run-2"}}}

	var got []Reply
	opts := b.options()
	opts.OnReply = func(r Reply) { got = append(got, r) }

	_ = RunHeartbeat(ctx, opts)

	if len(got) != 1 || !got[0].PendingWork || len(got[0].Cancel) != 1 {
		t.Errorf("the answer reached the caller as %+v", got)
	}
}

// A beat that failed carries no answer. Acting on the zero value would read a network error as
// the server saying there is no work and nothing to cancel.
func TestAFailedBeatHandsOnNoAnswer(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	b := &beats{stopAt: 2, cancel: cancel, sendErr: errors.New("no route to host")}

	called := 0
	opts := b.options()
	opts.OnReply = func(Reply) { called++ }

	_ = RunHeartbeat(ctx, opts)

	if called != 0 {
		t.Errorf("acted on %d answers that never arrived", called)
	}
}
