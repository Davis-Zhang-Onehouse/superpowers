# dispatchInstants — Design Spec
Updated: 2026-07-16 | Status: DURABLE

Parallel-TODO orchestration on top of `superpowers:maintain-workspace` + `duplicateWorkSpace`.
See CHARTER.md for goal/scope/acceptance and DECISIONS.md D-1..D-9 for the rationale behind
every choice here.

## 1. Mental model — two decoupled resources

| Resource | What | Lifecycle | Registry |
|---|---|---|---|
| **Instant** (state) | a maintain-workspace child folder under `operations/tasks/<effort>/` | forked off base; `inflight`→`complete`/`abort` | base instant's `dispatch/` |
| **Workspace** (code) | one of `~/ws1..ws6`, a pre-built checkout | leased → worked → released → re-leased | machine-global `~/.claude-ws-pool/` |

A TODO is **one child instant leasing one ws slot**. Instant = permanent context. Slot = recyclable code.
The base instant is the **bulletin board**: every dispatch and report-back is a file there, so a cold
base session sees the whole fleet without asking the operator.

## 2. On-disk contracts

### 2a. Machine-global pool: `~/.claude-ws-pool/`
```
~/.claude-ws-pool/
  pool                     # newline list of ENROLLED slots (opt-in, D-6): e.g. "ws5\nws6"
  golden                   # optional default golden ws path (fallback if --golden omitted)
  leases/
    ws5/                   # a lease = this dir existing (atomic mkdir, D-7)
      meta                 # KEY=VALUE: TODO_ID, TMUX, BASE_INSTANT, CHILD_INSTANT, WS_PATH, EPOCH, HOLDER_HOST
```
A slot is FREE iff enrolled in `pool` AND `leases/<slot>/` does not exist.
A lease is STALE iff `leases/<slot>/meta`'s `TMUX` session is not alive (`tmux has-session`).

### 2b. Per-base-instant dispatch dir: `<base-instant>/dispatch/`
```
<base-instant>/
  dispatch/
    <todo-id>.json         # IMMUTABLE dispatch record (one writer: dispatch-todo). See 4c.
    REGISTRY.md            # DERIVED dashboard (phase 3, dispatch-board). Never hand-edited.
```

## 3. Tool ① — `wspool.sh` (the crown jewel; race-safe + crash-safe)

`wspool.sh <cmd> [args]`, `POOL_DIR` overridable via env (default `~/.claude-ws-pool`) for testing.

| cmd | behavior |
|---|---|
| `add <ws-path>...` | enroll slots into `pool` (idempotent). Validates the dir exists. |
| `remove <slot>...` | unenroll (refuses if currently leased unless `--force`). |
| `list` | print enrolled slots + FREE/LEASED/STALE + holder summary. |
| `status [slot]` | machine-readable (KEY=VALUE) status, for scripts. |
| `claim --todo <id> --tmux <session> --base <path> --child <path> [--slot <ws>]` | atomically grab a FREE slot (or the named one). Prints the claimed ws path on stdout; exit 0. Exit 3 = pool full. Writes `meta`. |
| `release <slot>` | `rm -rf leases/<slot>`. Idempotent. |
| `reap` | free every STALE lease (dead tmux). Prints what it freed. |

**Atomicity (D-7):** `claim` iterates candidate FREE slots and tries `mkdir leases/<slot>` — the FIRST
success wins the slot (mkdir fails atomically if another claimer already made it). Only after winning
does it write `meta`. No flock, no lockfile races. Concurrent claimers therefore partition the free
slots with zero double-grants; when none remain, exit 3.

**Safety (D-6):** claim only ever considers slots listed in `pool`. A `~/ws3` busy with unrelated work
is invisible unless explicitly `add`ed.

**Crash recovery:** `claim` opportunistically reaps stale leases among its candidates before failing
with "pool full", so a crashed holder's slot is auto-recovered on the next claim (also `reap` on demand).

## 4. Tool ② — `dispatch-todo.sh` (one-command launcher, clean rollback)

```
dispatch-todo.sh \
  --base   <base-instant-path>      # the parent instant (bulletin board)
  --title  <"short TODO title">     # → derived kebab id + child instant name
  --brief  <path-to-brief.md | ->   # the TODO description/charter-seed (file or stdin)
  --golden <ws-path>                # source ws to duplicate from (default: pool 'golden' file)
  [--slot  <ws>]                    # force a specific slot (else first free)
  [--evidence <ptr>...]             # repeatable pointers into base evidence (RANKING row, analysis.md)
  [--no-launch]                     # do everything except spawn tmux (for tests/dry inspection)
```

**Sequence (each step rolls back the prior on failure — trap/cleanup):**
1. Validate base instant (has HANDOFF.md/CHARTER.md). Derive `TODO_ID` = `<kebab-title>-<MMDDHHMM>`.
   Derive child instant name `<baseCurr>-<now>-inflight-append-<kebabTitle>` (maintain-workspace grammar).
2. `TMUX_SESSION=dt-<TODO_ID>`. **Claim ws:** `wspool claim --todo … --tmux … --base … --child …`.
   On exit 3 → print "pool full; enroll a slot or wait", exit 2, NO other state created.
3. **Duplicate code:** `duplicate-workspace.sh <golden> <claimed-ws> --force`. On failure → release lease, exit.
4. **Fork child instant:** `mkdir` child dir under base; copy canonical files from maintain-workspace
   `templates.md`; **seed** CHARTER (D-8) with title/brief/evidence + RCA-first mandate + scope-branch
   rule; seed HANDOFF (resume header, ws path, session log stub). On failure → release lease, rm child, exit.
5. **Write dispatch record** `<base>/dispatch/<TODO_ID>.json` (4c).
6. **Launch** (unless `--no-launch`): `tmux new-session -d -s <TMUX_SESSION> -c <claimed-ws>`, then
   `tmux send-keys` a `claude "<seed prompt>"` invocation (4b). Print attach hint.

**Golden guard:** refuse if `--golden` == the claimed slot, or if golden is itself enrolled/leased.

### 4b. Seed prompt (leverages the using-superpowers bootstrap)
> You are a dispatched worker for a parallel TODO. Your effort instant is `<child-instant-path>`
> and your code is checked out here in `<ws>`. Read `HANDOFF.md` then `CHARTER.md` in the instant
> and begin. Follow the charter's RCA-first mandate: run systematic-debugging to produce the RCA
> report (Spark-Java = gold vs Gluten-Velox = actual) before any fix, then branch on scope. Keep
> the instant maintained; when you finish or hit a decision fork, update HANDOFF.md, park the fork
> under a `## Parked decision` block if you need the operator, and transition the instant state.

### 4c. Dispatch record `<TODO_ID>.json` (immutable; one writer)
```json
{ "todo_id":"…","title":"…","child_instant":"<abs path>","ws":"~/wsN","golden":"~/wsM",
  "tmux":"dt-…","base_instant":"<abs path>","dispatched_at":"2026-07-16T…","brief":"<abs path>" }
```
Status is NOT stored here (it's derived from child folder-state + HANDOFF, D-5). This record is the
stable mapping the dashboard joins against.

## 5. Tool ③ — `dispatch-board.sh` (phase 3; fully derived)
`dispatch-board.sh <base-instant>` → writes `<base>/dispatch/REGISTRY.md`:
for each `<todo-id>.json`, resolve the child instant's current folder (glob by name stem — the
`-inflight-`/`-complete-`/`-abort-` suffix moved when the child `mv`'d it), read its state + the
`## Parked decision` block if present, join the ws lease from `wspool status`, and render a row:
`TODO | state (running/parked/complete/abort) | ws | attach cmd | child instant path | parked?`.
Nothing hand-typed → cannot drift.

## 6. Packaging & registration  (UPDATED per DECISIONS D-10 — ships with the superpowers repo)
```
<superpowers-repo>/                            ← the repo IS the plugin (installLocation); relocatable
  skills/dispatchInstants/                     ← auto-discovered; no ~/.claude/skills symlink needed
    SKILL.md
    wspool.sh  dispatch-todo.sh  dispatch-board.sh
    docs/2026-07-16-dispatch-instants-design.md
  bin/                                         ← already on PATH; ships with repo
    pdispatch                                  ← umbrella entry point (overview + pool|todo|board|doc)
    wspool  dispatch-todo  dispatch-board      ← symlinks → ../skills/dispatchInstants/*.sh
    duplicate-workspace                        ← symlink → operations/…/duplicate-workspace.sh
```
Scripts self-locate via `readlink -f "$0"` so PATH symlinks resolve to the real skill dir.
`dispatch-todo` resolves `duplicate-workspace.sh` via `$DUPLICATE_WS_SH` → PATH → known locations.
(Original plan put this under `operations/kubectlCmds/claude/` mirroring `duplicateWorkSpace`;
superseded so the toolkit ships with the repo and is callable without abs paths.)

## 7. Test strategy (each AC → one self-contained evidence script)
- `evidence/wspool-concurrency.sh` (AC-1): `POOL_DIR=$(mktemp -d)`, enroll K fake slots, fire N>K
  parallel `claim`, assert exactly K unique winners + (N-K) pool-full + 0 double-grants; kill a
  holder's fake tmux, assert `reap` frees exactly it. PASS/FAIL + exit code.
- `evidence/dispatch-smoke.sh` (AC-2): stub `claude`/`tmux`/`duplicate-workspace.sh` on PATH,
  dispatch with `--no-launch`, assert leased ws + forked child + seeded RCA-first CHARTER +
  dispatch record; then a forced-failure (make duplicate stub exit 1) asserts lease released +
  child dir gone (clean rollback).
- `evidence/board-smoke.sh` (AC-3, phase 3): dispatch then render board; assert child + attach cmd
  present; `mv` child to `-complete-`; re-render; assert reflects complete.
All three runnable from RUNBOOK.md; each prints a final `PASS`/`FAIL` line and sets exit code.
