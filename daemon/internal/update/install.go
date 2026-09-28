package update

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// The two programs a release carries, installed as one: the daemon, and the callback program it
// refuses to start without (FR-008i).
const (
	DaemonProgram   = "armarius-daemon"
	CallbackProgram = "armarius"
)

// Target is where one release is put.
type Target struct {
	// Dir is the directory both programs live in — the running daemon's own.
	Dir string
	// GOOS and GOARCH pick the archive, the way the installer's detect_platform does.
	GOOS, GOARCH string
}

// ArchiveName is the file a release publishes for one platform, as `.goreleaser.yml` names it.
func ArchiveName(tag, goos, goarch string) string {
	ext := ".tar.gz"
	if goos == "windows" {
		ext = ".zip"
	}
	return fmt.Sprintf("%s_%s_%s_%s%s", DaemonProgram, strings.TrimPrefix(tag, "v"), goos, goarch, ext)
}

// Install puts one release in place: both programs, or neither (FR-008n, FR-008i).
//
// Checked or refused, with no third outcome — the installer's rule. The checksum list comes first,
// so a release half-published (archives up, `checksums.txt` not yet) fails before its archive is
// downloaded at all; the archive is checked whole, in memory, before a single byte of it is
// unpacked; and nothing is written beside the running programs until both have been read out.
//
// Then both land beside their targets as `<name>.new` and only after both are there do they move
// into place — so a failure part way leaves what was installed exactly as it was, and never a
// daemon without its callback program.
func Install(ctx context.Context, releases Releases, tag string, to Target) error {
	archive := ArchiveName(tag, to.GOOS, to.GOARCH)

	sums, err := releases.Download(ctx, tag, "checksums.txt")
	if err != nil {
		return fmt.Errorf("%w, so %s cannot be verified; nothing was changed", err, archive)
	}
	want, err := checksumFor(sums, archive)
	if err != nil {
		return err
	}
	packed, err := releases.Download(ctx, tag, archive)
	if err != nil {
		return err
	}
	got := sha256.Sum256(packed)
	if hex.EncodeToString(got[:]) != want {
		return fmt.Errorf("checksum mismatch on %s: expected %s, got %s — the download is not what %s published; nothing was changed",
			archive, want, hex.EncodeToString(got[:]), tag)
	}

	names := []string{executable(DaemonProgram, to.GOOS), executable(CallbackProgram, to.GOOS)}
	programs, err := unpack(packed, to.GOOS, names)
	if err != nil {
		return fmt.Errorf("%s: %w; nothing was changed", archive, err)
	}

	staged := make([]string, 0, len(names))
	unstage := func() {
		for _, path := range staged {
			_ = os.Remove(path)
		}
	}
	for _, name := range names {
		path := filepath.Join(to.Dir, name+".new")
		if err := os.WriteFile(path, programs[name], 0o755); err != nil { //nolint:gosec // an executable, which is the point
			unstage()
			return fmt.Errorf("writing %s into %s: %w; nothing was changed", name, to.Dir, err)
		}
		staged = append(staged, path)
	}
	for _, name := range names {
		if err := replace(filepath.Join(to.Dir, name+".new"), filepath.Join(to.Dir, name)); err != nil {
			return fmt.Errorf("putting %s in place in %s: %w", name, to.Dir, err)
		}
	}
	return nil
}

func executable(name, goos string) string {
	if goos == "windows" {
		return name + ".exe"
	}
	return name
}

// checksumFor pulls one archive's line out of `checksums.txt`: `<hex>  <name>`, or `<hex> *<name>`
// for a binary-mode line. Read by name rather than handed to a checker, as the installer does:
// the file lists every platform's archive, and only one of them is here.
func checksumFor(sums []byte, archive string) (string, error) {
	for _, line := range strings.Split(string(sums), "\n") {
		fields := strings.Fields(line)
		if len(fields) != 2 {
			continue
		}
		if name := strings.TrimPrefix(fields[1], "*"); name == archive {
			return strings.ToLower(fields[0]), nil
		}
	}
	return "", fmt.Errorf("checksums.txt does not list %s; nothing was changed", archive)
}

// unpack reads the named files out of an archive, and fails unless every one of them is there.
func unpack(packed []byte, goos string, names []string) (map[string][]byte, error) {
	wanted := make(map[string]bool, len(names))
	for _, name := range names {
		wanted[name] = true
	}
	found := make(map[string][]byte, len(names))
	keep := func(name string, r io.Reader) error {
		name = filepath.Base(name)
		if !wanted[name] {
			return nil
		}
		body, err := io.ReadAll(io.LimitReader(r, maxDownload+1))
		if err != nil {
			return err
		}
		if len(body) > maxDownload {
			return fmt.Errorf("%s is larger than any program this release could carry", name)
		}
		found[name] = body
		return nil
	}

	if goos == "windows" {
		zipped, err := zip.NewReader(bytes.NewReader(packed), int64(len(packed)))
		if err != nil {
			return nil, fmt.Errorf("reading the archive: %w", err)
		}
		for _, file := range zipped.File {
			if file.FileInfo().IsDir() {
				continue
			}
			rc, err := file.Open()
			if err != nil {
				return nil, fmt.Errorf("reading %s: %w", file.Name, err)
			}
			err = keep(file.Name, rc)
			_ = rc.Close()
			if err != nil {
				return nil, err
			}
		}
	} else {
		gz, err := gzip.NewReader(bytes.NewReader(packed))
		if err != nil {
			return nil, fmt.Errorf("reading the archive: %w", err)
		}
		tr := tar.NewReader(gz)
		for {
			header, err := tr.Next()
			if errors.Is(err, io.EOF) {
				break
			}
			if err != nil {
				return nil, fmt.Errorf("reading the archive: %w", err)
			}
			if header.Typeflag != tar.TypeReg {
				continue
			}
			if err := keep(header.Name, tr); err != nil {
				return nil, err
			}
		}
	}

	for _, name := range names {
		if _, ok := found[name]; !ok {
			return nil, fmt.Errorf("the archive does not contain %s", name)
		}
	}
	return found, nil
}
