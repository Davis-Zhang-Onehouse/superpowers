#!/usr/bin/env bash
set -euo pipefail
REPO="${REPO:-/home/ubuntu/superpowers}"
CTRL="$HOME/.superpowers-sync"
SCRIPTS_SRC="$REPO/scripts/sync"
GH_UPSTREAM="obra/superpowers"

echo "== 1. Remotes & fork =="
# Ensure 'upstream' points at the OSS repo (rename a matching 'origin' exactly once).
if ! git -C "$REPO" remote | grep -qx upstream; then
  origin_url="$(git -C "$REPO" remote get-url origin 2>/dev/null || true)"
  case "$origin_url" in
    *obra/superpowers*) : ;;
    *) echo "Refusing to rename: origin is '$origin_url', not obra/superpowers. Fix remotes manually."; exit 1;;
  esac
  git -C "$REPO" remote rename origin upstream
fi
# Ensure a personal fork exists on GitHub and 'origin' points at it (idempotent).
if ! git -C "$REPO" remote | grep -qx origin; then
  gh repo fork "$GH_UPSTREAM" 2>&1 | tail -3 || true   # no-op if the fork already exists
  me="$(gh api user -q .login)"
  git -C "$REPO" remote add origin "https://github.com/$me/superpowers.git"
fi
git -C "$REPO" fetch upstream --tags --quiet
LATEST="$(git -C "$REPO" tag -l 'v*' --sort=-v:refname | head -n1)"
[ -n "$LATEST" ] || { echo "No vX.Y.Z release tag found on upstream. Aborting."; exit 1; }

echo "== 2. live branch on $LATEST + rerere =="
git -C "$REPO" config rerere.enabled true
if ! git -C "$REPO" rev-parse -q --verify live >/dev/null; then
  # Base live on the latest RELEASE tag, replaying ONLY the commits unique to this
  # branch (my tooling/skills) — not any post-release upstream commits, which return
  # with the next release. merge-base(live, upstream/main) is the last shared upstream
  # commit; everything after it is mine.
  cur="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
  git -C "$REPO" branch live "$cur"
  git -C "$REPO" switch live
  base="$(git -C "$REPO" merge-base live upstream/main)"
  git -C "$REPO" rebase --onto "$LATEST" "$base" live || {
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
[ -f "$CTRL/state" ] || echo "BASE_TAG=$LATEST" > "$CTRL/state"

echo "== 4. switch plugin to live local marketplace =="
# Remove the cache-based install so there is one source of truth.
claude plugin uninstall superpowers@claude-plugins-official --scope user 2>/dev/null || true
claude plugin marketplace add "$REPO" --scope user 2>&1 | tail -2
# Marketplace name comes from the top-level "name" in .claude-plugin/marketplace.json
MKT="$(grep -m1 '"name"' "$REPO/.claude-plugin/marketplace.json" | sed 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')"
[ -n "$MKT" ] || { echo "Could not determine marketplace name from marketplace.json"; exit 1; }
echo "Installing superpowers@$MKT (live local marketplace)…"
claude plugin install "superpowers@$MKT" --scope user 2>&1 | tail -2
echo "If Task 1 found COPY behavior, set SPSYNC_REFRESH_CMD in $CTRL/config now."

echo "== 5. cron (03:30 daily) =="
LINE="30 3 * * * /usr/bin/env bash $CTRL/sync.sh >> $CTRL/cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v "$CTRL/sync.sh"; echo "$LINE" ) | crontab -

echo "== 6. shell banner =="
SNIP='[ -f "$HOME/.superpowers-sync/STATUS" ] && cat "$HOME/.superpowers-sync/STATUS"'
grep -qF "$SNIP" "$HOME/.zshrc" 2>/dev/null || printf '\n# superpowers-sync paused-rebase notice\n%s\n' "$SNIP" >> "$HOME/.zshrc"

echo "== DONE. Open a new Claude session and verify a skill edit appears. =="
