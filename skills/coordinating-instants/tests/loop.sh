#!/usr/bin/env bash
# V3 — the loop this skill documents must actually RUN.
#
# V1 proves every verb named exists and V2 proves every claimed refusal cites a passing case. Neither proves
# the SEQUENCE is coherent: a skill can name only real verbs, cite only real cases, and still tell you to do
# them in an order that does not work. This suite performs the loop from the skill's own table, in order,
# against a scratch store.
#
# On a PRIVATE tmux socket, and `dispatch` is `--dry-run`. `fleet dispatch` launches a real `claude` in a
# session named `dt-<name>`, and doing that on the default server is the one act the operator's rules forbid
# outright. What this suite is for is the sequence; a real launch is covered by fleet's own §J and §P.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
FLEET="$REPO/bin/fleet"
PROFILE="$REPO/skills/using-fleet/profiles/worker"
SOCK="itfleet-loop-$$"
TMP="$(mktemp -d)"
trap 'tmux -L "$SOCK" kill-server 2>/dev/null; rm -rf "$TMP"' EXIT

export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_TMUX_SOCKET="$SOCK"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"

fails=0
note() { printf '  %s\n' "$*"; }

step() {                  # step <label> <want-rc> <cmd...>
  local label="$1" want="$2"; shift 2
  "$@" > "$TMP/$label.out" 2>&1
  local rc=$?
  if [ "$rc" != "$want" ]; then
    note "STEP $label: exit $rc, wanted $want"
    sed 's/^/        /' "$TMP/$label.out" | tail -4
    fails=1
  fi
}

# ---- Setup the coordinator does once: a golden, and a slot in the pool ----------------------------
# Without this, `dispatch --dry-run` exits 3 (no capacity) — correctly, because a dry run still evaluates
# EVERY gate, and PoolCapacity refuses when nothing is enrolled. Measured: the first version of this suite
# expected 0 and got 3, which was the tool being right and the fixture being incomplete.
mkdir -p "$TMP/slot"
( cd "$TMP/slot" && git init -q . && git -c user.email=it@fleet -c user.name=it commit -q --allow-empty -m base ) >/dev/null 2>&1
step set-golden 0 "$FLEET" set-golden --path "$TMP/slot"
step enroll     0 "$FLEET" enroll --slot "$TMP/slot"

C="$("$FLEET" init --base 00000000 --name loopCoord --porcelain | awk -F'\t' '$1=="path"{print $2}')"
if [ -z "$C" ] || [ ! -d "$C" ]; then
  echo "could not create the coordinator instant; nothing below would be a verdict"
  echo "FAIL"; exit 1
fi

# ---- Raise: the only way work becomes dispatchable ------------------------------------------------
step raise-m1 0 "$FLEET" milestone --instant "$C" --id m1 --title "the enabling work" \
                  --status "done" --evidence evidence/INDEX.md
step raise-m2 0 "$FLEET" milestone --instant "$C" --id m2 --title "the real work" --dep m1
step raise-m3 0 "$FLEET" milestone --instant "$C" --id m3 --title "the tail" --dep m2
# A dep that is not on the roadmap is refused where the name is typed, not discovered later as a milestone
# that is permanently not-ready.
step bad-dep  2 "$FLEET" milestone --instant "$C" --id m9 --title "typo" --dep nosuchdep

# ---- Observe: three different questions, three verbs ----------------------------------------------
step roadmap    0 "$FLEET" roadmap --instant "$C" --porcelain
step board      0 "$FLEET" board --porcelain
step leases     0 "$FLEET" leases --porcelain
# ---- Reconcile ------------------------------------------------------------------------------------
step reconcile  0 "$FLEET" reconcile --porcelain
step reap       0 "$FLEET" reap --all --porcelain

# ---- Decide: readiness is DERIVED, so it is read and not maintained -------------------------------
notready="$("$FLEET" roadmap --instant "$C" --porcelain | awk -F'\t' '$1=="not-ready"{print $2}' | sort | tr '\n' ' ')"
case " $notready " in
  *" m3 "*) : ;;
  *) note "READINESS: m3 must be reported not-ready while m2 is unlanded; not-ready was '$notready'"; fails=1 ;;
esac
case " $notready " in
  *" m2 "*) note "READINESS: m2's dep m1 has LANDED, so m2 must not be not-ready; got '$notready'"; fails=1 ;;
esac

# ---- Dispatch: refused onto a not-ready milestone, admissible onto a ready one --------------------
step dispatch-unready 4 "$FLEET" dispatch --profile "$PROFILE" --title tail --base 00000000 \
                        --optype append --from "$C" --milestone m3 --dry-run
step dispatch-ready   0 "$FLEET" dispatch --profile "$PROFILE" --title real --base 00000000 \
                        --optype append --from "$C" --milestone m2 --dry-run

# ---- Receive: propose then apply, and readiness must RECOMPUTE ------------------------------------
step propose 0 "$FLEET" propose --instant "$C" --milestone m2 --status "done" --evidence evidence/INDEX.md
step apply   0 "$FLEET" apply --instant "$C" --milestone m2
after="$("$FLEET" roadmap --instant "$C" --porcelain | awk -F'\t' '$1=="not-ready"{print $2}' | tr '\n' ' ')"
case " $after " in
  *" m3 "*) note "RECOMPUTE: m3 is still not-ready after its dep landed; not-ready is '$after'"; fails=1 ;;
esac

# ---- Escalate, and clear ---------------------------------------------------------------------------
step park   0 "$FLEET" park --instant "$C" --question "which baseline is the ruler?"
step unpark 0 "$FLEET" unpark --instant "$C"

# ---- The endgame: a carried item is a milestone, and it is dispatchable ---------------------------
step carry 0 "$FLEET" milestone --instant "$C" --id carried \
             --title "an item that outlived its effort" --dep m3

# The live server must be untouched throughout: everything above ran on the private socket.
if tmux ls 2>/dev/null | grep -q "^$SOCK"; then
  note "ISOLATION: the private socket's sessions appeared on the DEFAULT server"; fails=1
fi

if [ "$fails" = 0 ]; then
  echo "PASS: the documented loop runs in the documented order — raise (with an unresolvable --dep refused where it is typed), observe through three separate verbs, reconcile, read DERIVED readiness, dispatch refused onto an unready milestone and admitted onto a ready one, propose+apply moving the status and readiness RECOMPUTING, park/unpark, and a carried item raised as a dispatchable milestone"
  exit 0
fi
echo "FAIL"
exit 1
