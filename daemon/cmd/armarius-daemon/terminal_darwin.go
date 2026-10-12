//go:build darwin

package main

import (
	"syscall"
	"unsafe"
)

// isTerminal reports whether fd is a terminal, by asking it for its terminal settings — which only
// a terminal has. Being a character device is not enough: /dev/null is one (FR-001e).
func isTerminal(fd uintptr) bool {
	var settings syscall.Termios
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, fd, syscall.TIOCGETA,
		uintptr(unsafe.Pointer(&settings))) //nolint:gosec // the ioctl's own out-parameter, read nowhere else
	return errno == 0
}
