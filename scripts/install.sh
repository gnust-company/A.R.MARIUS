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
# /releases/latest rather than the API, so there is no token and no rate limit; /usr/local/bin
# first, sudo only if it is not writable, and $HOME/.local/bin as the last resort with the PATH
# line written for you. One thing is ours: the download is checksum-verified before anything is
# installed. Piping a script from the network into a shell already asks for trust; spending the
# one request it takes to check what came down the wire is the least this can do.
set -euo pipefail

REPO="gnust-company/A.R.MARIUS"
RELEASES="https://github.com/${REPO}/releases"
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
# Falling back to $HOME/.local/bin is for the **default** only. Somebody who sets ARMARIUS_BIN_DIR
# has said where they want this, and quietly installing somewhere else — then naming that
# somewhere else in a line they may not read — is how a person ends up running last month's build
# out of a directory they had forgotten about.
choose_bin_dir() {
  local wanted="${ARMARIUS_BIN_DIR:-/usr/local/bin}"
  local named="${ARMARIUS_BIN_DIR:+yes}"

  [ -d "$wanted" ] || mkdir -p "$wanted" 2>/dev/null || true

  if [ -d "$wanted" ] && [ -w "$wanted" ]; then
    BIN_DIR="$wanted"; SUDO=""
    return
  fi
  if have sudo; then
    BIN_DIR="$wanted"; SUDO="sudo"
    info "$wanted needs root; you may be asked for your password."
    return
  fi
  if [ -n "$named" ]; then
    fail "ARMARIUS_BIN_DIR is ${wanted}, which cannot be written to, and there is no sudo here."
  fi

  BIN_DIR="$HOME/.local/bin"; SUDO=""
  mkdir -p "$BIN_DIR" || fail "Could not create ${BIN_DIR}."
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

  choose_bin_dir

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
  ARMARIUS_BIN_DIR       Where to install (default: /usr/local/bin, then $HOME/.local/bin)
  ARMARIUS_VERSION       A specific tag to install, e.g. v0.1.0 (default: the latest release)
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

  # Already here and already current? Say so and stop, rather than reinstalling the same bytes.
  if have "$DAEMON"; then
    local here; here=$(installed_version "$DAEMON")
    if [ -n "$here" ] && [ "$here" = "${tag#v}" ]; then
      ok "${DAEMON} ${here} is already the latest."
      exit 0
    fi
    [ -n "$here" ] && info "${DAEMON} ${here} is installed; ${tag} is available — upgrading."
  fi

  install_binaries "$tag"

  # Installed is not the same as runnable, and the difference is what a new shell hides.
  if ! "$BIN_DIR/$DAEMON" version >/dev/null 2>&1; then
    fail "${DAEMON} was installed but will not run. Try ${BIN_DIR}/${DAEMON} version to see why."
  fi
  ok "$("$BIN_DIR/$DAEMON" version)"

  printf '\n'
  info "Next: connect this machine"
  printf "     ${BOLD}%s login -server <your Armarius URL>${RESET}\n" "$DAEMON"
  printf "     ${BOLD}%s start${RESET}\n\n" "$DAEMON"
  printf "  Guide: ${CYAN}%s${RESET}\n" "$GUIDE"
}

main "$@"
