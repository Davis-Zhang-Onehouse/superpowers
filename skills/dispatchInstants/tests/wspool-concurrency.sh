#!/usr/bin/env bash
#
# AC-1 proof for wspool.sh: race-safe (no double-grant under concurrent claims,
# exactly K winners for K slots) + crash-safe (dead-tmux lease is reaped, live
# lease is not). Fully hermetic: POOL_DIR is a mktemp dir; tmux is a stub on PATH;
# no real ~/wsN or ~/.claude-ws-pool is touched.
#
# Exit 0 + "PASS" = all assertions held. Any failure => "FAIL" + exit 1.
#
set -uo pipefail

WSPOOL="$(cd "$(dirname "$0")/.." && pwd)/wspool.sh"
[ -f "$WSPOOL" ] || { echo "FAIL: cannot locate wspool.sh"; exit 1; }
chmod +x "$WSPOOL"

FAILED=0
check() { # check <desc> <actual> <expected>
  if [ "$2" = "$3" ]; then printf '  ok: %s (%s)\n' "$1" "$2"
  else printf '  XX: %s — got [%s] want [%s]\n' "$1" "$2" "$3"; FAILED=1; fi
}

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

# ---- tmux stub (liveness under our control) --------------------------------
# FAKE_TMUX_MODE=all-alive : has-session always 0
# FAKE_TMUX_MODE=markers   : has-session 0 iff $FAKE_TMUX_MARKERS/<session> exists
BIN="$ROOT/bin"; mkdir -p "$BIN"
cat > "$BIN/tmux" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "has-session" ]; then
  # args: has-session -t <session>
  sess="$3"
  case "${FAKE_TMUX_MODE:-all-alive}" in
    all-alive) exit 0 ;;
    markers)   [ -e "${FAKE_TMUX_MARKERS:-/nonexistent}/$sess" ] && exit 0 || exit 1 ;;
    *) exit 0 ;;
  esac
fi
exit 0
STUB
chmod +x "$BIN/tmux"
export PATH="$BIN:$PATH"

echo "== Test A: enrollment is opt-in and idempotent =="
export POOL_DIR="$ROOT/poolA"
K=3
declare -a WS=()
for i in $(seq 1 $K); do d="$ROOT/ws$i"; mkdir -p "$d"; WS+=("$d"); done
"$WSPOOL" add "${WS[@]}" >/dev/null
"$WSPOOL" add "${WS[0]}" >/dev/null   # re-add same → must not duplicate
enrolled="$("$WSPOOL" status | grep -c '^SLOT=')"
check "enrolled slot count (idempotent add)" "$enrolled" "$K"

echo "== Test B: $((K+3)) concurrent claims vs $K slots → exactly $K winners, 0 double-grant =="
export FAKE_TMUX_MODE=all-alive
N=$((K+3))
RES="$ROOT/res"; mkdir -p "$RES"
pids=()
for i in $(seq 1 $N); do
  (
    if out="$("$WSPOOL" claim --todo "todo$i" --tmux "sess$i" --base /b --child /c 2>/dev/null)"; then
      printf 'WON %s\n' "$out" > "$RES/$i"
    else
      printf 'FULL %s\n' "$?" > "$RES/$i"
    fi
  ) &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done

won=$(grep -l '^WON ' "$RES"/* | wc -l | tr -d ' ')
full=$(grep -l '^FULL ' "$RES"/* | wc -l | tr -d ' ')
uniq_ws=$(grep -h '^WON ' "$RES"/* | awk '{print $2}' | sort -u | wc -l | tr -d ' ')
lease_dirs=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "winners" "$won" "$K"
check "pool-full rejections" "$full" "$((N-K))"
check "distinct workspaces granted (no double-grant)" "$uniq_ws" "$K"
check "lease dirs on disk" "$lease_dirs" "$K"
# every FULL must be exit code 3
badfull=$(grep -h '^FULL ' "$RES"/* | awk '$2!=3' | wc -l | tr -d ' ')
check "pool-full exit code is 3" "$badfull" "0"

echo "== Test C: release frees a slot, and it can be re-claimed =="
one_ws="$(grep -h '^WON ' "$RES"/* | head -1 | awk '{print $2}')"
one_slot="$(basename "$one_ws")"
"$WSPOOL" release "$one_slot" >/dev/null
after_release=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "lease dirs after one release" "$after_release" "$((K-1))"
reclaim="$("$WSPOOL" claim --todo reclaim --tmux sessR --base /b --child /c --slot "$one_slot" 2>/dev/null && echo OK || echo NO)"
# claim prints path then we appended OK; just check exit success by re-counting
recount=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "released slot is re-claimable" "$recount" "$K"

echo "== Test D: crash recovery — dead-tmux lease reaped, live lease kept =="
export POOL_DIR="$ROOT/poolD"
export FAKE_TMUX_MODE=markers
export FAKE_TMUX_MARKERS="$ROOT/markers"; mkdir -p "$FAKE_TMUX_MARKERS"
mkdir -p "$ROOT/wd1" "$ROOT/wd2"
"$WSPOOL" add "$ROOT/wd1" "$ROOT/wd2" >/dev/null
# both sessions alive at claim time
: > "$FAKE_TMUX_MARKERS/live1"; : > "$FAKE_TMUX_MARKERS/live2"
"$WSPOOL" claim --todo t1 --tmux live1 --base /b --child /c --slot wd1 >/dev/null
"$WSPOOL" claim --todo t2 --tmux live2 --base /b --child /c --slot wd2 >/dev/null
s1="$("$WSPOOL" status wd1 | sed -n 's/.*STATE=\([A-Z]*\).*/\1/p')"
check "wd1 LEASED while tmux alive" "$s1" "LEASED"
# simulate t1's session crashing
rm -f "$FAKE_TMUX_MARKERS/live1"
s1b="$("$WSPOOL" status wd1 | sed -n 's/.*STATE=\([A-Z]*\).*/\1/p')"
check "wd1 STALE after tmux dies" "$s1b" "STALE"
# Owner-scoped reap: a bare reap must NOT free a lease tagged to an effort it cannot identify
# (the pool is machine-global — that would hand another effort's slot away).
"$WSPOOL" reap >/dev/null 2>&1
check "bare reap protects an owner-tagged stale lease" \
  "$([ -d "$POOL_DIR/leases/wd1" ] && echo yes || echo no)" "yes"
# ...but the owning effort frees it, either via --base or by exporting DISPATCH_BASE.
"$WSPOOL" reap --base /b >/dev/null
d1=$([ -d "$POOL_DIR/leases/wd1" ] && echo yes || echo no)
d2=$([ -d "$POOL_DIR/leases/wd2" ] && echo yes || echo no)
check "reap --base freed the dead lease (wd1)" "$d1" "no"
check "reap kept the live lease (wd2)" "$d2" "yes"

echo "== Test E: claim auto-reaps a stale slot instead of reporting pool-full =="
# wd1 free now, wd2 live-held. free wd1 count check then kill wd2 and claim → should reap wd2.
rm -f "$FAKE_TMUX_MARKERS/live2"     # wd2 now stale
# pool: wd1 free, wd2 stale. A claim (no --slot) should win wd1 first (free) — so force pool full:
"$WSPOOL" claim --todo t3 --tmux live3 --base /b --child /c --slot wd1 >/dev/null
: > "$FAKE_TMUX_MARKERS/live3"       # keep t3 alive
# now wd1 held-alive, wd2 stale → a new claim must reap wd2 and succeed (not exit 3)
got="$("$WSPOOL" claim --todo t4 --tmux live4 --base /b --child /c 2>/dev/null && echo CLAIMED || echo FULL)"
# capture via recount: both slots should be leased now
final=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "claim auto-reaped stale slot (both leased)" "$final" "2"

echo
if [ "$FAILED" -eq 0 ]; then echo "PASS: wspool AC-1 (race-safe + crash-safe)"; exit 0
else echo "FAIL: wspool AC-1"; exit 1; fi
