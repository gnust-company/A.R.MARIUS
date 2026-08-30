package supervisor

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	armruntime "github.com/gnust-company/armarius-daemon/internal/runtime"
)

// ── a server with opinions about particular events ───────────────────────────

type picky struct {
	mu sync.Mutex
	// poison names the sequence numbers this server will never accept, whatever else is in
	// the batch with them. It refuses the batch as a whole, the way the real one does.
	poison map[int]bool
	// unreachable, while set, is the road being shut rather than the server saying no.
	unreachable error

	calls int
	wrote []Recorded
}

func aPickyServer(refuses ...int) *picky {
	p := &picky{poison: map[int]bool{}}
	for _, seq := range refuses {
		p.poison[seq] = true
	}
	return p
}

func (p *picky) Start(context.Context, string, string) (bool, error) { return true, nil }
func (p *picky) Finish(context.Context, string, Conclusion) error    { return nil }

func (p *picky) Record(_ context.Context, _ string, events []Recorded) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.calls++
	if p.unreachable != nil {
		return p.unreachable
	}
	for _, event := range events {
		if p.poison[event.Seq] {
			return fmt.Errorf("%w: event %d", ErrRefusedForGood, event.Seq)
		}
	}
	p.wrote = append(p.wrote, events...)
	return nil
}

func (p *picky) written() []Recorded {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]Recorded(nil), p.wrote...)
}

func (p *picky) asked() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.calls
}

// aStream wires one up with the failures collected rather than dropped, so a test can say what
// the machine complained about.
func aStream(t *testing.T, server Ledger) (*stream, func() []error) {
	t.Helper()
	var mu sync.Mutex
	var moans []error
	s := newStream("run-1", 1, server, func(err error) {
		mu.Lock()
		defer mu.Unlock()
		moans = append(moans, err)
	}, func() {}, time.Now())
	return s, func() []error {
		mu.Lock()
		defer mu.Unlock()
		return append([]error(nil), moans...)
	}
}

func say(s *stream, howMany int) {
	for i := 0; i < howMany; i++ {
		s.record(armruntime.Event{
			Type:    armruntime.EventAssistantMessage,
			Payload: map[string]any{"text": fmt.Sprintf("line %d", i)},
		}, time.Now())
	}
}

func seqsIn(events []Recorded) []int {
	got := make([]int, 0, len(events))
	for _, e := range events {
		got = append(got, e.Seq)
	}
	return got
}

func confessions(events []Recorded) map[string]int {
	said := map[string]int{}
	for _, e := range events {
		if e.Type != armruntime.EventRunError {
			continue
		}
		code, _ := e.Payload["code"].(string)
		count, _ := e.Payload["count"].(int)
		said[code] = count
	}
	return said
}

// ── what a refusal must cost ─────────────────────────────────────────────────

// The buffer is first-in-first-out and the server refuses a batch whole, so one event it will
// never take sits at the head of the queue and everything behind it dies with it. That is the
// whole of the bug: the run works, produces a full record, and the record arrives empty.
func TestOneEventTheServerWillNotTakeDoesNotTakeTheRestWithIt(t *testing.T) {
	server := aPickyServer(3)
	s, _ := aStream(t, server)
	say(s, 5)

	s.flush(context.Background())

	if got := seqsIn(server.written()); fmt.Sprint(got) != "[1 2 4 5]" {
		t.Fatalf("everything but the refused event must land, got %v", got)
	}
}

// And it must not be asked about again. The server's answer is settled — asking a second time
// gets the same refusal, and asking every 250ms gets it forever.
func TestTheServerIsNotAskedTwiceAboutABatchItHasAlreadyRefused(t *testing.T) {
	server := aPickyServer(3)
	s, _ := aStream(t, server)
	say(s, 5)

	s.flush(context.Background()) // finds the refused event and drops it
	s.flush(context.Background()) // sends the confession it left behind
	settled := server.asked()
	s.flush(context.Background())
	s.flush(context.Background())

	if server.asked() != settled {
		t.Fatalf("the machine went back to ask again: %d calls, then %d", settled, server.asked())
	}
	s.mu.Lock()
	left := len(s.pending)
	s.mu.Unlock()
	if left != 0 {
		t.Fatalf("nothing should be left waiting, got %d events", left)
	}
	for _, e := range server.written() {
		if e.Seq == 3 {
			t.Fatal("the refused event was sent again under its own number")
		}
	}
}

// A hole in the record has to say it is a hole, or it reads as an agent that did less than it
// did (FR-047). The confession is what makes the gap visible, and it must reach the record in
// the very case it exists for — which, before this, it could not: it was written only after a
// batch went up cleanly, and a batch containing the refused event never did.
func TestTheRecordSaysHowManyEventsTheServerWouldNotTake(t *testing.T) {
	server := aPickyServer(2, 4)
	s, _ := aStream(t, server)
	say(s, 5)

	s.flush(context.Background())
	s.flush(context.Background())

	if said := confessions(server.written())["events_refused"]; said != 2 {
		t.Fatalf("the record must own up to both refused events, it said %d", said)
	}
}

// Two ways to lose an event, two different things to tell the reader. The buffer overflowing is
// this machine outrunning the road; a refusal is the two programs disagreeing about what an
// event is. One number covering both would send a reader after the wrong problem.
func TestFallingBehindAndBeingRefusedAreConfessedApart(t *testing.T) {
	server := aPickyServer(1)
	s, _ := aStream(t, server)
	say(s, maxPending+3)

	s.flush(context.Background())
	s.flush(context.Background())

	said := confessions(server.written())
	if said["events_dropped"] != 3 {
		t.Fatalf("three events fell off the end of the buffer, it said %d", said["events_dropped"])
	}
	if said["events_refused"] != 1 {
		t.Fatalf("one event was refused, it said %d", said["events_refused"])
	}
}

// A server that refuses everything refuses the confession too. Counting that as one more lost
// event would make the next flush write another confession about it, and the machine would
// spend the rest of the run talking about its own silence.
func TestAConfessionTheServerAlsoRefusesIsNotConfessedAgain(t *testing.T) {
	server := aPickyServer()
	s, _ := aStream(t, server)
	say(s, 2)
	// Everything, including anything written from here on.
	server.mu.Lock()
	for seq := 1; seq <= 20; seq++ {
		server.poison[seq] = true
	}
	server.mu.Unlock()

	for i := 0; i < 8; i++ {
		s.flush(context.Background())
	}

	s.mu.Lock()
	left, used := len(s.pending), s.seq
	s.mu.Unlock()
	if left != 0 {
		t.Fatalf("the machine is still holding %d events to talk about", left)
	}
	if used > 3 {
		t.Fatalf("it kept writing confessions about its confessions: %d events numbered", used)
	}
}

// The distinction has to hold from the other side too: a road that is merely shut keeps the
// batch, because the same batch sent later is the same events and the server will take them.
func TestAShutRoadKeepsTheBatchForTheNextTry(t *testing.T) {
	server := aPickyServer()
	server.unreachable = errors.New("dial tcp: connection refused")
	s, moans := aStream(t, server)
	say(s, 4)

	s.flush(context.Background())

	s.mu.Lock()
	left := len(s.pending)
	s.mu.Unlock()
	if left != 4 {
		t.Fatalf("a failed call must leave the events where they were, %d left", left)
	}
	if len(moans()) == 0 {
		t.Fatal("nothing was reported about a road that is shut")
	}

	server.mu.Lock()
	server.unreachable = nil
	server.mu.Unlock()
	s.flush(context.Background())

	if got := seqsIn(server.written()); fmt.Sprint(got) != "[1 2 3 4]" {
		t.Fatalf("the same events must go up once the road opens, got %v", got)
	}
}

// A run taken back is not a refusal of the bytes: the machine stops the run rather than
// dropping a few events and carrying on (FR-059).
func TestARunTakenBackStopsTheRunRatherThanDroppingEvents(t *testing.T) {
	server := aPickyServer()
	server.unreachable = ErrRunNotOurs
	var told bool
	s := newStream("run-1", 1, server, func(error) {}, func() { told = true }, time.Now())
	say(s, 3)

	s.flush(context.Background())

	if !told {
		t.Fatal("nobody was told the run is no longer this machine's")
	}
	s.mu.Lock()
	left, gone := len(s.pending), s.gone
	s.mu.Unlock()
	if !gone || left != 0 {
		t.Fatalf("the stream must shut: gone=%v, %d events still queued", gone, left)
	}
}
