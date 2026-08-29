// Package supervisor is the half of the daemon that decides *when*: when to ask for work, when
// to say this machine is alive, and — here — everything that happens between being handed a run
// and telling the server how it went.
package supervisor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
	"github.com/gnust-company/armarius-daemon/internal/runtime"
)

// Workplace is one place on this machine that work can be done: an agent CLI that was found
// here, registered with the server, and is now being handed something to do.
type Workplace struct {
	// CLI is the kind, spelled the way the server spells it in `workplaces.cli_kind`. Every
	// table in execenv and runtime is keyed on this exact string.
	CLI string
	// Family decides which of the two protocols this CLI is run under (FR-035, FR-039).
	Family string
	// Binary is where discovery found it. Carried rather than looked up again, so that the CLI
	// that runs is the one this machine registered.
	Binary string
}

// Recorded is one event with its place in the run's order (FR-045).
//
// The number is assigned on this machine, in the order the agent produced things, and it is
// what makes a re-sent batch harmless: the server writes each number once, so a reply lost on
// the way back costs a repeated call and nothing else.
type Recorded struct {
	Seq     int
	Type    string
	Payload map[string]any
}

// How a run ended, as a code (Constitution VII).
const (
	// Completed: the agent took its turn and the turn ended. It says nothing about whether the
	// agent did the job well — an agent that reports it could not finish still *ran*.
	Completed = "completed"
	// Failed: the run did not get to the end. The CLI would not start, died, or the machine
	// could not set it up.
	Failed = "failed"
	// TimedOut: the agent stopped producing anything for longer than the silence threshold and
	// was cut (FR-031).
	TimedOut = "timed_out"
	// Stopped: something outside the run ended it — this daemon shutting down, or the server
	// saying the run is no longer ours.
	Stopped = "stopped"
)

// Conclusion is what the server is told when a run closes.
type Conclusion struct {
	Status string
	// Error is what went wrong, when something did. Free text, English, and the daemon's own
	// words: it describes this machine's side of the failure, which no code on the server
	// could have known.
	Error string
	// Usage is whatever the CLI said the turn cost, passed on exactly as it was given.
	Usage map[string]any
}

// Ledger is the server, as far as one run is concerned.
//
// An interface rather than the client type: this package decides what a run does, and it should
// not have to be edited the day a field is added to the wire format — the same reason `Grant`
// is not the client's own struct.
type Ledger interface {
	// Start says the agent is up. False with no error means the hold ran out while this
	// machine was setting up: the run belongs to nobody now, and the only correct answer is to
	// stop and clean up (FR-058).
	Start(ctx context.Context, runID, session string) (bool, error)
	// Record sends one batch of events. ErrRunNotOurs means this machine no longer holds the
	// run and must stop (FR-059).
	Record(ctx context.Context, runID string, events []Recorded) error
	// Finish closes the run: the run token dies with it, and the task gets something live
	// pushing it again without waiting for a sweep (FR-014b, FR-030a).
	Finish(ctx context.Context, runID string, done Conclusion) error
}

// RunOptions is everything running one piece of work needs from the rest of the daemon.
type RunOptions struct {
	// WorkRoot holds one working directory per task; StateRoot holds what outlives them.
	WorkRoot  string
	StateRoot string
	// OperatorHome is the real home of the person running this daemon, linked into each run's
	// home so an agent does not have to log in again.
	OperatorHome string
	// Server is where this machine's runs call back to, handed to the agent alongside its own
	// token so that a credential never has to have its audience guessed.
	Server string
	// DaemonToken is this machine's own token, passed in **so it can be kept out** of every
	// agent's environment (FR-014c).
	DaemonToken string

	// Workplace answers what a workplace id means on this machine.
	Workplace func(workplaceID string) (Workplace, bool)
	// Runtime answers which protocol family runs a workplace of this kind.
	Runtime func(family string) (runtime.Runtime, bool)
	// Ledger is the server.
	Ledger Ledger
	// Runs is this machine's register of what it currently holds.
	Runs *Runs
	// Watchdog decides how long silence is allowed to last (FR-031, FR-031a).
	Watchdog *Watchdog

	// Report is told about anything that went wrong which did not end the run.
	Report func(error)
	// Now is the clock, handed in so a test does not have to wait for one.
	Now func() time.Time
}

// Do carries one granted run from being handed over to being closed (FR-015, FR-039).
//
// It returns nothing. Everything a run can produce — its events, how it ended, why it failed —
// travels to the server on the way through, and there is nobody left upstream to hand an error
// to: this is called from the ask loop, which has already moved on to the next thing.
func (o RunOptions) Do(ctx context.Context, grant Grant) {
	o = o.withDefaults()

	ctx, release := o.Runs.begin(ctx, grant)
	defer release()

	place, known := o.Workplace(grant.WorkplaceID)
	if !known {
		// The server handed out work for a workplace this machine no longer has — a CLI
		// uninstalled between the last sync and now. Nothing here can fix it and the next
		// sync will say so, which is what takes the workplace out of circulation (FR-033).
		o.giveUpDuringSetup(ctx, grant, fmt.Errorf("this machine has no workplace %s", grant.WorkplaceID))
		return
	}
	engine, runnable := o.Runtime(place.Family)
	if !runnable {
		o.giveUpDuringSetup(ctx, grant, fmt.Errorf("no runtime here speaks %q", place.Family))
		return
	}

	req, home, err := o.prepare(grant, place)
	if err != nil {
		o.giveUpDuringSetup(ctx, grant, err)
		return
	}
	// The home belongs to this run and goes when it does. Everything in it that has to outlive
	// the run is a link out to a store that is not in here, so taking it away takes away
	// nothing that will be wanted again (FR-023).
	defer func() {
		if err := os.RemoveAll(home); err != nil {
			o.Report(fmt.Errorf("clearing the home of run %s: %w", grant.RunID, err))
		}
	}()

	// The agent is about to exist. Saying so stops the clock on getting ready — from here the
	// thing being watched is the run itself, not the setting up of it (FR-056a).
	mine, err := o.Ledger.Start(ctx, grant.RunID, req.Session)
	if err != nil {
		o.giveUpDuringSetup(ctx, grant, fmt.Errorf("reporting the start of run %s: %w", grant.RunID, err))
		return
	}
	if !mine {
		// Not ours any more. Nothing is started, nothing is reported: a run this machine does
		// not hold is one whose every write would be refused anyway (FR-058, FR-059).
		o.Report(fmt.Errorf("run %s was taken back while this machine was setting it up", grant.RunID))
		return
	}

	o.carry(ctx, grant, place, engine, req)
}

// prepare puts everything the agent needs on disk and builds the environment it runs in.
//
// Ordered so that nothing exists half-made: the directory, then the home, then the two things
// written fresh for this run, and only then the environment — which is the one step that can
// refuse on a rule rather than on a filesystem (FR-014c).
func (o RunOptions) prepare(grant Grant, place Workplace) (runtime.Request, string, error) {
	workDir, err := execenv.WorkDir(o.WorkRoot, grant.TaskID)
	if err != nil {
		return runtime.Request{}, "", err
	}
	home, err := execenv.RunHome(workDir, grant.RunID)
	if err != nil {
		return runtime.Request{}, "", err
	}
	if _, err := execenv.Build(execenv.Spec{
		CLI:          place.CLI,
		Home:         home,
		StateRoot:    o.StateRoot,
		OperatorHome: o.OperatorHome,
		TaskID:       grant.TaskID,
	}); err != nil {
		return runtime.Request{}, home, err
	}
	if _, err := execenv.WriteContextFile(place.CLI, workDir, grant.Prompt); err != nil {
		return runtime.Request{}, home, err
	}
	if _, err := execenv.WriteSkills(place.CLI, workDir, home, grant.Skills); err != nil {
		return runtime.Request{}, home, err
	}
	env, err := execenv.Environ(execenv.EnvSpec{
		CLI:       place.CLI,
		Home:      home,
		TaskID:    grant.TaskID,
		ProjectID: grant.ProjectID,
		Inherited: os.Environ(),
		Credentials: execenv.Credentials{
			RunID:       grant.RunID,
			RunToken:    grant.RunToken,
			Server:      o.Server,
			DaemonToken: o.DaemonToken,
		},
	})
	if err != nil {
		return runtime.Request{}, home, err
	}
	return runtime.Request{
		CLI:     place.CLI,
		Binary:  place.Binary,
		WorkDir: workDir,
		Env:     env,
		Message: grant.Prompt,
		// Empty until the daemon keeps session state of its own (FR-023, task T109). A CLI
		// handed no handle opens a new conversation, which is the supported answer rather
		// than a failure (FR-025).
		Session: "",
	}, home, nil
}

// carry runs the agent and reports how it went.
func (o RunOptions) carry(
	ctx context.Context, grant Grant, place Workplace, engine runtime.Runtime, req runtime.Request,
) {
	// Cancelled from three directions, and the run cannot tell which: the daemon being stopped,
	// the server saying the run is not ours, and the agent going silent for too long. Each one
	// ends the CLI and its whole process tree the same way.
	ctx, stop := context.WithCancel(ctx)
	defer stop()

	var taken sync.Once
	events := newStream(grant.RunID, grant.FirstSeq, o.Ledger, o.Report, func() { taken.Do(stop) }, o.Now())

	var carrying sync.WaitGroup
	carrying.Add(1)
	go func() {
		defer carrying.Done()
		events.deliver(ctx)
	}()

	silent := o.watchSilence(ctx, place.CLI, events, stop)

	outcome, err := engine.Run(ctx, req, func(e runtime.Event) { events.record(e, o.Now()) })

	// Read before stopping anything. After the line below every context in here is cancelled,
	// including the one this run ended perfectly well under, and a verdict taken then would
	// call every finished run *stopped*.
	endedFromOutside := ctx.Err() != nil

	stop()
	carrying.Wait()

	o.close(ctx, grant, Conclusion{
		Status: o.verdict(err, silent(), endedFromOutside),
		Error:  errorText(err),
		Usage:  outcome.Usage,
	})
}

// watchSilence cuts a run that has stopped producing anything (FR-031).
//
// There is deliberately no limit on how long a run may take — only on how long it may say
// nothing. An agent thinking hard for an hour is working; an agent that has said nothing for
// ten minutes has stopped, and the difference is the only one this daemon can actually observe
// from outside the process.
//
// The returned function answers whether it was silence that ended the run, which is a different
// ending from a crash and leads somewhere different afterwards (`decide_self_wake` on the
// server treats a run that timed out as one to resume).
func (o RunOptions) watchSilence(
	ctx context.Context, cli string, events *stream, stop context.CancelFunc,
) func() bool {
	threshold := o.Watchdog.Threshold(cli)
	var cut sync.Once
	var wasSilence bool

	go func() {
		// Checked several times per threshold rather than once at the deadline: the deadline
		// moves every time the agent says something, and a timer set for the original one
		// would fire on a run that has been talking the whole time.
		beat := time.NewTicker(threshold / 4)
		defer beat.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-beat.C:
				if o.Watchdog.Stalled(cli, events.quietSince(), o.Now()) {
					cut.Do(func() {
						wasSilence = true
						events.record(runtime.Event{Type: runtime.EventRunError, Payload: map[string]any{
							"code":            "silence_threshold",
							"quiet_seconds":   int(threshold.Seconds()),
							"cli":             cli,
							"nothing_since":   events.quietSince().UTC().Format(time.RFC3339),
							"ended_by_daemon": true,
						}}, o.Now())
						stop()
					})
					return
				}
			}
		}
	}()

	return func() bool { return wasSilence }
}

// verdict turns what happened into the one code the server is told.
//
// Order matters. Silence is checked first because a run cut for silence also comes back with a
// cancellation error, and reporting that as *stopped* would lose the only fact that explains it.
func (o RunOptions) verdict(runErr error, silent, endedFromOutside bool) string {
	switch {
	case silent:
		return TimedOut
	case runErr == nil:
		return Completed
	case endedFromOutside:
		// Ended by something other than the agent: this daemon stopping, or the server saying
		// the run is no longer ours.
		return Stopped
	default:
		return Failed
	}
}

// close tells the server the run is over, on a context of its own.
//
// Its own, because the ordinary way a run ends badly is the run's context being cancelled — and
// a call made on that context would be refused before it left the machine. This is the call
// that revokes the run's token and puts something live back on the task (FR-014b, FR-030a), so
// it is the last one that may be skipped.
func (o RunOptions) close(ctx context.Context, grant Grant, done Conclusion) {
	closing, cancel := context.WithTimeout(context.WithoutCancel(ctx), flushDeadline)
	defer cancel()

	if err := o.Ledger.Finish(closing, grant.RunID, done); err != nil {
		if errors.Is(err, ErrRunNotOurs) {
			// Somebody has already closed it — the hold lapsed and the sweep took it back, or
			// this call is the second one after a reply went missing. Either way the run is
			// closed, which is what this call was for.
			return
		}
		o.Report(fmt.Errorf("closing run %s: %w", grant.RunID, err))
	}
}

// giveUpDuringSetup is what happens when this machine cannot get a run to the point of starting.
//
// It does **not** close the run. FR-057 separates *nobody took this* from *something took it and
// died getting ready*, and the second one is answered by the hold running out: the run goes back
// on the shelf and is offered again, to the same machine, because an agent belongs to one place
// (FR-007, FR-056a). Closing it here instead would spend a recovery attempt on a machine that
// has not tried once.
//
// What it does do is say why, on the record, before going quiet. A run that comes back to the
// shelf with nothing written about it is the shape of the failure that is impossible to
// diagnose afterwards.
func (o RunOptions) giveUpDuringSetup(ctx context.Context, grant Grant, cause error) {
	o.Report(fmt.Errorf("could not set up run %s: %w", grant.RunID, cause))

	saying, cancel := context.WithTimeout(context.WithoutCancel(ctx), flushDeadline)
	defer cancel()
	first := grant.FirstSeq
	if first < 1 {
		first = 1
	}
	err := o.Ledger.Record(saying, grant.RunID, []Recorded{{
		Seq:  first,
		Type: runtime.EventRunError,
		Payload: map[string]any{
			"code": "setup_failed",
			"why":  cause.Error(),
		},
	}})
	if err != nil && !errors.Is(err, ErrRunNotOurs) {
		o.Report(fmt.Errorf("recording why run %s could not be set up: %w", grant.RunID, err))
	}
}

func errorText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func (o RunOptions) withDefaults() RunOptions {
	if o.Workplace == nil {
		o.Workplace = func(string) (Workplace, bool) { return Workplace{}, false }
	}
	if o.Runtime == nil {
		o.Runtime = func(string) (runtime.Runtime, bool) { return nil, false }
	}
	if o.Runs == nil {
		o.Runs = &Runs{}
	}
	if o.Watchdog == nil {
		// The base threshold and nothing else, which is what a machine whose settings say
		// nothing about silence has asked for (FR-031).
		o.Watchdog, _ = NewWatchdog(DefaultSilenceThreshold, nil)
	}
	if o.Report == nil {
		o.Report = func(error) {}
	}
	if o.Now == nil {
		o.Now = time.Now
	}
	return o
}

// ── what this machine is holding ─────────────────────────────────────────────

// Runs is the register of work this machine currently has.
//
// Three questions are asked of it, from three directions, and they have to have one answer:
// how much room is left (the ask loop), what is running right now (the beat), and whether a
// working directory may be reclaimed (the sweep). Kept in three places they would drift, and
// the drift would show up as a machine claiming work it has no room for, or a sweep deleting a
// directory out from under a live agent.
type Runs struct {
	mu   sync.Mutex
	held map[string]holding
}

type holding struct {
	taskID string
	stop   context.CancelFunc
}

// begin registers one run and hands back a context that Cancel can end.
func (r *Runs) begin(ctx context.Context, grant Grant) (context.Context, func()) {
	ctx, stop := context.WithCancel(ctx)
	r.mu.Lock()
	if r.held == nil {
		r.held = make(map[string]holding)
	}
	r.held[grant.RunID] = holding{taskID: grant.TaskID, stop: stop}
	r.mu.Unlock()

	return ctx, func() {
		r.mu.Lock()
		delete(r.held, grant.RunID)
		r.mu.Unlock()
		stop()
	}
}

// Count is how many runs this machine is holding.
func (r *Runs) Count() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.held)
}

// IDs is what this machine would say it is running, if asked (FR-004).
func (r *Runs) IDs() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	ids := make([]string, 0, len(r.held))
	for id := range r.held {
		ids = append(ids, id)
	}
	return ids
}

// Cancel ends one run, if this machine is holding it.
//
// The server names runs to cancel on every beat: work it has taken back, usually because this
// machine's hold on it lapsed. Stopping is not a courtesy — every write from that run is going
// to be refused from now on (FR-059), so what carries on is an agent producing a record nobody
// will keep.
func (r *Runs) Cancel(runID string) bool {
	r.mu.Lock()
	held, mine := r.held[runID]
	r.mu.Unlock()
	if !mine {
		return false
	}
	held.stop()
	return true
}

// Holding answers the sweep: is anyone working in this directory right now (FR-021)?
//
// The sweep names a working directory by the task it belongs to, which is the same name this
// register keys on — so the comparison is on task, not on a path that would have to be built
// the same way in two places to agree.
func (r *Runs) Holding(dir string) bool {
	task := filepath.Base(dir)
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, held := range r.held {
		if held.taskID == task {
			return true
		}
	}
	return false
}
