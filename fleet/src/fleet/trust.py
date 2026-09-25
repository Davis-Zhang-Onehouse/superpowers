"""Claude folder trust, predicted read-only, and the trust screen, recognised in a frame (V23-P, FB-126).

The defect: `fleet dispatch` of a real Claude into a folder Claude Code does not trust lands the worker on the
folder-trust screen — where it waits for a human forever — while `dispatch` prints plain success. This module
is the pure half of the fix: it answers "will Claude show the trust screen in this cwd?" BEFORE the launch, and
"is this frame the trust screen, and which folder does it name?" AFTER it.

**The rule is measured, not guessed.** It was read from Claude Code 2.1.282's own trust functions and then run
against that binary in 12 layouts — plain dirs, a git root, a subdir, a linked worktree, a clone, a nested git
root — with 12/12 agreeing (v23ptrustscreen instant, `evidence/01-trust-rule/RESULT.tsv`, built by
`trust-matrix.sh` on a private tmux socket with a scratch `CLAUDE_CONFIG_DIR` and `HOME`). In short: a trust
record on a directory covers its descendants, but the walk up STOPS at the git toplevel, so a git root never
inherits trust from a parent; a linked worktree inherits from its MAIN worktree, a clone does not inherit from
its origin. See `predict_claude` for the exact order.

**The fence.** This module only READS `<config_dir>/.claude.json` and runs `git rev-parse`. It never writes trust,
never sets `CLAUDE_CODE_SANDBOXED`, and never accepts a screen: whether to trust a folder is the operator's
decision, and a tool that quietly granted it would be the bug this milestone exists to surface.
"""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from fleet.runtime import PROMPT_TAIL_LINES

TRUSTED, UNTRUSTED, UNKNOWN, NOT_PREDICTED = "trusted", "untrusted", "unknown", "not-predicted"

#: V23-P. Only the codex screen text is recognised for codex; its trust store is not read (see `predict`).
_CODEX_NOT_PREDICTED = "codex keeps folder trust in CODEX_HOME/config.toml; fleet does not predict it"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass(frozen=True)
class TrustPrediction:
    state: str  #: one of TRUSTED / UNTRUSTED / UNKNOWN / NOT_PREDICTED
    #: TRUSTED: the `projects` key that grants it ("" when the sandbox variable does); UNTRUSTED: the folder the
    #: screen will name (the cwd — measured in every TRUST case of the matrix); otherwise "".
    key: str
    detail: str  #: one line, for a human


#: `run(argv)` answers `(rc, stdout)`, or None when git could not be run at all (missing, timed out).
Runner = Callable[[list], "Optional[tuple[int, str]]"]

#: V23-P (review M1). Variables that make git describe a repository other than the one around `-C <cwd>`. A
#: caller that exported GIT_DIR (a hook, a script run under `git rebase -x`) must not change the answer.
_GIT_SCRUB = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_CEILING_DIRECTORIES",
              "GIT_DISCOVERY_ACROSS_FILESYSTEM")


#: V23-P (review I1). Raised rather than returned so `layout(cwd) -> (top, canonical)` keeps its shape for injected
#: layouts, and `predict_claude` maps it to UNKNOWN. Collapsing it to (None, None), "outside git", let the parent
#: walk run past the real toplevel to `/` and predict TRUSTED from an ancestor where Claude, bounded at the toplevel
#: (cases C/E2/G/I), shows the screen: a guess, where D-4 asks for UNKNOWN.
class GitLayoutUnknown(Exception):
    """git could not say where the work tree is, although `cwd` may be inside one."""


def _run(argv: list) -> "Optional[tuple[int, str]]":
    """`argv` is `["git", ...]`; run through `workspace.default_git`, the package's documented git seam (FI-27a:
    three spawn seams, and trust is not a fourth). The scrub and the 5s bound are that seam's opt-in arguments.
    `-C <cwd>` in `argv` chooses the directory, so the process itself runs in `/`, which always exists."""
    from fleet import workspace
    try:
        return workspace.default_git(scrub_env=_GIT_SCRUB, timeout=5)(argv[1:], "/")
    except Exception:  # noqa: BLE001 - V23-P: missing git, a timeout, an OS error: "git could not be run" -> None
        return None


def _under_dot_git(cwd: Path) -> Optional[Path]:
    """The nearest `.git` entry (a repo's dir, or a linked worktree's file) at `cwd` or above it, else None."""
    for d in (cwd, *cwd.parents):
        if os.path.lexists(d / ".git"):
            return d / ".git"
    return None


def git_layout(cwd: Path, run: Optional[Runner] = None) -> "tuple[Optional[Path], Optional[Path]]":
    """(toplevel, canonical_root) or (None, None) outside git. canonical_root = parent of
    `git rev-parse --path-format=absolute --git-common-dir` when that ends in `.git` (the MAIN worktree for a linked
    worktree), else the toplevel. `run(argv) -> (rc, stdout)` is injectable; the default is `workspace.default_git`,
    5s timeout, with the repository-selecting GIT_* variables scrubbed.

    Raises `GitLayoutUnknown` when git could not run, or answered rc != 0 while a `.git` entry sits at or above
    `cwd` (dubious ownership, a ceiling, a broken repo): "not a repository" is only believed where none is visible.
    """
    cwd = Path(cwd)
    answer = (run or _run)(["git", "-C", str(cwd), "rev-parse", "--path-format=absolute",
                            "--show-toplevel", "--git-common-dir"])
    if answer is None:
        raise GitLayoutUnknown(f"git could not be run in {cwd}")
    rc, out = answer
    lines = [line for line in out.splitlines() if line.strip()]
    if rc != 0 or len(lines) != 2:
        dotgit = _under_dot_git(cwd)
        if dotgit is not None:
            raise GitLayoutUnknown(f"git rev-parse failed (rc {rc}) in {cwd} although {dotgit} exists")
        return None, None
    top, common = Path(lines[0]), Path(lines[1])
    return top, (common.parent if common.name == ".git" else top)


def _spellings(p: Path) -> list:
    """The keys Claude may have recorded a directory under: as given, and resolved when that differs."""
    out = [str(p)]
    try:
        real = str(p.resolve())
    except OSError:
        return out
    if real != out[0]:
        out.append(real)
    return out


def _resolved(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p


def predict_claude(config_dir, cwd, *, environ: Optional[Mapping] = None, layout=git_layout) -> TrustPrediction:
    """Will Claude Code (2.1.282 rule) start in `cwd` without the folder-trust screen?

    1. `CLAUDE_CODE_SANDBOXED` set (read, never set) -> TRUSTED.
    2. No `<config_dir>/.claude.json` -> UNTRUSTED; unreadable / not JSON / wrong shape -> UNKNOWN.
    3. A key is trusted iff `projects[key]["hasTrustDialogAccepted"] is True`.
    4. The git canonical root (the main worktree) trusted -> TRUSTED.
    5. cwd, then each parent, trusted -> TRUSTED; the walk stops after the git toplevel, else at `/`.
    6. Otherwise UNTRUSTED, keyed by the cwd the screen will name.
    """
    environ = {} if environ is None else environ
    if environ.get("CLAUDE_CODE_SANDBOXED"):
        return TrustPrediction(TRUSTED, "", "CLAUDE_CODE_SANDBOXED is set, so Claude skips the folder-trust check")
    path = Path(config_dir) / ".claude.json"
    #: V23-P (review M2). normpath, not just absolute(): `g/../plain/sub` must not list `g` among its parents.
    cwd = Path(os.path.normpath(Path(cwd).absolute()))
    if not path.exists():
        return TrustPrediction(UNTRUSTED, str(cwd), f"{path} does not exist, so no trust record exists")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return TrustPrediction(UNKNOWN, "", f"cannot read {path}: {type(exc).__name__}: {exc}".splitlines()[0])
    if not isinstance(data, dict):
        return TrustPrediction(UNKNOWN, "", f"{path} is not a JSON object")
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        return TrustPrediction(UNKNOWN, "", f"{path}: `projects` is not an object")

    def granted(d: Path) -> Optional[str]:
        for key in _spellings(d):
            record = projects.get(key, {})
            #: V23-P (review M3). Strictly `is True`. 2.1.282 is mixed: `_Ee` compares `===true` while `wb`/`pI`
            #: test truthiness, so a non-boolean record errs toward UNTRUSTED, which the post-launch observation of
            #: the screen corrects. Not modelled either: `pI`'s session-level bypass `jle()`.
            if isinstance(record, dict) and record.get("hasTrustDialogAccepted") is True:
                return key
        return None

    try:
        top, canonical = layout(cwd)
    except GitLayoutUnknown as exc:
        return TrustPrediction(UNKNOWN, "", f"cannot bound the trust walk: {exc}")
    if canonical is not None:
        key = granted(canonical)
        if key is not None:
            return TrustPrediction(TRUSTED, key, f"the git root {canonical} is trusted ({key})")
    d = cwd
    while True:
        key = granted(d)
        if key is not None:
            return TrustPrediction(TRUSTED, key, f"{key} is trusted and covers {cwd}")
        #: V23-P. Measured cases C/E2/G/I: trust never crosses UP out of a git toplevel.
        if top is not None and (d == top or _resolved(d) == top):
            break
        if d.parent == d:
            break
        d = d.parent
    bound = str(top) if top is not None else "/"
    detail = f"no trust record on {cwd} or any parent up to {bound}"
    if top is not None:
        detail += f" (git toplevel {top})"
    return TrustPrediction(UNTRUSTED, str(cwd), detail)


def predict(runtime: str, config_dir, cwd, *, environ: Optional[Mapping] = None,
            layout=git_layout) -> TrustPrediction:
    if runtime == "codex":
        return TrustPrediction(NOT_PREDICTED, "", _CODEX_NOT_PREDICTED)
    return predict_claude(config_dir, cwd, environ=environ, layout=layout)


def _rows(frame: str) -> list:
    """The frame's rows with SGR stripped and tmux's bottom padding removed (`runtime._rendered`'s rule)."""
    rows = _ANSI.sub("", frame).splitlines()
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


def _window(rows: list) -> int:
    return max(0, len(rows) - PROMPT_TAIL_LINES)


def _dialog(rows: list, hints: tuple, option: str) -> "Optional[tuple[int, int]]":
    """RV-24. `(start, hint)`: the span of the LIVE screen, or None when it is not showing. Its hint row (beginning
    with one of `hints`) and its first-choice `option` row must both sit inside the dialog window — the last
    `runtime.PROMPT_TAIL_LINES` rendered rows, where `runtime.observe` looks for a dialog — and the screen starts
    after any earlier hint row. A screen quoted in history (a resumed pane redraws it above the live prompt) has
    both rows above that window, so it is not the screen and cannot lend its path to one below it."""
    def is_hint(row):
        return row.lstrip().lower().startswith(hints)
    window = _window(rows)
    hint = next((i for i in range(len(rows) - 1, window - 1, -1) if is_hint(rows[i])), None)
    if hint is None or not any(option in row for row in rows[window:hint]):
        return None
    earlier = _last(rows[:hint], is_hint)
    return (0 if earlier is None else earlier + 1), hint


def _last(rows: list, test) -> Optional[int]:
    return next((i for i in range(len(rows) - 1, -1, -1) if test(rows[i])), None)


def _joined_after(rows: list, header: int) -> str:
    """The path block under `rows[header]`: the non-blank rows after it, up to the next blank row. No separator:
    the TUI wraps a long path mid-word (claude-trust-wrapped-2.1.282.frame). RV-28: codex's path is read the same
    way, so a wrapped codex path is not cut at its first row."""
    parts = []
    for later in rows[header + 1:]:
        if later.strip():
            parts.append(later.strip())
        elif parts:
            break
    return "".join(parts)


def _claude_path(rows: list) -> Optional[str]:
    #: The hint row, not merely the phrase: an answer that QUOTES the screen is not the screen.
    span = _dialog(rows, ("enter to confirm",), "Yes, I trust this folder")
    if span is None:
        return None
    start, hint = span
    screen = rows[start:hint]
    if not any("one you trust" in row for row in screen):
        return None
    header = _last(screen, lambda row: row.strip() == "Accessing workspace:")
    if header is None:
        return ""
    return _joined_after(screen, header)


def _codex_path(rows: list) -> Optional[str]:
    #: RV-24. Each screen only with its own hint and first option inside the dialog window: "enter continue · esc
    #: quit" under "1. Trust and continue" on 0.156 (codex-trust-0156.frame), "Press enter to continue" under
    #: "1. Yes, continue" on 0.154 (codex-trust.frame).
    span = _dialog(rows, ("enter continue",), "Trust and continue")
    if span is not None:
        screen = rows[span[0]:span[1]]
        if not any("Trust this folder?" in row for row in screen):
            return None
        header = _last(screen, lambda row: row.strip() == "Folder access")
        if header is None:
            return ""
        return _joined_after(screen, header)
    span = _dialog(rows, ("press enter to continue",), "Yes, continue")
    if span is not None:
        screen = rows[span[0]:span[1]]
        if not any("Do you trust the contents of this directory?" in row for row in screen):
            return None
        where = _last(screen, lambda row: "You are in " in row)
        return "" if where is None else screen[where].split("You are in ", 1)[1].strip()
    return None


def trust_screen_path(runtime: str, frame: str) -> Optional[str]:
    """None when `frame` is NOT `runtime`'s folder-trust screen; else the folder it names ("" when the screen is
    certain but no path row reads)."""
    rows = _rows(frame)
    if runtime == "claude":
        return _claude_path(rows)
    if runtime == "codex":
        return _codex_path(rows)
    return None
