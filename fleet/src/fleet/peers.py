"""
peers — the mechanical provenance whitelist for cross-session messaging.

WHY THIS EXISTS
---------------
Claude Code sessions can now discover and message one another (`ListAgents` / `SendMessage`). That
dissolved a safety barrier this fleet used to get for free: "never touch another effort's session"
was previously enforced by IMPOSSIBILITY and is now enforced by discipline alone. This module turns
it back into a mechanism.

It joins two surfaces the RUNTIME emits, so nothing here depends on a human remembering to type a
convention — an anchor of that kind went dark for days once and the check reported success the whole
time:

  * ``claude agents --json`` — live, PID-backed local sessions, each carrying cwd / pid / status.
    It needs no TTY, so a shell tick can use it. Measured: it lists exactly the live local sessions,
    whereas the model-facing peer listing also carries stale cloud registrations for sessions that
    are finished or elsewhere, rendered indistinguishably from live ones.
  * fleet's own lease records — slot path -> todo id / instant / tmux name.

WHY THE JOIN IS NECESSARY AT ALL
--------------------------------
A peer is listed under ``basename(cwd)`` plus a short suffix — ``ws1-eb``, ``ws3-51``. That names the
SLOT, not the instant. Slots are re-leased (ws1 has hosted three different milestones), so the label
is ambiguous across time and carries no milestone. Resolving through the lease record is the only way
to get from a live peer to WHICH INSTANT it is.

FAIL-CLOSED IS THE WHOLE POINT
------------------------------
Every unresolved, ambiguous or malformed case classifies as FOREIGN, never as OURS, and a missing
``cwd`` or ``pid`` raises rather than defaulting. An allowlist that fails open is not an allowlist.

⛔ WHY LIVENESS MUST COME FROM A PID AND NEVER FROM A NAME
---------------------------------------------------------
The messaging contract states that *names keep working after an agent completes — a send resumes it
from its transcript*. The model-facing peer listing carries FINISHED sessions rendered exactly like
live ones, including this fleet's own harvested workers under their ``dt-`` names. So addressing a
peer by a name taken from that listing can RESUME A HARVESTED INSTANT, unattended, against a closed
lease — restarting work whose milestone is already reported done.

Everything here therefore derives liveness from a PID that must exist in ``/proc`` right now, and
ownership from an OPEN lease. A name is never sufficient evidence that anything is alive. This is
also why the classification carries DEAD as a verdict distinct from FOREIGN: "belongs to us but has
finished" and "belongs to somebody else" are different refusals, and collapsing them would make the
first one look addressable.
"""

from __future__ import annotations

import json
import os
import subprocess

from .errors import FleetError

# Verdicts. Only OURS is addressable.
SELF = "SELF"
OURS = "OURS"
FOREIGN = "FOREIGN"
DEAD = "DEAD"

#: Keys we refuse to proceed without. `cwd` and `pid` are what establish provenance at all; `name`
#: and `status` are what make the output actionable.
REQUIRED_KEYS = ("cwd", "pid", "name", "status")

DEFAULT_CLAUDE_BIN = "/home/ubuntu/.local/bin/claude"


class PeersUnavailable(FleetError):
    """The peer listing could not be established well enough to classify. Never downgraded."""


def _claude_bin():
    return os.environ.get("FLEET_CLAUDE_BIN") or os.environ.get("REAL_CLAUDE") or DEFAULT_CLAUDE_BIN


def load_peers(json_text=None, runner=subprocess.run):
    """
    Return the live local peer rows.

    Raises PeersUnavailable on anything unexpected. In particular a row missing `cwd` or `pid` is
    fatal: without those there is no provenance, and guessing means possibly messaging a session
    belonging to somebody else.
    """
    if json_text is None:
        argv = [_claude_bin(), "agents", "--json"]
        try:
            done = runner(argv, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise PeersUnavailable(f"could not run `{' '.join(argv)}`: {exc}")
        if done.returncode != 0:
            raise PeersUnavailable(
                f"`claude agents --json` exited {done.returncode}; refusing to classify. "
                f"stderr: {(done.stderr or '').strip()[:300]}"
            )
        json_text = done.stdout

    try:
        rows = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise PeersUnavailable(
            f"`claude agents --json` did not return JSON ({exc}); refusing to classify."
        )
    if not isinstance(rows, list):
        raise PeersUnavailable(
            f"expected a JSON array of sessions, got {type(rows).__name__}; refusing to classify."
        )
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PeersUnavailable(f"session row {i} is {type(row).__name__}, not an object")
        missing = [k for k in REQUIRED_KEYS if k not in row]
        if missing:
            raise PeersUnavailable(
                f"session row {i} (name={row.get('name', '?')!r}) is missing {missing}. "
                "Provenance cannot be established, so nothing is classified as addressable."
            )
        _validate_provenance(i, row)
    return rows


def _validate_provenance(i, row):
    """
    Reject a row whose `cwd` or `pid` is PRESENT but degenerate.

    ⛔ THIS IS A FAIL-OPEN THAT SHIPPED AND WAS CAUGHT IN REVIEW. Checking only that the key exists
    is not enough: `os.path.realpath("")` and `os.path.realpath(".")` both return THE CALLING
    PROCESS'S OWN CWD, and this verb normally runs from inside a leased slot. So a peer row carrying
    `"cwd": ""` inherited the caller's slot, matched that slot's open lease, and was classified OURS
    — stamped with the caller's milestone, instant and tmux name. Reproduced on a live foreign peer.

    An empty string is the degenerate form of "missing", and the contract this module states is that
    a missing `cwd` raises rather than defaults. So it raises here too. A relative path is rejected
    for the same reason: ownership must be decided by an absolute path, never by where we happen to
    be standing.
    """
    cwd = row.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        raise PeersUnavailable(
            f"session row {i} (name={row.get('name', '?')!r}) has a non-string or empty cwd "
            f"({cwd!r}). realpath('') resolves to THIS process's cwd, which would silently inherit "
            "our own slot's ownership; refusing to classify."
        )
    if not cwd.startswith("/"):
        raise PeersUnavailable(
            f"session row {i} (name={row.get('name', '?')!r}) has a relative cwd ({cwd!r}). "
            "Ownership must be decided by an absolute path, not by the caller's location."
        )
    if "\x00" in cwd:
        # JSON permits a NUL escape in a string; os.path.realpath does not, and raises ValueError -- which
        # is not a FleetError, so it escaped `main`'s handler as a full traceback rather than as a
        # refusal a reader can act on.
        raise PeersUnavailable(
            f"session row {i} (name={row.get('name', '?')!r}) has a NUL byte in cwd; refusing."
        )
    # `name` and `status` are rendered with format specs, so a non-string here raises TypeError deep
    # inside render() instead of refusing here. Presence was checked; type was not.
    for key in ("name", "status"):
        if not isinstance(row.get(key), str):
            raise PeersUnavailable(
                f"session row {i} has a non-string {key} ({row.get(key)!r}); refusing to classify."
            )
    try:
        pid = int(row["pid"])
    except (TypeError, ValueError):
        raise PeersUnavailable(
            f"session row {i} (name={row.get('name', '?')!r}) has a non-numeric pid "
            f"({row.get('pid')!r}); liveness cannot be established, so nothing is addressable."
        )
    if pid <= 0:
        raise PeersUnavailable(
            f"session row {i} (name={row.get('name', '?')!r}) has a non-positive pid ({pid}); "
            "refusing to classify."
        )


def load_leases(records_dir):
    """Load fleet's lease records. A record we cannot read is fatal, not skipped."""
    if not os.path.isdir(records_dir):
        raise PeersUnavailable(
            f"no lease records directory at {records_dir}; ownership cannot be established"
        )
    leases = []
    for name in sorted(os.listdir(records_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(records_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                leases.append(json.load(fh))
        except (OSError, json.JSONDecodeError) as exc:
            # Skipping an unreadable record would shrink the OURS set silently, turning a
            # data problem into a wrong answer that looks like a clean one.
            raise PeersUnavailable(f"lease record {path} is unreadable ({exc}); refusing to classify")
    return leases


def open_leases_by_slotpath(leases):
    """
    Map slot path -> the one OPEN lease holding it, plus the set of slots that are ambiguous.

    A lease counts as open only when it carries neither ``closed_at`` nor ``harvested_at``.

    ⚠️ THIS IS THE SUBTLE PART AND IT IS EASY TO "SIMPLIFY" WRONG. Slots are RE-LEASED: one slot in
    this fleet has hosted three separate milestones. Matching a live peer on slot path alone would
    attribute that session to whichever record happened to sort first — quite possibly one that was
    closed hours earlier. Requiring an OPEN lease is what makes the answer about the session that is
    actually running. If two open leases claim one slot the state is corrupt, and we refuse that slot
    rather than pick one, because picking one silently invents an ownership claim.
    """
    by_slot = {}
    for lease in leases:
        if not isinstance(lease, dict):
            raise PeersUnavailable(
                f"a lease record is a {type(lease).__name__}, not an object; refusing to classify"
            )
        slot_path = lease.get("golden") or ""
        for key in ("milestone", "tmux", "child_instant", "todo_id"):
            value = lease.get(key)
            if value is not None and not isinstance(value, str):
                # These are rendered with format specs; a list/dict here raises TypeError deep
                # inside render() and escapes `main` as a traceback rather than as a refusal.
                raise PeersUnavailable(
                    f"lease {lease.get('todo_id', '?')!r} has a non-string {key} ({value!r}); refusing"
                )
        if isinstance(slot_path, str) and "\x00" in slot_path:
            raise PeersUnavailable(
                f"lease {lease.get('todo_id', '?')!r} has a NUL byte in `golden`; refusing"
            )
        if not isinstance(slot_path, str):
            raise PeersUnavailable(
                f"lease {lease.get('todo_id', '?')!r} has a non-string `golden` ({slot_path!r}); "
                "refusing to classify rather than raising a TypeError out of a guard"
            )
        if not slot_path:
            continue
        if lease.get("closed_at") or lease.get("harvested_at"):
            continue
        by_slot.setdefault(os.path.realpath(slot_path), []).append(lease)

    resolved, ambiguous = {}, set()
    for slot_path, holders in by_slot.items():
        if len(holders) == 1:
            resolved[slot_path] = holders[0]
        else:
            ambiguous.add(slot_path)
    return resolved, ambiguous


def _ppid_of(pid, proc_root="/proc"):
    try:
        with open(os.path.join(proc_root, str(int(pid)), "status"), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def detect_self_pid(peer_pids, start_pid=None, proc_root="/proc"):
    """
    Identify which peer row is THIS session, by walking the process ancestry.

    ``os.getppid()`` is the shell that invoked us, never the claude session, so it never matches a
    peer row. Returns None when no ancestor matches, and nothing is then marked SELF.

    ⚠️ THE RISK ORDERING HERE IS THE OPPOSITE OF WHAT THIS COMMENT USED TO CLAIM. It said a foreign
    peer misread as SELF was the dangerous direction. It is not: SELF is evaluated BEFORE the lease
    branch, so that misread EXCLUDES the peer from OURS, which is the safe outcome. The direction
    with a live consequence is this function returning None for our OWN session -- it then falls
    through to the lease branch, resolves to OURS, and appears under `--addressable-only`, so a
    caller fanning out to every addressable peer messages ITSELF. None is still the right default;
    what makes it safe is that it never manufactures an OURS, not that SELF is harmless.
    """
    seen = set()
    pid = start_pid if start_pid is not None else os.getpid()
    while pid and pid not in seen:
        seen.add(pid)
        if pid in peer_pids:
            return pid
        pid = _ppid_of(pid, proc_root=proc_root)
    return None


def _is_live(pid, cwd, proc_root="/proc"):
    """
    Liveness, cross-checked against the process's ACTUAL cwd where the kernel will tell us.

    `/proc/<pid>` existing is weaker evidence than it looks: the same namespace holds THREAD ids, and
    a recycled pid would revive a stale row. Comparing `/proc/<pid>/cwd` to the cwd the listing
    claimed closes both, and costs one readlink.

    ⛔ AN UNREADABLE `/proc/<pid>/cwd` IS A REFUSAL, NOT A FALLBACK, AND THE OPPOSITE SHIPPED ONCE.
    The first version returned True on OSError, reasoning "assume alive; a send to something
    just-dead fails loudly". That reasoning was wrong twice over. It did not merely assume liveness —
    it SKIPPED THE CROSS-CHECK, so the row's *claimed* cwd was accepted unverified and conferred
    ownership. Reproduced: a stale listing row whose pid had been recycled onto PID 100
    (`migration/14`, a root kernel thread) was classified OURS, stamped with a real milestone and
    tmux name, and appeared under `--addressable-only`. The outcome is not "a send to something
    just-dead" but a send to something LIVE AND NOT OURS, which fails by succeeding.

    Our own sessions run as our uid, so their `/proc/<pid>/cwd` is always readable by us. An
    unreadable link is therefore positive evidence that the process is NOT one of ours, and the
    fail-closed answer costs nothing.
    """
    entry = os.path.join(proc_root, str(pid))
    if not os.path.exists(entry):
        return False
    try:
        actual = os.path.realpath(os.readlink(os.path.join(entry, "cwd")))
    except OSError:
        return False
    return actual == os.path.realpath(cwd)


def classify(rows, leases, self_pid=None, proc_root="/proc"):
    """Classify every peer. Anything not positively resolved to an open lease is FOREIGN."""
    if self_pid is None:
        self_pid = detect_self_pid({int(r["pid"]) for r in rows}, proc_root=proc_root)
    resolved, ambiguous = open_leases_by_slotpath(leases)

    # ⛔ A SLOT MAY HOLD ONLY ONE ADDRESSABLE SESSION, AND THIS IS NOT A THEORETICAL CASE.
    # Ownership is keyed on the slot DIRECTORY, and nothing in the lease record identifies WHICH
    # session it was issued for. So a second live session whose cwd is a leased slot -- `cd ws1 &&
    # claude`, which a human might simply do -- was also classified OURS and stamped with that
    # milestone's instant and tmux name. That misattributes somebody's own session to a milestone it
    # has nothing to do with, and D-6 is explicit that some of these sessions are people's.
    # Two live peers in one slot is therefore ambiguous in exactly the way two open leases on one
    # slot is ambiguous, and it refuses for the same reason: picking one invents an ownership claim.
    #
    # Liveness is sampled ONCE per row, here, and reused below. Calling `_is_live` again inside the
    # verdict loop would let a peer that exits between the two calls be counted as live when the slot
    # was contested and dead when its own verdict was decided -- a self-inconsistent answer from one
    # invocation. One sample, one verdict; the sample can still be stale by the time anyone acts on
    # it, but at least the report agrees with itself.
    # ⛔ KEYED BY ROW POSITION, NOT BY PID, AND THAT DISTINCTION IS A FAIL-OPEN.
    # A pid-keyed dict lets the LAST row with a given pid decide liveness for EVERY row with that
    # pid. Two rows sharing one pid is exactly the situation this cross-check exists for -- a stale
    # row claiming our slot, plus the live row for the process that now owns that recycled pid --
    # so the lying row inherited the truthful row's verdict and was classified OURS, stamped with a
    # real milestone and tmux name. `contested` did not catch it either: the two rows sit under
    # different slot keys, so neither slot looks contested. Reproduced in review.
    live = [_is_live(int(row["pid"]), row["cwd"], proc_root=proc_root) for row in rows]
    live_by_slot = {}
    for idx, row in enumerate(rows):
        if live[idx]:
            live_by_slot.setdefault(os.path.realpath(row["cwd"]), []).append(idx)
    # Count ROWS, not pids: two identical duplicate rows are not two sessions.
    contested = {slot for slot, idxs in live_by_slot.items() if len(idxs) > 1}

    out = []
    for idx, row in enumerate(rows):
        cwd = os.path.realpath(row["cwd"])
        pid = int(row["pid"])
        rec = {
            "name": row["name"], "pid": pid, "cwd": row["cwd"], "status": row["status"],
            "session_id": row.get("sessionId", ""),
            "instant": "", "milestone": "", "tmux": "", "todo_id": "",
        }

        # Attach the lease provenance FIRST, whatever the verdict turns out to be. A dead peer of
        # ours must be able to say WHOSE it was: "belongs to us but has finished" and "belongs to
        # somebody else" are different refusals, and DEAD exists to keep them apart. Reporting both
        # with empty lease fields made them byte-identical and collapsed the distinction the verdict
        # was introduced to draw.
        lease = resolved.get(cwd)

        # ⚠️ LEASE COLUMNS ARE ATTACHED ONLY WHERE THEY DESCRIBE **THIS PEER**, never merely the slot
        # it happens to sit in. An earlier version attached them before deciding the verdict, so a
        # FOREIGN co-tenant of a contested slot was rendered carrying OUR milestone and OUR tmux
        # session name, printed directly beside the stranger's own name -- and a human acting on that
        # row would send keys to our worker believing they were reaching that peer. DEAD keeps them,
        # because "ours, but finished" is exactly the distinction DEAD exists to draw; FOREIGN does
        # not, because for a FOREIGN row the lease describes the address, not the occupant.
        def _attach():
            if lease is not None:
                rec.update(instant=lease.get("child_instant", ""),
                           milestone=lease.get("milestone", ""),
                           tmux=lease.get("tmux", ""), todo_id=lease.get("todo_id", ""))

        if not live[idx]:
            _attach()
            rec.update(verdict=DEAD,
                       why=("this pid is not a live session at that cwd -- either gone, or the pid "
                            "now belongs to a different process; the listing is stale for this row. "
                            "Any lease columns shown describe THE SLOT this row claims, and are NOT "
                            "evidence that this row is ours"))
        elif self_pid is not None and pid == int(self_pid):
            _attach()
            rec.update(verdict=SELF, why="this session")
        elif cwd in ambiguous:
            rec.update(verdict=FOREIGN,
                       why="two open leases claim this slot; ambiguous, refusing (fail-closed)")
        elif cwd in contested:
            rec.update(verdict=FOREIGN,
                       why=("more than one LIVE session is running in this slot, so the lease cannot "
                            "identify which one this is; refusing (fail-closed)"))
        elif lease is None:
            rec.update(verdict=FOREIGN,
                       why="cwd is not the slot of any OPEN lease in this FLEET_HOME")
        else:
            _attach()
            rec.update(verdict=OURS,
                       why="cwd is the slot of an open lease dispatched by this fleet")
        out.append(rec)
    return out


#: The porcelain contract: exactly these fields, tab-separated, one line per peer, no blank lines.
PEER_COLUMNS = ("verdict", "name", "pid", "status", "milestone", "tmux", "cwd", "instant")


def _cell(value):
    """
    One porcelain cell, with the field and record separators made harmless.

    ⛔ WITHOUT THIS, A FOREIGN PEER'S FIELD CONTENT CAN FORGE AN `OURS` ROW. The cells are not ours:
    `name` is derived by the runtime from `basename(cwd)`, and a POSIX directory name may contain
    tabs and newlines. A tab injects extra columns; a newline splits one record into two — and the
    fabricated second record can begin with the literal text `OURS`, so a consumer doing
    `awk -F'\\t' '$1=="OURS"'` puts an attacker-chosen name in its addressable list while the row
    that got split is silently truncated. Both were reproduced in review.

    Escaped rather than stripped, so the value stays legible and no two distinct cells collapse
    into the same output.
    """
    text = "-" if value is None or value == "" else str(value)
    text = text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    # ⚠️ `\t\n\r` ARE NOT THE ONLY SEPARATORS THAT MATTER. Python's str.splitlines() also breaks on
    # \x0b \x0c \x1c \x1d \x1e \x85 U+2028 U+2029 -- so a cell containing any of them still forged an
    # extra `OURS`-leading record for any consumer using splitlines(), which includes this module's
    # own control suite. Shell consumers were safe (they split on \n), but "safe for the reader I
    # happened to imagine" is how the first version of this escaping passed review.
    for ch in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
        text = text.replace(ch, "\\x%02x" % ord(ch) if ord(ch) < 0x100 else "\\u%04x" % ord(ch))
    return text


def porcelain(results, addressable_only=False):
    """Machine form: one tab-separated row per peer, exactly `PEER_COLUMNS` fields each.

    Empty fields are emitted as `-` rather than as nothing, so a consumer splitting on tabs always
    gets the same field count. A blank cell that collapses a column is how a reader ends up reading
    `tmux` out of the `milestone` position.

    Ends with a trailing newline when non-empty: `while read` and `wc -l` both DROP a final line that
    has no terminator, and which peer that silently loses depends only on listing order — under
    `--addressable-only` it can be the sole OURS row, which then reads as "nothing addressable".
    """
    rows = [r for r in results if r["verdict"] == OURS] if addressable_only else results
    out = [ "\t".join(_cell(r.get(c)) for c in PEER_COLUMNS) for r in rows ]
    return "".join(line + "\n" for line in out)


def render(results, addressable_only=False):
    """Human form: a block per peer, with the reason the verdict was reached.

    ⛔ EVERY INTERPOLATED CELL GOES THROUGH `_cell()`, FOR THE SAME REASON PORCELAIN DOES.
    Hardening only the machine form was a mistake caught in review: `render()` is the DEFAULT surface
    the verb prints, and it interpolated raw. A peer whose `name` contained a newline forged a
    complete, byte-identical `OURS` block — plausible tmux name and all — inside the output of a row
    whose real verdict was FOREIGN. A bare carriage return does the same in a terminal by overwriting
    from column 0. These names are not ours: the runtime derives them from `basename(cwd)`, and a
    POSIX directory name may contain both characters.
    """
    rows = [r for r in results if r["verdict"] == OURS] if addressable_only else results
    lines = []
    for r in rows:
        lines.append(
            f"{_cell(r['verdict']):<8} {_cell(r['name']):<44} pid={_cell(r['pid']):<9} "
            f"{_cell(r['status']):<6} {_cell(r['milestone']):<6} {_cell(r['tmux'])}"
        )
        lines.append(f"         cwd={_cell(r['cwd'])}")
        if r["instant"]:
            lines.append(f"         instant={_cell(r['instant'])}")
        lines.append(f"         why={_cell(r['why'])}")
    if not rows:
        lines.append("(no peers matched)")
    return "\n".join(lines)


def summary(results):
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in (OURS, FOREIGN, SELF, DEAD)}
    return (
        f"{len(results)} peer(s): {counts[OURS]} addressable (OURS), {counts[FOREIGN]} FOREIGN, "
        f"{counts[SELF]} self, {counts[DEAD]} dead.\n"
        "FOREIGN peers are NOT addressable: they belong to another effort, and messaging one "
        "crosses a boundary this fleet treats as a standing hazard."
    )
