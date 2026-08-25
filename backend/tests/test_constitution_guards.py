"""Static guards for the three constitution rules no single đợt owns (T155, T157, T158).

Đa tenant và Cổng Done are checked by behaviour tests elsewhere — there is a request to
make and a response to assert. These three are different: they are rules about the
**shape** of the code, and the only way to break them is to write a line nobody looks at
again. A one-off review catches the line that exists today; a check that runs with the
suite catches the one written next month.

Reading the frontend from a pytest file is deliberate. The repo has no JS test runner, and
adding one to host three assertions would cost more than it guards. If a runner ever
arrives, these three move.

  * III — Trung lập adapter (FR-083)   → no runtime branching in domain/ or application/
  * III — Trung lập adapter (FR-035/037) → those layers never learn *where* work runs either
  * IV — Đẩy, không hỏi-vòng (FR-080)  → no refetch timer in the UI
  * VI — Tiếng Việt cho người dùng (FR-084) → diacritics kept; nothing hardcoded outside i18n
  * FR-060                             → the worker self-claim route stays gone
"""

from __future__ import annotations

import io
import re
import tokenize
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FRONTEND = REPO / "frontend" / "src"


def _sources(*roots: Path) -> list[Path]:
    return sorted(p for root in roots for p in root.rglob("*.py"))


def _python_code_lines(path: Path) -> list[str]:
    """The file with every comment and string literal blanked out, line numbers intact.

    Needed because these checks look for a *pattern in code*, and a docstring explaining
    why the pattern is banned would otherwise trip the very check it documents.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    blanked = [list(line) for line in lines]
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    for tok in tokens:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (r1, c1), (r2, c2) = tok.start, tok.end
        for row in range(r1, r2 + 1):
            if row - 1 >= len(blanked):
                break
            chars = blanked[row - 1]
            start = c1 if row == r1 else 0
            end = c2 if row == r2 else len(chars)
            for col in range(start, min(end, len(chars))):
                chars[col] = " "
    return ["".join(chars) for chars in blanked]


def _ts_code_lines(path: Path) -> list[str]:
    """Same idea for TypeScript/TSX: `//` to end of line, and `/* … */` across lines
    (which is what a `{/* … */}` JSX comment is)."""
    out: list[str] = []
    in_block = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line, i, kept = raw, 0, []
        while i < len(line):
            if in_block:
                close = line.find("*/", i)
                if close == -1:
                    i = len(line)
                    break
                in_block = False
                i = close + 2
                continue
            if line.startswith("//", i):
                break
            if line.startswith("/*", i):
                in_block = True
                i += 2
                continue
            kept.append(line[i])
            i += 1
        out.append("".join(kept))
    return out


# ── III. Trung lập adapter (FR-083) ──────────────────────────────────────────────

# A use case asking *which runtime is this* is a use case that will be edited every time a
# runtime is added, by someone who has to guess what the other branches were for. The
# difference belongs behind `MariusAdapter` — see `skill_install_steps`, which is exactly
# the instruction that used to live here as an if/elif chain.
_RUNTIME_BRANCH = re.compile(
    r"adapter_type\s*(==|!=|\s+in\s+)|\.type\s*(==|!=)\s*[\"']", re.ASCII
)


def test_the_business_layers_never_branch_on_which_runtime_it_is() -> None:
    offenders: list[str] = []
    for path in _sources(BACKEND / "armarius" / "domain", BACKEND / "armarius" / "application"):
        for i, line in enumerate(_python_code_lines(path), 1):
            if _RUNTIME_BRANCH.search(line):
                offenders.append(f"{path.relative_to(BACKEND)}:{i}  {line.strip()}")
    assert not offenders, (
        "Tầng nghiệp vụ không được nhánh mã theo loại agent (FR-083, Hiến pháp III).\n"
        "Đưa phần khác nhau xuống sau hợp đồng `MariusAdapter`:\n  " + "\n  ".join(offenders)
    )


# ── III. Ranh giới nơi việc chạy (FR-035, FR-037, SC-008) ───────────────────────

# The same principle as the check above, one level out. That one stops the business layers
# asking *which kind of agent* this is; this one stops them learning *where* the work runs.
#
# Both words matter for the same reason. A use case that knows a task runs on a machine
# under a daemon is a use case that has to be reopened the day work runs somewhere else,
# by someone who has to reconstruct what each branch was protecting. The place work runs
# belongs to infrastructure; what reaches the business layers is a slot that is free or a
# slot that is taken, and it reads the same whichever side of the wire filled it in.
#
# What this buys, concretely, is SC-008: adding a new kind of agent CLI touches the bottom
# layer and nothing else — and the proof is a check that runs with the suite rather than a
# claim in a design document.
_ELSEWHERE_WORDS = frozenset(
    {
        "daemon",
        "daemons",
        "machine",
        "machines",
        "runtime",
        "runtimes",
        "workplace",
        "workplaces",
    }
)

# Python's own names, which cannot be renamed and mean nothing about where work runs.
_NOT_OURS = frozenset({"RuntimeError", "RuntimeWarning"})

# Splits an identifier into its words, both conventions at once, so `machine_id` and
# `MachineAdapter` are both caught while `RuntimeError`-shaped names stay intact for the
# allow-list above to handle.
_IDENT_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+")


def _identifier_words(name: str) -> set[str]:
    return {w.lower() for w in _IDENT_WORD.findall(name)}


def _names_in(path: Path) -> list[tuple[int, str]]:
    """Every identifier in the file, with its line. Comments and strings never produce a
    NAME token, so an explanation of the rule cannot trip the rule."""
    text = path.read_text(encoding="utf-8")
    return [
        (tok.start[0], tok.string)
        for tok in tokenize.generate_tokens(io.StringIO(text).readline)
        if tok.type == tokenize.NAME
    ]


def test_the_business_layers_never_learn_where_the_work_runs() -> None:
    offenders: list[str] = []
    for path in _sources(BACKEND / "armarius" / "domain", BACKEND / "armarius" / "application"):
        for line_no, name in _names_in(path):
            if name in _NOT_OURS:
                continue
            if _identifier_words(name) & _ELSEWHERE_WORDS:
                offenders.append(f"{path.relative_to(BACKEND)}:{line_no}  {name}")
    assert not offenders, (
        "Tầng nghiệp vụ không được biết việc chạy ở đâu (FR-035, FR-037, SC-008,\n"
        "Hiến pháp III). Đặt tên theo thứ tầng này thật sự cần — một chỗ chạy còn trống\n"
        "hay đã bị chiếm — rồi để hạ tầng trả lời:\n  " + "\n  ".join(offenders)
    )


# ── FR-060. Thợ vẫn không được tự nhận việc ─────────────────────────────────────

# Removed in spec 001 and it stays removed: a worker does not take work, it asks, and the
# Leader — the only one who can see the whole board — decides.
#
# `POST /daemon/runs/claim` is not this route and is not checked here. That one is the
# transport for a task the Leader has **already** assigned, carrying it from the server
# down to wherever it will run; the assignee it names never changes. The two live in
# different files because they are different things (FR-060), and the check is scoped to
# the agent-facing router for exactly that reason.

_AGENT_ROUTER = BACKEND / "armarius" / "presentation" / "api" / "agent.py"

# Shape 1: the route comes back under its own name.
_CLAIM_ROUTE = re.compile(
    r"@router\.(?:post|put|patch)\(\s*[\"'][^\"']*(?:claim|take)", re.IGNORECASE
)

# Shape 2: the route comes back under an innocent name and calls the assignment use case
# directly. Note this does not match `request_assignment`, which is the sanctioned "ask the
# Leader" path and assigns nobody.
_ASSIGNS_DIRECTLY = re.compile(r"\.assign(?:_within)?\s*\(")

# Shape 3: a handler names the caller as the assignee of its own work. This is the one that
# matters most — it is what "self-claim" means, whatever the route is called.
_NAMES_ITSELF = re.compile(r"assign\w*\s*=\s*marius\.id")


def test_a_worker_still_cannot_take_work_for_itself() -> None:
    offenders: list[str] = []
    for i, raw in enumerate(_AGENT_ROUTER.read_text(encoding="utf-8").splitlines(), 1):
        # Route paths are string literals, so this shape has to be read off the raw line;
        # skipping whole-line comments keeps a note *about* the rule from tripping it.
        if not raw.lstrip().startswith("#") and _CLAIM_ROUTE.search(raw):
            offenders.append(f"agent.py:{i}  {raw.strip()}")
    for i, line in enumerate(_python_code_lines(_AGENT_ROUTER), 1):
        if _ASSIGNS_DIRECTLY.search(line) or _NAMES_ITSELF.search(line):
            offenders.append(f"agent.py:{i}  {line.strip()}")
    assert not offenders, (
        "Thợ không được tự nhận việc (FR-060). Người giao việc vẫn là Trưởng dự án —\n"
        "đường đúng là hỏi rồi chờ quyết, xem `request_task`:\n  " + "\n  ".join(offenders)
    )


# ── IV. Đẩy, không hỏi-vòng (FR-080) ────────────────────────────────────────────

# `setInterval` is not banned outright — an animation or a countdown redrawing data the
# page already holds is fine. What is banned is a timer that goes back to the server. The
# check looks for a timer whose callback is a loader, which is what every polling loop in
# this repo has looked like.
_TIMER = re.compile(r"\b(?:window\.)?setInterval\s*\(")

# Empty, and meant to stay that way. It held one name (AgentDetail, refetching an agent's
# run list every 15s) for exactly as long as it took T167 to give runs a workspace-level
# event to ride. An entry here is a hole in FR-080, so adding one is a decision to justify
# in review, not a way to make this test pass.
_POLLING_ALLOWED: set[str] = set()


def test_no_screen_asks_the_server_again_on_a_timer() -> None:
    offenders: list[str] = []
    for path in sorted(FRONTEND.rglob("*.tsx")) + sorted(FRONTEND.rglob("*.ts")):
        rel = path.relative_to(FRONTEND).as_posix()
        if rel in _POLLING_ALLOWED or rel.startswith("components/ui/"):
            continue
        for i, line in enumerate(_ts_code_lines(path), 1):
            if _TIMER.search(line):
                offenders.append(f"{rel}:{i}  {line.strip()}")
    assert not offenders, (
        "Giao diện không được hỏi vòng để biết trạng thái (FR-080, Hiến pháp IV).\n"
        "Nghe kênh sự kiện rồi đọc lại phần cần, đừng đặt đồng hồ:\n  "
        + "\n  ".join(offenders)
    )


def test_the_board_listens_to_the_project_channel() -> None:
    """The other half of the same rule: not polling is only half of it. A page that
    neither polls nor subscribes does not show stale data occasionally — it shows the
    moment it was opened, forever, which is worse because nothing on screen says so."""
    board = (FRONTEND / "pages" / "ProjectBoard.tsx").read_text(encoding="utf-8")
    assert "subscribeProjectEvents" in board


# ── VI. Tiếng Việt cho người dùng (FR-084) ──────────────────────────────────────

VI = FRONTEND / "i18n" / "vi.ts"
EN = FRONTEND / "i18n" / "en.ts"

# Vietnamese words that ALWAYS carry a diacritic. Seeing one bare means the string was run
# through an ASCII stripper — which shipped to main once (d1da541, "Khong gian lam viec")
# and is invisible to anyone who does not read Vietnamese.
_STRIPPED = (
    "khong,nguoi,viec,cong,duoc,thong,danh,trang,dung,giai,dang,nhung,truong,"
    "quyet,doi,gian,lam,tai,moi,thu,vien,chuyen,dinh,tre,phai,them,xoa,sua,"
    "tim,luu,huy,dong,mo,dau,ket,noi,gui,nhan,tra,loi,hoi,dap,chua,roi"
).split(",")
_STRIPPED_RE = re.compile(r"\b(" + "|".join(_STRIPPED) + r")\b", re.IGNORECASE | re.ASCII)

_VALUE = re.compile(r":\s*'((?:[^'\\]|\\.)*)'|:\s*\"((?:[^\"\\]|\\.)*)\"")


def _values(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [(m.group(1) or m.group(2) or "") for m in _VALUE.finditer(text)]


def _has_diacritic(text: str) -> bool:
    return any(unicodedata.combining(ch) for ch in unicodedata.normalize("NFD", text))


def test_the_vietnamese_strings_keep_their_diacritics() -> None:
    offenders = [
        v
        for v in _values(VI)
        if v.strip() and not _has_diacritic(v) and _STRIPPED_RE.search(v)
    ]
    assert not offenders, (
        "Tiếng Việt hiển thị phải đủ dấu (FR-084, Hiến pháp VI). "
        "Những chuỗi này trông như đã bị lột dấu:\n  " + "\n  ".join(map(repr, offenders))
    )


def _leaf_keys(path: Path) -> set[str]:
    """Dotted key paths, read off the nesting. Good enough to compare two files that are
    meant to be the same tree with different leaves."""
    keys: set[str] = set()
    stack: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        opened = re.match(r"([A-Za-z_][\w]*)\s*:\s*\{", line)
        if opened:
            stack.append(opened.group(1))
            continue
        if line.startswith("}"):
            if stack:
                stack.pop()
            continue
        leaf = re.match(r"([A-Za-z_][\w]*)\s*:\s*['\"]", line)
        if leaf:
            keys.add(".".join([*stack, leaf.group(1)]))
    return keys


def test_the_two_languages_carry_the_same_keys() -> None:
    """A key present in one file and not the other renders as its own raw key on screen —
    a failure that looks like a typo rather than a missing translation."""
    vi_keys, en_keys = _leaf_keys(VI), _leaf_keys(EN)
    assert vi_keys - en_keys == set(), f"thiếu bên tiếng Anh: {sorted(vi_keys - en_keys)}"
    assert en_keys - vi_keys == set(), f"thiếu bên tiếng Việt: {sorted(en_keys - vi_keys)}"


# The screens this rule is enforced on. Every string a patron reads on these has to come
# from i18n; a literal here is a string the Vietnamese file can never reach.
#
# It is a list rather than "every .tsx" because the older screens predate the rule and are
# not all clean yet. Anything built or rewritten from spec 001 onwards goes on it — a new
# screen that is not listed is a hole in the guard, not an exemption.
_SCREENS_UNDER_THE_RULE = (
    "App.tsx",
    "components/LeaderChatPanel.tsx",
    "components/StatusChip.tsx",
    "components/TopBar.tsx",
    "pages/CollaborationRoom.tsx",
    "pages/Inbox.tsx",
    # spec 002 — approving a machine into a workspace (T031).
    "pages/LinkMachine.tsx",
    "pages/ProjectBoard.tsx",
    "pages/ProjectPlan.tsx",
    "pages/Projects.tsx",
    "pages/Roster.tsx",
)

_QUOTED = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"")


def test_no_vietnamese_is_hardcoded_into_the_screens_under_the_rule() -> None:
    offenders: list[str] = []
    for rel in _SCREENS_UNDER_THE_RULE:
        path = FRONTEND / rel
        for i, line in enumerate(_ts_code_lines(path), 1):
            for m in _QUOTED.finditer(line):
                value = m.group(1) or m.group(2) or ""
                if _has_diacritic(value):
                    offenders.append(f"{rel}:{i}  {value!r}")
    assert not offenders, (
        "Chuỗi hiển thị phải đi qua cơ chế đa ngôn ngữ (FR-084, Hiến pháp VI).\n"
        "Đưa vào `i18n/vi.ts` + `i18n/en.ts` rồi gọi qua `t()`:\n  " + "\n  ".join(offenders)
    )
