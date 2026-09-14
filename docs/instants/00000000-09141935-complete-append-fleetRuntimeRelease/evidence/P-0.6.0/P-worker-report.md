# P-worker-report — prealworker, milestone p1

Updated: 2026-09-14 | Worker: Claude Code, model claude-opus-5[1m] | Todo id: `prealworker-09142202`

Every claim below cites a captured output under `evidence/P/` (relative to this instant). Each capture ends
with the command's real exit code, written by `echo "exit=$?"` directly after the command — no pipes.

## 1. What `fleet brief` told me

Capture: `evidence/P/01-brief-before.txt`. Six rows plus the population row, exit 0:

- **origin** — dispatched by `…-inflight-append-pcoord` at 2026-09-14T22:02:18Z for milestone `p1`.
- **milestone** — `p1` "prove the worker contract end to end", owner = me, *stored* status `blocked`, but
  it says explicitly that readiness is derived from deps and I am READY. That's clearer than the version
  earlier §P runs complained about: it tells me which value is a stored label and which is derived.
- **phase** — none declared, not parked.
- **review** — the gate would REFUSE as UNDECIDABLE (no round recorded). It names the exact `fleet review`
  shape that clears it.
- **destination** — a `propose` with no `--to` goes to `…-inflight-append-pcoord`, read from
  `.fleet/origin.json`.
- **outstanding** — no proposal pending yet, review gate closed, folder still `-inflight-`, a lineage base
  is recorded (`alpha=40105d3…`), and it prints `fleet base-check --id prealworker-09142202` with my id
  already filled in.

**Was `destination` useful?** Yes, but only as a check. It told me before I wrote anything that the
report would reach the coordinator and not stay in my own inbox as a LOCAL proposal. I'd have trusted the
seed's claim anyway, and nothing here was going to go wrong, so this run doesn't show the row preventing a
failure. What made it worth having is that `propose --dry-run` later printed the same destination and the
same provenance (`destination-chosen  read from .fleet/origin.json`), so the two agree
(`evidence/P/06-propose-done-dryrun-after.txt`). The `outstanding` row turned out to be the most useful of
the six, because it gave me my todo id and the next command in one place.

## 2. `base-check` before and after repositioning

**Before** (`evidence/P/02-base-check-before.txt`, exit **1**):

```
lineage  prealworker-09142202:alpha  violation  40105d3bbf22 is present but NOT checked out (HEAD 45833cf6d91f).
         Legitimate for an ANALYSIS milestone reading via refs … but this dispatch is lineage-mode=code
         remedy: git -C /home/…/P/out/slot/alpha checkout --detach 40105d3bbf22d02ca7f33b9a8fa160a977fb89a8
population … 1 repo(s) blocking a claim of done
```

The verdict was `present` (the skill's table): the base commit was already in the clone, but HEAD was the
golden `45833cf G: the golden prebuild`. The base `40105d3 L: the sibling's tip` is on a diverged sibling
branch, and both come off `f7477fd A: common ancestor` (`evidence/P/04-reposition.txt`). So the golden is
not an ancestor of my base, and building on it would have been wrong in a way no test here would catch.

**Repositioning** (`evidence/P/04-reposition.txt`): I ran the seed's two lines exactly as printed:
`git -C alpha fetch --all` (exit 0, no output, so no remotes had anything to fetch) and
`git -C alpha checkout --detach 40105d3…` (exit 0, `HEAD is now at 40105d3 L: the sibling's tip`). The
working tree is clean.

**After** (`evidence/P/05-base-check-after.txt`, exit **0**):

```
lineage     prealworker-09142202:alpha  info  at the base, 40105d3bbf22
population  … 0 repo(s) blocking a claim of done
```

## 3. Would `propose --status done` have been refused had I not repositioned?

**Yes, and I tested it rather than taking the seed's or skill's word for it.** Before repositioning I ran
`fleet propose --instant "$INSTANT" --milestone p1 --status done --evidence evidence/INDEX.md --dry-run`
(`evidence/P/03-propose-done-dryrun-before.txt`). It exited **4** with
`Refused: propose --status done refused: this instant was dispatched to build on alpha=40105d3… and its
workspace is not there — 40105d3bbf22 is present but NOT checked out (HEAD 45833cf6d91f)…`, plus a
`clears when` / `clears who` pair. I also listed the coordinator's `.fleet/` directory before and after.
It held only `roadmap.json` both times, so the dry-run wrote nothing.

After repositioning, the same dry-run exited **0**
(`evidence/P/06-propose-done-dryrun-after.txt`). Caveat: I proved the refusal with `--dry-run`, not with
a real write. `--help` says `--dry-run` "evaluate[s] every gate", and I'm relying on that. The seed, the
CHARTER's Positioning section and the skill (§ "Positioning your workspace", exit 4) all said the same
thing in advance.

## 4. What was wrong, missing, ambiguous, or not doable as written

Most-actionable first. I'm not going to pad this list: the core loop (brief → base-check → reposition →
base-check) worked exactly as written, first time, with no guessing.

1. **CHARTER's "When you are waiting on CI" section gives a command that gets refused, and doesn't
   mention why.** It says: "The moment your work is pushed and you are waiting on a CI run, declare it:
   `fleet declare --instant 00000000-… --phase awaiting-ci`". The skill says the claim now REFUSES unless a
   watcher is armed first. I ran the CHARTER's exact line with `--dry-run`
   (`evidence/P/09-probes.txt`) and it exited **4** ("nothing is armed to wake dt-prealworker…").
   The skill is authoritative for the mechanism, but the CHARTER is what I'm told is authoritative for my
   scope, and it teaches the pre-gate recipe. A worker reading only the CHARTER will hit that refusal.
   The refusal itself is good: it names the Monitor/background-shell remedy and `--watcher`. The template
   should say "arm a watcher first" or point to the skill.
   - Related nit: that CHARTER line uses the bare instant *name*, while the seed and the skill both insist on
     `"$INSTANT"`. The bare name did resolve (via `$FLEET_INSTANTS`), so it isn't broken, but it's a third
     spelling, and it stops matching the folder once `complete` renames it.

2. **`complete` refuses on the review gate with exit 2, but `--help` says 2 means "bad input" and 4 means
   "refused by an admission rule".** Before recording a review round I ran `fleet complete --instant
   "$INSTANT" --dry-run` (`evidence/P/07-complete-dryrun-before-review.txt`). The input was valid and the
   refusal was the UNDECIDABLE review gate, yet the exit code was **2**. The base-check refusal on `propose`
   was 4. A script that treats 2 as "I typed it wrong" will misread this. Either the code or the exit-code
   table is wrong. (I only saw this on `--dry-run`; I didn't try a real `complete` before the review.)

3. **`propose` accepts an evidence path that doesn't exist.** `fleet propose … --status done --evidence
   evidence/does-not-exist.md --dry-run` exited **0** and listed the path as evidence
   (`evidence/P/09-probes.txt`). The skill says "Evidence is mandatory… a proposal with no evidence is a
   claim rather than a report". But only *emptiness* is refused, not a dangling pointer, so a typo'd
   evidence path gets through as a report. I can't tell whether the real (non-dry-run) write checks
   existence; the dry-run, which claims to evaluate every gate, didn't.

4. **The CHARTER's Scope and Acceptance criteria are empty template comments.** The skill and the seed both
   say "Your CHARTER.md is authoritative for your scope". Here the scope was entirely in the seed's
   `=== YOUR TASK ===` block, and the CHARTER still reads `<!-- The coordinator replaces this per
   milestone. -->`. Nothing actually conflicted, so I followed the seed. But a worker told "the charter wins
   where they differ" gets no guidance when the charter is simply blank. The coordinator/dispatch should
   either fill it or say "scope is in the seed".

5. **Seed vs. launcher on how to invoke fleet.** The launcher header says to use `"$FLEET_BIN"` for every
   fleet command because PATH may put an older fleet first. The seed body, the CHARTER and the skill all
   write bare `fleet …`. I used `$FLEET_BIN` throughout, so it didn't bite. But the instruction lives in only
   one of four places, and every copy-paste block contradicts it.

6. **The seed's reposition lines are cwd-relative (`git -C alpha …`).** They're correct because a
   dispatched worker starts in the slot, and the skill says so. But `base-check`'s own remedy prints the
   absolute `git -C /home/…/slot/alpha …`, which is better. A worker that has `cd`'d into `$INSTANT` first
   (a natural thing to do after `brief`) would get `fatal: cannot change to 'alpha'`. The seed could print
   the absolute form, like base-check does.

7. **Skill nits.**
   - In § "Your first two commands", step 2 states twice, in back-to-back paragraphs, that the todo id is on
     CHARTER's `Todo id:` line and that `brief` prints the command with the id filled in.
   - The heading "Finishing is five steps, and the last one is not the rename" is followed by four bullets.
     I couldn't work out which five steps it means.
   - "Empty the slot of scratch": this slot came with a pre-existing, empty `.m2/` that I didn't create.
     The skill doesn't say whether inherited scratch is mine to delete. I left it alone.

8. **`review --dry-run` prints a `violation` row on valid input.** Its `gate` row reads
   `review-undecidable  violation` while the command exits 0 (`evidence/P/08-review-dryrun.txt`). The
   `round` row and the skill both explain this ("reflects the ledger WITHOUT this round"), so I wasn't
   misled. Still, a `violation` severity on the success path of a dry-run is a trap for anyone grepping
   porcelain for `violation`.

## What I did not do

- No commits, pushes, harvest, close, or reap. I touched no other instant, and didn't write to the
  coordinator except through `propose`.
- No native rebuild: the slot has no native artifacts, and the charter says nothing about rebuilding.
- No real (non-dry-run) `propose --status done` from the wrong base. That refusal is proven by dry-run only
  (see §3).
