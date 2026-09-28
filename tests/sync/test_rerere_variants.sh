# tests/sync/test_rerere_variants.sh — S7 review CR-1.
# rerere keeps several conflict VARIANTS under one id: rr-cache/<id>/preimage.N and postimage.N, named in MERGE_RR as
# "<id>.N<TAB><path>". The purge must (1) never drop an id a live MERGE_RR names through any variant — git's rerere
# segfaults on the next continue when that directory is gone — and (2) judge every variant, so a version-only
# postimage.1 behind a variant 0 with no postimage cannot survive to replay.
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
export SPSYNC_CONFIG="$CTRL/config"
# shellcheck source=/dev/null  # written by the harness into a sandbox
. "$SPSYNC_CONFIG"; . "$SCRIPTS/lib.sh"
CACHE="$FORK/.git/rr-cache"
vpre='{
<<<<<<<
  "version": "1.0.1+fleet.0.1.0",
=======
  "version": "1.1.0",
>>>>>>>
}
'
vpost='{
  "version": "1.1.0+fleet.0.1.0",
}
'
entry() {   # entry <id> <file> <content>...: write rr-cache/<id>/<file>
  mkdir -p "$CACHE/$1"; printf '%s' "$3" > "$CACHE/$1/$2"
}
# live: version-only in variant 0 and 1; a paused rebase's MERGE_RR names only variant 1
entry live preimage "$vpre"; entry live postimage "$vpost"; entry live preimage.1 "$vpre"; entry live postimage.1 "$vpost"
mkdir -p "$FORK/.git/worktrees/rebase-wt"
printf 'live.1\tb.json\0' > "$FORK/.git/worktrees/rebase-wt/MERGE_RR"
# hidden: variant 0 has no postimage, variant 1 is a recorded version-only resolution nobody names
entry hidden preimage "$vpre"; entry hidden preimage.1 "$vpre"; entry hidden postimage.1 "$vpost"
# neighbours: a preimage-only entry replays nothing (kept); a genuine conflict resolution (kept)
entry bare preimage "$vpre"
entry genuine preimage 'line1
<<<<<<<
MY-EDIT
=======
UPSTREAM-EDIT
>>>>>>>
line3
'
entry genuine postimage 'line1
MERGED
line3
'
dropped="$(forget_version_only_resolutions "$FORK")"
[ -d "$CACHE/live" ] || { echo "FAIL @ live-variant-kept: an id a live MERGE_RR names as live.1 was purged"; exit 1; }
[ ! -d "$CACHE/hidden" ] || { echo "FAIL @ hidden-variant-dropped: a version-only postimage.1 survived"; exit 1; }
[ -d "$CACHE/bare" ] || { echo "FAIL @ preimage-only-kept"; exit 1; }
[ -d "$CACHE/genuine" ] || { echo "FAIL @ genuine-kept"; exit 1; }
assert_eq "$dropped" "1" dropped-count
pass
