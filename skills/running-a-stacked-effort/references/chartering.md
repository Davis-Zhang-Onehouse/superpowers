# Chartering an effort

The charter is written once and is durable. Only the self-review column moves.

## The five blocks

**1. Identity.** Instant path, slot, todo id, base, role, effort root, and which registry is yours. One
line each. A resuming session reads this before anything else.

**2. Setup to begin with.** What the effort inherits, stated as measured facts rather than references.
Every branch, sha and PR number verified on the remote at the moment of writing, with the date. An
inherited claim you did not check is an assumption wearing a fact's clothes.

If the effort inherits read-only context from earlier work, name those trees and mark them read-only
explicitly. Someone will otherwise create an instant inside one.

**3. The first three raw prompts, verbatim.** See the skill body. Struck lines stay, with their reason.

**4. The goal, and what done means.**

> **Done means all N, and I do not get to soften any of them:**
> 1. …
> 2. …

Each clause is a thing that is either true or false about the finished state. If you cannot say what would
make a clause false, it is a direction, not a clause.

State the negative space too — **what you never do**: merge, push to a protected branch, delete outward
state, write another instant's registry. A coordinator that has written down what it will not do can be
told "proceed autonomously" without that becoming authority over anything irreversible.

**5. Acceptance criteria.** Three columns.

| # | NL statement | Executable proof | Self-review |
|---|---|---|---|
| AC-1 | The split is *designed*, not improvised: every hunk is attributed to exactly one position, or explicitly dropped with a reason. | A coverage map reconciling the diff against the proposed positions, with **zero** unattributed files, plus a negative control proving the checker can fail. | ✅ proven — residual 0 over 64 paths / 217 tuples |
| AC-2 | No coverage is lost in the split. | The union of the source's suites vs the new stack's, every difference explained. | 🔵 in progress |

Symbols: `⬜` not started · `🔵` in progress · `✅` proven · `🟡` proven with a stated bound.

## Three rules for the proof column

**Name the artifact, not the activity.** "Tests pass" is an activity. "This suite, this count, zero skips,
at this sha, captured in `evidence/`" is an artifact.

**A checker needs a negative control.** A reconciliation that reports zero unattributed files is worth
nothing until you have shown it can report a non-zero one. The most expensive failure available to a
coordinator is a check that cannot fail, because it reads exactly like success.

**Where a criterion is only half met, say which half.** Do not round up, and do not collapse two clauses
into one verdict. A criterion recorded as "half satisfied, and the open half is *this*" is usable; one
recorded as "in progress" is not.

## Revising an AC

Acceptance criteria do change — an operator ruling, a discovered constraint. When one does:

- Rewrite it in place, marked with the date and the decision that moved it.
- Keep the old text visible if anyone might have acted on it.
- Say **why**, in the AC. An AC whose text changed with no recorded reason is indistinguishable from one
  that was softened because it was hard.
