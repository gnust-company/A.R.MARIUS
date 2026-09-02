package client

import (
	"context"
	"encoding/json"
	"errors"
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

// The work packet: everything the agent needs, handed over in the same answer as the work.
// It is fetched nowhere else — an agent that had to go and collect its own skills could start
// reading before they arrived, and the first thing it did would be the one thing it was not
// equipped for (FR-011, FR-011b).
func TestTheWorkComesWithItsMessageAndItsSkills(t *testing.T) {
	server, _ := serverThatAnswers(t, `{"runs":[{
		"run_id":"11111111-1111-1111-1111-111111111111",
		"task_id":"22222222-2222-2222-2222-222222222222",
		"workplace_id":"33333333-3333-3333-3333-333333333333",
		"run_token":"armr_run_secret",
		"claim_expires_at":"2026-08-26T10:02:00Z",
		"prompt":"You are Marin, the release engineer.",
		"skills":[{"name":"cookbook","files":{"SKILL.md":"# Cookbook","ref/stock.md":"Simmer."}}]}]}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	got, err := session.ClaimRuns(context.Background(), ClaimRequest{Max: 1})
	if err != nil {
		t.Fatalf("claiming: %v", err)
	}

	run := got.Runs[0]
	if run.Prompt != "You are Marin, the release engineer." {
		t.Fatalf("the message did not survive the wire: %q", run.Prompt)
	}
	if len(run.Skills) != 1 || run.Skills[0].Name != "cookbook" {
		t.Fatalf("the skills did not survive the wire: %+v", run.Skills)
	}
	if len(run.Skills[0].Files) != 2 || run.Skills[0].Files["ref/stock.md"] != "Simmer." {
		t.Fatalf("a skill arrived without all of its files: %+v", run.Skills[0].Files)
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

// ── which failures the machine is allowed to keep asking about ───────────────

// A batch the server read and rejected must come back marked, or the caller has no way to
// tell it apart from a server that was momentarily unreachable — and it will ask again
// forever, holding every later event behind the same refusal (FR-047).
func TestABatchTheServerRejectsComesBackMarkedAsSettled(t *testing.T) {
	for _, status := range []int{
		http.StatusBadRequest,
		http.StatusConflict,
		http.StatusRequestEntityTooLarge,
		http.StatusUnsupportedMediaType,
		http.StatusUnprocessableEntity,
	} {
		server, _ := serverThatAnswers(t, `{}`, status)
		session := Session{Server: server.URL, Token: "armd_secret"}

		err := session.Record(context.Background(), "run-1", []EventIn{{Seq: 1, Type: "run.text"}})

		if !errors.Is(err, ErrRefusedForGood) {
			t.Fatalf("%d must read as the server's settled answer, got %v", status, err)
		}
	}
}

// The three ways a server says *not now*. Sending the same batch again is exactly the right
// thing to do with these, so none of them may be read as a refusal.
func TestAServerAskingForPatienceIsNotAServerRefusing(t *testing.T) {
	for _, status := range []int{
		http.StatusUnauthorized,
		http.StatusForbidden,
		http.StatusRequestTimeout,
		http.StatusTooEarly,
		http.StatusTooManyRequests,
		http.StatusInternalServerError,
		http.StatusBadGateway,
		http.StatusServiceUnavailable,
	} {
		server, _ := serverThatAnswers(t, `{}`, status)
		session := Session{Server: server.URL, Token: "armd_secret"}

		err := session.Record(context.Background(), "run-1", []EventIn{{Seq: 1, Type: "run.text"}})

		if err == nil {
			t.Fatalf("%d was swallowed", status)
		}
		if errors.Is(err, ErrRefusedForGood) {
			t.Fatalf("%d must stay retryable, but was marked as a refusal", status)
		}
	}
}

// A run taken back is neither. It has its own answer and must keep it, or the supervisor stops
// stopping the run and starts dropping events instead.
func TestARunTakenBackIsStillItsOwnAnswerAndNotARefusal(t *testing.T) {
	server, _ := serverThatAnswers(t, `{}`, 404)
	session := Session{Server: server.URL, Token: "armd_secret"}

	err := session.Record(context.Background(), "run-1", []EventIn{{Seq: 1, Type: "run.text"}})

	if !errors.Is(err, ErrRunNotOurs) {
		t.Fatalf("a 404 must stay *not ours*, got %v", err)
	}
	if errors.Is(err, ErrRefusedForGood) {
		t.Fatal("a run taken back is not a batch the server rejected")
	}
}

// A machine with no verdict must send exactly what it sent before this field existed. The
// server reads an absent `failure` as *I do not know why*, and an empty string it had to
// invent a meaning for would be the same claim made twice in two different words.
func TestAnEndingWithNoVerdictSaysNothingAboutWhy(t *testing.T) {
	server, seen := serverThatAnswers(t, `{}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	err := session.FinishRun(context.Background(), "run-1", FinishRequest{
		Status: "failed", Error: "the CLI gave up",
	})

	if err != nil {
		t.Fatalf("finishing: %v", err)
	}
	if strings.Contains(seen.body, "failure") {
		t.Fatalf("không biết vì sao mà vẫn khai một lý do: %s", seen.body)
	}
}

// And when it *is* certain, the code travels — the whole reason the field is there is that
// a run nothing can get past by trying again must not be tried again (FR-032).
func TestAnEndingThisMachineIsSureAboutCarriesTheReasonAsACode(t *testing.T) {
	server, seen := serverThatAnswers(t, `{}`, 200)
	session := Session{Server: server.URL, Token: "armd_secret"}

	err := session.FinishRun(context.Background(), "run-1", FinishRequest{
		Status: "failed", Failure: "quota_exhausted",
	})

	if err != nil {
		t.Fatalf("finishing: %v", err)
	}
	if !strings.Contains(seen.body, `"failure":"quota_exhausted"`) {
		t.Fatalf("lý do không đi ra khỏi máy: %s", seen.body)
	}
}
