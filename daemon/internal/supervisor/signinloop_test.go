package supervisor

import (
	"context"
	"errors"
	"reflect"
	"sync"
	"testing"
	"time"
)

// signIns is one machine whose CLI answers whatever the test last told it to.
type signIns struct {
	mu     sync.Mutex
	answer map[string]bool
	told   []map[string]bool
	fail   error
	heard  chan struct{}
}

func newSignIns(answer map[string]bool) *signIns {
	return &signIns{answer: answer, heard: make(chan struct{}, 16)}
}

func (s *signIns) says(answer map[string]bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.answer = answer
}

func (s *signIns) ask(context.Context) map[string]bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	defer func() { s.heard <- struct{}{} }()
	return s.answer
}

func (s *signIns) tell(_ context.Context, answers map[string]bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.fail != nil {
		return s.fail
	}
	s.told = append(s.told, answers)
	return nil
}

func (s *signIns) reports() []map[string]bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]map[string]bool(nil), s.told...)
}

// run starts the loop and hands back how to step it once and how to stop it.
func (s *signIns) run(t *testing.T, started map[string]bool, again chan struct{}) (step func(), stop func()) {
	t.Helper()
	ticks := make(chan time.Time)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = RunSignInLoop(ctx, SignInOptions{
			Ask: s.ask, Tell: s.tell, Reported: started, Again: again,
			Tick: func(time.Duration) <-chan time.Time { return ticks },
		})
	}()
	step = func() {
		ticks <- time.Now()
		<-s.heard
	}
	stop = func() {
		cancel()
		<-done
	}
	return step, stop
}

func TestNothingIsReportedWhileTheAnswerStaysTheSame(t *testing.T) {
	cli := newSignIns(map[string]bool{"claude_code": true})
	step, stop := cli.run(t, map[string]bool{"claude_code": true}, nil)

	step()
	step()
	stop()

	if got := cli.reports(); len(got) != 0 {
		t.Errorf("reported %v although nothing changed", got)
	}
}

func TestASignInThatLapsesIsReportedAndSoIsSigningInAgain(t *testing.T) {
	cli := newSignIns(map[string]bool{"claude_code": true})
	step, stop := cli.run(t, map[string]bool{"claude_code": true}, nil)

	cli.says(map[string]bool{"claude_code": false})
	step()
	step() // still signed out: said once, not on every tick
	cli.says(map[string]bool{"claude_code": true})
	step()
	stop()

	want := []map[string]bool{{"claude_code": false}, {"claude_code": true}}
	if got := cli.reports(); !reflect.DeepEqual(got, want) {
		t.Errorf("reported %v, want %v", got, want)
	}
}

// A CLI that stops being askable is news too: the server holds a *no* or a *yes* for it that
// nobody is standing behind any more.
func TestACLIThatCanNoLongerBeAskedIsReportedAsUnasked(t *testing.T) {
	cli := newSignIns(map[string]bool{"claude_code": false})
	step, stop := cli.run(t, map[string]bool{"claude_code": false}, nil)

	cli.says(map[string]bool{})
	step()
	stop()

	if got := cli.reports(); len(got) != 1 || len(got[0]) != 0 {
		t.Errorf("reported %v, want one report with no answer in it", got)
	}
}

// The provider refused a run and the server closed the workplace on it. This machine's next
// report is the only thing that reopens it, so it is sent even though the CLI says what it
// said before.
func TestARefusedRunMakesTheMachineReportAgainEvenWithNothingNew(t *testing.T) {
	cli := newSignIns(map[string]bool{"claude_code": true})
	again := make(chan struct{})
	_, stop := cli.run(t, map[string]bool{"claude_code": true}, again)

	again <- struct{}{}
	<-cli.heard
	stop()

	want := []map[string]bool{{"claude_code": true}}
	if got := cli.reports(); !reflect.DeepEqual(got, want) {
		t.Errorf("reported %v, want %v", got, want)
	}
}

func TestAReportThatDidNotArriveIsSentAgainOnTheNextTick(t *testing.T) {
	cli := newSignIns(map[string]bool{"claude_code": false})
	cli.fail = errors.New("connection reset by peer")
	step, stop := cli.run(t, map[string]bool{"claude_code": true}, nil)

	step()
	cli.mu.Lock()
	cli.fail = nil
	cli.mu.Unlock()
	step()
	stop()

	want := []map[string]bool{{"claude_code": false}}
	if got := cli.reports(); !reflect.DeepEqual(got, want) {
		t.Errorf("reported %v, want the news to arrive once the road was back", got)
	}
}
