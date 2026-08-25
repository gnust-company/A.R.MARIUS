package main

import (
	"bytes"
	"context"
	"path/filepath"
	"strings"
	"testing"
)

// dispatch runs the command line and hands back what a person would have seen on each stream.
func dispatch(t *testing.T, args ...string) (stdout, stderr string, err error) {
	t.Helper()
	var out, errOut bytes.Buffer
	err = run(context.Background(), args, &out, &errOut)
	return out.String(), errOut.String(), err
}

func TestHelpListsEverySubcommand(t *testing.T) {
	stdout, _, err := dispatch(t, "help")
	if err != nil {
		t.Fatalf("help returned an error: %v", err)
	}
	// The help text is generated from the command table, so this also proves no command can be
	// added to the table and left undocumented.
	for _, c := range commands {
		if !strings.Contains(stdout, c.name) {
			t.Errorf("help does not mention the %q command", c.name)
		}
		if !strings.Contains(stdout, c.summary) {
			t.Errorf("help does not describe the %q command", c.name)
		}
	}
}

func TestVersionPrintsTheBuildStamp(t *testing.T) {
	stdout, _, err := dispatch(t, "version")
	if err != nil {
		t.Fatalf("version returned an error: %v", err)
	}
	if !strings.Contains(stdout, version) {
		t.Errorf("version output %q does not contain the version %q", stdout, version)
	}
}

func TestNoSubcommandIsRefusedAndExplained(t *testing.T) {
	stdout, stderr, err := dispatch(t)
	if err == nil {
		t.Fatal("an empty command line was accepted")
	}
	if stdout != "" {
		t.Errorf("usage went to stdout on failure: %q", stdout)
	}
	if !strings.Contains(stderr, "Usage:") {
		t.Errorf("the operator was not shown how to use the program: %q", stderr)
	}
}

func TestUnknownSubcommandNamesWhatWasNotUnderstood(t *testing.T) {
	_, _, err := dispatch(t, "shutdown")
	if err == nil {
		t.Fatal("an unknown subcommand was accepted")
	}
	if !strings.Contains(err.Error(), "shutdown") {
		t.Errorf("the error does not say which word was not understood: %v", err)
	}
}

// Every declared subcommand must be reachable. A command sitting in the table that dispatch
// cannot reach would show up in help and then do nothing at all.
func TestEverySubcommandIsReachable(t *testing.T) {
	for _, c := range commands {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := dispatch(t, c.name, "-h")
			if err != nil {
				t.Fatalf("-h on %q returned an error: %v", c.name, err)
			}
		})
	}
}

// Asking a subcommand for help is a request, not a mistake: it must succeed and describe the
// flags, so an operator can find out what to pass before passing anything.
func TestSubcommandHelpDescribesItsFlags(t *testing.T) {
	stdout, _, err := dispatch(t, "login", "-h")
	if err != nil {
		t.Fatalf("login -h returned an error: %v", err)
	}
	if !strings.Contains(stdout, "-server") {
		t.Errorf("login -h does not mention the -server flag: %q", stdout)
	}
}

func TestLoginRefusesToRunWithoutAServer(t *testing.T) {
	_, _, err := dispatch(t, "login")
	if err == nil {
		t.Fatal("login ran without being told which server to link to")
	}
	if !strings.Contains(err.Error(), "-server") {
		t.Errorf("the error does not name the missing flag: %v", err)
	}
}

// Until the real behaviour lands, a subcommand must fail rather than exit cleanly. A supervisor
// running `armarius-daemon start` has to learn that the daemon did not come up.
func TestUnbuiltSubcommandsFailLoudly(t *testing.T) {
	cases := [][]string{
		{"status"},
	}
	for _, args := range cases {
		t.Run(args[0], func(t *testing.T) {
			_, _, err := dispatch(t, args...)
			if err == nil {
				t.Fatalf("%v reported success while doing nothing", args)
			}
			if !strings.Contains(err.Error(), "tasks.md") {
				t.Errorf("the error does not say where the missing work is tracked: %v", err)
			}
		})
	}
}

// `start` is built as far as registering this machine and beating (T033–T038). Pointed at a
// config file that holds no token, it must refuse there rather than at the door: proof that it
// got past the not-built-yet notice and into the work.
func TestStartRefusesAMachineThatWasNeverLinked(t *testing.T) {
	_, _, err := dispatch(t, "start", "-config", filepath.Join(t.TempDir(), "daemon.json"))
	if err == nil {
		t.Fatal("start reported success on a machine with no token")
	}
	if strings.Contains(err.Error(), "tasks.md") {
		t.Errorf("start still answers with the not-built-yet notice: %v", err)
	}
	if !strings.Contains(err.Error(), "login") {
		t.Errorf("the error does not tell the operator to link the machine first: %v", err)
	}
}

// `login` is built (T030), so it must no longer answer with the not-built-yet notice. Given a
// server that does not resolve it has to fail on the call itself — proof that it got as far as
// trying, rather than stopping at the door.
func TestLoginActuallyGoesAndTalksToTheServer(t *testing.T) {
	_, _, err := dispatch(t, "login", "-server", "https://armarius.invalid", "-config", filepath.Join(t.TempDir(), "daemon.json"))
	if err == nil {
		t.Fatal("login reported success against a server that does not exist")
	}
	if strings.Contains(err.Error(), "tasks.md") {
		t.Errorf("login still reports itself as unbuilt: %v", err)
	}
	if !strings.Contains(err.Error(), "/daemon/link/start") {
		t.Errorf("login failed somewhere other than the call it exists to make: %v", err)
	}
}

func TestDefaultConfigPathIsUnderTheArmariusDirectory(t *testing.T) {
	got := defaultConfigPath()
	if !strings.Contains(got, ".armarius") || !strings.HasSuffix(got, "daemon.json") {
		t.Errorf("default config path %q is not ~/.armarius/daemon.json", got)
	}
}
