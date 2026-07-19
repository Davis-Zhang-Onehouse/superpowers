#!/usr/bin/env bash
#
# duplicate-workspace.sh
#
# Make a target workspace match a source workspace for the hudi-internal /
# gluten-velox / hudi-rs setup: same branch + commit for each repo, plus the
# already-built RELEASE artifacts copied over so nothing has to be rebuilt.
#
# The target folder is created if missing, and any repo not yet present in the
# target is cloned from the source's on-disk copy (then origin is repointed to
# the source's real remote URL).
#
# Usage:
#   duplicate-workspace.sh <source_dir> <target_dir> [--force] [--no-artifacts] [--dry-run]
#
#   --force         proceed even if a target repo has uncommitted changes
#   --no-artifacts  sync git only, skip build-artifact copy
#   --dry-run       print the plan; change nothing
#
# Notes:
#   * rsync/scp/curl/wget/ssh are intentionally NOT used (blocked in this env).
#     Git objects are fetched from the source's on-disk copy (local transport,
#     no network) so even local-only commits transfer. Artifacts use `cp -a`.
#   * Only committed state is replicated. Uncommitted source changes are NOT
#     copied (a warning is printed).
#   * Build tools bake ABSOLUTE source paths into their metadata (cmake
#     CMakeCache.txt/build.ninja/*.make, cargo .d & .fingerprint,
#     compile_commands.json, *.pc). After copying, those are rewritten
#     SRC->DST so an incremental rebuild in the target does NOT reach back
#     into the source tree (and native libs like libhudi.so aren't sourced
#     from the source's HUDI_RS_DIR). Same-length workspace paths (e.g.
#     ws2->ws3) are rewritten byte-safe across ALL files, binaries included;
#     different-length paths rewrite TEXT files, then Phase 3b normalizes each
#     copied .so's DT_RUNPATH to $ORIGIN so the copy is self-contained (no
#     dependency on the source/golden absolute path) regardless of name length.
#
set -euo pipefail

# ---- known repos ------------------------------------------------------------
REPOS=(gluten-internal velox-internal hudi-internal hudi-rs-internal)

# ---- args -------------------------------------------------------------------
SRC=""
DST=""
FORCE=0
NO_ARTIFACTS=0
DRY_RUN=0

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-2}"
}

POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --force)        FORCE=1 ;;
    --no-artifacts) NO_ARTIFACTS=1 ;;
    --dry-run)      DRY_RUN=1 ;;
    -h|--help)      usage 0 ;;
    --*)            echo "ERROR: unknown option: $arg" >&2; usage 2 ;;
    *)              POSITIONAL+=("$arg") ;;
  esac
done

if [ "${#POSITIONAL[@]}" -ne 2 ]; then
  echo "ERROR: expected <source_dir> and <target_dir>" >&2
  usage 2
fi

SRC="${POSITIONAL[0]}"
DST="${POSITIONAL[1]}"

[ -d "$SRC" ] || { echo "ERROR: source dir not found: $SRC" >&2; exit 2; }

# absolute paths (git local-fetch and cp need them unambiguous).
# Source must exist; target may not yet — resolve it logically either way.
SRC="$(cd "$SRC" && pwd)"
DST="$(realpath -m "$DST")"

if [ "$SRC" = "$DST" ]; then
  echo "ERROR: source and target are the same directory" >&2
  exit 2
fi

# Create the target folder if it does not exist (skipped under --dry-run).
if [ ! -d "$DST" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "(dry-run) target dir does not exist; would create: $DST"
  else
    mkdir -p "$DST"
    echo "created target dir: $DST"
  fi
fi

# ---- helpers ----------------------------------------------------------------
c_bold=$'\033[1m'; c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_rst=$'\033[0m'
info()  { printf '%s\n' "$*"; }
step()  { printf '%s==> %s%s\n' "$c_bold" "$*" "$c_rst"; }
warn()  { printf '%sWARN:%s %s\n' "$c_yel" "$c_rst" "$*" >&2; }
err()   { printf '%sERROR:%s %s\n' "$c_red" "$c_rst" "$*" >&2; }
ok()    { printf '%s  ok:%s %s\n' "$c_grn" "$c_rst" "$*"; }

is_git()   { git -C "$1" rev-parse --git-dir >/dev/null 2>&1; }
cur_hash() { git -C "$1" rev-parse HEAD; }
cur_branch() { git -C "$1" rev-parse --abbrev-ref HEAD; }
is_dirty() { [ -n "$(git -C "$1" status --porcelain 2>/dev/null)" ]; }
dsize()    { local x; x="$( { du -sh "$1" 2>/dev/null || true; } | cut -f1)"; echo "${x:-?}"; }
# in_list <needle> <haystack...> — is needle present in the remaining args?
in_list()  { local n="$1"; shift; local x; for x in "$@"; do [ "$x" = "$n" ] && return 0; done; return 1; }

# ---- artifact item resolution ----------------------------------------------
# Echo the list of source-relative artifact items for a repo (one per line).
artifact_items() {
  local repo="$1" s="$SRC/$repo"
  case "$repo" in
    velox-internal)
      [ -d "$s/_build/release" ] && echo "_build/release"
      ;;
    gluten-internal)
      [ -d "$s/cpp/build" ] && echo "cpp/build"
      # maven target dirs at any module depth; skip the cpp native tree and
      # any target nested inside another target.
      while IFS= read -r t; do
        echo "${t#$s/}"
      done < <(find "$s" -type d -name target -not -path "*/target/*" -not -path "*/cpp/*" 2>/dev/null | sort)
      ;;
    hudi-rs-internal)
      [ -d "$s/target/release" ]   && echo "target/release"
      [ -d "$s/target/cxxbridge" ] && echo "target/cxxbridge"
      [ -f "$s/target/CACHEDIR.TAG" ] && echo "target/CACHEDIR.TAG"
      ;;
    hudi-internal)
      # maven target dirs at any module depth; skip any target nested inside
      # another target.
      while IFS= read -r t; do
        echo "${t#$s/}"
      done < <(find "$s" -type d -name target -not -path "*/target/*" 2>/dev/null | sort)
      ;;
  esac
}

plan_artifacts() {
  local repo="$1" s="$SRC/$repo" item
  local any=0
  while IFS= read -r item; do
    [ -z "$item" ] && continue
    any=1
    info "  $repo: $item ($(dsize "$s/$item"))"
  done < <(artifact_items "$repo")
  if [ "$any" -eq 0 ]; then info "  $repo: (no release artifacts found in source)"; fi
}

# repos we will actually process (present + git in source)
ACTIVE=()
# repos missing from the target that we will clone from source
TO_CLONE=()

step "Duplicate workspace"
info "  source: $SRC"
info "  target: $DST"
info "  flags : force=$FORCE no-artifacts=$NO_ARTIFACTS dry-run=$DRY_RUN"
echo

# ---- Phase 0: preflight -----------------------------------------------------
step "Phase 0: preflight"
DIRTY_TARGETS=()
for repo in "${REPOS[@]}"; do
  s="$SRC/$repo"; d="$DST/$repo"
  if [ ! -d "$s" ] || ! is_git "$s"; then
    warn "skip $repo: not a git repo in source"
    continue
  fi
  ACTIVE+=("$repo")

  sbranch="$(cur_branch "$s")"; shash="$(cur_hash "$s")"
  info "  $repo: source ${sbranch} @ ${shash:0:12}"
  if is_dirty "$s"; then
    warn "  $repo: SOURCE has uncommitted changes (NOT replicated — committed hash only)"
  fi

  if [ ! -d "$d" ] || ! is_git "$d"; then
    TO_CLONE+=("$repo")
    info "  $repo: TARGET missing — will clone from source"
  elif is_dirty "$d"; then
    DIRTY_TARGETS+=("$repo")
    warn "  $repo: TARGET has uncommitted changes"
  fi
done

if [ "${#ACTIVE[@]}" -eq 0 ]; then
  err "no source git repos to process"
  exit 1
fi

if [ "${#DIRTY_TARGETS[@]}" -gt 0 ] && [ "$FORCE" -eq 0 ]; then
  err "target repos with uncommitted changes: ${DIRTY_TARGETS[*]}"
  err "commit/stash them, or re-run with --force to overwrite."
  exit 1
fi
echo

if [ "$DRY_RUN" -eq 1 ]; then
  step "Phase 1 (dry-run): git sync plan"
  for repo in "${ACTIVE[@]}"; do
    s="$SRC/$repo"
    action="checkout"
    if [ "${#TO_CLONE[@]}" -gt 0 ] && in_list "$repo" "${TO_CLONE[@]}"; then action="clone +checkout"; fi
    info "  $repo -> $action $(cur_branch "$s") @ $(cur_hash "$s" | cut -c1-12)"
  done
  if [ "$NO_ARTIFACTS" -eq 0 ]; then
    echo
    step "Phase 2 (dry-run): artifact copy plan"
    for repo in "${ACTIVE[@]}"; do
      plan_artifacts "$repo"
    done
    echo
    step "Phase 3 (dry-run): repath plan"
    if [ "${#SRC}" -eq "${#DST}" ]; then
      info "  rewrite $SRC -> $DST in copied trees (byte-safe, all file types)"
    else
      info "  rewrite $SRC -> $DST in copied trees (TEXT files only; lengths differ ${#SRC} vs ${#DST})"
    fi
    echo
    step "Phase 3b (dry-run): normalize .so runpaths"
    info "  rewrite each copied final .so's DT_RUNPATH to \$ORIGIN (self-contained; byte-safe, no patchelf needed)"
  fi
  echo
  info "dry-run complete; nothing changed."
  exit 0
fi

# ---- Phase 1: git sync ------------------------------------------------------
FAILED=()
SYNCED=()
COPIED_TREES=()   # dest paths touched in Phase 2, freshened in Phase 3

git_sync() {
  local repo="$1" s="$SRC/$repo" d="$DST/$repo"
  local sbranch shash thash surl
  sbranch="$(cur_branch "$s")"
  shash="$(cur_hash "$s")"

  # Clone from the source's on-disk copy if the target repo doesn't exist yet.
  # A local clone hardlinks objects (fast, space-cheap) and needs no network,
  # so it also carries local-only commits. Then repoint origin at the real URL.
  if ! is_git "$d"; then
    mkdir -p "$(dirname "$d")"
    if ! git clone --quiet "$s" "$d" >/dev/null 2>&1; then
      err "$repo: clone from source failed (target path may be non-empty and not a git repo)"
      return 1
    fi
    surl="$(git -C "$s" config --get remote.origin.url 2>/dev/null || true)"
    if [ -n "$surl" ]; then
      git -C "$d" remote set-url origin "$surl" >/dev/null 2>&1 || true
    fi
    info "  $repo: cloned into target"
  fi

  # Bring source commits (incl. local-only) into target via local-path fetch.
  if ! git -C "$d" fetch --no-tags "$s" "+refs/heads/*:refs/remotes/_dupsrc/*" >/dev/null 2>&1; then
    # Fall back to fetching the single commit's branch explicitly.
    git -C "$d" fetch --no-tags "$s" "$sbranch" >/dev/null 2>&1 || true
  fi

  # Move/create the branch at the exact hash and check it out.
  if [ "$sbranch" != "HEAD" ]; then
    git -C "$d" checkout -B "$sbranch" "$shash" >/dev/null 2>&1 || git -C "$d" checkout "$shash" >/dev/null 2>&1
  else
    git -C "$d" checkout "$shash" >/dev/null 2>&1
  fi

  # Clean the temporary tracking refs.
  git -C "$d" for-each-ref --format='%(refname)' refs/remotes/_dupsrc 2>/dev/null \
    | while IFS= read -r ref; do git -C "$d" update-ref -d "$ref" >/dev/null 2>&1 || true; done

  thash="$(cur_hash "$d")"
  if [ "$thash" != "$shash" ]; then
    err "$repo: HEAD mismatch after sync (want ${shash:0:12}, got ${thash:0:12})"
    return 1
  fi
  ok "$repo: $sbranch @ ${shash:0:12}"
}

step "Phase 1: git sync"
for repo in "${ACTIVE[@]}"; do
  if git_sync "$repo"; then
    SYNCED+=("$repo")
  else
    FAILED+=("$repo")
  fi
done
echo

# ---- Phase 2: artifact copy -------------------------------------------------
copy_artifacts() {
  local repo="$1" s="$SRC/$repo" d="$DST/$repo" item
  local any=0
  while IFS= read -r item; do
    [ -z "$item" ] && continue
    any=1
    local src_item="$s/$item" dst_item="$d/$item"
    local dst_parent; dst_parent="$(dirname "$dst_item")"
    mkdir -p "$dst_parent"
    rm -rf "$dst_item"
    cp -a "$src_item" "$dst_parent/"
    COPIED_TREES+=("$dst_item")
    ok "$repo: copied $item ($(dsize "$src_item"))"
  done < <(artifact_items "$repo")
  if [ "$any" -eq 0 ]; then info "  $repo: (no release artifacts in source; skipped)"; fi
}

# ---- Phase 3: repath ---------------------------------------------------------
# Rewrite baked-in ABSOLUTE source-workspace paths ($SRC) to the target ($DST)
# inside the copied trees. Without this, cmake/ninja/cargo/*.make metadata still
# points at the source workspace, so an incremental rebuild in the target reads
# the source's sources/objects (and gluten's native build sources libhudi.so
# from the source's HUDI_RS_DIR). Because repos share an identical layout under
# each workspace root, replacing the root string $SRC->$DST covers every subpath.
#
# Same-length roots (e.g. ws2->ws3) => byte-for-byte, size-preserving rewrite is
# safe on EVERY file, binaries included (ELF/rlib debug paths, the binary
# .ninja_deps, cargo fingerprints) — no corruption. Different-length roots => we
# rewrite TEXT files only (all build-DECISION files are text); binaries keep
# their embedded source paths, which are debug-info only here.
repath_artifacts() {
  [ "${#COPIED_TREES[@]}" -gt 0 ] || return 0
  local same_len=0
  [ "${#SRC}" -eq "${#DST}" ] && same_len=1

  local -a files=(); local f
  if [ "$same_len" -eq 1 ]; then
    while IFS= read -r f; do files+=("$f"); done \
      < <(grep -rlF "$SRC" "${COPIED_TREES[@]}" 2>/dev/null | sort -u)
  else
    # -I skips binary files (can't size-safely rewrite when lengths differ)
    while IFS= read -r f; do files+=("$f"); done \
      < <(grep -rlIF "$SRC" "${COPIED_TREES[@]}" 2>/dev/null | sort -u)
  fi

  local n="${#files[@]}"
  if [ "$n" -eq 0 ]; then ok "no baked-in source paths to rewrite"; return 0; fi

  # SRC/DST passed via env so path metachars ($ @ \ /) are never interpreted:
  # \Q..\E literal-quotes the search; the replacement is a bare var interpolation.
  printf '%s\0' "${files[@]}" \
    | SRC_P="$SRC" DST_P="$DST" LC_ALL=C \
      xargs -0 perl -0777 -i -pe 's{\Q$ENV{SRC_P}\E}{$ENV{DST_P}}g'

  # NB: guard the grep — under `set -o pipefail` a zero-match grep (exit 1, the
  # SUCCESS case here) would otherwise fail the assignment and trip `set -e`,
  # aborting before the mtime-freshen phase.
  local left
  left="$( { grep -rlF "$SRC" "${COPIED_TREES[@]}" 2>/dev/null || true; } | wc -l | tr -d ' ')"
  if [ "$same_len" -eq 1 ]; then
    ok "rewrote $SRC -> $DST in $n file(s) (byte-safe, all file types)"
    [ "$left" = "0" ] || warn "$left file(s) still reference $SRC after rewrite"
  else
    warn "SRC/DST path lengths differ (${#SRC} vs ${#DST}); rewrote $n TEXT file(s) only"
    info "  binaries keep embedded source paths (debug-info, cosmetic). The one FUNCTIONAL"
    info "  binary reference — each final .so's DT_RUNPATH — is normalized to \$ORIGIN in Phase 3b,"
    info "  so the copy is self-contained regardless of name length."
    [ "$left" = "0" ] || info "  $left binary file(s) still reference $SRC (debug-info; harmless)"
  fi
}

# ---- Phase 3b: normalize .so runpaths to $ORIGIN -----------------------------
# The repath step (Phase 3) can only byte-rewrite TEXT files when SRC/DST differ
# in length, so a copied .so keeps its baked-in absolute DT_RUNPATH. That runpath
# is the ONE functional binary reference: it points at the ABSOLUTE build dir the
# .so was linked in (often a THIRD workspace — e.g. the golden the source was
# itself duplicated from) — so the copy silently depends on that path still
# existing and breaks if it is deleted/re-leased.
#
# This phase makes every copied final .so self-contained by rewriting its runpath
# relative to $ORIGIN: the .so's own build dir -> $ORIGIN, and any source-tree
# cross-reference -> $ORIGIN/<rel>. Needs no patchelf/chrpath — it shortens the
# runpath string in place, NUL-padded (offsets/sizes unchanged, exactly like
# chrpath); uses patchelf instead when available (handles the rare grow case).
# Runs for BOTH same- and different-length roots (the runpath may point at neither
# SRC nor DST, so Phase 3's SRC->DST rewrite would not catch it).
normalize_runpaths() {
  [ "${#COPIED_TREES[@]}" -gt 0 ] || return 0
  command -v readelf >/dev/null 2>&1 || { warn "readelf not found; skipping runpath normalization"; return 0; }
  command -v python3 >/dev/null 2>&1 || { warn "python3 not found; skipping runpath normalization"; return 0; }
  local have_patchelf=0; command -v patchelf >/dev/null 2>&1 && have_patchelf=1

  local helper; helper="$(mktemp)"
  cat > "$helper" <<'PY'
import os, re, subprocess, sys
def runpath_of(so):
    out = subprocess.run(["readelf","-d",so],capture_output=True,text=True).stdout
    m = re.search(r"\((?:RUNPATH|RPATH)\).*\[(.*)\]", out)
    return m.group(1) if m else None
def compute(so, repos, dst_root):
    old = runpath_of(so)
    if not old: return None, None
    so_dir   = os.path.realpath(os.path.dirname(so))
    dst_root = os.path.realpath(dst_root)
    out=[]; changed=False
    for e in old.split(":"):
        if e.startswith("$ORIGIN") or not e.startswith("/"): out.append(e); continue
        mapped=None
        # Anchor an absolute build-tree runpath at a KNOWN repo dir, then re-point it
        # at the SAME location under THIS workspace, relative to $ORIGIN. Handles the
        # .so's own dir (-> $ORIGIN) and any cross-tree / third-workspace reference
        # (e.g. a packaged .so whose runpath points at another workspace's cpp/build).
        for R in repos:
            k="/"+R+"/"; idx=e.find(k)
            if idx!=-1:
                tgt=os.path.join(dst_root, e[idx+1:])         # <dst>/<repo>/<subpath>
                if os.path.isdir(tgt):
                    rp=os.path.relpath(tgt, so_dir)
                    mapped="$ORIGIN" if rp=="." else os.path.join("$ORIGIN", rp)
                break
        if mapped is not None: out.append(mapped); changed=True
        else: out.append(e)                                   # system path (/usr/local/lib, ...) -> keep
    return (old, ":".join(out) if changed else None)
def main():
    mode, so, repos_csv, dst = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    old, new = compute(so, [r for r in repos_csv.split(",") if r], dst)
    if not new: print("keep"); return
    if mode=="plan": print("plan\t%s\t%s"%(old,new)); return
    if len(new) > len(old): print("defer\t%s"%new); return           # grow -> needs patchelf/section resize
    ob,nb=old.encode(),new.encode(); data=bytearray(open(so,"rb").read())
    i=data.find(ob)
    while i!=-1:
        data[i:i+len(nb)]=nb; data[i+len(nb)]=0; i=data.find(ob,i+len(ob))  # shorten in place, NUL-pad
    open(so,"wb").write(data); print("fixed\t%s\t%s"%(old,new))
main()
PY

  local repos_csv; repos_csv="$(IFS=,; echo "${REPOS[*]}")"           # known repo names anchor the mapping
  local so fixed=0 kept=0 deferred=0 res newrp line
  while IFS= read -r so; do
    [ -n "$so" ] || continue
    if [ "$DRY_RUN" -eq 1 ]; then
      line="$(python3 "$helper" plan "$so" "$repos_csv" "$DST" 2>/dev/null)"
      case "$line" in plan*) info "  would set runpath \$ORIGIN on ${so#$DST/}"; fixed=$((fixed+1)) ;; esac
      continue
    fi
    res="$(python3 "$helper" fix "$so" "$repos_csv" "$DST" 2>/dev/null)"
    case "$res" in
      fixed*) fixed=$((fixed+1)) ;;
      defer*) newrp="${res#defer$'\t'}"                               # new runpath longer than old
        if [ "$have_patchelf" -eq 1 ] && patchelf --set-rpath "$newrp" "$so" 2>/dev/null; then
          fixed=$((fixed+1))
        else
          deferred=$((deferred+1))
          warn "runpath grew for ${so#$DST/}; install patchelf and run: patchelf --set-rpath '$newrp' '$so'"
        fi ;;
      *) kept=$((kept+1)) ;;
    esac
  done < <(find "${COPIED_TREES[@]}" -type f -name '*.so' 2>/dev/null)

  rm -f "$helper"
  if [ "$DRY_RUN" -eq 1 ]; then
    info "  $fixed .so runpath(s) would be normalized to \$ORIGIN"
  else
    ok "normalized $fixed .so runpath(s) to \$ORIGIN (self-contained)$([ "$deferred" -gt 0 ] && echo "; $deferred deferred (need patchelf)")"
  fi
}

if [ "$NO_ARTIFACTS" -eq 0 ]; then
  step "Phase 2: release artifacts"
  for repo in "${SYNCED[@]}"; do
    copy_artifacts "$repo"
  done
  echo

  # ---- Phase 3: repath baked-in source paths -------------------------------
  if [ "${#COPIED_TREES[@]}" -gt 0 ]; then
    step "Phase 3: repath baked-in source paths ($SRC -> $DST)"
    repath_artifacts
    echo
  fi

  # ---- Phase 3b: normalize .so runpaths to $ORIGIN -------------------------
  if [ "${#COPIED_TREES[@]}" -gt 0 ]; then
    step "Phase 3b: normalize .so runpaths to \$ORIGIN (self-contained copy)"
    normalize_runpaths
    echo
  fi

  # ---- Phase 4: freshen mtimes ---------------------------------------------
  # git checkout stamped source files with "now"; copied+repathed artifacts must
  # look at least as new so incremental builds no-op. Touch them last, after the
  # repath rewrite has settled their contents.
  if [ "${#COPIED_TREES[@]}" -gt 0 ]; then
    step "Phase 4: freshen artifact mtimes"
    for t in "${COPIED_TREES[@]}"; do
      find "$t" -exec touch {} + 2>/dev/null || touch "$t"
    done
    ok "touched ${#COPIED_TREES[@]} artifact tree(s)"
    echo
  fi
else
  info "(--no-artifacts: skipped build-artifact copy)"
  echo
fi

# ---- summary ----------------------------------------------------------------
step "Summary"
info "  synced : ${SYNCED[*]:-none}"
if [ "${#TO_CLONE[@]}" -gt 0 ]; then info "  cloned : ${TO_CLONE[*]}"; fi
if [ "${#FAILED[@]}" -gt 0 ]; then err "  failed : ${FAILED[*]}"; fi
echo
info "Verify with:"
for repo in "${SYNCED[@]}"; do
  info "  git -C $DST/$repo log -1 --oneline"
done

if [ "${#FAILED[@]}" -gt 0 ]; then exit 1; fi
exit 0
