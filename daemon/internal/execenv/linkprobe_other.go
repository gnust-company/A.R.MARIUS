//go:build !windows

package execenv

import "context"

// createJunction reports that this machine has no such thing.
//
// A junction is a Windows filesystem feature. Everywhere else, a machine that will not make a
// symbolic link has no second option — which is a real answer, not a gap: it means the
// workplace is not ready, and saying so is the whole point of the probe.
func createJunction(_ context.Context, _, _ string) error { return errNoJunctions }
