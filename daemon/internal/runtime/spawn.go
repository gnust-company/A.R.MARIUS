package runtime

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"sync"
	"time"
)

// treeGrace is how long the whole tree under a CLI has to go away by itself after the run is
// over, before it is ended outright.
//
// Short, because by this point nobody is waiting for it to finish anything: either the turn
// ended and whatever is still running was never part of it, or the run was cancelled and the
// answer is no longer wanted. Long enough that a CLI which flushes its session file on the way
// down gets to finish writing it, which is the one thing in here worth waiting for (FR-023).
const treeGrace = 5 * time.Second

// newProcess builds the command one CLI is run with, ready to be started.
//
// Both families come through here, because both start a process and both have the same two
// problems with it.
//
// **The child leads its own process tree.** An agent CLI is a program that starts programs: a
// shell, a compiler, a test run, sometimes a server that means to outlive the command that
// started it. `exec.CommandContext` on its own ends only the process it started, so cancelling a
// run would leave that tree behind — still holding this run's working directory, still holding
// an environment with this run's token in it (FR-014). Putting the child in a process group of
// its own means the whole tree can be addressed as one thing, at the end of the run, whether the
// run ended well or was cut short.
//
// **Waiting has a bound.** `Wait` does not return until the pipes it created are closed, and a
// grandchild that inherited standard output holds them open long after the CLI itself has gone.
// Left alone that is not a slow run, it is a run that never ends: no exit code, no final event,
// and a slot on this machine occupied forever. `WaitDelay` puts a limit on how long the tail of
// a finished process is waited for, and turns the worst case into a run that ends untidily
// rather than one that does not end.
func newProcess(ctx context.Context, req Request, args []string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, req.Binary, args...) //nolint:gosec // the path is what discovery found on this machine
	cmd.Dir = req.WorkDir
	cmd.Env = req.Env
	leadItsOwnTree(cmd)

	// Cancellation asks the whole tree to stop, rather than only the CLI. Asking rather than
	// ending it: a CLI told to stop writes out where its conversation had got to, and the next
	// run on this task is the one that pays for skipping that (FR-023).
	cmd.Cancel = func() error { return endTree(cmd, false) }
	cmd.WaitDelay = treeGrace
	return cmd
}

// drainGrace is how long the last of a CLI's output is waited for once the CLI itself has gone
// and its tree has been ended. Short: everything still unread by then is already sitting in a
// kernel buffer, and what this bounds is the case where something is still holding the pipe
// open despite having been killed.
const drainGrace = 2 * time.Second

// pipes are the two streams a CLI writes to, owned by this process rather than by exec.Cmd.
//
// **This is not a detail.** exec.Cmd will make these itself, and that version deadlocks: a pipe
// reaches end-of-file when every writer has closed it, and an agent CLI is a program that starts
// programs — the shell it ran, the server that shell left running, all of them inherited the
// same two descriptors. `Wait` does not return until the copying it owns has finished, so a
// single background process the agent forgot about turns "wait for the CLI" into "wait forever",
// with the run's slot held and no exit status ever reported.
//
// Owning them here separates the two questions. Waiting for the CLI waits for the CLI. Reading
// the last of its output is a second wait, with an end to it (drainGrace), after the tree has
// been ended — and the reader is unblocked by taking the pipe away if it comes to that.
type pipes struct {
	out, errs        *os.File
	childOut, childE *os.File
}

func plumb(cmd *exec.Cmd) (*pipes, error) {
	outR, outW, err := os.Pipe()
	if err != nil {
		return nil, fmt.Errorf("opening a pipe for what it says: %w", err)
	}
	errR, errW, err := os.Pipe()
	if err != nil {
		_, _ = outR.Close(), outW.Close()
		return nil, fmt.Errorf("opening a pipe for what it complains about: %w", err)
	}
	// Real files rather than arbitrary writers: exec.Cmd hands a *os.File straight to the child
	// and starts no copying goroutine of its own, which is what keeps Wait free of them.
	cmd.Stdout, cmd.Stderr = outW, errW
	return &pipes{out: outR, errs: errR, childOut: outW, childE: errW}, nil
}

// handedOver closes this process's copies of the child's ends. Called right after Start: until
// it is, the pipes have a writer in this process too, and would never reach end-of-file.
func (p *pipes) handedOver() {
	_, _ = p.childOut.Close(), p.childE.Close()
}

// takeAway unblocks whoever is reading, whether or not anything is still writing.
func (p *pipes) takeAway() {
	_, _ = p.out.Close(), p.errs.Close()
}

// drain waits for the readers to finish, and stops waiting if something is still holding the
// pipes open after everything that should have closed them has been killed.
func (p *pipes) drain(readers *sync.WaitGroup) {
	done := make(chan struct{})
	go func() {
		readers.Wait()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(drainGrace):
		p.takeAway()
		<-done
	}
	p.takeAway()
}

// reap ends whatever is left of one run's process tree.
//
// Called after every run, not only after a cancelled one. A turn that ended perfectly can still
// leave a background process behind — an agent that started a dev server, a watcher it forgot,
// something that daemonised itself — and each of those holds an environment containing this
// run's token, in a working directory the sweep is meant to be free to reclaim (FR-014b, FR-021).
// Leaving them is how a machine acquires processes nobody remembers starting.
//
// Errors are not reported: by this point the ordinary case is that everything has already
// exited, which on Unix is indistinguishable from a group that was never there.
func reap(cmd *exec.Cmd) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	_ = endTree(cmd, true)
}
