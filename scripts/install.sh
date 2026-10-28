#!/usr/bin/env bash
# Armarius daemon installer.
#
#   curl -fsSL https://raw.githubusercontent.com/gnust-company/A.R.MARIUS/main/scripts/install.sh | bash
#
# Installs (or upgrades) the two programs that make up the daemon side of Armarius:
# `armarius-daemon`, which you run, and `armarius`, which the agents it starts use to call
# Armarius back. They ship in one archive and are installed together — see install_binaries.
#
# Shape inherited from Multica's own installer (FR-039b): latest tag read from the redirect on
# /releases/latest rather than the API, so there is no token and no rate limit, and the PATH line
# written for you when it is needed. One thing is ours: the download is checksum-verified before
# anything is installed. Piping a script from the network into a shell already asks for trust;
# spending the one request it takes to check what came down the wire is the least this can do.
#
# Where it goes changed on 2026-10-28 (FR-008n): **$HOME/.local/bin, no sudo**. The daemon keeps
# itself up to date by replacing its own file, and it runs as you — so it has to live somewhere you
# can write. This used to put it in /usr/local/bin with sudo, which is root's, and on every machine
# installed that way the daemon could never update itself. Claude Code installs into your home for
# the same reason. Running this again on such a machine moves it, removes the old copy, and
# restarts the daemon from the new place.
set -euo pipefail

REPO="gnust-company/A.R.MARIUS"
RELEASES="${ARMARIUS_RELEASES:-https://github.com/${REPO}/releases}"
RELEASES="${RELEASES%/}"
DAEMON="armarius-daemon"
CALLBACK="armarius"
GUIDE="https://github.com/${REPO}/blob/main/docs/machines-and-daemon.md"

if [ -t 1 ] || [ -t 2 ]; then
  BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'
  CYAN='\033[0;36m'; RESET='\033[0m'
else
  BOLD=''; GREEN=''; YELLOW=''; RED=''; CYAN=''; RESET=''
fi

info() { printf "${BOLD}${CYAN}==> %s${RESET}\n" "$*"; }
ok()   { printf "${BOLD}${GREEN}✓ %s${RESET}\n" "$*"; }
warn() { printf "${BOLD}${YELLOW}⚠ %s${RESET}\n" "$*" >&2; }
fail() { printf "${BOLD}${RED}✗ %s${RESET}\n" "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ── Which build this machine needs ───────────────────────────────────────────────────────────

detect_platform() {
  case "$(uname -s)" in
    Darwin) OS="darwin" ;;
    Linux)  OS="linux" ;;
    MINGW*|MSYS*|CYGWIN*)
      fail "This script does not support Windows. Install by hand for now — unpack the .zip from
  ${RELEASES}/latest and put both .exe files on your PATH:
  ${GUIDE}" ;;
    *) fail "Unsupported operating system: $(uname -s). Armarius supports macOS, Linux, and Windows." ;;
  esac

  case "$(uname -m)" in
    x86_64|amd64)   ARCH="amd64" ;;
    aarch64|arm64)  ARCH="arm64" ;;
    *) fail "Unsupported architecture: $(uname -m)." ;;
  esac
}

# The tag of the newest release, read off the redirect that /releases/latest answers with.
# No API call, so no token and no rate limit on a machine that has never talked to GitHub.
latest_tag() {
  curl -fsSLI -o /dev/null -w '%{url_effective}' "${RELEASES}/latest" 2>/dev/null \
    | sed 's|.*/tag/||' | tr -d '\r\n' || true
}

installed_version() {
  "$1" version 2>/dev/null | awk 'NR==1{print $2}' || true
}

# Whether $BIN_DIR already holds this exact release, whole.
#
# Two things this deliberately does **not** do, both learned by measuring:
#
# It does not ask PATH. It used to — `command -v armarius-daemon` — which meant that somebody who
# named ARMARIUS_BIN_DIR, with a copy of the same version sitting anywhere else on their PATH, was
# told "already the latest" and got an empty directory. Naming a directory is asking for a
# placement, not asking whether the program is reachable from somewhere.
#
# And it does not ask about the daemon alone. A directory holding a current daemon with no
# `armarius` beside it is exactly the broken state the staged install goes to such lengths to
# prevent — and reporting *already the latest* into it would leave the installer unable to repair
# the one fault it knows most about.
already_current() {
  local tag="$1"
  [ -x "$BIN_DIR/$DAEMON" ] || return 1
  [ -x "$BIN_DIR/$CALLBACK" ] || return 1
  [ "$(installed_version "$BIN_DIR/$DAEMON")" = "${tag#v}" ]
}

# ── Where the two programs go ────────────────────────────────────────────────────────────────

add_to_path() {
  local dir="$1" line="export PATH=\"$1:\$PATH\""
  # A scripted install — CI, a container image, a test of this very script — has no business
  # rewriting somebody's shell configuration, and the first run of this installer proved why:
  # it wrote a throwaway directory into a real ~/.bashrc. Say where to put the line instead.
  if [ -n "${ARMARIUS_NO_PATH_EDIT:-}" ]; then
    warn "$dir is not on your PATH. Add it with: $line"
    return
  fi

  # One file, picked from the shell in use. Writing the same export into .bashrc and .zshrc and
  # .profile at once leaves two of them as litter in a config somebody else has to read later.
  local rc
  case "${SHELL:-}" in
    */zsh)  rc="$HOME/.zshrc" ;;
    */bash) rc="$HOME/.bashrc" ;;
    *)      rc="$HOME/.profile" ;;
  esac

  # Matched as the whole line it would be, not as a substring anywhere in the file: the directory
  # name can appear in a comment, or inside a longer path, and either would silently skip the edit.
  if [ -f "$rc" ] && grep -qxF "$line" "$rc"; then
    warn "$dir is already on your PATH in $rc — open a new shell."
    return
  fi

  if printf '\n# Added by the Armarius installer\n%s\n' "$line" >> "$rc" 2>/dev/null; then
    warn "Added $dir to your PATH in $rc — open a new shell, or run: $line"
  else
    warn "$dir is not on your PATH, and $rc could not be written. Add it with: $line"
  fi
}

# Answers where to put them, and whether sudo is needed to do it.
#
# Your own $HOME/.local/bin unless you name somewhere else, because the daemon replaces its own
# file to update itself and runs as you (FR-008n). Somebody who sets ARMARIUS_BIN_DIR to a folder
# only root can write still gets it there, with sudo — and is told in so many words that the
# daemon will not be able to update itself in it.
choose_bin_dir() {
  local wanted="${ARMARIUS_BIN_DIR:-$HOME/.local/bin}"

  [ -d "$wanted" ] || mkdir -p "$wanted" 2>/dev/null || true

  if [ -d "$wanted" ] && [ -w "$wanted" ]; then
    BIN_DIR="$wanted"; SUDO=""
    return
  fi
  [ -n "${ARMARIUS_BIN_DIR:-}" ] || fail "Could not create or write ${wanted}."
  have sudo || fail "ARMARIUS_BIN_DIR is ${wanted}, which cannot be written to, and there is no sudo here."

  BIN_DIR="$wanted"; SUDO="sudo"
  info "$wanted needs root; you may be asked for your password."
  warn "The daemon cannot update itself in ${wanted}: it runs as you, and that folder is root's. Leave ARMARIUS_BIN_DIR unset to install into your own home folder instead."
}

# Removes copies an earlier install left on PATH — in /usr/local/bin, usually, from before this
# installed into your home. A copy found earlier on PATH is the one every `armarius-daemon` you type
# runs, so leaving it would hide the one just installed.
#
# Only folders on PATH are looked at: a copy nothing can find is in nobody's way, and a folder this
# script was not told about is not its business. Only a folder holding the daemon itself counts, so
# an unrelated program that happens to be called `armarius` is never touched.
remove_leftovers() {
  local dir seen=":$BIN_DIR:" IFS=':'
  for dir in $PATH; do
    [ -n "$dir" ] || continue
    case "$seen" in *":$dir:"*) continue ;; esac
    seen="$seen$dir:"
    [ -f "$dir/$DAEMON" ] || continue

    local old=("$dir/$DAEMON")
    [ -f "$dir/$CALLBACK" ] && old+=("$dir/$CALLBACK")
    if [ -w "$dir" ] && rm -f "${old[@]}"; then
      ok "Removed the old copy in ${dir}."
      continue
    fi
    if have sudo; then
      info "Removing the old copy in ${dir}, which needs root; you may be asked for your password."
      if sudo rm -f "${old[@]}"; then
        ok "Removed the old copy in ${dir}."
        continue
      fi
    fi
    warn "An older ${DAEMON} is still in ${dir} and is found before this one. Remove it with: sudo rm -f $(printf '%s ' "${old[@]}")"
  done
}

# Puts a running daemon onto the program just installed, if it runs from somewhere else.
#
# A daemon running from this same folder needs nothing: it notices its file changed and restarts
# into it by itself once it is idle (FR-008n). One running from the folder an older install used
# does not — its own file may be gone — so it is stopped, which lets the runs it holds finish, and
# started again from here. A daemon under a systemd unit is left to systemd, with what to change.
restart_if_elsewhere() {
  local status pid exe
  status=$("$BIN_DIR/$DAEMON" status -json 2>/dev/null) || return 0
  printf '%s' "$status" | grep -q '"daemon_running": *true' || return 0
  pid=$(printf '%s' "$status" | sed -n 's/.*"daemon_pid": *\([0-9][0-9]*\).*/\1/p' | head -1)
  [ -n "$pid" ] || return 0

  if [ -e "/proc/$pid/exe" ]; then
    exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
  else
    exe=$(ps -o comm= -p "$pid" 2>/dev/null || true)
  fi
  exe="${exe% (deleted)}"
  [ "$exe" = "$BIN_DIR/$DAEMON" ] && return 0

  if have systemctl && systemctl --user is-active --quiet armarius-daemon 2>/dev/null; then
    warn "The daemon runs as the systemd user service armarius-daemon, from ${exe:-another place}. Point its ExecStart at ${BIN_DIR}/${DAEMON}, then run: systemctl --user daemon-reload && systemctl --user restart armarius-daemon"
    return 0
  fi

  info "Restarting the daemon (process ${pid}) so it runs from ${BIN_DIR}. It finishes the runs it holds first."
  if "$BIN_DIR/$DAEMON" stop && "$BIN_DIR/$DAEMON" start; then
    ok "The daemon now runs ${BIN_DIR}/${DAEMON}."
  else
    warn "Could not restart the daemon. Do it with: ${DAEMON} stop && ${DAEMON} start"
  fi
}

# ── Download, check, install ─────────────────────────────────────────────────────────────────

install_binaries() {
  local tag="$1" version="${1#v}"
  local archive="${DAEMON}_${version}_${OS}_${ARCH}.tar.gz"
  local tmp; tmp=$(mktemp -d)
  # shellcheck disable=SC2064  # `tmp` must expand now, while it still names this directory.
  trap "rm -rf '$tmp'" EXIT

  info "Downloading ${archive}"
  curl -fsSL "${RELEASES}/download/${tag}/${archive}" -o "$tmp/$archive" \
    || fail "Could not download ${archive}. Is there a release for ${OS}/${ARCH} at ${RELEASES}/tag/${tag}?"

  # Verified before anything is unpacked, let alone installed — and *verified or refused*, with no
  # third outcome. A warn-and-continue here would hollow out the whole point: somebody who can
  # interfere with the download can just as easily make checksums.txt fail to arrive, and the
  # install would proceed on unchecked bytes while printing a tick at the end.
  curl -fsSL "${RELEASES}/download/${tag}/checksums.txt" -o "$tmp/checksums.txt" \
    || fail "Could not download checksums.txt for ${tag}, so ${archive} cannot be verified. Nothing was installed."

  # The expected hash is read out by name rather than handed to `-c`: the file lists every
  # platform's archive, only one of which is on this disk, and the flag for that (--ignore-missing)
  # is missing from the shasum that older macOS ships. Pulling one line out works everywhere and
  # makes "this release does not list my archive" a failure in its own words.
  local want
  want=$(awk -v f="$archive" '$2 == f || $2 == "*" f { print $1; exit }' "$tmp/checksums.txt")
  [ -n "$want" ] || fail "checksums.txt for ${tag} does not list ${archive}. Nothing was installed."

  local got
  if   have sha256sum; then got=$(sha256sum "$tmp/$archive" | awk '{print $1}')
  elif have shasum;    then got=$(shasum -a 256 "$tmp/$archive" | awk '{print $1}')
  else fail "Neither sha256sum nor shasum is here, so ${archive} cannot be verified. Nothing was installed."
  fi

  [ "$got" = "$want" ] \
    || fail "Checksum mismatch on ${archive}: expected ${want}, got ${got}. The download is not what this release published — do not use it."
  ok "Checksum verified"

  tar -xzf "$tmp/$archive" -C "$tmp" "$DAEMON" "$CALLBACK" \
    || fail "The archive did not contain both ${DAEMON} and ${CALLBACK}."
  chmod +x "$tmp/$DAEMON" "$tmp/$CALLBACK"

  # Both, or neither — and *neither* must mean "what was here before", not "nothing".
  #
  # `armarius-daemon` looks for `armarius` beside itself and refuses to start without it, so a
  # half-finished install leaves a daemon that cannot run and says so only when somebody
  # eventually tries. The first version of this installed the daemon over the top and deleted it
  # again if the second one failed — which on an upgrade destroyed a working installation and left
  # the machine with nothing, worse than the half-state it was written to avoid.
  #
  # So both land beside their targets under a `.new` name first, where nothing depends on them,
  # and only once both are there do they move into place. A failure at any point before that
  # leaves whatever was already installed exactly as it was.
  local staged=""
  for name in "$DAEMON" "$CALLBACK"; do
    if ! $SUDO install -m 0755 "$tmp/$name" "$BIN_DIR/$name.new"; then
      # shellcheck disable=SC2086  # `staged` is a deliberate word list of paths we just wrote.
      [ -n "$staged" ] && $SUDO rm -f $staged
      fail "Could not write ${name} into ${BIN_DIR}. Nothing was changed."
    fi
    staged="$staged $BIN_DIR/$name.new"
  done

  for name in "$DAEMON" "$CALLBACK"; do
    $SUDO mv -f "$BIN_DIR/$name.new" "$BIN_DIR/$name" \
      || fail "Could not put ${name} in place in ${BIN_DIR}. Left ${BIN_DIR}/${name}.new behind for you to move by hand."
  done

  ok "Installed ${DAEMON} and ${CALLBACK} to ${BIN_DIR}"

  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) add_to_path "$BIN_DIR" ;;
  esac
}

# ── What this run should actually do ─────────────────────────────────────────────────────────

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --help|-h)
        cat <<'USAGE'
Usage: install.sh

Installs or upgrades the Armarius daemon and the callback program it ships with.

Environment variables:
  ARMARIUS_BIN_DIR       Where to install (default: $HOME/.local/bin). A folder only root can
                         write is installed into with sudo, but the daemon cannot update
                         itself there.
  ARMARIUS_VERSION       A specific tag to install, e.g. v0.1.0 (default: the latest release)
  ARMARIUS_RELEASES      The releases page to install from (default: this project's on GitHub),
                         for a machine that takes releases from an internal mirror
  ARMARIUS_NO_PATH_EDIT  Set to any value to print the PATH line instead of writing it into
                         your shell configuration

Next steps after installing:
  armarius-daemon login -server <your Armarius URL>
  armarius-daemon start

Guide: https://github.com/gnust-company/A.R.MARIUS/blob/main/docs/machines-and-daemon.md
USAGE
        exit 0 ;;
      *) warn "Unknown option: $1" ;;
    esac
    shift
  done

  have curl || fail "curl is required and was not found."
  have tar  || fail "tar is required and was not found."
  detect_platform

  local tag="${ARMARIUS_VERSION:-}"
  if [ -z "$tag" ]; then
    tag=$(latest_tag)
    [ -n "$tag" ] || fail "Could not work out the latest release. Check your network, or set ARMARIUS_VERSION."
  fi

  # Where these go is settled before asking whether they are already there, because the answer
  # depends on the where.
  choose_bin_dir

  # Already here, whole, and already current? Say so and stop, rather than reinstalling the same
  # bytes — but still clear an older copy off PATH and move a daemon still running from one: a
  # machine half way through moving from /usr/local/bin is exactly the one that runs this twice.
  if already_current "$tag"; then
    ok "${DAEMON} ${tag#v} is already the latest, in ${BIN_DIR}."
    remove_leftovers
    restart_if_elsewhere
    exit 0
  fi
  if [ -x "$BIN_DIR/$DAEMON" ]; then
    local here; here=$(installed_version "$BIN_DIR/$DAEMON")
    if [ -n "$here" ] && [ "$here" != "${tag#v}" ]; then
      info "${DAEMON} ${here} is in ${BIN_DIR}; ${tag} is available — upgrading."
    elif [ ! -x "$BIN_DIR/$CALLBACK" ]; then
      info "${BIN_DIR} has ${DAEMON} but no ${CALLBACK} — repairing."
    fi
  fi

  install_binaries "$tag"

  # Installed is not the same as runnable, and the difference is what a new shell hides.
  if ! "$BIN_DIR/$DAEMON" version >/dev/null 2>&1; then
    fail "${DAEMON} was installed but will not run. Try ${BIN_DIR}/${DAEMON} version to see why."
  fi
  ok "$("$BIN_DIR/$DAEMON" version)"

  remove_leftovers
  restart_if_elsewhere

  printf '\n'
  info "Next: connect this machine"
  printf "     ${BOLD}%s login -server <your Armarius URL>${RESET}\n" "$DAEMON"
  printf "     ${BOLD}%s start${RESET}\n\n" "$DAEMON"
  printf "  Guide: ${CYAN}%s${RESET}\n" "$GUIDE"
}

main "$@"
