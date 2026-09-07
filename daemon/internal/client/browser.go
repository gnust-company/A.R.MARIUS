package client

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"runtime"
)

// ErrNoBrowser reports that this machine has no way to open a page.
//
// Named rather than generic because it is not a failure: a server reached over SSH, a
// container, a box with no desktop at all is a normal place to run `login` from, and the
// answer there is the printed address and the printed code — which is why the flow that
// existed before this file still exists behind it.
var ErrNoBrowser = errors.New("this machine has no browser to open")

// OpenBrowser shows url in whatever the operator's desktop uses for pages.
//
// Deliberately fire-and-forget. On some desktops the opener is the browser's own launcher and
// does not return until the browser exits, so waiting here would hang `login` for as long as
// the person leaves their browser open — with the code expiring while it waited. The child is
// reaped by a goroutine so it does not sit in the process table for the life of the daemon.
func OpenBrowser(ctx context.Context, url string) error {
	name, args := opener()
	if name == "" {
		return ErrNoBrowser
	}
	if _, err := exec.LookPath(name); err != nil {
		return ErrNoBrowser
	}
	cmd := exec.CommandContext(ctx, name, append(args, url)...) //nolint:gosec // fixed opener, url is the server's own answer
	// Nothing the opener says is for the person running `login`: its chatter would land in
	// the middle of the code they are meant to read, and its failures are already covered by
	// the address being printed anyway.
	cmd.Stdout, cmd.Stderr = nil, nil
	if err := cmd.Start(); err != nil {
		return err
	}
	go func() { _ = cmd.Wait() }()
	return nil
}

// opener names the program that opens pages here, or nothing when there is none to try.
func opener() (string, []string) {
	switch runtime.GOOS {
	case "darwin":
		return "open", nil
	case "windows":
		// Through cmd rather than directly: `start` is a shell builtin, not a program, and
		// the empty argument is the window title `start` would otherwise take the URL for.
		return "cmd", []string{"/c", "start", ""}
	default:
		// A Linux or BSD box with neither display is a machine nobody is sitting at —
		// most often one reached over SSH. Asking `xdg-open` there either fails or, worse,
		// succeeds into a terminal browser that swallows the session.
		if os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == "" {
			return "", nil
		}
		return "xdg-open", nil
	}
}
