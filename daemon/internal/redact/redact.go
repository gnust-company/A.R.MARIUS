// Package redact masks secret values before anything leaves the user's machine (FR-048).
//
// Masking belongs here rather than on the server, and the reason is the direction of travel: a
// secret that reached the server has already left the machine, and deleting it afterwards
// deletes a copy, not the fact. What this package does is the only version of the rule that is
// true — the bytes never go.
//
// Two nets, and they catch different things. The **known values** net is exact: this daemon
// minted or was handed the run token and the machine token, so it can look for those strings
// and be right every time. The **shape** net is a guess: it recognises the forms credentials
// usually take, and it exists for the ones nobody told us about — a key the agent read out of a
// file, an environment variable a tool printed. The first net is the guarantee; the second is
// there because the first only knows what it was told (FR-048a).
package redact

import (
	"regexp"
	"sort"
	"strings"
)

// Marker is what a masked value is replaced with.
//
// One fixed string rather than a length-preserving blob: a reader has to be able to tell that
// something was taken out, and a row of asterisks as long as the original hands back the one
// property of a secret that is worth guessing from.
const Marker = "[redacted]"

// tooShortToBeSecret is the length below which an exact value is not searched for.
//
// A three-character token would match inside ordinary words, and the result would be a log where
// half the prose is [redacted] — unreadable, and no safer. Anything a server mints is far longer
// than this, so the guard costs nothing real.
const tooShortToBeSecret = 12

// Masker replaces the values it was told about, and the shapes it recognises.
//
// The zero value is usable and masks by shape alone, which is what a caller that has no
// credentials to declare should get: fewer guarantees, not none.
type Masker struct {
	// known is sorted longest first, so a secret that contains a shorter one is masked whole
	// rather than left with its tail showing.
	known []string
}

// For builds a masker that knows these exact values.
//
// Empty and too-short entries are dropped rather than refused: the callers are assembling a list
// out of fields that are legitimately absent — a machine token this daemon was not given, an
// optional variable — and a masker that refuses to exist because one of them was blank would
// leave everything unmasked to report a non-problem.
func For(secrets ...string) *Masker {
	m := &Masker{}
	seen := map[string]bool{}
	for _, secret := range secrets {
		secret = strings.TrimSpace(secret)
		if len(secret) < tooShortToBeSecret || seen[secret] {
			continue
		}
		seen[secret] = true
		m.known = append(m.known, secret)
	}
	sort.SliceStable(m.known, func(i, j int) bool { return len(m.known[i]) > len(m.known[j]) })
	return m
}

// shaped is what a credential usually looks like when nobody declared it.
//
// Every entry here is anchored on a prefix the issuing service chose, or on a structure that
// does not occur in prose. Nothing matches on entropy or length alone: a rule that masks "any
// long word" turns a stack trace into confetti, and a log nobody can read is a log nobody reads.
var shaped = []*regexp.Regexp{
	// Anthropic, OpenAI and the many services that copied the form.
	regexp.MustCompile(`\bsk-[A-Za-z0-9][A-Za-z0-9_-]{16,}`),
	// GitHub, all four token kinds plus fine-grained.
	regexp.MustCompile(`\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}`),
	regexp.MustCompile(`\bgithub_pat_[A-Za-z0-9_]{20,}`),
	// Slack.
	regexp.MustCompile(`\bxox[abprs]-[A-Za-z0-9-]{10,}`),
	// AWS access key id, and the secret that travels beside it.
	regexp.MustCompile(`\b(?:AKIA|ASIA)[0-9A-Z]{16}\b`),
	// JSON Web Tokens: three base64url segments, the first of which always starts `eyJ`.
	regexp.MustCompile(`\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}`),
	// A PEM private key, however it is labelled, from its opening line to its closing one.
	regexp.MustCompile(`(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----`),
	// The same key with its closing line out of reach — everything after the header goes.
	//
	// Runs after the terminated form, so in whole text every key is already consumed by that
	// one and nothing reaches here. What reaches here is a header whose footer was left behind
	// a cut, and the bytes between them are the part worth stealing. Over-masking prose that
	// says BEGIN … PRIVATE KEY and never ends is the safe direction, and such prose is a broken
	// key far more often than it is a sentence.
	regexp.MustCompile(`(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*`),
}

// carrier matches a name that says the value beside it is a credential, and captures the value.
//
// This is how an environment variable is caught (FR-048): a tool that prints its environment,
// an agent that echoes a shell line. The name is the evidence — `DATABASE_PASSWORD=hunter2` says
// what it is holding, and nothing about `hunter2` itself would ever have given it away.
// The name and its separator are kept, the value goes: a reader has to be able to see *which*
// credential was there. Go's regexp has no backreference, so the closing quote is not matched —
// it is left behind after the marker, which reads fine and keeps the rule simple.
var carrier = regexp.MustCompile(
	`(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|APIKEY|API_KEY|ACCESS_KEY|PRIVATE_KEY|CREDENTIAL)S?"?\s*[:=]\s*"?)[^\s"']{6,}`,
)

// bearer matches an Authorization header value, whichever scheme it names.
var bearer = regexp.MustCompile(`(?i)\b(Bearer|Basic|Token)\s+([A-Za-z0-9._~+/=-]{12,})`)

// Text masks one string, and says whether it took anything out.
func (m *Masker) Text(s string) (string, bool) {
	if s == "" {
		return s, false
	}
	masked := s
	if m != nil {
		for _, secret := range m.known {
			masked = strings.ReplaceAll(masked, secret, Marker)
		}
	}
	for _, shape := range shaped {
		masked = shape.ReplaceAllString(masked, Marker)
	}
	masked = carrier.ReplaceAllString(masked, "${1}"+Marker)
	masked = bearer.ReplaceAllString(masked, "${1} "+Marker)
	return masked, masked != s
}

// patternReach is how far past a cut a **shape** can still begin and still be recognised.
//
// Every pattern above has a shortest form, and the longest of those shortest forms is a JWT at
// roughly thirty characters. This is that with room to spare: a secret whose first character
// lands before a cut stays fully visible to the masker as long as this many bytes follow it.
const patternReach = 256

// reach is how far past a cut this masker must look to recognise anything beginning before it.
func (m *Masker) reach() int {
	longest := patternReach
	// `known` is sorted longest first, and an exact value has to be seen whole to be found.
	if m != nil && len(m.known) > 0 && len(m.known[0]) > longest {
		longest = len(m.known[0])
	}
	return longest
}

// Window masks the leading part of s — enough of it to answer honestly about the first `keep`
// bytes — and says whether it took anything out of that part.
//
// Work is proportional to `keep`, not to len(s), and that is the whole point. The caller is
// about to throw the rest away: everything past the cut of a tool result stays on this machine
// (FR-043a), so masking it is work nobody can ever benefit from — and a tool that prints a
// megabyte turns it into *seconds* of it, on the goroutine reading the CLI, which is the one
// goroutine that must not stall.
//
// A secret lying **across** the cut is still caught: the window runs `reach()` bytes past
// `keep`, which is enough to see whole anything that begins before the cut. What begins after
// it is not masked and does not need to be — it never leaves.
//
// Trimming the result to size, and to a character boundary, is the caller's business.
func (m *Masker) Window(s string, keep int) (string, bool) {
	if keep < 0 {
		keep = 0
	}
	if window := keep + m.reach(); len(s) > window {
		s = s[:window]
	}
	return m.Text(s)
}

// Value masks anything that may appear in an event payload, walking into maps and slices.
//
// Keys are masked as well as values. A tool called with a map whose *key* is the secret is not a
// shape anyone designs on purpose, but it is one an agent can produce by accident, and a walk
// that only looks at values would carry it out intact.
func (m *Masker) Value(v any) (any, bool) {
	switch typed := v.(type) {
	case string:
		return m.Text(typed)
	case map[string]any:
		out := make(map[string]any, len(typed))
		changed := false
		for key, value := range typed {
			maskedKey, keyChanged := m.Text(key)
			maskedValue, valueChanged := m.Value(value)
			out[maskedKey] = maskedValue
			changed = changed || keyChanged || valueChanged
		}
		return out, changed
	case []any:
		out := make([]any, len(typed))
		changed := false
		for i, item := range typed {
			masked, itemChanged := m.Value(item)
			out[i] = masked
			changed = changed || itemChanged
		}
		return out, changed
	default:
		// Numbers, booleans, nil: nothing a string search could find, and nothing to rebuild.
		return v, false
	}
}

// Payload masks a whole event payload, returning it unchanged when there was nothing to take.
func (m *Masker) Payload(payload map[string]any) (map[string]any, bool) {
	if len(payload) == 0 {
		return payload, false
	}
	masked, changed := m.Value(payload)
	if !changed {
		return payload, false
	}
	return masked.(map[string]any), true
}
