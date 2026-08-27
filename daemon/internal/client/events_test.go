package client

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

// sseServer holds a connection open and writes whatever the test tells it to, when the test
// tells it to. A canned body would prove only that a finished response can be parsed; what
// is worth proving is that a nudge reaches the loop while the road is still open.
type sseServer struct {
	*httptest.Server
	lines  chan string
	mu     sync.Mutex
	opens  int
	auth   string
	accept string
}

func serverThatStreams(t *testing.T, status int) *sseServer {
	t.Helper()
	s := &sseServer{lines: make(chan string, 16)}
	s.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		s.opens++
		s.auth = r.Header.Get("Authorization")
		s.accept = r.Header.Get("Accept")
		s.mu.Unlock()
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(status)
		if status != http.StatusOK {
			return
		}
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Error("the test server cannot stream")
			return
		}
		flusher.Flush()
		for {
			select {
			case <-r.Context().Done():
				return
			case line, alive := <-s.lines:
				if !alive {
					return
				}
				_, _ = fmt.Fprint(w, line)
				flusher.Flush()
			}
		}
	}))
	t.Cleanup(s.Close)
	return s
}

func (s *sseServer) openCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.opens
}

// A client with no deadline of its own: the point of this road is that it lasts.
func streamingSession(server *sseServer) Session {
	return Session{Server: server.URL, Token: "armd_secret", HTTPClient: &http.Client{}}
}

func waitForNudge(t *testing.T, nudges <-chan struct{}) {
	t.Helper()
	select {
	case <-nudges:
	case <-time.After(3 * time.Second):
		t.Fatal("no nudge arrived down the push road")
	}
}

func TestAPendingWorkEventBecomesANudge(t *testing.T) {
	server := serverThatStreams(t, http.StatusOK)
	nudges := make(chan struct{}, 4)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() { _ = streamingSession(server).WatchEvents(ctx, WatchOptions{Nudge: nudges}) }()

	server.lines <- "event: pending_work\ndata: {\"workplace_id\":\"wp-1\"}\n\n"
	waitForNudge(t, nudges)
}

// The one thing the road is not allowed to become. A daemon that reads a run out of the
// message is a daemon being *told* to run something, and two messages arriving together then
// produce two runs — precisely what the one-door claim exists to prevent (FR-055a).
func TestTheNudgeIsActedOnWithoutReadingItsPayload(t *testing.T) {
	server := serverThatStreams(t, http.StatusOK)
	nudges := make(chan struct{}, 4)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() { _ = streamingSession(server).WatchEvents(ctx, WatchOptions{Nudge: nudges}) }()

	// No data line at all: the machine still goes and asks, because asking is the only way
	// it ever learns anything.
	server.lines <- "event: pending_work\n\n"
	waitForNudge(t, nudges)
}

func TestTheRoadCarriesTheMachineToken(t *testing.T) {
	server := serverThatStreams(t, http.StatusOK)
	nudges := make(chan struct{}, 4)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() { _ = streamingSession(server).WatchEvents(ctx, WatchOptions{Nudge: nudges}) }()

	server.lines <- "event: pending_work\n\n"
	waitForNudge(t, nudges)

	server.mu.Lock()
	defer server.mu.Unlock()
	if server.auth != "Bearer armd_secret" {
		t.Fatalf("the road must be opened with this machine's own token, got %q", server.auth)
	}
	if server.accept != "text/event-stream" {
		t.Fatalf("asked for %q rather than an event stream", server.accept)
	}
}

// Keep-alives and events this build does not know are both noise, and noise must not send the
// machine off to ask. An ask costs a round trip that can only come back empty.
func TestKeepAlivesAndUnknownEventsAreNotNudges(t *testing.T) {
	server := serverThatStreams(t, http.StatusOK)
	nudges := make(chan struct{}, 4)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() { _ = streamingSession(server).WatchEvents(ctx, WatchOptions{Nudge: nudges}) }()

	server.lines <- ": ping - 2026-08-26T10:00:00Z\n\n"
	server.lines <- "event: something_new\ndata: {}\n\n"
	select {
	case <-nudges:
		t.Fatal("a keep-alive or an unknown event sent the machine off to ask")
	case <-time.After(300 * time.Millisecond):
	}

	// …and the road still works afterwards, so the reader has not been left mid-event.
	server.lines <- "event: pending_work\n\n"
	waitForNudge(t, nudges)
}

// A nudge nobody is waiting for is dropped, not queued behind them. The loop that reads
// these is about to ask anyway; a backlog would make it ask again for work it has already
// had its chance at. What must never happen is the road wedging because the far end of the
// channel is busy — a push road that can be stalled by a slow reader is worse than none.
func TestANudgeNobodyIsWaitingForDoesNotWedgeTheRoad(t *testing.T) {
	server := serverThatStreams(t, http.StatusOK)
	nudges := make(chan struct{}) // deliberately unbuffered, and deliberately unread
	ctx, stop := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- streamingSession(server).WatchEvents(ctx, WatchOptions{Nudge: nudges})
	}()

	for range 5 {
		server.lines <- "event: pending_work\n\n"
	}
	time.Sleep(100 * time.Millisecond)
	stop()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("an orderly stop is not a failure: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("the road wedged behind a nudge nobody was waiting for")
	}
}

func TestADroppedRoadIsReopened(t *testing.T) {
	server := serverThatStreams(t, http.StatusOK)
	nudges := make(chan struct{}, 4)
	waits := make(chan time.Duration, 8)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() {
		_ = streamingSession(server).WatchEvents(ctx, WatchOptions{
			Nudge: nudges,
			Tick: func(d time.Duration) <-chan time.Time {
				waits <- d
				return time.After(time.Millisecond)
			},
		})
	}()

	server.lines <- "event: pending_work\n\n"
	waitForNudge(t, nudges)
	close(server.lines) // the server hangs up

	// It comes back, and the work it missed while away is still there to be asked for.
	deadline := time.After(3 * time.Second)
	for server.openCount() < 2 {
		select {
		case <-deadline:
			t.Fatal("the road was never reopened")
		case <-time.After(10 * time.Millisecond):
		}
	}
}

// A road that has been up for hours and drops once must not be treated as a road that has
// never worked. Otherwise a single hiccup costs a minute of push every time.
func TestAWorkingRoadStartsItsWaitOverAfterADrop(t *testing.T) {
	// A server that opens the road properly and then hangs up at once: every attempt
	// *worked*, so every wait afterwards must be the short one.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		if flusher, ok := w.(http.Flusher); ok {
			flusher.Flush()
		}
	}))
	t.Cleanup(server.Close)

	waits := make(chan time.Duration, 8)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	session := Session{Server: server.URL, Token: "armd_secret", HTTPClient: &http.Client{}}
	go func() {
		_ = session.WatchEvents(ctx, WatchOptions{
			Nudge: make(chan struct{}, 4),
			Tick: func(d time.Duration) <-chan time.Time {
				waits <- d
				return time.After(time.Millisecond)
			},
		})
	}()

	first := <-waits
	second := <-waits
	if first != minReconnectDelay || second != minReconnectDelay {
		t.Fatalf("a road that opened each time must not back off: %v then %v", first, second)
	}
}

// A server that refuses the machine is a different case, and the wait must grow: retrying a
// rejected token every second is a machine shouting at a door that will not open.
func TestARefusedRoadBacksOff(t *testing.T) {
	server := serverThatStreams(t, http.StatusUnauthorized)
	waits := make(chan time.Duration, 8)
	problems := make(chan error, 8)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() {
		_ = streamingSession(server).WatchEvents(ctx, WatchOptions{
			Nudge:  make(chan struct{}, 4),
			Report: func(err error) { problems <- err },
			Tick: func(d time.Duration) <-chan time.Time {
				waits <- d
				return time.After(time.Millisecond)
			},
		})
	}()

	select {
	case <-problems:
	case <-time.After(3 * time.Second):
		t.Fatal("a refusal went unreported")
	}
	first := <-waits
	second := <-waits
	if second <= first {
		t.Fatalf("the wait must grow while the door stays shut: %v then %v", first, second)
	}
}

func TestWatchingStopsWhenTheContextEnds(t *testing.T) {
	server := serverThatStreams(t, http.StatusOK)
	ctx, stop := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- streamingSession(server).WatchEvents(ctx, WatchOptions{Nudge: make(chan struct{}, 1)})
	}()

	time.Sleep(50 * time.Millisecond)
	stop()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("an orderly stop is not a failure: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("watching outlived its context")
	}
}
