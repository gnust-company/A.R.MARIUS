package execenv

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func aWorkDir(t *testing.T, name string) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), name)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	return dir
}

// FR-023: every wake on the same task carries on the same conversation.
func TestTheNextWakeOnTheSameTaskPicksTheThreadUpAgain(t *testing.T) {
	dir := aWorkDir(t, "task-1")
	now := time.Now()
	if err := RememberThread(dir, Thread{
		Handle: "sess-abc", Workplace: "place-1", OpenedAt: now, LastUsedAt: now,
	}); err != nil {
		t.Fatalf("RememberThread returned an error: %v", err)
	}

	thread, verdict, err := RecallThread(dir, now.Add(time.Hour), 0)
	if err != nil {
		t.Fatalf("RecallThread returned an error: %v", err)
	}
	if verdict != ThreadUsable {
		t.Fatalf("the verdict is %s, want %s", verdict, ThreadUsable)
	}
	if thread.Handle != "sess-abc" {
		t.Errorf("the handle came back as %q, want %q", thread.Handle, "sess-abc")
	}
	if thread.Workplace != "place-1" {
		t.Errorf("the workplace came back as %q, want %q", thread.Workplace, "place-1")
	}
}

// FR-024, FR-010b: two tasks are two conversations, even for the same agent on the same machine.
func TestTwoTasksAreTwoConversations(t *testing.T) {
	root := t.TempDir()
	now := time.Now()
	for name, handle := range map[string]string{"task-1": "sess-one", "task-2": "sess-two"} {
		dir := filepath.Join(root, name)
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		if err := RememberThread(dir, Thread{Handle: handle, LastUsedAt: now}); err != nil {
			t.Fatal(err)
		}
	}
	for name, want := range map[string]string{"task-1": "sess-one", "task-2": "sess-two"} {
		thread, verdict, err := RecallThread(filepath.Join(root, name), now, 0)
		if err != nil || verdict != ThreadUsable {
			t.Fatalf("%s: verdict %s, err %v", name, verdict, err)
		}
		if thread.Handle != want {
			t.Errorf("%s carried on %q, want %q — the two tasks share a conversation",
				name, thread.Handle, want)
		}
	}
}

// The first run on a task is not a restart. There is nothing to have lost, and an agent told it
// is starting over on its first turn goes looking for a history that never existed (FR-025).
func TestAFirstRunIsNotARestart(t *testing.T) {
	_, verdict, err := RecallThread(aWorkDir(t, "task-1"), time.Now(), 0)
	if err != nil {
		t.Fatalf("RecallThread returned an error for a task with no history: %v", err)
	}
	if verdict != ThreadNone {
		t.Errorf("the verdict is %s, want %s", verdict, ThreadNone)
	}
}

// FR-027, and the reason this check exists here at all: the sweep runs hours apart and not at all
// while the machine is off, so a wake can land on a thread days past its keeping that no sweep
// has reached. Handing that handle over is the worst answer available — the CLI either refuses
// to start or opens a new conversation silently, and the record claims a thread was carried on.
func TestAThreadPastItsKeepingIsNotOfferedEvenWhenNoSweepHasRun(t *testing.T) {
	dir := aWorkDir(t, "task-1")
	opened := time.Now().Add(-30 * 24 * time.Hour)
	if err := RememberThread(dir, Thread{
		Handle: "sess-old", OpenedAt: opened, LastUsedAt: opened,
	}); err != nil {
		t.Fatal(err)
	}

	_, verdict, err := RecallThread(dir, time.Now(), 14*24*time.Hour)
	if err != nil {
		t.Fatalf("RecallThread returned an error: %v", err)
	}
	if verdict != ThreadExpired {
		t.Errorf("the verdict is %s, want %s", verdict, ThreadExpired)
	}
}

// The keeping counts idleness, not age. A thread worked on daily for a month is not an old
// thread, and expiring it would restart a conversation that is in constant use.
func TestTheKeepingCountsIdlenessNotAge(t *testing.T) {
	dir := aWorkDir(t, "task-1")
	now := time.Now()
	if err := RememberThread(dir, Thread{
		Handle:     "sess-busy",
		OpenedAt:   now.Add(-90 * 24 * time.Hour),
		LastUsedAt: now.Add(-time.Hour),
	}); err != nil {
		t.Fatal(err)
	}
	_, verdict, err := RecallThread(dir, now, 14*24*time.Hour)
	if err != nil {
		t.Fatalf("RecallThread returned an error: %v", err)
	}
	if verdict != ThreadUsable {
		t.Errorf("a thread used an hour ago was judged %s", verdict)
	}
}

// A note this daemon cannot read is not an error travelling up: there is one thing to do about
// it and it is the same thing it does about a note that is missing. What differs is that this one
// is worth telling the agent about, so it is a verdict of its own rather than silence.
func TestANoteThatCannotBeReadIsAVerdictNotAFailure(t *testing.T) {
	dir := aWorkDir(t, "task-1")
	path := filepath.Join(dir, filepath.FromSlash(threadFile))
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("this is not a thread"), 0o600); err != nil {
		t.Fatal(err)
	}

	_, verdict, err := RecallThread(dir, time.Now(), 0)
	if err != nil {
		t.Fatalf("RecallThread returned an error: %v", err)
	}
	if verdict != ThreadUnreadable {
		t.Errorf("the verdict is %s, want %s", verdict, ThreadUnreadable)
	}
}

// A run that produced no handle leaves what was already remembered alone. Overwriting it with
// nothing would throw away a thread the *next* run could still have carried on, over one bad turn.
func TestOneBadTurnDoesNotCostTheConversation(t *testing.T) {
	dir := aWorkDir(t, "task-1")
	now := time.Now()
	if err := RememberThread(dir, Thread{Handle: "sess-kept", LastUsedAt: now}); err != nil {
		t.Fatal(err)
	}
	if err := RememberThread(dir, Thread{Handle: "", LastUsedAt: now}); err != nil {
		t.Fatalf("RememberThread returned an error for a run with nothing to remember: %v", err)
	}
	thread, verdict, err := RecallThread(dir, now, 0)
	if err != nil || verdict != ThreadUsable {
		t.Fatalf("verdict %s, err %v", verdict, err)
	}
	if thread.Handle != "sess-kept" {
		t.Errorf("the handle is now %q — a failed turn erased the conversation", thread.Handle)
	}
}

// Kept where no CLI lists it. The alternative was the store a CLI reads, where a stray entry is
// a project the agent believes it has.
func TestTheNoteIsKeptWhereNoCLILooks(t *testing.T) {
	dir := aWorkDir(t, "task-1")
	if err := RememberThread(dir, Thread{Handle: "sess-abc", LastUsedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.Name() != ".armarius" {
			t.Errorf("the working directory now holds %q, which the agent will see as its own",
				e.Name())
		}
	}
}

// Một handle bị CLI từ chối phải biến mất, không chỉ chờ được ghi đè: mạch nó gọi tên đã không
// còn ở phía CLI, nên giữ nó lại chỉ bảo đảm rằng lần gọi dậy sau đưa đúng cái handle chết ấy.
func TestAThreadCanBeForgotten(t *testing.T) {
	dir := aWorkDir(t, "task-1")
	if err := RememberThread(dir, Thread{Handle: "sess-dead", LastUsedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if err := ForgetThread(dir); err != nil {
		t.Fatalf("ForgetThread trả về lỗi: %v", err)
	}
	_, verdict, err := RecallThread(dir, time.Now(), 0)
	if err != nil {
		t.Fatalf("RecallThread trả về lỗi: %v", err)
	}
	if verdict != ThreadNone {
		t.Errorf("sau khi quên, phán quyết là %s, mong %s", verdict, ThreadNone)
	}
}

// Quên một thứ không có ở đó không phải lỗi — đó chính là trạng thái lời gọi này muốn tới.
func TestForgettingAThreadThatIsNotThereIsNotAFailure(t *testing.T) {
	if err := ForgetThread(aWorkDir(t, "task-1")); err != nil {
		t.Errorf("ForgetThread trả về lỗi cho một đầu việc chưa có mạch nào: %v", err)
	}
}
