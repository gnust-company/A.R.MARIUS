package supervisor

import (
	"context"
	"testing"
	"time"
)

// FR-008n: cổng chỉ đóng khi thật sự rảnh — không lượt nào đang giữ, không lần xin việc nào đang
// dở — và đóng rồi thì không lần xin việc nào lọt qua nữa.
func TestTheGatePausesOnlyAnIdleMachine(t *testing.T) {
	var gate Gate

	if !gate.PauseIfIdle(func() int { return 0 }) {
		t.Fatal("máy không giữ gì, không xin gì mà cổng không đóng")
	}
	if _, ok := gate.Admit(); ok {
		t.Fatal("cổng đã đóng mà vẫn cho một lần xin việc đi qua")
	}
	gate.Resume()
	release, ok := gate.Admit()
	if !ok {
		t.Fatal("mở lại rồi mà vẫn không cho xin việc")
	}
	release()
}

func TestTheGateDoesNotPauseWhileARunIsHeld(t *testing.T) {
	var gate Gate
	if gate.PauseIfIdle(func() int { return 1 }) {
		t.Fatal("đang giữ một lượt mà cổng vẫn coi là rảnh")
	}
	if _, ok := gate.Admit(); !ok {
		t.Fatal("một lần kiểm không rảnh đã đóng cổng lại")
	}
}

// Khe hở cổng này tồn tại để bịt: một lần xin việc đang dở có thể mang về một lượt, và lượt ấy
// chưa kịp vào sổ lúc đếm.
func TestTheGateDoesNotPauseWhileAnAskIsInFlight(t *testing.T) {
	var gate Gate
	release, ok := gate.Admit()
	if !ok {
		t.Fatal("cổng mở mà không cho xin việc")
	}
	if gate.PauseIfIdle(func() int { return 0 }) {
		t.Fatal("một lần xin việc đang dở mà cổng vẫn coi là rảnh")
	}
	release()
	release() // gọi hai lần không được đếm hai lần
	if !gate.PauseIfIdle(func() int { return 0 }) {
		t.Fatal("lần xin việc đã xong mà cổng vẫn không đóng")
	}
}

// Vòng xin việc hỏi cổng trước mỗi lần xin, và cổng đóng thì không xin.
func TestTheAskLoopAsksTheGateFirst(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	a := &asks{stopAt: 100, cancel: cancel, capacity: 2}
	opts := a.options()
	var gate Gate
	gate.PauseIfIdle(func() int { return 0 })
	opts.Admit = gate.Admit
	asked := 0
	opts.Tick = func(time.Duration) <-chan time.Time {
		asked++
		if asked >= 3 {
			cancel()
		}
		due := make(chan time.Time, 1)
		due <- time.Now()
		return due
	}

	if err := RunClaimLoop(ctx, opts); err != nil {
		t.Fatalf("một lần dừng có trật tự không phải là hỏng: %v", err)
	}
	if len(a.rooms) != 0 {
		t.Fatalf("cổng đóng mà vẫn xin việc %d lần", len(a.rooms))
	}
}

// Start phải ghi lượt vào sổ trước khi trả về — không để goroutine làm việc ấy sau.
func TestStartPutsTheRunOnTheBooksBeforeItReturns(t *testing.T) {
	w := aWorld(t)
	opts := w.options()
	block := make(chan struct{})
	opts.Workplace = func(string) (Workplace, bool) {
		<-block
		return Workplace{}, false
	}
	opts.Start(context.Background(), Grant{RunID: "run-1", WorkplaceID: "wp-1"})
	if w.held.Count() != 1 {
		t.Fatalf("Start trả về mà sổ đang giữ %d lượt, mong 1", w.held.Count())
	}
	close(block)
	deadline := time.Now().Add(5 * time.Second)
	for w.held.Count() != 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if w.held.Count() != 0 {
		t.Fatal("lượt chạy không bao giờ rời sổ")
	}
}
