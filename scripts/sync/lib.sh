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
    [ "$epoch" -lt "$cutoff" ] && g "$REPO" tag -d "$tag" >/dev/null
  done
}
