#!/usr/bin/env bash
# Re-derive the CORE claim of every open brief in evidence/issues/ against the working tree.
#
# WHY THIS EXISTS: `ASSUMPTIONS.md` `A-1` says the briefs describe the tree at `0.3.1` and must be
# re-measured before a gap is started — because three findings in this line of work (`FI-8`, half of
# `FI-11`, `FI-3`) evaporated on re-measure. A pasted log cannot be re-run; this can.
#
# Each check prints one row:  <gap> <verdict> <claim>
#   HOLDS   — the brief's premise is still true of the tree
#   MOVED   — the premise is stale; the brief must be corrected before the gap is worked
#   REFUTED — the premise is false as sourced; the gap's scope changes
# Exit 0 only if every check HOLDS. A non-zero exit means read the rows before designing anything.
#
# Usage:  bash bin/reverify-briefs.sh [REPO]
# Provenance: written 2026-08-03 in instant 00000000-08030228-inflight-append-fleetOpenGapClosure.

set -uo pipefail
REPO="${1:-/home/ubuntu/davis_root/superpowers}"
SRC="$REPO/fleet/src"
rc=0

say() {  # gap verdict claim
  printf '%-5s %-8s %s\n' "$1" "$2" "$3"
  [ "$2" = HOLDS ] || rc=1
}

echo "# brief re-verification — $(TZ=UTC date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "# repo:   $REPO"
echo "# tip:    $(git -C "$REPO" rev-parse --short HEAD) on $(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
echo "# tree:   $( [ -z "$(git -C "$REPO" status --porcelain)" ] && echo CLEAN || echo DIRTY )"
echo

# ---------------------------------------------------------------- G-1 no verb owns pane delivery
# The claim is an ABSENCE, so assert the absence directly: no `send-keys` string literal reaches tmux
# from inside the package. Comments and docstrings mentioning it do not implement it.
pkg_sends=$(grep -rn "send-keys" "$SRC"/fleet/*.py | grep -vc '^\s*[0-9]*:\s*#\|"""\|#:')
if [ "$(grep -rn "send-keys" "$SRC"/fleet/*.py | grep -c "subprocess\|run(\|tmux(" )" = 0 ]; then
  say G-1 HOLDS "no send-keys invocation anywhere in fleet/src — the package gates a send it cannot perform ($pkg_sends textual mentions, all prose)"
else
  say G-1 MOVED "something in fleet/src now invokes send-keys — G-1's premise (no implementation) is stale"
fi

# ---------------------------------------------------------------- A-2 the "six send paths" count
# `cli.py:153` attributes the count to `DA-2`. Check whether DA-2 actually enumerates them, and count the
# real in-repo implementations. If the number has no source, G-1's migration list is aimed at nothing.
DA2=/home/ubuntu/davis_root/operations/tasks/metaOpt/design-20260730-fleetInfraRefactor/09-OPEN-QUESTIONS.md
real_sends=$(grep -rln "send-keys" "$REPO" --include="*.sh" 2>/dev/null \
             | xargs -r grep -ln "tmux send-keys\|ptmux send-keys\|it_tmux send-keys" 2>/dev/null | sort | wc -l)
if [ -f "$DA2" ] && grep -q "DA-2.*WITHDRAWN" "$DA2"; then
  say A-2 REFUTED "DA-2 is WITHDRAWN/REFUTED in its own register and enumerates NO send paths; the count 6 traces only back to the cli.py:153 comment that cites it. Real in-repo implementations today: $real_sends file(s), both test-harness"
else
  say A-2 MOVED "DA-2's text no longer matches what was checked on 2026-08-03 — re-read $DA2 before trusting the count"
fi

# ---------------------------------------------------------------- G-2 nothing ACTS on the judgement
# `--include="*.py"` matters: without it `grep -rl` matches __pycache__/*.pyc and the row recites compiled
# copies of the same three files as if they were extra consumers.
consumers=$(grep -rl --include="*.py" --include="*.sh" --include="*.md" \
              "ACTIONABLE_STATES\|needs_a_human" "$SRC" "$REPO/scripts" "$REPO/skills" "$REPO/bin" 2>/dev/null \
            | grep -v "$SRC/fleet/reconcile.py" | sort)
outside=$(echo "$consumers" | grep -vc "$SRC/fleet/" || true)
if [ "$outside" -eq 0 ]; then
  say G-2 HOLDS "every consumer of the actionable judgement is a VIEW inside the package ($(echo "$consumers" | xargs -n1 basename | tr '\n' ' ')); nothing outside fleet reads it and nothing acts on it"
else
  say G-2 MOVED "$outside consumer(s) outside fleet/src now read the judgement — check whether one of them actuates"
fi

# ---------------------------------------------------------------- G-2 the tuple detection half shipped
tuple=$(cd "$REPO/fleet" && PYTHONPATH=src python3 -c "from fleet.reconcile import ACTIONABLE_STATES; print(ACTIONABLE_STATES)")
if [ "$tuple" = "('BLOCKED', 'IDLE')" ]; then
  say G-2 HOLDS "ACTIONABLE_STATES = $tuple — FI-14's detection half is still in place, so this gap is still only the actuation half"
else
  say G-2 MOVED "ACTIONABLE_STATES = $tuple, not ('BLOCKED', 'IDLE') — the tuple moved; see the non-negotiable 'never change it twice without measuring' constraint"
fi

# ---------------------------------------------------------------- G-4 the discriminator is uncollected
if [ "$(grep -rn "session_attached" "$SRC" "$REPO/fleet/tests" 2>/dev/null | wc -l)" = 0 ]; then
  say G-4 HOLDS "#{session_attached} appears nowhere in the package or its tests — the discriminator is still uncollected"
else
  say G-4 MOVED "session_attached is now referenced — someone started collecting it; reconcile the brief"
fi

# ---------------------------------------------------------------- G-7 the refusal names no route
refusal=$(grep -n "refusing to shadow it" "$SRC/fleet/roadmap.py")
if [ -n "$refusal" ] && ! echo "$refusal" | grep -qi "propose"; then
  say G-7 HOLDS "the anti-shadowing refusal (roadmap.py:${refusal%%:*}) still states its rule and names no route"
else
  say G-7 MOVED "the refusal text changed — re-read it before writing the clause"
fi

# ---------------------------------------------------------------- G-7 the false claim is IN THE SOURCE
# Not only in the commit message and QI-11: `Roadmap.retire`'s docstring argues the single-writer carve-out
# FROM the false premise. That is the copy a future reader actually hits.
if grep -q "no way to do this\|and no third one" "$SRC/fleet/roadmap.py"; then
  say G-7 HOLDS "Roadmap.retire's docstring still asserts 'no way to do this ... and no third one' — the refuted premise is live IN THE SHIPPED SOURCE, not only in bd69a7f's message"
else
  say G-7 MOVED "the docstring's premise was already corrected — check what it says now"
fi

# ---------------------------------------------------------------- G-8 no landing terminal status
vocab=$(cd "$REPO/fleet" && PYTHONPATH=src python3 -c "
import fleet.roadmap as r
print('%s|%s|%s' % (r.STATUSES, r.LANDED, r.TERMINAL))")
landed=${vocab#*|}; landed=${landed%%|*}
if [ "$landed" = "('done',)" ]; then
  say G-8 HOLDS "LANDED = $landed — 'done' is the ONLY status that satisfies a dependent, so a decision-resolved milestone must still overstate or strand. Full vocab: $vocab"
else
  say G-8 MOVED "LANDED = $landed — the landing set widened; re-measure readiness on a real roadmap before touching it again"
fi

# ---------------------------------------------------------------- G-3 the charter boots empty
tpl="$REPO/skills/using-fleet/profiles/worker/charter.md"
if sed -n '/^## Scope/,/^## Acceptance/p' "$tpl" | grep -q "The coordinator replaces this per milestone"; then
  say G-3 HOLDS "the worker charter template's authoritative Scope section is still a comment addressed to the coordinator, and Acceptance criteria is still empty"
else
  say G-3 MOVED "the charter template changed — FI-13 edited these files recently; re-read before designing"
fi

# ---------------------------------------------------------------- G-5 no mutation beyond M9
muts=$(ls "$REPO/fleet/it" | grep -c "^run-.*mutation.*\.sh$")
if [ "$muts" = 1 ]; then
  say G-5 HOLDS "exactly one mutation runner exists (run-m9-mutation.sh, the PATTERN); no case in the sampled frame has been shown to fail — J7 and J2 are still unproven"
else
  say G-5 MOVED "$muts mutation runners now exist — someone started the frame; check what is already covered"
fi

echo
if [ $rc -eq 0 ]; then
  echo "VERDICT: every open brief's premise HOLDS at $(git -C "$REPO" rev-parse --short HEAD)."
else
  echo "VERDICT: at least one premise MOVED or was REFUTED. Correct the brief BEFORE designing the fix —"
  echo "         a fix aimed at a premise that moved is the failure A-1 exists to prevent."
fi
exit $rc
