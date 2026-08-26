package execenv

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestEveryRunOfOneTaskComesBackToTheSameDirectory(t *testing.T) {
	// FR-010. The session lives in the directory it was opened in, so a second wake that got a
	// new directory would either find no session or find one whose remembered paths point at
	// nothing (FR-010a).
	root := t.TempDir()

	first, err := WorkDir(root, "task-a")
	if err != nil {
		t.Fatalf("lượt chạy đầu: %v", err)
	}
	second, err := WorkDir(root, "task-a")
	if err != nil {
		t.Fatalf("lượt chạy sau: %v", err)
	}

	if first != second {
		t.Fatalf("hai lượt chạy của cùng một đầu việc nhận hai chỗ làm việc khác nhau: %s và %s", first, second)
	}
}

func TestTwoTasksNeverShareADirectory(t *testing.T) {
	// FR-010b, and it holds even when the same agent works on both.
	root := t.TempDir()

	one, err := WorkDir(root, "task-a")
	if err != nil {
		t.Fatalf("đầu việc thứ nhất: %v", err)
	}
	two, err := WorkDir(root, "task-b")
	if err != nil {
		t.Fatalf("đầu việc thứ hai: %v", err)
	}

	if one == two {
		t.Fatalf("hai đầu việc dùng chung một thư mục làm việc: %s", one)
	}
}

func TestWhatTheLastRunLeftIsStillThere(t *testing.T) {
	// The directory belongs to the task, not to the run. Emptying it here would throw away the
	// half-finished work the next run is meant to carry on from — and the two things that must
	// not survive a run, the brief and the skills, are each rewritten by the code that owns them.
	root := t.TempDir()
	dir, err := WorkDir(root, "task-a")
	if err != nil {
		t.Fatalf("lượt chạy đầu: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "notes.md"), []byte("half done"), 0o600); err != nil {
		t.Fatalf("viết dở dang: %v", err)
	}

	if _, err := WorkDir(root, "task-a"); err != nil {
		t.Fatalf("lượt chạy sau: %v", err)
	}

	if got := read(t, filepath.Join(dir, "notes.md")); got != "half done" {
		t.Fatalf("việc dở dang của lượt trước bị dọn mất: %q", got)
	}
}

func TestATaskNameThatClimbsOutIsRefused(t *testing.T) {
	// The task id arrives from the server and becomes a path component on somebody else's
	// machine.
	root := t.TempDir()

	for _, name := range []string{"", ".", "..", "../escape", "a/b", `a\b`, "C:evil"} {
		if _, err := WorkDir(root, name); err == nil {
			t.Fatalf("tên đầu việc %q vẫn dựng được thư mục", name)
		}
	}
}

func TestADirectoryThatIsReallyALinkIsRefused(t *testing.T) {
	// A link here would send the brief, the skills and everything the agent writes wherever it
	// points — which on this machine could be the operator's own home.
	root := t.TempDir()
	elsewhere := t.TempDir()
	if err := os.Symlink(elsewhere, filepath.Join(root, "task-a")); err != nil {
		t.Skipf("máy này không tạo được liên kết: %v", err)
	}

	if _, err := WorkDir(root, "task-a"); err == nil {
		t.Fatal("thư mục làm việc là một liên kết mà vẫn được nhận")
	}
}

func TestSomethingThatIsNotADirectoryIsRefused(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "task-a"), []byte("not a directory"), 0o600); err != nil {
		t.Fatalf("dựng tệp chắn chỗ: %v", err)
	}

	if _, err := WorkDir(root, "task-a"); err == nil {
		t.Fatal("một tệp đứng chỗ thư mục làm việc mà vẫn được nhận")
	}
}

func TestTheDirectoryIsTheOperatorsAlone(t *testing.T) {
	root := t.TempDir()

	dir, err := WorkDir(root, "task-a")
	if err != nil {
		t.Fatalf("dựng thư mục làm việc: %v", err)
	}

	info, err := os.Stat(dir)
	if err != nil {
		t.Fatalf("soi thư mục làm việc: %v", err)
	}
	if perm := info.Mode().Perm(); perm != 0o700 {
		t.Fatalf("thư mục làm việc mở cho người khác đọc: %o", perm)
	}
}

func TestTheRunsHomeSitsInsideTheTasksDirectory(t *testing.T) {
	// So that a daemon killed mid-run leaves nothing stranded: the sweep already asks whether
	// anyone is holding this task and whether it has been quiet long enough (FR-021).
	root := t.TempDir()
	dir, err := WorkDir(root, "task-a")
	if err != nil {
		t.Fatalf("dựng thư mục làm việc: %v", err)
	}

	home, err := RunHome(dir, "run-1")
	if err != nil {
		t.Fatalf("chỗ nhà giả của lượt chạy: %v", err)
	}

	if !strings.HasPrefix(home, dir+string(os.PathSeparator)) {
		t.Fatalf("nhà giả của lượt chạy nằm ngoài thư mục làm việc: %s", home)
	}
}

func TestTwoRunsOfOneTaskGetTheirOwnHomes(t *testing.T) {
	dir := t.TempDir()

	first, err := RunHome(dir, "run-1")
	if err != nil {
		t.Fatalf("lượt chạy đầu: %v", err)
	}
	second, err := RunHome(dir, "run-2")
	if err != nil {
		t.Fatalf("lượt chạy sau: %v", err)
	}

	if first == second {
		t.Fatalf("hai lượt chạy dùng chung một nhà giả: %s", first)
	}
}

func TestARunNameThatClimbsOutIsRefused(t *testing.T) {
	for _, name := range []string{"", "..", "a/b"} {
		if _, err := RunHome(t.TempDir(), name); err == nil {
			t.Fatalf("tên lượt chạy %q vẫn dựng được nhà giả", name)
		}
	}
}
