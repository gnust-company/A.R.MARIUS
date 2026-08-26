package execenv

import (
	"os"
	"path/filepath"
	"testing"
)

// cookbook is one ordinary skill: a SKILL.md and a file it refers to.
var cookbook = Skill{
	Name: "cookbook",
	Files: map[string]string{
		"SKILL.md":     "# Cookbook\n",
		"ref/stock.md": "Simmer for six hours.\n",
	},
}

func read(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("đọc %s: %v", path, err)
	}
	return string(b)
}

// ── where they land ───────────────────────────────────────────────────────────

func TestSkillsLandWhereTheCLIAlreadyLooks(t *testing.T) {
	work, home := t.TempDir(), t.TempDir()

	dir, err := WriteSkills("claude_code", work, home, []Skill{cookbook})
	if err != nil {
		t.Fatalf("ghi kỹ năng: %v", err)
	}

	if want := filepath.Join(work, ".claude", "skills"); dir != want {
		t.Fatalf("kỹ năng của Claude Code phải nằm ở %s, không phải %s", want, dir)
	}
	if got := read(t, filepath.Join(dir, "cookbook", "SKILL.md")); got != "# Cookbook\n" {
		t.Fatalf("SKILL.md ghi sai nội dung: %q", got)
	}
	if got := read(t, filepath.Join(dir, "cookbook", "ref", "stock.md")); got == "" {
		t.Fatal("tệp trong thư mục con của kỹ năng không được ghi ra")
	}
}

func TestACLIThatKeepsItsSkillsInItsHomeGetsThemThere(t *testing.T) {
	work, home := t.TempDir(), t.TempDir()

	dir, err := WriteSkills("codex", work, home, []Skill{cookbook})
	if err != nil {
		t.Fatalf("ghi kỹ năng: %v", err)
	}

	if want := filepath.Join(home, ".codex", "skills"); dir != want {
		t.Fatalf("kỹ năng của Codex phải nằm trong nhà của nó: %s, không phải %s", want, dir)
	}
	if _, err := os.Stat(filepath.Join(work, ".codex")); !os.IsNotExist(err) {
		t.Fatal("không được đụng vào thư mục làm việc của một CLI cất kỹ năng trong nhà")
	}
}

func TestACLIWhoseSkillsDirectoryIsUnknownIsRefused(t *testing.T) {
	// Gemini CLI is in the wire vocabulary and deliberately not in this table: nobody has
	// verified where it looks. Guessing would write skills where nothing reads them, and a
	// skill that is silently never loaded is worse than a run that refuses to start.
	if _, err := WriteSkills("gemini", t.TempDir(), t.TempDir(), []Skill{cookbook}); err == nil {
		t.Fatal("CLI chưa khai chỗ để kỹ năng mà vẫn ghi ra được")
	}
}

// ── real files, not links (FR-011b) ───────────────────────────────────────────

func TestSkillsAreRealFilesAndNotLinksToAnythingShared(t *testing.T) {
	work, home := t.TempDir(), t.TempDir()

	dir, err := WriteSkills("claude_code", work, home, []Skill{cookbook})
	if err != nil {
		t.Fatalf("ghi kỹ năng: %v", err)
	}

	// A link would be the cheap way to do this, and it is exactly the way that leaks: one
	// workplace serves several agents, so a link into a shared store puts one agent's skills
	// in front of another (FR-007a, FR-007b).
	for _, path := range []string{
		filepath.Join(dir, "cookbook"),
		filepath.Join(dir, "cookbook", "SKILL.md"),
		filepath.Join(dir, "cookbook", "ref", "stock.md"),
	} {
		info, err := os.Lstat(path)
		if err != nil {
			t.Fatalf("không thấy %s: %v", path, err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			t.Fatalf("%s là một liên kết, phải là tệp thật", path)
		}
	}
}

// ── written fresh every run ───────────────────────────────────────────────────

func TestTheSecondRunGetsThisRunsSkillsAndNotTheLastOnes(t *testing.T) {
	// The working directory belongs to the task, not the run (FR-010), so it is still there
	// on the next wake. A skill the patron took away in between would still be sitting in it.
	work, home := t.TempDir(), t.TempDir()
	if _, err := WriteSkills("claude_code", work, home, []Skill{cookbook}); err != nil {
		t.Fatalf("lượt chạy đầu: %v", err)
	}

	dir, err := WriteSkills("claude_code", work, home, []Skill{{
		Name:  "ledger",
		Files: map[string]string{"SKILL.md": "# Ledger\n"},
	}})
	if err != nil {
		t.Fatalf("lượt chạy sau: %v", err)
	}

	if _, err := os.Stat(filepath.Join(dir, "cookbook")); !os.IsNotExist(err) {
		t.Fatal("kỹ năng của lượt trước vẫn còn nằm đó ở lượt sau")
	}
	if _, err := os.Stat(filepath.Join(dir, "ledger", "SKILL.md")); err != nil {
		t.Fatalf("kỹ năng của lượt này không được ghi: %v", err)
	}
}

func TestAFileDroppedFromASkillIsGoneOnTheNextRun(t *testing.T) {
	work, home := t.TempDir(), t.TempDir()
	if _, err := WriteSkills("claude_code", work, home, []Skill{cookbook}); err != nil {
		t.Fatalf("lượt chạy đầu: %v", err)
	}

	dir, err := WriteSkills("claude_code", work, home, []Skill{{
		Name:  "cookbook",
		Files: map[string]string{"SKILL.md": "# Cookbook\n"},
	}})
	if err != nil {
		t.Fatalf("lượt chạy sau: %v", err)
	}

	if _, err := os.Stat(filepath.Join(dir, "cookbook", "ref", "stock.md")); !os.IsNotExist(err) {
		t.Fatal("tệp đã bị gỡ khỏi kỹ năng vẫn còn trên đĩa")
	}
}

func TestNoSkillsAtAllStillLeavesADirectoryToLookIn(t *testing.T) {
	work, home := t.TempDir(), t.TempDir()

	dir, err := WriteSkills("claude_code", work, home, nil)
	if err != nil {
		t.Fatalf("ghi kỹ năng: %v", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("thư mục kỹ năng không tồn tại: %v", err)
	}
	if len(entries) != 0 {
		t.Fatalf("agent không có kỹ năng nào mà thư mục lại có %d mục", len(entries))
	}
}

// ── and nothing written outside it ────────────────────────────────────────────

func TestASkillsDirectoryThatIsALinkIsReplacedAndWhatItPointedAtIsLeftAlone(t *testing.T) {
	// The one thing FR-011b and FR-013a both forbid: writing into the operator's own CLI
	// configuration. That directory belongs to the person, and every agent on the machine
	// shares it.
	work, home := t.TempDir(), t.TempDir()
	operator := t.TempDir()
	if err := os.WriteFile(filepath.Join(operator, "theirs.md"), []byte("mine\n"), 0o600); err != nil {
		t.Fatalf("dựng thư mục của người dùng: %v", err)
	}
	if err := os.MkdirAll(filepath.Join(work, ".claude"), 0o700); err != nil {
		t.Fatalf("dựng thư mục: %v", err)
	}
	if err := os.Symlink(operator, filepath.Join(work, ".claude", "skills")); err != nil {
		t.Fatalf("dựng liên kết: %v", err)
	}

	dir, err := WriteSkills("claude_code", work, home, []Skill{cookbook})
	if err != nil {
		t.Fatalf("ghi kỹ năng: %v", err)
	}

	info, err := os.Lstat(dir)
	if err != nil {
		t.Fatalf("không thấy thư mục kỹ năng: %v", err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		t.Fatal("thư mục kỹ năng vẫn là liên kết — kỹ năng đã ghi vào chỗ của người dùng")
	}
	if _, err := os.Stat(filepath.Join(operator, "theirs.md")); err != nil {
		t.Fatalf("thư mục người dùng trỏ tới bị đụng vào: %v", err)
	}
	if _, err := os.Stat(filepath.Join(operator, "cookbook")); !os.IsNotExist(err) {
		t.Fatal("kỹ năng bị ghi vào thư mục của người dùng")
	}
}

func TestAPathThatLeavesItsOwnSkillIsRefusedBeforeAnythingIsWritten(t *testing.T) {
	for _, escape := range []string{"../../../etc/evil", "/etc/evil", "ref/../../evil", "..", `ref\..\..\evil`} {
		t.Run(escape, func(t *testing.T) {
			work, home := t.TempDir(), t.TempDir()
			// A good layout is already in place: a refused packet must not destroy it either.
			if _, err := WriteSkills("claude_code", work, home, []Skill{cookbook}); err != nil {
				t.Fatalf("lượt chạy đầu: %v", err)
			}

			_, err := WriteSkills("claude_code", work, home, []Skill{{
				Name:  "cookbook",
				Files: map[string]string{"SKILL.md": "# Cookbook\n", escape: "whatever"},
			}})

			if err == nil {
				t.Fatalf("đường dẫn %q thoát ra ngoài mà vẫn ghi được", escape)
			}
			if _, err := os.Stat(filepath.Join(work, ".claude", "skills", "cookbook", "SKILL.md")); err != nil {
				t.Fatalf("gói bị từ chối mà vẫn xoá mất thứ lượt trước để lại: %v", err)
			}
		})
	}
}

func TestASkillWhoseNameIsNotOneDirectoryIsRefused(t *testing.T) {
	for _, name := range []string{"", ".", "..", "a/b", `a\b`} {
		work, home := t.TempDir(), t.TempDir()
		_, err := WriteSkills("claude_code", work, home, []Skill{{
			Name:  name,
			Files: map[string]string{"SKILL.md": "x\n"},
		}})
		if err == nil {
			t.Fatalf("tên kỹ năng %q không phải một thư mục mà vẫn ghi được", name)
		}
	}
}
