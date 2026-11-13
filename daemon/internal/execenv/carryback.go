package execenv

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// CarryBack returns to the operator's own home what a CLI wrote **over** a link to it (FR-007s).
//
// A run's home links the operator's sign-in in rather than copying it, so that an agent does
// not have to sign in again. That holds for reading. It does not hold for a CLI that renews its
// sign-in during the run: Claude Code writes its credentials by staging a file beside the name
// and renaming it over the name, and a rename lands on the link, not through it. The renewed
// sign-in is then a regular file in a home that is deleted when the run ends, and the
// operator's real file still holds the one it replaced.
//
// That would only be a wasted renewal if the old one stayed good. It does not: the token that
// buys a renewal is spent by using it, so the file left in the operator's home can never renew
// again. Every later run — and the operator's own terminal — fails with *session expired and
// could not be refreshed*, on a machine where nobody signed out (seen 2026-11-11).
//
// So the renewed file is carried back to where the link pointed, and the link is put back. A
// path that is still a link was not rewritten and is left alone; a path that is gone is left
// alone too — a CLI that signed out inside one run has not signed the operator out.
//
// Returns the relative paths it carried, for the log. Never their contents.
func CarryBack(cli, home, operatorHome string) ([]string, error) {
	row, known := agentcli.Lookup(cli)
	if !known || home == "" || operatorHome == "" {
		return nil, nil
	}
	var carried []string
	for _, rel := range row.Refreshed {
		done, err := carryOne(
			filepath.Join(home, filepath.FromSlash(rel)),
			filepath.Join(operatorHome, filepath.FromSlash(rel)),
		)
		if err != nil {
			return carried, fmt.Errorf("carrying %s back to the operator's own: %w", rel, err)
		}
		if done {
			carried = append(carried, rel)
		}
	}
	return carried, nil
}

// carryOne looks at one linked path and carries it back if the CLI replaced it.
func carryOne(inHome, theirs string) (bool, error) {
	now, err := os.Lstat(inHome)
	if err != nil || !now.Mode().IsRegular() {
		// Gone, still the link, or something this was never meant to move.
		return false, nil //nolint:nilerr // a path that is not there has nothing to carry
	}

	// Where the operator's file really is. Somebody who keeps their dotfiles under a manager
	// has a link here of their own, and renaming over it would do to them exactly what the CLI
	// did to us.
	target := theirs
	if resolved, err := filepath.EvalSymlinks(theirs); err == nil {
		target = resolved
	}

	fresh := true
	if had, err := os.Stat(target); err == nil && !now.ModTime().After(had.ModTime()) {
		// The operator's own file changed after this one was written — they signed in again
		// while the run was going. Theirs is the newer truth.
		fresh = false
	}
	if fresh {
		data, err := os.ReadFile(inHome) //nolint:gosec // a path inside the home this daemon built
		if err != nil {
			return false, err
		}
		// Never trade the operator's sign-in for something that is not one. The CLI publishes
		// by rename, so a regular file here is whole — this is the check that it is also sane.
		if !json.Valid(data) || len(data) == 0 {
			fresh = false
		} else if err := replaceFile(target, data); err != nil {
			return false, err
		}
	}

	// The link goes back either way, so the rest of this run reads the operator's file again
	// and a second renewal is seen as well as the first. Staged and renamed, so the CLI never
	// finds the name missing — a sign-in that vanishes for an instant is a signed-out agent.
	staged := inHome + ".armarius-link"
	_ = os.Remove(staged)
	if err := os.Symlink(theirs, staged); err != nil {
		return fresh, err
	}
	if err := os.Rename(staged, inHome); err != nil {
		_ = os.Remove(staged)
		return fresh, err
	}
	return fresh, nil
}

// replaceFile puts new contents under a name in one step, readable by its owner only.
func replaceFile(path string, data []byte) error {
	staged, err := os.CreateTemp(filepath.Dir(path), ".armarius-carry-*")
	if err != nil {
		return err
	}
	name := staged.Name()
	// CreateTemp makes it 0600 already; said again because what is in it is a sign-in.
	err = staged.Chmod(0o600)
	if err == nil {
		_, err = staged.Write(data)
	}
	if err == nil {
		err = staged.Sync()
	}
	if closeErr := staged.Close(); err == nil {
		err = closeErr
	}
	if err == nil {
		err = os.Rename(name, path)
	}
	if err != nil {
		_ = os.Remove(name)
	}
	return err
}
