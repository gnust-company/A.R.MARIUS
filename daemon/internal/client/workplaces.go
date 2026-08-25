package client

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/discovery"
)

// Session is an authenticated connection to the server, held for as long as `start` runs.
//
// It carries the machine token and nothing else: the token speaks for this whole machine and
// is never handed to an agent, which gets a run token minted for one run instead (FR-014c).
type Session struct {
	// Server is the base URL of the Armarius API, as the operator typed it into `login`.
	Server string
	// Token is this machine's own credential.
	Token string
	// HTTPClient defaults to one with a timeout short enough that a stuck call cannot outlast
	// the beat that follows it.
	HTTPClient *http.Client
}

// WorkplaceReport is one agent CLI as this machine found it.
type WorkplaceReport struct {
	CLIKind        string                 `json:"cli_kind"`
	CLIVersion     string                 `json:"cli_version"`
	ProtocolFamily string                 `json:"protocol_family"`
	Capabilities   discovery.Capabilities `json:"capabilities"`
}

// WorkplacesRequest is the machine's whole list, sent every time rather than as a difference.
//
// Sending everything is what makes a CLI that *left* visible at all: there is no message for
// "gemini is gone", only a list that stops mentioning it (FR-033).
type WorkplacesRequest struct {
	Workplaces []WorkplaceReport `json:"workplaces"`
	// SymlinkCapable is what the link probe established by making a link, not a guess from
	// which operating system this is (research §5).
	SymlinkCapable bool `json:"symlink_capable"`
}

// RegisteredWorkplace is one workplace as the server now holds it.
type RegisteredWorkplace struct {
	ID             string `json:"id"`
	CLIKind        string `json:"cli_kind"`
	Ready          bool   `json:"ready"`
	NotReadyReason string `json:"not_ready_reason"`
	MachineName    string `json:"machine_name"`
}

// WorkplacesResponse is what came back.
type WorkplacesResponse struct {
	Workplaces []RegisteredWorkplace `json:"workplaces"`
}

// BeatRequest is what this machine says about itself on one beat.
type BeatRequest struct {
	FreeSlots int      `json:"free_slots"`
	Running   []string `json:"running"`
}

// BeatResponse is what the server answers.
type BeatResponse struct {
	PendingWork bool     `json:"pending_work"`
	Cancel      []string `json:"cancel"`
}

// SyncWorkplaces tells the server what this machine can run right now (FR-002).
func (s Session) SyncWorkplaces(
	ctx context.Context, req WorkplacesRequest,
) (WorkplacesResponse, error) {
	// An empty list is a real report — a machine with no agent CLI installed — so it has to
	// marshal as `[]` and not as `null`, which is not the same thing to read back.
	if req.Workplaces == nil {
		req.Workplaces = []WorkplaceReport{}
	}
	var out WorkplacesResponse
	_, err := sendJSON(
		ctx, s.client(), http.MethodPut,
		endpoint(s.Server, "/daemon/workplaces"), s.Token, req, &out,
	)
	return out, err
}

// Beat says this machine is still here, and brings back what to do next (FR-004).
func (s Session) Beat(ctx context.Context, req BeatRequest) (BeatResponse, error) {
	if req.Running == nil {
		req.Running = []string{}
	}
	var out BeatResponse
	_, err := sendJSON(
		ctx, s.client(), http.MethodPost,
		endpoint(s.Server, "/daemon/heartbeat"), s.Token, req, &out,
	)
	return out, err
}

func (s Session) client() *http.Client {
	if s.HTTPClient != nil {
		return s.HTTPClient
	}
	// Shorter than the beat interval on purpose: a call still hanging when the next beat is
	// due would stack one connection per beat against a server that has stopped answering.
	return &http.Client{Timeout: 10 * time.Second}
}

// LoadCredentials reads back what `login` left behind.
//
// A missing server or token is reported here rather than at the first call, so a machine that
// was never linked says so when it starts instead of failing on its first beat with something
// that reads like a network problem.
func LoadCredentials(path string) (Credentials, error) {
	var creds Credentials
	raw, err := os.ReadFile(path) //nolint:gosec // the operator's own config file
	switch {
	case errors.Is(err, os.ErrNotExist):
		// No file at all and a file with no token are the same situation to the person
		// running this — the machine was never linked — so they get the same sentence.
	case err != nil:
		return Credentials{}, fmt.Errorf("reading %s: %w", path, err)
	default:
		if err := json.Unmarshal(raw, &creds); err != nil {
			return Credentials{}, fmt.Errorf("%s is not readable as JSON: %w", path, err)
		}
	}
	if creds.Server == "" || creds.Token == "" {
		return Credentials{}, fmt.Errorf("%s holds no machine token; run `armarius-daemon login` first", path)
	}
	return creds, nil
}
