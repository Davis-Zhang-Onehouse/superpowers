#!/usr/bin/env bash
# §Q — the release lifecycle, end to end, through the CLI only.
#
# Every other release assertion is hermetic and drives the modules directly. This one runs the verbs an
# operator types, against a real git repository and a real symlink, because the properties that matter
# here are the ones no unit test can reach: that the tag really lands, that the payload really is
# read-only on disk, that `current` really moves, and that a rollback really returns the pointer to the
# previous release.
#
# Its repo and its releases root are BOTH throwaway, inside this section's evidence tree. The real
# $FLEET_RELEASES is never named, so a bug here cannot move what is deployed on this box, and no git
# command in this file is ever aimed at the checkout it is running from.
#
# THREE DEVIATIONS FROM THE PLAN'S OWN LISTING, STATED UP FRONT
# -------------------------------------------------------------
#  1. The plan's Q3 note is written inside double quotes with `current` in BACKTICKS, so bash would run
#     `current` as a command and splice its (empty) output into the evidence row. The word is quoted with
#     single quotes here instead. Nothing about the case changed.
#  2. Q1's own GIVEN/WHEN/THEN promises "an IMMUTABLE export" and "an ANNOTATED tag", and the plan's
#     assertions checked neither: `tag -l` matches a lightweight tag just as happily, and nothing looked
#     at a mode bit. Both are now asserted — `cat-file -t` must say `tag`, and `find -perm /222` over the
#     payload must come back empty while `.release/` stays writable, because a release frozen whole is
#     one that can never be promoted or verified. This ADDS to what Q1 measures; it removes nothing.
#  3. Q3 additionally requires that no history row exists after the refusal. "`current` was never
#     created" sampled after the verb returned is a post-state check, not a during-check (correction 1 in
#     the plan) — but a refusal that happens BEFORE the lock leaves no register either, and that is a
#     second, independent trace of the same fact. Both are asserted; the note says which is which.
#
# REPEATABILITY
# -------------
# `release-cut` refuses a version that already exists, so a second run of this file would refuse
# everything if it inherited the first run's release area. The throwaway trees are therefore reset on
# ENTRY, not on exit: the evidence a results row points at survives the run that produced it. The reset
# has to widen permissions first — `_freeze_payload` drops every write bit on the payload INCLUDING its
# directories, and a directory with no `w` cannot have its entries unlinked.
#
# Run: bash fleet/it/run-Q.sh
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'Q[0-9]+[a-z]?|ISOLATION-Q-(enter|leave)'
it_section Q
it_fresh_store

# Evidence paths are recorded RELATIVE to the instant — an absolute one is only readable on the box that
# produced it, and a $TMPDIR one is not readable anywhere for long.
EVREL="fleet/it/Q"
REPO="$EV/repo"; RELEASES="$EV/releases"; OUT="$EV/out"

q_reset() {     # the previous run's throwaway trees. The export is `chmod -R a-w` BY DESIGN.
  local victim
  for victim in "$REPO" "$RELEASES" "$OUT"; do
    [ -e "$victim" ] || continue
    chmod -R u+w "$victim" 2>/dev/null || true
    rm -rf "$victim"
  done
}
q_reset
mkdir -p "$REPO" "$RELEASES" "$OUT"

FLEET_BIN="$(cd "$IT_ROOT/../.." && pwd)/bin/fleet"

git -C "$REPO" init -q -b live
git -C "$REPO" config user.email "it@example.com"
git -C "$REPO" config user.name "IT"
git -C "$REPO" config commit.gpgsign false
git -C "$REPO" config tag.gpgsign false
mkdir -p "$REPO/fleet/src/fleet" "$REPO/bin"
printf '__version__ = "0.0.0"\n' > "$REPO/fleet/src/fleet/__init__.py"
printf '#!/bin/sh\necho stub\n' > "$REPO/bin/fleet"
chmod +x "$REPO/bin/fleet"
git -C "$REPO" add -A && git -C "$REPO" commit -q -m "initial import"

# Every verb goes through the launcher an operator has on PATH, with the release area named by
# environment. `--releases` is never passed, so this also exercises the env half of `_releases`.
rel() { FLEET_RELEASES="$RELEASES" FLEET_HOME="$EV/home" "$FLEET_BIN" "$@"; }

# Q1 — GIVEN a clean throwaway repo, WHEN `release-cut` runs, THEN an immutable export, an ANNOTATED tag
#      and a CANDIDATE state all exist, and the payload carries no write bit while `.release/` does.
EXPORT="$RELEASES/fleet-v0.1.0"
rel release-cut --version 0.1.0 --repo "$REPO" > "$OUT/Q1-cut.out" 2>&1; q1=$?
q1_tagtype="$(git -C "$REPO" cat-file -t 'fleet/v0.1.0' 2>/dev/null)"
q1_state="$(cat "$EXPORT/.release/STATE" 2>/dev/null)"
# Mode bits, not `-w`: `-w` is true for root whatever the mode says, and the claim is about the artifact.
q1_writable="$(find "$EXPORT" -mindepth 1 -path "$EXPORT/.release" -prune -o -perm /222 -print 2>/dev/null \
               | head -3 | tr '\n' ' ')"
q1_meta_writable=no
[ -n "$(find "$EXPORT/.release" -maxdepth 0 -perm -u+w -print 2>/dev/null)" ] && q1_meta_writable=yes
if [ "$q1" = 0 ] && [ -d "$EXPORT" ] && [ "$q1_tagtype" = tag ] && [ "$q1_state" = CANDIDATE ] \
   && [ -z "${q1_writable// /}" ] && [ "$q1_meta_writable" = yes ]; then
  it_pass Q1 "$EVREL/out/Q1-cut.out" \
    "cut 0.1.0: export present, ANNOTATED tag fleet/v0.1.0 (cat-file -t = tag), STATE=CANDIDATE, and not one payload path carries a write bit while .release/ stays writable so promote and verify can still record"
else
  it_fail Q1 "$EVREL/out/Q1-cut.out" \
    "want exit 0, an annotated tag, STATE=CANDIDATE, a write-bit-free payload and a writable .release/; got exit $q1, tag type '$q1_tagtype', state '$q1_state', writable payload paths '${q1_writable:-none}', .release writable=$q1_meta_writable"
fi

# Q2 — GIVEN a dirty tree, WHEN `release-cut` runs, THEN it is REFUSED (exit 4) and nothing is created.
printf 'uncommitted\n' > "$REPO/dirty.txt"
before_dirs="$(ls "$RELEASES" | sort | tr '\n' ' ')"
rel release-cut --version 0.2.0 --repo "$REPO" > "$OUT/Q2-dirty.out" 2>&1; q2=$?
after_dirs="$(ls "$RELEASES" | sort | tr '\n' ' ')"
if [ "$q2" = 4 ] && [ "$before_dirs" = "$after_dirs" ]; then
  it_pass Q2 "$EVREL/out/Q2-dirty.out" \
    "a dirty tree refused the cut with exit 4 and created nothing (releases unchanged: $after_dirs)"
else
  it_fail Q2 "$EVREL/out/Q2-dirty.out" "want exit 4 and no new release; got exit $q2, dirs '$after_dirs'"
fi
rm -f "$REPO/dirty.txt"

# Q3 — GIVEN a CANDIDATE with no evidence, WHEN `release-deploy` runs without --force, THEN it REFUSES.
rel release-deploy --version 0.1.0 > "$OUT/Q3-deploy.out" 2>&1; q3=$?
q3_hist=absent; [ -e "$RELEASES/RELEASE-HISTORY.tsv" ] && q3_hist=present
if [ "$q3" = 4 ] && [ ! -e "$RELEASES/current" ] && [ "$q3_hist" = absent ]; then
  it_pass Q3 "$EVREL/out/Q3-deploy.out" \
    "deploying a CANDIDATE was refused with exit 4; no 'current' exists afterwards, and — the independent half, since a post-state check alone cannot see a window — the refusal also left no RELEASE-HISTORY.tsv, so it returned before the lock rather than after a write it undid"
else
  it_fail Q3 "$EVREL/out/Q3-deploy.out" \
    "want exit 4, no current and no register; got exit $q3, current=$([ -e "$RELEASES/current" ] && echo present || echo absent), register=$q3_hist"
fi

# Q4 — GIVEN a forced deploy WITH a reason, WHEN it runs, THEN `current` resolves to the release and the
#      history records a DEPLOY row carrying that reason.
rel release-deploy --version 0.1.0 --force --reason "IT forced deploy" > "$OUT/Q4.out" 2>&1; q4=$?
target="$(readlink "$RELEASES/current" 2>/dev/null)"
if [ "$q4" = 0 ] && [ "$(basename "${target:-}")" = "fleet-v0.1.0" ] \
   && grep -q 'DEPLOY' "$RELEASES/RELEASE-HISTORY.tsv" 2>/dev/null \
   && grep -q 'IT forced deploy' "$RELEASES/RELEASE-HISTORY.tsv" 2>/dev/null; then
  it_pass Q4 "$EVREL/out/Q4.out" \
    "current -> fleet-v0.1.0 and the register carries a DEPLOY row with the stated reason"
else
  it_fail Q4 "$EVREL/out/Q4.out" "want current -> fleet-v0.1.0 and a DEPLOY row; got exit $q4, target '$target'"
fi

# Q5 — GIVEN a second release deployed over the first, WHEN `release-rollback` runs with no --to, THEN it
#      returns to the PREVIOUSLY deployed version, read from the register rather than guessed.
git -C "$REPO" commit -q --allow-empty -m "second change"
rel release-cut --version 0.1.1 --repo "$REPO" > "$OUT/Q5-cut.out" 2>&1; q5cut=$?
rel release-deploy --version 0.1.1 --force --reason "second" > "$OUT/Q5-deploy.out" 2>&1; q5dep=$?
rel release-rollback --reason "IT rollback" > "$OUT/Q5-rollback.out" 2>&1; q5=$?
target="$(readlink "$RELEASES/current" 2>/dev/null)"
if [ "$q5" = 0 ] && [ "$(basename "${target:-}")" = "fleet-v0.1.0" ] \
   && tail -1 "$RELEASES/RELEASE-HISTORY.tsv" 2>/dev/null | grep -q 'ROLLBACK'; then
  it_pass Q5 "$EVREL/out/Q5-rollback.out" \
    "rollback with no --to returned to 0.1.0, the version the register named as previous, and recorded a ROLLBACK row"
else
  it_fail Q5 "$EVREL/out/Q5-rollback.out" \
    "want current -> fleet-v0.1.0; got exit $q5, target '$target' (the setup exits were cut=$q5cut deploy=$q5dep — a non-zero there means this case never reached what it measures)"
fi

# Q6 — GIVEN a release cut after 0.1.0, WHEN the release's OWN changelog is read, THEN it lists the delta
#      commit, and the first release's lists none. A release that cannot say what changed is not a
#      release — and the payload's `fleet/CHANGELOG.md` is the whole history, which is a different
#      question from "what is in the artifact I am holding".
if grep -q 'second change' "$RELEASES/fleet-v0.1.1/.release/CHANGELOG.md" 2>/dev/null \
   && ! grep -q '^- ' "$RELEASES/fleet-v0.1.0/.release/CHANGELOG.md" 2>/dev/null; then
  it_pass Q6 "$EVREL/out/Q5-cut.out" \
    "0.1.1's own .release/CHANGELOG.md names the commit added since 0.1.0, and 0.1.0's lists no commits because it has no predecessor"
else
  it_fail Q6 "$EVREL/out/Q5-cut.out" "the changelogs do not describe the delta as expected"
fi

it_cleanup_tmux
it_assert_isolation Q-leave
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
