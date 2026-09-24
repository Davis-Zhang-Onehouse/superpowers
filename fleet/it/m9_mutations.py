"""SI-9's four M9 mutations as data, and the one rule that reads their outcome.

Shared by `run-m9-mutation.sh`, which injects each mutation into a `cp -r` copy of the package and audits it,
and by the hermetic `tests/test_m9_mutations.py`, which pins every anchor as present-and-unique in the
CURRENT tree. That test is the drift canary: an anchor that stops being unique fails there in seconds
rather than in a 45-minute release gate.

`FB-108`. The runner used to inject all four mutations in ONE heredoc and never checked its exit status. When
`atomic_write_if` gave M2's anchor three matches, the uniqueness assert aborted the heredoc after M1, so M2,
M3 and M4 were never written. The loop then audited three UN-mutated copies, they passed, and it reported
each one SURVIVED — "the rule did not fire". A mutation that never applied read as a hole in the audit.
The runner now carries an applied-state per mutation, and `classify` is the only place that turns an
outcome into a verdict. An unapplied mutation is NOT-APPLIED, never SURVIVED and never KILLED: it proves
nothing about the rule either way.

CLI (what the runner calls):
    python3 m9_mutations.py rel <n>                         -> the mutated file, relative to the package root
    python3 m9_mutations.py why <n>                         -> the audit text that must kill mutant n
    python3 m9_mutations.py inject <copy-root> <n>          -> rc 0 applied; rc 3 not applied, file untouched
    python3 m9_mutations.py classify <n> <applied 0|1> <audit-rc|-> <audit-output|->
                                                            -> prints `<PASS|FAIL> <KILLED|SURVIVED|WRONG-REASON|NOT-APPLIED>`
"""
import sys
from pathlib import Path

#: Each anchor must occur EXACTLY once in its file. A mutation applied twice, or not at all, makes the kill
#: unattributable. `why` is what the mutant must be caught BY: a kill for the wrong reason is not a kill.
MUTATIONS = {
    1: {
        "rel": "src/fleet/pool.py",
        "old": "        record.unlink()",
        "new": "        record = Path.home() / 'victim.json'\n        record.unlink()",
        "label": "M1 a second assignment putting the target under $HOME",
        "why": "derived neither from the store root",
    },
    2: {
        "rel": "src/fleet/atomic.py",
        #: Multi-line, and not the bare `os.unlink(tmp)` line. `atomic_write_if` added a second 12-space
        #: `os.unlink(tmp)` and a 16-space one that contains it as a substring, so the one-line anchor
        #: matched three times (FB-108). A line-anchored regex is no fix either: it still matches two lines.
        #: The trailing comment is what only `atomic_write`'s staging delete carries.
        "old": "            os.unlink(tmp)\n        except OSError:\n"
               "            pass                           # a staging file",
        "new": "            os.unlink('/var/tmp/whatever')\n        except OSError:\n"
               "            pass                           # a staging file",
        "label": "M2 a delete of an absolute literal",
        #: NOT "derived neither from the store root": a string literal leaves no local name to trace, so the
        #: audit takes its UNVERIFIABLE branch — it refuses to vouch for a delete it cannot attribute at all.
        "why": "could not name",
    },
    3: {
        "rel": "src/fleet/store.py",
        "old": "\nSCHEMA_VERSION = 1",
        "new": "\ndef _sneaky_cleanup(victim):\n    victim.unlink()\n\n\nSCHEMA_VERSION = 1",
        "label": "M3 a brand-new undeclared delete site",
        "why": "UNDECLARED DELETE SITE",
    },
    4: {
        "rel": "src/fleet/pool.py",
        "old": "        record.unlink()",
        "new": "        import os as _o\n        record = Path(_o.environ['HOME']) / 'x.json'\n"
               "        record.unlink()",
        "label": "M4 a target read out of the environment",
        "why": "derived neither from the store root",
    },
}

EXIT_NOT_APPLIED = 3


class NotApplied(Exception):
    """The mutation was not written. The file is left exactly as it was."""


def anchor_count(root, n):
    m = MUTATIONS[n]
    return (Path(root) / m["rel"]).read_text().count(m["old"])


def inject(root, n):
    """Apply mutation `n` under `root` (a package root holding `src/`), or raise NotApplied having written
    nothing. Present-and-unique is checked BEFORE the write, and the write is read back."""
    m = MUTATIONS[n]
    path = Path(root) / m["rel"]
    text = path.read_text()
    count = text.count(m["old"])
    if count != 1:
        raise NotApplied(f"{m['label']}: anchor appears {count} times in {m['rel']}, not once; nothing written")
    mutated = text.replace(m["old"], m["new"])
    path.write_text(mutated)
    if path.read_text() != mutated or mutated == text:
        raise NotApplied(f"{m['label']}: {m['rel']} does not hold the mutation after writing it")


def classify(n, applied, audit_rc, output):
    """(verdict, kind) for one mutant. The ONLY place an outcome becomes a verdict.

    Order matters: `applied` is decided first, so a copy that was never mutated can never be read as
    SURVIVED (the audit passing proves nothing about a rule that was not exercised) nor as KILLED."""
    if not applied:
        return "FAIL", "NOT-APPLIED"
    if audit_rc is None:
        raise ValueError(f"M{n} was applied but no audit exit code was given")
    if audit_rc == 0:
        return "FAIL", "SURVIVED"
    if MUTATIONS[n]["why"] in output:
        return "PASS", "KILLED"
    return "FAIL", "WRONG-REASON"


def main(argv):
    verb = argv[0] if argv else ""
    if verb in ("rel", "why") and len(argv) == 2:
        print(MUTATIONS[int(argv[1])][verb])
        return 0
    if verb == "inject" and len(argv) == 3:
        n = int(argv[2])
        try:
            inject(argv[1], n)
        except NotApplied as exc:
            print(f"  NOT APPLIED — {exc}", file=sys.stderr)
            return EXIT_NOT_APPLIED
        print(f"  {MUTATIONS[n]['label']}: injected")
        return 0
    if verb == "classify" and len(argv) == 5:
        n, applied = int(argv[1]), argv[2] == "1"
        audit_rc = None if argv[3] == "-" else int(argv[3])
        output = "" if argv[4] == "-" else Path(argv[4]).read_text(errors="replace")
        print(*classify(n, applied, audit_rc, output))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
