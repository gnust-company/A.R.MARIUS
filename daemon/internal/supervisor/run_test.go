package supervisor

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
	armruntime "github.com/gnust-company/armarius-daemon/internal/runtime"
)

// ── a server that remembers what it was told ─────────────────────────────────

type ledger struct {
	mu sync.Mutex

	// what it will do
	startMine  bool
	startErr   error
	recordErr  error
	finishErr  error
	notOursOn  int // the nth Record call comes back as *not yours* (0 = never)
	recordSeen int

	// what it saw
	started  []string
	sessions []string
	events   []Recorded
	finished []Conclusion
}

func aLedger() *ledger { return &ledger{startMine: true} }

func (l *ledger) Start(_ context.Context, runID, session string) (bool, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.started = append(l.started, runID)
	l.sessions = append(l.sessions, session)
	return l.startMine, l.startErr
}

func (l *ledger) Record(_ context.Context, _ string, events []Recorded) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.recordSeen++
	if l.notOursOn > 0 && l.recordSeen >= l.notOursOn {
		return ErrRunNotOurs
	}
	if l.recordErr != nil {
		return l.recordErr
	}
	l.events = append(l.events, events...)
	return nil
}

func (l *ledger) Finish(_ context.Context, _ string, done Conclusion) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.finished = append(l.finished, done)
	return l.finishErr
}

func (l *ledger) told() []Recorded {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]Recorded(nil), l.events...)
}

func (l *ledger) ending() (Conclusion, bool) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if len(l.finished) == 0 {
		return Conclusion{}, false
	}
	return l.finished[len(l.finished)-1], true
}

// ── an agent runtime that does what a test needs ─────────────────────────────

type scripted struct {
	says    []armruntime.Event
	fails   error
	session string
	refused bool
	usage   map[string]any
	waitFor func(ctx context.Context)
	saw     armruntime.Request
	ran     bool
}

func (s *scripted) Run(
	ctx context.Context, req armruntime.Request, emit armruntime.Emit,
) (armruntime.Outcome, error) {
	s.saw, s.ran = req, true
	for _, event := range s.says {
		emit(event)
	}
	if s.waitFor != nil {
		s.waitFor(ctx)
	}
	return armruntime.Outcome{
		Session: s.session, SessionRefused: s.refused, Usage: s.usage,
	}, s.fails
}

// ── the world one run happens in ─────────────────────────────────────────────

type world struct {
	t        *testing.T
	root     string
	callback string
	ledger   *ledger
	engine   *scripted
	place    Workplace
	held     *Runs
	report   []error
	mu       sync.Mutex
}

func aWorld(t *testing.T) *world {
	t.Helper()
	root := t.TempDir()
	// A stand-in for the callback program. Setting up a run refuses without one (FR-013a), and
	// rightly: an agent whose skill sheet names a command that is not there fails on every call
	// it makes, silently. What it does when run is nothing this package tests — the point here
	// is only that a run gets one.
	callback := filepath.Join(root, "armarius")
	if err := os.WriteFile(callback, []byte("#!/bin/sh\nexit 0\n"), 0o700); err != nil {
		t.Fatalf("laying down a callback program to hand runs: %v", err)
	}
	return &world{
		t:        t,
		root:     root,
		callback: callback,
		ledger:   aLedger(),
		engine:   &scripted{},
		place:    Workplace{CLI: "claude_code", Family: "one_shot", Binary: "/bin/true"},
		held:     &Runs{},
	}
}

func (w *world) options() RunOptions {
	return RunOptions{
		WorkRoot:        filepath.Join(w.root, "work"),
		StateRoot:       filepath.Join(w.root, "stores"),
		OperatorHome:    filepath.Join(w.root, "home"),
		Server:          "https://armarius.example",
		DaemonToken:     "armr_machine_secret",
		CallbackProgram: w.callback,
		Workplace: func(id string) (Workplace, bool) {
			if id != "wp-1" {
				return Workplace{}, false
			}
			return w.place, true
		},
		Runtime: func(family string) (armruntime.Runtime, bool) {
			if family != w.place.Family {
				return nil, false
			}
			return w.engine, true
		},
		Ledger: w.ledger,
		Runs:   w.held,
		Report: func(err error) {
			w.mu.Lock()
			defer w.mu.Unlock()
			w.report = append(w.report, err)
		},
	}
}

func (w *world) grant() Grant {
	return Grant{
		RunID:       "run-1",
		TaskID:      "task-1",
		ProjectID:   "project-1",
		WorkplaceID: "wp-1",
		RunToken:    "armr_run_thisone",
		Prompt:      "Your instructions: be Marin.\n",
		FirstSeq:    7,
		Expires:     time.Now().Add(2 * time.Minute),
	}
}

func (w *world) complaints() []error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return append([]error(nil), w.report...)
}

func of(events []Recorded, kind string) []Recorded {
	var found []Recorded
	for _, event := range events {
		if event.Type == kind {
			found = append(found, event)
		}
	}
	return found
}

// ── the run, end to end ──────────────────────────────────────────────────────

func TestOneRunLaysOutItsWorkSaysItStartedAndSaysHowItEnded(t *testing.T) {
	w := aWorld(t)
	w.engine.says = []armruntime.Event{
		{Type: armruntime.EventAssistantMessage, Payload: map[string]any{"text": "on it"}},
	}
	w.engine.usage = map[string]any{"input_tokens": 12}

	w.options().Do(context.Background(), w.grant())

	if !w.engine.ran {
		t.Fatal("không có agent nào được bật lên")
	}
	if len(w.ledger.started) != 1 {
		t.Fatalf("số lần báo đã bật agent: %d", len(w.ledger.started))
	}
	said := of(w.ledger.told(), armruntime.EventAssistantMessage)
	if len(said) != 1 || said[0].Payload["text"] != "on it" {
		t.Fatalf("chữ agent nói không tới nơi: %v", w.ledger.told())
	}
	done, closed := w.ledger.ending()
	if !closed || done.Status != Completed {
		t.Fatalf("lượt chạy khép lại thế nào: %+v", done)
	}
	if done.Usage["input_tokens"] != 12 {
		t.Fatalf("phần chi phí CLI khai không đi kèm: %v", done.Usage)
	}
}

func TestTheAgentIsGivenTheTasksOwnDirectoryTheMessageAndItsOwnToken(t *testing.T) {
	w := aWorld(t)

	w.options().Do(context.Background(), w.grant())

	work := filepath.Join(w.root, "work", "task-1")
	if w.engine.saw.WorkDir != work {
		t.Fatalf("agent chạy ở %s, không phải thư mục của đầu việc", w.engine.saw.WorkDir)
	}
	brief, err := os.ReadFile(filepath.Join(work, "CLAUDE.md"))
	if err != nil || !strings.Contains(string(brief), "be Marin") {
		t.Fatalf("tệp bối cảnh: %v %q", err, brief)
	}
	if w.engine.saw.Message != "Your instructions: be Marin.\n" {
		t.Fatalf("thông điệp gửi agent bị đổi: %q", w.engine.saw.Message)
	}
	if !lookup(w.engine.saw.Env, "ARMARIUS_RUN_TOKEN", "armr_run_thisone") {
		t.Fatalf("token của lượt chạy không có trong môi trường: %v", w.engine.saw.Env)
	}
	for _, entry := range w.engine.saw.Env {
		if strings.Contains(entry, "armr_machine_secret") {
			t.Fatalf("token của cả cái máy lọt vào tay agent: %q", entry)
		}
	}
}

func TestTheAgentIsToldWhatItsRunIsAboutSoItsCommandsExist(t *testing.T) {
	// Không phải chuyện trang trí. Hai mã này là thứ quyết **bộ lệnh** agent cầm trong tay
	// (FR-013d): thiếu chúng thì mọi lượt chạy — kể cả một lượt chạy đầu việc bình thường —
	// đọc thành "không nói về cái gì cả", và cả nhóm lệnh của đầu việc lẫn của dự án biến mất
	// mà không một dòng lỗi nào.
	//
	// Bài này canh đúng **chỗ nối**, không canh `Environ`: cả hai đầu đều từng đúng riêng nó,
	// và chỗ rỗng nằm ở giữa — nơi thật sự dựng môi trường cho agent quên không truyền vào.
	w := aWorld(t)

	w.options().Do(context.Background(), w.grant())

	if !lookup(w.engine.saw.Env, "ARMARIUS_TASK_ID", "task-1") {
		t.Fatalf("agent không được cho biết nó đang làm đầu việc nào: %v", w.engine.saw.Env)
	}
	if !lookup(w.engine.saw.Env, "ARMARIUS_PROJECT_ID", "project-1") {
		t.Fatalf("agent không được cho biết nó đang ở dự án nào: %v", w.engine.saw.Env)
	}
}

func TestTheCallbackProgramIsPutInTheAgentsHandAtTheRealCallSite(t *testing.T) {
	// The lesson from the last one of these, applied before it costs anything: `PlaceTools` and
	// `Environ` can each be perfectly right while the run that actually starts an agent never
	// calls them. Take the two lines out of `prepare` and this is the test that goes red.
	//
	// What it asserts is the agent's own view: the program is on the disk it works from, its
	// directory is at the **front** of the search path it was started with, and the tool face
	// it can load names a file that exists.
	w := aWorld(t)

	w.options().Do(context.Background(), w.grant())

	workDir := filepath.Join(w.root, "work", "task-1")
	placed := filepath.Join(workDir, ".armarius", "bin", "armarius")
	if _, err := os.Lstat(placed); err != nil {
		t.Fatalf("agent không có thứ để gọi ngược: %v", err)
	}

	path, found := valueIn(w.engine.saw.Env, "PATH")
	if !found {
		t.Fatal("agent được khởi chạy mà không có đường tìm lệnh nào")
	}
	if first, _, _ := strings.Cut(path, string(os.PathListSeparator)); first != filepath.Dir(placed) {
		t.Fatalf("thư mục của lượt chạy không đứng đầu đường tìm lệnh: %q", path)
	}
	if got, _ := valueIn(w.engine.saw.Env, "ARMARIUS_WORKDIR"); got != workDir {
		t.Fatalf("agent không được cho biết nó làm việc ở đâu: %q", got)
	}

	if w.engine.saw.ToolConfig == "" {
		t.Fatal("claude_code nạp được công cụ mà không được khai gì")
	}
	if _, err := os.Stat(w.engine.saw.ToolConfig); err != nil {
		t.Fatalf("lời khai công cụ trỏ vào một tệp không có: %v", err)
	}
	if len(w.engine.saw.ToolServers) != 1 || w.engine.saw.ToolServers[0].Command != placed {
		t.Fatalf("dạng khai trong bắt tay không trỏ về chương trình vừa đặt: %+v", w.engine.saw.ToolServers)
	}
}

func TestWhatSetupPutInTheWorkingDirectoryIsNotCountedAsTheAgentsWork(t *testing.T) {
	// FR-020a: the agent asks what it changed so it knows what to publish. A brief and a skills
	// directory listed among its files is a list it cannot act on — and the only side that
	// knows for certain which is which is the side that put them there.
	w := aWorld(t)

	w.options().Do(context.Background(), w.grant())

	workDir := filepath.Join(w.root, "work", "task-1")
	if err := os.WriteFile(filepath.Join(workDir, "report.md"), []byte("mine"), 0o600); err != nil {
		t.Fatalf("viết tệp của agent: %v", err)
	}

	list, err := execenv.Changes(workDir, 0)
	if err != nil {
		t.Fatalf("hỏi thư mục làm việc có gì: %v", err)
	}
	if list.Total != 1 || len(list.Files) != 1 || list.Files[0].Path != "report.md" {
		t.Fatalf("agent nhìn thấy cả thứ nó được phát: %+v", list.Files)
	}
}

func valueIn(env []string, name string) (string, bool) {
	for _, entry := range env {
		if got, value, ok := strings.Cut(entry, "="); ok && got == name {
			return value, true
		}
	}
	return "", false
}

func lookup(env []string, name, want string) bool {
	for _, entry := range env {
		if entry == name+"="+want {
			return true
		}
	}
	return false
}

func TestTheRunsHomeIsTakenAwayWhenTheRunEnds(t *testing.T) {
	w := aWorld(t)

	w.options().Do(context.Background(), w.grant())

	home := filepath.Join(w.root, "work", "task-1", ".armarius", "home", "run-1")
	if _, err := os.Lstat(home); !os.IsNotExist(err) {
		t.Fatalf("nhà của lượt chạy còn nằm lại ở %s: %v", home, err)
	}
	// And the working directory itself is not touched: it belongs to the task, not the run.
	if _, err := os.Stat(filepath.Join(w.root, "work", "task-1")); err != nil {
		t.Fatalf("thư mục của đầu việc bị dọn theo lượt chạy: %v", err)
	}
}

func TestEventsTravelWhileTheAgentIsStillWorking(t *testing.T) {
	// FR-015 in one test: the record has to move before the run is over, not afterwards.
	w := aWorld(t)
	w.engine.says = []armruntime.Event{
		{Type: armruntime.EventAssistantMessage, Payload: map[string]any{"text": "still going"}},
	}
	arrived := make(chan struct{})
	w.engine.waitFor = func(ctx context.Context) {
		select {
		case <-arrived:
		case <-ctx.Done():
		case <-time.After(5 * time.Second):
		}
	}

	done := make(chan struct{})
	go func() {
		defer close(done)
		w.options().Do(context.Background(), w.grant())
	}()

	deadline := time.After(5 * time.Second)
	for {
		if len(w.ledger.told()) > 0 {
			close(arrived)
			break
		}
		select {
		case <-deadline:
			t.Fatal("chưa có sự kiện nào tới server trong lúc agent còn đang chạy")
		case <-time.After(5 * time.Millisecond):
		}
	}
	<-done
}

func TestEventsAreNumberedFromWhereTheServerSaidTheyStart(t *testing.T) {
	// A run can be handed out more than once, so the numbering cannot start at one every
	// time: the message this hand-out was given is already written under a number of its own
	// (FR-045).
	w := aWorld(t)
	w.engine.says = []armruntime.Event{
		{Type: armruntime.EventAssistantMessage, Payload: map[string]any{"text": "one"}},
		{Type: armruntime.EventAssistantMessage, Payload: map[string]any{"text": "two"}},
	}

	w.options().Do(context.Background(), w.grant())

	told := w.ledger.told()
	if len(told) != 2 || told[0].Seq != 7 || told[1].Seq != 8 {
		t.Fatalf("đánh số sự kiện: %+v", told)
	}
}

func TestARunTheServerHasTakenBackIsStopped(t *testing.T) {
	// FR-059: every later write would be refused for the same reason, so carrying on is an
	// agent producing a record nobody will keep.
	w := aWorld(t)
	w.ledger.notOursOn = 1
	w.engine.says = []armruntime.Event{
		{Type: armruntime.EventAssistantMessage, Payload: map[string]any{"text": "hello"}},
	}
	stopped := make(chan struct{})
	w.engine.waitFor = func(ctx context.Context) {
		select {
		case <-ctx.Done():
			close(stopped)
		case <-time.After(5 * time.Second):
			t.Error("lượt chạy không bị cắt dù server nói nó không còn của máy này")
			close(stopped)
		}
	}

	w.options().Do(context.Background(), w.grant())
	<-stopped
}

func TestAnAgentThatGoesQuietIsCutAndSaidToHaveTimedOut(t *testing.T) {
	w := aWorld(t)
	options := w.options()
	// A threshold this test can outlast, rather than the ten real minutes (FR-031).
	options.Watchdog, _ = NewWatchdog(40*time.Millisecond, nil)
	w.engine.waitFor = func(ctx context.Context) { <-ctx.Done() }

	options.Do(context.Background(), w.grant())

	done, closed := w.ledger.ending()
	if !closed || done.Status != TimedOut {
		t.Fatalf("agent im bặt mà lượt chạy khép lại là %+v", done)
	}
	if len(of(w.ledger.told(), armruntime.EventRunError)) == 0 {
		t.Fatal("cắt vì im lặng mà không để lại dấu nào trong bản ghi")
	}
}

func TestARunThatCannotBeSetUpSaysWhyAndIsNotClosed(t *testing.T) {
	// FR-057: *nobody took this* and *something took it and died getting ready* are two
	// different failures. The second one is answered by the hold running out, so closing the
	// run here would spend a recovery attempt on a machine that has not tried once.
	w := aWorld(t)
	grant := w.grant()
	grant.WorkplaceID = "wp-gone"

	w.options().Do(context.Background(), grant)

	if _, closed := w.ledger.ending(); closed {
		t.Fatal("dựng hỏng mà vẫn khép lượt chạy — hạn giữ mới là đường trả nó về kệ")
	}
	failed := of(w.ledger.told(), armruntime.EventRunError)
	if len(failed) != 1 || failed[0].Payload["code"] != "setup_failed" {
		t.Fatalf("không nói được vì sao không dựng nổi: %v", w.ledger.told())
	}
	if len(w.complaints()) == 0 {
		t.Fatal("hỏng mà máy này không kêu một câu nào")
	}
}

func TestARunTheHoldRanOutOnStartsNothing(t *testing.T) {
	w := aWorld(t)
	w.ledger.startMine = false

	w.options().Do(context.Background(), w.grant())

	if w.engine.ran {
		t.Fatal("hạn giữ đã trôi mà vẫn bật agent lên")
	}
	if _, closed := w.ledger.ending(); closed {
		t.Fatal("khép một lượt chạy không còn thuộc máy này")
	}
}

func TestAnAgentThatDiesIsReportedAsFailedRatherThanFinished(t *testing.T) {
	w := aWorld(t)
	w.engine.fails = errors.New("claude ended badly: exit status 1")

	w.options().Do(context.Background(), w.grant())

	done, closed := w.ledger.ending()
	if !closed || done.Status != Failed {
		t.Fatalf("agent chết mà lượt chạy khép lại là %+v", done)
	}
	if !strings.Contains(done.Error, "exit status 1") {
		t.Fatalf("lý do hỏng không đi cùng: %q", done.Error)
	}
}

func TestTheRunIsClosedEvenWhenTheDaemonIsBeingStopped(t *testing.T) {
	// The call that closes a run is the one that revokes its token and puts the task back in
	// motion (FR-014b, FR-030a), so it cannot be made on the context that has just ended.
	w := aWorld(t)
	ctx, stop := context.WithCancel(context.Background())
	w.engine.waitFor = func(inner context.Context) {
		stop()
		<-inner.Done()
	}

	w.options().Do(ctx, w.grant())

	if _, closed := w.ledger.ending(); !closed {
		t.Fatal("daemon dừng giữa chừng và lượt chạy không được khép lại")
	}
}

// ── what this machine is holding ─────────────────────────────────────────────

func TestAHeldRunFillsASlotAndKeepsTheSweepOffItsDirectory(t *testing.T) {
	w := aWorld(t)
	inside := make(chan struct{})
	w.engine.waitFor = func(ctx context.Context) {
		close(inside)
		<-ctx.Done()
	}

	go w.options().Do(context.Background(), w.grant())
	<-inside

	if w.held.Count() != 1 {
		t.Fatalf("máy đang giữ %d lượt chạy", w.held.Count())
	}
	if ids := w.held.IDs(); len(ids) != 1 || ids[0] != "run-1" {
		t.Fatalf("máy khai đang chạy: %v", ids)
	}
	if !w.held.Holding(filepath.Join(w.root, "work", "task-1")) {
		t.Fatal("vòng quét được phép dọn một thư mục đang có người làm")
	}
	if w.held.Holding(filepath.Join(w.root, "work", "task-2")) {
		t.Fatal("giữ một đầu việc mà khai giữ cả đầu việc khác")
	}
	if !w.held.Cancel("run-1") {
		t.Fatal("không cắt được lượt chạy máy đang giữ")
	}
}

func TestAFinishedRunFreesItsSlot(t *testing.T) {
	w := aWorld(t)

	w.options().Do(context.Background(), w.grant())

	if w.held.Count() != 0 {
		t.Fatalf("lượt chạy xong rồi mà vẫn chiếm chỗ: %v", w.held.IDs())
	}
	if w.held.Holding(filepath.Join(w.root, "work", "task-1")) {
		t.Fatal("lượt chạy xong rồi mà vòng quét vẫn bị chặn khỏi thư mục")
	}
}

func TestCancellingARunNobodyHoldsChangesNothing(t *testing.T) {
	held := &Runs{}
	if held.Cancel("run-nobody-has") {
		t.Fatal("cắt được một lượt chạy máy này không hề giữ")
	}
}

// ── the whole tree goes, not only the CLI ────────────────────────────────────

func TestWhatTheCLIStartedGoesWhenTheCLIDoes(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("bài này dựa vào nhóm tiến trình của Unix")
	}
	// An agent CLI is a program that starts programs. A grandchild left behind holds this
	// run's working directory and an environment with this run's token in it (FR-014b,
	// FR-021), and it is also what makes `Wait` never return.
	w := aWorld(t)
	marker := filepath.Join(w.root, "still-alive")
	w.place.Binary = shellScript(t, w.root, `
sh -c 'while true; do : > `+marker+`; sleep 0.05; done' &
sleep 0.2
`)
	w.place.Family = "one_shot"
	options := w.options()
	options.Runtime = func(string) (armruntime.Runtime, bool) { return armruntime.OneShot{}, true }

	options.Do(context.Background(), w.grant())

	// Give anything left behind time to prove it is still there.
	_ = os.Remove(marker)
	time.Sleep(300 * time.Millisecond)
	if _, err := os.Stat(marker); err == nil {
		t.Fatal("tiến trình cháu của agent còn sống sau khi lượt chạy kết thúc")
	}
}

func shellScript(t *testing.T, dir, body string) string {
	t.Helper()
	path := filepath.Join(dir, "fake-cli")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body), 0o700); err != nil { //nolint:gosec // a test's own scratch directory
		t.Fatalf("viết CLI giả: %v", err)
	}
	return path
}

// ── carrying one task's conversation from one wake to the next ───────────────

// FR-023: the second wake on a task carries on the conversation the first one opened. Nothing
// above this machine keeps it — the handle is the CLI's own word for the thread, and it is
// written down here beside the work it is about.
func TestTheSecondWakeOnATaskCarriesOnTheFirstOnesConversation(t *testing.T) {
	w := aWorld(t)
	w.engine.session = "sess-first"
	w.options().Do(context.Background(), w.grant())

	if w.engine.saw.Session != "" {
		t.Errorf("the first run on a task was handed the handle %q", w.engine.saw.Session)
	}
	if w.engine.saw.Restart != nil {
		t.Errorf("the first turn on a task was announced as a restart: %v", w.engine.saw.Restart.Code)
	}

	second := w.grant()
	second.RunID = "run-2"
	w.options().Do(context.Background(), second)

	if w.engine.saw.Session != "sess-first" {
		t.Errorf("the second run was handed %q, want the conversation the first one opened",
			w.engine.saw.Session)
	}
	if w.engine.saw.Restart != nil {
		t.Errorf("a conversation that was carried on was announced as a restart: %v",
			w.engine.saw.Restart.Code)
	}
	if last := w.ledger.sessions[len(w.ledger.sessions)-1]; last != "sess-first" {
		t.Errorf("the server was told the run carried on %q, want %q", last, "sess-first")
	}
}

// FR-024, FR-010b: two tasks are two conversations, on the same machine, at the same workplace,
// with the same agent.
func TestTwoTasksNeverShareAConversation(t *testing.T) {
	w := aWorld(t)
	w.engine.session = "sess-one"
	w.options().Do(context.Background(), w.grant())

	other := w.grant()
	other.RunID, other.TaskID = "run-2", "task-2"
	w.engine.session = "sess-two"
	w.options().Do(context.Background(), other)
	if w.engine.saw.Session != "" {
		t.Errorf("a different task was handed %q — the two share a conversation", w.engine.saw.Session)
	}

	back := w.grant()
	back.RunID = "run-3"
	w.options().Do(context.Background(), back)
	if w.engine.saw.Session != "sess-one" {
		t.Errorf("the first task came back to %q, want %q", w.engine.saw.Session, "sess-one")
	}
}

// FR-027: past its keeping, the thread is not handed over — and the agent is told, in the same
// turn, that it is starting again (FR-025).
func TestAConversationPastItsKeepingIsRestartedWithAWordToTheAgent(t *testing.T) {
	w := aWorld(t)
	w.engine.session = "sess-old"
	opts := w.options()
	opts.Now = func() time.Time { return time.Now().Add(-30 * 24 * time.Hour) }
	opts.Do(context.Background(), w.grant())

	second := w.grant()
	second.RunID = "run-2"
	fresh := w.options()
	fresh.SessionRetention = 14 * 24 * time.Hour
	fresh.Do(context.Background(), second)

	if w.engine.saw.Session != "" {
		t.Errorf("a thread a month idle was handed over: %q", w.engine.saw.Session)
	}
	if w.engine.saw.Restart == nil || w.engine.saw.Restart.Code != armruntime.RestartExpired {
		t.Fatalf("the restart is %v, want %s", w.engine.saw.Restart, armruntime.RestartExpired)
	}
}

// FR-026: a thread opened at a workplace that no longer serves this agent is not carried on, and
// not quietly pretended to be either.
func TestAThreadFromARebuiltWorkplaceStartsAgainAndSaysSo(t *testing.T) {
	w := aWorld(t)
	w.engine.session = "sess-old"
	w.options().Do(context.Background(), w.grant())

	// The machine was rebuilt: the CLI here registered again and came back a different
	// workplace. The task is the same and its directory is still on disk.
	w.place = Workplace{CLI: "claude_code", Family: "one_shot", Binary: "/bin/true"}
	rebuilt := w.grant()
	rebuilt.RunID, rebuilt.WorkplaceID = "run-2", "wp-2"
	opts := w.options()
	opts.Workplace = func(string) (Workplace, bool) { return w.place, true }
	opts.Do(context.Background(), rebuilt)

	if w.engine.saw.Session != "" {
		t.Errorf("a thread from the old workplace was handed over: %q", w.engine.saw.Session)
	}
	if w.engine.saw.Restart == nil ||
		w.engine.saw.Restart.Code != armruntime.RestartWorkplaceRebuilt {
		t.Fatalf("the restart is %v, want %s",
			w.engine.saw.Restart, armruntime.RestartWorkplaceRebuilt)
	}
}

// A CLI that names no conversation leaves nothing behind, and the next wake is a first wake
// rather than one carrying on a handle nobody has.
func TestACLIThatNamesNoConversationLeavesNothingToCarryOn(t *testing.T) {
	w := aWorld(t)
	w.options().Do(context.Background(), w.grant())

	second := w.grant()
	second.RunID = "run-2"
	w.options().Do(context.Background(), second)

	if w.engine.saw.Session != "" {
		t.Errorf("the second run was handed %q out of nowhere", w.engine.saw.Session)
	}
	if w.engine.saw.Restart != nil {
		t.Errorf("nothing was ever remembered, and the agent was told it lost something: %v",
			w.engine.saw.Restart.Code)
	}
}

// The machine tells the server which conversation the run ended holding, and it is the one the
// CLI ended with rather than the one it was handed: a run whose handle would not load opens a new
// conversation and finishes on that (FR-023, FR-025).
func TestTheServerIsToldWhichConversationTheRunEndedHolding(t *testing.T) {
	w := aWorld(t)
	w.engine.session = "sess-ended-on-this"
	w.options().Do(context.Background(), w.grant())

	done, ended := w.ledger.ending()
	if !ended {
		t.Fatal("the run was never closed")
	}
	if done.Session != "sess-ended-on-this" {
		t.Errorf("the server was told the run ended on %q, want %q",
			done.Session, "sess-ended-on-this")
	}
}

// Một handle bị CLI từ chối phải **biến mất** khỏi máy, không chỉ được thay thế.
//
// Thay thế là đủ khi lượt thử lại chạy được. Khi nó cũng hỏng — vì một lý do khác hẳn — thì
// không có gì mới để ghi đè lên, và bản ghi cũ nằm nguyên đó: lần gọi dậy sau lại đưa đúng cái
// handle chết ấy, rồi lần sau nữa, cho tới lúc mạch hết hạn giữ (FR-025, FR-027).
func TestAHandleThatWasRefusedIsTakenAwayRatherThanLeftForTheNextWake(t *testing.T) {
	w := aWorld(t)
	w.engine.session = "sess-first"
	w.options().Do(context.Background(), w.grant())

	// Lượt sau: handle bị từ chối, và lượt thử lại cũng hỏng — nên nó không mang về mạch nào.
	second := w.grant()
	second.RunID = "run-2"
	w.engine.session = ""
	w.engine.refused = true
	w.engine.fails = errors.New("và lần thử lại cũng không chạy được")
	w.options().Do(context.Background(), second)

	third := w.grant()
	third.RunID = "run-3"
	w.engine.session, w.engine.refused, w.engine.fails = "sess-new", false, nil
	w.options().Do(context.Background(), third)

	if w.engine.saw.Session != "" {
		t.Errorf("lần gọi dậy sau lại được đưa %q — đúng cái handle vừa bị từ chối",
			w.engine.saw.Session)
	}
	if w.engine.saw.Restart != nil {
		t.Errorf("agent bị báo mất mạch lần thứ hai, cho cùng một lần mất: %v",
			w.engine.saw.Restart.Code)
	}
}

// Và khi lượt thử lại **chạy được**, mạch mới ghi đè như thường: không có gì phải quên.
func TestARefusedHandleReplacedByAWorkingOneIsSimplyOverwritten(t *testing.T) {
	w := aWorld(t)
	w.engine.session = "sess-first"
	w.options().Do(context.Background(), w.grant())

	second := w.grant()
	second.RunID = "run-2"
	w.engine.session, w.engine.refused = "sess-after-restart", true
	w.options().Do(context.Background(), second)

	third := w.grant()
	third.RunID = "run-3"
	w.engine.refused = false
	w.options().Do(context.Background(), third)

	if w.engine.saw.Session != "sess-after-restart" {
		t.Errorf("lần gọi dậy sau nối vào %q, mong mạch mở lại sau khi bắt đầu lại",
			w.engine.saw.Session)
	}
}
