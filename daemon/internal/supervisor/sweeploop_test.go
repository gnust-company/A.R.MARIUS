package supervisor

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// sweeps records what a loop did, safely enough to be read from the test goroutine.
type sweeps struct {
	mu       sync.Mutex
	at       []time.Time
	reported []error
	swept    []execenv.Report
}

func (s *sweeps) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.at)
}

func TestTheFirstSweepHappensWithoutWaitingOutAnInterval(t *testing.T) {
	// A machine coming back from a week switched off is the case this exists for. Making it
	// wait two hours adds that delay to precisely the moment there is most to reclaim.
	done := make(chan struct{})
	var seen sweeps
	ticks := make(chan time.Time)

	go func() {
		defer close(done)
		_ = RunSweepLoop(sweptOnce(t, &seen, 1), SweepOptions{
			Interval: time.Hour,
			Sweep: func(_ context.Context, now time.Time) (execenv.Report, error) {
				seen.mu.Lock()
				seen.at = append(seen.at, now)
				seen.mu.Unlock()
				return execenv.Report{}, nil
			},
			Tick: func(time.Duration) <-chan time.Time { return ticks },
		})
	}()

	<-done
	if seen.count() != 1 {
		t.Fatalf("swept %d times before the first tick, want 1", seen.count())
	}
}

func TestASweepHappensAgainOnEveryTick(t *testing.T) {
	ticks := make(chan time.Time)
	var seen sweeps
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	done := make(chan struct{})

	go func() {
		defer close(done)
		_ = RunSweepLoop(ctx, SweepOptions{
			Interval: time.Hour,
			Sweep: func(_ context.Context, now time.Time) (execenv.Report, error) {
				seen.mu.Lock()
				seen.at = append(seen.at, now)
				seen.mu.Unlock()
				return execenv.Report{}, nil
			},
			Tick: func(time.Duration) <-chan time.Time { return ticks },
		})
	}()

	for range 3 {
		ticks <- time.Now()
	}
	until(t, func() bool { return seen.count() >= 4 })
	stop()
	<-done

	if seen.count() < 4 {
		t.Fatalf("swept %d times, want the first one plus three ticks", seen.count())
	}
}

func TestTheLoopAsksForTheIntervalItWasGiven(t *testing.T) {
	asked := make(chan time.Duration, 1)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()

	go func() {
		_ = RunSweepLoop(ctx, SweepOptions{
			Interval: 37 * time.Minute,
			Tick: func(d time.Duration) <-chan time.Time {
				select {
				case asked <- d:
				default:
				}
				return make(chan time.Time)
			},
		})
	}()

	select {
	case got := <-asked:
		if got != 37*time.Minute {
			t.Fatalf("waited %s between sweeps, want the interval it was given", got)
		}
	case <-time.After(time.Second):
		t.Fatal("the loop never waited for anything")
	}
}

func TestAnUnsetIntervalTakesTheTwoHourDefault(t *testing.T) {
	asked := make(chan time.Duration, 1)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()

	go func() {
		_ = RunSweepLoop(ctx, SweepOptions{
			Tick: func(d time.Duration) <-chan time.Time {
				select {
				case asked <- d:
				default:
				}
				return make(chan time.Time)
			},
		})
	}()

	select {
	case got := <-asked:
		if got != execenv.DefaultSweepInterval {
			t.Fatalf("waited %s, want %s", got, execenv.DefaultSweepInterval)
		}
	case <-time.After(time.Second):
		t.Fatal("the loop never waited for anything")
	}
}

func TestASweepThatCouldNotFinishIsReportedAndTheLoopCarriesOn(t *testing.T) {
	// The usual reason is that the server could not be reached to ask about tasks — a laptop
	// off wifi. Stopping the loop over that would mean a machine that lost its network for an
	// hour never reclaims disk again until it is restarted.
	ticks := make(chan time.Time)
	var seen sweeps
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	done := make(chan struct{})
	boom := errors.New("no route to the server")

	go func() {
		defer close(done)
		_ = RunSweepLoop(ctx, SweepOptions{
			Sweep: func(_ context.Context, now time.Time) (execenv.Report, error) {
				seen.mu.Lock()
				seen.at = append(seen.at, now)
				seen.mu.Unlock()
				return execenv.Report{Removed: []string{"/work/task-1"}}, boom
			},
			Report: func(err error) {
				seen.mu.Lock()
				seen.reported = append(seen.reported, err)
				seen.mu.Unlock()
			},
			Swept: func(r execenv.Report) {
				seen.mu.Lock()
				seen.swept = append(seen.swept, r)
				seen.mu.Unlock()
			},
			Tick: func(time.Duration) <-chan time.Time { return ticks },
		})
	}()

	ticks <- time.Now()
	ticks <- time.Now()
	until(t, func() bool { return seen.count() >= 3 })
	stop()
	<-done

	seen.mu.Lock()
	defer seen.mu.Unlock()
	if len(seen.at) < 3 {
		t.Fatalf("a failing sweep stopped the loop after %d sweeps", len(seen.at))
	}
	if len(seen.reported) < 3 {
		t.Fatalf("%d failures reported out of %d sweeps", len(seen.reported), len(seen.at))
	}
	// What a half-finished sweep did manage to remove is exactly what an operator staring at
	// a full disk needs told.
	if len(seen.swept) == 0 || len(seen.swept[0].Removed) != 1 {
		t.Fatalf("a failed sweep threw away its own report: %#v", seen.swept)
	}
}

func TestTheLoopStopsWhenTheContextDoes(t *testing.T) {
	ctx, stop := context.WithCancel(context.Background())
	stop()

	done := make(chan error, 1)
	go func() {
		done <- RunSweepLoop(ctx, SweepOptions{
			Tick: func(time.Duration) <-chan time.Time { return make(chan time.Time) },
		})
	}()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("an orderly stop came back as a failure: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("the loop did not stop when the context did")
	}
}

func TestAskingTheServerTurnsTheWireIntoWhatTheSweepReads(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"tasks":[
			{"task_id":"task-1","closed":true,"last_activity":"2026-08-20T10:00:00Z"}]}`))
	}))
	t.Cleanup(server.Close)

	asking := Asking{Session: client.Session{Server: server.URL, Token: "armd_secret"}}
	states, err := asking.Lookup(context.Background(), []string{"task-1", "task-2"})
	if err != nil {
		t.Fatalf("asking: %v", err)
	}

	if !states["task-1"].Closed {
		t.Error("a closed task arrived at the sweep as open")
	}
	if !states["task-1"].LastActivity.Equal(time.Date(2026, 8, 20, 10, 0, 0, 0, time.UTC)) {
		t.Errorf("last activity = %s", states["task-1"].LastActivity)
	}
	if _, present := states["task-2"]; present {
		t.Error("a task the server did not mention arrived as a state")
	}
}

func TestAFailedAskIsAFailedLookupAndNotAnEmptyOne(t *testing.T) {
	// An empty answer means *the server knows none of these tasks*, which is the sweep's cue
	// to start the orphan clock. A server that could not be reached must never look like that.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	t.Cleanup(server.Close)

	asking := Asking{Session: client.Session{Server: server.URL, Token: "armd_secret"}}
	states, err := asking.Lookup(context.Background(), []string{"task-1"})
	if err == nil {
		t.Fatal("a server that answered 502 came back as a successful lookup")
	}
	if states != nil {
		t.Fatalf("a failed lookup handed back %d states", len(states))
	}
}

// sweptOnce hands back a context that is cancelled as soon as the loop has swept n times, so a
// test can watch the loop's own first move without racing it.
func sweptOnce(t *testing.T, seen *sweeps, n int) context.Context {
	t.Helper()
	ctx, stop := context.WithCancel(context.Background())
	go func() {
		until(t, func() bool { return seen.count() >= n })
		stop()
	}()
	t.Cleanup(stop)
	return ctx
}

// until waits for something the loop does on its own goroutine. A tick handed to the loop is
// received before the sweep it causes has finished, so a test that stops the loop the instant
// its last tick is accepted is a test racing the thing it is measuring.
func until(t *testing.T, ready func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for !ready() {
		if time.Now().After(deadline) {
			t.Error("waited two seconds for the loop to catch up")
			return
		}
		time.Sleep(time.Millisecond)
	}
}
