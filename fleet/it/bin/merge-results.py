#!/usr/bin/env python3
"""Merge this run's per-runner registers into RESULTS.tsv — the single writer, called by run-all.sh.

usage: merge-results.py <it-root> <runner-name>...   (each name's register is <it-root>/RESULTS-closeout-<name>.tsv)

A section that RAN replaces its rows and its NOT-RUN row; rows of sections this run did not execute are kept
(the register is current state across runs, so a targeted full run must not blank the rest). An `OWN-<case>`
FAIL row (lib.sh: a runner wrote a row its own regex did not claim) is that runner's verdict on its regex; it is
dropped only when the run that would re-judge it ran — its case is owned this time, or its section ran — so a
default-roster run cannot erase a standalone §F's OWN-F… row while the stale twin it flagged stays (found in
review). Prints the tallies run-all.sh logs. Extracted from run-all.sh so a hermetic test can drive it.
"""
import pathlib
import sys

SECTIONS = "ABCDEFGHIJKLMNOP"


def rows(path: pathlib.Path) -> list:
    return [line for line in path.read_text().splitlines()[1:] if line.strip()]


def case_of(row: str) -> str:
    return row.split("\t")[0]


def merge(root: pathlib.Path, names: list) -> str:
    main = root / "RESULTS.tsv"
    header = main.read_text().splitlines()[0]
    fresh, owned = [], set()
    for name in names:
        register = root / f"RESULTS-closeout-{name}.tsv"
        if not register.is_file():
            continue
        for row in rows(register):
            fresh.append(row)
            owned.add(case_of(row))
    # A section that RAN replaces its NOT-RUN row. Derived from the case ids present, never typed: a hand-kept
    # list of "which sections ran" is a second copy of the truth (SD-2).
    ran = {sec for sec in SECTIONS
           if any(case_of(r).startswith(sec) and case_of(r)[1:2].isdigit() for r in fresh)}
    owned |= {f"§{sec}" for sec in ran}

    def drop(row: str) -> bool:
        case = case_of(row)
        if case in owned:
            return True
        if case.startswith("OWN-"):
            flagged = case[4:]
            return flagged in owned or (flagged[:1] in ran and flagged[1:2].isdigit())
        return False

    existing = rows(main)
    kept = [r for r in existing if not drop(r)]
    notrun = [r for r in kept if "\tNOT-RUN\t" in r]
    kept = [r for r in kept if "\tNOT-RUN\t" not in r]
    main.write_text("\n".join([header] + kept + fresh + notrun) + "\n")
    dupes = {}
    for r in kept + fresh + notrun:
        dupes[case_of(r)] = dupes.get(case_of(r), 0) + 1
    return (f"merged {len(fresh)} fresh row(s) for {len(owned)} owned id(s); {len(kept)} untouched; "
            f"{len(notrun)} NOT-RUN\nduplicate case ids: {sorted(k for k, v in dupes.items() if v > 1) or 'none'}")


if __name__ == "__main__":
    print(merge(pathlib.Path(sys.argv[1]), sys.argv[2:]))
