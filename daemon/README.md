# armarius-daemon

The half of Armarius that runs on your own machine.

The server never reaches in here. It publishes work; this program comes and asks for it. That
direction is the whole design: a laptop behind a closed lid, a home router or a company firewall
needs no inbound port for the agents on it to do their jobs. Your agent CLIs stay where you
installed them, signed in as you, and the work they do happens on your disk.

## Install

Every release ships one archive per platform containing **two** binaries:

| Binary | What it is |
| --- | --- |
| `armarius-daemon` | the program you run |
| `armarius` | the small command an agent uses to call Armarius back during a run |

They ship together and must stay together — the daemon looks for `armarius` beside itself and
refuses to start without it, because an agent handed instructions naming a command that is not
there fails on every call it makes and nothing on either side reports why.

Download the archive for your platform from the releases page, unpack it, and put both files on
your `PATH`.

**Linux and macOS**

```sh
tar -xzf armarius-daemon_<version>_<os>_<arch>.tar.gz
sudo install -m 0755 armarius-daemon armarius /usr/local/bin/
armarius-daemon version
```

On macOS the first run of an unsigned download is blocked by Gatekeeper. Open **System Settings →
Privacy & Security** and allow it there, or clear the quarantine flag yourself:

```sh
xattr -d com.apple.quarantine /usr/local/bin/armarius-daemon /usr/local/bin/armarius
```

**Windows**

Unpack the `.zip` and put both `.exe` files in a directory on your `PATH` — for example
`%LOCALAPPDATA%\Programs\Armarius`.

Then **turn on Developer Mode**: Settings → System → For developers → Developer Mode. Without it,
Windows only lets an administrator create symbolic links, and this daemon needs them. It is not a
convenience. Each run gets a home directory of its own, and the pieces of it that must outlive the
run — above all the agent's session state — are linked out rather than copied. A copy would take
everything the run wrote and then be thrown away with the home, so the agent would lose its memory
of the task and nothing would say so. The daemon therefore **tests** whether it can make a link,
at startup, on the real disk; if it cannot, every workplace on the machine registers as *not
ready* with the reason on it, rather than accepting work it would quietly ruin.

## Link this machine

```sh
armarius-daemon login -server https://your-armarius.example.com
```

It prints a short code and waits. Open the link page in Armarius in your browser, enter the code,
and choose the workspace this machine joins. The machine's token is written to
`~/.armarius/daemon.json` (`%USERPROFILE%\.armarius\daemon.json` on Windows) and never leaves it —
agents are handed a token minted for one run, never this one.

## Run it

```sh
armarius-daemon start
```

It announces the agent CLIs it found here, then stays up: a beat that says the machine is
reachable, a road that carries *there is work, come and ask*, and its own unhurried rhythm of
asking whether or not anything nudged it. Stop it with Ctrl-C.

## Ask it what is going on

```sh
armarius-daemon status        # for a person
armarius-daemon status -json  # for a script
```

This asks the server **nothing**, which is the point of it. From the Machines screen on the web, a
machine that is switched off, a daemon that died, a token that expired and an agent CLI that was
uninstalled all look identical: everything simply stops arriving. Three of those four can only be
told apart from inside the machine. `status` exits 0 whether or not a daemon is running — *nothing
is running here* is the answer to the question, not a failure to answer it.

## Running it as a service

A unit file for systemd:

```ini
[Unit]
Description=Armarius daemon
After=network-online.target

[Service]
ExecStart=/usr/local/bin/armarius-daemon start
Restart=on-failure
# Must be longer than drain_patience below. See "Upgrading" — this is the one
# number that has to be set in two places at once.
TimeoutStopSec=120

[Install]
WantedBy=default.target
```

Install it as a **user** service (`~/.config/systemd/user/armarius-daemon.service`, then
`systemctl --user enable --now armarius-daemon`). The agent CLIs on this machine are signed in as
you and read their configuration from your home directory; a daemon running as `root` or as its
own service account would be a daemon whose agents are signed in as nobody.

## Upgrading

Stopping the daemon stops it **asking** for work immediately. The work it has already taken is
allowed to finish: it waits up to `drain_patience`, then cuts whatever is still going and says
which runs those were. Only when nothing is left running does it hand its workplaces back, so its
agents go offline at once instead of after the missed-beat threshold.

So an upgrade is: stop, replace the binaries, start. A daemon starting while the previous one is
still finishing its runs **waits** for it rather than registering on top of it; a daemon starting
beside one that is not going anywhere refuses to start at all and names the process holding the
machine, because two daemons on one machine would quietly run up to twice the concurrency you set.

`TimeoutStopSec` and `drain_patience` are one decision written in two places. Whichever is
smaller is the one in force: if the service manager's timeout is shorter, it destroys the process
mid-drain — which cuts the run **and** skips the goodbye, leaving the stop looking like a crash.
Raise both or neither.

## Settings

Everything below goes in the same `~/.armarius/daemon.json` that `login` wrote. Unknown keys are
ignored, so your settings and the token share a file without either knowing about the other. A
missing file is fine — the defaults are what a machine that has never been tuned runs on.
Durations are written the way you say them: `"5s"`, `"10m"`, `"24h"`.

| Key | Default | What it decides |
| --- | --- | --- |
| `max_concurrent_runs` | `5` | how many runs this machine holds at once. Advice: the server keeps its own ceiling and takes the smaller of the two |
| `heartbeat_interval` | `"15s"` | how often this machine says it is alive. Three missed beats and every workplace on it is treated as unavailable |
| `poll_interval` | `"5s"` | how often it asks for work when nothing has nudged it. This is the fallback road, not the main one |
| `claim_lease` | `"120s"` | how long a claimed run stays this machine's before the server takes it back |
| `drain_patience` | `"60s"` | how long a stopping daemon lets its runs finish before cutting them. Pair it with `TimeoutStopSec` |
| `tool_result_inline_limit_bytes` | `2048` | how much of a tool's output travels to the server inside the event. Past it, only the opening bytes, the true size, and the fact that it was cut — never the rest, which does not leave this machine |
| `sweep_interval` | `"2h"` | how often it looks over what it has left on its own disk |
| `work_dir_retention` | `"24h"` | how long a task's working directory survives after the server said that task was finished with |
| `session_retention` | `"336h"` | how long a conversation may sit idle and still be carried on |
| `orphan_retention` | `"72h"` | how long a working directory the server cannot account for survives. Longer than `work_dir_retention` on purpose: that clock acts on something the server stated, this one acts on the absence of a statement |

Point `start` at a different file with `-config`, which is how one machine runs two daemons
against two servers.

## Built on Multica

Armarius is built on [Multica](https://github.com/multica-ai/multica). The daemon's shape — a
machine that asks for work rather than being reached, an agent CLI given a home of its own per
run, capabilities measured from the binary rather than assumed from its name — is inherited from
theirs. No Multica source is used here: this daemon is written from scratch in Go against
Armarius's own server, and everything Armarius says to an agent is written independently.
