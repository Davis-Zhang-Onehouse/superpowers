#!/usr/bin/env bash
# `scripts/fleet-codex-skills.sh`, asserted against a fake release area and a fake CODEX_HOME under
# `mktemp -d` -- never the real fleet-releases or any root's .codex (FB-111).
#
# The properties worth pinning at this tier are the ones an operator meets at the shell: `--dry-run` writes
# nothing; the install writes ONE link whose text names `current`; a deploy (flipping `current`) needs no
# re-install; a directory in the way is refused and left alone; and `--codex-home` is never guessed.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRIPT="$REPO/scripts/fleet-codex-skills.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { # check <label> <expected> <actual>
  local label="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    note "ok   $label"
  else
    note "FAIL $label"
    note "       wanted: [$want]"
    note "       got:    [$got]"
    fails=1
  fi
}
listing() { (cd "$1" && find . -printf '%p %y %l\n' | sort); }

R="$TMP/fleet-releases"
CORE="using-superpowers systematic-debugging brainstorming writing-plans subagent-driven-development
      test-driven-development verification-before-completion working-as-a-dispatched-instant using-fleet
      harvesting-an-instant releasing-fleet"
for v in fleet-v1 fleet-v2; do
  for s in $CORE; do mkdir -p "$R/$v/skills/$s"; echo "$v" >"$R/$v/skills/$s/SKILL.md"; done
done
mkdir -p "$R/fleet-v2/skills/new-in-v2"; echo v2 >"$R/fleet-v2/skills/new-in-v2/SKILL.md"
ln -s "$R/fleet-v1" "$R/current"
H="$TMP/codex-home"; mkdir -p "$H"
LINK="$H/skills/superpowers"

echo "fleet-codex-skills.sh"

bash "$SCRIPT" --help >/dev/null 2>&1; check "--help exits 0" 0 $?

bash "$SCRIPT" --releases "$R" >/dev/null 2>&1; check "no --codex-home is bad input (2)" 2 $?

bash "$SCRIPT" --codex-home "$H" --releases "$R" --check >/dev/null 2>&1
check "--check on an empty home fails (1)" 1 $?

before="$(listing "$H")"
out="$(bash "$SCRIPT" --codex-home "$H" --releases "$R" --dry-run 2>&1)"; rc=$?
check "--dry-run exits 0" 0 "$rc"
check "--dry-run says would-create" yes "$(case "$out" in *would-create*) echo yes;; *) echo no;; esac)"
check "--dry-run wrote nothing" "$before" "$(listing "$H")"

bash "$SCRIPT" --codex-home "$H" --releases "$R" >/dev/null 2>&1; check "install exits 0" 0 $?
check "the link's text names current" "$R/current/skills" "$(readlink "$LINK")"
bash "$SCRIPT" --codex-home "$H" --releases "$R" --check >/dev/null 2>&1; check "--check after install (0)" 0 $?

ln -sfn "$R/fleet-v2" "$R/current"
bash "$SCRIPT" --codex-home "$H" --releases "$R" --check >/dev/null 2>&1
check "--check after a deploy, no re-install (0)" 0 $?
check "a skill new in the deployed release is reachable" v2 "$(cat "$LINK/new-in-v2/SKILL.md" 2>/dev/null)"

rm "$LINK"; ln -s "$R/fleet-v1/skills" "$LINK"
bash "$SCRIPT" --codex-home "$H" --releases "$R" --check >/dev/null 2>&1
check "--check on a link pinned to fleet-v1 fails (1)" 1 $?
bash "$SCRIPT" --codex-home "$H" --releases "$R" >/dev/null 2>&1; check "install repoints a pinned link (0)" 0 $?
check "the repointed link names current" "$R/current/skills" "$(readlink "$LINK")"

H2="$TMP/codex-home-2"; mkdir -p "$H2/skills/superpowers"; echo mine >"$H2/skills/superpowers/mine.txt"
before="$(listing "$H2")"
bash "$SCRIPT" --codex-home "$H2" --releases "$R" >/dev/null 2>&1; check "a real directory in the way is refused (4)" 4 $?
check "the refused directory is untouched" "$before" "$(listing "$H2")"

if [ "$fails" = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit "$fails"
