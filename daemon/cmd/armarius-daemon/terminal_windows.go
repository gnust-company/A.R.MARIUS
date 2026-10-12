//go:build windows

package main

import "syscall"

// isTerminal reports whether fd is a console. A redirected handle — a file, a pipe, NUL — has no
// console mode to read (FR-001e).
func isTerminal(fd uintptr) bool {
	var mode uint32
	return syscall.GetConsoleMode(syscall.Handle(fd), &mode) == nil
}
