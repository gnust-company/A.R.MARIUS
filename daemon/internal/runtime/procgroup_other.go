//go:build !windows

package runtime

import (
	"os/exec"
	"syscall"
)

// leadItsOwnTree makes the CLI the leader of a new process group, so that everything it starts
// can be addressed — and ended — as one thing rather than one process at a time.
func leadItsOwnTree(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

// endTree signals the CLI's whole process group.
//
// A negative process id is the Unix way of naming a group, and the group's id is the leader's
// own id because `Setpgid` above made it one. A group nobody is in any more answers `ESRCH`,
// which is the ordinary reply once everything has already exited.
func endTree(cmd *exec.Cmd, hard bool) error {
	pid := cmd.Process.Pid
	if pid <= 1 {
		return nil
	}
	signal := syscall.SIGTERM
	if hard {
		signal = syscall.SIGKILL
	}
	return syscall.Kill(-pid, signal)
}
