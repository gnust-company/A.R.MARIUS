package execenv

import (
	"context"
	"errors"
	"os"
	"path/filepath"
)

// LinkMode is how one kind of thing gets into a CLI's home on this machine.
type LinkMode string

// The four answers, best first.
const (
	// LinkSymlink is a real symbolic link. Writes go through to the thing linked to, which is
	// what every long-lived piece of a CLI's home depends on.
	LinkSymlink LinkMode = "symlink"
	// LinkJunction is the Windows directory junction — a real redirection that needs none of
	// the privilege a symbolic link needs, and works only for directories.
	LinkJunction LinkMode = "junction"
	// LinkCopy is a copy. Safe only for things regenerated every run, because a copy stops
	// being the same thing the moment either side is written.
	LinkCopy LinkMode = "copy"
	// LinkNone is no way at all.
	LinkNone LinkMode = "none"
)

// ReasonLinkUnsupported is the code a workplace carries when this machine cannot link the
// pieces of a CLI's home that have to be linked. A code, never a sentence (Constitution VII).
const ReasonLinkUnsupported = "link_unsupported"

// LinkSupport is what this machine can do, established by doing it rather than by asking what
// operating system this is.
//
// The three fields are the three rows of research.md §5, and they are not interchangeable:
//
//   - Directories are the operator's own configuration and plugins. A junction redirects them
//     just as well as a symbolic link does.
//   - Skills are rewritten from scratch every run, so copying them is not a compromise — there
//     is no other copy to drift away from.
//   - SessionState and long-term memory must be linked and must never be copied. A copied
//     session file swallows everything one run writes into a duplicate the next run throws
//     away: the agent loses its memory and nothing anywhere reports a failure. Better to say
//     the workplace is not ready.
type LinkSupport struct {
	Directories  LinkMode
	Skills       LinkMode
	SessionState LinkMode
	// NotReadyReason is empty when this machine can host workplaces, and a code when it
	// cannot. The server puts it on every workplace of this machine.
	NotReadyReason string
}

// SymlinkCapable is the single fact the server is told, and it is the one that decides whether
// this machine's workplaces are offered work at all.
func (s LinkSupport) SymlinkCapable() bool { return s.SessionState == LinkSymlink }

// LinkOptions hands in the two acts being measured, so a test can describe a machine that
// refuses one of them without needing a machine that refuses it.
type LinkOptions struct {
	Symlink  func(target, link string) error
	Junction func(ctx context.Context, target, link string) error
}

// ProbeLinks finds out what this machine will let the daemon do, by trying it once at startup.
//
// This is the *prove it before relying on it* rule of research.md §5, and it is a real attempt
// rather than a guess about permissions: on Windows the privilege that grants symbolic links
// is per-account and per-policy, and no property of the machine reveals it as reliably as
// making one link does.
//
// The probe leaves nothing behind. It works inside a directory it creates and removes.
func ProbeLinks(ctx context.Context, dir string, opts LinkOptions) LinkSupport {
	opts = opts.withDefaults()

	switch {
	case canLink(ctx, dir, opts.Symlink, nil):
		return LinkSupport{
			Directories:  LinkSymlink,
			Skills:       LinkSymlink,
			SessionState: LinkSymlink,
		}
	case canLink(ctx, dir, nil, opts.Junction):
		return LinkSupport{
			Directories:  LinkJunction,
			Skills:       LinkCopy,
			SessionState: LinkNone,
			// A junction covers the operator's directories and copying covers the skills, but
			// nothing covers session state — so the workplace is not ready, loudly, rather
			// than working for a while and losing the agent's memory quietly.
			NotReadyReason: ReasonLinkUnsupported,
		}
	default:
		return LinkSupport{
			Directories:    LinkNone,
			Skills:         LinkCopy,
			SessionState:   LinkNone,
			NotReadyReason: ReasonLinkUnsupported,
		}
	}
}

// canLink makes one link of the given kind and checks that it actually redirects.
//
// Creating the link is not enough to believe it: a link that dangles, or that the filesystem
// accepted and did not honour, reports no error at creation and fails later inside a run. So
// the check is whether the directory linked to can be reached *through* the link.
func canLink(
	ctx context.Context,
	dir string,
	symlink func(target, link string) error,
	junction func(ctx context.Context, target, link string) error,
) bool {
	scratch, err := os.MkdirTemp(dir, "armarius-linkprobe-")
	if err != nil {
		return false
	}
	defer func() { _ = os.RemoveAll(scratch) }()

	target := filepath.Join(scratch, "target")
	if err := os.MkdirAll(target, 0o700); err != nil {
		return false
	}
	// A file inside the target, so reaching it through the link proves the redirection rather
	// than proving that something with the right name exists.
	if err := os.WriteFile(filepath.Join(target, "proof"), []byte("proof"), 0o600); err != nil {
		return false
	}

	link := filepath.Join(scratch, "link")
	switch {
	case symlink != nil:
		err = symlink(target, link)
	case junction != nil:
		err = junction(ctx, target, link)
	default:
		return false
	}
	if err != nil {
		return false
	}

	_, err = os.Stat(filepath.Join(link, "proof"))
	return err == nil
}

// errNoJunctions is what a machine with no such concept answers.
var errNoJunctions = errors.New("directory junctions exist only on Windows")

func (o LinkOptions) withDefaults() LinkOptions {
	if o.Symlink == nil {
		o.Symlink = os.Symlink
	}
	if o.Junction == nil {
		o.Junction = createJunction
	}
	return o
}
