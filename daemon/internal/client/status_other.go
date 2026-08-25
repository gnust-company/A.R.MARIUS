//go:build !windows

package client

import (
	"errors"
	"os"
	"syscall"
)

// processAlive reports whether a process id is still running on this machine.
//
// Signal 0 is the portable Unix way to ask: it delivers nothing and only performs the checks a
// real signal would. `EPERM` counts as alive — the process exists, it simply belongs to another
// account, which is the ordinary case for a daemon started by a service manager.
//
// Known and accepted: a process id can be reused, so a very old state file could in principle
// name a live process that is not this daemon. The state file being removed on a clean exit
// keeps that to the case where a daemon was killed outright and the machine then handed the
// same number to something else.
func processAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	err = process.Signal(syscall.Signal(0))
	return err == nil || errors.Is(err, syscall.EPERM)
}
