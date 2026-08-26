package client

import (
	"context"
	"net/http"
	"time"
)

// ClaimRequest is a machine asking for work.
//
// Both fields are the machine's own account of itself and neither is trusted as a rule. The
// workplaces narrow the ask to what this machine can actually run; the server intersects them
// with what it knows this machine has, so a stale list from a daemon mid-upgrade is harmless.
// Max is how many more runs this machine will take right now, and the server takes the smaller
// of it and its own ceiling — a wrong number here can never win more work than allowed
// (FR-008d, FR-055c).
type ClaimRequest struct {
	WorkplaceIDs []string `json:"workplace_ids"`
	Max          int      `json:"max"`
}

// GrantedRun is one run this machine now holds.
type GrantedRun struct {
	RunID       string `json:"run_id"`
	TaskID      string `json:"task_id"`
	WorkplaceID string `json:"workplace_id"`
	// RunToken opens exactly this run and dies with it. It is never the machine's own token,
	// and it is never written to disk beside one: minting it is the server's job precisely so
	// that a compromised run cannot speak for the whole machine (FR-014a, FR-014c).
	RunToken string `json:"run_token"`
	// ClaimExpiresAt is when this machine loses the run if it has not reported it started.
	// The window covers setting up — a working directory, the skills, a cold CLI (FR-056a).
	ClaimExpiresAt time.Time `json:"claim_expires_at"`
	// Prompt is what the agent reads, assembled on the server and in English (FR-011a,
	// Constitution VII). The daemon composes none of it and sends none of it back: it writes
	// this string into the file its CLI already opens, and the server has already recorded
	// the copy it built (FR-012a).
	Prompt string `json:"prompt"`
	// Skills are this agent's own skills, whole. They come with the work rather than being
	// fetched afterwards, so that by the time the agent reads its first line everything it
	// was granted is already on disk (FR-011b).
	Skills []GrantedSkill `json:"skills"`
}

// GrantedSkill is one skill as it arrives: a directory name and everything that goes in it.
//
// Files maps a path relative to that directory to its contents. Relative on purpose — the
// daemon decides which directory this CLI reads skills from, and a path that could climb out
// of it would be a path that could write anywhere on the machine.
type GrantedSkill struct {
	Name  string            `json:"name"`
	Files map[string]string `json:"files"`
}

// ClaimResponse is what came back. An empty list is the ordinary answer.
type ClaimResponse struct {
	Runs []GrantedRun `json:"runs"`
}

// StartRequest is the machine saying the agent is up.
type StartRequest struct {
	SessionHandle string `json:"session_handle"`
}

// ClaimRuns asks for work and comes back with what was given (FR-053, FR-054).
//
// This is the only way a run begins. Nothing on this machine may start a run it was not handed
// here, and nothing on the server may start one on this machine's behalf.
func (s Session) ClaimRuns(ctx context.Context, req ClaimRequest) (ClaimResponse, error) {
	if req.WorkplaceIDs == nil {
		req.WorkplaceIDs = []string{}
	}
	var out ClaimResponse
	_, err := sendJSON(
		ctx, s.client(), http.MethodPost,
		endpoint(s.Server, "/daemon/runs/claim"), s.Token, req, &out,
	)
	return out, err
}

// StartRun reports that the agent for this run is up, and answers whether the run is still
// this machine's to run.
//
// A false with no error is the server saying the hold ran out while this machine was setting
// up: the run belongs to nobody now, and the only correct response is to stop and clean up.
// It is deliberately not an error — nothing went wrong with the call, and treating it as a
// failure would put it in the retry path, which is precisely where it must not be (FR-058).
func (s Session) StartRun(ctx context.Context, runID, sessionHandle string) (bool, error) {
	status, err := sendJSON(
		ctx, s.client(), http.MethodPost,
		endpoint(s.Server, "/daemon/runs/"+runID+"/start"), s.Token,
		StartRequest{SessionHandle: sessionHandle}, nil,
	)
	if status == http.StatusNotFound {
		return false, nil
	}
	return err == nil, err
}
