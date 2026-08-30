package client

import (
	"context"
	"errors"
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
	RunID string `json:"run_id"`
	// TaskID and ProjectID say what this run is *about*, and either may be empty. Which of
	// them is filled is what decides the set of commands the agent is handed (FR-013d), so an
	// empty one is a real answer here rather than a missing value: a Leader's run has no task,
	// and the team-building interview has neither.
	TaskID      string `json:"task_id"`
	ProjectID   string `json:"project_id"`
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

	// RuntimeOptions is what the person set on this agent, out of what this workplace said its
	// CLI takes (FR-007k). The keys are the server's names for the settings, not this CLI's
	// flags — turning one into the other is the runtime's job, and doing it here would put
	// knowledge of a particular CLI in the part that only carries bytes.
	RuntimeOptions map[string]string `json:"runtime_options"`
	// FirstSeq is the number this machine gives the first event it produces (FR-045).
	//
	// The server says it because the server owns the log: the message this run was given is
	// already written down there, and a run that was put back and handed out again has more
	// than one of those. Numbering from a number the server chose is what keeps the pair
	// (run, number) unique without a round trip per event to agree on the next one.
	FirstSeq int `json:"first_seq"`
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

// EventIn is one thing that happened during a run, on its way to the server (FR-015, FR-045).
//
// `seq` is assigned on this machine, in the order the agent produced things. It is what makes
// a re-sent batch harmless: the server writes each number once, so a reply lost on the way back
// costs a repeated call and nothing more.
type EventIn struct {
	Seq     int            `json:"seq"`
	Type    string         `json:"type"`
	Payload map[string]any `json:"payload"`

	// Why the payload is short, and whether something was taken out of it, said in fields of
	// their own rather than buried in the payload: the screen has to be able to draw *something
	// is missing here, and here is why* without reading into a shape that differs per event
	// (FR-043b, FR-047, FR-048). Omitted when they have nothing to say, so an old daemon and a
	// new one send the same bytes for the same ordinary event.
	Truncated      bool   `json:"truncated,omitempty"`
	OriginalBytes  int    `json:"original_byte_size,omitempty"`
	OmissionReason string `json:"omission_reason,omitempty"`
	Redacted       bool   `json:"redacted,omitempty"`
}

// EventsRequest is one batch.
type EventsRequest struct {
	Events []EventIn `json:"events"`
}

// FinishRequest is the machine saying a run is over, however it ended.
type FinishRequest struct {
	// Status is a code, never a sentence (Constitution VII): completed, failed, timed_out or
	// stopped. The server decides what each one means for the task.
	Status string `json:"status"`
	// Error is this machine's own account of what went wrong, when something did. It describes
	// the side of the failure no code on the server could have seen.
	Error string `json:"error,omitempty"`
	// Usage is whatever the CLI said the turn cost, passed on exactly as it was given.
	Usage map[string]any `json:"usage,omitempty"`
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

// Record sends one batch of a run's events while the run is still going (FR-015).
//
// Sent with the **machine's** token, like every other call this daemon makes: the run's own
// token belongs to the agent and never comes back out of it (FR-014a). What ties the batch to
// the run is the run's id in the path, and the server refuses a batch about a run this machine
// no longer holds (FR-059).
func (s Session) Record(ctx context.Context, runID string, events []EventIn) error {
	if len(events) == 0 {
		return nil
	}
	status, err := sendJSON(
		ctx, s.client(), http.MethodPost,
		endpoint(s.Server, "/daemon/runs/"+runID+"/events"), s.Token,
		EventsRequest{Events: events}, nil,
	)
	if status == http.StatusNotFound {
		return ErrRunNotOurs
	}
	return err
}

// FinishRun closes a run: the run token dies with it, and the task it belongs to gets something
// live pushing it again rather than waiting to be noticed by a sweep (FR-014b, FR-030a).
func (s Session) FinishRun(ctx context.Context, runID string, req FinishRequest) error {
	status, err := sendJSON(
		ctx, s.client(), http.MethodPost,
		endpoint(s.Server, "/daemon/runs/"+runID+"/finish"), s.Token, req, nil,
	)
	if status == http.StatusNotFound {
		return ErrRunNotOurs
	}
	return err
}

// ErrRunNotOurs is the server refusing a write about a run this machine no longer holds
// (FR-059). It is not a transport failure and must never be retried — the run has been taken
// back, and everything sent about it from now on would be refused for the same reason.
//
// Declared here rather than imported from the supervisor so that this package keeps depending
// on nothing above it; the supervisor's own sentinel is defined as this one.
var ErrRunNotOurs = errors.New("this run is no longer this machine's to run")
