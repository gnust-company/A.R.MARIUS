package callback

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// fakeArmarius stands in for the server and records what reached it.
type fakeArmarius struct {
	*httptest.Server
	method string
	path   string
	auth   string
	body   map[string]any
	status int
	answer string
}

func armarius(t *testing.T) *fakeArmarius {
	t.Helper()
	f := &fakeArmarius{status: 200, answer: `{"ok":true}`}
	f.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.method, f.path, f.auth = r.Method, r.URL.Path, r.Header.Get("Authorization")
		f.body = nil
		_ = json.NewDecoder(r.Body).Decode(&f.body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(f.status)
		_, _ = w.Write([]byte(f.answer))
	}))
	t.Cleanup(f.Close)
	return f
}

func (f *fakeArmarius) env() Environment {
	return Environment{
		Server:    f.URL,
		RunToken:  "armr_run_secret",
		RunID:     "run-1",
		TaskID:    "task-1",
		ProjectID: "project-1",
	}
}

func run(t *testing.T, env Environment, args ...string) (int, string, string) {
	t.Helper()
	var out, errs strings.Builder
	code := RunCLI(context.Background(), args, env, &out, &errs)
	return code, out.String(), errs.String()
}

// ── the credential (T136, FR-013c) ───────────────────────────────────────────

func TestTheCredentialComesFromTheEnvironmentAndTravelsInTheHeader(t *testing.T) {
	server := armarius(t)
	code, out, _ := run(t, server.env(), "task", "show")

	if code != ExitOK {
		t.Fatalf("exit %d, wanted %d", code, ExitOK)
	}
	if server.auth != "Bearer armr_run_secret" {
		t.Fatalf("the run token did not travel as a bearer token: %q", server.auth)
	}
	if !strings.Contains(out, `"ok":true`) {
		t.Fatalf("the server's answer did not reach stdout: %q", out)
	}
}

func TestACredentialOnTheCommandLineIsRefused(t *testing.T) {
	// FR-013c is not advice. Arguments are recorded in full (FR-043), so a token in an argument
	// is a token written into this run's own record — where it cannot be taken out again.
	server := armarius(t)
	for _, args := range [][]string{
		{"task", "show", "-token", "armr_run_secret"},
		{"task", "show", "--run-token=armr_run_secret"},
		{"task", "comment", "-body", "here is armr_run_secret for you"},
	} {
		code, _, errs := run(t, server.env(), args...)
		if code != ExitUsage {
			t.Fatalf("%v: exit %d, wanted a usage refusal (%d)", args, code, ExitUsage)
		}
		if server.method != "" {
			t.Fatalf("%v: the call went out anyway", args)
		}
		if !strings.Contains(errs, "ARMARIUS_RUN_TOKEN") {
			t.Fatalf("%v: the refusal does not say where the token comes from: %q", args, errs)
		}
	}
}

func TestARunWithNoTokenSaysSoAndCallsNothing(t *testing.T) {
	code, _, errs := run(t, Environment{Server: "http://example.invalid", TaskID: "task-1"}, "task", "show")
	if code != ExitNoRun {
		t.Fatalf("exit %d, wanted %d", code, ExitNoRun)
	}
	if !strings.Contains(errs, "ARMARIUS_RUN_TOKEN") {
		t.Fatalf("the refusal does not name what is missing: %q", errs)
	}
}

// ── how a call ends (T136) ───────────────────────────────────────────────────

func TestARefusalReachesStdoutWholeSoTheAgentCanReadWhichRuleSaidNo(t *testing.T) {
	server := armarius(t)
	server.status = 409
	server.answer = `{"detail":"A task closes only with both signatures.","code":"task_needs_signatures","params":{}}`

	code, out, errs := run(t, server.env(), "task", "status", "-status", "done")

	if code != ExitRefused {
		t.Fatalf("exit %d, wanted %d", code, ExitRefused)
	}
	if !strings.Contains(out, `"code":"task_needs_signatures"`) {
		t.Fatalf("the refusal's code did not reach stdout: %q", out)
	}
	if !strings.Contains(errs, "both signatures") {
		t.Fatalf("nothing readable reached stderr: %q", errs)
	}
}

func TestARunThatIsOverIsToldSoAndNotToldToTryAgain(t *testing.T) {
	// The one refusal that must not be retried: a revoked token fails identically every time,
	// and retrying it burns the recovery budget on a wall (FR-014f).
	server := armarius(t)
	server.status = 404
	server.answer = `{"detail":"Run not found.","code":"run_not_found","params":{}}`

	code, _, errs := run(t, server.env(), "task", "show")

	if code != ExitNoRun {
		t.Fatalf("exit %d, wanted %d — a dead run must not read as an ordinary refusal", code, ExitNoRun)
	}
	if !strings.Contains(errs, "no longer open") {
		t.Fatalf("the message does not say the run is over: %q", errs)
	}
}

func TestAServerFailureIsWorthTryingAgainAndSaysSoWithADifferentCode(t *testing.T) {
	server := armarius(t)
	server.status = 503
	server.answer = `{}`

	code, _, _ := run(t, server.env(), "task", "show")
	if code != ExitUnreached {
		t.Fatalf("exit %d, wanted %d", code, ExitUnreached)
	}
}

func TestAMissingRequiredArgumentIsCaughtHereRatherThanAtTheServer(t *testing.T) {
	server := armarius(t)
	code, _, errs := run(t, server.env(), "task", "comment")

	if code != ExitUsage {
		t.Fatalf("exit %d, wanted %d", code, ExitUsage)
	}
	if server.method != "" {
		t.Fatal("an incomplete call was sent to the server")
	}
	if !strings.Contains(errs, "-body") {
		t.Fatalf("the refusal does not name what is missing: %q", errs)
	}
}

// ── the task set (T137) ──────────────────────────────────────────────────────

func TestTaskCommandsAimAtTheTaskThisRunIsAboutWithoutBeingToldWhichOne(t *testing.T) {
	server := armarius(t)
	cases := []struct {
		args   []string
		method string
		path   string
	}{
		{[]string{"task", "show"}, "GET", "/agent/tasks/task-1"},
		{[]string{"task", "comment", "-body", "hello"}, "POST", "/agent/tasks/task-1/comment"},
		{[]string{"task", "status", "-status", "in_progress"}, "POST", "/agent/tasks/task-1/status"},
		{[]string{"task", "next-action", "-next_action", "write it"}, "POST", "/agent/tasks/task-1/next-action"},
		{[]string{"task", "publish", "-name", "r.md", "-content", "x"}, "POST", "/agent/tasks/task-1/artifact"},
		{[]string{"task", "criteria"}, "GET", "/agent/tasks/task-1/criteria"},
		{[]string{"task", "rate", "-criterion_id", "c1", "-result", "passed"}, "POST", "/agent/tasks/task-1/criteria/c1"},
		{[]string{"task", "sign", "-approve"}, "POST", "/agent/tasks/task-1/approval"},
		{[]string{"task", "handback", "-reason", "unclear"}, "POST", "/agent/tasks/task-1/handback"},
		{[]string{"task", "request"}, "POST", "/agent/tasks/task-1/request"},
		{[]string{"task", "recovery", "-action", "reassign"}, "POST", "/agent/tasks/task-1/recovery"},
		{[]string{"task", "escalate", "-reason", "stuck"}, "POST", "/agent/tasks/task-1/escalate"},
	}

	for _, c := range cases {
		if code, _, errs := run(t, server.env(), c.args...); code != ExitOK {
			t.Fatalf("%v: exit %d (%s)", c.args, code, errs)
		}
		if server.method != c.method || server.path != c.path {
			t.Fatalf("%v: went to %s %s, wanted %s %s", c.args, server.method, server.path, c.method, c.path)
		}
	}
}

func TestAnOmittedOptionalStaysOmittedRatherThanArrivingEmpty(t *testing.T) {
	// The server reads an explicit empty value as *set this to nothing*, which is a different
	// instruction from *leave it alone*.
	server := armarius(t)
	if code, _, errs := run(t, server.env(), "task", "status", "-status", "in_progress"); code != ExitOK {
		t.Fatalf("exit %d (%s)", code, errs)
	}
	if _, sent := server.body["reason"]; sent {
		t.Fatalf("an untouched flag was sent anyway: %v", server.body)
	}
}

// ── the project set (T138) ───────────────────────────────────────────────────

func TestProjectCommandsAimAtTheProjectThisRunIsAbout(t *testing.T) {
	server := armarius(t)
	env := server.env()
	env.TaskID = "" // a Leader's run: a project, no task

	cases := []struct {
		args   []string
		method string
		path   string
	}{
		{[]string{"project", "queue"}, "GET", "/agent/projects/project-1/queue"},
		{[]string{"project", "new-task", "-title", "Ship it"}, "POST", "/agent/projects/project-1/tasks"},
		{[]string{"project", "context", "-objective", "o"}, "POST", "/agent/projects/project-1/context"},
		{[]string{"project", "plan", "-summary", "s"}, "POST", "/agent/projects/project-1/plan"},
		{[]string{"project", "phase", "-target_phase", "operating"}, "POST", "/agent/projects/project-1/phase-proposal"},
		{[]string{"project", "sprint-summary", "-summary", "done"}, "POST", "/agent/projects/project-1/sprint-summary"},
		{[]string{"project", "change-request", "-area", "scope", "-summary", "wider"}, "POST", "/agent/projects/project-1/change-request"},
	}
	for _, c := range cases {
		if code, _, errs := run(t, env, c.args...); code != ExitOK {
			t.Fatalf("%v: exit %d (%s)", c.args, code, errs)
		}
		if server.method != c.method || server.path != c.path {
			t.Fatalf("%v: went to %s %s, wanted %s %s", c.args, server.method, server.path, c.method, c.path)
		}
	}
}

func TestARunAboutOneTaskIsNeverGivenTheProjectSet(t *testing.T) {
	// FR-013d: the toolset **is** the scope. The Leader's commands are not a superset an
	// ordinary worker inherits — a task-level run does not have them to call.
	server := armarius(t)
	env := server.env() // both ids set: a task-level run

	code, _, errs := run(t, env, "project", "queue")
	if code != ExitUsage {
		t.Fatalf("exit %d, wanted %d — a worker was handed a Leader's command", code, ExitUsage)
	}
	if server.method != "" {
		t.Fatal("a project call went out from a run about one task")
	}
	if !strings.Contains(errs, "no such command") {
		t.Fatalf("the refusal reads wrongly: %q", errs)
	}
	for _, cmd := range Commands(env) {
		if cmd.Group == GroupProject {
			t.Fatalf("a task-level run was handed %q", cmd.Name)
		}
	}
}

func TestARunAboutNeitherGetsOnlyWhatBelongsToNoScope(t *testing.T) {
	// The team-building interview (FR-040c): a run with no task and no project.
	env := Environment{Server: "http://example.invalid", RunToken: "armr_run_x"}
	for _, cmd := range Commands(env) {
		if cmd.Group != GroupAny {
			t.Fatalf("a workspace-level run was handed %q, which belongs to %s", cmd.Name, cmd.Group)
		}
	}
	if len(Commands(env)) == 0 {
		t.Fatal("a workspace-level run was handed nothing at all")
	}
}

func TestPlanItemsArriveAsAListAndAMalformedOneIsRefusedRatherThanEmptied(t *testing.T) {
	server := armarius(t)
	env := server.env()
	env.TaskID = ""

	if code, _, errs := run(t, env, "project", "plan", "-summary", "s", "-items", `[{"title":"One"}]`); code != ExitOK {
		t.Fatalf("exit %d (%s)", code, errs)
	}
	items, ok := server.body["items"].([]any)
	if !ok || len(items) != 1 {
		t.Fatalf("the plan items did not arrive as a list: %v", server.body["items"])
	}

	server.method = ""
	code, _, _ := run(t, env, "project", "plan", "-summary", "s", "-items", "not json")
	if code != ExitUsage {
		t.Fatalf("exit %d, wanted %d", code, ExitUsage)
	}
	if server.method != "" {
		t.Fatal("a plan with an unreadable item list was filed as an empty plan")
	}
}
