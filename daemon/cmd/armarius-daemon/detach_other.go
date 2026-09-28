//go:build !windows

package main

import (
	"os"
	"syscall"
)

// detached starts the background daemon in a session of its own, so closing the terminal that
// started it — and the hang-up that sends to its session — does not reach it (FR-008m).
func detached() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setsid: true}
}

// restartInto replaces this process with the program on disk, keeping its process id, its open
// log and its arguments (FR-008n). A service manager watching the process id sees nothing change;
// a background daemon keeps writing to the same log.
func restartInto(program string) error {
	return syscall.Exec(program, os.Args, os.Environ()) //nolint:gosec // this daemon's own executable
}
