package main

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/supervisor"
)

// FR-008m: `stop` trên một máy không có daemon nào đang chạy nói đúng thế và không coi là lỗi.
func TestStopOnAMachineWithNoDaemonSaysSo(t *testing.T) {
	stdout, _, err := dispatch(t, "stop", "-config", aLinkedMachine(t, "https://armarius.invalid"))
	if err != nil {
		t.Fatalf("stop khi không có daemon trả lỗi: %v", err)
	}
	if !strings.Contains(stdout, "No daemon is running") {
		t.Fatalf("stop nói: %q", stdout)
	}
}

// Một yêu cầu dừng làm daemon dừng — đúng đường dừng của mọi lần dừng khác.
func TestAStopRequestStopsTheDaemon(t *testing.T) {
	config := aLinkedMachine(t, "https://armarius.invalid")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stopped := make(chan struct{})
	var out bytes.Buffer
	go watchStopRequest(ctx, config, func() { close(stopped) }, &out)

	// Written after the watcher has cleared what it found on arrival.
	time.Sleep(50 * time.Millisecond)
	if err := os.WriteFile(client.StopRequestPath(config), []byte("1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	select {
	case <-stopped:
	case <-time.After(5 * time.Second):
		t.Fatal("có yêu cầu dừng mà daemon không dừng")
	}
	if _, err := os.Stat(client.StopRequestPath(config)); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("yêu cầu dừng đã làm xong mà vẫn nằm đó — daemon sau sẽ dừng ngay khi vừa lên")
	}
}

// Yêu cầu còn sót từ một daemon đã đi là của daemon ấy: daemon mới không được dừng vì nó.
func TestAStopRequestLeftFromBeforeIsClearedNotObeyed(t *testing.T) {
	config := aLinkedMachine(t, "https://armarius.invalid")
	if err := os.WriteFile(client.StopRequestPath(config), []byte("1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	stopped := make(chan struct{})
	go watchStopRequest(ctx, config, func() { close(stopped) }, &bytes.Buffer{})

	select {
	case <-stopped:
		t.Fatal("daemon vừa lên đã dừng vì một yêu cầu của daemon trước")
	case <-time.After(2500 * time.Millisecond):
	}
	cancel()
}

// FR-034a qua đường chạy nền: đã có một daemon đang chạy thì `start` từ chối ngay, nêu tiến
// trình, và không khởi động thêm tiến trình nào.
func TestStartRefusesWhileAnotherDaemonIsRunning(t *testing.T) {
	config := aLinkedMachine(t, "https://armarius.invalid")
	// This test process stands in for a daemon that is alive and means to keep running.
	if err := client.SaveState(client.StatePath(config), client.RunState{PID: os.Getpid(), StartedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}

	_, _, err := dispatch(t, "start", "-config", config)
	if !errors.Is(err, supervisor.ErrAnotherDaemonIsRunning) {
		t.Fatalf("start trên máy đã có daemon trả %v", err)
	}
	if _, statErr := os.Stat(client.LogPath(config)); statErr == nil {
		t.Fatal("từ chối rồi mà vẫn mở log — tức là đã đi tới bước khởi động")
	}
}

// daemon.log không được lớn mãi: quá ngưỡng lúc khởi động thì cất sang một bản cũ duy nhất.
func TestALargeLogIsSetAsideAtStart(t *testing.T) {
	log := filepath.Join(t.TempDir(), "daemon.log")
	if err := os.WriteFile(log, bytes.Repeat([]byte("x"), maxLogBytes+1), 0o600); err != nil {
		t.Fatal(err)
	}
	setAsideIfLarge(log)
	if _, err := os.Stat(log); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("log quá lớn vẫn nằm nguyên chỗ")
	}
	if info, err := os.Stat(log + ".1"); err != nil || info.Size() != maxLogBytes+1 {
		t.Fatalf("bản cũ không được giữ lại: %v", err)
	}

	small := filepath.Join(t.TempDir(), "daemon.log")
	if err := os.WriteFile(small, []byte("a few lines\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	setAsideIfLarge(small)
	if _, err := os.Stat(small); err != nil {
		t.Fatal("log nhỏ cũng bị cất đi")
	}
}
