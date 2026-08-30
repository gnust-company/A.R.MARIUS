package supervisor

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/runtime"
)

// ErrRunNotOurs is what the server answers when this machine writes about a run it no longer
// holds (FR-059). It is not a transport failure and must never be retried: the run has been
// given to somebody else, or taken back, and everything this machine does from here on is
// work that will be thrown away.
//
// The same value the client returns, rather than a second one of the same name. Two sentinels
// would compare equal to nothing and the check would silently stop matching — which here means
// a run carrying on after the server has said it is not ours.
var ErrRunNotOurs = client.ErrRunNotOurs

// ErrRefusedForGood is the server having read a batch and rejected it — a shape it will not
// take, whoever sends it and however many times (FR-047).
//
// Same value as the client's, for the same reason as above.
var ErrRefusedForGood = client.ErrRefusedForGood

// How often a batch goes up while a run is producing events.
//
// The events have to travel **during** the run, not after it (FR-015), and this is the whole
// of what that means in practice: the record on the server is at most this far behind what the
// agent has done. Small enough that a person watching the run sees it move; large enough that
// an agent producing a line at a time is not one HTTP call per line.
const flushEvery = 250 * time.Millisecond

// maxPending is how many events are held while the server cannot be reached.
//
// A bound rather than a queue that grows: an unreachable server is exactly the case where the
// agent keeps working and nobody is draining anything, and the machine this runs on belongs to
// the operator. What overflows is **counted and confessed** rather than quietly discarded —
// once the road opens again the record says how many events fell in the hole, because a gap
// that does not say it is a gap reads as an agent that did nothing (FR-047).
const maxPending = 1000

// stream carries one run's events to the server while the run is still going.
//
// It sits between the CLI reader, which must not be made to wait, and an HTTP call, which can
// take as long as the network feels like. Everything that can be slow happens in the flusher
// goroutine; `record` only takes a lock, appends, and returns.
type stream struct {
	runID  string
	ledger Ledger
	report func(error)
	// lost is called the one time the server says this run is not ours. Stopping the run is
	// the caller's business — this only says the news arrived.
	lost func()

	woken chan struct{}

	mu      sync.Mutex
	pending []Recorded
	// seq is the number already used. The next event takes seq+1, which is why it starts one
	// below where the server said this machine's numbering begins.
	seq int
	// dropped and refused are the two ways an event can fail to reach the record, counted
	// apart because they are not the same news. `dropped` is this machine outrunning the road
	// — the events existed and the buffer was full. `refused` is the server having read them
	// and said no. Told apart here so they can be told apart on screen: one says *the road was
	// too slow*, the other *these two programs do not agree on what an event is*, and a reader
	// shown one figure could act on the wrong one (FR-047).
	dropped int
	refused int
	// lastAt is when the agent last produced anything, which is the only clock the silence
	// threshold runs on (FR-031). Written here rather than in the watchdog so that there is
	// one answer to *when did this run last say something*.
	lastAt time.Time
	gone   bool
}

// newStream opens the road for one run. `from` is the number the server said this machine's
// own events start at; anything below one is read as one, which is what a server that says
// nothing about it means.
func newStream(runID string, from int, ledger Ledger, report func(error), lost func(), now time.Time) *stream {
	if from < 1 {
		from = 1
	}
	return &stream{
		runID:  runID,
		ledger: ledger,
		report: report,
		lost:   lost,
		woken:  make(chan struct{}, 1),
		seq:    from - 1,
		lastAt: now,
	}
}

// record takes one event from the CLI reader. It never blocks on anything but its own lock.
func (s *stream) record(event runtime.Event, now time.Time) {
	s.mu.Lock()
	s.lastAt = now
	if len(s.pending) >= maxPending {
		s.dropped++
		s.mu.Unlock()
		return
	}
	s.seq++
	s.pending = append(s.pending, Recorded{
		Seq:            s.seq,
		Type:           event.Type,
		Payload:        event.Payload,
		Truncated:      event.Truncated,
		OriginalBytes:  event.OriginalBytes,
		OmissionReason: event.OmissionReason,
		Redacted:       event.Redacted,
	})
	s.mu.Unlock()

	// Non-blocking: a wake-up already waiting is a flush already coming.
	select {
	case s.woken <- struct{}{}:
	default:
	}
}

// quietSince answers when the agent last produced anything.
func (s *stream) quietSince() time.Time {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.lastAt
}

// deliver keeps sending until the run's context ends, then sends whatever is left.
func (s *stream) deliver(ctx context.Context) {
	ticker := time.NewTicker(flushEvery)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			// The run is over — or this daemon is being stopped. Either way the tail of the
			// record is worth one more call on a context of its own: the one that just ended
			// would refuse it, and what is in the buffer is the end of the run, which is the
			// part anybody reading it afterwards most wants.
			last, cancel := context.WithTimeout(context.WithoutCancel(ctx), flushDeadline)
			defer cancel()
			s.flush(last)
			return
		case <-s.woken:
			s.flush(ctx)
		case <-ticker.C:
			s.flush(ctx)
		}
	}
}

// flushDeadline bounds the final send, so a run cannot be held open by a server that has
// stopped answering.
const flushDeadline = 10 * time.Second

// flush sends everything buffered, once.
//
// A batch that fails **transiently** stays in the buffer and goes up with the next one. That is
// what makes a lost reply harmless: the same events are sent again under the same sequence
// numbers, and the server, which keys on them, writes each one once (FR-045).
//
// A batch the server has *read and rejected* is a different case and is not retried at all —
// see `push`.
func (s *stream) flush(ctx context.Context) {
	s.mu.Lock()
	if s.gone || len(s.pending) == 0 {
		s.mu.Unlock()
		return
	}
	batch := make([]Recorded, len(s.pending))
	copy(batch, s.pending)
	s.mu.Unlock()

	settled, refused, err := s.push(ctx, batch)
	if errors.Is(err, ErrRunNotOurs) {
		s.mu.Lock()
		// Nothing more is sent about a run that is not ours: every later call would be
		// refused for the same reason, and each one asks the server to say so again.
		s.gone, s.pending = true, nil
		s.mu.Unlock()
		s.lost()
		return
	}
	if err != nil {
		s.report(err)
	}
	if settled == 0 {
		return
	}

	s.mu.Lock()
	s.pending = s.pending[settled:]
	s.refused += refused
	// Read out and cleared together with the trim, under the one lock that also protects the
	// buffer: a count taken outside it could be cleared by a flush that never wrote it down.
	fellBehind, wereRefused := s.dropped, s.refused
	s.dropped, s.refused = 0, 0
	s.mu.Unlock()

	// Written directly rather than through `record`: this is the record admitting to a hole in
	// itself, and a hole big enough to overflow the buffer is exactly the case where one more
	// ordinary event would be dropped too.
	s.confess(fellBehind, "events_dropped")
	s.confess(wereRefused, "events_refused")
}

// push sends one batch and answers how much of it is finished with.
//
// `settled` counts events from the front that need never be sent again — written by the server,
// or dropped here because it will never take them. `refused` is how many of those were dropped.
//
// The bisection is what keeps one bad event from killing a run's whole record. The server
// refuses a batch as a whole and does not say which event offended it (it cannot: writing the
// acceptable half would leave a hole at a number nothing can ever fill). So this halves the
// batch and asks again, which finds the offending events without the server having to name
// them. Every call it makes retires at least one event for good, so it cannot come back round:
// what a refusal costs is one pass, not a loop.
//
// Bounded by the buffer, and in practice far below it — a full buffer means the road was shut,
// and a shut road answers with a transport failure rather than a refusal.
func (s *stream) push(ctx context.Context, batch []Recorded) (settled, refused int, err error) {
	if len(batch) == 0 {
		return 0, 0, nil
	}
	err = s.ledger.Record(ctx, s.runID, batch)
	switch {
	case err == nil:
		return len(batch), 0, nil
	case !errors.Is(err, ErrRefusedForGood):
		// Includes ErrRunNotOurs, which the caller acts on, and every transport failure,
		// which stays in the buffer and is tried again.
		return 0, 0, err
	}

	if len(batch) == 1 {
		s.report(fmt.Errorf(
			"the server would not take event %d (%s), so it was dropped: %w",
			batch[0].Seq, batch[0].Type, err,
		))
		if batch[0].confession {
			// A confession the server also refuses is not confessed again. Counting it would
			// make the next flush write another one, and the machine would spend the rest of
			// the run talking about its own silence.
			return 1, 0, nil
		}
		return 1, 1, nil
	}

	half := len(batch) / 2
	settled, refused, err = s.push(ctx, batch[:half])
	if err != nil {
		return settled, refused, err
	}
	more, alsoRefused, err := s.push(ctx, batch[half:])
	return settled + more, refused + alsoRefused, err
}

// confess adds one line to the record saying how many events are missing and why.
//
// A code and a count, never a sentence — the screen owns the wording (Constitution VII).
func (s *stream) confess(count int, code string) {
	if count <= 0 {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seq++
	s.pending = append(s.pending, Recorded{
		Seq:  s.seq,
		Type: runtime.EventRunError,
		Payload: map[string]any{
			"code":  code,
			"count": count,
		},
		confession: true,
	})
}
