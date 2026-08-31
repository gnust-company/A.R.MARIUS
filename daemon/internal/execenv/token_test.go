package execenv

import (
	"path/filepath"
	"strings"
	"testing"
)

const daemonToken = "daemon-token-speaks-for-the-whole-machine"

func lookup(env []string, name string) (string, bool) {
	for _, entry := range env {
		if got, value, ok := strings.Cut(entry, "="); ok && got == name {
			return value, true
		}
	}
	return "", false
}

func aRunsEnvironment(t *testing.T, spec EnvSpec) []string {
	t.Helper()
	if spec.CLI == "" {
		spec.CLI = "claude_code"
	}
	if spec.Home == "" {
		spec.Home = t.TempDir()
	}
	if spec.Credentials.RunToken == "" {
		spec.Credentials.RunToken = "run-token"
	}
	env, err := Environ(spec)
	if err != nil {
		t.Fatalf("dựng biến môi trường: %v", err)
	}
	return env
}

func TestTheRunGetsATokenOfItsOwn(t *testing.T) {
	env := aRunsEnvironment(t, EnvSpec{Credentials: Credentials{
		RunID:    "run-1",
		RunToken: "only-this-run",
		Server:   "https://armarius.example",
	}})

	for name, want := range map[string]string{
		RunTokenVar: "only-this-run",
		RunIDVar:    "run-1",
		ServerVar:   "https://armarius.example",
	} {
		if got, ok := lookup(env, name); !ok || got != want {
			t.Fatalf("%s là %q (có: %v), mong %q", name, got, ok, want)
		}
	}
}

func TestAMintThatFailedStopsTheRunRatherThanSubstituting(t *testing.T) {
	// FR-014c. Minting is the server's job and it can fail; when it does the run goes back on
	// the shelf. Running with something else that happens to be lying around is the failure
	// Multica only wrote the rule about after falling into it.
	_, err := Environ(EnvSpec{
		CLI:         "claude_code",
		Home:        t.TempDir(),
		Credentials: Credentials{DaemonToken: daemonToken},
	})
	if err == nil {
		t.Fatal("không có token của lượt chạy mà vẫn dựng được môi trường để chạy")
	}
}

func TestTheMachinesOwnTokenIsNeverHandedOverAsTheRunsOwn(t *testing.T) {
	_, err := Environ(EnvSpec{
		CLI:  "claude_code",
		Home: t.TempDir(),
		Credentials: Credentials{
			RunToken:    daemonToken,
			DaemonToken: daemonToken,
		},
	})
	if err == nil {
		t.Fatal("token của cả cái máy được trao cho agent như thể là token của một lượt chạy")
	}
}

func TestTheMachinesOwnTokenIsScrubbedOutOfWhatIsInherited(t *testing.T) {
	// Refusing to *add* it is the easy half. An operator who exported their token to run a
	// one-off command has one in their environment, and the child inherits it without a single
	// line of this code being wrong.
	env := aRunsEnvironment(t, EnvSpec{
		Inherited: []string{
			"PATH=/usr/bin",
			"ARMARIUS_TOKEN=" + daemonToken,
			"SOMETHING_ELSE=prefix-" + daemonToken + "-suffix",
		},
		Credentials: Credentials{RunToken: "only-this-run", DaemonToken: daemonToken},
	})

	for _, entry := range env {
		if strings.Contains(entry, daemonToken) {
			t.Fatalf("token của máy đi theo agent qua %q", entry)
		}
	}
	if _, ok := lookup(env, "PATH"); !ok {
		t.Fatal("dọn token xong thì dọn luôn cả PATH")
	}
}

func TestAStaleRunTokenInTheDaemonsOwnEnvironmentIsNotInherited(t *testing.T) {
	// The value that would be hardest to notice: everything downstream still finds a token
	// where it expected one.
	env := aRunsEnvironment(t, EnvSpec{
		Inherited:   []string{RunTokenVar + "=belongs-to-another-run"},
		Credentials: Credentials{RunToken: "only-this-run"},
	})

	got, ok := lookup(env, RunTokenVar)
	if !ok || got != "only-this-run" {
		t.Fatalf("token của lượt chạy là %q (có: %v)", got, ok)
	}
	if count := strings.Count(strings.Join(env, "\n"), RunTokenVar+"="); count != 1 {
		t.Fatalf("%s xuất hiện %d lần", RunTokenVar, count)
	}
}

func TestTheCLIIsPointedAtTheHomeBuiltForThisRun(t *testing.T) {
	home := t.TempDir()
	env := aRunsEnvironment(t, EnvSpec{
		CLI:       "claude_code",
		Home:      home,
		Inherited: []string{"HOME=/home/the-operator"},
	})

	if got, _ := lookup(env, "HOME"); got != home {
		t.Fatalf("agent vẫn đọc nhà thật của người dùng: HOME=%s", got)
	}
}

func TestCodexIsToldWhereItsOwnHomeIs(t *testing.T) {
	// Codex keeps authentication, configuration and session state under one directory of its
	// own and reads CODEX_HOME to find it (research §11.1).
	home := t.TempDir()
	env := aRunsEnvironment(t, EnvSpec{CLI: "codex", Home: home})

	if got, _ := lookup(env, "CODEX_HOME"); got != filepath.Join(home, ".codex") {
		t.Fatalf("CODEX_HOME=%s, mong %s", got, filepath.Join(home, ".codex"))
	}
	if got, _ := lookup(env, "HOME"); got != home {
		t.Fatalf("HOME=%s, mong %s", got, home)
	}
}

func TestACLIWhoseHomeVariablesAreUnknownIsRefused(t *testing.T) {
	// Starting a CLI without redirecting its home means it reads the operator's own, and
	// everything Build lays out is laid out beside the point — so a kind the registry declares
	// no home variables for is refused rather than started.
	_, err := Environ(EnvSpec{
		CLI:         "opencode",
		Home:        t.TempDir(),
		Credentials: Credentials{RunToken: "only-this-run"},
	})
	if err == nil {
		t.Fatal("CLI chưa khai biến nhà mà vẫn dựng được môi trường")
	}
}

func TestAnAddressNobodyGaveIsLeftOutRatherThanSetEmpty(t *testing.T) {
	// A variable set to nothing is worse than an absent one: code that checks for presence
	// finds it, and code that checks for a value does not.
	env := aRunsEnvironment(t, EnvSpec{Credentials: Credentials{RunToken: "only-this-run"}})

	if got, ok := lookup(env, ServerVar); ok {
		t.Fatalf("%s được đặt thành %q dù không ai nói địa chỉ", ServerVar, got)
	}
}

// A CLI that needs more than a home pointer gets it, and gets it the same way: placed by this
// function, so an inherited value of the same name loses. Gemini will not read project-level
// configuration out of a folder nobody trusted, and the daemon makes a new folder per task.
func TestWhatACLINeedsSetBeyondItsHomeIsSet(t *testing.T) {
	env, err := Environ(EnvSpec{
		CLI:         "gemini",
		Home:        t.TempDir(),
		Inherited:   []string{"GEMINI_CLI_TRUST_WORKSPACE=false"},
		Credentials: Credentials{RunToken: "only-this-run"},
	})
	if err != nil {
		t.Fatalf("Environ trả về lỗi: %v", err)
	}
	got, set := lookup(env, "GEMINI_CLI_TRUST_WORKSPACE")
	if !set {
		t.Fatal("thư mục làm việc của lượt chạy không được khai là tin cậy, nên bản tóm tắt sẽ không ai đọc")
	}
	if got != "true" {
		t.Errorf("GEMINI_CLI_TRUST_WORKSPACE=%q — giá trị thừa hưởng sẵn trên máy đã thắng", got)
	}
}

// And a CLI that declares none gets none. A variable meant for one tool arriving in another's
// environment is how a setting nobody chose starts applying.
func TestACLIThatDeclaresNoExtraVariablesGetsNone(t *testing.T) {
	env, err := Environ(EnvSpec{
		CLI:         "claude_code",
		Home:        t.TempDir(),
		Credentials: Credentials{RunToken: "only-this-run"},
	})
	if err != nil {
		t.Fatalf("Environ trả về lỗi: %v", err)
	}
	if _, set := lookup(env, "GEMINI_CLI_TRUST_WORKSPACE"); set {
		t.Error("biến của một CLI khác lọt vào môi trường")
	}
}
