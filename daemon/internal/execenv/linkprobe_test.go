package execenv

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

// A machine that makes symbolic links can do everything, and its workplaces are offered work.
// This is the ordinary case, and it is measured on the real filesystem rather than faked.
func TestAMachineThatMakesSymlinksIsReady(t *testing.T) {
	got := ProbeLinks(context.Background(), t.TempDir(), LinkOptions{})

	if !got.SymlinkCapable() {
		t.Fatalf("this filesystem makes symlinks, yet the probe said %+v", got)
	}
	if got.NotReadyReason != "" {
		t.Errorf("not-ready reason = %q, want none", got.NotReadyReason)
	}
	for name, mode := range map[string]LinkMode{
		"directories":   got.Directories,
		"skills":        got.Skills,
		"session state": got.SessionState,
	} {
		if mode != LinkSymlink {
			t.Errorf("%s = %q, want %q", name, mode, LinkSymlink)
		}
	}
}

// Windows without Developer Mode: junctions work, symbolic links do not. The operator's own
// directories are still reachable and skills are still safe to copy — but session state has no
// answer, so the machine says its workplaces are not ready instead of losing an agent's memory
// somewhere nobody is looking (research.md §5).
func TestAMachineWithOnlyJunctionsSaysItsWorkplacesAreNotReady(t *testing.T) {
	refused := LinkOptions{
		Symlink: func(string, string) error { return errors.New("a required privilege is not held") },
		Junction: func(_ context.Context, target, link string) error {
			return os.Symlink(target, link) // stands in for the real junction on this filesystem
		},
	}

	got := ProbeLinks(context.Background(), t.TempDir(), refused)

	if got.SymlinkCapable() {
		t.Fatal("no symbolic link was made, so nothing may report that one can be")
	}
	if got.Directories != LinkJunction {
		t.Errorf("directories = %q, want %q", got.Directories, LinkJunction)
	}
	if got.Skills != LinkCopy {
		t.Errorf("skills = %q, want %q — they are rewritten every run", got.Skills, LinkCopy)
	}
	if got.SessionState != LinkNone {
		t.Errorf("session state = %q, want %q — a copy silently loses it", got.SessionState, LinkNone)
	}
	if got.NotReadyReason != ReasonLinkUnsupported {
		t.Errorf("not-ready reason = %q, want %q", got.NotReadyReason, ReasonLinkUnsupported)
	}
}

func TestAMachineThatLinksNothingIsNotReadyEither(t *testing.T) {
	refused := LinkOptions{
		Symlink:  func(string, string) error { return errors.New("no") },
		Junction: func(context.Context, string, string) error { return errors.New("no") },
	}

	got := ProbeLinks(context.Background(), t.TempDir(), refused)

	if got.Directories != LinkNone || got.SessionState != LinkNone {
		t.Errorf("nothing links here, yet the probe said %+v", got)
	}
	if got.NotReadyReason != ReasonLinkUnsupported {
		t.Errorf("not-ready reason = %q, want %q", got.NotReadyReason, ReasonLinkUnsupported)
	}
}

// A link that is created and does not redirect is the case that costs a whole run: nothing
// fails at creation, and the agent's home is quietly empty. Creating it is not the proof —
// reaching through it is.
func TestALinkThatIsCreatedButDoesNotRedirectDoesNotCount(t *testing.T) {
	pretend := LinkOptions{
		Symlink: func(_, link string) error {
			// The name exists afterwards, and points at nothing.
			return os.Symlink(filepath.Join(filepath.Dir(link), "nowhere"), link)
		},
		Junction: func(context.Context, string, string) error { return errors.New("no") },
	}

	got := ProbeLinks(context.Background(), t.TempDir(), pretend)

	if got.SymlinkCapable() {
		t.Fatal("the link was created and leads nowhere; that is not a machine that links")
	}
}

// The probe runs at startup on the operator's own disk. It must not leave anything on it.
func TestTheProbeLeavesNothingBehind(t *testing.T) {
	dir := t.TempDir()

	ProbeLinks(context.Background(), dir, LinkOptions{})

	left, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(left) != 0 {
		t.Errorf("the probe left %d entries behind in the operator's directory", len(left))
	}
}
