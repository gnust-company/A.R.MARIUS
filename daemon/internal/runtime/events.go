package runtime

import (
	"unicode/utf8"

	"github.com/gnust-company/armarius-daemon/internal/redact"
)

// DefaultResultLimit is how many bytes of a tool's result may travel inline (FR-043a).
//
// Small on purpose. The number is not a compression setting — it is the size of the largest
// mistake this rule can make, because whatever fits inside it leaves the machine. A reader
// looking at a run wants to know *that* a tool returned forty kilobytes of build log and what
// its first lines said; reading the forty kilobytes is done on the machine that has them.
const DefaultResultLimit = 512

// Why something is missing from the record (FR-047).
//
// Two reasons that look identical on screen — a short result and a short result — and mean
// opposite things. *We cut this* is a decision this system made and can undo by raising a
// threshold. *The CLI never said* is a fact about the tool, and no setting here will change it.
// Showing them the same way tells a reader to go looking for a setting that does not exist.
const (
	// TruncatedByPolicy: the result was longer than the threshold and the rest stayed home.
	TruncatedByPolicy = "truncated_by_policy"
	// NotExposedByCLI: this CLI does not reveal the data at all, so there was nothing to cut.
	NotExposedByCLI = "not_exposed_by_cli"
)

// Result is what a CLI said about what a tool gave back.
type Result struct {
	// Exposed is false when the CLI never revealed the output. Different from an empty output,
	// and telling those two apart is the whole of FR-047.
	Exposed bool
	// Body is the output as the tool produced it. **It does not leave this machine** (FR-043a):
	// what leaves is the summary built here from it.
	Body string
	// Kind is what sort of thing came back, when the CLI says so. Empty is ordinary.
	Kind string
}

// Journal is the one gate every event passes through on its way off this machine.
//
// One gate rather than a rule each reader remembers, because the two rules it enforces are the
// kind that fail silently when a new reader forgets them: a tool result that was never cut looks
// exactly like a small tool result, and a token that was never masked looks exactly like a token
// that had nothing to hide. Neither shows up as a broken run — they show up as a leak nobody
// notices, so the enforcement point cannot be a habit.
type Journal struct {
	out   Emit
	mask  *redact.Masker
	limit int
}

// NewJournal builds the gate for one run, out of the secrets that run knows.
//
// The credentials come from the request rather than from the environment because that is where
// they are *known* rather than guessed at: this run was handed its own token and its machine's,
// and an exact string search for a value you were given is the only part of masking that is a
// guarantee instead of a pattern (FR-048).
func NewJournal(req Request, emit Emit) *Journal {
	if emit == nil {
		emit = func(Event) {}
	}
	limit := req.ResultLimit
	if limit <= 0 {
		limit = DefaultResultLimit
	}
	return &Journal{out: emit, mask: redact.For(req.Secrets...), limit: limit}
}

// Say masks an event and lets it out.
//
// Masking here rather than at each call site is what makes FR-048a true of *every* channel: the
// message, the arguments, the agent's own words and every error all reach the server through
// this one call, so a channel added tomorrow is covered by having been written at all.
func (j *Journal) Say(event Event) {
	if j == nil {
		return
	}
	masked, hidden := j.mask.Payload(event.Payload)
	event.Payload = masked
	event.Redacted = event.Redacted || hidden
	j.out(event)
}

// Text records something the agent wrote (FR-044).
func (j *Journal) Text(text string) {
	if text == "" {
		return
	}
	j.Say(Event{Type: EventAssistantMessage, Payload: map[string]any{"text": text}})
}

// Thought records the agent's reasoning, for the CLIs that expose any (FR-044).
func (j *Journal) Thought(text string) {
	if text == "" {
		return
	}
	j.Say(Event{Type: EventAssistantThinking, Payload: map[string]any{"text": text}})
}

// ToolStarted records a call, with its arguments in full (FR-043).
//
// In full, and deliberately so: it is the *result* that must never leave this machine, not the
// request. A call whose arguments this CLI does not reveal is marked as such rather than sent
// with an empty map, because an empty map reads as *called with nothing* — a different fact,
// and one that would quietly make a CLI look worse-behaved than it is (FR-047).
func (j *Journal) ToolStarted(call, name string, args map[string]any, exposed bool) {
	payload := map[string]any{"call": call, "name": name}
	event := Event{Type: EventToolStarted, Payload: payload}
	if exposed {
		payload["args"] = args
	} else {
		event.OmissionReason = NotExposedByCLI
	}
	j.Say(event)
}

// ToolCompleted records that a call ended, and summarises what came back (FR-043a, FR-043b).
//
// The summary is a size, a kind and an opening slice. The size is measured **before** masking
// and before cutting, because it answers the reader's actual question — how much did this tool
// produce — and a number measured after either step would answer a question about this daemon's
// settings instead.
func (j *Journal) ToolCompleted(call string, failed bool, result Result) {
	payload := map[string]any{"call": call, "failed": failed}
	event := Event{Type: EventToolCompleted, Payload: payload}
	if result.Kind != "" {
		payload["kind"] = result.Kind
	}

	if !result.Exposed {
		event.OmissionReason = NotExposedByCLI
		j.Say(event)
		return
	}

	size := len(result.Body)
	payload["bytes"] = size
	event.OriginalBytes = size

	// Masked before cut, not after. A secret lying across the threshold would otherwise be cut
	// in half and the first half sent — and half a token is half a token, not a redaction.
	//
	// But only as far as the cut can reach. Masking the whole body would be work proportional
	// to what the tool printed, on the goroutine reading the CLI — and that goroutine must not
	// stall (a megabyte of build log measured at ~470ms, and a line may be eight of them). The
	// tail is discarded either way, so masking it protects nothing: what leaves is the opening,
	// and `Window` masks exactly enough to be honest about that.
	body, hidden := j.mask.Window(result.Body, j.limit)
	event.Redacted = hidden

	opening, _ := j.trim(body)
	payload["opening"] = opening
	// Read off the original, not off what masking left: masking shortens text, so a body that
	// was over the threshold can come back under it, and *truncated* is a fact about the
	// result — how much the tool produced — not about how much of it was worth hiding.
	if size > j.limit {
		event.Truncated = true
		event.OmissionReason = TruncatedByPolicy
	}
	j.Say(event)
}

// Fail records something that went wrong, as a code with its details (Constitution VII).
func (j *Journal) Fail(code string, details map[string]any) {
	payload := map[string]any{"code": code}
	for key, value := range details {
		if key != "code" {
			payload[key] = value
		}
	}
	j.Say(Event{Type: EventRunError, Payload: payload})
}

// trim cuts to the threshold at a character boundary, and says whether anything was taken.
//
// At a character boundary because cutting mid-sequence produces bytes that are not text: the
// tail would reach the screen as a replacement glyph, which reads as *the tool printed
// something strange* rather than as *this was cut here*.
func (j *Journal) trim(s string) (string, bool) {
	if len(s) <= j.limit {
		return s, false
	}
	kept := s[:j.limit]
	for len(kept) > 0 {
		last, width := utf8.DecodeLastRuneInString(kept)
		if last != utf8.RuneError || width > 1 {
			break
		}
		kept = kept[:len(kept)-1]
	}
	return kept, true
}
