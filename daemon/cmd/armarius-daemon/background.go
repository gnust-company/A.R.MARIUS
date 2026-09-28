package main

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/client"
	"github.com/gnust-company/armarius-daemon/internal/config"
	"github.com/gnust-company/armarius-daemon/internal/supervisor"
)

// How the background start and `stop` wait (FR-008m).
const (
	// startupPatience is how long `start` waits for the daemon it launched to say it is up. It
	// covers the slow half of starting — every agent CLI on the machine asked its version and
	// what it can do — with room to spare; past it, the daemon is still left running and the
	// person is pointed at its log rather than told it failed.
	startupPatience = 60 * time.Second
	// stopMargin is added to the drain patience when `stop` waits: what a stop takes is the
	// runs it lets finish, plus handing the workplaces back.
	stopMargin = 30 * time.Second
	// maxLogBytes is how large daemon.log may grow before a start sets it aside.
	maxLogBytes = 20 << 20
	// stopRequestCheck is how often a running daemon looks for a stop request.
	stopRequestCheck = time.Second
)

// startInBackground launches this same program as `start -foreground`, detached from the
// terminal, and waits until that daemon is up (FR-008m).
//
// Up means it has written the state file under its own process id — the moment it has registered
// this machine's workplaces — and not merely that a process exists. A daemon that dies while
// starting (a token that was revoked, a server that cannot be reached) is reported as failed with
// what it wrote to its log on the way down, because "started" followed by a machine that never
// appears is the one answer that sends a person looking in the wrong place.
func startInBackground(ctx context.Context, configPath string, out io.Writer) error {
	configPath, err := filepath.Abs(configPath)
	if err != nil {
		return err
	}
	if _, err := client.LoadCredentials(configPath); err != nil {
		return err
	}
	statePath := client.StatePath(configPath)
	if state, found, err := client.LoadState(statePath); err == nil && found &&
		client.ProcessAlive(state.PID) && !state.Leaving() {
		// Said here rather than left to the daemon we would launch: it would refuse just the
		// same (FR-034a), but into a log nobody is looking at.
		return fmt.Errorf("%w (process %d); `armarius-daemon stop` stops it", supervisor.ErrAnotherDaemonIsRunning, state.PID)
	}

	program, err := os.Executable()
	if err != nil {
		return fmt.Errorf("finding this program to start it in the background: %w", err)
	}
	logPath := client.LogPath(configPath)
	setAsideIfLarge(logPath)
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600) //nolint:gosec // beside the operator's own config
	if err != nil {
		return fmt.Errorf("opening the daemon's log: %w", err)
	}
	var from int64
	if info, err := logFile.Stat(); err == nil {
		from = info.Size()
	}

	// A context that is never cancelled: Ctrl-C on this command must not reach the daemon it is
	// leaving behind, which is the whole point of starting it detached.
	daemon := exec.CommandContext(context.WithoutCancel(ctx), //nolint:gosec // this same program
		program, "start", "-foreground", "-config", configPath)
	daemon.Stdout, daemon.Stderr = logFile, logFile
	daemon.SysProcAttr = detached()
	if err := daemon.Start(); err != nil {
		_ = logFile.Close()
		return fmt.Errorf("starting the daemon in the background: %w", err)
	}
	_ = logFile.Close()

	exited := make(chan error, 1)
	go func() { exited <- daemon.Wait() }()

	check := time.NewTicker(250 * time.Millisecond)
	defer check.Stop()
	deadline := time.After(startupPatience)
	for {
		select {
		case err := <-exited:
			return fmt.Errorf("the daemon stopped while starting (%w). What it said:\n%s", err, logSince(logPath, from))
		case <-deadline:
			emit(out, "The daemon (process %d) is still starting after %s. Its log says what it is doing:\n  %s\n",
				daemon.Process.Pid, startupPatience, logPath)
			return nil
		case <-ctx.Done():
			// Ctrl-C on this command, not on the daemon: the daemon is detached and carries on.
			return ctx.Err()
		case <-check.C:
			state, found, err := client.LoadState(statePath)
			if err == nil && found && state.PID == daemon.Process.Pid {
				emit(out, "The daemon is running in the background (process %d).\n", daemon.Process.Pid)
				emit(out, "Log:  %s\n", logPath)
				emit(out, "Stop: armarius-daemon stop\n")
				return nil
			}
		}
	}
}

// setAsideIfLarge moves a log past maxLogBytes to `<log>.1`, replacing an older one there, so the
// log a daemon keeps for weeks cannot take the disk with it. Checked at start rather than
// continuously: this daemon writes a few lines per run, not a stream.
func setAsideIfLarge(logPath string) {
	info, err := os.Stat(logPath)
	if err != nil || info.Size() <= maxLogBytes {
		return
	}
	_ = os.Remove(logPath + ".1")
	_ = os.Rename(logPath, logPath+".1")
}

// logSince is what a log gained after a given size, cut to its last lines.
func logSince(logPath string, from int64) string {
	f, err := os.Open(logPath) //nolint:gosec // the daemon's own log
	if err != nil {
		return "  (the log could not be read: " + err.Error() + ")"
	}
	defer func() { _ = f.Close() }()
	if _, err := f.Seek(from, io.SeekStart); err != nil {
		return "  (the log could not be read: " + err.Error() + ")"
	}
	var lines []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		lines = append(lines, "  "+scanner.Text())
		if len(lines) > 20 {
			lines = lines[1:]
		}
	}
	if len(lines) == 0 {
		return "  (nothing)"
	}
	return strings.Join(lines, "\n")
}

// runStop asks the daemon on this machine to stop, and waits for it to have stopped (FR-008m).
//
// The daemon stops the way every stop goes (FR-034): it stops asking for work at once, lets the
// runs it holds finish, and hands its workplaces back. So `stop` waits for as long as that may
// take, and says how long that is before it starts waiting.
func runStop(ctx context.Context, args []string, out io.Writer) error {
	fs := newFlagSet("stop", out)
	configPath := fs.String("config", defaultConfigPath(), "path to this machine's daemon configuration")
	if err := fs.Parse(args); err != nil {
		return err
	}
	abs, err := filepath.Abs(*configPath)
	if err != nil {
		return err
	}
	state, found, err := client.LoadState(client.StatePath(abs))
	if err != nil {
		return err
	}
	if !found || !client.ProcessAlive(state.PID) {
		emit(out, "No daemon is running on this machine.\n")
		return nil
	}
	settings, err := config.Load(abs)
	if err != nil {
		return err
	}
	patience := settings.DrainPatience.Duration()

	if err := os.WriteFile(client.StopRequestPath(abs), []byte(fmt.Sprintf("%d\n", state.PID)), 0o600); err != nil {
		return fmt.Errorf("asking the daemon to stop: %w", err)
	}
	emit(out, "Asked the daemon (process %d) to stop. It lets the runs it holds finish first, for up to %s.\n",
		state.PID, patience)

	check := time.NewTicker(250 * time.Millisecond)
	defer check.Stop()
	deadline := time.After(patience + stopMargin)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-deadline:
			return fmt.Errorf("the daemon (process %d) was still stopping after %s; `armarius-daemon status` says what it is doing",
				state.PID, patience+stopMargin)
		case <-check.C:
			if !client.ProcessAlive(state.PID) {
				emit(out, "Stopped.\n")
				return nil
			}
		}
	}
}

// watchStopRequest ends the daemon's context when `armarius-daemon stop` asks it to (FR-008m).
// Any request already lying there when the daemon starts is from a daemon that is gone, and is
// cleared first rather than obeyed.
func watchStopRequest(ctx context.Context, configPath string, stop func(), out io.Writer) {
	request := client.StopRequestPath(configPath)
	_ = os.Remove(request)
	check := time.NewTicker(stopRequestCheck)
	defer check.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-check.C:
			if _, err := os.Stat(request); errors.Is(err, os.ErrNotExist) {
				continue
			}
			_ = os.Remove(request)
			emit(out, "Asked to stop by `armarius-daemon stop`.\n")
			stop()
			return
		}
	}
}
