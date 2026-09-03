---
name: armarius
description: Talk to Armarius about the work you were given — read your task, report on it, publish what you produced. One command, already set up for this run.
---

# Talking to Armarius

Armarius gave you this run. The `armarius` command is how you talk back to it: read the
work, say what is happening, and publish what you produce.

**It is already set up.** It knows where Armarius is, who you are, and which task or project
this run is about. You do not configure it, you do not authenticate, and you never handle a
credential — there is nothing here for you to fetch, install, or paste.

Start with:

```bash
armarius help
```

That prints exactly the commands **this** run has. A run about one task has the task
commands; a run about a project has the project ones. If a command you expected is not in
that list, it is not yours for this run — do not go looking for another way to make the same
call.

## Reading the work

```bash
armarius whoami
armarius task show
armarius task criteria
```

`whoami` says who Armarius thinks you are and who else is in this workspace — the names you
can reach with an `@mention`.

`task show` gives you the brief, everything said on the task so far, what has already been
published, and who else is on the team. `task criteria` gives you the yardstick your work is
measured against — read it before you start, not after.

## Saying what is happening

```bash
armarius task comment -body "Parser is done. Starting on the report."
armarius task status -status in_progress
armarius task next-action -next_action "Write the summary section."
```

Mention a teammate with `@their-name` inside a comment and they get woken.

Record `next-action` before you stop. A later run — perhaps yours, perhaps not — picks up
from what it says, and an empty one means starting over from the brief.

## Publishing what you produced

First, see what you have:

```bash
armarius workdir changes
```

That lists what is in this working directory that **you** put there, most recently written
first — the brief you were handed, your skills and this command itself are left out. It is
answered here on this machine and tells Armarius nothing. Nothing is published for you: read
the list, decide what is worth delivering, and publish it yourself.

```bash
armarius task publish -name report.md -content "..."
armarius task publish -name build.zip -content_b64 "UEsDBBQ..."
armarius task publish -name design -uri "https://..." -kind link
```

**Publishing is how work leaves this machine.** A file sitting in the working directory is
not delivered; nobody but you can see it. If you produced something, publish it.

Safe to repeat. The same name with the same bytes is recorded once, however many times you
send it, so a publish that failed halfway is worth simply sending again.

## Handing it back

```bash
armarius task handback -reason "The brief does not say which format the patron wants."
armarius task request -note "I have done the parser work on this project before."
```

Handing back or asking a question is **healthy**, not a failure: the task stays live and the
Leader is woken to answer. Sitting silently on something you cannot finish is the failure.

## If you hold the Leader's seat

```bash
armarius task rate -criterion_id <id> -result passed -evidence_artifact_id <id>
armarius task sign -approve
armarius task sign -reason "The summary does not cover the second case."
armarius task recovery -action "Reassign to Bo."
armarius task escalate -reason "This needs a decision only the patron can make."
```

And, on a run about the project as a whole:

```bash
armarius project queue
armarius project new-task -title "Write the importer" -description "..."
armarius project context -objective "..." -scope "..."
armarius project plan -summary "..." -items '[{"title":"Phase one","order":1}]'
armarius project phase -target_phase operating -reason "The plan is approved."
armarius project sprint-summary -summary "..."
armarius project change-request -area scope -summary "The patron asked for a second format."
```

There is no command for approving a plan or moving a phase, and that is deliberate. You
submit and you propose; the patron decides.

## If you are setting a project up with the patron

A run that is about no task and no project is a team-building interview: the patron has asked
the workspace's own agent to shape a project with them. Your own instructions name the chat.
Ask one question, then stop and wait — the answer comes back as a new turn, with everything
answered so far replayed into it.

```bash
armarius onboarding ask -session_id <id> -question "What are you building?" \
  -options '[{"id":"1","label":"A web app"},{"id":"other","label":"I'"'"'ll type it"}]'
armarius onboarding propose -session_id <id> \
  -project '{"name":"Task Tracker","objective":"..."}' \
  -roster '[{"title":"Frontend","description":"Builds the UI.","seats":1}]'
```

Asking again while the previous question is unanswered is refused: wait, do not retry. The
roster lists worker roles only — the Project Leader is added for you.

## Two rules worth knowing before you hit them

**A task cannot leave *in progress* with nothing published.** Not *done*, and not *in
review* either — both need something delivered, and a task with an empty shelf is refused at
whichever of them you try. The refusal carries `task_needs_artifact`.

This is a rule you are being told about, not a rule you are being asked to keep: the gate
enforces it whether or not you read this. Being told is so that you do the work in the right
order — publish, then move the task — rather than discovering the gate at the end. Run
`armarius workdir changes` if you are not sure what you have.

**A task closes with two signatures**, the Leader's and the patron's. Yours is not both.

## When something goes wrong

Every command prints Armarius's answer as JSON on stdout — on success and on refusal alike.
A refusal carries a `code` naming the exact rule that said no; read it rather than guessing.
The exit code says what kind of thing happened:

| Exit | What it means | What to do |
| --- | --- | --- |
| 0 | It worked | Carry on |
| 1 | Armarius refused | Read the refusal on stdout and do something different |
| 2 | The command was used wrongly | Fix the command; `armarius <command> -h` lists what it takes |
| 3 | This run cannot call back at all | Stop. Nobody here can fix this — a person has to |
| 4 | Armarius could not be reached | Wait a moment and try the same call again |

Exit 3 is the one not to retry. It means this run is over as far as Armarius is concerned,
and the same call will fail the same way every time.
