//go:build windows

package main

import (
	"context"
	"os"
	"os/exec"
	"syscall"
)

// Process creation flags from the Windows API that the syscall package does not name.
const detachedProcess = 0x00000008

// detached starts the background daemon without a console and in a process group of its own,
// so closing the window that started it does not end it (FR-008m).
func detached() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{CreationFlags: detachedProcess | syscall.CREATE_NEW_PROCESS_GROUP}
}

// restartInto starts the program on disk as this daemon's successor, with the same arguments and
// the same log, and then ends this process (FR-008n). Windows has no way to replace a running
// process image, so the successor is a new process, the way Multica's daemon hands over there.
func restartInto(program string) error {
	successor := exec.CommandContext(context.Background(), program, os.Args[1:]...) //nolint:gosec // this daemon's own executable
	successor.Stdout, successor.Stderr = os.Stdout, os.Stderr
	successor.SysProcAttr = detached()
	if err := successor.Start(); err != nil {
		return err
	}
	os.Exit(0)
	return nil
}
