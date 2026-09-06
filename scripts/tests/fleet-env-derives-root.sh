#!/usr/bin/env bash
# `scripts/fleet-env.sh` derives its settings from the `.fleet-root` marker instead of naming davis_root.
#
# Why this test exists rather than a read-through of the file: the values it exports are what every shell
# on the box inherits, so a literal path in there is not a style problem — it is the mechanism by which a
# SECOND root silently gets the FIRST root's release area. `FI-421` is the same class one layer down: a
# path constant that was true when written, dead the day the process moved, and silent in between.
#
# Run: bash scripts/tests/fleet-env-derives-root.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
ENVSH="$REPO/scripts/fleet-env.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1"; note "       wanted [$2] got [$3]"; fails=1; fi; }

# Two roots under one fake $HOME, exactly the shape the design specifies for the real box.
mkdir -p "$TMP/home/alpha_root/ws1" "$TMP/home/beta_root/ws1" "$TMP/home/unmarked"
printf '{"name": "alpha"}\n' > "$TMP/home/alpha_root/.fleet-root"
printf '{"name": "beta"}\n'  > "$TMP/home/beta_root/.fleet-root"

# Source it in a clean shell whose cwd decides the answer, and print what it exported.
probe() {                       # probe <cwd> -> "<FLEET_HOME>|<FLEET_RELEASES>|<FLEET_TMUX_SOCKET>"
  ( cd "$1" && env -u FLEET_HOME -u FLEET_RELEASES -u FLEET_TMUX_SOCKET -u FLEET_INSTANTS \
      -u FLEET_ROOT HOME="$TMP/home" bash -c \
      ". '$ENVSH' >/dev/null 2>&1; printf '%s|%s|%s' \"\${FLEET_HOME:-}\" \"\${FLEET_RELEASES:-}\" \"\${FLEET_TMUX_SOCKET:-}\"" )
}

a="$(probe "$TMP/home/alpha_root/ws1")"
b="$(probe "$TMP/home/beta_root/ws1")"
u="$(probe "$TMP/home/unmarked")"

check "alpha derives its own store"    "$TMP/home/alpha_root/.fleet"          "${a%%|*}"
check "alpha derives its own releases" "$TMP/home/alpha_root/fleet-releases"  "$(echo "$a" | cut -d'|' -f2)"
check "alpha derives its own socket"   "fleet-alpha"                          "${a##*|}"
check "beta derives its own store"     "$TMP/home/beta_root/.fleet"           "${b%%|*}"
check "beta derives its own socket"    "fleet-beta"                           "${b##*|}"

# The two roots must not agree about anything. Asserted rather than assumed: two derivations that both
# silently fell back to the same literal would each look right in isolation.
if [ "$a" = "$b" ]; then note "FAIL alpha and beta exported identical settings [$a]"; fails=1
else note "ok   the two roots share no exported value"; fi

# An unmarked directory exports NOTHING rather than defaulting. A default here is how a shell with no
# root reaches another root's store — the exact interference this work removes.
check "unmarked exports no store"    "" "${u%%|*}"
check "unmarked exports no releases" "" "$(echo "$u" | cut -d'|' -f2)"
check "unmarked exports no socket"   "" "${u##*|}"

# And it must SAY so. A silent no-op is indistinguishable from a working setup until the first write.
said="$( cd "$TMP/home/unmarked" && env -u FLEET_HOME -u FLEET_RELEASES -u FLEET_TMUX_SOCKET \
         -u FLEET_INSTANTS -u FLEET_ROOT HOME="$TMP/home" bash -c ". '$ENVSH'" 2>&1 )"
if printf '%s' "$said" | grep -q '\.fleet-root'; then note "ok   an unmarked shell is told why nothing was set"
else note "FAIL an unmarked shell was left silent: [$said]"; fails=1; fi

# An already-exported value WINS. `it_section` and 1291 call sites depend on explicit naming out-ranking
# derivation, and this file is sourced by the shell rc that those runs inherit.
pre="$( cd "$TMP/home/alpha_root/ws1" && env -u FLEET_RELEASES -u FLEET_TMUX_SOCKET -u FLEET_INSTANTS \
        -u FLEET_ROOT HOME="$TMP/home" FLEET_HOME="$TMP/explicit" bash -c \
        ". '$ENVSH' >/dev/null 2>&1; printf '%s' \"\$FLEET_HOME\"" )"
check "an exported FLEET_HOME is not overridden" "$TMP/explicit" "$pre"

# No literal davis_root anywhere in the file. The regression this whole test exists for.
if grep -q 'davis_root' "$ENVSH"; then
  note "FAIL fleet-env.sh still names davis_root literally:"
  grep -n 'davis_root' "$ENVSH" | sed 's/^/       /'
  fails=1
else
  note "ok   fleet-env.sh names no root literally"
fi

if [ "$fails" = 0 ]; then echo "fleet-env-derives-root: ALL GREEN"; exit 0; fi
echo "fleet-env-derives-root: FAILURES" >&2
exit 1
