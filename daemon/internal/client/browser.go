package client

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"runtime"
	"strings"
)

// ErrNoBrowser reports that this machine has no way to open a page.
//
// Named rather than generic because it is not a failure: a server reached over SSH, a
// container, a box with no desktop at all is a normal place to run `login` from, and the
// answer there is the printed address and the printed code — which is why the flow that
// existed before this file still exists behind it.
var ErrNoBrowser = errors.New("this machine has no browser to open")

// SafeToOpen refuses an address that must not be handed to the desktop.
//
// The address comes down the wire from the server (`/daemon/link/start`), so it is input, not
// a constant — and a machine's desktop opener will do a great deal more than show a web page
// if you let it. Three refusals, each closing something different:
//
//   - **Only http and https.** `file:` opens whatever is on this disk; on Windows
//     `FileProtocolHandler` given a path to an executable runs it; `smb:` reaches out to
//     somebody else's server. A web page is the only thing this flow ever needs.
//   - **A host must be there.** `http:///x` and `http:x` parse, and what an opener does with
//     them is nothing this end can reason about.
//   - **No spaces and no control characters.** An opener takes arguments; a string with a
//     space in it is a string that can become two arguments somewhere down the line, and a
//     newline in a terminal can rewrite what the person thinks they are reading.
//
// What is deliberately *not* checked is whether the host matches `-server`. It must not:
// `-server` is the API and this address is the web interface, which is a different port and
// routinely a different hostname altogether.
//
// This is the second line, not the first. The first is that no opener here goes through a
// command interpreter — see `opener`.
func SafeToOpen(raw string) error {
	if strings.ContainsAny(raw, " \t\r\n") {
		return fmt.Errorf("%q has whitespace in it, so it is not an address this will open", raw)
	}
	for _, r := range raw {
		if r < 0x20 || r == 0x7f {
			return fmt.Errorf("%q has a control character in it, so it is not an address this will open", raw)
		}
	}
	parsed, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("%q is not a URL: %w", raw, err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return fmt.Errorf("%q is %q, and only http and https are opened", raw, parsed.Scheme)
	}
	if parsed.Host == "" {
		return fmt.Errorf("%q names no host", raw)
	}
	return nil
}

// OpenBrowser shows url in whatever the operator's desktop uses for pages.
//
// Deliberately fire-and-forget. On some desktops the opener is the browser's own launcher and
// does not return until the browser exits, so waiting here would hang `login` for as long as
// the person leaves their browser open — with the code expiring while it waited. The child is
// reaped by a goroutine so it does not sit in the process table for the life of the daemon.
func OpenBrowser(ctx context.Context, url string) error {
	// Checked here as well as by the caller, because this is the line the string crosses to
	// become a process argument, and a second caller added later must not have to remember.
	if err := SafeToOpen(url); err != nil {
		return err
	}
	name, args := opener()
	if name == "" {
		return ErrNoBrowser
	}
	if _, err := exec.LookPath(name); err != nil {
		return ErrNoBrowser
	}
	cmd := exec.CommandContext(ctx, name, append(args, url)...) //nolint:gosec // fixed opener; url is checked above
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
//
// **No entry here goes through a command interpreter, and that is the rule rather than the
// coincidence.** The first version of this file used `cmd /c start "" <url>` on Windows, which
// is exactly the hole review found: `cmd.exe /c` takes the whole command line and *parses it
// again* as a script, and Go's argument quoting knows about spaces and quotes but nothing about
// `&`, `|`, `^` or `%`. An address ending `&calc.exe` would have run a second command on the
// operator's own machine — and the address is the server's answer, not ours.
//
// `rundll32 url.dll,FileProtocolHandler` is the replacement: a program, given an argument, with
// no shell anywhere in the path.
func opener() (string, []string) {
	switch runtime.GOOS {
	case "darwin":
		return "open", nil
	case "windows":
		return "rundll32", []string{"url.dll,FileProtocolHandler"}
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
