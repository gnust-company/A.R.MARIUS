package execenv

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Skill is one skill as it arrives with the work: a directory name, and everything that goes
// in it.
//
// Files maps a path **relative to this skill's own directory** to that file's contents. The
// server sends contents rather than somewhere to fetch them from, so that by the time the
// agent reads its first line every skill it was granted is already on disk (FR-011b).
type Skill struct {
	Name  string
	Files map[string]string
}

// where one CLI looks for skills, and which directory that path hangs off.
type skillDir struct {
	path string
	// inHome is true when the CLI looks under its home rather than under the working
	// directory. Not a detail: the working directory belongs to one task, the home is built
	// for one run, and putting skills in the wrong one changes how long they live.
	inHome bool
}

// skillDirs is where each CLI goes looking for skills of its own accord.
//
// Same principle as the context file: write where it already looks. Gemini CLI is absent for
// the same reason it is absent there — unverified (FR-039a, task T013).
var skillDirs = map[string]skillDir{
	"claude_code": {path: ".claude/skills"},
	"codex":       {path: ".codex/skills", inHome: true},
}

// WriteSkills lays this run's skills out where cli will find them (FR-011b).
//
// **Real files, written fresh every run, never links into a shared store.** In the home Multica
// builds, everything else is a link — credentials, configuration, session state — and skills are
// the one thing deliberately copied. That is not an inconsistency: one workplace serves several
// agents (FR-007a), and a link to a shared skill store would put agent A's skills in front of
// agent B, which is exactly what FR-007b forbids. Writing the files out costs a few kilobytes
// and makes the leak impossible rather than merely unlikely.
//
// Writing fresh every run settles a second case at the same time. A working directory belongs to
// the task, not the run (FR-010), so it survives between runs — and a skill the patron changed
// or took away between two runs would otherwise still be sitting there, being read.
//
// Returns the directory the skills were written into.
func WriteSkills(cli, workDir, home string, skills []Skill) (string, error) {
	where, ok := skillDirs[cli]
	if !ok {
		return "", fmt.Errorf("no skills directory is declared for %q", cli)
	}
	root := workDir
	if where.inHome {
		root = home
	}
	if root == "" {
		return "", fmt.Errorf("writing skills for %s needs the directory they hang off", cli)
	}

	// Every skill is checked before a single byte is written. Checking as we go would leave a
	// half-laid-out directory behind on a bad packet — and worse, it would have already thrown
	// away the layout the previous run left, so a packet that is refused would still have
	// destroyed something.
	for _, skill := range skills {
		if !safeSegment(skill.Name) {
			return "", fmt.Errorf("skill %q has an unusable directory name", skill.Name)
		}
		for path := range skill.Files {
			if !staysInside(path) {
				return "", fmt.Errorf("skill %q has a file that leaves its own directory: %q", skill.Name, path)
			}
		}
	}

	dir := filepath.Join(root, filepath.FromSlash(where.path))
	// Taken away whole, then made again. Removing rather than emptying is also what stops the
	// directory being a link: os.RemoveAll takes the link and leaves whatever it pointed at
	// alone, so a run cannot be talked into writing skills into the operator's own CLI
	// configuration — the one place FR-013a and FR-011b both say must never be written.
	if err := os.RemoveAll(dir); err != nil {
		return "", fmt.Errorf("clearing the skills directory for %s: %w", cli, err)
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", fmt.Errorf("creating the skills directory for %s: %w", cli, err)
	}

	for _, skill := range skills {
		for path, content := range skill.Files {
			target := filepath.Join(dir, skill.Name, filepath.FromSlash(path))
			if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
				return "", fmt.Errorf("creating %s for skill %q: %w", path, skill.Name, err)
			}
			if err := os.WriteFile(target, []byte(content), 0o600); err != nil {
				return "", fmt.Errorf("writing %s for skill %q: %w", path, skill.Name, err)
			}
		}
	}
	return dir, nil
}

// safeSegment says whether name can be one directory, and only ever one directory.
func safeSegment(name string) bool {
	if name == "" || name == "." || name == ".." {
		return false
	}
	return !strings.ContainsAny(name, `/\:`)
}

// staysInside says whether a skill file's relative path can only land inside its own directory.
//
// Checked step by step rather than by cleaning the path and comparing the result against the
// root. Cleaning answers *where would this end up*, which is only useful once compared — and the
// comparison is the half that gets forgotten. Asking whether any single step could climb, or
// start from the top, has no forgettable half.
//
// The server refuses these too, before they are ever sent. Both checks are wanted: the server's
// keeps a bad skill out of every packet, and this one is what makes the promise true on a
// machine that is handed a packet from anywhere at all.
func staysInside(path string) bool {
	if path == "" || strings.HasPrefix(path, "/") || strings.HasPrefix(path, `\`) {
		return false
	}
	for _, part := range strings.Split(strings.ReplaceAll(path, `\`, "/"), "/") {
		if !safeSegment(part) {
			return false
		}
	}
	return true
}
