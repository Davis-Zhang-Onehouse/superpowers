#!/usr/bin/env python3
"""Check two factual properties of a fleet skill. Usage: lint-skill.py <skill-dir>

V1  every `fleet <verb>` named in a CODE SPAN is a registered verb, unless marked
    `<!-- v1-proposed: <verb> -->`.
V2  every sentence claiming a refusal cites an integration case that PASSED, via
    `<!-- v2-cite: <slug> <CASE-ID> -->`.

SCOPE: every markdown file the skill SHIPS — `SKILL.md`, any sibling `*.md`, and `references/**/*.md`.
`tests/` is excluded: those are fixtures, not prose a reader is routed to.

This used to read `SKILL.md` and nothing else, which left `references/` — the pages carrying the worked
examples, and therefore the commands most likely to be copied and run — completely unchecked. V1 findings
name the file they came from. V2 pools the whole skill: a citation in `SKILL.md` covers a claim made in a
reference, because a reference is part of the skill and not a separate document.

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

#: A refusal claim: a sentence promising that THE TOOL will stop you. Lines that are themselves markers are
#: excluded, or the marker that clears a claim would read as another claim.
#:
#: `cannot` and `may not` used to be in this list and were removed, because they match the WORD without
#: matching the CLAIM — they have no subject. Measured over the ten skills this lint actually runs on: of 47
#: matched sentences, the 25 containing a refusal word were all genuine tool guarantees, while 22 matched on
#: `cannot`/`may not` alone and almost all of those were ordinary prose — "Two judgements the tool cannot
#: make", "a goal that cannot be softened later", "If you cannot say what would". None of them was a promise
#: about `fleet`, and none of them was citable, so the only way to clear them was to reword the sentence. That
#: happened three times in one session, in three different skills, and each reword was the lint editing prose
#: it had no finding about. A check that changes writing without catching defects is a check people route
#: around. Dropping the two words costs no file-level coverage: every skill that still needs a citation raises
#: one through a refusal word.
#:
#: `refusing`, `refuse`, `rejects`, `rejected` and `rejecting` were ADDED, having been missed. Two real
#: guarantees escaped the old list — "makes the gate refuse a `READY` verdict" and "is rejected with
#: *refusing to shadow it*" — both of which are exactly what V2 exists to hold evidence against.
CLAIM = re.compile(r"^(?![ \t]*<!--).*\b(refuses|refused|refusing|refuse|rejects|rejected|rejecting)\b.*$",
                   re.I | re.M)

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


def skill_docs(skill: pathlib.Path) -> list:
    """Every markdown file the skill ships as documentation, SKILL.md first.

    `tests/` is deliberately absent: a fixture that names a deliberately-bogus verb is doing its job, and
    linting it would make the suites unwritable.
    """
    docs = [skill / "SKILL.md"]
    docs += sorted(p for p in skill.glob("*.md") if p.name != "SKILL.md")
    docs += sorted(skill.glob("references/**/*.md"))
    return [p for p in docs if p.is_file()]


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
    if not (skill / "SKILL.md").is_file():
        print(f"lint-skill: no SKILL.md in {skill}", file=sys.stderr)
        return 2
    docs = skill_docs(skill)
    texts = {p: p.read_text() for p in docs}
    findings = []

    src = pathlib.Path(os.environ.get("FLEET_SRC") or DEFAULT_FLEET_SRC)
    known = verbs_from(src)
    # V1 is per-file: an unregistered verb is a defect at a location, and a finding that does not say which
    # file it came from sends the reader hunting through the whole skill.
    for path, text in texts.items():
        where = path.relative_to(skill)
        proposed = set(PROPOSED.findall(text))
        for verb in sorted(verbs_named(text) - known - proposed):
            findings.append(f"{where}: V1: `fleet {verb}` is named in a code span and is not a registered "
                            f"verb. If it is deliberate, mark it: <!-- v1-proposed: {verb} -->")
        for verb in sorted(proposed & known):
            findings.append(f"{where}: V1: `{verb}` is marked <!-- v1-proposed --> and IS now a registered "
                            f"verb. Remove the marker — a stale promise reads as a gap that does not exist.")

    results = pathlib.Path(os.environ.get("FLEET_RESULTS") or DEFAULT_RESULTS)
    passing = passing_cases(results)
    # V2 pools the skill. A reference is part of the skill, so a citation in SKILL.md covers a claim made in
    # a reference; requiring each file to re-cite would only produce duplicated markers.
    cited = {case for text in texts.values() for _slug, case in CITE.findall(text)}
    for case in sorted(cited - passing):
        findings.append(f"V2: cited case {case!r} is not PASS in {results}. A claim may only cite a case "
                        f"that actually passed.")
    claims = [(path.relative_to(skill), m.group(0).strip())
              for path, text in texts.items() for m in CLAIM.finditer(text)]
    if claims and not cited:
        where, first = claims[0]
        findings.append(f"V2: {len(claims)} sentence(s) claim a refusal and this skill cites no case. Add "
                        f"<!-- v2-cite: <slug> <CASE-ID> -->. First claim ({where}): {first[:110]!r}")

    if show:
        notes = case_notes(results)
        for path, text in texts.items():
            for slug, case in sorted(CITE.findall(text)):
                print(f"  {path.relative_to(skill)}: {slug} -> {case}: {notes.get(case, '(no note)')[:150]}")

    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
