//go:build windows

package execenv

import (
	"context"
	"fmt"
	"os/exec"
)

// createJunction makes a directory junction — the redirection Windows hands out without the
// privilege a symbolic link needs, so it is what a machine that is not in Developer Mode has
// left for the operator's own configuration directories (research.md §5).
//
// Both paths are ones the daemon just built inside a scratch directory of its own making, and
// no shell is involved: cmd.exe is the program that owns `mklink`, not an interpreter being
// handed a user's string.
func createJunction(ctx context.Context, target, link string) error {
	out, err := exec.CommandContext(ctx, "cmd", "/c", "mklink", "/J", link, target).CombinedOutput() //nolint:gosec // paths built by this process, in a directory it created
	if err != nil {
		return fmt.Errorf("mklink /J: %w: %s", err, out)
	}
	return nil
}
