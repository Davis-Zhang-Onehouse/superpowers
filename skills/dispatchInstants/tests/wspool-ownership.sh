#!/usr/bin/env bash
# Hermetic tests: a coordinator must never reap or steal ANOTHER effort's slot.
# The pool + board are machine-global; leases carry BASE_INSTANT as the owner tag.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$here/../wspool.sh"
fail=0
ok(){ echo "  ok   - $1"; }
bad(){ echo "  FAIL - $1"; fail=1; }
chk(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected rc=$2, got rc=$3)"; fi; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export POOL_DIR="$tmp/pool"
mkdir -p "$tmp/wsA" "$tmp/wsB" "$tmp/wsC"
bash "$W" add "$tmp/wsA" "$tmp/wsB" "$tmp/wsC" >/dev/null 2>&1

MINE="$tmp/base-mine"; THEIRS="$tmp/base-theirs"
mklease(){ # mklease <slot> <base|-> ; dead tmux name => STALE
  local ld="$POOL_DIR/leases/$1"; mkdir -p "$ld"
  { printf 'TODO_ID=%s\n' "todo-$1"
    printf 'TMUX=dt-dead-%s\n' "$1"
    [ "$2" = "-" ] || printf 'BASE_INSTANT=%s\n' "$2"
    printf 'WS_PATH=%s\n' "$tmp/$1"
    printf 'EPOCH=%s\n' "$(date +%s)"; } > "$ld/meta"
}
leased(){ [ -d "$POOL_DIR/leases/$1" ]; }

echo "== reap ownership =="
mklease wsA "$MINE"; mklease wsB "$THEIRS"; mklease wsC "-"
bash "$W" reap --base "$MINE" >/dev/null 2>&1
leased wsA || ok "reap --base frees MY stale lease"; leased wsA && bad "my stale lease survived"
leased wsB && ok "reap --base leaves ANOTHER effort's stale lease alone" || bad "STOMPED a foreign lease"
leased wsC || ok "reap --base frees untagged legacy leases (back-compat)"; leased wsC && bad "legacy lease survived"

out=$(bash "$W" reap --base "$MINE" 2>&1); echo "$out" | grep -qi "skip\|foreign\|another" \
  && ok "explains what it skipped" || bad "silent about skipped foreign leases"

# --all is the explicit global escape hatch (old behaviour)
bash "$W" reap --all >/dev/null 2>&1
leased wsB || ok "--all still reaps everything stale" ; leased wsB && bad "--all failed to reap"

# bare reap must not stomp tagged foreign leases
rm -rf "$POOL_DIR/leases"; mkdir -p "$POOL_DIR/leases"
mklease wsB "$THEIRS"; mklease wsC "-"
bash "$W" reap >/dev/null 2>&1
leased wsB && ok "bare reap protects tagged (unknown-owner) leases" || bad "bare reap stomped a foreign lease"
leased wsC || ok "bare reap still frees untagged legacy leases" ; leased wsC && bad "legacy lease survived bare reap"

echo "== claim never steals a foreign stale slot =="
rm -rf "$POOL_DIR/leases"; mkdir -p "$POOL_DIR/leases"
mklease wsA "$THEIRS"; mklease wsB "$THEIRS"; mklease wsC "$THEIRS"
bash "$W" claim --todo t1 --tmux dt-t1 --base "$MINE" --child "$tmp/child" >/dev/null 2>&1
chk "claim fails rather than steal foreign stale slots (pool full)" 3 $?
leased wsA && leased wsB && leased wsC && ok "all foreign leases intact after failed claim" \
  || bad "claim reaped a foreign lease"

rm -rf "$POOL_DIR/leases"; mkdir -p "$POOL_DIR/leases"
mklease wsA "$MINE"; mklease wsB "$THEIRS"
bash "$W" claim --todo t2 --tmux dt-t2 --base "$MINE" --child "$tmp/child" >/dev/null 2>&1
chk "claim reclaims MY OWN stale slot" 0 $?
leased wsB && ok "foreign lease still intact" || bad "claim stomped the foreign lease"

if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
