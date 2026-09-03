package callback

import (
	"strings"
	"testing"
)

// interviewEnv is a run about neither a task nor a project — the shape the team-building
// interview arrives in (FR-040c).
func interviewEnv(f *fakeArmarius) Environment {
	env := f.env()
	env.TaskID = ""
	env.ProjectID = ""
	return env
}

func TestAQuestionGoesToTheChatItNames(t *testing.T) {
	server := armarius(t)

	code, _, errs := run(t, interviewEnv(server),
		"onboarding", "ask",
		"-session_id", "sess-9",
		"-question", "What are you building?",
		"-options", `[{"id":"1","label":"A web app"}]`,
	)

	if code != ExitOK {
		t.Fatalf("exit %d: %s", code, errs)
	}
	if server.method != "POST" || server.path != "/agent/onboarding/sess-9/question" {
		t.Fatalf("the question went to %s %s", server.method, server.path)
	}
	if server.body["question"] != "What are you building?" {
		t.Fatalf("the question did not travel: %#v", server.body)
	}
	options, ok := server.body["options"].([]any)
	if !ok || len(options) != 1 {
		t.Fatalf("the options did not arrive as a list: %#v", server.body["options"])
	}
	// Not given is not the same as given false, but for this one flag they mean the same thing
	// to the server, and sending it always is what keeps that true from both faces.
	if server.body["multi"] != false {
		t.Fatalf("multi should have travelled as false: %#v", server.body["multi"])
	}
}

func TestAQuestionWithNoOptionsIsStillAQuestion(t *testing.T) {
	// A question the patron types the answer to. An empty list is a real answer here, so it
	// must not be refused the way a malformed one is.
	server := armarius(t)

	code, _, errs := run(t, interviewEnv(server),
		"onboarding", "ask", "-session_id", "sess-9", "-question", "What should we call it?")

	if code != ExitOK {
		t.Fatalf("exit %d: %s", code, errs)
	}
	if options, ok := server.body["options"].([]any); !ok || len(options) != 0 {
		t.Fatalf("options should be an empty list: %#v", server.body["options"])
	}
}

func TestAMalformedOptionListIsRefusedRatherThanEmptied(t *testing.T) {
	// Sending it on as an empty list would ask the patron a question with no answers and
	// report success — the agent would have no idea anything went wrong.
	server := armarius(t)

	code, _, errs := run(t, interviewEnv(server),
		"onboarding", "ask", "-session_id", "s", "-question", "q", "-options", "{not json")

	if code != ExitUsage {
		t.Fatalf("exit %d, wanted %d", code, ExitUsage)
	}
	if server.path != "" {
		t.Fatalf("a malformed call still reached the server at %q", server.path)
	}
	if !strings.Contains(errs, "options must be a JSON array") {
		t.Fatalf("the refusal does not say what is wrong: %q", errs)
	}
}

func TestACallThatNamesNoChatNeverLeavesTheMachine(t *testing.T) {
	// A path with an empty id in the middle of it is a different path, and whatever it comes
	// back with is about something else.
	server := armarius(t)

	code, _, errs := run(t, interviewEnv(server), "onboarding", "ask", "-question", "q")

	if code != ExitUsage {
		t.Fatalf("exit %d, wanted %d", code, ExitUsage)
	}
	if server.path != "" {
		t.Fatalf("a call naming no chat reached the server at %q", server.path)
	}
	if !strings.Contains(errs, "session_id") {
		t.Fatalf("the refusal does not name what is missing: %q", errs)
	}
}

func TestTheDraftCarriesBothHalvesInTheShapeTheServerTakes(t *testing.T) {
	server := armarius(t)

	code, _, errs := run(t, interviewEnv(server),
		"onboarding", "propose",
		"-session_id", "sess-9",
		"-project", `{"name":"Task Tracker","objective":"A web app"}`,
		"-roster", `[{"title":"Frontend","description":"Builds the UI.","seats":1}]`,
	)

	if code != ExitOK {
		t.Fatalf("exit %d: %s", code, errs)
	}
	if server.path != "/agent/onboarding/sess-9/complete" {
		t.Fatalf("the draft went to %q", server.path)
	}
	project, ok := server.body["project"].(map[string]any)
	if !ok || project["name"] != "Task Tracker" {
		t.Fatalf("the project did not arrive as an object: %#v", server.body["project"])
	}
	if roster, ok := server.body["roster"].([]any); !ok || len(roster) != 1 {
		t.Fatalf("the roster did not arrive as a list: %#v", server.body["roster"])
	}
}

func TestARunAboutATaskIsNeverHandedTheInterview(t *testing.T) {
	// The toolset *is* the scope (FR-013d): a worker on one task is not handed the tools for
	// setting a project up, and "not handed" is literal — there is no command to call.
	server := armarius(t)

	code, _, errs := run(t, server.env(), "onboarding", "ask", "-session_id", "s", "-question", "q")

	if code == ExitOK {
		t.Fatal("a task-level run asked the patron an onboarding question")
	}
	if !strings.Contains(errs, "no such command") {
		t.Fatalf("the refusal reads wrongly: %q", errs)
	}
	if server.path != "" {
		t.Fatalf("it still reached the server at %q", server.path)
	}
}
