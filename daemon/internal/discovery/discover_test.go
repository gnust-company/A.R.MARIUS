package discovery

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// machine describes a machine that does not exist, so a test can say what is installed on it
// without installing anything.
type machine struct {
	installed map[string]string   // binary name -> path
	answers   map[string]string   // path -> what it prints
	failures  map[string]error    // path -> why it will not run
	asked     map[string][]string // path -> the arguments it was asked with
}

func (m *machine) options() Options {
	m.asked = map[string][]string{}
	return Options{
		LookPath: func(binary string) (string, error) {
			path, ok := m.installed[binary]
			if !ok {
				return "", fmt.Errorf("%s: not found in PATH", binary)
			}
			return path, nil
		},
		Run: func(_ context.Context, path string, args ...string) ([]byte, error) {
			m.asked[path] = args
			if err, broken := m.failures[path]; broken {
				return nil, err
			}
			return []byte(m.answers[path]), nil
		},
		Timeout: time.Second,
	}
}

func TestOnlyTheCLIsActuallyInstalledAreReported(t *testing.T) {
	m := &machine{
		installed: map[string]string{"claude": "/usr/bin/claude"},
		answers:   map[string]string{"/usr/bin/claude": "2.1.226 (Claude Code)\n"},
	}

	got := Discover(context.Background(), m.options())

	if len(got.Found) != 1 {
		t.Fatalf("want exactly the one installed CLI, got %+v", got.Found)
	}
	if got.Found[0].Kind != agentcli.ClaudeCode {
		t.Errorf("kind = %q, want %q", got.Found[0].Kind, agentcli.ClaudeCode)
	}
	if got.Found[0].Family != agentcli.FamilyOneShot {
		t.Errorf("family = %q, want %q", got.Found[0].Family, agentcli.FamilyOneShot)
	}
	if got.Found[0].Version != "2.1.226" {
		t.Errorf("version = %q, want the number out of the line it printed", got.Found[0].Version)
	}
	if len(got.Skipped) != 0 {
		t.Errorf("a CLI that is simply not installed is not news: %+v", got.Skipped)
	}
}

// A binary that is present but will not run must not become a workplace. Registering it would
// mean taking work and failing quietly, which is the case FR-033 exists to prevent — and it is
// not hypothetical: the development machine's codex is a launcher missing its platform binary.
func TestABinaryThatWillNotRunIsSkippedRatherThanOffered(t *testing.T) {
	m := &machine{
		installed: map[string]string{"codex": "/usr/local/bin/codex"},
		failures: map[string]error{
			"/usr/local/bin/codex": errors.New("exit status 1"),
		},
	}

	got := Discover(context.Background(), m.options())

	if len(got.Found) != 0 {
		t.Fatalf("a CLI that cannot print its own version cannot run a task: %+v", got.Found)
	}
	if len(got.Skipped) != 1 {
		t.Fatalf("want the broken CLI reported, got %+v", got.Skipped)
	}
	if got.Skipped[0].Kind != agentcli.Codex || got.Skipped[0].Reason != ReasonNotRunnable {
		t.Errorf("skipped = %+v, want codex/%s", got.Skipped[0], ReasonNotRunnable)
	}
	if got.Skipped[0].Err == nil {
		t.Error("the operator has to be told why their machine offers one workplace fewer")
	}
}

func TestTheVersionIsReadOutOfWhateverShapeTheCLIPrints(t *testing.T) {
	for _, tc := range []struct {
		printed string
		want    string
	}{
		{"0.56.0\n", "0.56.0"},
		{"2.1.226 (Claude Code)\n", "2.1.226"},
		{"codex-cli v1.2\n", "1.2"},
		{"  \n0.1.0-rc.4\n", "0.1.0"},
	} {
		m := &machine{
			installed: map[string]string{"gemini": "/usr/local/bin/gemini"},
			answers:   map[string]string{"/usr/local/bin/gemini": tc.printed},
		}
		got := Discover(context.Background(), m.options())
		if len(got.Found) != 1 || got.Found[0].Version != tc.want {
			t.Errorf("printing %q gave %+v, want version %q", tc.printed, got.Found, tc.want)
		}
	}
}

// A CLI whose version cannot be read still runs, and running is what a workplace needs. Hiding
// a working CLI over a cosmetic field would cost the operator a whole machine.
func TestACLIWithAnUnreadableVersionIsStillOffered(t *testing.T) {
	m := &machine{
		installed: map[string]string{"gemini": "/usr/local/bin/gemini"},
		answers:   map[string]string{"/usr/local/bin/gemini": "built from source\n"},
	}

	got := Discover(context.Background(), m.options())

	if len(got.Found) != 1 {
		t.Fatalf("want the CLI offered anyway, got %+v", got.Found)
	}
	if got.Found[0].Version != "" {
		t.Errorf("version = %q, want it left blank rather than invented", got.Found[0].Version)
	}
}

// The order candidates are declared in is the order they are reported in. Two heartbeats that
// disagree about the order of the same three workplaces would look like a machine whose CLIs
// keep changing.
func TestTheSweepReportsInAStableOrder(t *testing.T) {
	m := &machine{
		installed: map[string]string{
			"codex":  "/usr/local/bin/codex",
			"claude": "/usr/bin/claude",
			"gemini": "/usr/local/bin/gemini",
		},
		answers: map[string]string{
			"/usr/local/bin/codex":  "1.0.0",
			"/usr/bin/claude":       "2.1.226",
			"/usr/local/bin/gemini": "0.56.0",
		},
	}

	for range 5 {
		got := Discover(context.Background(), m.options())
		want := []Kind{agentcli.Gemini, agentcli.ClaudeCode, agentcli.Codex}
		if len(got.Found) != len(want) {
			t.Fatalf("found %+v, want all three", got.Found)
		}
		for i, kind := range want {
			if got.Found[i].Kind != kind {
				t.Fatalf("position %d = %q, want %q", i, got.Found[i].Kind, kind)
			}
		}
	}
}

// A CLI that hangs must not hold the sweep open. The machine still has other CLIs and the
// server is waiting to hear about them.
func TestAHungCLIDoesNotHoldUpTheSweep(t *testing.T) {
	opts := Options{
		LookPath: func(binary string) (string, error) {
			if binary == "claude" {
				return "/usr/bin/claude", nil
			}
			return "", errors.New("not found")
		},
		Run: func(ctx context.Context, _ string, _ ...string) ([]byte, error) {
			<-ctx.Done()
			return nil, ctx.Err()
		},
		Timeout: 20 * time.Millisecond,
	}

	done := make(chan Result, 1)
	go func() { done <- Discover(context.Background(), opts) }()

	select {
	case got := <-done:
		if len(got.Found) != 0 || len(got.Skipped) != 1 {
			t.Errorf("a CLI that never answers is a broken one: %+v", got)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("the sweep waited on a hung CLI instead of timing it out")
	}
}
