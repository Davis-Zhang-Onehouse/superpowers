# P-worker report — 00000000-09112000-inflight-append-prealworker

## What `fleet brief` told me

Ran `fleet brief --instant "$INSTANT"` first, per the skill. All six rows came back with real content, not
placeholders:

- `origin`: dispatched by the pcoord instant at 2026-09-11T20:00:36Z for milestone p1.
- `milestone`: p1 is titled "prove the worker contract end to end", owner is me, stored status is
  `blocked` — but the row explicitly told me readiness is *derived* from whether dependencies landed, so a
  stale `blocked` label does not actually block me. That's a useful and non-obvious distinction; without
  this row I would have read "status=blocked" and either stalled or asked the coordinator, when in fact
  nothing was blocking me.
- `phase`: none declared, not parked.
- `review`: correctly reported `REFUSE: UNDECIDABLE` since no round was on file yet — matches the skill's
  description that a first round reads UNDECIDABLE, not NOT-READY.
- `destination`: told me a plain `fleet propose` with no `--to` would reach the pcoord instant, resolved
  from `.fleet/origin.json`. Useful, and confirms the skill's claim that this row exists specifically to
  prevent a report silently staying LOCAL. In my case it was never going to be LOCAL (origin.json was
  populated), so this row didn't catch anything for me, but I can see exactly how it would for a
  misconfigured dispatch.
- `outstanding`: this was the most useful row of the six. It listed, as one item, *every* blocking
  condition in plain language: no pending proposal, review gate not yet passed, folder still `-inflight-`,
  and — critically — printed the exact `fleet base-check --id prealworker-09112000` command with my real
  todo id already filled in. I did not have to go hunt CHARTER.md for the todo id; brief handed it to me
  pre-filled.

**Verdict on `destination`:** useful, but in this run it was inert — origin.json already had a real
coordinator recorded, so there was nothing for the row to catch. Its value is prophylactic, not something I
personally exercised.

## What `base-check` said, before and after

**Before repositioning** (`fleet base-check --id prealworker-09112000`), exit code 1:

```
lineage     prealworker-09112000:alpha  violation  40202439853b is present but NOT checked out (HEAD 7a087182ba25).
population  prealworker-09112000        info       expected alpha=40202439853b2aff1cad653aacb0f0f4f43bf233 ... 1 repo(s) blocking a claim of done
```

So the slot's alpha repo already *had* the base commit fetched (from the golden image build), just not
checked out — HEAD was still on `goldenbranch` at `7a087182ba25`. This matches the CHARTER's warning almost
exactly: the slot was "still at the golden" and would have built and tested green with no signal that
anything was wrong.

I then repositioned exactly as CHARTER.md / the seed's "POSITION YOUR WORKSPACE" section instructed:

```
git -C alpha fetch --all
git -C alpha checkout --detach 40202439853b2aff1cad653aacb0f0f4f43bf233
```

**After repositioning**, `fleet base-check --id prealworker-09112000` returned exit code 0:

```
lineage     prealworker-09112000:alpha  info  at the base, 40202439853b
population  prealworker-09112000        info  ... 0 repo(s) blocking a claim of done
```

Clean, exactly as the skill described the `at-base` verdict.

## Would `propose --status done` have been refused before repositioning?

**Yes — I did not guess or infer this, I directly tested it.** Before touching the alpha repo, I ran:

```
fleet propose --instant "$INSTANT" --milestone p1 --status done --evidence evidence/P-worker-report.md --dry-run
```

It returned **exit code 4** with:

> Refused: propose --status done refused: this instant was dispatched to build on
> alpha=40202439853b2aff1cad653aacb0f0f4f43bf233 (lineage-mode=code) and its workspace is not there — ...
> clears when: the workspace is repositioned onto the recorded lineage base ...
> clears who: the dispatched instant

This is a direct, mechanical observation of the actual gate (via `--dry-run`, which the skill states writes
nothing but evaluates every gate), not an inference from documentation. Notably, the evidence file named in
that dry-run command (`evidence/P-worker-report.md`) did not exist on disk yet at the time I ran it, and the
refusal was still about lineage, not about the missing evidence file — so the lineage gate is checked before
(or independently of) evidence-file existence for `--dry-run`, which is worth knowing if you're trying to
diagnose a refusal message: the FIRST reason given may not be the only thing wrong.

## Things that were wrong, missing, ambiguous, or unfollowable

1. **CHARTER.md's "Scope" and "Acceptance criteria" sections are empty** — just the HTML comment
   placeholders (`<!-- The coordinator replaces this per milestone... -->` and
   `<!-- One per line, each naming the proof that would satisfy it. -->`), with no actual content filled
   in. The skill and CHARTER both say "CHARTER.md is authoritative for scope," but for this dispatch, the
   *seed's* Section "YOUR TASK" was the only place real scope/AC lived. If a worker took "CHARTER is
   authoritative" literally and looked there first for the actual task, they'd find nothing and have to
   fall back to the seed anyway. Not fatal — the seed's task section was clear and complete — but the
   authoritative doc being blank while the "generic" doc carries the real instructions inverts what the
   skill tells you to expect.

2. **The seed's step 4b duplicates step 4** in numbering (both are labeled "4" and "4b" but step 4 itself
   already says "Write a report... answering [3 bullet points]" and then 4b adds a 4th question as an
   afterthought). Trivial, but it reads as if 4b was bolted on after the fact — which, per CHARTER.md line
   25's own parenthetical, it apparently was (referencing "a real worker in §P flagged exactly that" about
   a different ambiguity in this same file). Worth normalizing to a flat numbered list next time this seed
   is edited.

3. **The seed does not tell the worker whether to `--dry-run` first or run the real refused command.** I
   inferred (correctly, I believe) that a `--dry-run` was the right way to test "would this have been
   refused" without producing a spurious real proposal in the coordinator's inbox before repositioning. But
   the task's step 4b just asks "would it have been refused... did you try it?" without guidance on *how*
   to try it safely. A worker who ran the real (non-dry-run) command to find out would have sent the
   coordinator a doomed proposal it never needed to see. `--dry-run` is documented in `using-fleet`, but
   the seed itself doesn't point a worker at it for this specific check — I only used it because I'd just
   loaded that skill.

4. **Everything else matched the skill exactly.** `brief`'s command, `base-check`'s `--id` (not
   `--instant`) flag, the `present`/`absent`/`at-base`/`descendant` verdict vocabulary, the exit codes, and
   the review/propose/complete sequence all worked exactly as documented. No surprises, no mismatches
   between what the skill said a command would print and what it actually printed.

## Summary

The contract held end-to-end. The one genuine gap is #1 (empty CHARTER scope/AC sections contradicting "the
charter is authoritative"), and the one practical rough edge for future workers is #3 (no explicit guidance
to use `--dry-run` when testing whether a done-claim would be refused, before you've actually repositioned).
Neither blocked me — I worked around both by reading the seed carefully and by already knowing about
`--dry-run` from `using-fleet`.
