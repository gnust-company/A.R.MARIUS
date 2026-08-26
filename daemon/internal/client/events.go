package client

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// The push road's own reconnect rhythm, and it is **only** the push road's.
//
// Losing this connection loses nothing: the machine still asks for work on its own beat, and
// that beat is the guarantee (FR-055d). So the retry here can afford to give up quickly and
// come back slowly. What it must never do is make the asking beat faster to compensate — a
// push road that is down is fixed by fixing the push road, not by charging every machine a
// permanently tighter poll.
const (
	minReconnectDelay = 1 * time.Second
	maxReconnectDelay = 60 * time.Second
)

// pendingWork is the one event name this machine acts on. Anything else on the road is
// ignored rather than guessed at: a nudge is a promise to come and ask, and reacting to an
// event whose meaning this build does not know would be asking for reasons it cannot name.
const pendingWork = "pending_work"

// maxEventLine bounds one SSE line. Every line the server sends is a short field; a longer
// one means something other than the Armarius API is at the other end, and growing a buffer
// to meet it would be the one way this daemon could be made to exhaust its own memory.
const maxEventLine = 64 << 10

// WatchOptions is what holding the push road open needs from the rest of the daemon.
type WatchOptions struct {
	// Nudge is where *there is work, go and ask* is delivered. Sent without blocking: a
	// nudge already waiting means an ask is already coming, and a second one would only make
	// that ask happen twice. Two asks in a row are harmless — the second finds an empty
	// shelf — but they are pointless, and pointless is what this road is trying not to be.
	Nudge chan<- struct{}
	// Report is told when the road drops. Optional; a dropped road is not an incident.
	Report func(error)
	// Tick answers when the next reconnect is due. A seam for tests, exactly as in the ask
	// loop; defaults to `time.After`.
	Tick func(d time.Duration) <-chan time.Time
}

func (o WatchOptions) withDefaults() WatchOptions {
	if o.Tick == nil {
		o.Tick = time.After
	}
	if o.Report == nil {
		o.Report = func(error) {}
	}
	return o
}

// streamClient is a client with no overall deadline, for the one call that is meant to last.
//
// The ordinary client times out in ten seconds so a stuck request cannot outlive the beat
// behind it. Holding that rule here would close a perfectly healthy road every ten seconds,
// so what replaces it is a deadline on the *answer* rather than on the conversation: a server
// that accepts the connection and then says nothing is still noticed, while one that says
// hello and then waits — which is what a quiet machine looks like — is left alone.
func (s Session) streamClient() *http.Client {
	if s.HTTPClient != nil {
		return s.HTTPClient
	}
	return &http.Client{
		Transport: &http.Transport{ResponseHeaderTimeout: 30 * time.Second},
	}
}

// WatchEvents holds the push road open and turns what comes down it into nudges (FR-055).
//
// This is the fast road, never the only one. Everything it can do, the asking beat also does
// a few seconds later; all this buys is those few seconds. That is why every failure here is
// swallowed into a reconnect rather than returned: there is nothing upstream that could do
// anything more useful about a push road being down than wait for it to come back.
//
// Returns only when the context ends.
func (s Session) WatchEvents(ctx context.Context, opts WatchOptions) error {
	opts = opts.withDefaults()
	delay := minReconnectDelay

	for {
		connected, err := s.readEvents(ctx, opts)
		if ctx.Err() != nil {
			return nil
		}
		if err != nil {
			opts.Report(err)
		}
		if connected {
			// The road worked at least once. Whatever ended it is more likely a passing
			// thing than a broken server, so start the wait over rather than punishing a
			// machine that has been connected for hours for one dropped connection.
			delay = minReconnectDelay
		}
		select {
		case <-ctx.Done():
			return nil
		case <-opts.Tick(delay):
		}
		if delay < maxReconnectDelay {
			delay *= 2
			if delay > maxReconnectDelay {
				delay = maxReconnectDelay
			}
		}
	}
}

// readEvents holds one connection until it ends. The bool says whether it was ever open,
// which is what tells a server that refused this machine from one that hung up on it.
func (s Session) readEvents(ctx context.Context, opts WatchOptions) (bool, error) {
	req, err := http.NewRequestWithContext(
		ctx, http.MethodGet, endpoint(s.Server, "/daemon/events"), nil,
	)
	if err != nil {
		return false, fmt.Errorf("building the push-road request: %w", err)
	}
	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set("Authorization", "Bearer "+s.Token)

	resp, err := s.streamClient().Do(req)
	if err != nil {
		return false, fmt.Errorf("opening the push road: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return false, fmt.Errorf("the push road answered %s", resp.Status)
	}

	lines := bufio.NewScanner(resp.Body)
	lines.Buffer(make([]byte, 0, 4096), maxEventLine)
	name := ""
	for lines.Scan() {
		line := strings.TrimRight(lines.Text(), "\r")
		switch {
		case line == "":
			// End of one event. The payload is deliberately never read: this machine asks
			// about everything it hosts anyway, so the only thing the message can usefully
			// say is *that* there is something (FR-055a). Reading a run out of it is how a
			// signal quietly turns into an instruction.
			if name == pendingWork {
				select {
				case opts.Nudge <- struct{}{}:
				default:
				}
			}
			name = ""
		case strings.HasPrefix(line, ":"):
			// A comment — the server's keep-alive. Not an event, and not a boundary.
		case strings.HasPrefix(line, "event:"):
			name = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		}
	}
	if err := lines.Err(); err != nil && !errors.Is(err, context.Canceled) {
		return true, fmt.Errorf("reading the push road: %w", err)
	}
	return true, nil
}
