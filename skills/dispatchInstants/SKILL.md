---
name: dispatchInstants
description: Use when a base maintain-workspace instant has produced a solid base + multiple independent TODOs (e.g. a ranked list of ANSI gaps) and you want to kick each off as its OWN parallel, interactive Claude session — each in its own pre-built workspace (~/ws1..ws6, no rebuild) and its own forked child instant, RCA-first, reporting back onto the base. Triggers on "dispatch these TODOs in parallel", "kick off a session per gap", "fan out the ranked TODOs into workspaces", "parallel worker per TODO".
---

# dispatchInstants — parallel TODO orchestration

Turn ONE base instant (its `RANKING.md` / TODO list) into MANY parallel workers. Each TODO becomes
a **child instant** (its own maintain-workspace folder) leasing a **workspace slot** (a pre-built
`~/wsN` checkout), running as an **interactive** `claude` session you can attach to, seeded to work
**RCA-first** and report back onto the base. Built on `superpowers:maintain-workspace` (the instant
model) + `duplicateWorkSpace` (fast, no-rebuild checkouts).

## Mental model — two decoupled resources
- **Instant** = state (charter / HANDOFF / RCA / evidence). Forked off the base; permanent history.
- **Workspace** = a `~/wsN` code checkout. Leased → worked → released → re-leased. Recyclable.

A TODO = one child instant **leasing** one ws slot. Dispatch records live in a **machine-global board
store** (`~/.claude-dispatch-board/records/<id>.json`, like the pool at `~/.claude-ws-pool/`); each
report-back is the child's own folder-state + HANDOFF. `pdispatch board` (no path) derives the whole
fleet across every base from that store, so any session sees all in-flight work without asking you.

## The three tools
| Tool | Job |
|------|-----|
| `wspool.sh` | machine-global, **race-safe** (atomic `mkdir` lease) + **crash-safe** (dead-tmux reap) lease manager over an **opt-in** set of ws slots. |
| `dispatch-todo.sh` | one command: claim slot → duplicate golden (no rebuild) → fork child instant + seed an **RCA-first CHARTER** → launch interactive tmux `claude` → record the dispatch. Rolls back cleanly on any failure. |
| `dispatch-board.sh` | the fleet dashboard — takes **no arguments** (global, like `pool list`); fully **derived** from the global record store + child folder-states + leases (running / parked / complete / abort), grouped by base. Never hand-edited. |

## Entry point
`pdispatch` (in this repo's `bin/`, on PATH) is the single entry point. Run it with no args for
the toolkit map + use case. Subcommands: `pdispatch pool|todo|board|doc`. The underlying scripts
(`wspool`, `dispatch-todo`, `dispatch-board`) are also individually on PATH.

## One-time setup (per box)
```bash
# Enroll ONLY genuinely-free slots — NEVER auto-grabbed, so a ws holding other live work is safe.
pdispatch pool add ~/ws5 ~/ws6
echo ~/ws1 > ~/.claude-ws-pool/golden     # the pre-built source to clone into each slot
pdispatch pool list
```

## Dispatching a TODO (do this from the base-instant session, once per TODO)
```bash
pdispatch todo \
  --base    /path/to/<base-instant>                # the instant holding the TODOs (bulletin board)
  --profile ansi                                    # which CHARTER+SEED profile (name under profiles/ or a path); REQUIRED
  --title   "Close ANSI gap: int4 overflow"        # → dashless camelCase instant name + tmux session
  --brief   brief.md                               # the TODO description / charter seed (file or -)
  --golden  ~/ws1                                   # pre-built source (must be OUTSIDE the pool)
  --evidence "RANKING.md#1"  --evidence "c1/analysis.md"   # pointers the worker starts its RCA from
```

## Profiles (the CHARTER + SEED content)
Each worker's `CHARTER.md` and interactive kickoff SEED come from a **profile** — a
directory `profiles/<name>/` (or any path) holding `charter.md` + `seed.txt` (+ an
optional `handoff.md`), templated with `{{TITLE}} {{WS}} {{BRIEF}} {{EVIDENCE}} …`.
Select one with `--profile <name|path>`; a profile is **REQUIRED** (no silent default)
— you can also set `$DISPATCH_PROFILE` or write a name/path to
`~/.claude-ws-pool/profile`. The shipped `ansi` profile carries the Gluten-Velox
ANSI-gap pipeline; copy it to `profiles/<your-effort>/` (or anywhere) to make your
own effort's profile without touching the script.
Exit 3 = pool full (enroll a slot or wait). On success it prints the child instant, the leased ws,
and `tmux attach -t dt-<id>`.

Each launched session is seeded to: read its HANDOFF/CHARTER, run `superpowers:systematic-debugging`
to produce an **RCA** (framed **Spark-Java = gold** vs **Gluten-Velox = actual**) BEFORE any fix, then
branch on scope — small → `test-driven-development`; large → `brainstorming` → `writing-plans` →
`subagent-driven-development`. It runs autonomously and **parks** a `## Parked decision` block in its
HANDOFF only when it genuinely needs you.

## Watching the fleet & responding
```bash
pdispatch board                            # NO path — writes/prints ~/.claude-dispatch-board/REGISTRY.md (all bases)
tmux attach -t dt-<id>                     # jump into a session flagged 🅿 PARKED
pdispatch pool reap                        # reclaim a crashed holder's slot
pdispatch pool release ws5                 # free a slot when its TODO is done + merged
```
Report-back needs no live IPC: the child session transitions its own folder
(`-inflight-`→`-complete-`/`-abort-`) per maintain-workspace discipline, and the board derives the
fleet view from that. Partial completions with follow-ups stay in the TODO's own instant.

## Where it lives (fully self-contained in this repo — checkout & go)
- Skill + scripts: `skills/dispatchInstants/` (auto-discovered by the superpowers plugin).
- Dependency skill: `skills/duplicateWorkSpace/` (moved IN — a repo sibling; `dispatch-todo`
  resolves `duplicate-workspace.sh` as `../duplicateWorkSpace/…` first, so no machine path needed).
- Entry points: `bin/{pdispatch,wspool,dispatch-todo,dispatch-board,duplicate-workspace}` — all
  **relative** symlinks, so they survive a checkout at any path.
- Self-tests: `skills/dispatchInstants/tests/{wspool-concurrency,dispatch-smoke,board-smoke,adopt-smoke}.sh`
  — hermetic (temp dirs + stubs), path-independent; run any/all to verify on a fresh checkout.

**On a new machine:** (1) check out the repo; (2) install/enable the superpowers plugin from it
(the skills then load, incl. this one); (3) add `<repo>/bin` to PATH for the `pdispatch` CLI
(optional — Claude can also run the scripts from the skill dir directly); (4) `pdispatch pool add`
your free `~/wsN` slots. Nothing outside the repo is required.

## Design & rationale
`docs/2026-07-16-dispatch-instants-design.md`; the global board store is
`docs/2026-07-18-global-dispatch-board-design.md` (D-11). Proofs: `tests/*.sh` (shipped,
path-independent) — each prints `PASS`/`FAIL`.

## Constraints
Zero external deps (bash + git + tmux + coreutils + python3). No rsync/scp/curl/ssh. The pool is
**opt-in** (D-6) so it never clobbers unrelated `~/wsN` work; leases are atomic (`mkdir`, D-7) and
crash-recoverable (tmux liveness).
