# Fleet Root Isolation — Design

**Date:** 2026-09-06
**Status:** approved in brainstorm, ready for an implementation plan

## Goal

Make a `fleet` a property of a **root directory under `$HOME`**, so that `~/davis_root` and `~/davis2_root`
each run their own fleet — their own records, their own slot pool, their own tmux server, their own release
area — and neither can read, write, lease from, or kill anything belonging to the other.

The root is discovered by walking up from the working directory to a `.fleet-root` marker, the way `git`
finds `.git`. Nothing is derived from a path constant, and nothing falls back to a shared default.

## What is already isolated, and therefore out of scope

Measured 2026-09-05/06 at `fleet 0.3.18` (the tree and `fleet-releases/current` are the same version today).
Scoping this correctly matters: half of the obvious work is already done, and doing it twice is how a design
grows a migration it did not need.

| state | where it lives | verdict |
|---|---|---|
| the milestone registry, the proposal inbox | `<instant>/.fleet/roadmap.json`, `proposals.json` (`roadmap.py:180-184`) | **already per-effort.** No change. |
| instants | `$FLEET_INSTANTS`, per effort — e.g. `~/davis_root/operations/tasks/<effort>/instants` | already per-effort **when set**; the unset case is the defect below |
| the release area | `$FLEET_RELEASES` = `~/davis_root/fleet-releases` | already root-scoped **by an export**, not by derivation |
| the auto-resume watchdog's own state | `~/davis_root/.claude-auto-retry/` | already root-scoped |
| the fork-sync control dir | `~/davis_root/.superpowers-sync/` | already root-scoped |

## What is shared, measured

```
FLEET_HOME=/home/ubuntu/.fleet          # 75 records, 6 enrolled slots, harvest sources
FLEET_TMUX_SOCKET=fleet                 # one server for every root on the box
FLEET_RELEASES=/home/ubuntu/davis_root/fleet-releases
```

Four distinct interference paths, each verified rather than reasoned about:

**1. One store.** `~/.fleet/{records,pool,harvest}` is box-wide. All six enrolled slots
(`~/.fleet/pool/enrolled/ws*.json`) carry absolute paths into `davis_root`. A `davis2_root` coordinator
sharing this store would see `davis_root`'s dispatch records in `fleet board`, and could lease
`davis_root`'s workspaces.

**2. One tmux server.** `close`, `abort` and `harvest` kill sessions **by name**. Session names are
`dt-<subject>`, and subject names are chosen by the coordinator — so two roots working on similarly-named
milestones can collide, and the loser is killed without a diagnostic. `fleet-env.sh:30` already argues for a
private server over the default one for exactly this reason; the argument simply has not been taken one step
further to per-root.

**3. The instants fallback writes into the store.** With `FLEET_INSTANTS` unset, `cli.py:519` resolves
instants to `$FLEET_HOME/instants`. This is `SI-56` / `FI-382`: a `dispatch` returned rc=0 with all four
guards `allow` and planted the child in `~/.fleet/instants` instead of the effort tree. Nothing downstream
goes red — every verb resolves the child through its dispatch record — so the damage surfaces only at
endgame compaction, when the instant is not in the directory being enumerated.

**4. Two consumers name the shared values as constants.** `scripts/fleet-env.sh:34,41` hardcode
`/home/ubuntu/davis_root/...`; `scripts/claude-watchdog.sh:30` hardcodes `DAVIS="/home/ubuntu/davis_root"`
and `:210` defaults its socket scan to the literal `fleet`. A second root sourcing `fleet-env.sh` gets the
first root's release area.

There is a fifth, and it is already broken rather than merely shared: `cli.py:3258` defaults a read-only
release verb to `Path.home()/".fleet-releases"`, **a path that does not exist on this box.** Root derivation
replaces a phantom default with a correct one.

## The resolution model

### The marker

A file at the top of each root:

```
~/davis_root/.fleet-root      {"name": "davis"}
~/davis2_root/.fleet-root     {"name": "davis2"}
```

**The name is declared, not derived from the path.** This is the one design decision most directly bought
with a measured failure. `FI-421`'s fix for a dead path constant shipped *with a silent fallback* because it
slugified a directory into a name with `replace("/", "-")` while the harness also maps `_` to `-`, so
`davis_root` and `davis-root` silently diverged. A declared name has no derivation to get wrong. It is also
what the tmux socket is built from, and a socket name is exactly the kind of value that must not change
because somebody renamed a directory.

The marker is a distinct filename from the store directory (`.fleet-root` vs `.fleet/`) on purpose: an
instant carries its own `<instant>/.fleet/` (`roadmap.py:180`), so a walk keyed on `.fleet` would stop at the
first instant it passed through and call it a root.

### The walk

Resolve the working directory physically (`Path.cwd().resolve()`), then walk upward testing each directory
for `.fleet-root`. **The walk covers cwd up to but excluding `$HOME`.**

Excluding `$HOME` is deliberate. A marker at `$HOME` would make every root one root again, silently — it
would look like the feature working and behave like the feature absent. So it is never found. When the walk
fails *and* `$HOME/.fleet-root` exists, the refusal says so by name:

> no `.fleet-root` at or above `<cwd>` (searched up to `~`). There **is** one at `~/.fleet-root`, which is
> deliberately not honoured: a marker there makes every root the same root. Put it at `~/<root>/.fleet-root`.

Physical resolution has one consequence worth stating rather than discovering: if a workspace under one root
is a symlink into another root's tree, the walk lands in the tree the files really live in. That is the
correct answer to "which fleet owns these bytes", and it is not the answer someone following the symlink
expects. It is recorded here so the first person to hit it reads a note instead of filing a defect.

### Precedence

Ordered by **how specifically the caller named the destination** — the rule `cli.py` already argues for at
I2-11, where an explicit `--home` had been out-ranked, for a component of its own destination, by an
environment variable the caller never mentioned.

| tier | source | scope |
|---|---|---|
| 1 | `--home` / `--instants-dir` / `--releases` | one component each |
| 2 | `--root <path>` | home + releases + socket |
| 3 | `$FLEET_HOME` / `$FLEET_INSTANTS` / `$FLEET_RELEASES` | one component each |
| 4 | `$FLEET_ROOT` | home + releases + socket |
| 5 | the marker walk | home + releases + socket |
| 6 | **refuse** | — |

`--root` is new and earns its place by making cross-root inspection possible without a `cd`:
`fleet board --root ~/davis2_root`.

**Tiers 1 and 3 are unchanged from today**, which is what protects the existing suites: **1291 occurrences
across 238 files** already name the store with `--home` or `FLEET_HOME` — `fleet/it` 1209 in 222 files,
`fleet/tests` 47 in 4, `scripts` 19 in 5, `skills` 16 in 7 — and every one of them keeps working
byte-for-byte.

The existing implication **`--home X` ⇒ instants `X/instants`** is also kept exactly as it is. What is
deleted is narrower: when `home` was resolved at tier 4 or 5 and no instants directory was named at any
tier, `fleet` **refuses** instead of deriving `$FLEET_HOME/instants`. That is `SI-56` closed, and it is
closed by removing a fallback rather than by re-pointing it.

### Tier 6 applies to reads

This revises `SI-15`, which established that a *mutating* verb with no store named refuses while a read-only
verb keeps the default, on the ground that *"nothing is enrolled" is a real answer to a real question*.

Under isolation that ground no longer holds. A read that falls back to a shared default is not answering
about no fleet in particular — **it is answering about a different root's fleet**, confidently, with a
population line and everything. That is the `FI-417` shape: a true sentence answering the wrong question. So
reads refuse too, and the refusal names the cwd it searched from.

The cost is real and worth stating: discovery from an unmarked directory stops working. `fleet board` in
`/tmp` no longer prints an empty board; it prints a refusal naming what would fix it. That is the trade this
design accepts.

## The derived layout

```
$ROOT/.fleet-root                     the marker            {"name": "<name>"}
$ROOT/.fleet/records/                 dispatch records
$ROOT/.fleet/pool/enrolled/           slot membership
$ROOT/.fleet/pool/leases/             THE LOCK
$ROOT/.fleet/harvest/                 harvest sources
$ROOT/fleet-releases/current          the deployed export
socket                                fleet-<name>
instants                              named, or derived from an explicitly named home — never from a
                                      derived one (see Precedence)
```

Roots are stored **resolved**. During migration `~/.fleet` and `~/davis_root/.fleet` are the same directory
reached two ways; resolving means both answer `/home/ubuntu/davis_root`, so the compatibility symlink cannot
manufacture a root mismatch.

## Three guards

The marker walk cannot be forgotten, which is its whole advantage over an exported variable. Its exposure is
the mirror image: a process that changes directory across roots changes fleets. These make that loud instead
of silent.

### G1 — a dispatch may not point outside its own root

The obvious form of this guard would be vacuous, and it is worth saying why before specifying the real one.
Records live *inside* the store (`$ROOT/.fleet/records/`), so a verb run in root A can never accidentally
resolve a record belonging to root B — it would not find it. "Wrong record" is not the exposure.

The exposure is a record in root A whose **contents point into root B**, which is exactly the `FI-382`
shape one level out: `dispatch` accepts an `--instants-dir` or a slot anywhere on the filesystem, exits 0
with every guard green, and nothing downstream disagrees because every verb resolves the child through the
record. So:

- `dispatch` **stamps the resolved root** into the record.
- `dispatch` **refuses** when the instants directory, or the slot it is about to lease, does not resolve
  under the active root — naming both paths.
- Any verb resolving a record refuses when the record's stamped root differs from the active root. This
  catches a store copied or restored between roots, which the containment rule above cannot see.

This is `FI-381`'s rule — *every claim states the tree it was measured on* — applied to the store instead of
to source, and it is what turns "the roots do not interfere" from a description of intended behaviour into
something a command refuses to violate.

### G2 — every verb prints its resolved root and where it came from

In the banner and in `--porcelain`:

```
root  /home/ubuntu/davis_root   (marker at /home/ubuntu/davis_root/.fleet-root)
root  /home/ubuntu/davis2_root  ($FLEET_ROOT)
root  /tmp/it-sandbox/A3        (--home)
```

`FI-421`'s second defect — the function written to remove a silent fallback shipping with a silent fallback —
was caught **only by printing the resolved path**. Its own words: *"reading the code would not have shown it;
printing the resolved path did."* A resolution chain with five tiers gets the same treatment from the start.

### G3 — the pool refuses a foreign slot

`Pool.enroll` (`pool.py:247`) asserts the workspace path resolves under the pool's own root, and refuses by
name when it does not. This is what makes *"davis2 cannot lease a davis_root workspace"* mechanical rather
than conventional. Without it, isolation is a claim about how people will behave.

## Migration

The live store holds 75 records, 6 enrolled slots and an inflight coordinator.

1. **Quiet moment.** No worker mid-turn. The coordinator may stay inflight — its instant is not touched.
2. `mv ~/.fleet ~/davis_root/.fleet` then `ln -s ~/davis_root/.fleet ~/.fleet`.
3. Write both markers: `~/davis_root/.fleet-root` `{"name":"davis"}`, `~/davis2_root/.fleet-root`
   `{"name":"davis2"}`.
4. **Enrolled slots need no rewrite** — all six already carry absolute `davis_root` paths. Verified.
5. Fix the four consumers in the table below.
6. Drop the symlink once `fleet selftest` and the IT isolation sections are green without it.

**The symlink is a net, and it has a hazard that must be closed before it is trusted.** While `~/.fleet`
still resolves, a shell carrying a stale `FLEET_HOME=~/.fleet` export with no marker above its cwd reaches
`davis_root`'s store through tier 3 — which is precisely the interference this design exists to remove, wearing
the compatibility layer as a disguise. So step 5 lands **before** step 2 is relied on, and `fleet-env.sh`
stops exporting a literal `FLEET_HOME` at all.

The socket changes name at migration (`fleet` → `fleet-davis`). Sessions already running on the old server
are not migrated; they keep running and remain reachable as `tmux -L fleet attach`. This is stated because a
coordinator that reads `dt-*` sessions vanishing from `fleet-davis` should recognise it as the rename rather
than as dead workers.

## Blast radius

Every consumer that assumes the shared values today, with its line:

| file | line | today | after |
|---|---|---|---|
| `fleet/src/fleet/cli.py` | 495 | `home = Path(named_home or Path.home()/".fleet")` | resolve through the 6 tiers |
| `fleet/src/fleet/cli.py` | 519 | instants fall back to `home/"instants"` | kept for tier 1–3; refused for tier 4–5 |
| `fleet/src/fleet/cli.py` | 3258 | releases default `Path.home()/".fleet-releases"` (does not exist) | `$ROOT/fleet-releases` |
| `fleet/src/fleet/session.py` | 257–264 | socket from `$FLEET_TMUX_SOCKET` or the default server | env, else `fleet-<name>` from the marker |
| `fleet/src/fleet/pool.py` | 247 | `enroll` accepts any directory | G3: refuse outside the root |
| `scripts/fleet-env.sh` | 21, 30, 34, 41 | literal `$HOME/.fleet`, `fleet`, `/home/ubuntu/davis_root/...` | derive from the marker; export nothing literal |
| `scripts/claude-watchdog.sh` | 30, 83, 210 | `DAVIS=` constant, `$HOME/.fleet`, socket scan defaults to `fleet` | derive; **`:210` must learn the per-root socket or it monitors nothing** |
| `bin/fleet-view` | 408 | prints `"(unset — defaults to ~/.fleet for reads)"` | print the resolved root and its source |
| `fleet/it/lib.sh` | 46, 481 | watches `$HOME/.fleet/instants` as a leak destination | watch the derived root's store, or the check goes vacuous |

`scripts/claude-watchdog.sh:210` deserves the emphasis it has. Its comment says the `fleet` socket is
included by default rather than opt-in because *"an opt-in list is a list somebody forgets on the day it
matters."* Renaming the socket under it turns that default into a list of one wrong name — the `FI-421` class
exactly, in the file whose own comment predicts it.

`fleet/it/lib.sh:606-610` already refuses to report a pass over zero watched trees (*"zero watched trees is
not 'nothing changed', it is 'nothing was looked at'"*). That guard is what will catch a botched migration of
line 481, so it must not be weakened while line 481 is edited.

## Testing

**Hermetic** (`fleet/tests/`): the resolution chain is a pure function of `(flags, env, cwd, disk)` and gets
a table-driven test with one case per tier plus the refusal, including the `$HOME/.fleet-root` directed
refusal and the walk stopping at `$HOME`.

**Integration** — a new IT section with two marked roots side by side:

| case | asserts |
|---|---|
| R1 | dispatch in each root; the two stores are disjoint on disk |
| R2 | the two tmux servers are disjoint; a session name present in both resolves to its own root's pane |
| R3a | `dispatch` from root A with `--instants-dir` into root B's tree **refuses**, naming both (G1) |
| R3b | a record whose stamped root differs from the active root **refuses** — built by copying a record from B's store into A's, which is the only way to reach this state |
| R4 | `fleet enroll` of a workspace outside the root **refuses** (G3) |
| R5 | from an unmarked directory, a **read-only** verb refuses rather than reading a shared store |
| R6 | with `home` derived and no instants named, `dispatch` refuses instead of writing `$FLEET_HOME/instants` |
| R7 | every tier-1 and tier-3 invocation resolves exactly as it does today (regression) |

R3a, R4, R5 and R6 all have known-bad inputs available today, so each is written **red first** and shown to
fail before the fix exists. R3b has to be constructed, and the construction is the point: if a copied record
is the only way to reach that state, the guard is cheap insurance rather than a live defence, and the spec
should not imply otherwise.

R7 is the case that matters most for confidence and the one most likely to be skipped: it is what proves the
1291 explicit call sites did not move.

## What this deliberately does not do

- **`SI-51` … `SI-56`** — the six live fleet defects measured while mining the coordinator's register
  (`abort` not disowning a milestone; `seed-check` calling a healthy worker foreign; no `--seed-extra`;
  `pane-guard` keyed on `--pane`; no positive channel for a send-keys delivery; and `SI-56` itself). Only
  `SI-56` is touched here, and only because deleting the instants fallback closes it for free. The rest stay
  queued.
- **The script-offload shortlist** — `fleet lint --carry-across` and the rest. Separate work, after this
  lands.
- **A box-wide concurrency ceiling.** Pools are fully per-root with no shared cap, chosen deliberately. The
  consequence accepted: two roots each capping at 3 workers can put 6 concurrent sessions on one box, and
  nothing enforces a total. If that bites, it is a new decision, not a defect in this one.
- **Rewriting the coordinator's own `tools/`.** `FI-421` records ~10 further `ws3` path literals in
  `coordinator-checks.sh`. Those live in an instant, not in this repository.
