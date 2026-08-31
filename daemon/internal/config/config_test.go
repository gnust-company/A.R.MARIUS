package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The defaults are not arbitrary — each one is argued for in research.md §3 and §7. Pinning them
// here means a future edit that quietly changes one has to change this test too, and explain why.
func TestDefaultsAreTheNumbersTheResearchSettledOn(t *testing.T) {
	c := Defaults()
	for _, want := range []struct {
		name string
		got  any
		want any
	}{
		{"poll_interval", c.PollInterval.Duration(), 5 * time.Second},
		{"heartbeat_interval", c.HeartbeatInterval.Duration(), 15 * time.Second},
		{"claim_lease", c.ClaimLease.Duration(), 120 * time.Second},
		{"tool_result_inline_limit_bytes", c.ToolResultInlineLimit, 2048},
		{"max_concurrent_runs", c.MaxConcurrentRuns, 5},
		{"sweep_interval", c.SweepInterval.Duration(), 2 * time.Hour},
		{"work_dir_retention", c.WorkDirRetention.Duration(), 24 * time.Hour},
		{"session_retention", c.SessionRetention.Duration(), 14 * 24 * time.Hour},
		{"orphan_retention", c.OrphanRetention.Duration(), 72 * time.Hour},
	} {
		if want.got != want.want {
			t.Errorf("%s = %v, want %v", want.name, want.got, want.want)
		}
	}
	if err := c.Validate(); err != nil {
		t.Fatalf("the defaults do not pass their own validation: %v", err)
	}
}

// A machine that has been linked but never tuned is the ordinary case, not a broken one.
func TestAMissingFileLeavesTheDefaultsStanding(t *testing.T) {
	got, err := Load(filepath.Join(t.TempDir(), "there-is-no-such-file.json"))
	if err != nil {
		t.Fatalf("a missing config file was treated as a failure: %v", err)
	}
	if got != Defaults() {
		t.Errorf("got %+v, want the defaults %+v", got, Defaults())
	}
}

func writeConfig(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "daemon.json")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("could not write the test config: %v", err)
	}
	return path
}

// Naming one number must not reset any of the others.
func TestNamingOneNumberLeavesTheRestAlone(t *testing.T) {
	got, err := Load(writeConfig(t, `{"poll_interval": "30s"}`))
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if got.PollInterval.Duration() != 30*time.Second {
		t.Errorf("poll_interval = %s, want 30s", got.PollInterval)
	}
	want := Defaults()
	want.PollInterval = Duration(30 * time.Second)
	if got != want {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

// `login` writes its own half into the same file. This loader must walk past it rather than
// choke on it.
func TestTheCredentialsLoginWroteAreIgnoredNotRejected(t *testing.T) {
	got, err := Load(writeConfig(t, `{
		"server_url": "https://armarius.example.com",
		"token": "not-a-real-token",
		"machine_id": "abc123"
	}`))
	if err != nil {
		t.Fatalf("a config carrying login's fields was rejected: %v", err)
	}
	if got != Defaults() {
		t.Errorf("got %+v, want the defaults %+v", got, Defaults())
	}
}

func TestDurationsAreWrittenTheWayPeopleSayThem(t *testing.T) {
	got, err := Load(writeConfig(t, `{"claim_lease": "2m30s", "heartbeat_interval": "20s"}`))
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if got.ClaimLease.Duration() != 150*time.Second {
		t.Errorf("claim_lease = %s, want 2m30s", got.ClaimLease)
	}
	if got.HeartbeatInterval.Duration() != 20*time.Second {
		t.Errorf("heartbeat_interval = %s, want 20s", got.HeartbeatInterval)
	}
}

func TestSomethingThatIsNotADurationIsSaidSoPlainly(t *testing.T) {
	_, err := Load(writeConfig(t, `{"poll_interval": "soon"}`))
	if err == nil {
		t.Fatal("\"soon\" was accepted as a duration")
	}
	if !strings.Contains(err.Error(), "soon") {
		t.Errorf("the error does not quote what could not be read: %v", err)
	}
}

func TestANumberWhereADurationBelongsIsRefused(t *testing.T) {
	if _, err := Load(writeConfig(t, `{"poll_interval": 5}`)); err == nil {
		t.Fatal("a bare number was accepted where a duration belongs")
	}
}

// The one rule that spans two numbers: a lease shorter than the wake budget takes work back from
// a machine that is preparing it correctly (FR-056c).
func TestALeaseShorterThanTheWakeBudgetIsRefused(t *testing.T) {
	for _, lease := range []string{"1s", "14s", "15s"} {
		t.Run(lease, func(t *testing.T) {
			_, err := Load(writeConfig(t, `{"claim_lease": "`+lease+`"}`))
			if err == nil {
				t.Fatalf("a claim_lease of %s was accepted", lease)
			}
			if !strings.Contains(err.Error(), "claim_lease") {
				t.Errorf("the error does not name the offending setting: %v", err)
			}
		})
	}
}

func TestALeaseLongerThanTheWakeBudgetIsAccepted(t *testing.T) {
	got, err := Load(writeConfig(t, `{"claim_lease": "16s"}`))
	if err != nil {
		t.Fatalf("a claim_lease of 16s was refused: %v", err)
	}
	if got.ClaimLease.Duration() != 16*time.Second {
		t.Errorf("claim_lease = %s, want 16s", got.ClaimLease)
	}
}

func TestSettingsThatWouldStopTheMachineWorkingAreRefused(t *testing.T) {
	for name, body := range map[string]string{
		"poll interval of zero":       `{"poll_interval": "0s"}`,
		"negative heartbeat":          `{"heartbeat_interval": "-5s"}`,
		"no room for any tool output": `{"tool_result_inline_limit_bytes": 0}`,
		"no room for any run":         `{"max_concurrent_runs": 0}`,
		"a sweep that never comes":    `{"sweep_interval": "0s"}`,
		"nothing kept at all":         `{"work_dir_retention": "0s"}`,
		"no conversation kept":        `{"session_retention": "0s"}`,
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := Load(writeConfig(t, body)); err == nil {
				t.Fatalf("%s was accepted", name)
			}
		})
	}
}

// A directory the server never mentioned is deleted on a guess; one it said was finished with
// is deleted on a statement. Letting the guess act sooner inverts which of the two this program
// trusts more, and it does so silently — the machine runs, and quietly reclaims the directories
// it knows least about first (FR-021a).
func TestGuessingIsNeverAllowedToActSoonerThanBeingTold(t *testing.T) {
	tighter := `{"work_dir_retention": "48h", "orphan_retention": "24h"}`
	if _, err := Load(writeConfig(t, tighter)); err == nil {
		t.Fatal("một hạn đoán ngắn hơn hạn được kể được nhận")
	}

	equal := `{"work_dir_retention": "24h", "orphan_retention": "24h"}`
	if _, err := Load(writeConfig(t, equal)); err == nil {
		t.Fatal("hai hạn bằng nhau được nhận — ca đoán phải dài hơn hẳn")
	}

	longer := `{"work_dir_retention": "24h", "orphan_retention": "72h"}`
	if _, err := Load(writeConfig(t, longer)); err != nil {
		t.Fatalf("một cặp hạn hợp lệ bị từ chối: %v", err)
	}
}

// What is written out has to read back as the same thing, or a machine that saves its own config
// loses the settings it was given.
func TestWritingTheConfigBackOutReadsAsTheSameConfig(t *testing.T) {
	raw, err := json.Marshal(Defaults())
	if err != nil {
		t.Fatalf("could not write the config out: %v", err)
	}
	got, err := Load(writeConfig(t, string(raw)))
	if err != nil {
		t.Fatalf("could not read the config back: %v", err)
	}
	if got != Defaults() {
		t.Errorf("round trip changed the config: got %+v, want %+v", got, Defaults())
	}
}

func TestUnreadableJSONNamesTheFile(t *testing.T) {
	path := writeConfig(t, `{this is not json`)
	_, err := Load(path)
	if err == nil {
		t.Fatal("a broken config file was accepted")
	}
	if !strings.Contains(err.Error(), path) {
		t.Errorf("the error does not say which file could not be read: %v", err)
	}
}
