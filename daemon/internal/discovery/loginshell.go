package discovery

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// Finding a CLI the daemon's own search path does not have (FR-002a).
//
// A daemon is not started the way a person's terminal is. Run as a service, from a desktop
// launcher, or under a minimal environment, it inherits a search path that has never seen the
// operator's startup files — and those files are exactly where an installer puts a CLI it has
// just installed. Measured 2026-11-15: Kimi Code installs to `~/.kimi-code/bin` and adds that
// directory to PATH with one line in `~/.bashrc`, so `kimi` answers in every terminal on the
// machine and is nowhere on the path of a daemon started with the system's own.
//
// The answer is the one Multica's daemon uses (`resolveAgentsViaLoginShell`,
// `server/internal/daemon/config.go`): ask the operator's shell, started the way their terminal
// starts it, where it finds each name.

// The shells this is put to. All of them take `-ilc` and a POSIX script; a shell that is none
// of these is not asked, because a script that fails in an unknown shell fails in an unknown way.
var loginShells = map[string]bool{"bash": true, "zsh": true, "sh": true, "dash": true, "ksh": true}

// loginShellPatience bounds the whole question. The shell runs the operator's startup files,
// which this daemon knows nothing about; one that takes longer than this is treated as having
// found nothing, and the daemon starts with the CLIs its own path has.
const loginShellPatience = 3 * time.Second

// loginShellGrace bounds the tail after that: a startup file that left something running holds
// the pipe open, and waiting on it would be the daemon never finishing its start.
const loginShellGrace = 2 * time.Second

// askLoginShell asks the operator's login shell where it finds each of these names.
//
// What comes back is only what survives three checks. The name has to be one that is safe to
// write into a script as it is. The shell has to answer with an absolute path — an alias or a
// shell function answers with its own definition, which is why both are taken off the name
// before asking. And the path has to be something this process can run right now: a version
// manager's per-shell directory can be gone by the time the shell that named it has exited.
//
// No shell, an unknown shell, a slow one, a failing one: all of them are *nothing found*, which
// is where the daemon stood before it asked.
func askLoginShell(ctx context.Context, binaries []string) map[string]string {
	shell := strings.TrimSpace(os.Getenv("SHELL"))
	if shell == "" || !loginShells[filepath.Base(shell)] {
		return nil
	}
	var names []string
	for _, binary := range binaries {
		if bareName(binary) {
			names = append(names, binary)
		}
	}
	if len(names) == 0 {
		return nil
	}

	ctx, cancel := context.WithTimeout(ctx, loginShellPatience)
	defer cancel()

	// Interactive **and** login, so a path set in either kind of startup file is seen: people
	// put it in both, and installers pick one without saying which.
	cmd := exec.CommandContext(ctx, shell, "-ilc", whereScript(names)) //nolint:gosec // the operator's own shell, and a script built from names checked by bareName
	cmd.WaitDelay = loginShellGrace
	out, err := cmd.Output()
	if err != nil {
		return nil
	}
	return placed(string(out), exec.LookPath)
}

// placed reads the shell's answer: one `name<TAB>path` per line, among whatever else the
// operator's startup files chose to print.
func placed(out string, runnable func(string) (string, error)) map[string]string {
	found := map[string]string{}
	for _, line := range strings.Split(out, "\n") {
		name, path, ok := strings.Cut(line, "\t")
		path = strings.TrimSpace(path)
		if !ok || !bareName(name) || !filepath.IsAbs(path) {
			continue
		}
		if _, err := runnable(path); err != nil {
			continue
		}
		found[name] = path
	}
	return found
}

// whereScript is what the shell is given to run.
//
// `command -v` is the POSIX way to ask where a name resolves. The directory is then read back
// with `pwd -P` while the shell is still alive, so a path through a link that exists only for
// that shell comes back as the real one.
func whereScript(names []string) string {
	var script strings.Builder
	script.WriteString("for n in")
	for _, name := range names {
		script.WriteByte(' ')
		script.WriteString(name)
	}
	script.WriteString("; do\n")
	script.WriteString("  unalias \"$n\" 2>/dev/null\n")
	script.WriteString("  unset -f \"$n\" 2>/dev/null\n")
	script.WriteString("  p=$(command -v \"$n\" 2>/dev/null) || continue\n")
	script.WriteString("  case \"$p\" in /*) ;; *) continue ;; esac\n")
	// Split with the shell's own expansions rather than `dirname` and `basename`: those are
	// programs, and a daemon started with next to no search path hands the shell a path they
	// may not be on — measured, where every name was found and then dropped on this line.
	script.WriteString("  d=${p%/*}; f=${p##*/}\n")
	script.WriteString("  c=$(cd \"${d:-/}\" 2>/dev/null && pwd -P) || continue\n")
	script.WriteString("  printf '%s\\t%s\\n' \"$n\" \"$c/$f\"\n")
	script.WriteString("done\n")
	return script.String()
}

// bareName says whether a name can be written into a shell script exactly as it is: letters,
// digits, dot, dash and underscore. Every binary in the registry is; the check is there for the
// row somebody adds later.
func bareName(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		case r == '-' || r == '_' || r == '.':
		default:
			return false
		}
	}
	return true
}
