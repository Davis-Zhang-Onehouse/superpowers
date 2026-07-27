#!/usr/bin/env bash
#
# dispatch-todo.sh — dispatch ONE TODO as its own parallel worker:
#   claim a workspace slot  ->  duplicate the golden checkout into it (no rebuild)
#   ->  fork a maintain-workspace CHILD INSTANT off the base  ->  seed its CHARTER
#   with the RCA-first mandate  ->  launch an INTERACTIVE tmux `claude` session
#   ->  write an immutable dispatch record on the base (the bulletin board).
#
# Every step rolls back the previous ones on failure: a mid-way error never leaks
# a lease or leaves a half-built child instant.
#
# Design: dispatchInstants/docs/2026-07-16-dispatch-instants-design.md §4, DECISIONS D-1/D-3/D-8.
#
# Usage:
#   dispatch-todo.sh --base <base-instant> --title "<short title>" --brief <file|-> \
#       [--golden <ws-path>] [--slot <ws>] [--evidence <ptr>]... \
#       [--no-launch] [--no-duplicate]
#
# Env (for hermetic tests / overrides):
#   POOL_DIR          passed through to wspool.sh
#   WSPOOL_SH         path to wspool.sh          (default: alongside this script)
#   DUPLICATE_WS_SH   path to duplicate-workspace.sh
#                     (default: ../duplicateWorkSpace/duplicate-workspace.sh)
#
set -euo pipefail

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"; HERE="$(cd "$(dirname "$SELF")" && pwd)"
WSPOOL_SH="${WSPOOL_SH:-$HERE/wspool.sh}"
# Resolve duplicate-workspace.sh (repo-self-contained): env override → repo sibling skill
# → on PATH. No machine-specific paths, so a fresh checkout works anywhere.
if [ -z "${DUPLICATE_WS_SH:-}" ]; then
  if [ -x "$HERE/../duplicateWorkSpace/duplicate-workspace.sh" ]; then
    DUPLICATE_WS_SH="$HERE/../duplicateWorkSpace/duplicate-workspace.sh"
  elif command -v duplicate-workspace.sh >/dev/null 2>&1; then
    DUPLICATE_WS_SH="$(command -v duplicate-workspace.sh)"
  elif command -v duplicate-workspace >/dev/null 2>&1; then
    DUPLICATE_WS_SH="$(command -v duplicate-workspace)"
  fi
fi
DUPLICATE_WS_SH="${DUPLICATE_WS_SH:-duplicate-workspace.sh}"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_bold=$'\033[1m'; c_rst=$'\033[0m'
err()  { printf '%sERROR:%s %s\n' "$c_red" "$c_rst" "$*" >&2; }
warn() { printf '%sWARN:%s %s\n'  "$c_yel" "$c_rst" "$*" >&2; }
info() { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$c_bold" "$c_rst" "$*"; }

# render_template <template-file>  ->  stdout, with {{VAR}} placeholders filled.
# Unknown {{...}} placeholders are left literal. python3 (already a dep) avoids
# sed-escaping hazards for multi-line brief/evidence and slash-heavy paths.
render_template() {
  local tpl="$1"
  TPL_TITLE="$TITLE" TPL_TODO_ID="$TODO_ID" TPL_CHILD="$CHILD" \
  TPL_CHILD_NAME="$CHILD_NAME" TPL_WS="$WS" TPL_SLOT="$CLAIMED_SLOT" \
  TPL_GOLDEN="$GOLDEN" TPL_BASE_NAME="$BASE_NAME" TPL_BASE_CURR="$BASE_CURR" \
  TPL_TMUX_SESSION="$TMUX_SESSION" TPL_TODAY="$TODAY" \
  TPL_BRIEF="$BRIEF_TEXT" TPL_EVIDENCE="$EVI_MD" \
  python3 - "$tpl" <<'PY'
import os, re, sys
tpl = open(sys.argv[1]).read()
vars = {k[4:]: v for k, v in os.environ.items() if k.startswith("TPL_")}
sys.stdout.write(re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: vars.get(m.group(1), m.group(0)), tpl))
PY
}

# ---- args -------------------------------------------------------------------
BASE="" TITLE="" BRIEF="" GOLDEN="" SLOT="" PROFILE="" NO_LAUNCH=0 NO_DUP=0 LINEAGE_BASE=""
declare -a EVIDENCE=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --base)        BASE="$2"; shift 2;;
    --title)       TITLE="$2"; shift 2;;
    --brief)       BRIEF="$2"; shift 2;;
    --golden)      GOLDEN="$2"; shift 2;;
    --slot)        SLOT="$2"; shift 2;;
    --profile)     PROFILE="$2"; shift 2;;
    --evidence)    EVIDENCE+=("$2"); shift 2;;
    --no-launch)   NO_LAUNCH=1; shift;;
    --lineage-base) LINEAGE_BASE="$2"; shift 2;;
    --no-duplicate) NO_DUP=1; shift;;
    -h|--help)     sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) err "unknown arg: $1"; exit 2;;
  esac
done

[ -n "$BASE" ]  || { err "--base <base-instant> required"; exit 2; }
[ -n "$TITLE" ] || { err "--title required"; exit 2; }
[ -n "$BRIEF" ] || { err "--brief <file|-> required"; exit 2; }
BASE="$(realpath -m -- "$BASE")"
[ -f "$BASE/HANDOFF.md" ] && [ -f "$BASE/CHARTER.md" ] \
  || { err "--base does not look like a maintain-workspace instant (needs HANDOFF.md + CHARTER.md): $BASE"; exit 2; }
[ -x "$WSPOOL_SH" ] || { err "wspool.sh not found/executable at $WSPOOL_SH"; exit 2; }

# golden: explicit, else pool default file, else error
if [ -z "$GOLDEN" ]; then
  gf="${POOL_DIR:-$HOME/.claude-ws-pool}/golden"
  [ -f "$gf" ] && GOLDEN="$(head -1 "$gf")"
fi
# The golden is effort-scoped state that used to live only in a HANDOFF paragraph, so a dispatch
# without --golden failed on a config file nobody knew to create. Inherit it from THIS effort's
# most recent dispatch record before giving up, and make the error say how to fix it for good.
if [ -z "$GOLDEN" ]; then
  GOLDEN="$(BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}" python3 - "$BASE" <<'PYG'
import json, os, sys, glob
base = os.path.realpath(sys.argv[1])
recs = sorted(glob.glob(os.path.join(os.environ["BOARD_DIR"], "records", "*.json")),
              key=os.path.getmtime, reverse=True)
for f in recs:
    try: d = json.load(open(f))
    except Exception: continue
    if os.path.realpath(str(d.get("base_instant", ""))) != base: continue
    g = d.get("golden")
    if g and os.path.isdir(g):
        print(g); break
PYG
)"
  [ -n "$GOLDEN" ] && info "golden inherited from this effort's last dispatch: $GOLDEN"
fi
if [ -z "$GOLDEN" ]; then
  err "no --golden, no prior dispatch for this base to inherit from, and no ${POOL_DIR:-$HOME/.claude-ws-pool}/golden file"
  err "  fix once for this box:  echo /path/to/prebuilt-workspace > ${POOL_DIR:-$HOME/.claude-ws-pool}/golden"
  err "  or pass:                --golden /path/to/prebuilt-workspace"
  exit 2
fi
GOLDEN="$(realpath -m -- "$GOLDEN")"
[ -d "$GOLDEN" ] || { err "golden workspace does not exist: $GOLDEN"; exit 2; }

# ---- resolve profile (required; no silent default) --------------------------
# The child CHARTER + interactive SEED come from a profile dir (charter.md +
# seed.txt [+ optional handoff.md]). Selection order: --profile, else
# $DISPATCH_PROFILE, else ${POOL_DIR:-~/.claude-ws-pool}/profile. If none set,
# error (never silently pick one). A value with a slash (or leading '.') is a
# path; a bare word is a name under this skill's profiles/ dir.
PROFILES_DIR="$HERE/profiles"
PROFILE_SEL="$PROFILE"
[ -n "$PROFILE_SEL" ] || PROFILE_SEL="${DISPATCH_PROFILE:-}"
if [ -z "$PROFILE_SEL" ]; then
  pf="${POOL_DIR:-$HOME/.claude-ws-pool}/profile"
  [ -f "$pf" ] && PROFILE_SEL="$(head -1 "$pf")"
fi
if [ -z "$PROFILE_SEL" ]; then
  err "no profile selected. Pass --profile <name|path>, set \$DISPATCH_PROFILE, or write a name/path to ${POOL_DIR:-$HOME/.claude-ws-pool}/profile"
  { echo "available shipped profiles:"; ls "$PROFILES_DIR" 2>/dev/null | sed 's/^/  - /'; } >&2
  exit 2
fi
case "$PROFILE_SEL" in
  */*|.*) PROFILE_DIR="$(realpath -m -- "$PROFILE_SEL")";;   # path
  *)      PROFILE_DIR="$PROFILES_DIR/$PROFILE_SEL";;          # bare name
esac
[ -d "$PROFILE_DIR" ]             || { err "profile dir not found: $PROFILE_DIR"; exit 2; }
[ -f "$PROFILE_DIR/charter.md" ] || { err "profile missing charter.md: $PROFILE_DIR"; exit 2; }
[ -f "$PROFILE_DIR/seed.txt" ]   || { err "profile missing seed.txt: $PROFILE_DIR"; exit 2; }

# ---- derive names (maintain-workspace grammar) ------------------------------
# The instant name is 5 fields split on '-': <base>-<curr>-<state>-<opType>-<instantName>.
# The instantName field MUST be dashless (camelCase) or the grammar can't be parsed back —
# so the child folder stays locatable after a state-rename. TODO_ID (record filename / tmux
# session) is free-form and may carry dashes.
NOW="$(date +%m%d%H%M)"
camel() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
            | sed -E 's/[^a-z0-9]+/ /g' \
            | awk '{o="";for(i=1;i<=NF;i++){w=$i; o=(i==1)?w:o toupper(substr(w,1,1)) substr(w,2)} print o}'; }
INAME="$(camel "$TITLE")"
[ -n "$INAME" ] || INAME="todo"
TODO_ID="${INAME}-${NOW}"
BASE_DIR="$(dirname "$BASE")"                          # instants are siblings here
BASE_NAME="$(basename "$BASE")"
BASE_CURR="$(printf '%s' "$BASE_NAME" | cut -d- -f2)"  # field 2 = curr_instant (survives renames)
[ -n "$BASE_CURR" ] || BASE_CURR="main"
CHILD_NAME="${BASE_CURR}-${NOW}-inflight-append-${INAME}"
CHILD="$BASE_DIR/$CHILD_NAME"
TMUX_SESSION="dt-${TODO_ID}"
# Dispatch records live in the machine-global board store (D-11), NOT under the base.
# BOARD_DIR is env-overridable (default ~/.claude-dispatch-board) for hermetic tests,
# mirroring POOL_DIR for the pool.
BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
RECORDS_DIR="$BOARD_DIR/records"
RECORD="$RECORDS_DIR/${TODO_ID}.json"

# golden guard (D-3): golden must be OUTSIDE the pool and != the slot we'll claim
if [ -n "$SLOT" ] && [ "$(basename "$GOLDEN")" = "$(basename "$SLOT")" ]; then
  err "golden ($GOLDEN) is the same slot as --slot — refusing (would clobber the source)"; exit 2
fi
if POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" status "$(basename "$GOLDEN")" 2>/dev/null | grep -q '^SLOT='; then
  err "golden ($GOLDEN) is ENROLLED in the pool — a golden source must be outside the leasable pool"; exit 2
fi

if [ -e "$CHILD" ]; then err "child instant already exists: $CHILD"; exit 2; fi

# ---- rollback machinery -----------------------------------------------------
CLAIMED_SLOT=""      # basename of the slot we leased (empty until claimed)
CHILD_MADE=0
RECORD_MADE=0
SUCCESS=0
cleanup() {
  [ "$SUCCESS" -eq 1 ] && return 0
  warn "dispatch failed — rolling back"
  [ "$RECORD_MADE" -eq 1 ] && rm -f "$RECORD" && warn "  removed dispatch record"
  [ "$CHILD_MADE" -eq 1 ] && rm -rf "$CHILD" && warn "  removed child instant $CHILD_NAME"
  if [ -n "$CLAIMED_SLOT" ]; then
    POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" release "$CLAIMED_SLOT" >/dev/null 2>&1 && warn "  released lease $CLAIMED_SLOT"
  fi
}
trap cleanup EXIT

# ---- 1. claim a workspace slot ---------------------------------------------
step "claiming a workspace slot"
claim_args=(--todo "$TODO_ID" --tmux "$TMUX_SESSION" --base "$BASE" --child "$CHILD")
[ -n "$SLOT" ] && claim_args+=(--slot "$SLOT")
set +e
WS="$(POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" claim "${claim_args[@]}")"
claim_rc=$?
set -e
if [ "$claim_rc" -ne 0 ]; then
  if [ "$claim_rc" -eq 3 ]; then
    err "pool full — no free slot. Enroll one ('wspool.sh add ~/wsN') or wait for a release."
  else
    err "wspool claim failed (rc=$claim_rc)"
  fi
  exit "$claim_rc"
fi
CLAIMED_SLOT="$(basename "$WS")"
info "  leased $CLAIMED_SLOT -> $WS"

# ---- 2. duplicate golden -> slot (no rebuild) ------------------------------
if [ "$NO_DUP" -eq 0 ]; then
  step "duplicating golden ($GOLDEN) -> $WS (no rebuild)"
  [ -x "$DUPLICATE_WS_SH" ] || { err "duplicate-workspace.sh not executable at $DUPLICATE_WS_SH"; exit 1; }
  "$DUPLICATE_WS_SH" "$GOLDEN" "$WS" --force
else
  warn "  --no-duplicate: leaving $WS as-is"
fi

# ---- 3. fork child instant + bootstrap canonical files ----------------------
step "forking child instant $CHILD_NAME"
mkdir -p "$CHILD"/{investigations,evidence,plans,specs}
CHILD_MADE=1

# read brief (file or stdin)
if [ "$BRIEF" = "-" ]; then BRIEF_TEXT="$(cat)"; else BRIEF_TEXT="$(cat "$BRIEF")"; fi
EVI_MD=""
for e in "${EVIDENCE[@]}"; do EVI_MD+="  - $e"$'\n'; done
[ -n "$EVI_MD" ] || EVI_MD="  - (none supplied)"$'\n'
TODAY="$(date +%Y-%m-%d)"

render_template "$PROFILE_DIR/charter.md" > "$CHILD/CHARTER.md"

if [ -f "$PROFILE_DIR/handoff.md" ]; then
  render_template "$PROFILE_DIR/handoff.md" > "$CHILD/HANDOFF.md"
else
  cat > "$CHILD/HANDOFF.md" <<EOF
Updated: ${TODAY} | Status: LIVE SNAPSHOT (rots)

# ${TITLE} — HANDOFF   (read me first)

## Resume here
- Instant: ${CHILD}
- Workspace (code checked out here): ${WS}   (slot ${CLAIMED_SLOT})
- Resume: \`cd ${WS} && claude --resume <uuid>\`   (record the uuid in the session log below once known)
- Dispatched: ${TODAY} from base ${BASE_NAME} (tmux session: ${TMUX_SESSION})

## Where we are (one paragraph)
Freshly dispatched. Nothing done yet. Next: follow the CHARTER acceptance criteria.

## Next action
1. Read CHARTER.md and begin at its first acceptance criterion.
2. Keep this instant maintained per superpowers:maintain-workspace.

## Parked decision (for the operator — empty unless I need you)
<none>

## Live snapshot (volatile — dated)
- In flight: not started.

## Session log
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| ${TODAY} | ${WS} | (dispatched) | Instant forked + workspace leased by parallelDispatch; awaiting first session action. |

## Index
- Scope / acceptance / brief → CHARTER.md
- Decisions → DECISIONS.md · Issues → ISSUES.md · Assumptions → ASSUMPTIONS.md
- RCA / deep dives → investigations/  · Proof → evidence/INDEX.md
EOF
fi

# minimal canonical stubs (maintain-workspace invariants; the session fleshes them out)
printf '# %s — STATE\nUpdated: %s\n\n| Repo | Branch | Tip | PR | CI | Notes |\n|---|---|---|---|---|---|\n| (fill as work lands) | | | | | |\n' "$TITLE" "$TODAY" > "$CHILD/STATE.md"
printf '# %s — RUNBOOK\nUpdated: %s\n\n## Build / run / repro\n- Workspace: %s (pre-built; see duplicateWorkSpace).\n- (add exact repro commands as you find them during the RCA)\n' "$TITLE" "$TODAY" "$WS" > "$CHILD/RUNBOOK.md"
printf '# DECISIONS   (durable; append-only; dated)\nUpdated: %s\n' "$TODAY" > "$CHILD/DECISIONS.md"
printf '# ISSUES   (durable; append-only; one sub-section per issue)\nUpdated: %s\n' "$TODAY" > "$CHILD/ISSUES.md"
printf '# ASSUMPTIONS   (append, do not rewrite)\nUpdated: %s\n\n| ID | Assumption | Status | Evidence/next check |\n|---|---|---|---|\n' "$TODAY" > "$CHILD/ASSUMPTIONS.md"
printf '# Evidence index\nUpdated: %s\n\n| # | Criterion | Artifact | Shows | Source |\n|---|---|---|---|---|\n' "$TODAY" > "$CHILD/evidence/INDEX.md"
info "  child instant bootstrapped with RCA-first seeded CHARTER"

# ---- 4. write immutable dispatch record into the global board store ---------
step "recording dispatch (global board store)"
mkdir -p "$RECORDS_DIR"
DISPATCHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# ---- 4b. hygiene: persist the seed, snapshot the profile, isolate the build cache ----------
# The rendered SEED is stored so a launch line never has to be hand-built (`dispatch-launch`
# replays it, correctly quoted). The PROFILE is globally mutable and gets edited mid-effort, so
# a snapshot goes with the instant or the dispatch stops being reproducible.
SEED="$(render_template "$PROFILE_DIR/seed.txt")"
DISPATCH_META="$CHILD/.dispatch"
mkdir -p "$DISPATCH_META/profile"
printf '%s' "$SEED" > "$DISPATCH_META/seed.txt"
cp -R "$PROFILE_DIR/." "$DISPATCH_META/profile/" 2>/dev/null || true
info "  seed + profile snapshot -> $DISPATCH_META"

# Parallel workers sharing one build cache poison each other (OI-6). Point every maven project
# in this workspace at a cache INSIDE the workspace, so it cannot be got wrong.
if [ "${ISOLATE_BUILD:-1}" = "1" ]; then
  # Reuse the slot's ALREADY-POPULATED local repo if one exists under any name (previous efforts
  # used e.g. .m2-compact1). Assuming ".m2" pointed a live workspace at a directory that did not
  # exist — isolated, but with a cold cache, which is its own failure. Never point at a missing dir.
  MREPO=""
  for cand in "$WS"/.m2 "$WS"/.m2-*; do
    [ -d "$cand" ] || continue
    if [ -n "$(find "$cand" -maxdepth 3 -name '*.jar' -print -quit 2>/dev/null)" ]; then MREPO="$cand"; break; fi
  done
  [ -n "$MREPO" ] || MREPO="$WS/.m2"
  mkdir -p "$MREPO"
  while IFS= read -r pom; do
    [ -n "$pom" ] || continue
    pdir="$(dirname "$pom")"
    mkdir -p "$pdir/.mvn"
    if ! grep -qs 'maven.repo.local' "$pdir/.mvn/maven.config" 2>/dev/null; then
      printf -- '-Dmaven.repo.local=%s\n' "$MREPO" >> "$pdir/.mvn/maven.config"
      info "  build cache isolated: $pdir/.mvn/maven.config -> $MREPO"
    fi
  done <<< "$(find "$WS" -maxdepth 2 -name pom.xml 2>/dev/null)"
fi

BRIEF_ABS="$([ "$BRIEF" = "-" ] && echo "(stdin)" || realpath -m -- "$BRIEF")"
# JSON with evidence array
{
  printf '{\n'
  printf '  "todo_id": "%s",\n' "$TODO_ID"
  printf '  "title": %s,\n' "$(printf '%s' "$TITLE" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
  printf '  "child_instant": "%s",\n' "$CHILD"
  printf '  "ws": "%s",\n' "$WS"
  printf '  "slot": "%s",\n' "$CLAIMED_SLOT"
  printf '  "golden": "%s",\n' "$GOLDEN"
  printf '  "tmux": "%s",\n' "$TMUX_SESSION"
  printf '  "base_instant": "%s",\n' "$BASE"
  printf '  "brief": "%s",\n' "$BRIEF_ABS"
  printf '  "lineage_base": "%s",\n' "$LINEAGE_BASE"
  printf '  "seed_file": "%s",\n' "$DISPATCH_META/seed.txt"
  printf '  "profile": "%s",\n' "$PROFILE_DIR"
  printf '  "profile_archive": "%s",\n' "$DISPATCH_META/profile"
  printf '  "dispatched_at": "%s"\n' "$DISPATCHED_AT"
  printf '}\n'
} > "$RECORD"
RECORD_MADE=1
info "  wrote $RECORD"

# ---- 5. launch the interactive session --------------------------------------

if [ "$NO_LAUNCH" -eq 0 ]; then
  step "launching interactive tmux session $TMUX_SESSION"
  tmux new-session -d -s "$TMUX_SESSION" -c "$WS"
  # send the seeded claude invocation; %q keeps the multi-word prompt a single arg.
  # --remote-control (named after the tmux session) is REQUIRED for all dispatched
  # sessions so they can be driven remotely; the explicit name keeps the SEED prompt
  # from being consumed as the optional [name] arg.
  # --permission-mode auto: dispatched workers must run autonomously (the config-dir
  # default is "manual", which stalls unattended sessions on the first tool prompt).
  tmux send-keys -t "$TMUX_SESSION" "claude --permission-mode auto --remote-control $(printf '%q' "$TMUX_SESSION") $(printf '%q' "$SEED")" Enter
  python3 - "$RECORD" <<'PYL' 2>/dev/null || true
import json, sys, datetime
p = sys.argv[1]
d = json.load(open(p))
d["launched_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
PYL
  info "  session live. Attach with:  tmux attach -t $TMUX_SESSION"
else
  warn "  --no-launch: session NOT started. Start it later with:"
  info "    tmux new-session -d -s $TMUX_SESSION -c $WS"
  info "    tmux send-keys -t $TMUX_SESSION \"claude --permission-mode auto --remote-control $(printf '%q' "$TMUX_SESSION") $(printf '%q' "$SEED")\" Enter"
fi

SUCCESS=1
echo
step "DISPATCHED ${c_grn}${TODO_ID}${c_rst}"
info "  workspace : $WS (slot $CLAIMED_SLOT)"
info "  instant   : $CHILD"
info "  record    : $RECORD"
info "  attach    : tmux attach -t $TMUX_SESSION"
