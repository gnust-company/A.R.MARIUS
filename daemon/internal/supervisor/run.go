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
	// Resumable is what **this installation** answered when it was asked whether it can carry a
	// conversation on (FR-017). Carried on the workplace rather than looked up by kind, because
	// that is precisely the lookup FR-017 forbids: two machines with the same CLI installed can
	// answer differently, and the one that matters is the one about to run the work.
	//
	// A workplace that answered no still gets work. It gets a new conversation each turn and the
	// agent is told why, which is FR-039a's degraded-but-supported rather than a failure.
	Resumable bool
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

	// What the store keeps beside the payload: why something is short, and whether a secret was
	// taken out of it before it left (FR-043b, FR-047, FR-048). Carried rather than recomputed,
	// because the side that cut and masked is the only side that can say so truthfully — the
	// server sees the result of both and cannot tell either from an event that never needed one.
	Truncated      bool
	OriginalBytes  int
	OmissionReason string
	Redacted       bool

	// confession marks the one kind of event this machine writes about *itself* rather than
	// about the agent: the count of events that never reached the record (FR-047). Never sent —
	// the server has no use for it — and read in exactly one place, where a confession the
	// server also refuses must not become a reason to write another one.
	confession bool
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
	// Session is the conversation the run ended holding (FR-023). Told to the server as well as
	// written down here, because a claim about this machine's disk is a claim nobody can check —
	// and the machine can be rebuilt, switched off, or simply wrong.
	Session string
	// Failure is which wall the run hit, as one of the server's codes, when the CLI said so
	// plainly enough to be sure (FR-032a). Separate from Error because that field is prose and
	// a retry policy cannot branch on prose twice running. Empty means *no verdict*, which is
	// the ordinary answer and leaves the run retried exactly as it always was.
	Failure string
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
	// CallbackProgram is the program an agent calls Armarius back with, on this machine
	// (FR-013a). Each run gets its own reachable path to it; this is where the real one is.
	CallbackProgram string

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
	// SessionRetention is how long a conversation may sit idle and still be carried on
	// (FR-027). Zero takes execenv.DefaultSessionRetention. Asked here as well as by the
	// sweep because the two answer different questions at different moments: the sweep decides
	// when a thread is *deleted*, this decides whether the one still on disk may be *trusted*,
	// and a machine that was switched off for a week has plenty of the second and none of the
	// first.
	SessionRetention time.Duration

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

	req, home, prior, err := o.prepare(grant, place)
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
		// A run about no task worked in a directory of its own, and nobody comes back to it —
		// there is no next run of this task, because there is no task. Taken away here rather
		// than left to the sweep so that an interview does not leave one directory per question
		// on somebody's disk for hours; the sweep stays the backstop for a daemon that died.
		if grant.TaskID == "" {
			if err := os.RemoveAll(req.WorkDir); err != nil {
				o.Report(fmt.Errorf("clearing the turf of run %s: %w", grant.RunID, err))
			}
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

	o.remember(grant, req, prior, o.carry(ctx, grant, place, engine, req))
}

// remember writes down the conversation this run leaves behind, so the next wake on the same
// task carries it on instead of starting again (FR-023).
//
// After `carry` and not inside it, because what is being remembered is what the CLI *ended* the
// turn calling the conversation — a run that opened a new one because the old handle would not
// load has a different answer at the end than it had at the start, and the handle written down
// has to be the one that will work next time.
//
// A failure here is reported and nothing else. The run happened, its events are already at the
// server, and losing the note costs the next wake its thread — which is a restart with a notice,
// the outcome FR-025 is written for.
func (o RunOptions) remember(
	grant Grant, req runtime.Request, prior execenv.Thread, outcome runtime.Outcome,
) {
	if outcome.Session == "" {
		if outcome.SessionRefused {
			// The handle was offered, refused, and this turn produced no replacement — a second
			// start that failed for its own reasons. Leaving the note where it is would have the
			// next wake offer the same dead handle and fail the same way, and the one after
			// that, until the thread aged out (FR-025, FR-027).
			if err := execenv.ForgetThread(req.WorkDir); err != nil {
				o.Report(fmt.Errorf("forgetting the conversation of task %s: %w", grant.TaskID, err))
			}
		}
		return
	}
	now := o.Now()
	opened := prior.OpenedAt
	if outcome.Session != prior.Handle || opened.IsZero() {
		opened = now
	}
	if err := execenv.RememberThread(req.WorkDir, execenv.Thread{
		Handle:     outcome.Session,
		Workplace:  grant.WorkplaceID,
		OpenedAt:   opened,
		LastUsedAt: now,
	}); err != nil {
		o.Report(fmt.Errorf("remembering the conversation of task %s: %w", grant.TaskID, err))
	}
}

// turf is where this run works: the task's directory, or one of the run's own when it is about
// no task.
func (o RunOptions) turf(grant Grant) (string, error) {
	if grant.TaskID == "" {
		return execenv.TurnDir(o.WorkRoot, grant.RunID)
	}
	return execenv.WorkDir(o.WorkRoot, grant.TaskID)
}

// storeKey names the store that outlives this run — see the note where it is used.
func (o RunOptions) storeKey(grant Grant) string {
	if grant.TaskID == "" {
		return grant.RunID
	}
	return grant.TaskID
}

// prepare puts everything the agent needs on disk and builds the environment it runs in.
//
// Ordered so that nothing exists half-made: the directory, then the home, then the two things
// written fresh for this run, and only then the environment — which is the one step that can
// refuse on a rule rather than on a filesystem (FR-014c).
func (o RunOptions) prepare(
	grant Grant, place Workplace,
) (runtime.Request, string, execenv.Thread, error) {
	// A run about a task works in the task's directory, which every run of that task comes back
	// to. A run about no task — the team-building interview (FR-040c) — has no such directory to
	// come back to and needs one all the same, so it gets one of its own that goes when it does.
	workDir, err := o.turf(grant)
	if err != nil {
		return runtime.Request{}, "", execenv.Thread{}, err
	}
	home, err := execenv.RunHome(workDir, grant.RunID)
	if err != nil {
		return runtime.Request{}, "", execenv.Thread{}, err
	}
	// What this task was last saying, and whether it may still be said (FR-023, FR-027). Read
	// before anything is built: a failure to read is not a reason to refuse the run — it is a
	// new conversation with a sentence explaining itself (FR-025).
	prior, verdict, err := execenv.RecallThread(workDir, o.Now(), o.SessionRetention)
	if err != nil {
		return runtime.Request{}, "", execenv.Thread{}, err
	}
	handle, restart := runtime.Continue(prior, verdict, grant.WorkplaceID, place.Resumable, o.Now())
	if _, err := execenv.Build(execenv.Spec{
		CLI:          place.CLI,
		Home:         home,
		StateRoot:    o.StateRoot,
		OperatorHome: o.OperatorHome,
		// The key of the store that outlives the run. A turn about no task has nothing to
		// outlive it — the conversation it is carrying on lives on the server and is replayed
		// into the message of every turn — so the key names this one turn, and what it points at
		// is swept on the same clock as any other session store nobody comes back to.
		TaskID: o.storeKey(grant),
	}); err != nil {
		return runtime.Request{}, home, prior, err
	}
	brief, err := execenv.WriteContextFile(place.CLI, workDir, grant.Prompt)
	if err != nil {
		return runtime.Request{}, home, prior, err
	}
	skills, err := execenv.WriteSkills(place.CLI, workDir, home, grant.Skills)
	if err != nil {
		return runtime.Request{}, home, prior, err
	}
	tools, err := execenv.PlaceTools(execenv.ToolsSpec{
		CLI:     place.CLI,
		WorkDir: workDir,
		Program: o.CallbackProgram,
	})
	if err != nil {
		return runtime.Request{}, home, prior, err
	}
	// What was put here, said plainly, so that what the agent is later shown as its own changes
	// is only what the agent made (FR-020a). Not fatal: a run whose record could not be written
	// works, and the agent merely sees its brief listed among its files.
	if err := execenv.RecordPlaced(workDir, []string{brief, skills, tools.Dir, tools.ConfigFile}); err != nil {
		o.Report(fmt.Errorf("recording what was placed for run %s: %w", grant.RunID, err))
	}
	env, err := execenv.Environ(execenv.EnvSpec{
		CLI:  place.CLI,
		Home: home,
		// The **task** and nothing else, even when the directory above was named after the run:
		// what this says is what the run is *about*, and that is what decides the toolset the
		// agent is handed (FR-013d). A run id smuggled in here would hand an interview the
		// commands of a task nobody assigned it.
		TaskID:    grant.TaskID,
		ProjectID: grant.ProjectID,
		WorkDir:   workDir,
		ToolsDir:  tools.Dir,
		Inherited: os.Environ(),
		Credentials: execenv.Credentials{
			RunID:       grant.RunID,
			RunToken:    grant.RunToken,
			Server:      o.Server,
			DaemonToken: o.DaemonToken,
		},
	})
	if err != nil {
		return runtime.Request{}, home, prior, err
	}
	return runtime.Request{
		CLI:         place.CLI,
		Binary:      place.Binary,
		WorkDir:     workDir,
		Env:         env,
		Message:     grant.Prompt,
		ToolConfig:  tools.ConfigFile,
		ToolServers: tools.Servers,
		Options:     grant.RuntimeOptions,
		// The two values this run must never let out in anything it says (FR-048a). The run's
		// own token goes in through the environment and the message, so it can come back out
		// through either; the machine's is here because losing it is worse than losing the
		// run's, and a net that catches only the lesser one is not a net.
		Secrets: []string{grant.RunToken, o.DaemonToken},
		// The conversation this task was already having, when there is one that may still be
		// carried on (FR-023). Empty is not a failure: it is either the first turn on this task
		// or a thread that could not be picked up, and the second of those comes with a sentence
		// saying so (FR-025).
		Session: handle,
		Restart: restart,
	}, home, prior, nil
}

// carry runs the agent and reports how it went.
func (o RunOptions) carry(
	ctx context.Context, grant Grant, place Workplace, engine runtime.Runtime, req runtime.Request,
) runtime.Outcome {
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
		Status:  o.verdict(err, silent(), endedFromOutside),
		Error:   errorText(err),
		Usage:   outcome.Usage,
		Session: outcome.Session,
		// Only when this run actually failed. An agent can perfectly well *mention* a quota
		// while finishing its work — reading a log, quoting an error it handled — and a
		// verdict attached to a run that completed would take a task nobody is stuck on and
		// put it in front of a person (FR-032).
		Failure: o.walledIn(err, silent(), endedFromOutside, outcome.Failure),
	})
	return outcome
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

// walledIn is the verdict, but only on a run that actually failed.
//
// The reading is the CLI's own words, and words turn up for more than one reason: an agent that
// finishes its work while quoting a quota message it handled has said the sentence without
// hitting the wall. What makes it a verdict is the pair — this run ended badly **and** the
// agent said which wall it was.
//
// A run cut off from outside is excluded for a different reason: this daemon stopping, or the
// server taking the run back, is not a wall a person can clear, and the ending nobody
// classified is the one that gets tried again — which is the correct answer there.
func (o RunOptions) walledIn(runErr error, silent, endedFromOutside bool, said string) string {
	if said == "" || runErr == nil || silent || endedFromOutside {
		return ""
	}
	return said
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
