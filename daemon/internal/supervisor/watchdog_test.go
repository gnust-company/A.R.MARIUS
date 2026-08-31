package supervisor

import (
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

func newTestWatchdog(t *testing.T, base time.Duration, perCLI map[string]time.Duration) *Watchdog {
	t.Helper()
	w, err := NewWatchdog(base, perCLI)
	if err != nil {
		t.Fatalf("NewWatchdog returned an error: %v", err)
	}
	return w
}

func TestTheBaseThresholdIsTenMinutes(t *testing.T) {
	if DefaultSilenceThreshold != 10*time.Minute {
		t.Errorf("DefaultSilenceThreshold = %s, want 10m", DefaultSilenceThreshold)
	}
}

func TestACLIWithNoEntryOfItsOwnGetsTheBase(t *testing.T) {
	w := newTestWatchdog(t, DefaultSilenceThreshold, map[string]time.Duration{
		"codex": 3 * time.Minute,
	})
	if got := w.Threshold("gemini"); got != DefaultSilenceThreshold {
		t.Errorf("threshold for an unconfigured CLI = %s, want the base %s", got, DefaultSilenceThreshold)
	}
}

func TestACLIMayTightenTheBase(t *testing.T) {
	w := newTestWatchdog(t, 10*time.Minute, map[string]time.Duration{"codex": 3 * time.Minute})
	if got := w.Threshold("codex"); got != 3*time.Minute {
		t.Errorf("threshold for codex = %s, want 3m", got)
	}
	if len(w.Loosened()) != 0 {
		t.Errorf("tightening was reported as loosening: %v", w.Loosened())
	}
}

// FR-031a: one CLI's configuration must not switch off the net that covers every CLI.
func TestACLIMayNotLoosenTheBaseAndIsToldSo(t *testing.T) {
	w := newTestWatchdog(t, 10*time.Minute, map[string]time.Duration{"hermes": time.Hour})

	if got := w.Threshold("hermes"); got != 10*time.Minute {
		t.Errorf("threshold for hermes = %s, want it pulled back to the base 10m", got)
	}

	loosened := w.Loosened()
	if len(loosened) != 1 {
		t.Fatalf("the adjustment was made silently: %v", loosened)
	}
	if loosened[0].CLI != "hermes" || loosened[0].Asked != time.Hour || loosened[0].Enforced != 10*time.Minute {
		t.Errorf("the adjustment was recorded wrongly: %+v", loosened[0])
	}
	if msg := loosened[0].String(); !strings.Contains(msg, "hermes") || !strings.Contains(msg, "1h0m0s") {
		t.Errorf("the message does not say what was asked for: %q", msg)
	}
}

// The same configuration has to produce the same report every time, or nobody trusts the log.
func TestAdjustmentsAreReportedInAStableOrder(t *testing.T) {
	perCLI := map[string]time.Duration{
		"codex":  time.Hour,
		"claude": time.Hour,
		"gemini": time.Hour,
	}
	want := []string{"claude", "codex", "gemini"}
	for range 20 {
		w := newTestWatchdog(t, time.Minute, perCLI)
		got := w.Loosened()
		if len(got) != len(want) {
			t.Fatalf("got %d adjustments, want %d", len(got), len(want))
		}
		for i := range want {
			if got[i].CLI != want[i] {
				t.Fatalf("adjustments came back as %v, want %v", got, want)
			}
		}
	}
}

func TestSilencePastTheThresholdIsAStall(t *testing.T) {
	w := newTestWatchdog(t, 10*time.Minute, nil)
	now := time.Now()

	cases := []struct {
		name   string
		silent time.Duration
		want   bool
	}{
		{"just started talking", time.Second, false},
		{"quiet a while but within reach", 9*time.Minute + 59*time.Second, false},
		{"exactly at the number the operator wrote", 10 * time.Minute, true},
		{"long past it", time.Hour, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := w.Stalled("gemini", now.Add(-c.silent), now); got != c.want {
				t.Errorf("after %s of silence, Stalled = %v, want %v", c.silent, got, c.want)
			}
		})
	}
}

// FR-031: what is forbidden is going quiet, not taking a long time. An agent narrating a six-hour
// build is working, and nothing here may cut it off.
func TestALongRunThatKeepsTalkingIsNeverStalled(t *testing.T) {
	w := newTestWatchdog(t, 10*time.Minute, nil)
	now := time.Now()

	for _, age := range []time.Duration{time.Hour, 6 * time.Hour, 72 * time.Hour} {
		// The run began `age` ago; it said something one second ago.
		if w.Stalled("claude", now.Add(-time.Second), now) {
			t.Errorf("a run %s old that spoke a second ago was called stalled", age)
		}
	}
}

func TestAThresholdOfZeroIsRefused(t *testing.T) {
	if _, err := NewWatchdog(0, nil); err == nil {
		t.Fatal("a base threshold of zero was accepted")
	}
	if _, err := NewWatchdog(-time.Minute, nil); err == nil {
		t.Fatal("a negative base threshold was accepted")
	}
	_, err := NewWatchdog(10*time.Minute, map[string]time.Duration{"codex": 0})
	if err == nil {
		t.Fatal("a per-CLI threshold of zero was accepted")
	}
	if !strings.Contains(err.Error(), "codex") {
		t.Errorf("the error does not name the offending CLI: %v", err)
	}
}

// FR-031a from the other side: the clamp above proves a loose threshold is pulled back, and this
// proves the table it is applied to has nothing to pull.
//
// Both are wanted. The clamp is what keeps a future entry honest; this is what says the entries
// there today are, and it fails loudly if somebody adds one that would run under a rule the
// operator does not think is in force — a run cut later than the machine's own threshold is a
// run nobody is watching for exactly as long as the difference.
func TestNoCLIInTheRegistryAsksForMoreRoomThanTheBaseAllows(t *testing.T) {
	w, err := NewWatchdog(DefaultSilenceThreshold, agentcli.Silences())
	if err != nil {
		t.Fatalf("the registry's own thresholds do not build a watchdog: %v", err)
	}
	if pulled := w.Loosened(); len(pulled) != 0 {
		t.Errorf("the registry declares thresholds that had to be pulled back: %v", pulled)
	}
	for cli, threshold := range agentcli.Silences() {
		if threshold > DefaultSilenceThreshold {
			t.Errorf("%s asks for %s, which is more room than the base %s",
				cli, threshold, DefaultSilenceThreshold)
		}
		if got := w.Threshold(cli); got != threshold {
			t.Errorf("%s declares %s and the watchdog enforces %s", cli, threshold, got)
		}
	}
}

// A kind the registry declares no threshold of its own for runs on the machine's, which is what
// every kind does today. Stated so that "the table is empty" and "the table is not read" stay
// two different things.
func TestACLIWithNoThresholdOfItsOwnRunsOnTheMachines(t *testing.T) {
	w, err := NewWatchdog(DefaultSilenceThreshold, agentcli.Silences())
	if err != nil {
		t.Fatalf("NewWatchdog returned an error: %v", err)
	}
	for _, row := range agentcli.All() {
		if row.Silence > 0 {
			continue
		}
		if got := w.Threshold(string(row.Kind)); got != DefaultSilenceThreshold {
			t.Errorf("%s declares no threshold and is cut at %s, want the base %s",
				row.Kind, got, DefaultSilenceThreshold)
		}
	}
}
