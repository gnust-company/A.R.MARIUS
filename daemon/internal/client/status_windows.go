//go:build windows

package client

import "os"

// processAlive reports whether a process id is still running on this machine.
//
// Windows has no signal 0, but it does not need one: unlike on Unix, os.FindProcess actually
// opens the process there and fails when there is nothing to open.
func processAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	_ = process.Release()
	return true
}
