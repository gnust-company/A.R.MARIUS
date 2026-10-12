package client

// Chạy `login` trên một máy đã được nối (FR-001e, issue #285).
//
// Ngày 2026-10-12 người chủ chạy `login` lần hai trên một máy đang chạy daemon, lần này duyệt bằng một tài
// khoản khác. Không có câu nào báo trước: token mới đè lên file, daemon đang chạy vẫn dùng token cũ, máy mới
// không bao giờ beat, agent ở workspace mới offline, và `status` ghép thông tin của máy mới với nhịp beat
// của máy cũ. Các bài dưới đây giữ ba điều: báo rồi mới hỏi, không đồng ý thì không đổi gì, và `status`
// không trộn hai nguồn.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// relinkServer approves at the first poll and counts how many codes it was asked for: a refused
// or declined login must not have asked for one, because asking creates nothing yet but approving
// creates a machine, and the person has no reason to see a page they said no to.
func relinkServer(t *testing.T) (*httptest.Server, *int) {
	t.Helper()
	starts := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/daemon/link/start":
			starts++
			_ = json.NewEncoder(w).Encode(map[string]any{
				"code": "KQ7F-M2XD", "verify_url": "https://armarius.example/link?code=KQ7F-M2XD",
				"expires_in": 600, "interval": 5,
			})
		case "/daemon/link/poll":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "approved", "machine_id": "m-new", "workspace_id": "ws-new", "token": "armd_new",
			})
		default:
			t.Errorf("login called an endpoint nobody built: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(server.Close)
	return server, &starts
}

// alreadyLinked is a machine that went through `login` once, to workspace ws-old.
func alreadyLinked(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "daemon.json")
	if err := SaveCredentials(path, Credentials{
		Server: "https://old.example", Token: "armd_old", MachineID: "m-old", WorkspaceID: "ws-old",
	}); err != nil {
		t.Fatal(err)
	}
	return path
}

func loginOn(path, server string, out *bytes.Buffer) LoginOptions {
	return LoginOptions{
		Server: server, ConfigPath: path, Hostname: "gnust-thinkpad",
		Platform: runtime.GOOS, Version: "0.2.0", Out: out, Sleep: noWait,
		Alive: func(int) bool { return false },
	}
}

func readFile(t *testing.T, path string) []byte {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestALinkedMachineIsToldWhatLoggingInAgainReplacesThenAsked(t *testing.T) {
	server, _ := relinkServer(t)
	path := alreadyLinked(t)
	var out bytes.Buffer
	var asked []string
	opts := loginOn(path, server.URL, &out)
	opts.Confirm = func(question string) (bool, error) {
		// Câu hỏi phải tới SAU lời báo: hỏi trước rồi mới nói là hỏi một người chưa biết mình đồng ý cái gì.
		if !strings.Contains(out.String(), "ws-old") {
			t.Errorf("asked before saying what would be replaced; printed so far:\n%s", out.String())
		}
		asked = append(asked, question)
		return true, nil
	}

	creds, err := Login(context.Background(), opts)
	if err != nil {
		t.Fatalf("login failed after the person agreed: %v", err)
	}
	if len(asked) != 1 {
		t.Fatalf("asked %d times, want once", len(asked))
	}
	for _, want := range []string{"https://old.example", "ws-old", "m-old", path} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("không nói rõ kết nối nào sẽ bị thay — thiếu %q:\n%s", want, out.String())
		}
	}
	if !strings.Contains(out.String(), "Machines screen") {
		t.Errorf("không nói máy cũ vẫn nằm lại trong workspace cũ:\n%s", out.String())
	}
	if creds.Token != "armd_new" || !strings.Contains(string(readFile(t, path)), "armd_new") {
		t.Errorf("đồng ý rồi mà kết nối mới không được ghi: %+v", creds)
	}
}

func TestSayingNoChangesNothingAndAsksTheServerForNothing(t *testing.T) {
	server, starts := relinkServer(t)
	path := alreadyLinked(t)
	before := readFile(t, path)
	var out bytes.Buffer
	opts := loginOn(path, server.URL, &out)
	opts.Confirm = func(string) (bool, error) { return false, nil }

	_, err := Login(context.Background(), opts)
	if !errors.Is(err, ErrLoginDeclined) {
		t.Fatalf("saying no came back as %v, want ErrLoginDeclined", err)
	}
	if *starts != 0 {
		t.Errorf("người ta đã nói không mà vẫn xin mã nối máy %d lần", *starts)
	}
	if !bytes.Equal(before, readFile(t, path)) {
		t.Error("người ta đã nói không mà file cấu hình vẫn bị đổi")
	}
}

func TestWithNobodyToAskALinkedMachineIsRefusedAndToldHow(t *testing.T) {
	server, starts := relinkServer(t)
	path := alreadyLinked(t)
	before := readFile(t, path)
	var out bytes.Buffer

	_, err := Login(context.Background(), loginOn(path, server.URL, &out)) // no Confirm, no Yes
	if err == nil || errors.Is(err, ErrLoginDeclined) {
		t.Fatalf("không có ai để hỏi mà login không từ chối: %v", err)
	}
	if !strings.Contains(err.Error(), "-yes") {
		t.Errorf("lời từ chối không nói cách đồng ý trước: %v", err)
	}
	if *starts != 0 || !bytes.Equal(before, readFile(t, path)) {
		t.Errorf("bị từ chối mà vẫn đổi gì đó: %d mã được xin, file đổi = %v",
			*starts, !bytes.Equal(before, readFile(t, path)))
	}
}

func TestAgreeingInAdvanceIsNotAskedButIsStillTold(t *testing.T) {
	server, _ := relinkServer(t)
	path := alreadyLinked(t)
	var out bytes.Buffer
	opts := loginOn(path, server.URL, &out)
	opts.Yes = true
	opts.Confirm = func(string) (bool, error) {
		t.Error("asked a person who had already agreed with -yes")
		return false, nil
	}

	if _, err := Login(context.Background(), opts); err != nil {
		t.Fatalf("login with -yes failed: %v", err)
	}
	if !strings.Contains(out.String(), "ws-old") {
		t.Errorf("đồng ý trước vẫn phải được báo là thay kết nối nào:\n%s", out.String())
	}
}

func TestAMachineNeverLinkedIsAskedNothing(t *testing.T) {
	server, _ := relinkServer(t)
	path := filepath.Join(t.TempDir(), "daemon.json")
	var out bytes.Buffer
	opts := loginOn(path, server.URL, &out)
	opts.Confirm = func(string) (bool, error) {
		t.Error("asked about replacing a link on a machine that never had one")
		return false, nil
	}

	if _, err := Login(context.Background(), opts); err != nil {
		t.Fatalf("a first login failed: %v", err)
	}
}

func TestASettingsOnlyConfigIsNotALink(t *testing.T) {
	// Người vận hành chỉnh vài núm trước khi nối máy lần đầu: chưa có token thì chưa có gì để thay.
	server, _ := relinkServer(t)
	path := filepath.Join(t.TempDir(), "daemon.json")
	if err := os.WriteFile(path, []byte(`{"max_concurrent_runs": 2}`), 0o600); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	opts := loginOn(path, server.URL, &out)
	opts.Confirm = func(string) (bool, error) {
		t.Error("asked about replacing a link that was never made")
		return false, nil
	}

	if _, err := Login(context.Background(), opts); err != nil {
		t.Fatalf("login failed: %v", err)
	}
}

func TestAConfigThatCannotBeReadStopsLoginBeforeAnyCodeIsAsked(t *testing.T) {
	// Trước đây lỗi này chỉ lộ ra lúc ghi, tức SAU khi người ta đã duyệt và server đã tạo máy.
	server, starts := relinkServer(t)
	path := filepath.Join(t.TempDir(), "daemon.json")
	if err := os.WriteFile(path, []byte("{not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer

	if _, err := Login(context.Background(), loginOn(path, server.URL, &out)); err == nil {
		t.Fatal("login went ahead on a config file it cannot read")
	}
	if *starts != 0 {
		t.Errorf("xin mã nối máy dù biết trước là không ghi được token: %d lần", *starts)
	}
}

func TestADaemonRunningOnTheOldLinkIsNamedAndTheLastLineSaysRestartIt(t *testing.T) {
	server, _ := relinkServer(t)
	path := alreadyLinked(t)
	if err := SaveState(StatePath(path), RunState{
		PID: 4242, StartedAt: time.Now(), MachineID: "m-old", WorkspaceID: "ws-old",
		Server:     "https://old.example",
		Workplaces: []RegisteredWorkplace{{ID: "wp-1", CLIKind: "claude_code", Ready: true, MachineName: "gnust-thinkpad"}},
	}); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	opts := loginOn(path, server.URL, &out)
	opts.Alive = func(pid int) bool { return pid == 4242 }
	opts.Confirm = func(string) (bool, error) { return true, nil }

	if _, err := Login(context.Background(), opts); err != nil {
		t.Fatalf("login failed: %v", err)
	}
	said := out.String()
	for _, want := range []string{"4242", "keeps using", "gnust-thinkpad"} {
		if !strings.Contains(said, want) {
			t.Errorf("không nói daemon đang chạy vẫn dùng kết nối cũ — thiếu %q:\n%s", want, said)
		}
	}
	// Dòng cuối: `start` một mình sẽ bị từ chối vì đã có daemon chạy (FR-034a).
	last := said[strings.LastIndex(strings.TrimRight(said, "\n"), "\n")+1:]
	if !strings.Contains(last, "armarius-daemon stop") || !strings.Contains(last, "armarius-daemon start") {
		t.Errorf("dòng cuối không bảo dừng rồi chạy lại daemon: %q", last)
	}
}

// ── `status` không được trộn hai nguồn ──────────────────────────────────────────────────────────

func TestStatusSaysWhenTheDaemonRunsOnALinkTheConfigNoLongerHolds(t *testing.T) {
	config := linkedConfig(t) // m-1 in ws-1
	save(t, config, RunState{
		PID: 4242, StartedAt: time.Now(), LastBeatOKAt: time.Now(),
		Server: "https://armarius.example", MachineID: "m-old", WorkspaceID: "ws-old",
	})

	got, err := Report(context.Background(), aMachineWith(config, nil, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}
	if !got.Relinked || got.RunningMachineID != "m-old" || got.RunningWorkspaceID != "ws-old" {
		t.Fatalf("status did not notice the daemon runs on another link: %+v", got)
	}
	var text bytes.Buffer
	got.WriteText(&text, time.Now())
	for _, want := range []string{"m-old", "ws-old", "armarius-daemon stop"} {
		if !strings.Contains(text.String(), want) {
			t.Errorf("status vẫn ghép máy mới với nhịp beat của máy cũ — thiếu %q:\n%s", want, text.String())
		}
	}
}

func TestStatusOfADaemonOnTheSameLinkSaysNothingMore(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{
		PID: 4242, StartedAt: time.Now(),
		Server: "https://armarius.example", MachineID: "m-1", WorkspaceID: "ws-1",
	})

	got, err := Report(context.Background(), aMachineWith(config, nil, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}
	if got.Relinked {
		t.Errorf("a daemon on the very link in the config was reported as relinked: %+v", got)
	}
}

func TestStatusOfADaemonThatNeverRecordedItsLinkClaimsNothing(t *testing.T) {
	// Daemon `v0.2.0` không ghi kết nối của nó. Không biết thì không đoán.
	config := linkedConfig(t)
	save(t, config, RunState{PID: 4242, StartedAt: time.Now()})

	got, err := Report(context.Background(), aMachineWith(config, nil, map[int]bool{4242: true}))
	if err != nil {
		t.Fatal(err)
	}
	if got.Relinked {
		t.Errorf("guessed a relink from a state file that never said which link it ran on: %+v", got)
	}
}

func TestTheStateFileStillNeverHoldsTheToken(t *testing.T) {
	config := linkedConfig(t)
	save(t, config, RunState{PID: 1, StartedAt: time.Now(), Server: "https://armarius.example", MachineID: "m-1", WorkspaceID: "ws-1"})
	if strings.Contains(string(readFile(t, StatePath(config))), "armd_") {
		t.Fatal("ghi kết nối vào file trạng thái đã kéo theo cả token")
	}
}
