# Shared helpers. Caller must have already sourced $SPSYNC_CONFIG.
g() { git -C "$1" "${@:2}"; }

load_state() { [ -f "$STATE_FILE" ] && . "$STATE_FILE" || true; }

set_state() { # set_state KEY VALUE  (idempotent rewrite)
  local k="$1" v="$2" tmp; tmp="$(mktemp)"
  touch "$STATE_FILE"
  grep -v "^$k=" "$STATE_FILE" > "$tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

latest_tag() { # highest semver vX.Y.Z tag known to the repo
  g "$REPO" tag -l 'v*' --sort=-v:refname | head -n1
}

log_event() { # log_event RESULT NEWTAG SNAPSHOT [conflicts]
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"ts":"%s","result":"%s","base":"%s","new":"%s","snapshot":"%s","conflicts":"%s"}\n' \
    "$ts" "$1" "${BASE_TAG:-}" "${2:-}" "${3:-}" "${4:-}" >> "$HISTORY"
}

prune_history() { # drop ndjson lines whose ts is older than RETENTION_DAYS
  [ -f "$HISTORY" ] || return 0
  local cutoff tmp; cutoff="$(date -u -d "-${RETENTION_DAYS} days" +%Y-%m-%dT%H:%M:%SZ)"
  tmp="$(mktemp)"
  while IFS= read -r line; do
    local ts; ts="$(printf '%s' "$line" | sed -n 's/.*"ts":"\([^"]*\)".*/\1/p')"
    { [ -z "$ts" ] || [ "$ts" \> "$cutoff" ]; } && printf '%s\n' "$line" >> "$tmp"
  done < "$HISTORY"
  mv "$tmp" "$HISTORY"
}

prune_snapshots() { # delete snapshot/* tags older than RETENTION_DAYS
  local cutoff; cutoff="$(date -u -d "-${RETENTION_DAYS} days" +%s)"
  g "$REPO" for-each-ref --format='%(refname:short) %(creatordate:unix)' 'refs/tags/snapshot/*' |
  while read -r tag epoch; do
    if [ "$epoch" -lt "$cutoff" ]; then g "$REPO" tag -d "$tag" >/dev/null; fi
  done
}

finalize_live() { # finalize_live NEWTAG RESULT  — adopt sync-rebase into live, snapshot, log, prune, refresh
  local newtag="$1" result="$2" stamp
  g "$REPO" reset --hard sync-rebase >/dev/null   # live is checked out & clean (verified)
  g "$REPO" worktree remove --force "$WORKTREE" 2>/dev/null || true
  g "$REPO" branch -D sync-rebase >/dev/null 2>&1 || true
  set_state BASE_TAG "$newtag"
  stamp="snapshot/$(date +%Y-%m-%d-%H%M%S)"
  g "$REPO" tag -a "$stamp" -m "sync onto $newtag ($result)"
  log_event "$result" "$newtag" "$stamp"
  prune_history; prune_snapshots
  if [ -n "${SPSYNC_REFRESH_CMD:-}" ]; then
    eval "$SPSYNC_REFRESH_CMD" || log_event refresh-failed "$newtag" "$stamp"
  fi
}
