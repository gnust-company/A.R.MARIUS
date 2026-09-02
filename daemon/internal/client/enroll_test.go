package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/config"
)

// noWait replaces the pause between polls so the whole wait-for-approval loop runs at test
// speed. It still honours cancellation, which is the one behaviour of the real sleep that the
// tests below actually depend on.
func noWait(ctx context.Context, _ time.Duration) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return nil
}

// linkServer is a stand-in for the two endpoints login talks to. approveAfter says how many
// polls answer *pending* before the token is handed over.
func linkServer(t *testing.T, approveAfter int, expire bool) *httptest.Server {
	t.Helper()
	polls := 0
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/daemon/link/start":
			var body map[string]string
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Errorf("link/start received a body that is not JSON: %v", err)
			}
			if body["hostname"] == "" {
				t.Error("link/start received no hostname; the approval screen would have nothing to show")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"code": "KQ7F-M2XD", "verify_url": "https://armarius.example/link",
				"expires_in": 600, "interval": 5,
			})
		case "/daemon/link/poll":
			polls++
			if expire {
				w.WriteHeader(http.StatusGone)
				_ = json.NewEncoder(w).Encode(map[string]any{"status": "expired"})
				return
			}
			if polls <= approveAfter {
				w.WriteHeader(http.StatusAccepted)
				_ = json.NewEncoder(w).Encode(map[string]any{"status": "pending"})
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "approved", "machine_id": "m-1", "workspace_id": "w-1", "token": "armd_secret",
			})
		default:
			t.Errorf("login called an endpoint nobody built: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

func TestLoginPrintsTheCodeAndWaitsUntilSomeoneApproves(t *testing.T) {
	server := linkServer(t, 2, false)
	defer server.Close()

	var out bytes.Buffer
	path := filepath.Join(t.TempDir(), "daemon.json")
	creds, err := Login(context.Background(), LoginOptions{
		Server: server.URL, ConfigPath: path, Hostname: "gnust-thinkpad",
		Platform: runtime.GOOS, Version: "0.1.0", Out: &out, Sleep: noWait,
	})
	if err != nil {
		t.Fatalf("login failed: %v", err)
	}

	// The code and the address are the whole point of the printout: without both of them the
	// person has nowhere to go and nothing to type.
	for _, want := range []string{"KQ7F-M2XD", "https://armarius.example/link"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("login never told the operator %q; it printed:\n%s", want, out.String())
		}
	}
	if creds.Token != "armd_secret" || creds.MachineID != "m-1" || creds.WorkspaceID != "w-1" {
		t.Fatalf("login came back with the wrong credentials: %+v", creds)
	}
	if creds.Server != server.URL {
		t.Errorf("credentials point at %q, not at the server that issued them (%q)", creds.Server, server.URL)
	}
}

// The token is the one secret on this machine that speaks for the whole machine (FR-014c). A
// file another account on the same box can read is the failure this checks for.
func TestTheTokenLandsInAFileOnlyItsOwnerCanRead(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix file modes do not describe what Windows enforces")
	}
	server := linkServer(t, 0, false)
	defer server.Close()

	path := filepath.Join(t.TempDir(), "nested", "daemon.json")
	if _, err := Login(context.Background(), LoginOptions{
		Server: server.URL, ConfigPath: path, Hostname: "box", Sleep: noWait,
	}); err != nil {
		t.Fatalf("login failed: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("login reported success but wrote no file: %v", err)
	}
	if mode := info.Mode().Perm(); mode != 0o600 {
		t.Errorf("the machine token sits at mode %o; anything but 600 leaves it readable by other accounts", mode)
	}
}

// A file left readable by an earlier version, or by an operator's editor, is exactly the case
// worth tightening — writing to an existing file does not change its mode on its own.
func TestAnAlreadyLooseFileIsTightenedRatherThanTrusted(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix file modes do not describe what Windows enforces")
	}
	path := filepath.Join(t.TempDir(), "daemon.json")
	if err := os.WriteFile(path, []byte(`{}`), 0o644); err != nil {
		t.Fatalf("could not stage a world-readable file: %v", err)
	}
	if err := SaveCredentials(path, Credentials{Server: "https://s", Token: "armd_x"}); err != nil {
		t.Fatalf("saving credentials failed: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat failed: %v", err)
	}
	if mode := info.Mode().Perm(); mode != 0o600 {
		t.Errorf("a pre-existing file kept mode %o instead of being tightened to 600", mode)
	}
}

// The credentials and the operator's tuning knobs share one file. Login must not cost someone
// the settings they tuned, and `start` must still be able to read them back.
func TestLoggingInDoesNotWipeTheSettingsTheOperatorTuned(t *testing.T) {
	path := filepath.Join(t.TempDir(), "daemon.json")
	if err := os.WriteFile(path, []byte(`{"poll_interval":"30s","max_concurrent_runs":3}`), 0o600); err != nil {
		t.Fatalf("could not stage a tuned config: %v", err)
	}
	if err := SaveCredentials(path, Credentials{Server: "https://s", Token: "armd_x", MachineID: "m", WorkspaceID: "w"}); err != nil {
		t.Fatalf("saving credentials failed: %v", err)
	}

	tuned, err := config.Load(path)
	if err != nil {
		t.Fatalf("the config half of the file no longer loads: %v", err)
	}
	if got := tuned.PollInterval.Duration(); got != 30*time.Second {
		t.Errorf("poll_interval came back as %s, not the 30s the operator set", got)
	}
	if tuned.MaxConcurrentRuns != 3 {
		t.Errorf("max_concurrent_runs came back as %d, not the 3 the operator set", tuned.MaxConcurrentRuns)
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading the merged file failed: %v", err)
	}
	var merged map[string]any
	if err := json.Unmarshal(raw, &merged); err != nil {
		t.Fatalf("the merged file is not JSON: %v", err)
	}
	if merged["token"] != "armd_x" {
		t.Errorf("the token is missing from the merged file: %v", merged)
	}
}

// Nothing is wrong when a code expires — the person took too long. The daemon has to say that
// rather than report a transport failure, because the fix is simply to run login again.
func TestAnExpiredCodeIsReportedAsExpiryAndNotAsBreakage(t *testing.T) {
	server := linkServer(t, 0, true)
	defer server.Close()

	path := filepath.Join(t.TempDir(), "daemon.json")
	_, err := Login(context.Background(), LoginOptions{
		Server: server.URL, ConfigPath: path, Hostname: "box", Sleep: noWait,
	})
	if !errors.Is(err, ErrLinkExpired) {
		t.Fatalf("an expired code reported %v, not ErrLinkExpired", err)
	}
	if _, statErr := os.Stat(path); !errors.Is(statErr, os.ErrNotExist) {
		t.Error("a login that never got a token still wrote a credentials file")
	}
}

// Ctrl-C during the wait must not be mistaken for the code running out: the two lead a person
// to do completely different things next.
func TestGivingUpOnTheWaitIsNotTheSameAsTheCodeExpiring(t *testing.T) {
	server := linkServer(t, 1000, false)
	defer server.Close()

	// Cancelled at the first pause, not before the first call: the point is that giving up
	// *while waiting for a person* is reported as giving up, and the loop is the only place
	// that distinction can be got wrong.
	ctx, cancel := context.WithCancel(context.Background())
	_, err := Login(ctx, LoginOptions{
		Server: server.URL, ConfigPath: filepath.Join(t.TempDir(), "daemon.json"),
		Hostname: "box",
		Sleep: func(c context.Context, _ time.Duration) error {
			cancel()
			return c.Err()
		},
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("a cancelled login reported %v, not context.Canceled", err)
	}
}

// A server restart, or a lid closing on wifi, is a normal thing to live through while a person
// walks to a browser. Login must ride it out rather than throw the code away.
func TestATemporaryFailureWhileWaitingIsRiddenOutRatherThanFatal(t *testing.T) {
	polls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/daemon/link/start" {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"code": "KQ7F-M2XD", "verify_url": "https://armarius.example/link",
				"expires_in": 600, "interval": 5,
			})
			return
		}
		polls++
		// Two hiccups, then a person approves.
		if polls <= 2 {
			w.WriteHeader(http.StatusBadGateway)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "approved", "machine_id": "m-1", "workspace_id": "w-1", "token": "armd_secret",
		})
	}))
	defer server.Close()

	creds, err := Login(context.Background(), LoginOptions{
		Server: server.URL, ConfigPath: filepath.Join(t.TempDir(), "daemon.json"),
		Hostname: "box", Sleep: noWait,
	})
	if err != nil {
		t.Fatalf("two failed polls ended the whole login: %v", err)
	}
	if creds.Token != "armd_secret" {
		t.Errorf("login recovered but came back with %q", creds.Token)
	}
}

// …but a server that is simply gone must not be waited on forever. The code's own expiry
// cannot end that wait: a server answering nothing never answers 410 either.
func TestAServerThatNeverAnswersIsGivenUpOnRatherThanWaitedOnForever(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/daemon/link/start" {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"code": "KQ7F-M2XD", "verify_url": "https://armarius.example/link",
				"expires_in": 600, "interval": 5,
			})
			return
		}
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	done := make(chan error, 1)
	go func() {
		_, err := Login(context.Background(), LoginOptions{
			Server: server.URL, ConfigPath: filepath.Join(t.TempDir(), "daemon.json"),
			Hostname: "box", Sleep: noWait,
		})
		done <- err
	}()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("login reported success against a server that only ever failed")
		}
		if errors.Is(err, ErrLinkExpired) {
			t.Errorf("a dead server was reported as an expired code: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("login never gave up on a server that only ever failed")
	}
}

func TestLoginRefusesToStartWithoutSomewhereToGo(t *testing.T) {
	for _, tc := range []struct {
		name string
		opts LoginOptions
	}{
		{"no server", LoginOptions{ConfigPath: "/tmp/x.json"}},
		{"no config path", LoginOptions{Server: "https://armarius.example"}},
	} {
		if _, err := Login(context.Background(), tc.opts); err == nil {
			t.Errorf("%s: login went ahead anyway", tc.name)
		}
	}
}

// ── being told to ask less often (T126a) ─────────────────────────────────────
//
// The poll door has a pace limit on it now, and a machine that trips it is told 429. That is
// a refusal, not a failure, and the two are counted differently on this side: five failures in
// a row end the login, while a refusal is an instruction to wait. Reading them the same way
// would abandon a link that is still perfectly alive.

// slowDownServer answers 429 for the first `refusals` polls, then behaves normally.
func slowDownServer(t *testing.T, refusals int, seconds string) *httptest.Server {
	t.Helper()
	polls := 0
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/daemon/link/start":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"code": "KQ7F-M2XD", "verify_url": "https://armarius.example/link",
				"expires_in": 600, "interval": 5,
			})
		case "/daemon/link/poll":
			polls++
			if polls <= refusals {
				w.Header().Set("Retry-After", seconds)
				w.WriteHeader(http.StatusTooManyRequests)
				_ = json.NewEncoder(w).Encode(map[string]any{
					"detail": "Asking too often.",
					"code":   "daemon_link_polled_too_often",
					"params": map[string]string{"seconds": seconds},
				})
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "approved", "machine_id": "m-1", "workspace_id": "w-1", "token": "armd_secret",
			})
		default:
			t.Errorf("login called an endpoint nobody built: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

func TestBeingToldToAskLessOftenIsNotAFailedAttempt(t *testing.T) {
	// More refusals than maxPollFailures: if 429 were counted as a failure this login would
	// give up, which is exactly the regression the branch exists to prevent.
	server := slowDownServer(t, maxPollFailures+3, "30")
	defer server.Close()

	creds, err := Login(context.Background(), LoginOptions{
		Server: server.URL, ConfigPath: filepath.Join(t.TempDir(), "daemon.json"),
		Hostname: "box", Out: io.Discard, Sleep: noWait,
	})
	if err != nil {
		t.Fatalf("login gave up on a link that was still alive: %v", err)
	}
	if creds.Token != "armd_secret" {
		t.Fatalf("token = %q, want the one the server handed over", creds.Token)
	}
}

func TestTheWaitTheServerAsksForIsTheWaitTaken(t *testing.T) {
	server := slowDownServer(t, 1, "30")
	defer server.Close()

	var waits []time.Duration
	_, err := Login(context.Background(), LoginOptions{
		Server: server.URL, ConfigPath: filepath.Join(t.TempDir(), "daemon.json"),
		Hostname: "box", Out: io.Discard,
		Sleep: func(ctx context.Context, d time.Duration) error {
			waits = append(waits, d)
			return ctx.Err()
		},
	})
	if err != nil {
		t.Fatalf("login: %v", err)
	}
	// The first wait is the ordinary interval before the first poll; the second is the one the
	// refusal asked for.
	if len(waits) < 2 || waits[1] != 30*time.Second {
		t.Fatalf("waits = %v, want the second one to be the 30s the server asked for", waits)
	}
}

func TestAWaitThisMachineCannotReadFallsBackToTheInterval(t *testing.T) {
	// A number that is absent, malformed, or shorter than the pace already handed over must
	// never produce a tighter loop against a door that has just said it is being asked too
	// often.
	for _, asked := range []string{"", "soon", "-5", "1"} {
		server := slowDownServer(t, 1, asked)
		var waits []time.Duration
		_, err := Login(context.Background(), LoginOptions{
			Server: server.URL, ConfigPath: filepath.Join(t.TempDir(), "daemon.json"),
			Hostname: "box", Out: io.Discard,
			Sleep: func(ctx context.Context, d time.Duration) error {
				waits = append(waits, d)
				return ctx.Err()
			},
		})
		server.Close()
		if err != nil {
			t.Fatalf("seconds=%q: login: %v", asked, err)
		}
		if len(waits) < 2 || waits[1] != 5*time.Second {
			t.Fatalf("seconds=%q: waits = %v, want the 5s interval the server advertised", asked, waits)
		}
	}
}
