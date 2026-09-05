"""Typed profile manifests: declared kind, required clauses, placeholders, invocation templates.

**The kind is declared in `profile.json` or it does not exist.** It is never inferred from the
charter's prose. Grepping it out of prose failed in *both* directions: a greedy same-line match let a
later word win, and a `^Kind:` anchor missed a mid-line declaration — and the outcome was that **3 of
5 shipped profiles silently fell back to `worker`** (`OBS-5`/`OBS-64`). A kind-aware linter that picks
the wrong kind is worse than no linter, because it converts *"unchecked"* into *"checked and fine"*.
So `load` raises rather than defaults, and `lint` never guesses a kind.

`render` fails on an unresolved `{{TOKEN}}` instead of emitting it literally (`SR-C10-2`). The old
renderer left unknown tokens in place with a human checklist as the only defence, and the rendered
charter is the first thing a dispatched worker reads.

`lint` covers **invocation templates**, which the original specification omitted (`FI-5` /
`RCF-B-8` / `R5I-7`): a shared CI-dispatch command *"silently runs the base branch's workflow
definition unless `--ref` is passed"*. That was fixed in one instant's RUNBOOK and left wrong in the
shared profile, so a profile shipping a command whose default silently targets the wrong thing passed
every check there was. Every flag whose omission changes the *target* of an invocation is required
here, not defaulted.

This module reads `charter.md`/`seed.txt` as the **text under lint** — the artifact being checked —
and never for a control signal (AC-2). Every control value it acts on comes from `profile.json`.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from fleet.errors import BadInput
from fleet.layout import Violation

KINDS = ("worker", "coordinator", "compaction")

#: Kinds whose charter is read by an instant that runs work and can therefore be waiting on CI.
#: `OBS-63`: the AWAITING-CI clause landed in the fix profile and not the compaction profile, because
#: "where else does this shape live?" was answered by grepping for the text just fixed — which finds
#: copies and never counterparts. Both kinds are named here so neither can be the forgotten one.
WORKER_FACING = ("worker", "compaction")

#: `W2-13`/`OBS-58`: both flags that make a compaction a compaction defaulted wrong, on a path taken
#: once, at a cap of 1, unrepairable by rename. The agreement is a table, not a default.
OPTYPES_OF_KIND = {
    "worker": ("append",),
    "coordinator": ("append",),
    "compaction": ("compact",),
}
OPTYPES = ("append", "compact")

MANIFEST = "profile.json"
ARTIFACTS = ("charter.md", "seed.txt")

#: The clause every worker-facing profile must carry: the phase is STRUCTURED state. Note this is the
#: `fleet declare` command and not the token `AWAITING-CI` — the profiles that shipped the failure all
#: contained the token, in a sentence telling the worker to write it into `HANDOFF.md` as prose
#: (`AC-9`/DA-6 drop 3). A lint that greps for the token passes exactly the files that are wrong.
#:
#: I-6: this clause used to read `fleet declare phase awaiting-ci` — a spelling `parse` REFUSES
#: (`declare` declares no positionals, exit 2), so the lint required profiles to teach a command that
#: could never succeed. It is now two substrings, both required in the SAME artifact, because the
#: instant value between them varies per profile (`{{INSTANT}}` in a template, `"$INSTANT"` in a seed):
#: one substring alone is either too weak (`fleet declare --instant` passes a charter that never says
#: which phase) or unmatchable (no single stable spelling spans the instant value).
AWAITING_CI_PARTS = ("fleet declare --instant", "--phase awaiting-ci")
#: The display form for messages; the check matches `AWAITING_CI_PARTS`, never this string.
AWAITING_CI_CLAUSE = "fleet declare --instant <instant> --phase awaiting-ci"

#: Flags whose omission changes the TARGET of an invocation rather than its options. Omitting one is
#: not a smaller version of the command; it is a different command pointed somewhere else.
TARGET_FLAGS = (
    ("gh workflow run", "--ref",
     "without --ref this runs the BASE branch's workflow definition, not this branch's"),
    ("gh pr create", "--base",
     "without --base this targets the repository's default branch"),
)

_TOKEN = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")

#: An authoring stub that survived into a shipped profile. `OBS-63`: `the-tip-in-your-CHARTER` shipped
#: in `compact-ansi/seed.txt` where two baseline run ids belonged, disagreeing with its own sibling
#: charter.
_AUTHORING = re.compile(r"the-[a-z][a-z-]*-in-your-[A-Z]{3,}|FILL-?ME|TODO-?FILL|<[A-Z_]{3,}>")

#: A static commit sha. `OBS-41` flagged these; the `OBS-42` over-correction then flagged a CI **run
#: id**, because digits are valid hex — and pinning run ids is what the brief contract *requires*. The
#: discriminator is that a sha carries a hex **letter**; a run id is all digits. Both lookaheads are
#: load-bearing: drop the `[a-f]` one and every run id is a "sha".
_SHA = re.compile(r"\b(?=[0-9a-f]{7,40}\b)(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b")

#: A CI run id, as pinned by the brief contract. Nine digits or more, all digits.
_RUN_ID = re.compile(r"\b\d{9,}\b")


@dataclass(frozen=True)
class Profile:
    """A profile as a type. `path`, `kind`, `charter`, `seed` are the declared interface; the three
    manifest collections follow with defaults, because `lint` cannot check an invocation template it
    was never given and re-reading the manifest per check would be a second parse of one fact."""

    path: Path
    kind: str
    charter: str
    seed: str
    placeholders: tuple = field(default=())
    requires_clauses: tuple = field(default=())
    invocation_templates: tuple = field(default=())

    @classmethod
    def load(cls, path: Path) -> "Profile":
        path = Path(path)
        manifest = path / MANIFEST
        if not manifest.is_file():
            raise BadInput(
                f"{path} declares no kind: there is no {MANIFEST}. The kind is a declared field and is "
                f"NEVER read out of charter prose — 3 of 5 profiles that were read that way silently "
                f"became `worker`. Add {MANIFEST} with \"kind\" in {KINDS}."
            )
        try:
            data = json.loads(manifest.read_text())
        except json.JSONDecodeError as exc:
            raise BadInput(f"{manifest} is not valid JSON: {exc}") from None
        if not isinstance(data, dict):
            raise BadInput(f"{manifest} must be a JSON object with a \"kind\" field, not {type(data).__name__}")

        kind = data.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise BadInput(
                f"{manifest} does not declare a kind. There is no default: an undeclared kind is an "
                f"error, not a `worker`. Set \"kind\" to one of {KINDS}. The charter's prose is not "
                f"consulted — a kind guessed from prose converts 'unchecked' into 'checked and fine'."
            )
        kind = kind.strip()
        if kind not in KINDS:
            raise BadInput(
                f"{manifest} declares kind={kind!r}, which is outside the declared domain "
                f"{KINDS}. Refused, not coerced (FD-1)."
            )

        charter_path = path / "charter.md"
        if not charter_path.is_file():
            raise BadInput(f"{path} has {MANIFEST} but no charter.md; a profile renders a charter.")
        seed_path = path / "seed.txt"

        return cls(
            path=path,
            kind=kind,
            charter=charter_path.read_text(),
            seed=seed_path.read_text() if seed_path.is_file() else "",
            placeholders=_strings(data, "placeholders", manifest),
            requires_clauses=_strings(data, "requires_clauses", manifest),
            invocation_templates=_strings(data, "invocation_templates", manifest),
        )

    def artifacts(self) -> tuple:
        """`(name, text)` for every artifact this profile renders. One list, so a check cannot look at
        the charter and quietly skip the seed — which is how the two disagreed in the first place."""
        return (("charter.md", self.charter), ("seed.txt", self.seed))

    def render(self, context: dict) -> dict:
        """Substitute `{{NAME}}` in every artifact. Raises on any token left over.

        Nothing is returned when a token is unresolved: the caller cannot accidentally write a charter
        with a literal `{{VAR}}` in it, which is the artifact the worker reads first (`SR-C10-2`).
        """
        out = {}
        for name, text in self.artifacts():
            rendered = _TOKEN.sub(
                lambda m: context[m.group(1)] if m.group(1) in context else m.group(0), text)
            left = sorted(set(_TOKEN.findall(rendered)))
            if left:
                raise BadInput(
                    f"{self.path.name}/{name} has unresolved placeholder(s) "
                    + ", ".join("{{%s}}" % t for t in left)
                    + f". Supplied context: {sorted(context)}. Refusing to emit an artifact with a "
                    "literal placeholder in it."
                )
            out[name.split(".")[0]] = rendered
        return out


def _strings(data: dict, key: str, manifest: Path) -> tuple:
    value = data.get(key, [])
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise BadInput(f"{manifest}: {key!r} must be a list of strings, got {type(value).__name__}")
    for item in value:
        if not isinstance(item, str):
            raise BadInput(f"{manifest}: {key!r} contains a non-string entry {item!r}")
    return tuple(value)


def lint(profile: Profile) -> list:
    """Check one profile. Returns `Violation`s and never guesses a kind.

    The kind is already declared by the time a `Profile` exists, so every rule below can be
    kind-specific without any inference. The last row states the population examined (`FR2-8.3`), so
    a scope that narrows cannot read as a pass.
    """
    out = []
    for name, text in profile.artifacts():
        for stub in sorted(set(_AUTHORING.findall(text))):
            out.append(Violation(
                path=str(profile.path / name), rule="authoring-placeholder",
                detail=(f"{name} still contains the authoring placeholder {stub!r}; it shipped where "
                        "real content belonged."),
                severity="violation"))
        for sha in sorted(set(_SHA.findall(text))):
            out.append(Violation(
                path=str(profile.path / name), rule="static-sha",
                detail=(f"{name} pins the static sha {sha!r}; a sha in a shared profile goes stale "
                        "silently. An all-digit CI run id is NOT a sha and is required to be pinned."),
                severity="violation"))

    out.extend(_baseline_disagreement(profile))

    # The whole worker-facing population, every time. Never "the first one we looked at" (M-35), and
    # never conditional on the profile declaring the clause itself — a profile that forgot the clause
    # is exactly the profile that also forgot to require it.
    if profile.kind in WORKER_FACING:
        if not any(all(part in text.lower() for part in AWAITING_CI_PARTS)
                   for _, text in profile.artifacts()):
            out.append(Violation(
                path=str(profile.path), rule="awaiting-ci-clause",
                detail=(f"a {profile.kind}-kind profile must instruct the worker to run "
                        f"`{AWAITING_CI_CLAUSE}`; none of {list(ARTIFACTS)} does. The phase is "
                        "structured state — a line of AWAITING-CI prose in HANDOFF.md is read by "
                        "nothing."),
                severity="violation"))

    for clause in profile.requires_clauses:
        if not any(clause in text for _, text in profile.artifacts()):
            out.append(Violation(
                path=str(profile.path), rule="required-clause",
                detail=f"the declared required clause {clause!r} appears in no rendered artifact",
                severity="violation"))

    for template in profile.invocation_templates:
        for command, flag, why in TARGET_FLAGS:
            if command in template and flag not in template:
                out.append(Violation(
                    path=str(profile.path / MANIFEST), rule="invocation-target-flag",
                    detail=(f"invocation template {template!r} runs `{command}` without {flag}: {why}. "
                            "A flag whose omission changes the TARGET is required, not defaulted."),
                    severity="violation"))

    out.append(Violation(
        path=str(profile.path), rule="population",
        detail=(f"examined kind={profile.kind}, artifacts {', '.join(ARTIFACTS)} "
                f"({len(profile.charter)}+{len(profile.seed)} chars), "
                f"{len(profile.requires_clauses)} declared clause(s), "
                f"{len(profile.invocation_templates)} invocation template(s), "
                f"{len(profile.placeholders)} declared placeholder(s)"),
        severity="info"))
    return out


def _baseline_disagreement(profile: Profile) -> list:
    """Two artifacts of one profile naming different baseline run ids (`OBS-63`).

    Only lines that mention a baseline are considered, and only all-digit run ids on them: a sha is a
    different finding with a different rule, and a profile that names a baseline in one artifact and
    nowhere else is not a disagreement — it is the authoring-placeholder case above.
    """
    sets = {}
    for name, text in profile.artifacts():
        found = set()
        for line in text.splitlines():
            if "baseline" in line.lower():
                found.update(_RUN_ID.findall(line))
        sets[name] = found
    charter, seed = sets["charter.md"], sets["seed.txt"]
    if charter and seed and charter != seed:
        return [Violation(
            path=str(profile.path), rule="baseline-disagreement",
            detail=(f"charter.md names baseline run id(s) {', '.join(sorted(charter))} but seed.txt "
                    f"names {', '.join(sorted(seed))}; one profile, two baselines."),
            severity="violation")]
    return []


def agrees_with_optype(profile: Profile, optype: str) -> bool:
    """Does this profile's declared kind agree with the opType it is being dispatched as?

    An unknown opType is refused rather than answered `False`, because `False` reads as "these
    disagree" and the truth is "the question was malformed".
    """
    if optype not in OPTYPES:
        raise BadInput(f"optype={optype!r} is outside {OPTYPES}")
    return optype in OPTYPES_OF_KIND[profile.kind]
