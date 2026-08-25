package discovery

import (
	"context"
	"errors"
	"testing"
	"time"
)

// claudeHelp is the shape of what `claude --help` prints, cut down to the lines the probe
// reads. Copied from claude 2.1.226 on 2026-08-25 rather than invented, so a test passing here
// means something about the real binary.
const claudeHelp = `Usage: claude [options] [command] [prompt]

Options:
  -c, --continue                        Continue the most recent conversation
  -r, --resume [value]                  Resume a conversation by session ID
  --output-format <format>              Output format (only works with --print):
                                        "text" (default), "json" (single
                                        result), or "stream-json" (realtime
                                        streaming)
`

func askedWith(printed string, err error) Options {
	return Options{
		Run: func(_ context.Context, _ string, _ ...string) ([]byte, error) {
			if err != nil {
				return nil, err
			}
			return []byte(printed), nil
		},
		Timeout: time.Second,
	}
}

func TestAOneShotCLIsCapabilitiesComeFromWhatItPrinted(t *testing.T) {
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}

	got := Probe(context.Background(), found, askedWith(claudeHelp, nil))

	if !got.Resumable {
		t.Error("it printed --resume and --continue; resumable should be true")
	}
	if !got.ExposesToolArgs || !got.ExposesToolResult {
		t.Error("it printed stream-json, the form that carries tool calls and their results")
	}
	if len(got.Unanswered) != 0 {
		t.Errorf("everything was asked and answered, yet %+v came back unanswered", got.Unanswered)
	}
}

// The point of FR-017. Same CLI, same name, a build without the resume flag — and the answer
// has to change, because it came from the binary rather than from the name on it.
func TestTheSameCLIWithoutTheFlagIsReportedWithoutTheCapability(t *testing.T) {
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}
	stripped := `Usage: claude [options] [prompt]

Options:
  --output-format <format>   "text" (default)
`

	got := Probe(context.Background(), found, askedWith(stripped, nil))

	if got.Resumable {
		t.Error("nothing in what it printed says it can resume, so nothing may say so here")
	}
	if got.ExposesToolArgs || got.ExposesToolResult {
		t.Error("no streaming form was offered, so no tool call ever reaches the server")
	}
}

// A family the daemon cannot yet interrogate registers with everything unanswered and a code
// saying why. It does not register with guesses, and it does not fail to register: a CLI with
// no declared capability is still supported, degraded (FR-039a).
func TestAFamilyWithNoProbeSaysSoRatherThanGuessing(t *testing.T) {
	found := Found{Kind: KindGemini, Family: FamilyACP, Path: "/usr/local/bin/gemini"}

	got := Probe(context.Background(), found, askedWith("anything at all", nil))

	if got.Resumable || got.ExposesToolArgs || got.ExposesToolResult {
		t.Fatalf("nothing was asked, so nothing may be claimed: %+v", got)
	}
	if len(got.Unanswered) != len(everyCapability) {
		t.Fatalf("want every capability marked unanswered, got %+v", got.Unanswered)
	}
	for _, missing := range got.Unanswered {
		if missing.Reason != ReasonNoProbe {
			t.Errorf("reason = %q, want %q", missing.Reason, ReasonNoProbe)
		}
	}
}

func TestACLIThatRefusesToDescribeItselfIsUnansweredNotAssumed(t *testing.T) {
	found := Found{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"}

	got := Probe(context.Background(), found, askedWith("", errors.New("exit status 2")))

	if len(got.Unanswered) != len(everyCapability) {
		t.Fatalf("want every capability marked unanswered, got %+v", got.Unanswered)
	}
	if got.Unanswered[0].Reason != ReasonProbeFailed {
		t.Errorf("reason = %q, want %q", got.Unanswered[0].Reason, ReasonProbeFailed)
	}
}

func TestEveryFoundCLIGetsAskedInOrder(t *testing.T) {
	found := []Found{
		{Kind: KindGemini, Family: FamilyACP, Path: "/usr/local/bin/gemini"},
		{Kind: KindClaudeCode, Family: FamilyOneShot, Path: "/usr/bin/claude"},
	}

	got := ProbeAll(context.Background(), found, askedWith(claudeHelp, nil))

	if len(got) != 2 {
		t.Fatalf("want one answer per CLI, got %+v", got)
	}
	if len(got[0].Unanswered) == 0 {
		t.Error("the ACP one cannot be asked yet and must say so")
	}
	if !got[1].Resumable {
		t.Error("the one-shot one was asked and answered")
	}
}
