# Stage 3 Reviewers — PR Code Review

Stage 3 of `reviewing-workspace` runs PR code review by **reusing** the
`superpowers:requesting-code-review` reviewer, one subagent per in-scope PR,
diffing only what changed since the last review round.

## Reuse (do not fork the template)

Stage 3 dispatches the existing "Senior Code Reviewer" template at
`skills/requesting-code-review/code-reviewer.md` **verbatim**. Do NOT copy,
fork, re-word, or maintain a second reviewer prompt here. Fill its four
placeholders and dispatch it — nothing else changes.

- One reviewer subagent per in-scope PR.
- The template is read-only on the checkout (see below); Stage 3 inherits that.

## PR selection (what is in-scope)

1. Read the `HANDOFF.md` **"PR / branch stack"** table
   (Repo | Branch | Tip githash | PR | CI | Contents).
2. **In-scope** = PRs whose branch was authored on **this instant**.
   Cross-check the table's **Branch** and **Contents** columns against this
   instant's own work and its session log.
3. **Skip** inherited base-instant PRs — branches carried forward from the
   fork parent that were already reviewed upstream. List these in
   `REVIEW.md`'s Stage 3 section under **"Skipped (inherited …)"** so it is
   explicit they were considered and deliberately excluded.

## Incremental / delta review

Reviews run repeatedly (mid-flight and pre-complete), so each round reviews
only the commits added since the previous round.

For each in-scope PR:

- Read the prior round's **"Head sha (this round)"** from the Stage-3
  "Reviewed" table in `REVIEW.md` — this is the **prev-reviewed head**.
- **`[BASE_SHA]`** = the prev-reviewed head (so only new commits are reviewed).
  - **First-ever review** of a PR: use the PR's **merge-base with its target
    branch** as `[BASE_SHA]`.
- **`[HEAD_SHA]`** = the PR's current tip (the table's **Tip githash**).
- After the review returns, the orchestrator records the new tip as
  **"Head sha (this round)"** in `REVIEW.md`, so the next round diffs from here.

## Placeholder mapping into `code-reviewer.md`

| Placeholder | Value |
|---|---|
| `[DESCRIPTION]` | HANDOFF **"Where we are"** one-paragraph + the PR's **Contents** cell. |
| `[PLAN_OR_REQUIREMENTS]` | The **CHARTER** acceptance criteria (what the work must satisfy). |
| `[BASE_SHA]` | Per the delta rule above (prev-reviewed head, or merge-base on first review). |
| `[HEAD_SHA]` | The PR's current tip. |

## Read-only

`code-reviewer.md` already forbids mutating the working tree, index, HEAD, or
branch state, and directs the reviewer to use `git show` / `git diff` /
`git log` (or a throwaway `git worktree`) for inspection. Stage 3 inherits
this — reviewers never move HEAD on the checkout.

## No PRs authored here

If no PRs were authored on this instant, Stage 3 is recorded as **N/A** in
`REVIEW.md` and the round's verdict rests on Stages 1–2.
