#!/usr/bin/env bash
set -euo pipefail
REPO="${REPO:-/home/ubuntu/superpowers}"
CTRL="$HOME/.superpowers-sync"
SCRIPTS_SRC="$REPO/scripts/sync"
GH_UPSTREAM="obra/superpowers"

echo "== 1. Remotes & fork =="
if ! git -C "$REPO" remote | grep -qx upstream; then
  # current 'origin' points at upstream OSS; rename it and create a real fork
  git -C "$REPO" remote rename origin upstream
  gh repo fork "$GH_UPSTREAM" --clone=false --remote=false
  me="$(gh api user -q .login)"
  git -C "$REPO" remote add origin "git@github.com:$me/superpowers.git"
fi
git -C "$REPO" fetch upstream --tags --quiet
LATEST="$(git -C "$REPO" tag -l 'v*' --sort=-v:refname | head -n1)"

echo "== 2. live branch on $LATEST + rerere =="
git -C "$REPO" config rerere.enabled true
if ! git -C "$REPO" rev-parse -q --verify live >/dev/null; then
  # base live on latest release; current local commits (e.g. specs/scripts) replay on top
  cur="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
  git -C "$REPO" branch live "$cur"
  git -C "$REPO" switch live
  git -C "$REPO" rebase --onto "$LATEST" "$(git -C "$REPO" merge-base "$LATEST" live)" live || {
    echo "Resolve initial rebase, then re-run bootstrap."; exit 1; }
fi
git -C "$REPO" switch live

echo "== 3. control dir + scripts =="
mkdir -p "$CTRL"
cp "$SCRIPTS_SRC"/{lib.sh,sync.sh,finish.sh,rollback.sh} "$CTRL/"
chmod +x "$CTRL"/*.sh
if [ ! -f "$CTRL/config" ]; then
  sed "s#__REPO__#$REPO#" "$SCRIPTS_SRC/config.template" > "$CTRL/config"
fi
echo "BASE_TAG=$LATEST" > "$CTRL/state"

echo "== 4. switch plugin to live local marketplace =="
# Remove the cache-based install so there is one source of truth.
claude plugin uninstall superpowers@claude-plugins-official --scope user 2>/dev/null || true
claude plugin marketplace add "$REPO" --scope user 2>&1 | tail -2
MKT="$(claude plugin marketplace list 2>/dev/null | sed -n 's/.*\b\([a-z0-9-]*\) .*'"$REPO"'.*/\1/p' | head -n1)"
MKT="${MKT:-superpowers}"
claude plugin install "superpowers@$MKT" --scope user 2>&1 | tail -2
echo "If Task 1 found COPY behavior, set SPSYNC_REFRESH_CMD in $CTRL/config now."

echo "== 5. cron (03:30 daily) =="
LINE="30 3 * * * /usr/bin/env bash $CTRL/sync.sh >> $CTRL/cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v "$CTRL/sync.sh"; echo "$LINE" ) | crontab -

echo "== 6. shell banner =="
SNIP='[ -f "$HOME/.superpowers-sync/STATUS" ] && cat "$HOME/.superpowers-sync/STATUS"'
grep -qF "$SNIP" "$HOME/.zshrc" 2>/dev/null || printf '\n# superpowers-sync paused-rebase notice\n%s\n' "$SNIP" >> "$HOME/.zshrc"

echo "== DONE. Open a new Claude session and verify a skill edit appears. =="
