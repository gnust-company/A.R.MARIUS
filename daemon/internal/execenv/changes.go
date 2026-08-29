package execenv

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// placedFile is where the daemon writes down what it put into a working directory itself.
//
// A record rather than a rule. What has to be left out of *what the agent changed* is a moving
// list — a brief, a skills directory, a callback program, whatever is laid down next — and every
// other way of knowing it is a guess made somewhere else: a table of CLI-specific names that has
// to be kept in step with three other tables, or a blanket rule about hidden files that would
// quietly swallow something the agent actually made. The side that placed the files is the only
// side that knows for certain, so it says so.
const placedFile = ".armarius/placed.json"

// Change is one thing found in a task's working directory that the agent put there.
type Change struct {
	// Path is relative to the working directory, always with forward slashes so that what the
	// agent is shown reads the same on every operating system.
	Path string `json:"path"`
	// Size is in bytes, as of the moment of looking.
	Size int64 `json:"bytes"`
	// Modified is when it was last written.
	Modified time.Time `json:"modified_at"`
}

// ChangeList is the answer to *what have I got here*.
type ChangeList struct {
	// Root is the working directory this is about.
	Root string `json:"root"`
	// Total is how many files were found, which is not always how many are listed.
	Total int `json:"total"`
	// Files are the most recently written ones first, cut to the limit that was asked for. Most
	// recent first because the thing an agent is about to publish is almost always the thing it
	// has just finished writing.
	Files []Change `json:"changed"`
}

// RecordPlaced writes down what this run's setup put into the working directory (FR-020a).
//
// Called after everything is laid out, so that what the agent is later shown as *its* changes
// does not include the brief it was handed, the skills it was granted, or the program it calls
// back with.
func RecordPlaced(workDir string, paths []string) error {
	if workDir == "" {
		return fmt.Errorf("recording what was placed needs the working directory it was placed in")
	}
	relative := make([]string, 0, len(paths))
	for _, p := range paths {
		if rel, ok := within(workDir, p); ok {
			relative = append(relative, rel)
		}
	}
	sort.Strings(relative)

	path := filepath.Join(workDir, filepath.FromSlash(placedFile))
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("recording what was placed in %s: %w", workDir, err)
	}
	body, err := json.Marshal(relative)
	if err != nil {
		return fmt.Errorf("recording what was placed in %s: %w", workDir, err)
	}
	if err := os.WriteFile(path, body, 0o600); err != nil {
		return fmt.Errorf("recording what was placed in %s: %w", workDir, err)
	}
	return nil
}

// Changes lists what is in a task's working directory that the agent put there (FR-020a).
//
// **The working directory starts empty, so its contents are the changes.** Armarius puts no
// source code in it and manages no branch (FR-041); the only things in it that are not the
// agent's are the ones this run's setup laid down, and those were written down at the time. So
// there is no baseline to take, nothing to diff against, and no clock to trust — which also
// means the answer stays right across runs of the same task, where a per-run baseline would hide
// the file an earlier run made and never published (FR-010, FR-020b).
//
// **It is information, and it publishes nothing** (FR-018, FR-020a). The agent reads this and
// decides; the daemon never decides for it, and never pushes anything on its behalf.
//
// Deletions are not reported, and cannot be: what is gone left no trace to find. That is the
// honest limit of reading a directory, and it costs nothing here — a file that is gone is not a
// file anybody was about to publish.
func Changes(workDir string, limit int) (ChangeList, error) {
	if workDir == "" {
		return ChangeList{}, fmt.Errorf("listing changes needs a working directory")
	}
	info, err := os.Stat(workDir)
	if err != nil {
		return ChangeList{}, fmt.Errorf("looking in %s: %w", workDir, err)
	}
	if !info.IsDir() {
		return ChangeList{}, fmt.Errorf("%s is not a directory", workDir)
	}

	skip := placedIn(workDir)
	// Ours whether or not it was written down: the record itself lives in here, and so does
	// every run's home.
	skip[".armarius"] = struct{}{}

	list := ChangeList{Root: workDir}
	walkErr := filepath.WalkDir(workDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			// A directory this daemon cannot read is not a reason to answer nothing about the
			// rest. The agent asked what it has; an unreadable corner is not part of that.
			if d != nil && d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if path == workDir {
			return nil
		}
		rel, ok := within(workDir, path)
		if !ok {
			return nil
		}
		if _, placed := skip[rel]; placed {
			if d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if d.IsDir() {
			return nil
		}
		// Symbolic links are counted as what they are, never followed. Following one would walk
		// out of the working directory — into the operator's own home, in the case of the links
		// this daemon puts there itself — and report their contents as the agent's work.
		if d.Type()&fs.ModeSymlink != 0 {
			return nil
		}
		entry, err := d.Info()
		if err != nil {
			return nil
		}
		list.Total++
		list.Files = append(list.Files, Change{
			Path:     rel,
			Size:     entry.Size(),
			Modified: entry.ModTime().UTC(),
		})
		return nil
	})
	if walkErr != nil {
		return ChangeList{}, fmt.Errorf("looking through %s: %w", workDir, walkErr)
	}

	sort.Slice(list.Files, func(i, j int) bool {
		if list.Files[i].Modified.Equal(list.Files[j].Modified) {
			return list.Files[i].Path < list.Files[j].Path
		}
		return list.Files[i].Modified.After(list.Files[j].Modified)
	})
	if limit > 0 && len(list.Files) > limit {
		list.Files = list.Files[:limit]
	}
	return list, nil
}

// placedIn reads back what setup said it put here.
//
// A missing or unreadable record answers *nothing was placed*. It is the weaker failure of the
// two available: the agent then sees its brief listed among its own files, which is confusing and
// harmless, where refusing outright would take away the only way it has of seeing what it made.
func placedIn(workDir string) map[string]struct{} {
	skip := map[string]struct{}{}
	// #nosec G304 -- the path is this daemon's own constant under a directory this daemon made;
	// the caller is the run flow, not anything that came off the wire.
	body, err := os.ReadFile(filepath.Join(workDir, filepath.FromSlash(placedFile)))
	if err != nil {
		return skip
	}
	var paths []string
	if err := json.Unmarshal(body, &paths); err != nil {
		return skip
	}
	for _, p := range paths {
		skip[p] = struct{}{}
	}
	return skip
}

// within answers what a path is called relative to a root, and whether it is inside it at all.
func within(root, path string) (string, bool) {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return "", false
	}
	if rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return "", false
	}
	return filepath.ToSlash(rel), true
}
