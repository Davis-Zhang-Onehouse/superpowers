# P-worker report — prealworker-09111951 / milestone p1

## 1. What `fleet brief` told me, and whether `destination` was useful

`fleet brief --instant "$INSTANT"` did NOT work on the first try — see §3, this is the headline finding.
Once resolved, `brief` printed six rows: `origin`, `milestone`, `phase`, `review`, `destination`,
`outstanding`. All were accurate and specific:

- `origin` named the dispatching coordinator instant and timestamp.
- `milestone` told me `p1`'s stored status is `blocked` but that readiness is *derived*, and that the
  stale label does not block me — this matched reality (I was in fact able to proceed).
- `review` correctly predicted `UNDECIDABLE` before I had recorded a round, and explained why that is not
  the same as a refusal.
- `outstanding` was the most useful single row: in one line it named every remaining gate (no pending
  proposal, review gate not yet satisfied, folder still `-inflight-`, lineage base recorded, and gave me
  the exact `base-check` command with my todo id already filled in).
- **`destination` was genuinely useful**, exactly as the skill promises: it named the coordinator instant
  `fleet propose` would reach with no `--to`, sourced from `.fleet/origin.json`. It answered "where does my
  report go" before I had to write one, which is the whole point of the row.

## 2. What `base-check` said before and after repositioning

Before: `lineage prealworker-09111951:alpha violation 820698766bbd is present but NOT checked out (HEAD
7b2d4e7065fc)` — exit 1, one repo blocking a claim of done. This matched the seed's claim that the slot is
"a duplicate of the golden checkout" (HEAD was at the golden commit `7b2d4e7065fc`, per the record's
`golden_base` field) and nothing had moved it.

I ran the seed's two commands (`git -C alpha fetch --all`, then `git -C alpha checkout --detach
820698766bbd2e7758697dc8f23e8627e751562d`).

After: `lineage prealworker-09111951:alpha info at the base, 820698766bbd` — exit 0, `0 repo(s) blocking a
claim of done`. Repositioning worked exactly as documented, once I could actually invoke `fleet` (see §3).

## 3. What was WRONG, missing, or ambiguous — be specific

**This is the real finding, and it blocked step 1 entirely.** `fleet brief --instant "$INSTANT"` did not
print the six-row orientation table — it crashed:

```
BadInput: record 'prealworker-09111951' has unknown field(s): ['runtime', 'runtime_config_dir', 'runtime_executable']
```

`fleet base-check --id prealworker-09111951` failed identically. Both are the FIRST TWO commands the seed
and the skill tell a worker to run, unconditionally, before doing anything else. Neither worked as typed.

**Root cause, verified, not guessed:** `fleet` is on `$PATH` twice — once at
`/home/ubuntu/davis_root/superpowers/bin/fleet` (PATH position 4) and once at
`/home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime/bin/fleet` (PATH position 38, last). Shell
`fleet` resolution picks the **main-repo** launcher. That launcher deliberately resolves the `fleet`
package from *its own physical location* (by design — its own header comment explains this is to prevent
one process mixing modules from two releases mid-invocation), so it always imports
`/home/ubuntu/davis_root/superpowers/fleet/src/fleet`, **not** this worktree's `fleet/src/fleet` — even
though `$PYTHONPATH` already names the worktree's src and the launcher merely appends to it.

The main repo's `fleet/src/fleet/store.py` `Record` dataclass has no `runtime`, `runtime_executable`, or
`runtime_config_dir` fields at all (verified by `grep -n runtime store.py` — zero hits). This worktree
(`feat/fleet-runtime-selection`) added those three fields to support Claude/Codex runtime selection. My
dispatch record (`$FLEET_HOME/records/prealworker-09111951.json`) was written by this worktree's dispatch
code and legitimately carries those fields. Reading it back through the PATH-resolved `fleet` — which
loads the OLDER, main-repo `store.py` with the stricter unknown-field check — fails every time, for every
verb that reads this record: `brief`, `base-check`, and (I confirmed) `propose`.

**Workaround I used:** invoke the worktree's own launcher explicitly —
`/home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime/bin/fleet` — instead of the bare `fleet` on
`$PATH`. That resolves the matching `fleet/src` and every command behaves exactly as documented. Neither
the seed nor the `working-as-a-dispatched-instant` / `using-fleet` skills mention this possibility, and
both assume a bare `fleet <verb>` will work. In a feature-branch worktree with a shadowing main-repo
launcher earlier on `$PATH`, it silently does not — and the failure mode (`BadInput: unknown field(s)`)
gives no hint that the fix is "use a different binary," only that the record itself looks corrupt. A
worker without the ability (or the inclination) to `grep` two copies of `store.py` and inspect `$PATH`
order would reasonably conclude the dispatch itself is broken and park the question, when the actual fix
is a one-line explicit path.

**This is squarely a "PATH / launcher resolution" defect, not something either skill's prose could have
prevented by wording alone** — but the seed's "orient yourself, do not guess any of this" framing gave me
no signal that the very first command it tells me to run could fail for an environment reason unrelated to
my dispatch. I'd flag this to the coordinator/maintainers: either the worktree's own `bin/fleet` should be
made to win (e.g., PATH ordering, or a `.fleet-root`-relative resolution) when a dispatch happened from
inside a worktree, or `fleet dispatch`/the seed should record (and warn about) which `fleet` binary path
was actually used to write the record, so a mismatch is diagnosable from the error alone.

**Everything else in the seed and the skill was accurate and followable:**
- The "your cwd is the leased SLOT, not your instant folder" warning was correct and necessary — I would
  have run `--instant .` otherwise.
- `--id`, not `--instant`, for `base-check` — correct, and the skill calls out this exact trap.
- The "detached HEAD is enough, no naming convention required" note in CHARTER.md matched what `base-check`
  actually accepted (I never cut a branch and it was not required).
- `CHARTER.md`'s Scope and Acceptance-criteria sections were empty template placeholders
  (`<!-- The coordinator replaces this per milestone... -->`) rather than filled in for this exercise.
  Minor — the seed's own `=== YOUR TASK ===` section was the actual, complete scope — but worth noting
  since the skill says "your CHARTER.md is authoritative for your scope," and here it stated nothing.

## 4b. Would `propose --status done` have been REFUSED without repositioning?

**Yes — and I did not just infer this, I tried it.** After confirming `base-check` reported a violation
(HEAD at the golden commit, base not checked out), I ran, from that same unrepositioned state:

```
fleet propose --instant "$INSTANT" --milestone p1 --status done --evidence evidence/P-worker-report.md --dry-run
```

It returned exit code 4 with:

```
Refused: propose --status done refused: this instant was dispatched to build on
alpha=820698766bbd2e7758697dc8f23e8627e751562d (lineage-mode=code) and its workspace is not there —
820698766bbd is present but NOT checked out (HEAD 7b2d4e7065fc). ... A claim of done from the wrong base
is the failure this gate exists for ...
  clears when: the workspace is repositioned onto the recorded lineage base
  clears who: the dispatched instant
```

`--dry-run` made this safe to test without writing a record. I then repositioned back onto the base
(`820698766bbd...`) and re-ran `base-check`, confirming `at the base` / exit 0 before proceeding with the
real (non-dry-run) proposal in step 6 below.
