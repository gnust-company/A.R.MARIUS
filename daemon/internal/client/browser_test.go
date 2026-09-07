package client

import (
	"context"
	"os"
	"runtime"
	"strings"
	"testing"
)

// The addresses that must never reach a desktop opener: things that are not a web page.
//
// A desktop opener does far more than show pages. `file:` reads this disk; on Windows
// `FileProtocolHandler` handed a path to an executable **runs** it; `smb:` reaches somebody
// else's server. And the address is the server's answer, not a constant.
func TestAnAddressThatIsNotAWebPageIsRefused(t *testing.T) {
	refused := map[string]string{
		"a local file":               "file:///etc/passwd",
		"a windows executable path":  `C:\Windows\System32\calc.exe`,
		"script in an address":       "javascript:alert(1)",
		"somebody else's file share": "smb://attacker.example/share",
		"no host at all":             "http:///link",
		// `%` is legal in a URL only as the start of an escape, so `%CO` is not a URL at all
		// and parsing says so. It lands here rather than beside the other `cmd.exe` payloads
		// because the reason is *not a URL*, not *dangerous character*.
		"a bare percent, as cmd expands variables": "http://localhost:3000/link%COMSPEC%",
		"a newline in the middle":                  "http://localhost:3000/link\nrm -rf /",
		"a space in the middle":                    "http://localhost:3000/li nk",
		"empty":                                    "",
	}
	for what, raw := range refused {
		if err := SafeToOpen(raw); err == nil {
			t.Errorf("%s (%q) was accepted as an address to open", what, raw)
		}
	}
}

// The payloads review found, and the reason they are **accepted** here.
//
// `cmd.exe /c` takes its whole command line and parses it again as a script, so in `cmd`'s world
// `&`, `|`, `^` and `%` start new commands — and Go's argument quoting knows about spaces and
// quotes but nothing about those. That was a real hole while the Windows opener was
// `cmd /c start`. The fix is that **no opener goes through an interpreter any more**
// (`TestNoOpenerGoesThroughAShell`), not a character blacklist — because every one of these
// characters is ordinary and legal in a URL, and a check that refused them would refuse a large
// part of the real web along with the attack.
//
// Written down as a passing test on purpose. Somebody reading the review later will look for
// where these strings are handled, and the honest answer is *here, and they are let through* —
// which is only safe as long as the line above it stays true.
func TestShellMetacharactersAreOrdinaryCharactersHere(t *testing.T) {
	for what, raw := range map[string]string{
		"a second command appended": "http://localhost:3000/link?code=A&calc.exe",
		"a piped command":           "http://localhost:3000/link|calc.exe",
		"a caret-escaped command":   "http://localhost:3000/link^&calc.exe",
	} {
		if err := SafeToOpen(raw); err != nil {
			t.Errorf("%s (%q) was refused; the protection is meant to be the missing shell, not this check: %v", what, raw, err)
		}
	}
	// And the thing that makes the line above safe.
	name, _ := opener()
	for _, shell := range []string{"cmd", "cmd.exe", "sh", "bash", "powershell", "pwsh"} {
		if strings.EqualFold(name, shell) {
			t.Fatalf("opener is %q — the addresses above become commands", name)
		}
	}
}

// `&` and `%` are ordinary characters in a URL query, and a check that refused them would refuse
// half the real addresses on the web.
func TestAnOrdinaryWebAddressIsAccepted(t *testing.T) {
	for _, raw := range []string{
		"http://localhost:3000/link?code=KQ7F-M2XD",
		"https://armarius.example.com/link?code=KQ7F-M2XD&from=daemon",
		"https://armarius.example.com:8443/link?q=a%20b",
		"http://192.168.1.10:3000/link",
	} {
		if err := SafeToOpen(raw); err != nil {
			t.Errorf("a perfectly ordinary address was refused: %q → %v", raw, err)
		}
	}
}

// The check has to be on the door itself, not only on the one caller that exists today.
func TestOpenBrowserRefusesBeforeItRunsAnything(t *testing.T) {
	// A PATH with nothing on it: if the refusal did not happen first, this would fail with
	// "no browser" instead, and the test would pass for the wrong reason.
	t.Setenv("PATH", t.TempDir())
	t.Setenv("DISPLAY", ":0")
	err := OpenBrowser(context.Background(), "file:///etc/passwd")
	if err == nil {
		t.Fatal("OpenBrowser accepted a file: address")
	}
	if err == ErrNoBrowser {
		t.Fatal("OpenBrowser got as far as looking for an opener before refusing the address")
	}
	if !strings.Contains(err.Error(), "http") {
		t.Errorf("the refusal does not say what is wrong with the address: %v", err)
	}
}

// No opener may be a command interpreter, on any platform. Written as a test because the way
// this was got wrong the first time was a plausible-looking line, not a missing one.
func TestNoOpenerGoesThroughAShell(t *testing.T) {
	name, _ := opener()
	for _, shell := range []string{"cmd", "cmd.exe", "sh", "bash", "powershell", "pwsh"} {
		if strings.EqualFold(name, shell) {
			t.Fatalf("the opener on %s is %q, which parses its arguments as a script", runtime.GOOS, name)
		}
	}
}

// A machine nobody is sitting at must not be asked to open a page: on Linux that is exactly
// what an empty DISPLAY and WAYLAND_DISPLAY mean, and `xdg-open` there either fails or opens a
// terminal browser over the session the person is working in.
func TestALinuxBoxWithNoDisplayOpensNothing(t *testing.T) {
	if runtime.GOOS == "darwin" || runtime.GOOS == "windows" {
		t.Skip("the display test is about the Linux and BSD branch")
	}
	t.Setenv("DISPLAY", "")
	t.Setenv("WAYLAND_DISPLAY", "")
	if name, _ := opener(); name != "" {
		t.Errorf("a machine with no display was given %q to open pages with", name)
	}

	t.Setenv("DISPLAY", ":0")
	if name, _ := opener(); name == "" {
		t.Error("a machine with a display was given nothing to open pages with")
	}

	// Wayland alone counts too — a desktop without X is still a desktop.
	t.Setenv("DISPLAY", "")
	t.Setenv("WAYLAND_DISPLAY", "wayland-0")
	if name, _ := opener(); name == "" {
		t.Error("a Wayland desktop was given nothing to open pages with")
	}
}

// The address never reaches a shell, so this only has to hold for the one thing that could
// still bite: an opener that takes flags. A leading `-` is impossible once the scheme must be
// http or https, and that is what this pins.
func TestAnAddressCannotBeMistakenForAFlag(t *testing.T) {
	for _, raw := range []string{"-a", "--help", "-a /Applications/Calculator.app"} {
		if err := SafeToOpen(raw); err == nil {
			t.Errorf("%q was accepted, and an opener would read it as a flag", raw)
		}
	}
	if os.Getenv("ARMARIUS_NO_BROWSER") != "" {
		t.Skip("nothing here opens anything, but say so rather than pretending the variable was read")
	}
}
