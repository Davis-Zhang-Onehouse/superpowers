---
name: duplicateWorkSpace
description: Use when the user wants to duplicate/clone/mirror a hudi-internal / gluten-velox / hudi-rs workspace to a second folder to work on another issue in parallel — makes the target repos check out the same branch+commit as the source and copies the already-built RELEASE build artifacts so nothing has to be rebuilt. Triggers on "duplicate workspace", "copy my workspace", "mirror ws1 to ws2", "set up a parallel workspace without rebuilding".
---

# Duplicate Workspace

Make a **target** workspace match a **source** workspace for the gluten-velox /
hudi-rs / hudi-internal setup: identical branch + commit per repo, plus the
already-built **release** artifacts copied over so the target needs no rebuild.

## When to use

The user keeps a workspace (e.g. `~/ws1`) with these repos built, and wants a
second workspace (e.g. `~/ws2`) to work on a different issue in parallel without
re-running the slow velox / gluten native builds or the hudi-rs Rust build.

## Prerequisite

The **source** folder must contain the repos as built git clones. The **target**
folder is created if missing, and any repo absent from the target is cloned from
the source's on-disk copy (fast, hardlinked, carries local-only commits), with its
`origin` repointed to the source's real remote URL. Repos already present in the
target are re-pointed to the source's commit in place.

## Usage

```bash
# on PATH via the repo's bin/ (or call ./duplicate-workspace.sh in this skill dir)
duplicate-workspace <source_dir> <target_dir> [--force] [--no-artifacts] [--dry-run]
```

- `--force` — proceed even if a target repo has **uncommitted** changes
  (default: abort and list them, so you never silently clobber work).
- `--no-artifacts` — sync git only; skip copying build artifacts.
- `--dry-run` — print the per-repo branch/hash and artifact sizes; change nothing.

**Always run `--dry-run` first** and show the plan before the real run — the real
run switches the target repos' branches and overwrites the target's build
artifacts.

## What it does

Repos handled (skipped if absent on either side): `gluten-internal`,
`velox-internal`, `hudi-internal`, `hudi-rs-internal`.

0. **Create/clone** — creates the target folder if missing; clones any repo absent
   from the target from the source's on-disk path (hardlinked objects, no network,
   carries local-only commits), then repoints `origin` to the source's real URL.
1. **Preflight** — reads source branch+hash per repo; warns if source is dirty
   (uncommitted changes are *not* replicated); aborts if any *existing* target repo
   is dirty unless `--force` (freshly-cloned repos are always clean).
2. **Git sync** — fetches the source repo's commits from its on-disk path (local
   transport, no network — works for local-only commits) and `checkout -B` the
   same branch at the same hash. Asserts the target HEAD matches.
3. **Release artifacts** (`cp -a`, mirroring each item):
   - `velox-internal`: `_build/release` (debug is skipped)
   - `gluten-internal`: `cpp/build` native libs + every maven `*/target`
   - `hudi-rs-internal`: `target/release` + `target/cxxbridge` + `CACHEDIR.TAG`
   - `hudi-internal`: every maven `*/target`
4. **Repath** — rewrites baked-in **absolute source paths** (`<source_dir>` →
   `<target_dir>`) inside the copied trees. Build tools hardcode absolute paths in
   their metadata — cmake `CMakeCache.txt`/`build.ninja`/`*.make` (incl.
   `VELOX_BUILD_PATH`, `HUDI_RS_DIR`, `*_SOURCE_DIR`/`*_BINARY_DIR`), cargo `.d` &
   `.fingerprint` files, `compile_commands.json`, `*.pc`. Copied verbatim these
   still point at the *source* workspace, so an incremental rebuild in the target
   would reach back into the source tree (and gluten's native build would source
   `libhudi.so` from the source's `HUDI_RS_DIR`). Because the repo layout under
   each workspace root is identical, replacing the root string covers every
   subpath.
   - **Same-length roots** (e.g. `ws2` → `ws3`, both 16 bytes): a byte-for-byte,
     size-preserving rewrite is applied to **every** file, binaries included
     (ELF/rlib debug paths, the binary `.ninja_deps`, cargo fingerprints) — no
     corruption possible.
   - **Different-length roots**: only **text** files are rewritten (all
     build-*decision* files are text). Binaries keep their embedded source paths —
     these are **debug-info only** (cosmetic). The one *functional* binary
     reference, each final `.so`'s `DT_RUNPATH`, is handled by step 5 below, so
     name length no longer matters for a self-contained copy.
5. **Normalize `.so` runpaths (`$ORIGIN`)** — rewrites every copied final `.so`'s
   `DT_RUNPATH` so it is self-contained: the `.so`'s own build dir → `$ORIGIN`,
   and any source-tree cross-reference → `$ORIGIN/<rel>`. This removes the baked-in
   **absolute** runpath — which points at the build dir the `.so` was *linked* in
   (often a **third** workspace, e.g. the golden the source was itself duplicated
   from), so without this the copy silently depends on that path still existing and
   breaks if it is deleted/re-leased. Runs for **both** same- and different-length
   roots (the runpath may point at neither source nor target). Needs no
   `patchelf`/`chrpath` — it shortens the runpath string in place, NUL-padded
   (offsets/sizes unchanged, exactly like `chrpath`); uses `patchelf` when present
   for the rare case where the new runpath is longer, and otherwise prints the exact
   `patchelf` command to run.
6. **Freshen mtimes** — touches copied+repathed artifacts so cmake/cargo/maven
   treat them as up-to-date and incremental builds are no-ops.

## Notes / constraints

- Does **not** use `rsync`/`scp`/`curl`/`ssh` (blocked in this environment) — uses
  `cp -a` and git's local-path fetch.
- Only committed state is replicated (branch + commit). Uncommitted working-tree
  changes in the source are not copied.
- Only **release** builds are copied; debug trees (huge) are intentionally skipped.
- The repath step (4) is what makes the copied cmake cache / cargo / ninja
  metadata and the native `libhudi.so` toolchain point at the **target**, not the
  source. Same-length workspace names (`ws1`/`ws2`/`ws3`) let that byte-safe rewrite
  also clean binary **debug-info** paths — cosmetic. It is **not** required for
  correctness: the one functional binary reference (each `.so`'s `DT_RUNPATH`) is
  normalized to `$ORIGIN` in step 5 regardless of name length, so a different-length
  duplicate (e.g. `wsgold` → `ws5`) is still a self-contained, load-correct copy.
