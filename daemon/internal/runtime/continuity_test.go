package runtime

import (
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// SC-007, stated as the property rather than as a list: **every** way of losing a thread is told
// to the agent, and none of them is silent. Walking the table is what makes that true of codes
// added later — a code with no sentence fails here on the day it is written.
func TestEveryLostThreadIsToldToTheAgent(t *testing.T) {
	codes := []string{
		RestartExpired, RestartWorkplaceRebuilt, RestartUnreadable, RestartRefused,
		"a_code_nobody_wrote_a_sentence_for",
	}
	for _, code := range codes {
		t.Run(code, func(t *testing.T) {
			notice := (&Restart{Code: code, Params: map[string]any{"idle": 15 * 24 * time.Hour}}).Notice()
			if notice == "" {
				t.Fatal("a conversation was restarted and the agent was told nothing")
			}
			if !strings.Contains(notice, "new conversation") {
				t.Errorf("the notice does not say this is a new conversation: %q", notice)
			}
			if !strings.Contains(notice, "brief") {
				t.Errorf("the notice does not say where the agent's context actually is: %q", notice)
			}
		})
	}
}

// Nothing lost, nothing said. A thread carried on is the ordinary case and it is silent.
func TestCarryingOnSaysNothing(t *testing.T) {
	now := time.Now()
	handle, restart := Continue(
		execenv.Thread{Handle: "sess-abc", Workplace: "place-1", LastUsedAt: now},
		execenv.ThreadUsable, "place-1", now,
	)
	if handle != "sess-abc" {
		t.Errorf("the handle is %q, want the one that was remembered", handle)
	}
	if restart != nil {
		t.Errorf("a conversation that carried on was announced as a restart: %v", restart.Code)
	}
	if restart.Notice() != "" {
		t.Errorf("a nil restart still said something: %q", restart.Notice())
	}
}

// A first run is not a restart: there is nothing to have lost (FR-025).
func TestAFirstTurnIsNotAnnouncedAsARestart(t *testing.T) {
	handle, restart := Continue(execenv.Thread{}, execenv.ThreadNone, "place-1", time.Now())
	if handle != "" {
		t.Errorf("a task with no history was given the handle %q", handle)
	}
	if restart != nil {
		t.Errorf("the first turn on a task was announced as a restart: %v", restart.Code)
	}
}

// FR-026: a thread that belongs to a workplace no longer serving this agent is not carried on,
// and it is not quietly pretended to be either.
func TestAThreadFromARebuiltWorkplaceIsNotPretendedToContinue(t *testing.T) {
	now := time.Now()
	handle, restart := Continue(
		execenv.Thread{Handle: "sess-abc", Workplace: "the-old-place", LastUsedAt: now},
		execenv.ThreadUsable, "the-place-now-serving", now,
	)
	if handle != "" {
		t.Errorf("the old handle was handed over anyway: %q", handle)
	}
	if restart == nil || restart.Code != RestartWorkplaceRebuilt {
		t.Fatalf("the restart is %v, want %s", restart, RestartWorkplaceRebuilt)
	}
	if restart.Params["opened_at"] != "the-old-place" || restart.Params["serving"] != "the-place-now-serving" {
		t.Errorf("the record does not say which two workplaces differed: %v", restart.Params)
	}
}

// An absence is not evidence of a rebuild. A thread written before the workplace was recorded, or
// a caller that did not say, must not cost a conversation that is perfectly good.
func TestAnUnknownWorkplaceIsNotTreatedAsADifferentOne(t *testing.T) {
	now := time.Now()
	for name, pair := range map[string][2]string{
		"the thread does not say": {"", "place-1"},
		"the caller does not say": {"place-1", ""},
	} {
		t.Run(name, func(t *testing.T) {
			handle, restart := Continue(
				execenv.Thread{Handle: "sess-abc", Workplace: pair[0], LastUsedAt: now},
				execenv.ThreadUsable, pair[1], now,
			)
			if handle != "sess-abc" || restart != nil {
				t.Errorf("a conversation was restarted on an absence: handle %q, restart %v",
					handle, restart)
			}
		})
	}
}

// FR-027: past its keeping, the thread is not offered, and the notice says how long it sat.
func TestAThreadPastItsKeepingIsAnnouncedWithHowLongItSat(t *testing.T) {
	now := time.Now()
	handle, restart := Continue(
		execenv.Thread{Handle: "sess-old", LastUsedAt: now.Add(-20 * 24 * time.Hour)},
		execenv.ThreadExpired, "place-1", now,
	)
	if handle != "" {
		t.Errorf("an expired handle was handed over: %q", handle)
	}
	if restart == nil || restart.Code != RestartExpired {
		t.Fatalf("the restart is %v, want %s", restart, RestartExpired)
	}
	if notice := restart.Notice(); !strings.Contains(notice, "480h") {
		t.Errorf("the notice does not say how long the thread sat: %q", notice)
	}
}

// A note this daemon cannot read is a restart with a reason, not a silent new conversation.
func TestANoteThatCannotBeReadIsStillAnnounced(t *testing.T) {
	handle, restart := Continue(execenv.Thread{}, execenv.ThreadUnreadable, "place-1", time.Now())
	if handle != "" {
		t.Errorf("a handle came out of an unreadable note: %q", handle)
	}
	if restart == nil || restart.Code != RestartUnreadable {
		t.Fatalf("the restart is %v, want %s", restart, RestartUnreadable)
	}
}

// Two readers, two languages, one fact (Constitution VII, FR-084a). The run's log keeps the code
// and its parts; the agent gets the English. The sentence is never what is stored.
func TestTheLogKeepsTheCodeAndTheAgentGetsTheEnglish(t *testing.T) {
	var said []Event
	journal := NewJournal(Request{}, func(e Event) { said = append(said, e) })

	notice := tell(journal, &Restart{
		Code:   RestartExpired,
		Params: map[string]any{"idle": 15 * 24 * time.Hour},
	})

	if len(said) != 1 {
		t.Fatalf("%d events were recorded, want exactly one", len(said))
	}
	if said[0].Payload["code"] != RestartExpired {
		t.Errorf("the recorded code is %v, want %s", said[0].Payload["code"], RestartExpired)
	}
	if said[0].Payload["idle_seconds"] != int(15*24*time.Hour/time.Second) {
		t.Errorf("the recorded detail is %v, want the idleness in seconds", said[0].Payload["idle_seconds"])
	}
	for key, value := range said[0].Payload {
		if text, isText := value.(string); isText && strings.Contains(text, "new conversation") {
			t.Errorf("the sentence was stored under %q instead of the code and its parts", key)
		}
	}
	if notice == "" {
		t.Error("the agent was told nothing")
	}
}

// Nothing to say, nothing recorded. A run that carried its thread on leaves no trace of a restart
// that did not happen.
func TestNoRestartRecordsNothing(t *testing.T) {
	var said []Event
	journal := NewJournal(Request{}, func(e Event) { said = append(said, e) })
	if notice := tell(journal, nil); notice != "" {
		t.Errorf("a run that lost nothing was given a notice: %q", notice)
	}
	if len(said) != 0 {
		t.Errorf("%d events were recorded about a restart that did not happen", len(said))
	}
}

// The message is the server's: assembled there, recorded there before it was sent, and nothing on
// this machine may compose any part of it (FR-011a). The notice goes *before* it, whole.
func TestTheServersMessageIsNotTouched(t *testing.T) {
	message := "Do the thing. Here is the brief."
	if got := ahead("", message); got != message {
		t.Errorf("a run with nothing to announce changed the message: %q", got)
	}
	got := ahead("This is a new conversation.", message)
	if !strings.HasSuffix(got, message) {
		t.Errorf("the message was altered: %q", got)
	}
	if !strings.HasPrefix(got, "This is a new conversation.") {
		t.Errorf("the notice does not come first: %q", got)
	}
}
