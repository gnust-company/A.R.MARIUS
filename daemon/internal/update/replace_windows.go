//go:build windows

package update

import "os"

// replace moves a staged program over the one in place.
//
// Windows will not overwrite or delete an executable that is running, but it will rename one. So
// the running file moves aside to `<name>.old` first — removing whatever an earlier update left
// there — and the new one takes its name. The `.old` file is removed on the next update, once
// nothing is running from it.
func replace(staged, target string) error {
	aside := target + ".old"
	_ = os.Remove(aside)
	if err := os.Rename(target, aside); err != nil && !os.IsNotExist(err) {
		return err
	}
	if err := os.Rename(staged, target); err != nil {
		// Put the old one back rather than leave the name empty.
		_ = os.Rename(aside, target)
		return err
	}
	return nil
}
