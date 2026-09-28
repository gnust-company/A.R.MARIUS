// Package update keeps a running daemon on the newest release by itself (FR-008n).
//
// Two roads, one decision about when to take them. The daemon can fetch a newer release and put
// it in place, or notice that somebody else already put one in place; either way it restarts only
// when it is holding no run, and it restarts through the same orderly stop every other stop takes
// (FR-034). The shape is Multica's daemon's (`server/internal/daemon/auto_update.go`,
// `server/internal/cli/update.go`); where the release lives and how a download is checked are the
// installer's (FR-008i), so the daemon and `install.sh` can never disagree about what a release is.
package update

import (
	"strconv"
	"strings"
)

// IsRelease reports whether a version names a tagged release — `0.1.0`, `v0.1.0` — rather than
// a build from source, which reports `dev` or a `git describe` string.
//
// Only a release updates itself. A build from source is on the machine because somebody is trying
// something on it, and replacing it with a public release would quietly throw that away.
func IsRelease(version string) bool {
	_, ok := parse(version)
	return ok
}

// Newer reports whether latest is strictly newer than current. Either side unreadable answers
// false, which the caller reads as *stay where you are*.
func Newer(latest, current string) bool {
	l, ok := parse(latest)
	if !ok {
		return false
	}
	c, ok := parse(current)
	if !ok {
		return false
	}
	for i := range l {
		if l[i] != c[i] {
			return l[i] > c[i]
		}
	}
	return false
}

// parse reads exactly three numeric parts. Strict on purpose: a `git describe` suffix or a
// pre-release tag is not a release, and reading its leading digits as one would let the loop
// "upgrade" a developer's build to a public release that happens to share the first numbers.
func parse(version string) ([3]int, bool) {
	s := strings.TrimPrefix(strings.TrimSpace(version), "v")
	parts := strings.Split(s, ".")
	if len(parts) != 3 {
		return [3]int{}, false
	}
	var out [3]int
	for i, part := range parts {
		if part == "" {
			return [3]int{}, false
		}
		for _, r := range part {
			if r < '0' || r > '9' {
				return [3]int{}, false
			}
		}
		n, err := strconv.Atoi(part)
		if err != nil {
			return [3]int{}, false
		}
		out[i] = n
	}
	return out, true
}

// VersionIn reads the version out of what `armarius-daemon --version` prints:
//
//	armarius-daemon 0.1.0 (commit abc1234, built 2026-09-07T01:54:55Z)
//
// Anything else comes back trimmed, which compares unequal to a real version and is therefore
// noticed rather than silently taken for a match.
func VersionIn(printed string) string {
	line, _, _ := strings.Cut(printed, "\n")
	fields := strings.Fields(line)
	if len(fields) >= 2 && fields[0] == "armarius-daemon" {
		return fields[1]
	}
	return strings.TrimSpace(line)
}
