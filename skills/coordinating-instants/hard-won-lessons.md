# Hard-won lessons — traps and alarm hygiene

Everything here was paid for by a real failure in a real effort. The SKILL body carries the loop; this
file carries the field notes it would otherwise bury. Read it once before your first dispatch, and again
whenever a signal surprises you.

## Gotchas to watch (from real coordination runs)

| Trap | Guard |
|---|---|
| The slot pool + board are **global**, shared with other efforts | `pdispatch pool reap --base <your-instant>` (bare `reap` now refuses foreign leases; `--all` overrides). Claim with `--slot <ws>` you verified via `pdispatch pool status`. Remove your own coordinator slot from the pool at charter time. |
| Liveness / blocked / idle detection | `pdispatch health` — one correct implementation. Never hand-roll it. On a BLOCKED worker see Autonomy posture. |
| A message to a busy worker silently not submitting | `pdispatch send <id> <msg>` — verifies, retries, fails loudly. |
| Two workers pushing ONE shared branch collide | `pdispatch guard <repo> <shared-branch>` makes it impossible. Each worker owns its branch + draft PR; linear stacking happens at the compaction restack. |
| Parallel builds poisoning a shared cache; source-vs-binary skew | `dispatch-todo` isolates each workspace's build cache automatically. The final restack must still carry all pieces together. |
| Shared reference checkouts written to | `pdispatch ref protect <ref>` once, then `pdispatch ref worktree <ref> <dest>` for writes. |
| Usage/budget limits are account-wide across all your sessions | Stop new dispatch; send each inflight worker a **convergence nudge** (stop refinement cycles, finalize on current green evidence); make the final compaction lean by reusing the last one; economize polling; ensure every completed instant is independently pushed + green so a post-reset resumer can finish. **A budget plan never lowers the evidence bar** — a failed or stale run is not evidence; re-spend and record the overrun, and record any carried-over evidence as an explicit ASSUMPTION with a flagged optional re-run. |

## Alarm hygiene — you will build watchers, and they will lie to you

Empirically the largest defect family in this system is not the work failing; it is the machinery that
reports on the work being wrong. Across one effort, twenty-plus defects were false passes, false failures,
or alarms that could never turn off — in both the coordinator's watcher and the tools it depends on.

- **Prime state from reality at startup.** A seen-set built only from events observed while running
  conflates "first time I have seen this" with "this just happened", so every restart replays history.
  (`pdispatch issues --prime` does this; it reports how many it recorded, because a silent reset is worse.)
- **Anchor parsing to structure, not text.** Detect a section by its content, not its heading; do not parse
  a human-readable summary line as data (a tool's stdout is data, its commentary belongs on stderr).
- **Never match a NAME PATTERN to find your workers, either.** A pattern is wrong in both directions: a
  narrow one (`dt-r[0-9]`) silently excludes every later milestone name, a broad one (`dt-`) counts other
  efforts and the coordinator itself. Both fail silently and in opposite directions. Enumerate from the
  records for your base — `pdispatch alive --base <instant>` — so new names are covered automatically and
  nothing foreign is. Cross-check it against what `health` says SHOULD be running; a mismatch named
  out loud is a real death.
- **Never count a label as the thing.** Counting `RUNNING` rows is not counting live workers: when the
  label transiently changes, the count goes to zero and the fleet looks empty. Count processes.
- **Scope a heuristic to the population it was derived from.** A rule inferred from one wave of workers
  applied to the next produces confident nonsense.
- **An alarm that cannot be cleared is a defect, not caution.** If doing the thing the alarm asks for
  leaves it still firing, it will be ignored — and so will the real one next to it.
- **Report SUSTAINED state, never instantaneous state.** RUNNING/IDLE/PARKED flicker as a pane's progress
  comes and goes; announcing every flip produces a stream of events about a fleet that is fine. Require a
  non-terminal change to hold for N consecutive samples before reporting it; let terminal states
  (complete/harvested/dead) fire at once, since those never flap back.
- **Prime every channel you diff, not just the one that bit you.** A state map, a seen-set, a baseline —
  each needs its startup value taken from reality and announced once as a baseline. Fixing one channel and
  leaving its neighbour is the most common way these bugs recur.
- **Two watchers must never share one piece of mutable state.** An idle baseline kept in a single file was
  overwritten by whichever watcher sampled last, so both saw phantom transitions. Namespace it per caller.
- **Absence is never success.** A missing test result, an uncovered dimension, a suite that produced no
  output, a baseline that never covered the row: all mean UNPROVEN, never unbroken. State what you could
  not check, positively and by name.

Apply the same evidence discipline to alarm plumbing as to the work. When your watcher and a tool disagree,
find out which is lying before acting on either — and when two independent authors improvise the same
missing convention, the bug is the missing convention.

## Close every fix with one question
**"Where else does this exact shape live?"** Four defects in a single effort were the same fix applied in one
place and not the adjacent one: dim-qualified names hid a lost dimension from a coverage check that only
looked one way; an identifier rename broke the liveness checks consuming it; an adapter's silent parse was
fixed while its silent file-discovery was not; a priming fix landed on the issue channel and not the state
channel beside it. Asking the question costs a minute and would have caught all four.
