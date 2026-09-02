// Package client holds the calls this machine makes up to the Armarius server.
//
// Every one of them is outbound. The server never opens a connection to this machine, which is
// what lets a laptop behind a closed lid or a workstation behind a company firewall run agents
// with no inbound port at all.
package client

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Credentials are what `login` leaves behind for `start` to pick up.
//
// They share a file with the operator's tuning knobs (internal/config), which is why they are
// written by merging into whatever that file already holds rather than by overwriting it. Both
// halves ignore fields they do not recognise, so neither has to know about the other.
type Credentials struct {
	Server      string `json:"server"`
	Token       string `json:"token"`
	MachineID   string `json:"machine_id"`
	WorkspaceID string `json:"workspace_id"`
}

// LoginOptions is everything Login needs from the outside world.
//
// The clock, the sleep and the HTTP client are handed in rather than reached for so that a test
// can run the whole wait-for-approval loop in microseconds. The loop is the part worth testing —
// it is the only place in the daemon that gives up on its own.
type LoginOptions struct {
	// Server is the base URL of the Armarius API, as the operator typed it.
	Server string
	// ConfigPath is the file the token is written to, at mode 0600.
	ConfigPath string
	// Platform, Version and Hostname are what this machine claims about itself. They are shown
	// on the approval screen so a person can recognise the machine they are admitting; the
	// server treats them as claims, never as identity.
	Platform string
	Version  string
	Hostname string

	HTTPClient *http.Client
	// Out receives the code and the progress a person watches while they walk to a browser.
	Out io.Writer
	// Sleep waits between polls. It must return the context's error if the wait is cut short,
	// so that Ctrl-C during a login is not mistaken for the code expiring.
	Sleep func(ctx context.Context, d time.Duration) error
}

// linkStartResponse mirrors the answer to POST /daemon/link/start.
type linkStartResponse struct {
	Code      string `json:"code"`
	VerifyURL string `json:"verify_url"`
	ExpiresIn int    `json:"expires_in"`
	Interval  int    `json:"interval"`
}

// linkPollResponse mirrors the answer to POST /daemon/link/poll. The status field, not the HTTP
// code, is what the loop below branches on: they agree, and one of them is easier to read.
type linkPollResponse struct {
	Status      string `json:"status"`
	MachineID   string `json:"machine_id"`
	WorkspaceID string `json:"workspace_id"`
	Token       string `json:"token"`
	// The parts of a refusal, when the answer is one. A 429 carries how long this machine
	// should wait before asking again; the server words the reason for whoever reads it and
	// puts the number here separately, so this side reads the number rather than the sentence.
	Params struct {
		Seconds string `json:"seconds"`
	} `json:"params"`
}

// ErrLinkExpired reports that the code ran out, or was already used, before anyone approved it.
//
// It is a distinct error because the answer is different from every other failure here: nothing
// is wrong, the person simply took too long, and the fix is to run `login` again.
var ErrLinkExpired = errors.New("the link code expired before it was approved")

// Login links this machine to a workspace and writes the resulting token to disk.
//
// The flow is deliberately one that works on a machine with no browser (research §1): this
// program prints a short code, a person opens Armarius wherever they already are and approves
// it, and the poll below picks the token up. Nothing secret is ever typed by hand — the code is
// worthless without a signed-in person, and the token never leaves this function except into a
// file only its owner can read.
func Login(ctx context.Context, opts LoginOptions) (Credentials, error) {
	opts = opts.withDefaults()
	if strings.TrimSpace(opts.Server) == "" {
		return Credentials{}, errors.New("no server given")
	}
	if strings.TrimSpace(opts.ConfigPath) == "" {
		return Credentials{}, errors.New("no config path given")
	}

	started, err := startLink(ctx, opts)
	if err != nil {
		return Credentials{}, err
	}

	say(opts.Out, "Open %s and enter this code:\n\n\t%s\n\n", started.VerifyURL, started.Code)
	say(opts.Out, "Waiting for approval (the code is good for %s)...\n", time.Duration(started.ExpiresIn)*time.Second)

	interval := time.Duration(started.Interval) * time.Second
	if interval <= 0 {
		// The server is meant to set the pace. If its answer is missing or nonsensical, fall
		// back to something slow rather than spinning: an unattended login that polls in a
		// tight loop is a denial of service aimed at the person who ran it.
		interval = 5 * time.Second
	}

	creds, err := awaitApproval(ctx, opts, started.Code, interval)
	if err != nil {
		return Credentials{}, err
	}
	if err := SaveCredentials(opts.ConfigPath, creds); err != nil {
		return Credentials{}, err
	}
	say(opts.Out, "\nLinked. This machine's token is in %s.\n", opts.ConfigPath)
	return creds, nil
}

// maxPollFailures is how many polls in a row may fail before login gives up.
//
// A failure is not the same as a refusal: a server being restarted, or a laptop lid closing
// on a wifi connection, is a normal thing to live through during the minute or two a person
// takes to walk to a browser. What must not happen is looping forever against a server that
// is simply gone — the code's own ten-minute expiry cannot end that loop, because a server
// that answers nothing never answers 410 either.
const maxPollFailures = 5

// awaitApproval polls until a person approves, the code dies, or the context is cancelled.
//
// There is no *attempt* limit here on purpose. The server already put one on the code — ten
// minutes, expressed as an expiry it enforces — and a second limit living on this side could
// only ever disagree with it. The limit that does live here counts consecutive failures,
// which is a different thing and is the one the server cannot bound.
func awaitApproval(
	ctx context.Context, opts LoginOptions, code string, interval time.Duration,
) (Credentials, error) {
	failures := 0
	for {
		// The wait comes first. Nobody has approved a code in the moment between printing it
		// and asking about it, so an immediate poll can only ever answer *pending*.
		if err := opts.Sleep(ctx, interval); err != nil {
			return Credentials{}, err
		}
		polled, status, err := pollLink(ctx, opts, code)
		if err != nil {
			failures++
			if failures >= maxPollFailures {
				return Credentials{}, fmt.Errorf("gave up after %d failed attempts to ask: %w", failures, err)
			}
			say(opts.Out, "?")
			continue
		}
		failures = 0
		switch {
		case status == http.StatusTooManyRequests:
			// A refusal, not a failure, and the distinction is the whole of this branch. The
			// server is saying *ask less often*, which is an answer; counting it as a failed
			// attempt would abandon a link that is still perfectly alive after five of them.
			// The wait is the server's to set, and never shorter than the pace it already
			// handed over.
			if err := opts.Sleep(ctx, waitAsked(polled, interval)); err != nil {
				return Credentials{}, err
			}
			say(opts.Out, ",")
			continue
		case status == http.StatusGone || polled.Status == "expired":
			return Credentials{}, ErrLinkExpired
		case polled.Status == "approved" && polled.Token != "":
			return Credentials{
				Server:      strings.TrimRight(opts.Server, "/"),
				Token:       polled.Token,
				MachineID:   polled.MachineID,
				WorkspaceID: polled.WorkspaceID,
			}, nil
		}
		say(opts.Out, ".")
	}
}

func startLink(ctx context.Context, opts LoginOptions) (linkStartResponse, error) {
	body := map[string]string{
		"platform":       opts.Platform,
		"daemon_version": opts.Version,
		"hostname":       opts.Hostname,
	}
	var out linkStartResponse
	if _, err := opts.post(ctx, "/daemon/link/start", body, &out); err != nil {
		return linkStartResponse{}, err
	}
	if out.Code == "" {
		return linkStartResponse{}, errors.New("the server did not return a link code")
	}
	return out, nil
}

// waitAsked reads how long the server said to wait, floored at the pace it already handed over.
//
// Floored rather than trusted outright: a number this side cannot read — absent, malformed, or
// smaller than the interval — must not turn into a tighter loop against a door that has just
// said it is being asked too often.
func waitAsked(polled linkPollResponse, interval time.Duration) time.Duration {
	seconds, err := strconv.Atoi(strings.TrimSpace(polled.Params.Seconds))
	if err != nil || seconds <= 0 {
		return interval
	}
	asked := time.Duration(seconds) * time.Second
	if asked < interval {
		return interval
	}
	return asked
}

// pollLink returns the decoded answer and its HTTP status. 410 and 429 are real answers rather
// than failures — the code is dead, or this machine is asking too often — so both travel back as
// statuses instead of being turned into errors here.
func pollLink(ctx context.Context, opts LoginOptions, code string) (linkPollResponse, int, error) {
	var out linkPollResponse
	status, err := opts.post(ctx, "/daemon/link/poll", map[string]string{"code": code}, &out)
	if err != nil && status != http.StatusGone && status != http.StatusTooManyRequests {
		return linkPollResponse{}, status, err
	}
	return out, status, nil
}

// post sends one JSON request to the server this machine is trying to link to. No token: at
// this point in the flow there is none to send.
func (o LoginOptions) post(ctx context.Context, path string, body, into any) (int, error) {
	return sendJSON(ctx, o.HTTPClient, http.MethodPost, endpoint(o.Server, path), "", body, into)
}

// SaveCredentials writes the token into the machine's config file without disturbing anything
// else in it.
//
// Mode 0600 on both the file and the directory: this file holds a secret that speaks for the
// whole machine — every workplace on it and every agent behind those — so it must not be
// readable by other accounts on a shared box (FR-014c). An existing file's permissions are
// tightened rather than trusted, because a file left world-readable by an earlier version, or
// by an operator's editor, is exactly the case this guards against.
func SaveCredentials(path string, creds Credentials) error {
	merged := map[string]any{}
	existing, err := os.ReadFile(path) //nolint:gosec // the operator's own config file
	switch {
	case err == nil:
		if unmarshalErr := json.Unmarshal(existing, &merged); unmarshalErr != nil {
			return fmt.Errorf("%s is not readable as JSON; move it aside and log in again: %w", path, unmarshalErr)
		}
	case errors.Is(err, os.ErrNotExist):
		// First login on this machine. Nothing to preserve.
	default:
		return fmt.Errorf("reading %s: %w", path, err)
	}

	merged["server"] = creds.Server
	merged["token"] = creds.Token
	merged["machine_id"] = creds.MachineID
	merged["workspace_id"] = creds.WorkspaceID

	encoded, err := json.MarshalIndent(merged, "", "  ")
	if err != nil {
		return fmt.Errorf("encoding %s: %w", path, err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("creating %s: %w", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, encoded, 0o600); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	// WriteFile only applies its mode when it creates the file; a pre-existing one keeps
	// whatever it had, which is the case this line exists for.
	if err := os.Chmod(path, 0o600); err != nil {
		return fmt.Errorf("restricting %s to its owner: %w", path, err)
	}
	return nil
}

// withDefaults fills in the edges a caller did not care to supply.
func (o LoginOptions) withDefaults() LoginOptions {
	if o.HTTPClient == nil {
		// A timeout well under the code's ten-minute life: a call that hangs must fail while
		// the code is still good, so the operator sees an error rather than an expiry.
		o.HTTPClient = &http.Client{Timeout: 30 * time.Second}
	}
	if o.Out == nil {
		o.Out = io.Discard
	}
	if o.Sleep == nil {
		o.Sleep = sleep
	}
	if o.Hostname == "" {
		if name, err := os.Hostname(); err == nil {
			o.Hostname = name
		}
	}
	return o
}

// say writes progress a person is meant to read. A failed write to a terminal, or to a pipe that
// has already been closed, leaves nothing worth reporting — there is no second stream to report
// it on — so the error is dropped here, once and on purpose, rather than at every call site.
func say(w io.Writer, format string, args ...any) {
	_, _ = fmt.Fprintf(w, format, args...)
}

// sleep waits, and reports a cancelled context as the error it is.
func sleep(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
