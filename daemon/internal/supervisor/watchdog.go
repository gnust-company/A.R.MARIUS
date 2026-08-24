// Package supervisor holds the loops that keep this machine's side of a run honest.
package supervisor

import (
	"fmt"
	"sort"
	"time"
)

// DefaultSilenceThreshold is how long a run may say nothing before it is treated as hung.
//
// Ten minutes, measured from the last event the agent produced — never from when the run began.
// A run is not allowed to be too long; it is only not allowed to go quiet (FR-031). An agent that
// has been compiling and testing for six hours while narrating what it does is working, and
// nothing here may cut it off.
const DefaultSilenceThreshold = 10 * time.Minute

// Watchdog answers one question: has this run gone quiet for too long?
//
// Notice what it is never told — when the run started. The total-runtime limit FR-031 forbids
// cannot be added by accident later, because the information needed to impose one does not reach
// this type.
type Watchdog struct {
	base     time.Duration
	perCLI   map[string]time.Duration
	loosened []Loosened
}

// Loosened records a per-CLI threshold that asked for more room than the base allows and was
// pulled back to it. The caller is expected to say so out loud: an operator who set a number and
// silently did not get it will otherwise believe a safety net exists where none does.
type Loosened struct {
	CLI      string
	Asked    time.Duration
	Enforced time.Duration
}

func (l Loosened) String() string {
	return fmt.Sprintf(
		"silence threshold for %s: asked for %s, enforced %s (a CLI may tighten the base, never loosen it)",
		l.CLI, l.Asked, l.Enforced,
	)
}

// NewWatchdog builds a watchdog around a base threshold, with optional per-CLI overrides.
//
// An override that is stricter than the base is taken as given. An override that is more
// generous is clamped back to the base and recorded in Loosened: no CLI's configuration may
// switch off the safety net that covers every CLI (FR-031a). Clamping rather than refusing is
// deliberate — a wrong number in one CLI's entry must not take the whole machine offline, which
// would cost far more than the too-generous threshold it was trying to prevent.
func NewWatchdog(base time.Duration, perCLI map[string]time.Duration) (*Watchdog, error) {
	if base <= 0 {
		return nil, fmt.Errorf("base silence threshold must be greater than zero, got %s", base)
	}

	w := &Watchdog{base: base, perCLI: make(map[string]time.Duration, len(perCLI))}

	names := make([]string, 0, len(perCLI))
	for cli := range perCLI {
		names = append(names, cli)
	}
	// Sorted so that the same configuration always reports the same adjustments in the same
	// order — a log line that reshuffles itself between restarts is one nobody trusts.
	sort.Strings(names)

	for _, cli := range names {
		asked := perCLI[cli]
		if asked <= 0 {
			return nil, fmt.Errorf(
				"silence threshold for %s must be greater than zero, got %s", cli, asked,
			)
		}
		if asked > base {
			w.loosened = append(w.loosened, Loosened{CLI: cli, Asked: asked, Enforced: base})
			w.perCLI[cli] = base
			continue
		}
		w.perCLI[cli] = asked
	}
	return w, nil
}

// Threshold is how long the given CLI may stay silent. A CLI with no entry of its own gets the
// base, which is the point of having a base at all.
func (w *Watchdog) Threshold(cli string) time.Duration {
	if t, ok := w.perCLI[cli]; ok {
		return t
	}
	return w.base
}

// Loosened lists the per-CLI thresholds that were pulled back to the base.
func (w *Watchdog) Loosened() []Loosened { return w.loosened }

// Stalled reports whether a run has been silent past its threshold.
//
// lastEvent is when the agent last produced anything at all. Reaching the threshold counts as
// crossing it: a watchdog that waits for one more nanosecond past the number the operator wrote
// is a watchdog set to a number nobody chose.
func (w *Watchdog) Stalled(cli string, lastEvent, now time.Time) bool {
	return now.Sub(lastEvent) >= w.Threshold(cli)
}
