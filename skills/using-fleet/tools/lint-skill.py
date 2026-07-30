#!/usr/bin/env python3
"""Check two factual properties of a fleet skill. Usage: lint-skill.py <skill-dir>

V1  every `fleet <verb>` named in a CODE SPAN is a registered verb, unless marked
    `<!-- v1-proposed: <verb> -->`.
V2  every sentence claiming a refusal cites an integration case that PASSED, via
    `<!-- v2-cite: <slug> <CASE-ID> -->`.

Exit 0 = clean, 1 = findings, 2 = bad input.

Why code spans only: a whole-document match for `fleet <word>` fires on ordinary prose — "fleet refuses it",
"fleet state is authoritative" — and a lint that reports its own author's sentences gets switched off. This
was measured, not guessed: running V1 over the design spec produced exactly those two false positives before
the extraction was narrowed.

Why a marker rather than tolerance: a skill may legitimately name a verb that is not built yet, and the
difference between a promise and a bug is that somebody wrote the promise down. An unmarked unknown verb is a
defect; a marked one is a commitment you can grep for.

Why V2 exists at all: a skill's whole value is telling a reader what the tool will refuse. An uncited refusal
claim is a promise with no evidence behind it, and the reader has no way to tell a real guarantee from a
hopeful sentence. Citing a case that PASSED makes the promise falsifiable — and if the case stops passing, the
skill stops linting, which is the coupling we want.

WHAT V2 DOES NOT CHECK, and you must not read it as checking: **relevance.** It verifies that a cited case
passed, not that the case is about the claim beside it. A citation can be green and irrelevant, and that is not
hypothetical — the first skill written with this lint cited `M13` (which is about `selftest`'s dirty-tree
handling) for a claim about a verb naming its store, and the lint accepted it. `--show` exists for exactly
that: it prints each citation next to the cited case's own note, so a reviewer can check the pairing in one
command instead of trusting it.
"""
import os
import pathlib
import re
import sys

#: The package root, from THIS FILE's location. `fleet` lives at <repo>/fleet/src in the same repository as
#: these skills, which is the whole reason this lint can be a hard check rather than a conditional one: there
#: is no cross-repo path to be unset, and therefore no half of this lint that can silently skip.
_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[3]                      # lint-skill.py -> tools -> using-fleet -> skills -> <repo>
DEFAULT_FLEET_SRC = _REPO / "fleet" / "src"
DEFAULT_RESULTS = _REPO / "fleet" / "it" / "RESULTS.tsv"

FENCE = re.compile(r"```.*?```", re.S)
SPAN = re.compile(r"`([^`\n]+)`")
#: `fleet <verb>` as a COMMAND. The negative lookbehind excludes a path or module — `bin/fleet`,
#: `.fleet/`, `fleet/src` — because a directory listing inside a fenced block is ordinary content in a
#: skill, and `bin/fleet             this launcher` was read as the verb `this`. Found by running this
#: lint over the first skill written with it.
COMMAND = re.compile(r"(?<![/.\w-])fleet\s+([a-z][a-z0-9-]*)")
PROPOSED = re.compile(r"<!--\s*v1-proposed:\s*([a-z][a-z0-9-]*)\s*-->")
CITE = re.compile(r"<!--\s*v2-cite:\s*(\S+)\s+(\S+)\s*-->")

#: A refusal claim. Deliberately narrow — the words a skill uses to promise the tool will stop you. Lines that
#: are themselves markers are excluded, or the marker that clears a claim would read as another claim.
CLAIM = re.compile(r"^(?![ \t]*<!--).*\b(refuses|refused|will refuse|cannot|may not)\b.*$", re.I | re.M)

#: A verb list is not the only thing `fleet` could be followed by inside a code span. `fleet brief --instant`
#: names a verb; `fleet/src/fleet` is a path and `fleet.cli` is a module. Filtered here rather than by making
#: COMMAND cleverer, because each exclusion is a decision worth reading.
NOT_A_VERB_CONTEXT = ("/", ".", "_")


def verbs_from(src: pathlib.Path) -> set:
    sys.path.insert(0, str(src))
    try:
        from fleet.cli import VERBS
    except Exception as exc:                       # noqa: BLE001 - reported, never guessed around
        raise SystemExit(f"lint-skill: cannot import fleet.cli from {src} ({exc}). "
                         f"Set FLEET_SRC if the package has moved.")
    return set(VERBS)


def passing_cases(results: pathlib.Path) -> set:
    if not results.is_file():
        raise SystemExit(f"lint-skill: no results file at {results}. This lint cannot check a citation "
                         f"without it, and passing anyway would make an uncited claim indistinguishable "
                         f"from a verified one.")
    out = set()
    for line in results.read_text().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip() == "PASS":
            out.add(parts[0].strip())
    return out


def code_regions(text: str) -> list:
    """Fenced blocks, plus inline spans from what is left after the fences are removed."""
    regions = [m.group(0) for m in FENCE.finditer(text)]
    regions += [m.group(1) for m in SPAN.finditer(FENCE.sub("", text))]
    return regions


def verbs_named(text: str) -> set:
    named = set()
    for region in code_regions(text):
        for match in COMMAND.finditer(region):
            after = region[match.end():match.end() + 1]
            if after in NOT_A_VERB_CONTEXT:
                continue
            named.add(match.group(1))
    return named


def case_notes(results: pathlib.Path) -> dict:
    """case id -> the note the runner wrote. Used by `--show` so a citation's RELEVANCE can be reviewed."""
    out = {}
    for line in results.read_text().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 4:
            out[parts[0].strip()] = parts[3].strip()
    return out


def main(argv: list) -> int:
    show = "--show" in argv
    argv = [a for a in argv if a != "--show"]
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    skill = pathlib.Path(argv[1])
    doc = skill / "SKILL.md"
    if not doc.is_file():
        print(f"lint-skill: no SKILL.md in {skill}", file=sys.stderr)
        return 2
    text = doc.read_text()
    findings = []

    src = pathlib.Path(os.environ.get("FLEET_SRC") or DEFAULT_FLEET_SRC)
    known = verbs_from(src)
    proposed = set(PROPOSED.findall(text))
    for verb in sorted(verbs_named(text) - known - proposed):
        findings.append(f"V1: `fleet {verb}` is named in a code span and is not a registered verb. "
                        f"If it is deliberate, mark it: <!-- v1-proposed: {verb} -->")
    for verb in sorted(proposed & known):
        findings.append(f"V1: `{verb}` is marked <!-- v1-proposed --> and IS now a registered verb. "
                        f"Remove the marker — a stale promise reads as a gap that does not exist.")

    results = pathlib.Path(os.environ.get("FLEET_RESULTS") or DEFAULT_RESULTS)
    passing = passing_cases(results)
    cited = {case for _slug, case in CITE.findall(text)}
    for case in sorted(cited - passing):
        findings.append(f"V2: cited case {case!r} is not PASS in {results}. A claim may only cite a case "
                        f"that actually passed.")
    claims = [m.group(0).strip() for m in CLAIM.finditer(text)]
    if claims and not cited:
        findings.append(f"V2: {len(claims)} sentence(s) claim a refusal and this file cites no case. Add "
                        f"<!-- v2-cite: <slug> <CASE-ID> -->. First claim: {claims[0][:110]!r}")

    if show:
        notes = case_notes(results)
        for slug, case in sorted(CITE.findall(text)):
            print(f"  {slug} -> {case}: {notes.get(case, '(no note)')[:150]}")

    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
