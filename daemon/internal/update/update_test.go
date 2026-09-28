package update

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// ── số hiệu phiên bản ──────────────────────────────────────────────────────────────

func TestOnlyATaggedReleaseUpdatesItself(t *testing.T) {
	for version, want := range map[string]bool{
		"0.1.0": true, "v0.1.0": true, "1.12.3": true,
		"dev": false, "": false, "0.1": false, "v0.2.15-235-gdaf0e935": false, "0.1.0-rc1": false,
	} {
		if got := IsRelease(version); got != want {
			t.Errorf("IsRelease(%q) = %v, mong %v", version, got, want)
		}
	}
}

func TestNewerComparesAllThreeNumbers(t *testing.T) {
	cases := []struct {
		latest, current string
		want            bool
	}{
		{"v0.2.0", "0.1.9", true},
		{"v0.10.0", "0.9.0", true},
		{"v0.1.0", "0.1.0", false},
		{"v0.1.0", "0.2.0", false},
		{"v0.2.0", "dev", false},
		{"not-a-tag", "0.1.0", false},
	}
	for _, c := range cases {
		if got := Newer(c.latest, c.current); got != c.want {
			t.Errorf("Newer(%q, %q) = %v, mong %v", c.latest, c.current, got, c.want)
		}
	}
}

func TestTheVersionIsReadOutOfWhatTheProgramPrints(t *testing.T) {
	printed := "armarius-daemon 0.2.0 (commit abc1234, built 2026-09-28T07:00:00Z)\n"
	if got := VersionIn(printed); got != "0.2.0" {
		t.Fatalf("đọc ra %q", got)
	}
	if got := VersionIn("something else entirely\n"); got == "0.2.0" || got == "" {
		t.Fatalf("một câu lạ phải đọc thành chính nó, để so khác đi: %q", got)
	}
}

// ── nơi phát hành ──────────────────────────────────────────────────────────────────

// aRelease is a releases page serving one release, the way GitHub lays it out.
type aRelease struct {
	tag      string
	files    map[string][]byte
	noLatest bool
}

func (r aRelease) serve(t *testing.T) string {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/releases/latest", func(w http.ResponseWriter, req *http.Request) {
		if r.noLatest {
			http.Redirect(w, req, "/releases", http.StatusFound)
			return
		}
		http.Redirect(w, req, "/releases/tag/"+r.tag, http.StatusFound)
	})
	mux.HandleFunc("/releases/download/", func(w http.ResponseWriter, req *http.Request) {
		name := strings.TrimPrefix(req.URL.Path, "/releases/download/"+r.tag+"/")
		body, ok := r.files[name]
		if !ok {
			http.NotFound(w, req)
			return
		}
		_, _ = w.Write(body)
	})
	server := httptest.NewServer(mux)
	t.Cleanup(server.Close)
	return server.URL + "/releases"
}

func TestTheLatestTagIsReadOffTheRedirect(t *testing.T) {
	base := aRelease{tag: "v0.2.0"}.serve(t)
	tag, err := Releases{Base: base}.Latest(context.Background())
	if err != nil {
		t.Fatalf("hỏi bản mới nhất: %v", err)
	}
	if tag != "v0.2.0" {
		t.Fatalf("tag là %q", tag)
	}
}

func TestNoReleaseYetIsSaidRatherThanReadAsAVersion(t *testing.T) {
	base := aRelease{noLatest: true}.serve(t)
	if tag, err := (Releases{Base: base}).Latest(context.Background()); err == nil {
		t.Fatalf("chưa có bản phát hành nào mà vẫn đọc ra tag %q", tag)
	}
}

// ── đặt một bản phát hành vào chỗ ─────────────────────────────────────────────────

func tarGz(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	for name, body := range files {
		if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o755, Size: int64(len(body)), Typeflag: tar.TypeReg}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write([]byte(body)); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func sumOf(body []byte) string {
	sum := sha256.Sum256(body)
	return hex.EncodeToString(sum[:])
}

// anInstall is a directory holding the programs of an older release.
func anInstall(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	for _, name := range []string{DaemonProgram, CallbackProgram} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("old "+name), 0o755); err != nil { //nolint:gosec // a test's own scratch program
			t.Fatal(err)
		}
	}
	return dir
}

func contentOf(t *testing.T, path string) string {
	t.Helper()
	body, err := os.ReadFile(path) //nolint:gosec // a path this test made
	if err != nil {
		t.Fatal(err)
	}
	return string(body)
}

func leftovers(t *testing.T, dir string) []string {
	t.Helper()
	found, _ := filepath.Glob(filepath.Join(dir, "*.new"))
	return found
}

func releaseWith(t *testing.T, programs map[string]string, sums func(archive string, body []byte) string) (string, Target) {
	t.Helper()
	archive := ArchiveName("v0.2.0", "linux", "amd64")
	body := tarGz(t, programs)
	checksums := sums(archive, body)
	base := aRelease{tag: "v0.2.0", files: map[string][]byte{
		archive: body, "checksums.txt": []byte(checksums),
	}}.serve(t)
	return base, Target{Dir: anInstall(t), GOOS: "linux", GOARCH: "amd64"}
}

func honest(archive string, body []byte) string {
	return "0000000000000000000000000000000000000000000000000000000000000000  armarius-daemon_0.2.0_darwin_arm64.tar.gz\n" +
		sumOf(body) + "  " + archive + "\n"
}

// FR-008n, FR-008i: cả hai chương trình vào chỗ, bản kiểm đúng checksum.
func TestAVerifiedReleasePutsBothProgramsInPlace(t *testing.T) {
	base, to := releaseWith(t, map[string]string{
		DaemonProgram: "new daemon", CallbackProgram: "new callback", "README.md": "readme",
	}, honest)

	if err := Install(context.Background(), Releases{Base: base}, "v0.2.0", to); err != nil {
		t.Fatalf("cài bản mới: %v", err)
	}
	if got := contentOf(t, filepath.Join(to.Dir, DaemonProgram)); got != "new daemon" {
		t.Errorf("daemon là %q", got)
	}
	if got := contentOf(t, filepath.Join(to.Dir, CallbackProgram)); got != "new callback" {
		t.Errorf("chương trình gọi ngược là %q", got)
	}
	if left := leftovers(t, to.Dir); len(left) != 0 {
		t.Errorf("còn sót tệp tạm: %v", left)
	}
	if _, err := os.Stat(filepath.Join(to.Dir, "README.md")); err == nil {
		t.Error("giải nén cả thứ không phải chương trình vào thư mục cài")
	}
}

// Kiểm hoặc từ chối, không có đường thứ ba: sai checksum thì không một byte nào được ghi.
func TestAChecksumMismatchChangesNothing(t *testing.T) {
	base, to := releaseWith(t, map[string]string{DaemonProgram: "tampered", CallbackProgram: "tampered"},
		func(archive string, _ []byte) string {
			return sumOf([]byte("what was published")) + "  " + archive + "\n"
		})

	if err := Install(context.Background(), Releases{Base: base}, "v0.2.0", to); err == nil {
		t.Fatal("sai checksum mà vẫn cài")
	}
	assertUntouched(t, to.Dir)
}

func TestAnArchiveListedNowhereInTheChecksumsChangesNothing(t *testing.T) {
	base, to := releaseWith(t, map[string]string{DaemonProgram: "new", CallbackProgram: "new"},
		func(string, []byte) string { return sumOf([]byte("x")) + "  something-else.tar.gz\n" })

	if err := Install(context.Background(), Releases{Base: base}, "v0.2.0", to); err == nil {
		t.Fatal("checksums.txt không nhắc tới archive mà vẫn cài")
	}
	assertUntouched(t, to.Dir)
}

// Hai chương trình là một khối: thiếu một thì không cài cái nào.
func TestAnArchiveMissingTheCallbackProgramChangesNothing(t *testing.T) {
	base, to := releaseWith(t, map[string]string{DaemonProgram: "new daemon"}, honest)

	if err := Install(context.Background(), Releases{Base: base}, "v0.2.0", to); err == nil {
		t.Fatal("archive thiếu chương trình gọi ngược mà vẫn cài")
	}
	assertUntouched(t, to.Dir)
}

func assertUntouched(t *testing.T, dir string) {
	t.Helper()
	for _, name := range []string{DaemonProgram, CallbackProgram} {
		if got := contentOf(t, filepath.Join(dir, name)); got != "old "+name {
			t.Errorf("%s bị đổi thành %q", name, got)
		}
	}
	if left := leftovers(t, dir); len(left) != 0 {
		t.Errorf("còn sót tệp tạm: %v", left)
	}
}

// ── vòng kiểm ─────────────────────────────────────────────────────────────────────

// aLoop records what the loop did, with every seam scripted and every tick due at once — twice,
// then never, so a loop that does nothing still ends when the test cancels it.
type aLoop struct {
	mu         sync.Mutex
	idle       bool
	latest     string
	installed  []string
	installErr error
	onDisk     string
	restarts   int
	busied     int
	said       []string
	ticks      int
}

func (l *aLoop) options(version string) Options {
	return Options{
		Version:    version,
		Executable: "/opt/armarius/armarius-daemon",
		Pull:       true,
		Reload:     true,
		Idle: func() bool {
			l.mu.Lock()
			defer l.mu.Unlock()
			return l.idle
		},
		Busy: func() {
			l.mu.Lock()
			l.busied++
			l.mu.Unlock()
		},
		Restart: func() {
			l.mu.Lock()
			l.restarts++
			l.mu.Unlock()
		},
		Say: func(format string, _ ...any) {
			l.mu.Lock()
			l.said = append(l.said, format)
			l.mu.Unlock()
		},
		Latest: func(context.Context) (string, error) {
			if l.latest == "" {
				return "", errors.New("no answer")
			}
			return l.latest, nil
		},
		Install: func(_ context.Context, tag string) error {
			l.mu.Lock()
			defer l.mu.Unlock()
			l.installed = append(l.installed, tag)
			return l.installErr
		},
		OnDisk: func(context.Context) (string, error) {
			if l.onDisk == "" {
				return version, nil
			}
			return l.onDisk, nil
		},
		Tick: func(time.Duration) <-chan time.Time {
			l.mu.Lock()
			defer l.mu.Unlock()
			l.ticks++
			if l.ticks > 4 {
				return nil
			}
			due := make(chan time.Time, 1)
			due <- time.Now()
			return due
		},
	}
}

func (l *aLoop) run(t *testing.T, opts Options) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		Run(ctx, opts)
	}()
	select {
	case <-done:
	case <-time.After(300 * time.Millisecond):
		cancel()
		<-done
	}
	cancel()
}

func TestANewerReleaseIsInstalledAndRestartedIntoWhenIdle(t *testing.T) {
	l := &aLoop{idle: true, latest: "v0.2.0"}
	l.run(t, l.options("0.1.0"))

	if len(l.installed) != 1 || l.installed[0] != "v0.2.0" {
		t.Fatalf("đã cài %v, mong đúng v0.2.0 một lần", l.installed)
	}
	if l.restarts != 1 {
		t.Fatalf("khởi động lại %d lần, mong 1", l.restarts)
	}
}

// FR-034, FR-008n: đang bận thì không cài, không khởi động lại — hoãn sang nhịp sau.
func TestABusyMachineDefersTheUpdate(t *testing.T) {
	l := &aLoop{idle: false, latest: "v0.2.0"}
	l.run(t, l.options("0.1.0"))

	if len(l.installed) != 0 || l.restarts != 0 {
		t.Fatalf("máy bận mà vẫn cài %v, khởi động lại %d lần", l.installed, l.restarts)
	}
}

// Cài hỏng thì mở lại cổng xin việc và không khởi động lại — daemon không được dừng vì một lần
// tải hỏng.
func TestAFailedInstallResumesWorkAndDoesNotRestart(t *testing.T) {
	l := &aLoop{idle: true, latest: "v0.2.0", installErr: errors.New("checksum mismatch")}
	l.run(t, l.options("0.1.0"))

	if l.restarts != 0 {
		t.Fatal("cài hỏng mà vẫn khởi động lại")
	}
	if l.busied == 0 {
		t.Fatal("cài hỏng mà cổng xin việc không được mở lại — máy sẽ không nhận việc nữa")
	}
}

func TestNothingNewerMeansNothingHappens(t *testing.T) {
	l := &aLoop{idle: true, latest: "v0.1.0"}
	l.run(t, l.options("0.1.0"))
	if len(l.installed) != 0 || l.restarts != 0 {
		t.Fatalf("không có gì mới mà vẫn cài %v, khởi động lại %d lần", l.installed, l.restarts)
	}
}

// Bản dựng từ nguồn không tự cập nhật — nâng nó lên bản phát hành là xoá thứ đang được thử.
func TestABuildFromSourceIsNeverPulledOverButStillReloads(t *testing.T) {
	l := &aLoop{idle: true, latest: "v9.9.9"}
	l.run(t, l.options("dev"))
	if len(l.installed) != 0 {
		t.Fatalf("bản dựng từ nguồn bị cài đè bằng %v", l.installed)
	}
}

// Người vận hành chạy lại lệnh cài: file trên đĩa là bản khác thì khởi động lại vào nó.
func TestAProgramReplacedOnDiskIsRestartedIntoWhenIdle(t *testing.T) {
	l := &aLoop{idle: true, onDisk: "0.3.0"}
	opts := l.options("0.2.0")
	opts.Pull = false
	l.run(t, opts)
	if l.restarts != 1 {
		t.Fatalf("file trên đĩa đã là 0.3.0 mà khởi động lại %d lần", l.restarts)
	}
}

func TestAProgramReplacedOnDiskWaitsForAnIdleMachine(t *testing.T) {
	l := &aLoop{idle: false, onDisk: "0.3.0"}
	opts := l.options("0.2.0")
	opts.Pull = false
	l.run(t, opts)
	if l.restarts != 0 {
		t.Fatal("máy đang bận mà vẫn khởi động lại")
	}
}

func TestBothRoadsOffMeansTheLoopEndsAtOnce(t *testing.T) {
	l := &aLoop{idle: true, latest: "v0.2.0", onDisk: "0.3.0"}
	opts := l.options("0.1.0")
	opts.Pull, opts.Reload = false, false
	l.run(t, opts)
	if len(l.installed) != 0 || l.restarts != 0 {
		t.Fatal("cả hai đường tắt mà vẫn làm gì đó")
	}
}
