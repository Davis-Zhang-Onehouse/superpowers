"""Seed-delivery integrity — does the worker actually carry the briefing `dispatch` rendered for it?

`dispatch` renders a seed into `<child>/.fleet/seed.txt` and then starts the worker with the bare string
`"claude"` (`cli._do_dispatch`). It delivers no seed. Delivery is the caller's job, performed by a launcher
`fleet` neither writes nor reads — historically a `PATH` shim that execs the real binary with a seed file as
argv. So there are two artefacts, produced by two actors, and **nothing compared them**: `FI-78` checks the
seed FILE, never what was DELIVERED.

The cost, measured 2026-08-07: `i1selfcertifyingcontrols` was dispatched for a fleet-infra milestone and
started with the v2stack COORDINATOR's bootstrap briefing — 17927 characters, byte-identical to the
coordinator's own, md5 `4ec786cf57d92a2049833c795084ff5a` — and ran coordinator orientation for ten minutes.
Every `fleet` gate passed, because `fleet` was not in that path.

**Why the comparison belongs in the product rather than in a launcher discipline.** The remedy that existed
was *"give each dispatch its own launcher directory"*, which is a step a human must remember, and it was
forgotten the first time the dispatch shape changed: the coordinator's `launchers/` held `w18 w19 w22 w24
retro q6b …` and no `i1`. A control whose failure mode is "somebody did not do it" fails in exactly the
handoff it exists to protect.

**Why argv.** The seed a worker was started with is recoverable from `/proc/<pid>/cmdline` for the worker's
whole life, so the check is not a race to observe a moment — it can be run at dispatch time *and* re-run at
any point afterwards by a sweep. That matters because the two delivery shapes settle at different times: a
STALE launcher already holds a non-empty seed file and execs immediately, while a correct launcher waits for
the caller to write one, which happens after `dispatch` has returned. The stale case — the dangerous one — is
therefore the case that IS visible at dispatch time.

⚠️ `/proc/<pid>/cmdline` reports `st_size` 0. It must be READ, never `stat`-ed: a size check returns 0 for
every process alive and reads exactly like "no argv was delivered". Measured while writing this module.

⚠️ argv is NUL-separated **and a seed contains newlines**. `tr '\\0' '\\n' | wc -l` counts the seed's own
lines, not arguments, and `tail -1` yields the seed's last LINE rather than the prompt. A census written that
way reported "no misdelivery" for the very session that was misdelivered — a false negative on the defect
itself. Everything here splits on NUL and nothing splits on newline.

**Three outcomes, not two, and the third is the honest one.** `VERIFIED` / `FOREIGN` / `NOT_DELIVERED` are
different facts with different remedies, and collapsing the last two into "not verified" is the `FI-195`
error — a check that cannot distinguish "I was given the wrong thing" from "I cannot see what I was given"
sends its reader to the wrong fix. `NOT_DELIVERED` is emphatically **not** a pass: it is the shipped shape
for every caller that delivers by send-keys, and it is reported as unverifiable rather than as clean.
"""
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

#: A briefing is long. Anything shorter than this in a positional argument is a flag's value or a subcommand,
#: not a seed — the shipped worker profile renders to 1210 characters before any caller prepends to it.
#: Deliberately far below any real seed: this bound decides whether a payload is a CANDIDATE, and a bound set
#: near the real size would reclassify a truncated delivery as "nothing was delivered", which is the
#: permissive direction.
MIN_PAYLOAD_CHARS = 200

VERIFIED = "VERIFIED"
FOREIGN = "FOREIGN"
NOT_DELIVERED = "NOT-DELIVERED"

#: An instant folder as it appears inside a seed: `<...>/<base>-<stamp>-<state>-<optype>-<name>`. Used only
#: to make a FOREIGN verdict SAY WHOSE briefing arrived, which is the difference between an alarm a reader
#: can act on and one they have to investigate from scratch.
_INSTANT_PATH = re.compile(r"/[\w./-]*/\d{8}-\d{8}-(?:inflight|complete|abandoned)-[\w-]+")


def normalise(text: str) -> str:
    """Blank lines dropped, every line right-stripped.

    Two deliveries of the same seed differ in whitespace for reasons that are not misdelivery: a launcher
    passes the file through `$(cat …)`, which strips trailing newlines, and tmux/`send-keys` reflows. None of
    that changes WHOSE briefing it is, and a comparison that fired on it would be switched off within a day.
    Nothing else is normalised — case, order and content are compared exactly.
    """
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


def digest(text: str) -> str:
    return hashlib.md5(normalise(text).encode("utf-8")).hexdigest()


def split_argv(raw: bytes) -> list:
    """argv from a raw `/proc/<pid>/cmdline`. Split on NUL, never on newline — see the module docstring."""
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    return [p.decode("utf-8", "replace") for p in parts]


def payload(argv: list) -> Optional[str]:
    """The briefing-shaped argument in this argv, or None.

    The LONGEST argument at or above `MIN_PAYLOAD_CHARS` that is not a flag. Deliberately not "the last
    positional after parsing the flags": that requires knowing every flag the launcher's binary accepts and
    which of them take values, and being wrong about one silently changes the answer. Length is a property
    of the thing being looked for.
    """
    best = None
    for arg in argv:
        if arg.startswith("-"):
            continue
        if len(arg) < MIN_PAYLOAD_CHARS:
            continue
        if best is None or len(arg) > len(best):
            best = arg
    return best


def carries(rendered: str, argv: list) -> bool:
    """Whether this argv delivers `rendered` — as a WHOLE, in one argument.

    Containment rather than equality, because a correct launcher may legitimately prepend to the seed: §P's
    wrapper adds *"Your instant folder is … and your leased slot is …"* above it, and the live `i2` dispatch
    was delivered its seed with an operator preamble. What must never happen is a DIFFERENT briefing, and
    containment answers that: the misdelivered `i1` argv did not contain i1's seed anywhere.
    """
    target = normalise(rendered)
    if not target:
        return False
    return any(target in normalise(arg) for arg in argv)


def foreign_hint(delivered: str) -> str:
    """Whose briefing this looks like, for the alarm text. Best-effort and labelled as such."""
    found = _INSTANT_PATH.findall(delivered or "")
    if found:
        seen = []
        for path in found:
            if path not in seen:
                seen.append(path)
        return "it names instant folder(s): " + ", ".join(seen[:3])
    first = (delivered or "").strip().splitlines()
    return f"its first line is {first[0][:90]!r}" if first else "it is empty"


@dataclass
class Verdict:
    """What was delivered, judged against what was rendered."""

    state: str
    session: str = ""
    pid: int = 0
    rendered_chars: int = 0
    rendered_md5: str = ""
    delivered_chars: int = 0
    delivered_md5: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        """VERIFIED only. `NOT_DELIVERED` is not a pass — see the module docstring."""
        return self.state == VERIFIED

    def row(self) -> list:
        return [("session", self.session), ("state", self.state), ("pid", str(self.pid)),
                ("rendered_md5", self.rendered_md5), ("delivered_md5", self.delivered_md5 or "(none)"),
                ("detail", self.detail)]


def classify(rendered: str, argv: list, session: str = "", pid: int = 0) -> Verdict:
    """Judge one worker's delivered argv against the seed `dispatch` rendered for it."""
    base = dict(session=session, pid=pid, rendered_chars=len(rendered), rendered_md5=digest(rendered))
    if carries(rendered, argv):
        got = payload(argv) or ""
        return Verdict(state=VERIFIED, delivered_chars=len(got), delivered_md5=digest(got),
                       detail="the delivered argv carries this instant's rendered seed", **base)
    got = payload(argv)
    if got is None:
        return Verdict(state=NOT_DELIVERED, detail=(
            "no briefing-shaped argument was delivered to this process. fleet renders the seed but does "
            "not deliver it, so this is what a send-keys delivery looks like from here, and it is ALSO "
            "what a worker started with no briefing at all looks like. This is NOT a pass: it means the "
            "delivery could not be verified, not that it was correct"), **base)
    return Verdict(state=FOREIGN, delivered_chars=len(got), delivered_md5=digest(got), detail=(
        f"a briefing of {len(got)} chars was delivered and it does NOT contain this instant's rendered "
        f"seed — {foreign_hint(got)}"), **base)


@dataclass
class Probes:
    """The seam between this module and /proc. Injected, so the suite never needs a real process."""

    read_cmdline: Callable[[int], Optional[bytes]]
    children_of: Callable[[int], list] = field(default=lambda pid: [])


def default_probes() -> Probes:
    def read_cmdline(pid: int):
        try:
            return Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return None

    def children_of(pid: int) -> list:
        out = []
        try:
            for task in Path(f"/proc/{pid}/task").glob("*"):
                try:
                    out += [int(x) for x in (task / "children").read_text().split()]
                except OSError:
                    continue
        except OSError:
            return []
        return out

    return Probes(read_cmdline=read_cmdline, children_of=children_of)


def delivered_argv(pid: int, probes: Probes, depth: int = 2) -> tuple:
    """The argv carrying a briefing at or below `pid`, as `(pid, argv)`; `(pid, [])` when there is none.

    One generation down by default, because whether the launcher `exec`s or forks is the launcher's business
    and not a fact this check may depend on. A shim that `exec`s leaves the briefing on the pane pid itself;
    one that forks leaves it on a child.
    """
    frontier, seen, fallback = [pid], set(), (pid, [])
    for _ in range(max(1, depth)):
        nxt = []
        for candidate in frontier:
            if candidate in seen:
                continue
            seen.add(candidate)
            raw = probes.read_cmdline(candidate)
            if raw:
                argv = split_argv(raw)
                if payload(argv) is not None:
                    return candidate, argv
                if not fallback[1]:
                    fallback = (candidate, argv)
            nxt += probes.children_of(candidate)
        frontier = nxt
        if not frontier:
            break
    return fallback


def check_session(session: str, pid: int, rendered: str, probes: Probes) -> Verdict:
    """The whole check for one live worker."""
    found_pid, argv = delivered_argv(pid, probes)
    return classify(rendered, argv, session=session, pid=found_pid or pid)


def collisions(verdicts: list) -> list:
    """Groups of sessions started with a BYTE-IDENTICAL briefing.

    A second signal that needs no knowledge of what any seed SHOULD have been, and therefore survives every
    way the first one can be defeated: two instants dispatched for two milestones must never have been given
    one briefing. On the live fleet this alone names the incident — `dt-i1selfcertifyingcontrols` and
    `dt-v2stackcoordinator`, one prompt, md5 `4ec786cf57d92a2049833c795084ff5a`.
    """
    by_payload = {}
    for verdict in verdicts:
        if not verdict.delivered_md5:
            continue
        by_payload.setdefault(verdict.delivered_md5, []).append(verdict.session)
        by_payload[verdict.delivered_md5] = sorted(set(by_payload[verdict.delivered_md5]))
    return [(md5, names) for md5, names in sorted(by_payload.items()) if len(names) > 1]
