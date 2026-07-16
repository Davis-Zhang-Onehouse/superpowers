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
     build-*decision* files are text). Binaries keep their embedded source paths.
     Those are debug-info **except** the final `.so`'s `DT_RUNPATH` (e.g.
     `libvelox.so`'s runpath that locates `libhudi.so`), which is *functional* —
     it survives only because `$ORIGIN` leads the runpath and `libhudi.so` is
     copied alongside it. For a guaranteed-clean runpath, prefer same-length
     names (or run `patchelf --set-rpath` afterward). The script warns in this
     case.
5. **Freshen mtimes** — touches copied+repathed artifacts so cmake/cargo/maven
   treat them as up-to-date and incremental builds are no-ops.

## Notes / constraints

- Does **not** use `rsync`/`scp`/`curl`/`ssh` (blocked in this environment) — uses
  `cp -a` and git's local-path fetch.
- Only committed state is replicated (branch + commit). Uncommitted working-tree
  changes in the source are not copied.
- Only **release** builds are copied; debug trees (huge) are intentionally skipped.
- The repath step (4) is what makes the copied cmake cache / cargo / ninja
  metadata and the native `libhudi.so` toolchain point at the **target**, not the
  source. Prefer same-length workspace names (`ws1`/`ws2`/`ws3`) so the byte-safe
  rewrite covers binaries too.
