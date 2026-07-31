"""The views — board, status, leases, roadmap — each in a machine form and a human form.

**This module computes nothing.** It transports what `reconcile` decided, and every state string it
prints came out of a `Subject`. That is the whole design: three views in the predecessor each derived
state from a different subset of the facts, `board` drew a dead session `PARKED` and counted it in "N
sessions need you" while `health` said DEAD from the same records (`W2-14`/`OBS-57`), and *the one that
was wrong was the one everybody read*. One producer of a state value removes the possibility of
disagreement rather than fixing an instance of it. The lease view lives here for the same reason: it was
`pool` printing its own view of its own inputs that made three views into three answers (DA-6 0.3).

Three properties are requirements, not presentation choices:

1. **The board shows only slot-holding subjects** (FD-4 / operator Q6). That single filter deletes four
   defects at once — the `HARVESTED`-forever row, the eleven permanently-unclearable legacy rows, the
   `--base` scoping trap in which an instant's own liveness was invisible from its own base, and the
   orphan concept — and **a small board is one people read**. The subjects it does not show are counted
   in the banner rather than silently dropped: a checker whose scope narrows without saying so reads as a
   pass (`OBS-49`).
2. **Every row carries the machine identity, in both forms.** `OBS-62` was an assertion anchored to a
   human summary line that could never match: *"I wrote the check from a model of the board's output
   rather than from its output."* A row without a key is a row no check can anchor to.
3. **Labels are unique across the live fleet.** A 3-character label once collapsed two distinct workers,
   so one's state could be read as the other's (`OBS-32`). `label()` extends until it is unambiguous.

stdout is data: the porcelain forms are tab-separated records with a declared column tuple and no
commentary, headers or blank lines, so `2>/dev/null | cut -f1` is a supported way to read them
(`NFR2-7`). The human forms carry the banner.
"""
import re

from fleet.errors import BadInput
from fleet.reconcile import ACTIONABLE_STATES

#: The shortest label that will ever be handed out. It is a floor, never a truncation: `label()` grows
#: past it until the result is unique, because OBS-32's collapse was a fixed-width prefix.
LABEL_MIN_LEN = 3

#: The porcelain schemas. Declared as data so a consumer (and a test) reads columns from the renderer
#: rather than from a comment that can go stale — `W2-20`'s class, where a flag existed and its
#: documentation did not.
#: `SI-27` added `milestone` as a COLUMN rather than folding it into `note`: the north star is that
#: nothing machine-consumed is parsed out of prose, and "which milestone is this worker on" is the
#: question a coordinator asks a script.
BOARD_COLUMNS = ("identity", "kind", "state", "label", "slot", "milestone", "note")
STATUS_COLUMNS = ("field", "value")
LEASE_COLUMNS = ("slot", "lease", "todo_id", "owner", "tmux", "claimed_at", "path")
ROADMAP_COLUMNS = ("kind", "subject", "severity", "detail", "clears_when", "clears_who")

#: Shown in a human column that has no value. The machine form keeps the field empty — a placeholder is
#: for a reader, and a consumer that has to strip it is a consumer that will forget to.
_EMPTY = "-"


# --- helpers ---------------------------------------------------------------------------------------


def _oneline(text) -> str:
    """One record, one line. A note with a newline in it would split a TSV record in two."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _tsv(rows: list, columns: tuple) -> str:
    """The machine form: one record per line, tab-separated, nothing else on stdout."""
    out = []
    for row in rows:
        out.append("\t".join(_oneline(row.get(column, "")) for column in columns))
    return "".join(line + "\n" for line in out)


def _columns(rows: list, columns: tuple) -> str:
    """The human form: padded columns, two spaces between them, indented under a banner."""
    if not rows:
        return ""
    widths = {c: max(len(_oneline(r.get(c, "")) or _EMPTY) for r in rows) for c in columns}
    lines = []
    for row in rows:
        cells = []
        for column in columns:
            value = _oneline(row.get(column, "")) or _EMPTY
            cells.append(value.ljust(widths[column]))
        lines.append(("  " + "  ".join(cells)).rstrip())
    return "".join(line + "\n" for line in lines)


# --- labels ----------------------------------------------------------------------------------------


def label(identity: str, seen: set) -> str:
    """A short handle for one subject, unique across everything `seen` already holds.

    `seen` is the live fleet's set of handed-out labels and is updated in place, so uniqueness is a
    property of the fleet and not of one call. The label is the shortest prefix of the identity that
    nobody has taken; brevity is best-effort and uniqueness is not, because `OBS-32` was a fixed
    3-character prefix that collapsed two distinct workers and let one's state be read as the other's.
    """
    text = str(identity).strip()
    if not text:
        raise BadInput("a subject with no identity cannot be labelled; identity is a key, not a label")
    for size in range(min(LABEL_MIN_LEN, len(text)), len(text) + 1):
        candidate = text[:size]
        if candidate not in seen:
            seen.add(candidate)
            return candidate
    suffix = 2
    while f"{text}~{suffix}" in seen:
        suffix += 1
    candidate = f"{text}~{suffix}"
    seen.add(candidate)
    return candidate


# --- the board -------------------------------------------------------------------------------------


def _slot_holders(subjects) -> list:
    """FD-4: the board's whole population. A harvested record names the slot it used and no longer holds
    it, and rendering that is how the board filled with rows nobody could clear."""
    return [s for s in subjects if s.holds_slot]


def _needs_a_human(subjects) -> list:
    """The "needs you" population, taken from `reconcile.ACTIONABLE_STATES` rather than decided here.

    `W2-14`/`OBS-57`: the predecessor counted DEAD sessions in this banner while drawing them PARKED. A
    dead worker needs a reap, not a keystroke, and a banner that cries for attention on a session nobody
    can answer trains people to ignore the banner.
    """
    return [s for s in subjects if s.state in ACTIONABLE_STATES]


def _row_state(subject) -> str:
    """The state, as `reconcile` decided it. **This is the only place a state reaches a view**, and it
    is a lookup rather than a derivation on purpose: a second derivation from the folder name, the record
    or the lease is precisely how three views came to disagree."""
    return subject.state


def _board_cells(subjects) -> list:
    seen = set()
    cells = []
    for subject in sorted(subjects, key=lambda s: s.identity):
        cells.append({
            "identity": subject.identity,
            "kind": subject.kind,
            "state": _row_state(subject),
            "label": label(subject.identity, seen),
            "slot": subject.evidence.get("slot", ""),
            "milestone": subject.evidence.get("milestone", ""),
            "note": subject.note,
        })
    return cells


def board(subjects, porcelain: bool = False) -> str:
    """Every subject holding a slot, and nothing else (FD-4).

    The hidden population is counted in the human banner: `N not holding a slot`. It is not an alarm and
    not a row — it is the scope, stated, so that a small board cannot be mistaken for a broken one.
    """
    subjects = list(subjects)
    held = _slot_holders(subjects)
    cells = _board_cells(held)
    if porcelain:
        return _tsv(cells, BOARD_COLUMNS)
    banner = (f"fleet: {len(held)} holding a slot · {len(_needs_a_human(held))} needs you · "
              f"{len(subjects) - len(held)} not holding a slot (not shown, FD-4)")
    return banner + "\n" + _columns(cells, ("label", "identity", "state", "slot", "milestone",
                                                 "note"))


# --- one subject -----------------------------------------------------------------------------------


def status(subject, porcelain: bool = False) -> str:
    """One subject in full, including the evidence `reconcile` joined to reach its state.

    The evidence is reproduced verbatim and never summarised into a verdict: a report that hides what it
    was derived from is a report you cannot check when it is wrong.
    """
    fields = [("identity", subject.identity),
              ("kind", subject.kind),
              ("state", _row_state(subject)),
              ("holds_slot", "true" if subject.holds_slot else "false"),
              ("note", subject.note)]
    fields += [(f"evidence.{key}", value) for key, value in sorted(subject.evidence.items())]
    if porcelain:
        return _tsv([{"field": key, "value": value} for key, value in fields], STATUS_COLUMNS)
    head = f"{subject.identity}  {_row_state(subject)}  ({subject.kind})"
    body = [(key, value) for key, value in fields if key not in ("identity", "kind", "state")]
    return head + "\n" + _columns([{"field": k, "value": v} for k, v in body], STATUS_COLUMNS)


# --- the lease view --------------------------------------------------------------------------------


def _lease_rows(pool_state) -> list:
    """Normalise whatever the caller has: a `Pool`, or an iterable of `(slot, lease)` pairs / leases.

    `render` reads the pool; it does not ask the pool to describe itself. That is the point of this
    function living here (DA-6 0.3).
    """
    if hasattr(pool_state, "slots") and hasattr(pool_state, "lease"):
        return [(slot, pool_state.lease(slot)) for slot in pool_state.slots()]
    rows = []
    for item in pool_state:
        if isinstance(item, tuple):
            rows.append((item[0], item[1]))
        else:
            rows.append((item.slot, item))
    return rows


def leases(pool_state, porcelain: bool = False) -> str:
    """Every enrolled slot and who holds it. Free slots are rows too — capacity is a fact a reader
    needs, and "nothing is shown" cannot distinguish an empty pool from an unread one.

    A slot can be in THREE states, not two (`SI-7`). `held` and `free` were the only labels, and a slot
    holding an **interrupted** claim — a claim directory whose lease body never landed — was reported
    `free` while no claimant could take it. That is the same disagreement in the reporting layer that the
    pool had internally: `lease()` reads the body and saw nothing, `free_slots()` tests the directory and
    saw it taken. A reader who acts on `free` here gets `NoCapacity`.

    Reporting is IMMEDIATE while reclaiming waits for an age floor, and the asymmetry is deliberate: saying
    "this slot is not usable" the moment it is true costs nothing if the claim turns out to be a
    microsecond-old birth, whereas DELETING on the same evidence would destroy a live worker's lease.
    """
    interrupted = ()
    if hasattr(pool_state, "interrupted_claims"):
        # min_age_s=0: see above. `render` reads the pool rather than asking it to describe itself, which
        # is why the query lives here (DA-6 0.3).
        interrupted = {slot for slot, _ in pool_state.interrupted_claims(min_age_s=0.0)}
    cells = []
    for slot, lease in _lease_rows(pool_state):
        cells.append({
            "slot": slot,
            "lease": "held" if lease is not None else ("interrupted" if slot in interrupted else "free"),
            "todo_id": getattr(lease, "todo_id", "") if lease else "",
            "owner": getattr(lease, "base_instant", "") if lease else "",
            "tmux": getattr(lease, "tmux", "") if lease else "",
            "claimed_at": getattr(lease, "claimed_at", "") if lease else "",
            "path": str(getattr(lease, "path", "")) if lease else "",
        })
    if porcelain:
        return _tsv(cells, LEASE_COLUMNS)
    held = sum(1 for c in cells if c["lease"] == "held")
    stuck = sum(1 for c in cells if c["lease"] == "interrupted")
    banner = (f"slots: {len(cells)} enrolled · {held} held · {len(cells) - held - stuck} free"
              + (f" · {stuck} INTERRUPTED (no lease body; `reap` clears them)" if stuck else ""))
    return banner + "\n" + _columns(cells, LEASE_COLUMNS)


# --- the roadmap -----------------------------------------------------------------------------------


def roadmap_view(roadmap, porcelain: bool = False) -> str:
    """`roadmap.report()`, rendered. Readiness, blockers and the population row are all `roadmap`'s
    derivations; this function decides nothing about them, including which rows are RED."""
    rows = roadmap.report() if hasattr(roadmap, "report") else list(roadmap)
    cells = [{
        "kind": row.kind,
        "subject": row.subject,
        "severity": row.severity,
        "detail": row.detail,
        "clears_when": row.clears_when or "",
        "clears_who": row.clears_who or "",
    } for row in rows]
    if porcelain:
        return _tsv(cells, ROADMAP_COLUMNS)
    attention = sum(1 for c in cells if c["severity"] == "attention")
    banner = f"roadmap: {len(cells)} row(s) · {attention} needing attention"
    return banner + "\n" + _columns(cells, ROADMAP_COLUMNS)
