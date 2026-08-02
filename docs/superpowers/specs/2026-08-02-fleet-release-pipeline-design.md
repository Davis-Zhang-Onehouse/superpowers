# Fleet Release Pipeline — Design

**Date:** 2026-08-02
**Status:** approved in brainstorm, ready for an implementation plan

## Goal

Give the fleet infrastructure a release pipeline: every release carries a version tag and a changelog of
the commits since the previous release; deployment and rollback are one command each and are recorded with
a timestamp and a reason; and no version becomes deployable until the hermetic suite and the IT suite have
both run green against that exact artifact.

## Why this is not just `git tag`

Three properties of this repository shape every decision below. Each was verified, not assumed.

**1. The working tree is production.** `davis_root/.claude/settings.json` registers
`/home/ubuntu/davis_root/superpowers` as a live local-marketplace plugin (`superpowers-dev`),
`scripts/fleet-env.sh` puts its `bin/` on `PATH` for every `davis_root` shell, and `bin/fleet` resolves the
`fleet` package from its own location. There is no separation between editing and running: saving `cli.py`
changes the tool that every live dispatched instant invokes on its next call. Closing that gap is the
substance of this work; tagging is the easy part.

**2. The branch is rebased on a schedule.** `davis_root/.superpowers-sync/sync.sh` runs from cron at 03:30
daily and rebases `live` onto each new upstream release (most recently onto `v6.2.0`, manual-resolved, on
2026-07-30). This fork carries 272 commits on top. A rebase rewrites every one of those hashes, so a
release tag survives as an object but stops being an ancestor of `live` — and `git log <lastTag>..HEAD`
silently returns the wrong set from that moment on. Any delta computation has to be rebase-proof.

**3. Two tag namespaces are already occupied.** `v4.0.3`…`v6.2.0` are upstream superpowers releases;
`snapshot/*` belongs to the fork-sync tool. `scripts/bump-version.sh` and `.version-bump.json` govern the
*plugin* version (`package.json` is at `6.2.0`) and are upstream's mechanism. This pipeline uses a
disjoint namespace and does not touch any of them.

Sizing, for the record: the tracked tree is 403 files / 4.9 MB. (`fleet/` measures 71 MB on disk, but that
is untracked IT output and `__pycache__`.) Releases are therefore built with `git archive`, never a
directory copy.

## Decisions

| Decision | Choice |
|---|---|
| What a deploy moves | An immutable exported directory per version, selected by a `current` symlink |
| When a version may exist | Cut immediately as a CANDIDATE; promote to RELEASED only on green evidence |
| What the artifact contains | The whole tracked tree, including `skills/` and the plugin surface |
| Live editing | `deploy --dev` points `current` at the git checkout, through the same one mechanism |
| Version scheme | Manual semver; tags `fleet/vX.Y.Z`; `fleet.__version__` is the single source of truth |
| Delta computation | `git cherry -v` (patch-id), so a rebase cannot corrupt a changelog |
| IT isolation | Classify the live-session delta on this box; do not containerise and lose the real-box assertions |
| IT coverage | Two tiers: the 11-runner gate set every release, all 19 for a minor or major bump |

## Architecture

### Layout

```
/home/ubuntu/davis_root/fleet-releases/          # $FLEET_RELEASES
  current -> fleet-v0.1.0/                       # the one pointer every consumer follows
  RELEASE-HISTORY.tsv                            # append-only; every deploy and rollback
  .lock/                                         # mkdir-lock for mutating verbs
  fleet-v0.1.0/                                  # immutable export, chmod -R a-w after build
    .release/
      MANIFEST.tsv
      CHANGELOG.md                               # this release's section only
      STATE                                      # CANDIDATE | RELEASED
      evidence/
        hermetic.log
        it-RESULTS.tsv
        it-FULL-RUN.log
        source-pin-before.txt
        source-pin-after.txt
        live-subjects-before.tsv
        live-subjects-after.tsv
        VERDICT.tsv
    bin/ fleet/ skills/ scripts/ hooks/ commands/ .claude-plugin/ …
  fleet-v0.2.0/
```

### Who follows `current`

Exactly two consumers are repointed, once:

- `scripts/fleet-env.sh` — the `PATH` entry becomes `$FLEET_RELEASES/current/bin` instead of the hardcoded
  repo `bin`.
- `davis_root/.claude/settings.json` — `extraKnownMarketplaces.superpowers-dev.source.path` becomes
  `/home/ubuntu/davis_root/fleet-releases/current`.

Nothing else in the system needs to know releases exist.

### A required fix to `bin/fleet`

`bin/fleet` currently computes its repo root with `cd "$(dirname "$_fleet_self")/.." && pwd`. `pwd` is
logical, so the result is `…/fleet-releases/current` — a path that is re-resolved on every file open. A
symlink flip during a long invocation could therefore hand one Python process modules from two different
releases. Changing to `cd -P` resolves the symlink once, pinning each invocation to one physical release
directory for its whole life. This is a one-line change, and the failure it prevents is only reachable
once deploys exist.

### Module decomposition

Small, single-responsibility modules, so git interaction can be faked in hermetic tests and so the
one-writer-per-file rule has clean boundaries.

| File | Responsibility | Depends on |
|---|---|---|
| `fleet/src/fleet/release.py` | The model: version parsing and ordering, release-directory layout, `MANIFEST.tsv` and `STATE` read/write, history append, `current` resolution and atomic flip. No git, no subprocesses. | `atomic.py` |
| `fleet/src/fleet/release_git.py` | Every git call: dirty-tree check, patch-id delta, changelog rendering, annotated tag, `git archive` export. | `subprocess`, `git` |
| `fleet/src/fleet/release_verify.py` | Runs the two suites against an export, captures evidence, computes the verdict. | `release.py` |
| `fleet/src/fleet/cli.py` | The `release` verb group: argument parsing, refusals, exit codes. | all three |
| `bin/fleet-view` | A `releases` view. Rendering only — reads `--porcelain`, computes nothing. | — |
| `scripts/fleet-env.sh` | Defaults `FLEET_RELEASES`; `PATH` via `current`. | — |
| `fleet/it/lib.sh` | `it_assert_isolation` classifies the live-session delta instead of comparing it. | — |
| `fleet/it/run-all.sh` | Two rosters — the gate set and `--full` — and a header that states the one it runs. | — |

## The release lifecycle

### `fleet release cut <version> [--notes <text>]`

Ordered so the changelog ships *inside* the artifact it describes.

1. **Refuse on a dirty tree** (exit 4). An export contains only committed content; a dirty tree means the
   thing tested is not the thing edited.
2. **Compute the delta.** The previous release is the highest `fleet/v*` tag in semver order, not the most
   recently created one — a tag created out of order must not silently redefine the delta.
   `git cherry -v <prev-tag> HEAD`, taking the `+` lines. Patch-id based, so a
   commit rewritten by the nightly rebase is still recognised as the same change. Verified against the
   live repo: of the 272 commits `live` carries over `v6.2.0`, `git cherry` marks 270 as `+` and 2 as
   already-present-upstream — the comparison is doing real work, not counting.
3. **Write the changelog.** Prepend the new section to `fleet/CHANGELOG.md` (cumulative, committed,
   newest-first). This file is distinct from the root `RELEASE-NOTES.md`, which is upstream's.
4. **Bump `fleet.__version__`** in `fleet/src/fleet/__init__.py` and commit both files as
   `fleet v<version>`.
5. **Tag** `fleet/v<version>`, annotated, with the changelog section as the message. The tag is not the
   deployed artifact, but it costs nothing and pins the exact tree against garbage collection, so any
   release stays recoverable after its commits are rewritten off the branch.
6. **Export** `git archive fleet/v<version>` into `$FLEET_RELEASES/fleet-v<version>/`, write
   `MANIFEST.tsv`, write `STATE=CANDIDATE`, then `chmod -R a-w` the export.

`MANIFEST.tsv` — one `key<TAB>value` pair per line:

```
version        0.1.0
tag            fleet/v0.1.0
source_commit  2faa525524d113e24f0a5363bf08128db0229dd8
source_branch  live
upstream_base  v6.2.0
tree_sha       <sha256 over sorted "mode path sha" of the exported tracked files>
cut_at         2026-08-02T14:22:11Z
cut_by         davis@onehouse.ai
notes          <--notes text, or ->
```

### `fleet release verify <version>`

Runs both suites **against the frozen export**. This is what makes contamination structurally impossible
rather than procedurally discouraged: nothing can edit the tree underneath the run.

- **Hermetic:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -q`, run
  inside the export's `fleet/` directory, captured to `evidence/hermetic.log`. The environment variable is
  load-bearing: the export is read-only and `__pycache__` writes would otherwise fail against our own
  artifact.
- **IT:** `fleet/it/run-all.sh` writes `RESULTS*.tsv` beside itself and so cannot run inside a read-only
  export. Rather than teach twenty runner scripts an output directory, `verify` copies the export to a
  scratch directory, runs there, and copies `RESULTS*.tsv` and the full-run log back into
  `evidence/`. It recomputes the scratch copy's `tree_sha` and compares it to `MANIFEST.tsv`, so the claim
  "what was tested is what shipped" is asserted rather than assumed.
### Two IT tiers

`run-all.sh`'s header says *"ONE validation run: every runner, sequentially"*, but its `RUNNERS` array
holds 11 of the 19 runners on disk — F, G, H, I, J, O, P and lineage are absent, with no comment saying
why. Prose and behaviour must agree before either can gate a release, so `run-all.sh` gains an explicit
second roster and a corrected header:

- **`run-all.sh`** — the 11-runner gate set. Run by `verify` for every release.
- **`run-all.sh --full`** — all 19. Required by `promote` for a **minor or major** version bump; optional
  for a patch.

The `--full` roster cannot be assembled by assumption. The plan's first step here is to determine, per
excluded runner, why it is excluded and whether it is unattended-safe. **§P is the real-`claude` tier**: it
spends the account's usage allowance and depends on the identity pinning established in
`fleet-dispatch-launcher.sh`. Any runner that invokes real `claude` sits behind an explicit opt-in within
`--full` rather than running by default, because a release gate that silently consumes a weekly limit is a
gate nobody will keep using. Whatever the answer per runner, it gets written into the header — an
undocumented exclusion is how this discrepancy arose in the first place.

### Isolation, and why the baseline is fixed rather than escaped

The IT suite asserts against the **real box** on purpose: `lib.sh` hashes the operator's
`~/.claude-dispatch-board` and `~/.claude-ws-pool`, lists the **default** tmux server's sessions, and
`run-A.sh`'s `A1c` asserts that the operator's real `~/.fleet` is unchanged across the probe. Running the
suite in a container would make every one of those pass against an empty box — green for the wrong reason,
wearing the release gate's badge. So the baseline is made precise instead of being escaped.

Of the two baselines, only the tmux session list moves under normal operation; the store hashes change
only if something writes those legacy stores, which is a genuine finding rather than noise.
`it_assert_isolation` therefore **classifies** the session delta instead of comparing it for equality:

| Observation | Treatment |
|---|---|
| A session appeared whose name matches an IT prefix (`$TMUX_PREFIX`, `itfleet-*`) | **LEAK — hard FAIL** |
| A `dt-` session the suite itself created is missing | **hard FAIL** (the suite killed live work) |
| A `dt-` session the suite never named appeared or disappeared | operator activity — recorded as a note |
| A store hash changed | **hard FAIL** |

The suite already writes `dt-sessions-seen*.txt`, so it knows which names were its own. This is strictly
stronger than what it replaces: today "your coordinator finished normally" and "the suite killed a live
session" produce the identical signal, and the second is the event the check exists to catch.

`verify` also captures `fleet board --porcelain` before and after into `live-subjects-{before,after}.tsv`.

**Verdicts** are written to `evidence/VERDICT.tsv` as `suite<TAB>verdict<TAB>evidence<TAB>note`, with the
exact roster of sections run recorded alongside, so a release states its own coverage rather than implying
it:

| Verdict | Meaning |
|---|---|
| GREEN | Both suites passed. |
| RED | A suite failed with no concurrent operator activity recorded. |
| INCONCLUSIVE | A suite failed *and* operator activity was recorded during the run. |

With classification in place the isolation assertion itself no longer fires spuriously, so INCONCLUSIVE
becomes rare rather than routine — but it stays, because a functional section that fails while the box was
busy is still not attributable to HEAD with confidence. That is the source-pin doctrine applied to the one
baseline the suite cannot own: contamination is never a verdict. It costs a re-run and never a false record.

`verify` **warns** on a busy box; it does not refuse. Refusing would make releases impossible during normal
operation, which here is most of the time. Exit code is 0 for GREEN, 1 for RED or INCONCLUSIVE.

### `fleet release promote <version>`

Refuses (exit 4) unless `evidence/VERDICT.tsv` exists and records GREEN for both suites. On success writes
`STATE=RELEASED`. `promote` never runs tests — it only reads the evidence `verify` left.

It additionally compares the version being promoted with the previous release: a **minor or major** bump
requires evidence from a `--full` run, and `promote` refuses a minor or major whose recorded roster is the
gate set. A patch bump promotes on the gate set. This is the one place the two tiers are enforced, so the
tier policy lives in exactly one function rather than in an operator's memory.

### `fleet release deploy <version>` / `fleet release deploy --dev` `[--reason <text>]`

Flips `current` and appends one line to `RELEASE-HISTORY.tsv`.

- Refuses a CANDIDATE (exit 4) unless `--force`, and `--force` requires `--reason` — deploying untested
  code is exactly the event the history file exists to explain.
- Prints the currently RUNNING subjects before flipping, so waiting is a choice you make rather than a
  consequence you discover.
- `--dev` points `current` at `/home/ubuntu/davis_root/superpowers` — the git checkout — restoring live
  editing of skills and code through the same one mechanism. Recorded with `action=DEV`.
- The flip is `ln -s <target> current.tmp && mv -T current.tmp current`. `ln -sfn` is not atomic and would
  leave a window in which `current` does not exist, and every `davis_root` shell's `PATH` points through
  it.

### `fleet release rollback [--to <version>] --reason <text>`

Mechanically the same flip, recorded as `action=ROLLBACK`. `--reason` is **required** (exit 4 without it) —
the reason is the whole point of the history file. `--to` defaults to the previously-deployed version,
read from the history file's most recent `from_version`.

### Read-only verbs

`status` (what is live, its state, when it was deployed, by whom, and why), `list` (versions, states, cut
dates, sizes, and which one `current` points at), `history [-n N]`. Each supports `--porcelain`.

In `--dev` mode, `status` additionally prints the checkout's `HEAD` and whether it is dirty, because "what
is live" is a moving target in that mode and reporting only `DEV` would be true about the pointer and
misleading about the code.

## The history file

`RELEASE-HISTORY.tsv`, append-only, tab-separated, with a header line:

```
ts	action	version	from_version	actor	host	reason	evidence
2026-08-02T14:40:02Z	DEPLOY	0.1.0	DEV	davis@onehouse.ai	ip-10-0-1-23	first real release	fleet-v0.1.0/.release/evidence
2026-08-02T15:12:55Z	ROLLBACK	0.0.9	0.1.0	davis@onehouse.ai	ip-10-0-1-23	harvest wedged on a leased slot	fleet-v0.0.9/.release/evidence
```

- `action` ∈ `DEPLOY` | `ROLLBACK` | `DEV`.
- It records **transitions, not states**. `from_version` is what makes "roll back to whatever we were on"
  answerable and what lets the timeline be reconstructed afterwards; a file of states alone cannot say what
  a rollback rolled back *from*.
- `actor` is `CLAUDE_OWNER_EMAIL` when set, else `$USER` — this is a shared box and the identity work
  already established that the owning account is worth pinning explicitly.
- Appends go through `atomic.py`, under the same lock as the flip.

Rendering is separate from the record, following the split already used for `board` and `leases`:
`fleet release history --porcelain` emits the TSV; `fleet-view releases` renders it in **list** form, not a
table, so a long `reason` is never truncated.

## Refusals and exit codes

Reusing the existing registry — no new codes.

| Code | Situation |
|---|---|
| 0 | ok |
| 1 | `verify` returned RED or INCONCLUSIVE |
| 2 | malformed version string; unknown version; unreadable release directory |
| 4 | dirty tree at `cut`; `promote` without GREEN evidence; `deploy` of a CANDIDATE without `--force`; `rollback` without `--reason`; `FLEET_RELEASES` unset for a mutating verb; a mutating verb invoked from a package that resolves inside `$FLEET_RELEASES` |

That last refusal carries real weight. **The tool that manages `current` must not be the thing `current`
points at** — otherwise rolling back to a version whose release code has a bug also rolls back your ability
to roll forward. Mutating verbs therefore refuse unless invoked from the git checkout; read-only verbs work
from anywhere, matching fleet's existing read-only/mutating split.

`FLEET_RELEASES` is defaulted in `fleet-env.sh` and refused-if-unset in the CLI, exactly as `FLEET_HOME` is
— a mutating verb with no named store refuses rather than inventing one.

## Concurrency

Two shells on this box can plausibly cut and deploy at the same time, so `cut`, `verify`, `promote`,
`deploy` and `rollback` all take `$FLEET_RELEASES/.lock/` for their duration. `mkdir` **is** the lock — the
same idiom the rest of fleet uses, because it is the one filesystem primitive that is atomic and
self-cleaning to reason about. The lock directory holds a `holder` file naming the pid, the verb and the
start time, so a stale lock can be identified rather than guessed at; a mutating verb that cannot take the
lock reports the holder and exits 4. Read-only verbs never take it.

The lock covers the history append as well as the flip, so the ordering of `RELEASE-HISTORY.tsv` always
matches the ordering of the flips it describes.

## Accepted limitations

Written down rather than papered over.

- **An instant can straddle a deploy.** A running `fleet` process is pinned by `cd -P`, but the instant's
  *next* invocation gets the new version. Any store-format change must be called out in the release notes;
  `deploy` printing the RUNNING subjects is the mitigation, and it is a prompt, not a guarantee.
- **Skills and binaries can skew.** Skills load at session start, so a long-lived instant can run new
  binaries against prose it loaded hours ago. The model does not fix this; `status` at least makes the
  deployed version nameable when the two disagree.
- **No prune verb.** At ~5 MB a release it is not worth the code. `list` marks the directory `current`
  points at; deleting any other by hand is safe.
- **`verify` is not CI.** There is no build server here; it runs on this box, when invoked, and its
  isolation caveat is the price of that.

## Testing

**Hermetic** — `fleet/tests/test_release.py`, run against a temporary git repository built by the fixture,
with `FLEET_RELEASES` pointed at a temp directory:

- the delta is correct across a *synthetic rebase* (rewrite the fixture's history, assert the patch-id
  delta is unchanged where `git log A..B` would be wrong);
- the changelog header names the rebase when the previous tag is no longer an ancestor;
- the first release omits the commit list and records its source commit;
- `cut` refuses a dirty tree;
- a mutating verb refuses when its package resolves inside `$FLEET_RELEASES`;
- a mutating verb refuses when `FLEET_RELEASES` is unset;
- `promote` refuses a candidate whose verdict is absent, RED, or INCONCLUSIVE;
- `deploy` refuses a CANDIDATE without `--force`;
- `rollback` refuses without `--reason`, and defaults `--to` to the previous `from_version`;
- a mutating verb refuses with exit 4 when the lock is held, and names the holder;
- the flip never leaves `current` absent (assert by racing a reader against the flip);
- concurrent history appends produce two well-formed lines, not one interleaved line;
- `verify` returns INCONCLUSIVE, not RED, when a suite fails and operator activity was recorded;
- `promote` refuses a minor or major bump whose evidence records only the gate roster, and accepts the same
  evidence for a patch bump.

Every one of these must be shown to fail with the implementation reverted before it counts.

**The IT harness change needs its own tests, with a negative control.** `it_assert_isolation` is the thing
every other section's verdict rests on, and loosening it is exactly the change that could quietly stop
protecting anything. Against a scratch tmux server:

- a session appearing that matches an IT prefix still produces a hard FAIL — this is the negative control,
  and without it the whole classification change is unfalsifiable;
- a `dt-` session the suite created and then lost still produces a hard FAIL;
- a `dt-` session the suite never named, appearing or disappearing, produces a note and not a failure;
- a changed store hash still produces a hard FAIL;
- the establishing (first) call still reports SKIP, not PASS, because it compared nothing.

**Integration** — one new section, `fleet/it/run-Q.sh`, added to `run-all.sh`: a real
cut → verify → promote → deploy → rollback against a throwaway git clone and a throwaway releases root,
asserting that the deployed `current/bin/fleet` reports the deployed version and that the history file
records both transitions. It must obey the existing isolation contract (`it_assert_isolation`) like every
other section.

## Bootstrapping

Ordered so that repointing the consumers changes nothing observable, and the first real release is a
separate, reversible step.

1. Create `$FLEET_RELEASES` and point `current` at the git checkout (DEV).
2. Repoint `fleet-env.sh`'s `PATH` entry and `settings.json`'s marketplace path at `current`. Confirm a
   **fresh** Claude session still loads the skills — the plugin cache is a copy, so this only takes effect
   in a new session.
3. Read `davis_root/.superpowers-sync/sync.sh` and `bootstrap.sh` for their plugin-refresh step; it may
   assume the marketplace path is the repository. Adjust it if so. Releases themselves are exported copies
   and cannot be disturbed by a rebase.
4. Cut `fleet/v0.1.0` from the current tree — no predecessor, so the changelog records its source commit
   and omits the list. `verify`, `promote`, `deploy`.
5. Confirm `fleet release status` names `0.1.0` and that `fleet --help` still works from a fresh shell.

## Out of scope

Pruning old releases; multi-machine distribution; artifact signing; extracting `fleet/` into a standalone
repository or publishing it to PyPI; automatic cutting on a schedule or from a hook. Each is a separate
project, and none is needed for the pipeline to be useful.

**Containerising the IT suite** is deliberately deferred rather than rejected. It would give deterministic
isolation, but it cannot host the real-box assertions — those would need a seeded synthetic dispatch board,
ws-pool and decoy `dt-` sessions to guard anything at all, and a fixture that drifts from the real thing
fails silently. It also needs an image carrying an authenticated `claude` for the sections that invoke it,
and the `/proc` cwd-holder probe (OBS-48) that guards `reap` and `harvest` behaves differently under a PID
namespace. On this box the docker daemon is not running and neither podman nor bwrap is installed, though
`unshare` and unprivileged user namespaces are available. Revisit if classification proves insufficient;
the right shape would be containerised functional sections with the real-box assertions kept outside, on
the host.

## Acceptance criteria

1. `fleet release cut <v>` on a clean tree produces a read-only export, an annotated `fleet/v<v>` tag, a
   `CHANGELOG.md` section listing `<githash> <title>` for every commit since the previous release, and
   `STATE=CANDIDATE`; on a dirty tree it refuses with exit 4 and creates nothing.
2. The changelog delta is provably unchanged when the branch is rebased between two releases.
3. `fleet release verify <v>` runs both suites against the export, leaves evidence under
   `.release/evidence/`, and returns GREEN, RED, or INCONCLUSIVE per the rules above.
4. `fleet release promote <v>` succeeds only on GREEN evidence.
5. `fleet release deploy <v>` flips `current` atomically, refuses a CANDIDATE without `--force`, and
   appends a `DEPLOY` line; `rollback --reason` appends a `ROLLBACK` line and refuses without a reason.
6. `fleet release deploy --dev` restores live editing, and `status` then reports the checkout's HEAD and
   dirty state.
7. A mutating verb invoked from inside `$FLEET_RELEASES` refuses with exit 4.
8. `it_assert_isolation` classifies the session delta: an IT-prefixed session appearing is still a hard
   FAIL (shown by a negative control), while a `dt-` session the suite never named is a note.
9. `run-all.sh` runs a documented roster, `run-all.sh --full` runs all 19 with any real-`claude` runner
   behind an explicit opt-in, and `promote` refuses a minor or major bump that has only gate-set evidence.
10. The hermetic suite and `run-Q.sh` both pass, and each new hermetic test has been shown to fail with its
    implementation reverted.
