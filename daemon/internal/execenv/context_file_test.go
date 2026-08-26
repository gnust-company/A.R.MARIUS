package execenv

import (
	"os"
	"path/filepath"
	"testing"
)

const brief = "You are Marin, the release engineer.\n"

func TestTheBriefLandsInTheFileTheCLIAlreadyOpens(t *testing.T) {
	for cli, want := range map[string]string{"claude_code": "CLAUDE.md", "codex": "AGENTS.md"} {
		work := t.TempDir()

		path, err := WriteContextFile(cli, work, brief)
		if err != nil {
			t.Fatalf("%s: ghi thông điệp: %v", cli, err)
		}

		if path != filepath.Join(work, want) {
			t.Fatalf("%s đọc %s, nhưng thông điệp được ghi vào %s", cli, want, path)
		}
		if got := read(t, path); got != brief {
			t.Fatalf("%s: nội dung sai: %q", cli, got)
		}
	}
}

func TestACLIWhoseContextFileIsUnknownIsRefused(t *testing.T) {
	// Which file Gemini CLI reads has not been verified (T013). Guessing means writing where
	// nothing looks, and an agent that was never told anything reads exactly like one that
	// was told nothing was needed.
	if _, err := WriteContextFile("gemini", t.TempDir(), brief); err == nil {
		t.Fatal("CLI chưa khai tệp bối cảnh mà vẫn ghi ra được")
	}
}

func TestAnEmptyBriefIsRefusedRatherThanWritten(t *testing.T) {
	work := t.TempDir()

	if _, err := WriteContextFile("claude_code", work, ""); err == nil {
		t.Fatal("thông điệp rỗng vẫn được ghi ra tệp")
	}
	if _, err := os.Stat(filepath.Join(work, "CLAUDE.md")); !os.IsNotExist(err) {
		t.Fatal("từ chối rồi mà vẫn để lại một tệp rỗng — đọc y hệt một tệp đúng")
	}
}

func TestTheSecondRunOnTheSameTaskReadsThisRunsBrief(t *testing.T) {
	// The working directory is the task's, not the run's (FR-010), so last wake's brief is
	// still lying there when the next one starts.
	work := t.TempDir()
	if _, err := WriteContextFile("claude_code", work, "the first wake\n"); err != nil {
		t.Fatalf("lượt chạy đầu: %v", err)
	}

	path, err := WriteContextFile("claude_code", work, "the second wake\n")
	if err != nil {
		t.Fatalf("lượt chạy sau: %v", err)
	}

	if got := read(t, path); got != "the second wake\n" {
		t.Fatalf("agent đọc lại thông điệp của lượt trước: %q", got)
	}
}

func TestALinkLeftWhereTheBriefGoesIsRemovedRatherThanFollowed(t *testing.T) {
	work, elsewhere := t.TempDir(), t.TempDir()
	theirs := filepath.Join(elsewhere, "notes.md")
	if err := os.WriteFile(theirs, []byte("theirs\n"), 0o600); err != nil {
		t.Fatalf("dựng tệp của người dùng: %v", err)
	}
	if err := os.Symlink(theirs, filepath.Join(work, "CLAUDE.md")); err != nil {
		t.Fatalf("dựng liên kết: %v", err)
	}

	path, err := WriteContextFile("claude_code", work, brief)
	if err != nil {
		t.Fatalf("ghi thông điệp: %v", err)
	}

	info, err := os.Lstat(path)
	if err != nil {
		t.Fatalf("không thấy tệp bối cảnh: %v", err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		t.Fatal("tệp bối cảnh vẫn là liên kết")
	}
	if got := read(t, theirs); got != "theirs\n" {
		t.Fatalf("ghi đè lên tệp mà liên kết trỏ tới: %q", got)
	}
}

func TestWritingTheBriefNeedsAWorkingDirectory(t *testing.T) {
	if _, err := WriteContextFile("claude_code", "", brief); err == nil {
		t.Fatal("không có thư mục làm việc mà vẫn ghi được")
	}
}
