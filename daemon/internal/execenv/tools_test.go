package execenv_test

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// aCallbackProgram lays down something real to hand a run, and answers where it is.
func aCallbackProgram(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "armarius")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nexit 0\n"), 0o700); err != nil {
		t.Fatalf("laying down a callback program: %v", err)
	}
	return path
}

func TestTheAgentCanCallTheCallbackProgramByItsBareName(t *testing.T) {
	// The whole of FR-013a's command face, end to end and across the seam it actually crosses:
	// the daemon places a program and builds an environment, and the agent — which knows only
	// the name it was taught — resolves that name the way its shell will.
	//
	// Neither half proves this alone. Placing a program somewhere nothing looks, and putting a
	// directory on a path with nothing in it, both pass their own tests and leave the agent
	// running a command that does not exist.
	if runtime.GOOS == "windows" {
		t.Skip("path resolution is spelled differently here; the seam is the same one")
	}
	workDir := t.TempDir()
	program := aCallbackProgram(t)

	tools, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI: "claude_code", WorkDir: workDir, Program: program,
	})
	if err != nil {
		t.Fatalf("placing the callback program: %v", err)
	}

	env, err := execenv.Environ(execenv.EnvSpec{
		CLI:         "claude_code",
		Home:        filepath.Join(workDir, ".armarius", "home", "run-1"),
		WorkDir:     workDir,
		ToolsDir:    tools.Dir,
		Inherited:   []string{"PATH=/usr/bin:/bin"},
		Credentials: execenv.Credentials{RunToken: "armr_run_thisone"},
	})
	if err != nil {
		t.Fatalf("building the environment: %v", err)
	}

	path, found := valueOf(env, "PATH")
	if !found {
		t.Fatal("the agent was given no search path at all")
	}
	// Resolved through the operating system's own rule, with the agent's path and nothing else.
	t.Setenv("PATH", path)
	resolved, err := exec.LookPath(execenv.CallbackProgram)
	if err != nil {
		t.Fatalf("an agent typing %q finds nothing: %v", execenv.CallbackProgram, err)
	}
	if resolved != tools.Program {
		t.Fatalf("typing %q reaches %s, not the program this run was given at %s",
			execenv.CallbackProgram, resolved, tools.Program)
	}
}

func TestTheRunsOwnProgramWinsOverOneAlreadyOnThePath(t *testing.T) {
	// A machine we do not own may well have something called armarius on its path already — an
	// older install, a shim, a script somebody wrote. Ours has to be the one that answers, or a
	// run silently talks to a program nobody here placed.
	if runtime.GOOS == "windows" {
		t.Skip("path resolution is spelled differently here; the seam is the same one")
	}
	elsewhere := t.TempDir()
	other := filepath.Join(elsewhere, execenv.CallbackProgram)
	if err := os.WriteFile(other, []byte("#!/bin/sh\nexit 9\n"), 0o700); err != nil {
		t.Fatalf("laying down somebody else's copy: %v", err)
	}

	workDir := t.TempDir()
	tools, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI: "claude_code", WorkDir: workDir, Program: aCallbackProgram(t),
	})
	if err != nil {
		t.Fatalf("placing the callback program: %v", err)
	}
	env, err := execenv.Environ(execenv.EnvSpec{
		CLI:         "claude_code",
		Home:        filepath.Join(workDir, "home"),
		ToolsDir:    tools.Dir,
		Inherited:   []string{"PATH=" + elsewhere},
		Credentials: execenv.Credentials{RunToken: "armr_run_thisone"},
	})
	if err != nil {
		t.Fatalf("building the environment: %v", err)
	}

	path, _ := valueOf(env, "PATH")
	t.Setenv("PATH", path)
	resolved, err := exec.LookPath(execenv.CallbackProgram)
	if err != nil {
		t.Fatalf("nothing answers to %q: %v", execenv.CallbackProgram, err)
	}
	if resolved != tools.Program {
		t.Fatalf("the agent reaches %s, which is not this run's program at %s", resolved, tools.Program)
	}
	if !strings.Contains(path, elsewhere) {
		t.Fatalf("the machine's own path was thrown away rather than followed: %s", path)
	}
}

func TestARunWithNoCallbackProgramIsRefusedRatherThanStarted(t *testing.T) {
	// The failure this prevents is the quiet one. A run set up without the program still starts,
	// still produces events, and still ends — it simply cannot do anything the skill sheet told
	// it to, and every attempt dies inside the agent as *command not found*, where nothing on
	// either side of the wire can see it.
	workDir := t.TempDir()

	if _, err := execenv.PlaceTools(execenv.ToolsSpec{CLI: "claude_code", WorkDir: workDir}); err == nil {
		t.Fatal("a run with no callback program to hand was set up anyway")
	}
	missing := filepath.Join(t.TempDir(), "not-installed")
	if _, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI: "claude_code", WorkDir: workDir, Program: missing,
	}); err == nil {
		t.Fatal("a callback program that is not on disk was accepted")
	}
}

func TestTheToolDeclarationNamesThisRunsOwnProgram(t *testing.T) {
	workDir := t.TempDir()
	tools, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI: "claude_code", WorkDir: workDir, Program: aCallbackProgram(t),
	})
	if err != nil {
		t.Fatalf("placing the callback program: %v", err)
	}
	if tools.ConfigFile == "" {
		t.Fatal("claude_code loads tools and was declared none")
	}

	body, err := os.ReadFile(tools.ConfigFile)
	if err != nil {
		t.Fatalf("reading the declaration: %v", err)
	}
	var declared struct {
		Servers map[string]struct {
			Command string   `json:"command"`
			Args    []string `json:"args"`
		} `json:"mcpServers"`
	}
	if err := json.Unmarshal(body, &declared); err != nil {
		t.Fatalf("the declaration is not readable as the CLI reads it: %v", err)
	}
	server, named := declared.Servers[execenv.CallbackProgram]
	if !named {
		t.Fatalf("the declaration does not name %q: %s", execenv.CallbackProgram, body)
	}
	if server.Command != tools.Program {
		t.Fatalf("the declaration points at %s, not this run's own program at %s",
			server.Command, tools.Program)
	}
	if len(server.Args) != 1 || server.Args[0] != "mcp" {
		t.Fatalf("the declaration does not ask for the tool face: %v", server.Args)
	}

	// The same declaration, in the shape the family that carries it inline needs. One value,
	// two renderings — a second list would be a second answer to what this agent can do.
	if len(tools.Servers) != 1 || tools.Servers[0].Command != tools.Program {
		t.Fatalf("the inline form does not match the file: %+v", tools.Servers)
	}
}

func TestACLIThatLoadsNoToolsIsGivenNoDeclarationAndStillGetsTheCommand(t *testing.T) {
	// Codex is not in the table because its side is unmeasured, and Gemini because none of it
	// is. Neither is thereby left without a way to call back: the command face is the baseline,
	// and this is the test that says so.
	for _, cli := range []string{"codex", "gemini"} {
		workDir := t.TempDir()
		tools, err := execenv.PlaceTools(execenv.ToolsSpec{
			CLI: cli, WorkDir: workDir, Program: aCallbackProgram(t),
		})
		if err != nil {
			t.Fatalf("%s: placing the callback program: %v", cli, err)
		}
		if tools.ConfigFile != "" {
			t.Fatalf("%s: a declaration was written for a CLI whose loader is not known: %s",
				cli, tools.ConfigFile)
		}
		if _, err := os.Lstat(tools.Program); err != nil {
			t.Fatalf("%s: the command face was not placed: %v", cli, err)
		}
	}
}

func TestTheProgramIsRemadeSoAnUpgradedDaemonIsNotHandedOutTwice(t *testing.T) {
	// The working directory belongs to the task and outlives the run (FR-010), so what is in it
	// was put there by an earlier run — possibly by an earlier build of this daemon. A machine
	// upgraded mid-life must not keep handing out the program it was installed with.
	workDir := t.TempDir()
	first := aCallbackProgram(t)
	if _, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI: "claude_code", WorkDir: workDir, Program: first,
	}); err != nil {
		t.Fatalf("first run: %v", err)
	}

	second := aCallbackProgram(t)
	tools, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI: "claude_code", WorkDir: workDir, Program: second,
	})
	if err != nil {
		t.Fatalf("second run: %v", err)
	}
	target, err := os.Readlink(tools.Program)
	if err != nil {
		t.Fatalf("reading where the placed program points: %v", err)
	}
	if target != second {
		t.Fatalf("the agent still reaches %s after the daemon was replaced by %s", target, second)
	}
}

func TestTheAgentIsToldWhereItIsWorking(t *testing.T) {
	// The one command whose answer is on this disk needs to know which directory it is about,
	// and cannot ask the process where it happens to be standing (FR-020a).
	env, err := execenv.Environ(execenv.EnvSpec{
		CLI:         "claude_code",
		Home:        filepath.Join(t.TempDir(), "home"),
		WorkDir:     "/work/task-1",
		Credentials: execenv.Credentials{RunToken: "armr_run_thisone"},
	})
	if err != nil {
		t.Fatalf("building the environment: %v", err)
	}
	if got, _ := valueOf(env, execenv.WorkDirVar); got != "/work/task-1" {
		t.Fatalf("%s is %q, not the working directory", execenv.WorkDirVar, got)
	}
}

// valueOf finds one variable in a built environment.
func valueOf(env []string, name string) (string, bool) {
	for _, entry := range env {
		if n, v, ok := strings.Cut(entry, "="); ok && n == name {
			return v, true
		}
	}
	return "", false
}
