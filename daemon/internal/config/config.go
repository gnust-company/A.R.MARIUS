// Package config holds the numbers an operator is allowed to turn on their own machine.
//
// They are gathered here rather than scattered through the code because some of them are not
// independent, and a rule between two numbers can only be enforced where both numbers live:
//
//   - the lease the server grants when this machine claims a run has to outlast the whole
//     wake-to-running budget, or the system takes work back from a machine that is doing
//     everything right (FR-056c);
//   - a directory the server cannot account for has to be kept longer than one it said was
//     finished with, because the first is a guess and the second is a statement (FR-021a).
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

	"github.com/gnust-company/armarius-daemon/internal/execenv"
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

	// DrainPatience is how long a stopping daemon lets the runs it already holds finish before
	// it cuts them (FR-034). Stopping the daemon always stops it *asking* for work at once;
	// this number is only about the work it had already taken.
	//
	// The default is written out here and again as supervisor.DefaultDrainPatience, the same way
	// the heartbeat interval is, because neither package can be made to run without a number and
	// neither may import the other. The two are held together by a test in the one place that
	// sees both — cmd/armarius-daemon.
	//
	// It is paired with whatever the service manager on this machine allows a stop to take —
	// systemd's `TimeoutStopSec`, 90 seconds by default — and raising one without the other
	// buys nothing: past that limit the process is destroyed mid-drain, which cuts the run
	// anyway and additionally leaves the machine looking as though it crashed.
	DrainPatience Duration `json:"drain_patience"`

	// SweepInterval is how often this machine looks over what it has left on its own disk
	// (FR-021). Nothing is removed before its retention has passed, so this decides how *late*
	// a reclaim can be, never whether one happens.
	SweepInterval Duration `json:"sweep_interval"`

	// WorkDirRetention is how long a task's working directory survives after the server said
	// that task was finished with and nothing more happened to it (FR-021).
	WorkDirRetention Duration `json:"work_dir_retention"`

	// SessionRetention is how long a conversation may sit idle and still be carried on
	// (FR-027). It is asked twice — by the sweep, and again at each wake, because the sweep
	// does not run while the machine is off (FR-027a).
	SessionRetention Duration `json:"session_retention"`

	// OrphanRetention is how long a working directory the server cannot account for survives
	// (FR-021a). Longer than WorkDirRetention on purpose, and the difference is not caution
	// for its own sake: that clock acts on something the server stated, this one acts on the
	// absence of a statement, and an absence is the weaker evidence of the two.
	OrphanRetention Duration `json:"orphan_retention"`
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
		DrainPatience:         Duration(60 * time.Second),
		SweepInterval:         Duration(execenv.DefaultSweepInterval),
		WorkDirRetention:      Duration(execenv.DefaultWorkDirRetention),
		SessionRetention:      Duration(execenv.DefaultSessionRetention),
		OrphanRetention:       Duration(execenv.DefaultOrphanRetention),
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
		{"drain_patience", c.DrainPatience.Duration()},
		{"sweep_interval", c.SweepInterval.Duration()},
		{"work_dir_retention", c.WorkDirRetention.Duration()},
		{"session_retention", c.SessionRetention.Duration()},
		{"orphan_retention", c.OrphanRetention.Duration()},
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

	// The second rule that spans two numbers. A directory the server never mentioned is
	// deleted on a guess; one it said was finished with is deleted on a statement. Letting the
	// guess act sooner than the statement inverts which of the two this program trusts more
	// (FR-021a).
	if c.OrphanRetention.Duration() <= c.WorkDirRetention.Duration() {
		return fmt.Errorf(
			"orphan_retention must be longer than work_dir_retention (%s), got %s",
			c.WorkDirRetention, c.OrphanRetention,
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
