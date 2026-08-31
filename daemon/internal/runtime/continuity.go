package runtime

import (
	"fmt"
	"strings"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// The ways a conversation is not carried on. Codes, because the agent reads a sentence and the
// run's log keeps the parts (Constitution VII, FR-084a): one of these plus its parameters is
// what is written down, and the English below is what is said.
const (
	// RestartExpired means the thread was remembered and is older than this machine keeps
	// threads (FR-027).
	RestartExpired = "session_expired"
	// RestartWorkplaceRebuilt means the thread belonged to a workplace that is no longer the
	// one serving this agent — the machine was rebuilt, or the daemon registered again as a new
	// workplace (FR-026).
	RestartWorkplaceRebuilt = "session_workplace_rebuilt"
	// RestartUnreadable means there is a note about a previous session that this daemon
	// cannot read.
	RestartUnreadable = "session_unreadable"
	// RestartRefused means the handle was handed over and the CLI would not load it. Discovered
	// inside the turn rather than before it, which is why this one is raised by the runtime
	// itself (FR-039a).
	RestartRefused = "session_not_resumed"
	// RestartNotResumable means the workplace did not declare that it can carry a conversation
	// on, so the handle this task was holding was never offered (FR-017, FR-039a).
	//
	// The difference from RestartRefused is where it was found out, and it is worth a code of
	// its own for that reason alone: this one is known *before* the turn, from the CLI's own
	// account of itself, and acting on it is the degrade FR-039a calls still-supported. The
	// other is a handle that was offered in good faith and bounced.
	RestartNotResumable = "session_cli_not_resumable"
)

// Restart is a conversation that had to begin again, and why.
//
// Carried on the Request rather than folded into the message, and the difference is the whole
// of FR-011a: the message is the server's, assembled there, recorded there before it was sent,
// and nothing on this machine may compose any part of it. This is not part of it. It is one
// sentence from the machine about the machine, and it travels beside the message so that the
// agent reads both without either being rewritten.
type Restart struct {
	Code   string
	Params map[string]any
}

// restartReasons is the second half of each sentence: what happened, in English.
//
// A table rather than a switch so that the property SC-007 actually asks for — *every* way of
// losing a thread is told to the agent, none is silent — is a thing a test can walk rather than
// a thing a reader has to trust. A code added without a line here has no sentence, and the test
// beside this file fails on the day it is added rather than on the day it happens.
var restartReasons = map[string]string{
	RestartExpired: "the previous session for this task had not been used for %s, " +
		"which is longer than this machine keeps one",
	RestartWorkplaceRebuilt: "the previous session belonged to a workplace that no longer " +
		"serves this agent, so nothing on this machine can still open it",
	RestartUnreadable: "this machine kept a note of the previous session and can no longer " +
		"read it",
	RestartRefused: "the previous session was offered to the agent and it could not be loaded",
	RestartNotResumable: "the agent CLI serving this task did not declare that it can carry a " +
		"conversation on, so the previous session was not offered to it",
}

// Notice is what the agent is told, in English (Constitution VII).
//
// It says three things in this order, and each earns its place. *This is a new conversation* is
// the fact the agent has to act on. *Because …* is what stops it treating the restart as its own
// mistake and going looking for what it forgot. *Everything you need is in the brief* is the
// instruction that follows from the first two — without it an agent that remembers being
// mid-task will try to carry on from a memory it does not have.
func (r *Restart) Notice() string {
	if r == nil || r.Code == "" {
		return ""
	}
	reason, known := restartReasons[r.Code]
	if !known {
		// A code with no sentence is a bug in this file, and the answer to it is still a
		// notice: FR-025 asks for one every time, and a silent restart is the one outcome
		// SC-007 rules out. The code goes in the sentence so the gap names itself.
		reason = fmt.Sprintf("the previous session could not be carried on (%s)", r.Code)
	} else if strings.Contains(reason, "%s") {
		reason = fmt.Sprintf(reason, r.detail())
	}
	return "This is a new conversation, not a continuation: " + reason + ". " +
		"Do not rely on remembering earlier turns of this task — everything you need has been " +
		"given to you again in the brief above."
}

// detail is the one parameter a sentence above interpolates, rendered for a reader.
func (r *Restart) detail() string {
	if idle, ok := r.Params["idle"].(time.Duration); ok {
		return idle.Round(time.Hour).String()
	}
	return "some time"
}

// Continue decides whether this run carries the previous conversation on, and what the agent is
// told when it does not.
//
// Everything it needs is already decided: execenv answered whether a thread exists and whether
// it is still within its keeping, the workplace answered whether this CLI can carry one on at
// all (FR-017), and the caller knows which workplace is serving this agent now. What is left
// here is the two comparisons execenv cannot make and the words for all of them.
//
// **A first run is not a restart.** ThreadNone returns no handle and no notice: there is nothing
// to have lost, and an agent told it is starting over on its first turn would go looking for a
// history that never existed.
func Continue(
	thread execenv.Thread, verdict execenv.Verdict, workplace string, resumable bool, now time.Time,
) (string, *Restart) {
	switch verdict {
	case execenv.ThreadNone:
		return "", nil
	case execenv.ThreadExpired:
		return "", &Restart{
			Code:   RestartExpired,
			Params: map[string]any{"idle": now.Sub(thread.LastUsedAt)},
		}
	case execenv.ThreadUnreadable:
		return "", &Restart{Code: RestartUnreadable}
	}

	// FR-017's answer, applied rather than merely recorded. The workplace was asked whether it
	// can carry a conversation on and said it could not, so the handle is not offered — and the
	// agent is told why, which is the whole of FR-039a's *degraded is still supported*.
	//
	// Checked after ThreadNone on purpose. A CLI that never resumes also never hands back a
	// handle, so its ordinary turns have nothing to have lost and are not restarts at all; what
	// is left here is the case that actually needs saying — a thread this machine is holding,
	// for a workplace that has since answered that it cannot open one.
	if !resumable {
		return "", &Restart{Code: RestartNotResumable}
	}

	// FR-026, and the reason it is checked here rather than where the thread was read: only
	// this side knows which workplace is serving the agent *now*. An empty workplace on either
	// side is not evidence of a rebuild — it is a thread written before this was recorded, or a
	// caller that did not say — and refusing to continue on an absence would throw away good
	// conversations to enforce a rule about a case that has not arisen.
	if thread.Workplace != "" && workplace != "" && thread.Workplace != workplace {
		return "", &Restart{
			Code: RestartWorkplaceRebuilt,
			Params: map[string]any{
				"opened_at": thread.Workplace,
				"serving":   workplace,
			},
		}
	}
	return thread.Handle, nil
}

// tell records the restart in the run's log and returns the sentence to put before the message.
//
// One call for both families, so that a restart looks the same in the record whichever kind of
// CLI it happened to. The log keeps the code and its parameters; the agent gets the English.
func tell(j *Journal, r *Restart) string {
	if r == nil {
		return ""
	}
	details := make(map[string]any, len(r.Params))
	for key, value := range r.Params {
		if idle, isDuration := value.(time.Duration); isDuration {
			details[key+"_seconds"] = int(idle.Seconds())
			continue
		}
		details[key] = value
	}
	j.Fail(r.Code, details)
	return r.Notice()
}

// ahead puts the machine's own sentence before the server's message, without touching it.
func ahead(notice, message string) string {
	if notice == "" {
		return message
	}
	return notice + "\n\n" + message
}
