//go:build windows

package runtime

import (
	"fmt"
	"os/exec"
	"strconv"
	"syscall"
)

// leadItsOwnTree starts the CLI in a console process group of its own, so a Ctrl-C meant for the
// daemon does not travel down into an agent mid-turn.
//
// Windows has no equivalent of a process group that can be signalled as a unit, so unlike on
// Unix this is not also how the tree is ended — see endTree.
func leadItsOwnTree(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP}
}

// endTree ends the CLI and everything it started.
//
// `taskkill /T` is what walks the tree here. A job object would be the tighter answer — it holds
// even processes that have detached themselves — but it needs `golang.org/x/sys/windows`, and
// this daemon has no dependencies at all; that is worth more than the last few percent of a case
// this walk already covers. The same reasoning picked `cmd /c mklink` for junctions.
func endTree(cmd *exec.Cmd, hard bool) error {
	pid := cmd.Process.Pid
	if pid <= 0 {
		return nil
	}
	args := []string{"/T", "/PID", strconv.Itoa(pid)}
	if hard {
		args = append([]string{"/F"}, args...)
	}
	out, err := exec.Command("taskkill", args...).CombinedOutput() //nolint:gosec // a process this daemon started, named by number
	if err != nil {
		return fmt.Errorf("taskkill: %w: %s", err, out)
	}
	return nil
}
