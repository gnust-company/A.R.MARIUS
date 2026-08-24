// Package config holds the numbers an operator is allowed to turn on their own machine.
//
// There are five of them, and they are gathered here rather than scattered through the code
// because two of them are not independent: the lease the server grants when this machine claims
// a run has to outlast the whole wake-to-running budget, or the system takes work back from a
// machine that is doing everything right (FR-056c). A rule between two numbers can only be
// enforced where both numbers live.
//
// The silence threshold that decides a run has hung is deliberately NOT here. It carries a rule
// this file cannot express — each agent CLI may tighten it but none may loosen it — so it lives
// with the watchdog that enforces that rule.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"time"
)

// wakeToRunBudget is the 15 seconds SC-002 allows from deciding to wake an agent to that agent
// running. It is not a setting: it is the measurement the product is judged on. It appears here
// only so ClaimLease can be checked against it.
const wakeToRunBudget = 15 * time.Second

// Config is one machine's copy of the five numbers.
//
// The file it comes from also carries what `login` wrote — which server this machine belongs to
// and its token. Those are not read here: unknown fields are ignored, so both halves can share a
// file without either one having to know about the other.
type Config struct {
	// PollInterval is how often this machine asks the server for work when no push has arrived.
	// Polling is the fallback, not the main road (FR-055d) — if pushes stop arriving, the fix is
	// the push path, never a shorter interval here.
	PollInterval Duration `json:"poll_interval"`

	// HeartbeatInterval is how often this machine says it is alive. Three missed beats in a row
	// and every workplace on it is treated as unavailable (FR-004).
	HeartbeatInterval Duration `json:"heartbeat_interval"`

	// ClaimLease is how long a claimed run stays this machine's before the server takes it back.
	// It is generous on purpose: the lease does not exist to hand work to a faster machine — each
	// agent is bound to exactly one workplace — it exists so a task stops sitting in *claimed*
	// when the machine holding it has died (FR-056a).
	ClaimLease Duration `json:"claim_lease"`

	// ToolResultInlineLimit is how much of a tool's output travels to the server inside the event
	// itself. Past it the event carries the opening bytes, the true size and the fact that it was
	// cut (FR-043b) — never the rest of the content, which must not leave this machine (FR-043a).
	ToolResultInlineLimit int `json:"tool_result_inline_limit_bytes"`

	// MaxConcurrentRuns is how many runs this machine will hold at once. It is advice, not a
	// ceiling: the server keeps its own cap and takes the smaller of the two, so a machine that
	// reports a stale or wrong number still cannot be given more than the server allows
	// (FR-008d).
	MaxConcurrentRuns int `json:"max_concurrent_runs"`
}

// Defaults are the values a machine runs with when its config file says nothing. Every one of
// them is argued for in specs/002-daemon-acp-runtime/research.md §3 and §7.
func Defaults() Config {
	return Config{
		PollInterval:          Duration(5 * time.Second),
		HeartbeatInterval:     Duration(15 * time.Second),
		ClaimLease:            Duration(120 * time.Second),
		ToolResultInlineLimit: 2048,
		MaxConcurrentRuns:     5,
	}
}

// Load reads a config file, filling in Defaults for everything it does not mention.
//
// A missing file is not an error: a machine that has been linked but never tuned is the ordinary
// case, and it should run on the defaults rather than refuse to start.
func Load(path string) (Config, error) {
	cfg := Defaults()

	// The path is whatever the operator passed to -config on their own machine, pointing at
	// their own file. There is no boundary being crossed here to guard.
	raw, err := os.ReadFile(path) //nolint:gosec // operator-supplied path to the operator's own file
	if errors.Is(err, os.ErrNotExist) {
		return cfg, nil
	}
	if err != nil {
		return Config{}, fmt.Errorf("reading config %s: %w", path, err)
	}

	if err := json.Unmarshal(raw, &cfg); err != nil {
		return Config{}, fmt.Errorf("parsing config %s: %w", path, err)
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, fmt.Errorf("config %s: %w", path, err)
	}
	return cfg, nil
}

// Validate refuses settings that would break the machine quietly rather than loudly.
func (c Config) Validate() error {
	positive := []struct {
		name  string
		value time.Duration
	}{
		{"poll_interval", c.PollInterval.Duration()},
		{"heartbeat_interval", c.HeartbeatInterval.Duration()},
		{"claim_lease", c.ClaimLease.Duration()},
	}
	for _, p := range positive {
		if p.value <= 0 {
			return fmt.Errorf("%s must be greater than zero, got %s", p.name, p.value)
		}
	}

	// The one rule that spans two numbers. Preparing a workspace, writing the skills and starting
	// the CLI all happen inside the wake-to-running budget, so a lease shorter than that budget
	// takes the run back in the middle of a machine doing its job correctly (FR-056c).
	if c.ClaimLease.Duration() <= wakeToRunBudget {
		return fmt.Errorf(
			"claim_lease must be longer than the %s a wake is allowed to take, got %s",
			wakeToRunBudget, c.ClaimLease.Duration(),
		)
	}

	if c.ToolResultInlineLimit <= 0 {
		return fmt.Errorf(
			"tool_result_inline_limit_bytes must be greater than zero, got %d",
			c.ToolResultInlineLimit,
		)
	}
	if c.MaxConcurrentRuns < 1 {
		return fmt.Errorf("max_concurrent_runs must be at least 1, got %d", c.MaxConcurrentRuns)
	}
	return nil
}

// Duration is a time.Duration an operator can write the way they say it — "5s", "10m", "24h" —
// instead of counting nanoseconds into a JSON file.
type Duration time.Duration

// Duration returns the underlying value.
func (d Duration) Duration() time.Duration { return time.Duration(d) }

func (d Duration) String() string { return time.Duration(d).String() }

// MarshalJSON writes the value back in the same form it is read in.
func (d Duration) MarshalJSON() ([]byte, error) {
	return json.Marshal(time.Duration(d).String())
}

// UnmarshalJSON accepts "90s" and "1m30s" alike, and says plainly when it accepts neither.
func (d *Duration) UnmarshalJSON(raw []byte) error {
	var text string
	if err := json.Unmarshal(raw, &text); err != nil {
		return fmt.Errorf("expected a duration such as \"10m\", got %s", raw)
	}
	parsed, err := time.ParseDuration(text)
	if err != nil {
		return fmt.Errorf("%q is not a duration such as \"10m\": %w", text, err)
	}
	*d = Duration(parsed)
	return nil
}
