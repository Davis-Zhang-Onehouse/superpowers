# The chain manifest

The stack is the deliverable, so the stack needs a machine-readable record. Without one the current tip
lives in a prose table and gets **retyped** into the next dispatch, which is the single most consequential
untyped value in the whole routine: the tool checks that a worker's slot *arrives* at the sha you typed,
never that the sha was the right one.

`fleet` has no manifest verb yet (`SI-43` in `docs/superpowers/fleet-infra-backlog.md`). Until it does,
keep the file yourself, at the effort root, and treat it as state.

## What a position records

One row per position per repo. A position is one PR.

| Field | Why it is here |
|---|---|
| `ordinal` | position in the chain; the sort key |
| `repo` | which repository |
| `branch` | the ref name — **stable for the life of the position** |
| `pr` | the PR number, reused across restacks |
| `tip` | the full 40-char sha at that position |
| `parent` | the ordinal below it, or the effort base |
| `pins` | for each paired repo: the sha this position's build resolves to |
| `graded` | the sha that was graded, the verdict, and when |

Two fields carry the weight.

**`pins` is why this is a manifest and not a list of branches.** In a pinned multi-repo stack, each
position of the primary repo builds against a specific commit of each paired repo. When the chain is
restacked, those pins move with the positions — and a position whose pin still points into the
*pre-restack* history builds fine and tests the wrong native code. Recording the pin per position is what
makes that checkable.

**`graded` stores the sha it graded, not just a verdict.** Ancestry is derivable at any time and should be
re-derived rather than stored. A grade is not: CI runs age out, and six weeks later the only record that a
given sha was ever green is the one you wrote down. A verdict without its sha is not evidence.

## Shape

Tab-separated, one row per position per repo, sorted by ordinal. TSV rather than JSON because the readers
are `awk` one-liners in a runbook, and because a diff of it is legible in a commit.

```
ordinal  repo             branch                      pr    tip         parent  pins                      graded
07       gluten-internal  x3/13-a8-round-bround-pin   547   3f8e5336c7  06      velox=eb205d82c           GREEN@3f8e5336c7 2026-08-31
08       velox-internal   ansi-1.7/12-agg-on-10       188   eb205d82c   07      -                         -
```

## The checks it makes possible

Run these before every dispatch and after every restack. Each is one command, and each answers a question
that is otherwise answered from memory.

**Is the chain actually linear?** For every consecutive pair in a repo:

```bash
git merge-base --is-ancestor <parent tip> <child tip>
```

**Does the recorded tip still exist on the remote?** The manifest is a record, and records go stale:

```bash
git ls-remote origin 'refs/heads/<branch>'
```

**Does every pin resolve into the chained history?** For each position with pins, the pinned sha must be
an ancestor of the paired repo's tip at that position — not merely a valid commit somewhere. This is the
check that catches a restack that moved branches and forgot their pins.

**Did anything outside the grant move?** Snapshot `git ls-remote` before and after a restack and diff the
two. The set of changed refs must equal the set you were authorised to change — including the refs you
were *not* authorised to touch appearing unchanged, which is the half a "did my branches move?" check
misses.

## Keeping it true

The integration routine is the only writer of tips. The wave routine reads and does not write. When they
disagree with the remote, **the remote wins** and the manifest is corrected — it is a record of what you
did, not a declaration of what should be.

Re-derive rather than trust when the answer gates something irreversible: a dispatch base, a force-push, a
grade. The manifest saves you from retyping; it does not save you from checking.
