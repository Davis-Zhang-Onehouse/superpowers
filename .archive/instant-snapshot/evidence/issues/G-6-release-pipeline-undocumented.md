# G-6 — the release pipeline has eight verbs, four promoted releases, and no operator documentation

**Origin:** found 2026-08-03 while answering the operator's question *"do we have claude md or read me or
claude skill anywhere?"*
**State:** **CLOSED** `d07b4a2`, 2026-08-03.

---

## 1. The observable

```
$ for v in release-cut release-verify release-promote release-deploy \
           release-rollback release-status release-list release-history; do
    printf '%-18s %s\n' "$v" "$(grep -c "$v" skills/using-fleet/SKILL.md)"; done
release-cut        0
release-verify     0
release-promote    0
release-deploy     0
release-rollback   0
release-status     0
release-list       0
release-history    0

$ grep -ci 'release-cut\|release-verify' fleet/CLAUDE.md CLAUDE.md
0
0
```

`skills/using-fleet/SKILL.md` is the document that carries the verb surface — it has a "Read-only" table
and a "Mutating" table listing every other verb. **All eight release verbs are absent from both.**
`fleet/CLAUDE.md` and the root `CLAUDE.md` do not mention the pipeline either.

## 2. What DOES exist, and why it is not enough
- `docs/superpowers/specs/2026-08-02-fleet-release-pipeline-design.md` — the design spec
- `docs/superpowers/plans/2026-08-02-fleet-release-pipeline.md` — the implementation plan
- `fleet/CHANGELOG.md` — per-release sections, written by `release-cut`

The first two are **design artifacts**: they record what was decided and why it was built, not how to use
it. Nobody looking for "how do I cut a release" finds a spec. The changelog is output, not instruction.

## 3. Why this is a real defect and not tidiness
This is `SI-19`'s exact shape, which the package already has a name for: **a correct, tested, dead public
surface.** `SI-19` was `fleet clone`; `SI-26` records the same thing happening to `Roadmap.add`, which
*"had always existed, been locked and been tested; it had **no verb**, so from a command line the
replacement was unreachable"*. The failure mode is a capability nobody can find.

Here it is one step worse than unreachable: it IS reachable, four releases have been promoted through it,
and the next person to touch it has to read the source or a spec to learn that `release-verify` needs a
repo, that `--dry-run` exists on every mutating verb, or that a CANDIDATE is not deployable.

## 4. What has to be written, and the facts it must carry
Things a user cannot guess and that were learned expensively:

1. **The verb set and the lifecycle:** cut → verify → promote; deploy/rollback are separate and act on
   `current`.
2. **`release-verify` needs a repository** — it runs the IT suite from a `git worktree` at the tag,
   because the suite cannot judge an export (`II-7`). A release records `source_repo` at cut; older ones
   need `--repo`. A release that records neither is REFUSED, not verified against the export.
3. **A CANDIDATE cannot be deployed** and a promote without GREEN evidence is refused (exit 4).
4. **The gate's verdict comes from FAIL rows in the run's own registers**, never from `run-all.sh`'s exit
   code — the release that shipped GREEN over 7 FAIL rows is `SI-38` and it is why.
5. **Retention: 10 releases**, oldest pruned at the next cut, never the deployed one. Recoverable from
   the tag.
6. **What a RED means and how to triage it** — read `it-RESULTS-closeout-*.tsv`, not the merged
   `it-RESULTS.tsv`, which keeps rows from runs that did not happen this time (`II-6`).
7. **Exit codes**, which differ from the general set for these verbs only where documented.

## 5. Where it should go — decide before writing
- **`skills/using-fleet/SKILL.md`** already owns the verb tables and the exit codes, and a reader looking
  for a verb goes there. Strongest candidate.
- A separate `releasing-fleet` skill would be discoverable by name but splits the verb surface across two
  documents, which is how two copies of a list start.
- `fleet/CLAUDE.md` is for someone working ON the package rather than USING it; the pipeline's internals
  (the worktree, `tree_sha`, the registries) belong there if anywhere.

**Recommendation:** the verb tables and lifecycle in `using-fleet`; the internals note in
`fleet/CLAUDE.md`; no new skill.

## 6. How to know it is closed
- All eight verbs appear in `using-fleet`'s tables with a one-line "what it answers / what it does".
- The lifecycle and the seven facts in §4 are written where a user will hit them.
- A reader who has never seen the pipeline can cut, verify and promote from the docs alone, without
  opening the source or the spec. That is the acceptance test — try it on somebody.

## 7. Files
- `skills/using-fleet/SKILL.md` — the verb tables, the exit-code section
- `fleet/CLAUDE.md` — package-internals doc
- `docs/superpowers/specs/2026-08-02-fleet-release-pipeline-design.md` — the source of the facts
- `fleet/src/fleet/cli.py` — the eight `_verb(...)` declarations, which are the authority on flags


---

## 8. CLOSED — `d07b4a2`, 2026-08-03

**The test is the fix**, and it found **nine** verbs undocumented, not eight: `clone` as well, which is
the verb `SI-19` created to close `SI-19`. Derived from `cli.VERBS`, so a verb added later cannot escape
the way these did. The reverse direction is asserted too — the skill may not name a verb the parser does
not declare, which is `FI-11` defect 1 exactly.

Then the documentation:
- All nine verbs in `using-fleet`'s read-only and mutating tables.
- A **"Releasing fleet"** section: the four-state lifecycle and the seven facts from §4 above, each one
  something a user cannot guess.
- Internals in `fleet/CLAUDE.md`, where somebody CHANGING the pipeline will be rather than using it —
  why `release.py` holds no git, what `tree_sha` excludes and why, why `Verify`'s runner is required,
  and that `prune`'s delete site is declared in both registries.

No new skill: the verb surface stays in one document, because two copies of a list is how `II-3` started.

1179 hermetic tests OK.
