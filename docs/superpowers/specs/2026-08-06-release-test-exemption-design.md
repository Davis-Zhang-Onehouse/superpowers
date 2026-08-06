# Release test exemption — design

Date: 2026-08-06
Status: approved

## Problem

`fleet release-verify` runs both suites — ~24 minutes — against every release. But a release is a
`git archive` of the **whole repository**, not just `fleet/`: it ships `skills/`, `commands/`, `hooks/`,
`docs/`, and the `.claude-plugin/` manifest, and the deployed release *is* the plugin marketplace source
that Claude Code loads skills from (`extraKnownMarketplaces.superpowers-dev.source.path` →
`fleet-releases/current`).

So a release that only edits documentation or a skill pays the full 24-minute gate to prove nothing: the
suites test `fleet/`, and `fleet/` did not change. Today the only way around it is
`release-deploy --force`, which is a manual, per-release judgement call that also discards the gate
entirely and records the release as UNVERIFIED. That is the wrong tool: it is an override, not a decision,
and using it routinely is how `0.3.2` came to be deployed as an unverified CANDIDATE.

We want the skip to be **automatic, narrow, and auditable** — computed from the diff, never asserted by an
operator.

## The trap this design exists to avoid

"Doesn't touch fleet code" is not the same as "outside `fleet/`". Two paths outside `fleet/` are covered
by the suites:

- `fleet/tests/test_contracts.py` — `TestEveryVerbIsDocumentedWhereUsersLook` asserts, **in both
  directions**, that `skills/using-fleet/SKILL.md` names exactly the verbs `cli.VERBS` declares. Renaming a
  verb mention there is a red build.
- `fleet/it/run-P.sh:76` — copies `skills/using-fleet/profiles/worker` into a live IT fixture.

A rule of "only `fleet/**` requires tests" would therefore skip the gate on precisely the skills edit most
likely to break it, and ship the break to `current`, where every session on the box loads it.

## Decision: fail-safe classification

Exempt **only** when every changed path matches a declared inert set. Anything unrecognised — a new
top-level directory, a new script, an unforeseen file — requires verification.

```
INERT (exempt-eligible)                    REQUIRES VERIFY
  docs/**                                    fleet/**
  assets/**                                  skills/using-fleet/**
  skills/**  EXCEPT skills/using-fleet/**    scripts/**, hooks/**, bin/**, tests/**
  README.md, LICENSE, CODE_OF_CONDUCT.md,    package.json, gemini-extension.json
  RELEASE-NOTES.md, AGENTS.md, GEMINI.md,    .claude-plugin/**, patches/**, _staging/**
  CLAUDE.md                                  everything not matched on the left
```

Rejected alternative — a denylist ("verify only if `fleet/**` or `skills/using-fleet/**` changed") — is
fail-open: a suite that later reads a new path, or any new top-level directory, becomes silently exempt.
The failure is invisible and ships. The allowlist's failure mode is a needless 24-minute run, which is
merely annoying.

## Decision: anchor is the last GREEN release

The diff is computed `git diff --name-only <anchor-tag>..<this-tag>`, where the anchor is the most recent
release, older than this one, whose recorded verdict is **all-GREEN**. An `EXEMPT` release is never an
anchor.

This makes chains safe. Three docs-only releases in a row each diff against the last release that actually
passed, so an exempt release's `fleet/` tree is provably byte-identical to verified code. Anchoring to the
immediate predecessor instead would let exemptions chain off an unverified CANDIDATE — the state `0.3.2`
was in.

No anchor (no GREEN release exists, or its tag is missing from the checkout) → not exempt; run the suites.
Refused rather than assumed.

## Decision: a distinct verdict, never `GREEN`

`VERDICT.tsv` records `EXEMPT`, not `GREEN`. Dressing a skipped run as a pass would reproduce `SI-38` — a
verdict whose evidence does not support it — in a new place. A reader must always be able to distinguish
"the suites ran and passed" from "the suites were not required".

```
suite     verdict  evidence                    note
hermetic  EXEMPT   evidence/EXEMPTION.tsv      not required: no path requiring verification changed
it        EXEMPT   evidence/EXEMPTION.tsv      not required: no path requiring verification changed
roster    exempt   -                           the set of IT runners this verdict covers
```

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `fleet/src/fleet/release_scope.py` (new leaf) | `classify(paths) -> Scope(inert, requiring)`. Pure; no git, no I/O | nothing |
| `Repo.changed_paths(a, b)` in `release_git.py` | `git diff --name-only a..b` through the injected git seam | the git seam |
| `Releases.last_green(version)` in `release.py` | anchor selection from recorded verdicts | `read_verdict` |
| `release-verify` short-circuit | computes exemption before spawning anything | the three above |
| `release-promote` | accepts `GREEN` or `EXEMPT`; refuses `EXEMPT` on a minor/major bump | `read_verdict` |

`release_scope.py` is a leaf so the classification rule can be tested exhaustively without a repository,
a release area, or a subprocess — the package's existing "leaves import nothing in the package" structural
test applies to it.

## Data flow

```
release-verify --version X
  |
  +- anchor = Releases.last_green(X)         -- none? -> run both suites (today's path)
  +- --full passed?                          -- yes?  -> run both suites (never exempt)
  +- paths = Repo.changed_paths(anchor.tag, X.tag)
  +- scope = release_scope.classify(paths)
  |
  +- scope.requiring is empty?
       yes -> write EXEMPTION.tsv + VERDICT.tsv(EXEMPT); emit; exit 0   (~2s)
       no  -> run hermetic + IT exactly as today                        (~24m)
```

## Evidence

`.release/evidence/EXEMPTION.tsv` — written only on the exempt path:

```
key            value
anchor         0.3.3
anchor_tag     fleet/v0.3.3
compared       fleet/v0.3.3..fleet/v0.3.4
path           docs/foo.md            inert
path           skills/brainstorming/SKILL.md   inert
```

Every changed path is listed with its classification, so the decision is re-checkable by hand. The gate's
principle — "a promotion always cites a measurement someone can go and look at" — is preserved; the
measurement is the diff instead of a test run.

## Error handling

| Condition | Behaviour |
|---|---|
| No GREEN release exists | not exempt; run the suites |
| Anchor tag absent from the checkout | Refused (exit 4), naming the tag — never assume |
| Any path unmatched by the inert set | not exempt; run the suites |
| `--full` requested | never exempt |
| Minor/major bump with an EXEMPT verdict | `release-promote` refuses (exit 4) |
| No repository available (`source_repo` unset, no `--repo`) | existing refusal is unchanged |

## Testing

- **`release_scope` unit tests** — every inert pattern; the `skills/using-fleet/**` carve-out in both
  spellings; unknown top-level directory → requiring; empty diff; a mixed set.
- **Regression guard for the carve-out** — a test asserting `skills/using-fleet/SKILL.md` and
  `skills/using-fleet/profiles/worker` classify as *requiring*, citing the two suite call-sites, so the
  carve-out cannot be deleted without a failure that explains itself.
- **Anchor selection** — skips EXEMPT releases; picks the newest GREEN; returns None when there is none.
- **CLI** — exempt path writes both files and exits 0 without spawning; non-exempt path is byte-identical
  to today's behaviour; promote accepts EXEMPT; promote refuses EXEMPT on a minor bump.

## Out of scope

`RI-9`/`RI-11` (the evidence directory is keyed by version, not attempt, so a re-verify overwrites the
previous attempt and a GREEN release can ship a stale failure manifest), `RI-10` (`pgrep -x claude` counts
fork-before-exec children), and `RI-12` (the `.claude-plugin` / `package.json` version line does not move
with a fleet release). Tracked in their own instant.

## Outcome (2026-08-06)

Shipped in `0.3.5`. Building it surfaced a second, larger problem: `0.3.4` could not pass its gate at all,
because three `ISOLATION-*-claude-count` sections compared a bare `pgrep -x claude` count and so failed on
other operators' fork-before-exec transients. That is fixed in the same release
(`it_classify_claude_delta`), and the exemption is what stops a docs-only change from having to survive a
25-minute gate on a shared box in the first place.
