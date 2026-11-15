package execenv

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// kimiOperator lays out the operator's own Kimi Code home the way 2.5.3 keeps it, as far as a
// run borrows from it — plus two of the things a run must **not** reach.
func kimiOperator(t *testing.T, operatorHome string) string {
	t.Helper()
	theirs := filepath.Join(operatorHome, ".kimi-code")
	for _, dir := range []string{"credentials", "oauth", "sessions", "cache"} {
		if err := os.MkdirAll(filepath.Join(theirs, dir), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	for name, content := range map[string]string{
		"config.toml":                      "default_model = \"kimi-code/k3\"\n",
		"device_id":                        "a-device",
		"session_index.jsonl":              "{\"sessionId\":\"theirs\"}\n",
		"credentials/kimi-code-env-0.json": "{\"refresh_token\":\"spent-once-used\"}\n",
		"oauth/kimi-code-env-0":            "",
	} {
		if err := os.WriteFile(filepath.Join(theirs, name), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return theirs
}

// The measurement behind Kimi's row, kept as a test (FR-039g, FR-007s).
//
// Kimi renews its sign-in the way Claude Code does — a new file staged beside the name and
// renamed over it (`FileTokenStorage.save` in the 2.5.3 binary: `<name>.json.tmp.<pid>.<rand>`,
// fsync, rename). Over a linked *file* that rename replaces the link and the renewal is lost
// with the run's home. Kimi's row links the *directory* instead, and this is the property that
// buys: the same write, made inside the run's home, is the operator's own file afterwards.
func TestASignInKimiRenewsInsideARunIsTheOperatorsOwnAfterwards(t *testing.T) {
	spec := buildSpec(t, string(agentcli.Kimi))
	theirs := kimiOperator(t, spec.OperatorHome)
	if _, err := Build(spec); err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}

	// Exactly the CLI's write, addressed the way the CLI addresses it: through the run's home.
	inRun := filepath.Join(spec.Home, ".kimi-code", "credentials", "kimi-code-env-0.json")
	staged := inRun + ".tmp.4242.9f3a1c0e"
	if err := os.WriteFile(staged, []byte("{\"refresh_token\":\"renewed\"}\n"), 0o600); err != nil {
		t.Fatalf("staging the renewal: %v", err)
	}
	if err := os.Rename(staged, inRun); err != nil {
		t.Fatalf("renaming the renewal over the name: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(theirs, "credentials", "kimi-code-env-0.json"))
	if err != nil || string(got) != "{\"refresh_token\":\"renewed\"}\n" {
		t.Fatalf("the operator's own sign-in is %q (%v): the renewal stayed in the run's home, "+
			"and theirs now holds a token that was spent", got, err)
	}
	if info, err := os.Lstat(filepath.Join(spec.Home, ".kimi-code", "credentials")); err != nil ||
		info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("the credentials directory in the run's home is no longer a link (%v)", err)
	}

	// And so there is nothing for the carry-back to do, on this row.
	carried, err := CarryBack(string(agentcli.Kimi), spec.Home, spec.OperatorHome)
	if err != nil || len(carried) != 0 {
		t.Fatalf("carried %v (%v); the renewal was already in the operator's own", carried, err)
	}
}

// The lock two Kimi processes take before renewing has to be the same lock for a run and for
// the operator's own terminal, or both renew with one token and one of them is refused.
func TestKimisRenewalLockIsSharedWithTheOperatorsOwn(t *testing.T) {
	spec := buildSpec(t, string(agentcli.Kimi))
	theirs := kimiOperator(t, spec.OperatorHome)
	if _, err := Build(spec); err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}

	// proper-lockfile takes a lock by making `<name>.lock` beside the name.
	if err := os.Mkdir(filepath.Join(spec.Home, ".kimi-code", "oauth", "kimi-code-env-0.lock"), 0o700); err != nil {
		t.Fatalf("taking the lock from inside the run: %v", err)
	}
	if _, err := os.Stat(filepath.Join(theirs, "oauth", "kimi-code-env-0.lock")); err != nil {
		t.Fatalf("the lock taken in the run is not visible in the operator's own: %v", err)
	}
}

// What a run writes about its own sessions stays out of the operator's installation. Kimi
// appends to `session_index.jsonl` and keeps a search database under `cache/`; linked, both
// would come to describe sessions the operator never had (seen while measuring, 2026-11-15).
func TestAKimiRunWritesNothingAboutItselfIntoTheOperatorsOwn(t *testing.T) {
	spec := buildSpec(t, string(agentcli.Kimi))
	theirs := kimiOperator(t, spec.OperatorHome)
	built, err := Build(spec)
	if err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}

	ours := filepath.Join(spec.Home, ".kimi-code")
	for _, name := range []string{"session_index.jsonl", "cache"} {
		if _, err := os.Lstat(filepath.Join(ours, name)); !os.IsNotExist(err) {
			t.Errorf("%s is in the run's home before the CLI has run (%v): it reaches the operator's", name, err)
		}
	}

	// The conversation goes to the task's store, not to the operator's `sessions`.
	target, err := os.Readlink(filepath.Join(ours, "sessions"))
	if err != nil {
		t.Fatalf("the session directory is not a link: %v", err)
	}
	if len(built.Stores) != 1 || target != built.Stores[0] {
		t.Fatalf("sessions link to %s, and the stores this home reached are %v", target, built.Stores)
	}
	if filepath.Dir(target) == theirs {
		t.Fatal("a run's conversation would be written into the operator's own sessions")
	}
}

// An operator who has never signed in to Kimi has nothing to link, and that is not a failure
// to build: the CLI says *authentication required* far better than a missing file would.
func TestAKimiHomeIsBuiltForAnOperatorWhoNeverSignedIn(t *testing.T) {
	spec := buildSpec(t, string(agentcli.Kimi))
	if _, err := Build(spec); err != nil {
		t.Fatalf("Build returned an error: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(spec.Home, ".kimi-code", "credentials")); !os.IsNotExist(err) {
		t.Errorf("a credentials link was made to something that is not there (%v)", err)
	}
	if _, err := os.Stat(filepath.Join(spec.Home, ".kimi-code", "sessions")); err != nil {
		t.Errorf("the session store is not there: %v", err)
	}
}

// The run is pointed at its own home twice over, so a `KIMI_CODE_HOME` the daemon itself was
// started with cannot send it back to the operator's real directory.
func TestKimiIsPointedAtItsOwnHomeEvenWhenTheDaemonInheritedAnother(t *testing.T) {
	env, err := Environ(EnvSpec{
		CLI: string(agentcli.Kimi), Home: "/work/task-1/home",
		Inherited:   []string{"PATH=/usr/bin", "KIMI_CODE_HOME=/home/operator/.kimi-code", "HOME=/home/operator"},
		Credentials: Credentials{RunID: "run-1", RunToken: "run-token", Server: "http://armarius"},
	})
	if err != nil {
		t.Fatalf("Environ returned an error: %v", err)
	}

	seen := map[string][]string{}
	for _, entry := range env {
		for _, name := range []string{"HOME", "KIMI_CODE_HOME"} {
			if len(entry) > len(name) && entry[:len(name)+1] == name+"=" {
				seen[name] = append(seen[name], entry[len(name)+1:])
			}
		}
	}
	if got := seen["HOME"]; len(got) != 1 || got[0] != "/work/task-1/home" {
		t.Errorf("HOME = %v", got)
	}
	if got := seen["KIMI_CODE_HOME"]; len(got) != 1 || got[0] != filepath.FromSlash("/work/task-1/home/.kimi-code") {
		t.Errorf("KIMI_CODE_HOME = %v", got)
	}
}
