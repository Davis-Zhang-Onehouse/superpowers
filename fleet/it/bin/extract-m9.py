#!/usr/bin/env python3
"""Lift the M9 audit out of run-group5.sh — and say WHICH block was taken.

The runner used to do this inline with `src.index(anchor)`: the FIRST match, with no cardinality check, while
its own `inject()` twenty lines below asserted present-and-unique. A decoy heredoc bearing the anchor above the
real one made the runner certify the decoy as the audit under test (B25, the fleet analogue of i5v2). The
anchor and its terminator are asserted to occur exactly once; anything else is a refusal (exit 2), never a
guess, and nothing is written.

usage: extract-m9.py <run-group5.sh> <out.py>   -> exit 0 and the audit at <out.py>, or exit 2 and nothing.
"""
import pathlib
import sys

ANCHOR = 'cat > "$PY_DIR/m9.py" <<'
TERMINATOR = "\nPY\n"


def refuse(message: str) -> None:
    print(f"extract-m9: {message}", file=sys.stderr)
    sys.exit(2)


def extract(src: str) -> str:
    n = src.count(ANCHOR)
    if n != 1:
        refuse(f"the anchor {ANCHOR!r} occurs {n} times in the caller, not once — refusing to guess which "
               f"block is the audit under test (B25)")
    start = src.index(ANCHOR)
    body = src.index("\n", start) + 1
    end = src.find(TERMINATOR, body)
    if end < 0:
        refuse("the anchored block has no terminator — refusing")
    return src[body:end] + "\n"


def main(argv):
    if len(argv) != 3:
        refuse(__doc__)
    caller, out = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    text = extract(caller.read_text())
    out.write_text(text)
    print(f"extracted the M9 audit: {len(text.splitlines())} lines, from the one block anchored at {ANCHOR!r}")


if __name__ == "__main__":
    main(sys.argv)
