# Shared helpers. Caller must have already sourced $SPSYNC_CONFIG.
# shellcheck shell=bash
g() { git -C "$1" "${@:2}"; }

# Portable "N days ago" in UTC. BSD/macOS date uses -v; GNU/Linux date uses -d.
days_ago_utc() { # days_ago_utc DAYS FORMAT   e.g. days_ago_utc 90 +%s
  date -u -v-"$1"d "$2" 2>/dev/null || date -u -d "-$1 days" "$2"
}

# shellcheck source=/dev/null  # a run-time state file the sync writes; it does not exist in the repo
load_state() { [ -f "$STATE_FILE" ] && . "$STATE_FILE" || true; }

set_state() { # set_state KEY VALUE  (idempotent rewrite)
  local k="$1" v="$2" tmp; tmp="$(mktemp)"
  touch "$STATE_FILE"
  grep -v "^$k=" "$STATE_FILE" > "$tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

latest_tag() { # highest STABLE vX.Y.Z release tag (excludes pre-releases like v1.2.0-rc1)
  g "$REPO" tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname \
    | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n1
}

log_event() { # log_event RESULT NEWTAG SNAPSHOT [conflicts]
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"ts":"%s","result":"%s","base":"%s","new":"%s","snapshot":"%s","conflicts":"%s"}\n' \
    "$ts" "$1" "${BASE_TAG:-}" "${2:-}" "${3:-}" "${4:-}" >> "$HISTORY"
}

prune_history() { # drop ndjson lines whose ts is older than RETENTION_DAYS
  [ -f "$HISTORY" ] || return 0
  local cutoff tmp; cutoff="$(days_ago_utc "$RETENTION_DAYS" +%Y-%m-%dT%H:%M:%SZ)"
  tmp="$(mktemp)"
  while IFS= read -r line; do
    local ts; ts="$(printf '%s' "$line" | sed -n 's/.*"ts":"\([^"]*\)".*/\1/p')"
    { [ -z "$ts" ] || [ "$ts" \> "$cutoff" ]; } && printf '%s\n' "$line" >> "$tmp"
  done < "$HISTORY"
  mv "$tmp" "$HISTORY"
}

prune_snapshots() { # delete snapshot/* tags older than RETENTION_DAYS
  local cutoff; cutoff="$(days_ago_utc "$RETENTION_DAYS" +%s)"
  g "$REPO" for-each-ref --format='%(refname:short) %(creatordate:unix)' 'refs/tags/snapshot/*' |
  while read -r tag epoch; do
    if [ "$epoch" -lt "$cutoff" ]; then g "$REPO" tag -d "$tag" >/dev/null; fi
  done
}

new_snapshot_tag() { # echo a unique snapshot/<ts> tag name (avoids same-second collisions)
  local base cand n
  base="snapshot/$(date +%Y-%m-%d-%H%M%S)"
  cand="$base"; n=1
  while g "$REPO" rev-parse -q --verify "refs/tags/$cand" >/dev/null 2>&1; do
    cand="${base}-$n"; n=$((n + 1))
  done
  printf '%s' "$cand"
}

finalize_live() { # finalize_live NEWTAG RESULT [DETAIL] — adopt sync-rebase into live, snapshot, log, prune, refresh
  local newtag="$1" result="$2" detail="${3:-}" stamp
  # Always adopt onto the live branch, never whatever happens to be checked out.
  g "$REPO" switch -q "$LIVE_BRANCH" || { echo "finalize_live: cannot switch to $LIVE_BRANCH" >&2; return 1; }
  # Tolerate a crash-resumed finish where sync-rebase was already adopted/deleted.
  if g "$REPO" rev-parse -q --verify sync-rebase >/dev/null 2>&1; then
    g "$REPO" reset --hard sync-rebase >/dev/null   # live tree verified clean by caller
    g "$REPO" worktree remove --force "$WORKTREE" 2>/dev/null || true
    g "$REPO" branch -D sync-rebase >/dev/null 2>&1 || true
  fi
  set_state BASE_TAG "$newtag"
  stamp="$(new_snapshot_tag)"
  g "$REPO" tag -a "$stamp" -m "sync onto $newtag ($result)"
  log_event "$result" "$newtag" "$stamp" "$detail"
  prune_history; prune_snapshots
  if [ -n "${SPSYNC_REFRESH_CMD:-}" ]; then
    # Run from $REPO, not from wherever the caller stood: the STATUS banner tells you to
    # `cd $WORKTREE` before running finish.sh, and that worktree was deleted a few lines up.
    # A refresh subprocess inheriting a deleted cwd dies before doing anything (claude
    # reports "ENOENT: Bun could not find a file"), so every documented conflict
    # resolution logged refresh-failed and left the plugin cache stale.
    ( cd "$REPO" && eval "$SPSYNC_REFRESH_CMD" ) || log_event refresh-failed "$newtag" "$stamp"
  fi
}

# resolve_manifest_versions WORKTREE — S6 / coordinator D-136. Resolve the conflict a replayed fleet release commit
# meets on every upstream version bump: prints the files it resolved (one per line) and exits 0 when EVERY unmerged
# path is a manifest named in the worktree's .version-bump.json and EVERY conflict hunk in them differs only in the
# version value. The result is upstream's version with the replayed commit's "+<build>" suffix ("+fleet.<x>"), and
# the files are staged. Anything else — a non-manifest path, a hunk touching another line, an unparsable result —
# exits 1 having written nothing, so the caller pauses exactly as before.
resolve_manifest_versions() {
  local wt="$1" files
  files="$(g "$wt" diff --name-only --diff-filter=U)"
  [ -n "$files" ] || return 1
  # RV-S6Y-3: a recreated merge's "theirs" is its second parent, not the replayed commit: never resolve a merge step.
  g "$wt" rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1 && return 1
  # shellcheck disable=SC2086  # manifest paths carry no whitespace; word splitting is the argument list
  python3 - "$wt" $files <<'PY' || return 1
import copy, json, pathlib, re, sys
wt, files = pathlib.Path(sys.argv[1]), sys.argv[2:]
try:
    fields = {entry["path"]: entry["field"] for entry in json.loads((wt / ".version-bump.json").read_text())["files"]}
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)
if not files or any(f not in fields for f in files):
    sys.exit(1)
block = re.compile(r"<<<<<<< [^\n]*\n(.*?)(?:\|\|\|\|\|\|\|[^\n]*\n.*?)?=======\n(.*?)>>>>>>> [^\n]*\n", re.S)
version = re.compile(r'^(\s*"?version"?\s*:\s*"?)([^",\s]+)("?,?\s*)$')

def at(doc, path):
    for key in path:
        doc = doc[int(key)] if isinstance(doc, list) else doc[key]
    return doc

def put(doc, path, value):
    for key in path[:-1]:
        doc = doc[int(key)] if isinstance(doc, list) else doc[key]
    last = path[-1]
    doc[int(last) if isinstance(doc, list) else last] = value

resolved = {}
for name in files:
    #: RV-S6Y-4: bytes as they are — newline="" keeps a CRLF file CRLF.
    with open(wt / name, newline="") as handle:
        text = handle.read()
    changes = []                                  # (ours version, new version, prefix) per differing line
    def merge(m):
        ours, theirs = m.group(1).splitlines(True), m.group(2).splitlines(True)
        if len(ours) != len(theirs):
            changes.append(None); return m.group(0)
        out = []
        for a, b in zip(ours, theirs):
            if a == b:
                out.append(a); continue
            ea = a[len(a.rstrip("\r\n")):]
            va, vb = version.match(a.rstrip("\r\n")), version.match(b.rstrip("\r\n"))
            if not (va and vb and va.group(1) == vb.group(1) and va.group(3) == vb.group(3)):
                changes.append(None); return m.group(0)
            core = va.group(2).split("+", 1)[0]
            build = "+" + vb.group(2).split("+", 1)[1] if "+" in vb.group(2) else ""
            changes.append((va.group(2), core + build, va.group(1)))
            out.append(f"{va.group(1)}{core}{build}{va.group(3)}{ea}")
        return "".join(out)
    new, count = block.subn(merge, text)
    #: RV-S6Y-2: exactly ONE differing line per file, and it must be the field .version-bump.json declares.
    if count == 0 or "<<<<<<<" in new or ">>>>>>>" in new or len(changes) != 1 or changes[0] is None:
        sys.exit(1)
    before, after, prefix = changes[0]
    field = str(fields[name]).split(".")
    if name.endswith(".json"):
        try:
            ours_doc = json.loads(block.sub(lambda m: m.group(1), text))
            new_doc = json.loads(new)
            if at(ours_doc, field) != before:
                sys.exit(1)
            expected = copy.deepcopy(ours_doc)
            put(expected, field, after)
        except (ValueError, KeyError, IndexError, TypeError):
            sys.exit(1)
        if expected != new_doc:
            sys.exit(1)
    elif field != ["version"] or not prefix.startswith("version"):   # YAML: the top-level key only
        sys.exit(1)
    resolved[name] = new
for name, new in resolved.items():
    with open(wt / name, "w", newline="") as handle:
        handle.write(new)
    print(name)
PY
  # shellcheck disable=SC2086
  g "$wt" add -- $files
}
