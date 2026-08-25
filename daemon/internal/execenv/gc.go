package execenv

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// How long things are kept, and how often we look.
const (
	// DefaultSweepInterval is how often the daemon looks around. Two hours, following Multica:
	// often enough that a machine does not fill up, rare enough that the sweep costs nothing.
	DefaultSweepInterval = 2 * time.Hour

	// DefaultWorkDirRetention is how long a working directory survives after its task closed
	// and went quiet (FR-021).
	DefaultWorkDirRetention = 24 * time.Hour

	// DefaultSessionRetention is how long a session is kept before the next wake has to start a
	// new one (FR-027). Fourteen days, per research §3.
	DefaultSessionRetention = 14 * 24 * time.Hour

	// DefaultOrphanRetention is how long a working directory the server no longer accounts for
	// survives (FR-021a). Deliberately far longer than DefaultWorkDirRetention: that one acts on
	// something the server stated, this one acts on the absence of a statement, and an absence is
	// the weaker evidence of the two. Seventy-two hours, per research §10.3.
	DefaultOrphanRetention = 72 * time.Hour
)

// TaskState is what the server says about one task while a sweep is running.
type TaskState struct {
	// Closed is true once the task is done or cancelled. Nothing else counts as closed.
	Closed bool
	// LastActivity is when anything last happened to the task.
	LastActivity time.Time
}

// TaskStates is how the collector asks the server about the tasks it found on disk.
//
// The daemon asks; the server never tells. There is deliberately no "this task is finished"
// message pushed down here (FR-021): a message can arrive while a machine is switched off, and a
// machine that missed it would hold the directory forever. A question asked on a schedule cannot
// be missed — it can only be asked late.
type TaskStates interface {
	Lookup(ctx context.Context, taskIDs []string) (map[string]TaskState, error)
}

// RunHolder reports whether a run currently holds a working directory.
type RunHolder interface {
	Holding(dir string) bool
}

// Collector reclaims what nobody needs any more, and nothing else.
type Collector struct {
	// WorkRoot holds one working directory per task, named after the task.
	WorkRoot string
	// StateRoot holds what outlives the working directories, laid out by StorePath.
	StateRoot string

	Tasks TaskStates
	Runs  RunHolder

	// Zero values fall back to the defaults above.
	WorkDirRetention time.Duration
	SessionRetention time.Duration
	OrphanRetention  time.Duration
}

// Kept is one directory the sweep chose to leave alone, and why. Every decision is recorded, not
// only the deletions: a collector that deletes nothing and says nothing is indistinguishable from
// a collector that is not running.
type Kept struct {
	Path   string
	Reason string
}

// Report is what one sweep did.
type Report struct {
	Removed []string
	Kept    []Kept
}

func (c Collector) workDirRetention() time.Duration {
	if c.WorkDirRetention > 0 {
		return c.WorkDirRetention
	}
	return DefaultWorkDirRetention
}

func (c Collector) sessionRetention() time.Duration {
	if c.SessionRetention > 0 {
		return c.SessionRetention
	}
	return DefaultSessionRetention
}

func (c Collector) orphanRetention() time.Duration {
	if c.OrphanRetention > 0 {
		return c.OrphanRetention
	}
	return DefaultOrphanRetention
}

// Sweep looks once at everything on disk and reclaims what has aged out.
//
// Uploaded artifacts are not affected by any of this. They left the machine before the task
// closed and live in the store on the server; removing the working directory they were produced
// in does not remove them (FR-021).
func (c Collector) Sweep(ctx context.Context, now time.Time) (Report, error) {
	var report Report

	if err := c.sweepWorkDirs(ctx, now, &report); err != nil {
		return report, err
	}
	if err := c.sweepSessions(now, &report); err != nil {
		return report, err
	}

	// Per-agent stores — long-term memory — are not swept. No CLI in the first round declares
	// one, so there is nothing on disk to age out, and inventing a retention for a store nobody
	// writes would be inventing the shared memory concept FR-007e rules out. The CLI that
	// declares the first PerAgent entry brings its own retention with it.

	sort.Strings(report.Removed)
	sort.Slice(report.Kept, func(i, j int) bool { return report.Kept[i].Path < report.Kept[j].Path })
	return report, nil
}

func (c Collector) sweepWorkDirs(ctx context.Context, now time.Time, report *Report) error {
	dirs, err := subdirectories(c.WorkRoot)
	if err != nil {
		return fmt.Errorf("listing working directories: %w", err)
	}
	if len(dirs) == 0 {
		return nil
	}

	// A directory a run is holding is never even asked about (FR-022). Asking would be harmless,
	// but keeping the check first means no future edit can reorder its way past it.
	candidates := make([]string, 0, len(dirs))
	for _, taskID := range dirs {
		path := filepath.Join(c.WorkRoot, taskID)
		if c.Runs != nil && c.Runs.Holding(path) {
			report.Kept = append(report.Kept, Kept{path, "a run is holding it"})
			continue
		}
		candidates = append(candidates, taskID)
	}
	if len(candidates) == 0 {
		return nil
	}

	states, err := c.Tasks.Lookup(ctx, candidates)
	if err != nil {
		return fmt.Errorf("asking the server about %d tasks: %w", len(candidates), err)
	}

	for _, taskID := range candidates {
		path := filepath.Join(c.WorkRoot, taskID)

		state, known := states[taskID]
		switch {
		case !known:
			// The server has no task by this name. Usually that means the task, its project or
			// its whole workspace was deleted while this machine was not looking; it can also
			// mean the run died before the server ever recorded the task. Either way nothing
			// will ever claim this directory again, so the FR-021 path — which only acts on a
			// task it was *told* had closed — would hold it forever (FR-021a).
			//
			// This is still the branch that acts without being told, so it gets the longer
			// clock and it asks the disk for a second opinion before destroying anything.
			if err := c.reclaimIfCold(now, path, report); err != nil {
				return err
			}
		case !state.Closed:
			report.Kept = append(report.Kept, Kept{path, "the task is still open"})
		case now.Sub(state.LastActivity) < c.workDirRetention():
			report.Kept = append(report.Kept, Kept{
				path,
				fmt.Sprintf("the task closed only %s ago", now.Sub(state.LastActivity).Round(time.Minute)),
			})
		default:
			if err := c.remove(c.WorkRoot, path); err != nil {
				return err
			}
			report.Removed = append(report.Removed, path)
		}
	}
	return nil
}

// reclaimIfCold removes a directory the server no longer accounts for, but only once nothing
// inside it has been written for the orphan retention.
//
// The two questions are asked in this order on purpose. A directory's own timestamp moves when an
// entry is added or removed directly inside it, and not when a file deep in the tree is written,
// so it alone would be a dangerous thing to delete on. It is a fine thing to *keep* on, though:
// if even the shallow answer says the directory was touched recently, it is certainly in use and
// no walk is needed. The full walk therefore runs only on the path that ends in RemoveAll, which
// is exactly where the extra I/O is worth paying for.
func (c Collector) reclaimIfCold(now time.Time, path string, report *Report) error {
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("inspecting %s: %w", path, err)
	}
	keep := func(age time.Duration) {
		report.Kept = append(report.Kept, Kept{
			path,
			fmt.Sprintf("the server does not know this task, but it was written to %s ago",
				age.Round(time.Minute)),
		})
	}

	if age := now.Sub(info.ModTime()); age < c.orphanRetention() {
		keep(age)
		return nil
	}

	newest, err := newestModTime(path)
	if err != nil {
		return fmt.Errorf("inspecting the contents of %s: %w", path, err)
	}
	if age := now.Sub(newest); age < c.orphanRetention() {
		keep(age)
		return nil
	}

	if err := c.remove(c.WorkRoot, path); err != nil {
		return err
	}
	report.Removed = append(report.Removed, path)
	return nil
}

// newestModTime is the most recent modification time anywhere under root, root itself included.
func newestModTime(root string) (time.Time, error) {
	var newest time.Time
	err := filepath.WalkDir(root, func(_ string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := d.Info()
		if err != nil {
			// A file that vanished mid-walk cannot be the newest thing here, and it is not a
			// reason to abandon a sweep that runs unattended.
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}
		if info.ModTime().After(newest) {
			newest = info.ModTime()
		}
		return nil
	})
	return newest, err
}

func (c Collector) sweepSessions(now time.Time, report *Report) error {
	clis, err := subdirectories(c.StateRoot)
	if err != nil {
		return fmt.Errorf("listing state stores: %w", err)
	}

	for _, cli := range clis {
		sessions := filepath.Join(c.StateRoot, cli, "sessions")
		tasks, err := subdirectories(sessions)
		if err != nil {
			return fmt.Errorf("listing sessions of %s: %w", cli, err)
		}

		for _, taskID := range tasks {
			path := filepath.Join(sessions, taskID)

			// The working directory of a live run links into this store. Deleting it now would
			// pull the session out from under an agent that is mid-conversation.
			workDir := filepath.Join(c.WorkRoot, taskID)
			if c.Runs != nil && c.Runs.Holding(workDir) {
				report.Kept = append(report.Kept, Kept{path, "a run is holding the task this session belongs to"})
				continue
			}

			info, err := os.Stat(path)
			if err != nil {
				return fmt.Errorf("inspecting session %s: %w", path, err)
			}
			if age := now.Sub(info.ModTime()); age < c.sessionRetention() {
				report.Kept = append(report.Kept, Kept{
					path, fmt.Sprintf("last used %s ago", age.Round(time.Minute)),
				})
				continue
			}
			if err := c.remove(c.StateRoot, path); err != nil {
				return err
			}
			report.Removed = append(report.Removed, path)
		}
	}
	return nil
}

// remove deletes a directory, but only after proving it is inside the root it was found under.
// The collector runs unattended on somebody else's machine and calls RemoveAll; a path assembled
// from a directory name is exactly the kind of input that deserves the check.
func (c Collector) remove(root, path string) error {
	cleanRoot, err := filepath.Abs(root)
	if err != nil {
		return fmt.Errorf("resolving %s: %w", root, err)
	}
	cleanPath, err := filepath.Abs(path)
	if err != nil {
		return fmt.Errorf("resolving %s: %w", path, err)
	}
	if cleanPath == cleanRoot || !strings.HasPrefix(cleanPath, cleanRoot+string(os.PathSeparator)) {
		return fmt.Errorf("refusing to remove %s: it is not inside %s", cleanPath, cleanRoot)
	}
	if err := os.RemoveAll(cleanPath); err != nil {
		return fmt.Errorf("removing %s: %w", cleanPath, err)
	}
	return nil
}

// subdirectories lists the immediate subdirectory names of a path, treating a path that does not
// exist as empty: a machine that has not run anything yet has no directories, which is normal.
func subdirectories(root string) ([]string, error) {
	entries, err := os.ReadDir(root)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	return names, nil
}
