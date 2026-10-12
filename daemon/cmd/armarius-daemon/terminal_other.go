//go:build !linux && !darwin && !windows

package main

// isTerminal answers no where this build cannot tell. No means nobody to ask, which makes `login`
// on a linked machine refuse unless `-yes` was given — the safe side of not knowing (FR-001e).
func isTerminal(uintptr) bool { return false }
