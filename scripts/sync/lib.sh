# Shared helpers. Caller must have already sourced $SPSYNC_CONFIG.
g() { git -C "$1" "${@:2}"; }

# Portable "N days ago" in UTC. BSD/macOS date uses -v; GNU/Linux date uses -d.
days_ago_utc() { # days_ago_utc DAYS FORMAT   e.g. days_ago_utc 90 +%s
  date -u -v-"$1"d "$2" 2>/dev/null || date -u -d "-$1 days" "$2"
}

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

finalize_live() { # finalize_live NEWTAG RESULT — adopt sync-rebase into live, snapshot, log, prune, refresh
  local newtag="$1" result="$2" stamp
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
  log_event "$result" "$newtag" "$stamp"
  prune_history; prune_snapshots
  if [ -n "${SPSYNC_REFRESH_CMD:-}" ]; then
    eval "$SPSYNC_REFRESH_CMD" || log_event refresh-failed "$newtag" "$stamp"
  fi
}
