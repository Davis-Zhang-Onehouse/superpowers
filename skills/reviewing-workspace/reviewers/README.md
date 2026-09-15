# The hunt's code lens — PR code review

The code lens of a hunt (Stage 1 of `reviewing-workspace`) runs PR code review by **reusing** the
`superpowers:requesting-code-review` reviewer, one subagent per in-scope PR, at the frozen review
tip `T0`.

## Reuse (do not fork the template)

The lens dispatches the existing "Senior Code Reviewer" template at
`skills/requesting-code-review/code-reviewer.md` **verbatim**. Do NOT copy,
fork, re-word, or maintain a second reviewer prompt here. Fill its four
placeholders and dispatch it — nothing else changes.

- One reviewer subagent per in-scope PR.
- The template is read-only on the checkout (see below); the lens inherits that.

## PR selection (what is in-scope)

1. Read the `HANDOFF.md` **"PR / branch stack"** table
   (Repo | Branch | Tip githash | PR | CI | Contents).
2. **In-scope** = PRs whose branch was authored on **this instant**.
   Cross-check the table's **Branch** and **Contents** columns against this
   instant's own work and its session log.
3. **Skip** inherited base-instant PRs — branches carried forward from the
   fork parent that were already reviewed upstream. Record each as a finding
   through `fleet review --finding` with status `wont-fix` and an action
   naming why it was excluded — considered and deliberately declined, so it
   survives the render.

## The hunt reviews the whole authored delta, with the family named

Every hunt's code lens reviews `[BASE_SHA]` = the PR's merge-base with its target branch through
`[HEAD_SHA]` = the frozen review tip `T0`. Never "since the last round": a defect that predates the
delta cannot be found by a delta, and a stack of delta reviews reads like coverage while leaving the
original surface unexamined — one bypass survived four such rounds.

Scope alone did not find it either; framing did. Append to `[DESCRIPTION]`:

> Defect family for this effort: <the charter's traps, verbatim> ; <the classes in this instant's and
> its parent's ISSUES.md, one line each>. Assume the next member of this family is present in the
> code under review and look for it.

The previous round's `heads` in `.fleet/review.json` are read only by the closure reviewer, as
`[T_PREV]`.

## Placeholder mapping into `code-reviewer.md`

| Placeholder | Value |
|---|---|
| `[DESCRIPTION]` | HANDOFF **"Where we are"** one-paragraph + the PR's **Contents** cell + the **defect family** paragraph above. |
| `[PLAN_OR_REQUIREMENTS]` | The **CHARTER** acceptance criteria (what the work must satisfy). |
| `[BASE_SHA]` | The PR's merge-base with its target branch — every hunt, not only the first. |
| `[HEAD_SHA]` | `T0`, the frozen review tip (a sha, never a branch name). |

## Read-only

`code-reviewer.md` already forbids mutating the working tree, index, HEAD, or
branch state, and directs the reviewer to use `git show` / `git diff` /
`git log` (or a throwaway `git worktree`) for inspection. The lens inherits
this — reviewers never move HEAD on the checkout. Findings are received by the
orchestrator through `superpowers:receiving-workspace-review`; nothing a
reviewer reports is applied in line.

## No PRs authored here

If no PRs were authored on this instant, the code lens is recorded as **N/A** in the round and the
verdict rests on the format and alignment lenses.
