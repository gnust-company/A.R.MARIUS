//go:build !windows

package update

import "os"

// replace moves a staged program over the one in place. On Unix a rename over a running
// executable is safe: the running process keeps the file it was started from, and the name now
// points at the new one.
func replace(staged, target string) error {
	return os.Rename(staged, target)
}
