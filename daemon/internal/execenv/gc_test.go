package execenv

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fakeTasks struct {
	states map[string]TaskState
	err    error
	asked  [][]string
}

func (f *fakeTasks) Lookup(_ context.Context, ids []string) (map[string]TaskState, error) {
	f.asked = append(f.asked, append([]string(nil), ids...))
	if f.err != nil {
		return nil, f.err
	}
	return f.states, nil
}

type fakeRuns struct{ held map[string]bool }

func (f fakeRuns) Holding(dir string) bool { return f.held[dir] }

// world lays out a machine's disk for one test: working directories, and session stores whose
// age can be set.
type world struct {
	root      string
	workRoot  string
	stateRoot string
}

func newWorld(t *testing.T) world {
	t.Helper()
	root := t.TempDir()
	return world{root: root, workRoot: filepath.Join(root, "work"), stateRoot: filepath.Join(root, "state")}
}

func (w world) workDir(t *testing.T, taskID string) string {
	t.Helper()
	path := filepath.Join(w.workRoot, taskID)
	if err := os.MkdirAll(filepath.Join(path, "repo", "src"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "repo", "src", "main.go"), []byte("package main"), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func (w world) session(t *testing.T, cli, taskID string, age time.Duration) string {
	t.Helper()
	path := filepath.Join(w.stateRoot, cli, "sessions", taskID)
	if err := os.MkdirAll(path, 0o700); err != nil {
		t.Fatal(err)
	}
	when := time.Now().Add(-age)
	if err := os.Chtimes(path, when, when); err != nil {
		t.Fatal(err)
	}
	return path
}

func (w world) collector(tasks TaskStates, runs RunHolder) Collector {
	return Collector{WorkRoot: w.workRoot, StateRoot: w.stateRoot, Tasks: tasks, Runs: runs}
}

func reasonFor(r Report, path string) (string, bool) {
	for _, k := range r.Kept {
		if k.Path == path {
			return k.Reason, true
		}
	}
	return "", false
}

func contains(list []string, want string) bool {
	for _, got := range list {
		if got == want {
			return true
		}
	}
	return false
}

func TestAMachineThatHasRunNothingSweepsCleanly(t *testing.T) {
	w := newWorld(t)
	report, err := w.collector(&fakeTasks{}, fakeRuns{}).Sweep(context.Background(), time.Now())
	if err != nil {
		t.Fatalf("sweeping an empty machine failed: %v", err)
	}
	if len(report.Removed) != 0 || len(report.Kept) != 0 {
		t.Errorf("an empty machine produced %+v", report)
	}
}

// FR-022. The check comes before the question to the server, so it cannot be reordered past.
func TestADirectoryARunIsHoldingIsNeverEvenAskedAbout(t *testing.T) {
	w := newWorld(t)
	busy := w.workDir(t, "task-busy")
	now := time.Now()

	tasks := &fakeTasks{states: map[string]TaskState{
		"task-busy": {Closed: true, LastActivity: now.Add(-30 * 24 * time.Hour)},
	}}
	report, err := w.collector(tasks, fakeRuns{held: map[string]bool{busy: true}}).Sweep(context.Background(), now)
	if err != nil {
		t.Fatalf("Sweep returned an error: %v", err)
	}

	if _, err := os.Stat(busy); err != nil {
		t.Fatalf("a directory a run was holding was removed: %v", err)
	}
	if reason, kept := reasonFor(report, busy); !kept || !strings.Contains(reason, "holding") {
		t.Errorf("the report does not say the run was holding it: %q", reason)
	}
	for _, ask := range tasks.asked {
		if contains(ask, "task-busy") {
			t.Error("the server was asked about a task whose directory a run is holding")
		}
	}
}

func TestWhatIsKeptAndWhatGoes(t *testing.T) {
	w := newWorld(t)
	now := time.Now()

	open := w.workDir(t, "task-open")
	justClosed := w.workDir(t, "task-just-closed")
	longClosed := w.workDir(t, "task-long-closed")
	orphan := w.workDir(t, "task-nobody-knows")

	tasks := &fakeTasks{states: map[string]TaskState{
		"task-open":        {Closed: false, LastActivity: now.Add(-90 * 24 * time.Hour)},
		"task-just-closed": {Closed: true, LastActivity: now.Add(-time.Hour)},
		"task-long-closed": {Closed: true, LastActivity: now.Add(-25 * time.Hour)},
	}}

	report, err := w.collector(tasks, fakeRuns{}).Sweep(context.Background(), now)
	if err != nil {
		t.Fatalf("Sweep returned an error: %v", err)
	}

	// An open task keeps its directory no matter how long it has been quiet: quiet is not closed.
	if _, err := os.Stat(open); err != nil {
		t.Error("the directory of an open task was removed")
	}
	if reason, _ := reasonFor(report, open); !strings.Contains(reason, "still open") {
		t.Errorf("wrong reason for keeping an open task: %q", reason)
	}

	if _, err := os.Stat(justClosed); err != nil {
		t.Error("a directory was removed one hour after its task closed")
	}
	if reason, _ := reasonFor(report, justClosed); !strings.Contains(reason, "ago") {
		t.Errorf("wrong reason for keeping a just-closed task: %q", reason)
	}

	if _, err := os.Stat(longClosed); !os.IsNotExist(err) {
		t.Error("a directory whose task closed 25 hours ago was kept")
	}
	if !contains(report.Removed, longClosed) {
		t.Errorf("the removal was not reported: %+v", report.Removed)
	}

	// Never guess. A directory the server cannot account for may hold work nobody can recover.
	if _, err := os.Stat(orphan); err != nil {
		t.Error("a directory was removed although the server said nothing about its task")
	}
	if reason, _ := reasonFor(report, orphan); !strings.Contains(reason, "does not know") {
		t.Errorf("wrong reason for keeping an unaccounted-for directory: %q", reason)
	}
}

func TestNothingIsRemovedWhenTheServerCannotBeReached(t *testing.T) {
	w := newWorld(t)
	dir := w.workDir(t, "task-1")
	now := time.Now()

	_, err := w.collector(&fakeTasks{err: errors.New("no route to host")}, fakeRuns{}).Sweep(context.Background(), now)
	if err == nil {
		t.Fatal("a failed lookup was reported as a successful sweep")
	}
	if _, statErr := os.Stat(dir); statErr != nil {
		t.Error("a directory was removed on the strength of a failed lookup")
	}
}

// FR-027, and the reason T009 and T012 belong in one change: the sessions gc expires are the
// same directories the homes link into.
func TestSessionsAgeOutOnTheirOwnClock(t *testing.T) {
	w := newWorld(t)
	now := time.Now()

	fresh := w.session(t, "claude", "task-fresh", 24*time.Hour)
	stale := w.session(t, "claude", "task-stale", 15*24*time.Hour)

	report, err := w.collector(&fakeTasks{}, fakeRuns{}).Sweep(context.Background(), now)
	if err != nil {
		t.Fatalf("Sweep returned an error: %v", err)
	}

	if _, err := os.Stat(fresh); err != nil {
		t.Error("a session used a day ago was removed")
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Error("a session untouched for fifteen days was kept")
	}
	if !contains(report.Removed, stale) {
		t.Errorf("the removal was not reported: %+v", report.Removed)
	}
}

// The coupling that made these tasks one change: a live run's home links into its session store,
// so age alone must not be enough to delete it.
func TestALiveRunsSessionIsNotPulledOutFromUnderIt(t *testing.T) {
	w := newWorld(t)
	now := time.Now()

	busy := w.workDir(t, "task-busy")
	session := w.session(t, "claude", "task-busy", 90*24*time.Hour)

	report, err := w.collector(&fakeTasks{}, fakeRuns{held: map[string]bool{busy: true}}).Sweep(context.Background(), now)
	if err != nil {
		t.Fatalf("Sweep returned an error: %v", err)
	}
	if _, err := os.Stat(session); err != nil {
		t.Fatal("the session of a running task was removed while the agent was using it")
	}
	if reason, kept := reasonFor(report, session); !kept || !strings.Contains(reason, "holding") {
		t.Errorf("the report does not explain why the session was kept: %q", reason)
	}
}

func TestTheRetentionsCanBeChanged(t *testing.T) {
	w := newWorld(t)
	now := time.Now()
	dir := w.workDir(t, "task-1")
	session := w.session(t, "claude", "task-2", 2*time.Hour)

	c := w.collector(&fakeTasks{states: map[string]TaskState{
		"task-1": {Closed: true, LastActivity: now.Add(-2 * time.Hour)},
	}}, fakeRuns{})
	c.WorkDirRetention = time.Hour
	c.SessionRetention = time.Hour

	if _, err := c.Sweep(context.Background(), now); err != nil {
		t.Fatalf("Sweep returned an error: %v", err)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Error("a shortened working-directory retention was ignored")
	}
	if _, err := os.Stat(session); !os.IsNotExist(err) {
		t.Error("a shortened session retention was ignored")
	}
}

func TestTheDefaultsAreTheNumbersTheSpecSettledOn(t *testing.T) {
	if DefaultWorkDirRetention != 24*time.Hour {
		t.Errorf("DefaultWorkDirRetention = %s, want 24h", DefaultWorkDirRetention)
	}
	if DefaultSessionRetention != 14*24*time.Hour {
		t.Errorf("DefaultSessionRetention = %s, want 14 days", DefaultSessionRetention)
	}
	if DefaultSweepInterval != 2*time.Hour {
		t.Errorf("DefaultSweepInterval = %s, want 2h", DefaultSweepInterval)
	}
}

// The collector runs unattended on somebody else's machine and calls RemoveAll. A path assembled
// from a directory name deserves the check.
func TestRemoveRefusesToLeaveItsOwnRoot(t *testing.T) {
	w := newWorld(t)
	c := w.collector(&fakeTasks{}, fakeRuns{})

	outside := filepath.Join(w.root, "not-ours")
	if err := os.MkdirAll(outside, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{outside, w.workRoot, filepath.Join(w.workRoot, "..", "not-ours")} {
		if err := c.remove(w.workRoot, path); err == nil {
			t.Errorf("remove agreed to delete %s, which is outside %s", path, w.workRoot)
		}
	}
	if _, err := os.Stat(outside); err != nil {
		t.Fatal("a directory outside the root was deleted")
	}
}
