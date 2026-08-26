package client

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestClaimRunsAsksUnderTheMachineTokenAndCarriesBothNumbers(t *testing.T) {
	server, seen := serverThatAnswers(t, `{"runs":[{
		"run_id":"11111111-1111-1111-1111-111111111111",
		"task_id":"22222222-2222-2222-2222-222222222222",
		"workplace_id":"33333333-3333-3333-3333-333333333333",
		"run_token":"armr_run_secret",
		"claim_expires_at":"2026-08-26T10:02:00Z"}]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	got, err := session.ClaimRuns(context.Background(), ClaimRequest{
		WorkplaceIDs: []string{"33333333-3333-3333-3333-333333333333"},
		Max:          2,
	})
	if err != nil {
		t.Fatalf("claiming: %v", err)
	}

	if seen.method != http.MethodPost {
		t.Fatalf("asked with %s", seen.method)
	}
	if seen.auth != "Bearer armd_secret" {
		t.Fatalf("the ask must carry this machine's own token, got %q", seen.auth)
	}
	var sent map[string]any
	if err := json.Unmarshal([]byte(seen.body), &sent); err != nil {
		t.Fatalf("the ask was not JSON: %v", err)
	}
	if sent["max"] != float64(2) {
		t.Fatalf("the machine must say how much room it has, got %v", sent["max"])
	}
	if len(got.Runs) != 1 {
		t.Fatalf("expected one run, got %d", len(got.Runs))
	}
	if got.Runs[0].RunToken != "armr_run_secret" {
		t.Fatalf("the run's own token did not come back: %+v", got.Runs[0])
	}
	if !got.Runs[0].ClaimExpiresAt.Equal(time.Date(2026, 8, 26, 10, 2, 0, 0, time.UTC)) {
		t.Fatalf("the hold's deadline did not survive the wire: %v", got.Runs[0].ClaimExpiresAt)
	}
}

// The ordinary answer, and the one this loop gets most of the time. An empty shelf is not a
// failure and must not be reported as one, or a machine asking every five seconds would spend
// its life logging errors about nothing being wrong.
func TestAnEmptyShelfIsNotAnError(t *testing.T) {
	server, _ := serverThatAnswers(t, `{"runs":[]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	got, err := session.ClaimRuns(context.Background(), ClaimRequest{Max: 1})

	if err != nil {
		t.Fatalf("an empty shelf reported as a failure: %v", err)
	}
	if len(got.Runs) != 0 {
		t.Fatalf("expected nothing, got %d", len(got.Runs))
	}
}

// A machine with no workplaces still has to marshal as `[]`. `null` is a different thing to
// read back, and the difference between "I have none" and "I did not say" is exactly the sort
// of ambiguity the whole claim path is built to avoid.
func TestAnAskWithNoWorkplacesStillSendsAList(t *testing.T) {
	server, seen := serverThatAnswers(t, `{"runs":[]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	if _, err := session.ClaimRuns(context.Background(), ClaimRequest{Max: 1}); err != nil {
		t.Fatalf("claiming: %v", err)
	}

	if !strings.Contains(seen.body, `"workplace_ids":[]`) {
		t.Fatalf("an empty list went out as something else: %s", seen.body)
	}
}

func TestStartRunSaysTheAgentIsUp(t *testing.T) {
	server, seen := serverThatAnswers(t, `{}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	held, err := session.StartRun(context.Background(), "run-1", "sess-9")

	if err != nil {
		t.Fatalf("starting: %v", err)
	}
	if !held {
		t.Fatal("the server accepted the report but the caller was told the run was lost")
	}
	if !strings.Contains(seen.body, `"session_handle":"sess-9"`) {
		t.Fatalf("the session handle did not go out: %s", seen.body)
	}
}

// 404 here means the hold ran out while this machine was setting up: the run belongs to
// nobody now and the machine must stop and clean up. It comes back as an answer rather than
// as an error on purpose — an error would land it in the retry path, which is the one place
// it must never go (FR-058).
func TestARunThisMachineNoLongerHoldsComesBackAsAnAnswerNotAFailure(t *testing.T) {
	server, _ := serverThatAnswers(t, `{}`, 404)
	session := Session{Server: server.URL, Token: "armd_secret"}

	held, err := session.StartRun(context.Background(), "run-1", "")

	if err != nil {
		t.Fatalf("a lost run is not a broken call: %v", err)
	}
	if held {
		t.Fatal("the machine was told to carry on with a run it no longer holds")
	}
}

// Anything else is a real failure and has to read as one, or a server that is down looks
// exactly like a run that was taken away.
func TestAServerFailureIsStillAFailure(t *testing.T) {
	server, _ := serverThatAnswers(t, `{}`, 500)
	session := Session{Server: server.URL, Token: "armd_secret"}

	held, err := session.StartRun(context.Background(), "run-1", "")

	if err == nil {
		t.Fatal("a 500 was swallowed")
	}
	if held {
		t.Fatal("a failed call must not read as a run still held")
	}
}
