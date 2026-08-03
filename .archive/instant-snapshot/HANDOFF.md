# Fleet open-gap closure — HANDOFF   (read me first)
Updated: 2026-08-03 by session e7426760-8dc2-481c-a368-b80f1bce54eb  |  Status: LIVE (rots — reconcile to DECISIONS)

# ===== PART A · CURRENT STATE =====

## Where we are (one paragraph)
Instant created to drive named gaps to closure. **`G-6` is done** (`d07b4a2`). Re-reading the
coordinator's register afterwards found it had been updated 40 minutes earlier — 15 findings → 17 — and
both new ones landed on work shipped that same night: **`G-7`** corrects a false claim I made and built a
verb on, and **`G-8`** exposed a regression from three of our own changes composing (fixed: `11f2f58`).
**Seven gaps remain**, ranked in `PRIORITIES.md`. Each gap has an exhaustive,
self-contained brief under `evidence/issues/` — symptom with verbatim quotes, measurements, code
locations, what a fix must decide, and how to know it is closed. Four were deferred by operator decision;
one is an untouched acceptance criterion; one (`G-6`) was found on 2026-08-03 while checking whether the
release pipeline was documented at all. It is not.

**Later on 2026-08-03** the operator asked to brainstorm → design → plan the remaining seven before any
implementation. Re-measuring first (now `bin/reverify-briefs.sh`, `D-4`) held eight of ten premises and
broke two: **`A-2` is REFUTED** — "`DA-2` enumerated six send paths" has no source anywhere, which removes
`G-1`'s de-duplication argument and voids one of its closure criteria (`G-1` §6a) — and **`G-7`'s false
premise is live in shipped source**, in `Roadmap.retire`'s docstring, which makes its central design
question genuinely open rather than foregone (`G-7` §5a). Filed `G-9` against the new check itself: it has
no control.

**Then, same day, the effort moved from analysis into delivery.** The operator picked `G-1`+`G-2` as one
piece and parked `G-7`; a repro and a grounded RCA came first (`investigations/g1-g2-stall-loop/`), which
found `G-10` — the detector `G-2` would actuate on had **no test at all** — and, after the operator asked
whether a legitimately-parked child would be nudged, `G-11`: a parked question reaches nobody. Both were
folded in. A design (`specs/`) and a 10-task plan (`plans/`) were written and approved, then executed by
dispatched subagents with a two-stage review per task. **Five tasks are complete and reviewed; `G-10` and
`G-11` are CLOSED. `G-1` is mid-flight and archived on a branch. `G-2` has not started.** A sixth finding,
`G-12`, was raised along the way. Live state, per-task, is in the snapshot below; the authoritative
per-task record is the SDD ledger named in the Index.

## Live snapshot (volatile — dated 2026-08-03 ~06:15Z, at archiving)

**Implementation is UNDERWAY and paused mid-Task-6 on operator instruction. 5 of 10 tasks complete.**

| # | task | state |
|---|---|---|
| 1 | `G-10` — the `IDLE` detector gets a test | ✅ `653ff90`, reviewed, control flips `M-1`/`M-3` to KILLED |
| 2 | `#{session_attached}`, failing safe | ✅ `fdccc8c`, reviewed |
| 3 | `D-9` gate — measure attention BEFORE | ✅ artifact; controller-verified, no diff to review |
| 4 | `G-11` — `PARKED` becomes actionable | ✅ `4933291`, reviewed, ZERO findings |
| 5 | `D-10` — `awaiting-ci` needs a live watcher | ✅ `32368a9`, reviewed, 1 minor deferred |
| 6 | `G-1` — `fleet pane-send` | ⏸ **WIP on `stall-loop-g1-g2` (`bb3371e`)**, steps 1–7 of 10, unreviewed |
| 7 | declared profile kind (`D-11`) | not started |
| 8 | `G-2` — `fleet nudge` | not started |
| 9 | watchdog heartbeat | not started — **needs operator sign-off before arming** |
| 10 | re-run reds → green, cut `0.4.0` | not started |

- **Gaps closed so far: `G-10`, `G-11`.** `G-1` and `G-2` — the two the operator pays for daily — are still
  OPEN. `G-1` is close but its closure criterion is unmet (see the branch caveats above).
- **New findings raised while implementing:** `G-12` (both shipped charters instruct a command that exits 2,
  and the linter enforces the broken form — verified three ways, out of scope here). Plus two deferred
  minors, both in the ledger.
- Suite: **1204 green on `live`**, 1231 on the WIP branch with an unexplained delta.
- `AC-2` still has NO artifact — no release has been cut over any of this.
- **Real-claude probes are authorised for this session without asking (`D-6`).** Scoped to this session.
- No probe sessions left behind: `probe-ra1-send-race.sh` reaps on exit. Verify with
  `tmux -L fleetprobe ls` (expect "no server") and `tmux ls` (the default server must never hold one).
- **`bash bin/reverify-briefs.sh` exits 1 by design** — row `A-2` is REFUTED. That is a known, recorded
  refutation (`ISSUES.md`, `ASSUMPTIONS.md` `A-2`), not a fresh alarm. Every other premise HOLDS at
  `11f2f58`.
- **This instant's own path moved** — it now lives under `operations/tasks/metaOpt/fleetInfraOps/`, not
  `operations/tasks/fleetInfraOps/`. The session-log resume command below is corrected; any inherited copy
  of the old path is wrong.
- Predecessor `00000000-08021753-inflight-append-quantonFeedbackAndReleases` stays INFLIGHT and keeps the
  standing duty of monitoring the two quanton registers (`D-2`). It is not blocked by this instant.
- `0.3.1` RELEASED and GREEN, but **six commits have now landed on `live` since it was verified**
  (`d07b4a2`, `11f2f58`, `653ff90`, `fdccc8c`, `4933291`, `32368a9`) plus one WIP on the branch, and no
  release has been cut over any of them — so `AC-2` has no artifact at all (`evidence/INDEX.md` says so
  explicitly rather than leaving the gap implied). The `0.4.0` cut is Task 10.
- **`G-11` (Task 4 of the stall-loop plan) closed the `D-9` gate: `ACTIONABLE_STATES` widened to
  `(BLOCKED, IDLE, PARKED)`.** `reconcile.py`'s comment and `test_reconcile.py`'s
  `TestAParkedQuestionAsksForAHuman` now encode why: `fleet park --question` is a child saying "I
  cannot proceed without a decision" (an empty park is refused at the producer, so a park is always a
  real question), and `PARKED` being excluded meant `needs_a_human` said False and the question reached
  nobody until it timed out into `IDLE` after 30 minutes — the same defect as `FI-14`, one state over.
  `test_render.py`'s `test_the_needs_you_count_excludes_dead_sessions` tripwire fired exactly as
  designed on the old `{"BLOCKED", "IDLE"}` set assertion; updated to the three-element set, not
  deleted. Full suite: 1192 green (was 1190).
  **`D-9`'s before/after attention measurement on the real store (`bin/measure-attention.sh`):**
  `NEEDS-YOU` is **1 before and 1 after** (10 subjects both times; the one BLOCKED subject,
  `v2stackcoordinator-07310348`, is unchanged). **No subject in the live population is currently
  parked** (`evidence/2026-08-03-attention-{before,after}.txt` both show `parked=False` on every row),
  so this is the expected **no-regression** result, not evidence the fix works and not evidence it did
  nothing — the live store simply has zero parked subjects right now to move. The fix is proven by the
  hermetic test above, which constructs a parked subject and asserts `needs_a_human` flips to True; the
  live measurement's job here is only to confirm the widening moved nothing it shouldn't have.

## PR / branch stack   (REQUIRED slot)
| Repo | Branch | Tip githash | PR | CI | Contents |
|------|--------|-------------|----|----|----------|
| superpowers | `live` | [`32368a9`](https://github.com/Davis-Zhang-Onehouse/superpowers/commit/32368a98aabb5c8fbba4833ceb23aa9c6c965989) | branch only; pushed, `live` == `origin/live` | n/a — no CI on this box; the gate is local (`RUNBOOK.md`) | Five REVIEWED commits: `d07b4a2` (G-6) · `11f2f58` (G-8 severity half) · `653ff90` (**G-10**) · `fdccc8c` (attachment probe) · `4933291` (**G-11**) · `32368a9` (**D-10**). 1204 green. |
| superpowers | **`stall-loop-g1-g2`** | [`bb3371e`](https://github.com/Davis-Zhang-Onehouse/superpowers/commit/bb3371e) | [open a PR](https://github.com/Davis-Zhang-Onehouse/superpowers/pull/new/stall-loop-g1-g2) — none yet | same | **THE ARCHIVE BRANCH.** `live` + one **WIP, UNREVIEWED** commit carrying `G-1`'s `pane-send`. 1231 green, but see the caveats below — do NOT merge as-is. |

Both branches CLEAN and pushed. `live` holds only reviewed work; the WIP is quarantined on the branch.
Checked out branch as of archiving: `stall-loop-g1-g2`.

### ⚠️ What `bb3371e` is and is not
Archived mid-task on operator instruction, not at a natural boundary. **Green (1231) is not the same as
done**, and three things are outstanding:
1. **`live-pane.sh cmd_submit` is NOT re-pointed at the verb.** That is `G-1`'s actual closure criterion —
   two implementations of one primitive collapsing into one — so **`G-1` is NOT closed.**
2. **No live-pane integration proof was captured.** The verb's contract is measured (`RA-1`), but this
   implementation of it has never driven a real claude pane.
3. **The +27 test delta is UNACCOUNTED FOR.** 1204 → 1231. Expected +9 hand-written and +2 per new flag
   (3 flags → +6) = +15. **Twelve cases are unexplained**, and `test_contracts.py` was edited too. An
   unexplained total is not evidence of anything — reconcile it before trusting this commit.
4. **No task review has run against this diff.** Every other commit on `live` has one.

What IS verified in it: the §M9 spawn-seam audit passes and attributes both new send sites to the
already-declared seam (checked, not assumed), and the verb is registered with the flags the design names.

**Everything is in that one repo** — 21 package modules, all tracked, no untracked files, one remote.

## How each artifact was built & tested (REVIEWER GUIDE)
### `bin/reverify-briefs.sh` — the `A-1` gate (`D-4`)
- **What it is:** one command that re-derives the CORE premise of every open brief and exits non-zero if
  any moved. It is what `A-1` used to ask a human to do by hand.
- **Built by:** turning the by-hand re-measure of 2026-08-03 into assertions — each row is the grep or the
  `python3 -c` that established the fact, with the verdict computed rather than narrated.
- **Tested by:** running it against `11f2f58` on a CLEAN tree; artifact
  `evidence/2026-08-03-brief-reverification.txt`. Two self-inflicted defects were found and fixed while
  writing it: `grep -rl` without `--include` recited `__pycache__/*.pyc` as extra consumers, and a `tee` in
  the invocation masked the exit code — which is `SI-38`'s exact shape (a gate whose exit is read from the
  wrong place), caught here before it was relied on.
- **Caveat, recorded as `G-9`:** it has **no control**. Nothing yet demonstrates a row CAN go red, and two
  of the ten rows assert an absence. Do not cite its verdict as proof beyond its own rows until `G-9` is
  closed.

### the eight briefs
- **What they are:** the closure specs. Each is self-contained by construction — a reader needs neither
  the parent instant, nor the quanton registers, nor a transcript.
- **Built by:** carrying forward the measurements taken 2026-08-02/03, with the exact command that
  produced each one, so `A-1` can be re-checked cheaply.
- **Caveat:** they describe the tree at `0.3.1`. `A-1` says re-measure before starting — three findings
  in this line of work turned out already fixed or misclassified when re-measured.

# ===== PART B · HANDOFF (pickup guide) =====

## Resume here
- Workspace: `/home/ubuntu/davis_root/superpowers` · Instant: this directory
  (`…/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure`)
- **First command, always: `bash bin/reverify-briefs.sh`** (`D-4`). It re-derives every open brief's core
  premise in one run. Expect exit 1 with `A-2` REFUTED — anything else is new and must be read before
  designing. Do not skip it: three findings in this line of work evaporated on re-measure.
- Then read `CHARTER.md` for the eight, then the brief for whichever you take. `G-1` §6a and `G-7` §5a are
  dated amendments — read them, they change both gaps' scope.

## Next action (the very next thing to do)

**Resume the stall-loop plan at Task 6, step 8.** Everything is on disk; nothing needs re-deriving.

```bash
cd /home/ubuntu/davis_root/superpowers && git checkout stall-loop-g1-g2   # the WIP lives here, not on live
cat .superpowers/sdd/2026-08-03-stall-loop-implementation/progress.md      # the ledger IS the recovery map
```

**Read in this order:**
1. `.superpowers/sdd/…/progress.md` — the SDD ledger. Every task's outcome, every deviation, every deferred
   minor, every carried risk. It survives a lost session; this HANDOFF summarises it, it does not replace it.
2. `plans/2026-08-03-stall-loop-implementation.md` — the plan. **Tasks 1–5 are done and reviewed. Task 6 is
   partially done (steps 1–7 of 10).** Tasks 7–10 untouched.
3. `specs/2026-08-03-stall-loop-design.md` — why the design is what it is, and the four questions it answers
   explicitly (who detects, under what condition, who is nudged, what is actually sent).
4. `investigations/g1-g2-stall-loop/analysis.md` — the RCA. `state-vocabulary.md` beside it gives the exact
   `IDLE`/`PARKED`/`AWAITING-CI` definitions and the observed-vs-declared split.

**Task 6's remaining steps, in order** (brief at `.superpowers/sdd/…/task-6-brief.md`):
- **step 8** — re-point `fleet/it/bin/live-pane.sh`'s `cmd_submit` at `fleet pane-send`, keeping its
  `check_name` refusal. **Until this lands, `G-1` is not closed**, because its closure criterion is that the
  two implementations of the primitive become one.
- **step 9** — `bash fleet/it/bin/live-pane.sh selftest` (free), then
  `FLEET_ALLOW_LIVE_CLAUDE=1 bash bin/probe-ra1-send-race.sh` (~10 min, authorised per `D-6`). The
  `submit (condition)` row must still report `submitted=YES`; it then exercises the VERB, which is the live
  proof. Copy the artifact aside — the script archives its own previous run now, but the top-level `.txt` is
  overwritten.
- **step 10** — reconcile the **unexplained +12 test cases**, then commit.
- then a task review, which this diff has never had.

**Then Tasks 7–10:** the declared profile-kind read (`D-11`) → `fleet nudge` (`G-2`) → the watchdog heartbeat
→ re-run every red and cut `0.4.0`.

**⚠️ Before Task 9 arms anything, stop and ask the operator.** The real store holds other efforts' live work
(a `RUNNING` worker and a `BLOCKED` coordinator were present at archiving). Neither is nudgeable by design,
but Task 9 wires `fleet nudge` into a daemon that may already be armed — which would make automatic sends to
other efforts' panes live on the next `$INTERVAL`. Show the `fleet nudge --dry-run` output first.

**An open question the operator has not answered:** whether `live` should be rewound so the five reviewed
commits move onto the feature branch too. They are currently on `live` AND on `stall-loop-g1-g2`. Rewinding
`live` would rewrite pushed history and `RUNBOOK`'s release cycle cuts from the branch, so it was not done
unilaterally.


**Brainstorm the `G-1`+`G-2` design with the operator, then write the spec and the plan.** The operator
chose that slice 2026-08-03 and parked `G-7`. Repro and RCA are DONE — brainstorming is the gate that
remains, and nothing may be implemented before a design is approved.

Read first: **`investigations/g1-g2-stall-loop/analysis.md`** (the RCA — why-chain, five design
consequences that are facts rather than opinions, three open assumptions). Two of those assumptions need an
operator decision before they can be closed: `A-6` needs a real claude pane (**spends weekly allowance**),
`A-5` needs load instrumentation.

Fix direction the RCA establishes, in order: (1) close the detector's test gap (`G-10`) — the repro's PART 1
already IS the missing test; (2) `G-1`'s verb; (3) `G-2`'s actuator — *the missing component that ACTS on the
judgement; the operator is that component today (see the RCA's §"Terms used below")*. Step 1 is not
optional: an actuator over
an unguarded detector makes any future `_live_state` regression present as "the nudges stopped working".

The sequence below is the pre-existing recommendation. `G-7`'s §5a changes its first step: the choice
"does `--retire` become sugar over propose/apply?" is now a genuinely open call on the merits, because the
carve-out's real argument (advance-vs-remove) survives independently of the false premise. Decide it
deliberately; the brief's original recommendation was made without knowing that.
**`PRIORITIES.md`** ranks by impact, effort and risk. **`evidence/recommended-sequence.md`** explains why
the execution order DIFFERS from that ranking, and which orderings are preferences versus real failure
modes. The sequence:

1. **`G-7`** — an hour. One clause on `milestone`'s refusal, plus the decision whether `--retire` becomes
   sugar over propose/apply. It corrects a false belief that has already produced two wrong conclusions,
   and `G-8`'s central design question is `G-7`'s question.
2. **`J7` + `J2` mutations from `G-5`** — a day, no decisions, and it makes everything after it
   verifiable. `J7` alone is worth it: *"if this is wrong, `reap` kills somebody else's pane"* is
   currently an unproven claim.
3. **`G-1` + `G-2` as ONE piece** — stops the daily tax (the operator is the mitigation today) and closes
   the loop properly rather than adding a seventh send implementation.
4. **`G-8`** — brainstorm the vocabulary; measure readiness on a real roadmap before and after any
   `LANDED` change.
5. **`G-4`** — brainstorm first, measure the attention counter before and after, and it makes `G-2`'s
   nudge safe. Read its retraction section before proposing anything.
6. **`G-3`'s cheap half** — refuse an empty scope — then measure whether the full two-phase split is
   still needed.
7. The rest of `G-5`'s frame and `G-3`'s split, as background.

**Two constraints that are not negotiable** (`PRIORITIES.md` §"sequencing"): `G-1` before `G-2`, and
never change `ACTIONABLE_STATES` semantics twice without measuring in between.

## Setup you end up with (delivered handoff)
- Deliverables: eight gaps closed or explicitly re-deferred with a reason; a GREEN release after the last
  fix; the briefs still true at close-out.
- **AC-1:** 1 of 8 closed (`G-6`); `G-7`/`G-8` added 2026-08-03; `G-9` (this instant's own tooling) added
  2026-08-03 and is not one of the eight.
- **AC-2:** **no artifact** — two commits since `0.3.1` was verified, no release cut over them.
- **AC-3:** partial machine coverage as of `D-4` — `bin/reverify-briefs.sh` checks each brief's CORE premise
  every run, not its whole body. `G-6`'s brief was updated at closure; `G-1` §6a and `G-7` §5a are dated
  amendments; the rest still describe `0.3.1` and now have a one-command way to say so.

## Session log
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| 2026-08-03 | /home/ubuntu/davis_root/superpowers | `cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure && claude --resume ef733ca7-5db1-4efd-99a4-2633f954e816` | Created the instant; six briefs; CLOSED G-6 (`d07b4a2`); PRIORITIES.md + recommended-sequence.md; re-read the coordinator register, added G-7/G-8, fixed the terminal-dep regression they exposed (`11f2f58`, 1183 tests) |
| 2026-08-03 | /home/ubuntu/davis_root/superpowers | `cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure && claude --resume e7426760-8dc2-481c-a368-b80f1bce54eb` | Resumed to brainstorm the open gaps. Read all 8 briefs + PRIORITIES + recommended-sequence. Built `bin/reverify-briefs.sh` (`D-4`) and ran it → **`A-2` REFUTED** (the "six send paths" count has no source; `G-1` §6a) and **`G-7`'s false premise found in shipped source** (`roadmap.py` docstring; `G-7` §5a). Created the missing `evidence/INDEX.md` (invariant 4). Filed `G-9` (the new check has no control). Fixed this instant's path drift. No code touched in the product. |
| 2026-08-03 | /home/ubuntu/davis_root/superpowers | same as above | **Closed `RA-1`/`A-6` on a real claude pane** (`D-6`: allowance authorised for the session). 12 clean trials via `bin/probe-ra1-send-race.sh`: the race is REAL and **intermittent — 1/5 at gap=0**, and **`pane-guard` after the type predicted the outcome 12/12**, which makes the polling contract decisive rather than merely safer. Also found the ORIGINAL 2026-08-02 sweep's trials 2-4 were contaminated by residue in the input box — its conclusion survives a clean re-measurement (0/6 at ≥50ms), its numbers do not. `A-5` (150ms under load) still OPEN: 0/2 at loadavg 0.32 is not a rate. |
| 2026-08-03 | /home/ubuntu/davis_root/superpowers | same as above | Operator picked **`G-1`+`G-2` as one loop**, parked `G-7`. Reproduced both with `bin/repro-g2-stall-loop.sh` (mutation experiment with a built-in control) and wrote the RCA at `investigations/g1-g2-stall-loop/analysis.md`. **Found `G-10`: `FI-14`'s IDLE detector is guarded by NO test** — disable it and 1183 tests stay green, while the control dies. **Closed `A-4`** by reading `claude-auto-retry` at last (`DA-2`'s action, open since the design phase): it uses a 150ms delay, not the condition, and its `pane-guard` patch gates only before typing — which settles `G-1` §5.1 as *verb*. Raised `A-5`/`A-6`. Still no product code touched. |

| 2026-08-03 | /home/ubuntu/davis_root/superpowers (branch `stall-loop-g1-g2`) | `claude --resume e7426760-8dc2-481c-a368-b80f1bce54eb` | Wrote the design (`specs/`) and a 10-task plan (`plans/`), then EXECUTED tasks 1-5 via subagent-driven development with a two-stage review per task. Closed **`G-10`** (`653ff90`) and **`G-11`** (`4933291`); landed the attachment probe (`fdccc8c`) and **`D-10`**'s watcher requirement (`32368a9`). 1183 -> 1204 green. Filed **`G-12`** (charters instruct a command that exits 2 — verified three ways). Task 6 (`G-1`'s `pane-send`) archived mid-flight to branch `stall-loop-g1-g2` (`bb3371e`), green at 1231 but UNREVIEWED with an unexplained +12 and its closure criterion unmet. Ledger: `.superpowers/sdd/2026-08-03-stall-loop-implementation/progress.md`. |

## Index
- Scope / acceptance / constraints → CHARTER.md
- The eight gaps → `evidence/issues/G-*.md` (the record) · ISSUES.md (the index, plus `G-9`)
- Order → PRIORITIES.md (ranked by impact) · `evidence/recommended-sequence.md` (why execution differs)
- **Is any brief stale? → `bash bin/reverify-briefs.sh`** (`D-4`); proofs → `evidence/INDEX.md`
- Decisions → DECISIONS.md (`D-1`..`D-11`) · Unverified assumptions → ASSUMPTIONS.md · Commands → RUNBOOK.md
- **Design → `specs/2026-08-03-stall-loop-design.md`** · **Plan → `plans/2026-08-03-stall-loop-implementation.md`**
- **Execution ledger → `/home/ubuntu/davis_root/superpowers/.superpowers/sdd/2026-08-03-stall-loop-implementation/progress.md`**
  (per-task outcomes, deviations, deferred minors, carried risks — the recovery map; it outranks this file on task detail)
- RCA → `investigations/g1-g2-stall-loop/analysis.md` · state definitions → `.../state-vocabulary.md`
