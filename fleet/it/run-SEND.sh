#!/usr/bin/env bash
# §SEND — `fleet send` against a REAL agent pane: a multi-line message is delivered, confirmed and RECORDED.
#
# B13 + FB-27. Before this section nothing in the harness ever called `fleet send` (`grep 'fleet send' run-*.sh`
# found no case; `runtime-live.py` sends a 3-line message and is opt-in). FB-27 happened on every multi-line
# coordinator send in production because both TUIs replace a paste of 4+ lines (Claude Code) or > ~1000 chars
# (codex) with a COUNT-SUMMARY placeholder — `[Pasted text #N +M lines]` / `[Pasted Content C chars]` — and the
# verb's "the observed draft is the message" check could never hold, so it timed out without sending Enter.
# B13: the verb wrote nothing down, so "who wrote into this pane" had no subject.
#
# What this section measures, on a PRIVATE tmux server and a PRIVATE store, with a real dispatch:
#   SEND-1  a one-line send is submitted (the control: the path that always worked)
#   SEND-2  a FIVE-line send is submitted and confirmed by the verb on its own — no human Enter
#   SEND-3  every send that reached the pane is recorded in the worker's `.fleet/sends.jsonl` with the sender,
#           the time, the message digest and the outcome, and `fleet brief` reads it back
#   SEND-4  a pane already holding a draft is still REFUSED (the guarded-messaging rule survives the fix)
#   SENDC-1..3  the same on a CODEX pane: one line; EIGHT lines (an inline draft taller than the observer's
#           old 8-row window); a > 1000-char message (codex's placeholder). Opt-in: needs an authenticated
#           PRIVATE codex home in SEND_CODEX_HOME (FB-102: never the root's shared ~/.codex).
#
# Spends a real model's turns (each send asks for the one-word reply "OK"). Gated like §P: FLEET_IT_ALLOW_CLAUDE=1.
# Run: FLEET_IT_ALLOW_CLAUDE=1 [SEND_CODEX_HOME=/private/codex/home] bash fleet/it/run-SEND.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'SEND-[0-9]+|SENDC-[0-9]+|ISOLATION-SEND(C)?-(enter|leave)'

REAL_CLAUDE="${P_REAL_CLAUDE:-/home/ubuntu/.local/bin/claude}"
REAL_CODEX="${SEND_REAL_CODEX:-$(command -v codex 2>/dev/null || true)}"
READY_TIMEOUT="${SEND_READY_TIMEOUT:-120}"

# ---- helpers ----------------------------------------------------------------------------------------
send_wait_ready() {   # send_wait_ready <tmux session> <marker regex> -> 0 when the pane shows the marker AND pane-guard says 0
  local name="$1" marker="$2" deadline=$(( $(date +%s) + READY_TIMEOUT ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if it_tmux capture-pane -p -t "$name" 2>/dev/null | grep -Eq "$marker"; then
      fleet pane-guard --pane "$name" >/dev/null 2>&1 && return 0
    fi
    sleep 2
  done
  return 1
}
send_wait_idle() {    # send_wait_idle <tmux session> -> 0 when pane-guard says 0 (turn over, box empty)
  local name="$1" deadline=$(( $(date +%s) + READY_TIMEOUT ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    fleet pane-guard --pane "$name" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}
send_profile() {      # send_profile <dir>: the smallest worker profile — a fixture that answers, never works
  mkdir -p "$1"
  printf '{"kind":"worker","placeholders":["TITLE","BASE"],"requires_clauses":[],"invocation_templates":[]}\n' > "$1/profile.json"
  cat > "$1/charter.md" <<'CH'
# CHARTER — {{TITLE}}
Base {{BASE}}. Instant {{PATH}}. A messaging fixture: it answers and does nothing else.
CH
  cat > "$1/seed.txt" <<'SEED'
You are a TEST FIXTURE for `fleet send` (instant {{PATH}}, milestone {{MILESTONE}}, coordinator {{COORDINATOR}}).
Reply with the single word READY and nothing else. For EVERY later message, reply with the single word OK and
nothing else. Do not run any tool, do not read any file, do not ask any question, do not write anything.
SEED
}
send_setup() {        # send_setup <section> <runtime> -> COORD, SLOT, PROFILE, OUT set; exit 2 on failure
  it_section "$1"
  it_fresh_store
  OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
  export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
  #: The slot must NOT sit inside a git repository. Claude Code keys its folder trust by the enclosing repo's
  #: toplevel (else by the folder and its ancestors), so a slot under this checkout shows the folder-trust
  #: screen (`pane-guard` 15) to a worker that never answers it — measured on the first run of this section
  #: (w1sendrecords, evidence/01-red/run-SEND-red.log: "Is this a project you created or one you trust?").
  #: A folder beside the checkout, under an ancestor the operator already trusts, opens straight into the
  #: prompt. Codex keys trust the same way (D-35), and the codex half writes its own trust entry for it.
  #: Overridable: SEND_SLOT_PARENT=<a trusted, non-repo directory>.
  SLOT_PARENT="${SEND_SLOT_PARENT:-$(cd "$(git -C "$IT_ROOT" rev-parse --show-toplevel 2>/dev/null || echo "$IT_ROOT/../..")/.." && pwd)}"
  SLOT="$SLOT_PARENT/send-fixture-slot-$1-$$"; rm -rf "$SLOT"; mkdir -p "$SLOT"
  echo "slot: $SLOT" > "$OUT/setup-slot.txt"
  #: RV-42. The teardown is armed the moment something exists outside the checkout, so a setup failure
  #: below (or a source-pin refusal) cannot leave a fixture slot in the operator's workspace directory.
  W_PID=""; TODO=""; TMUXN=""
  trap 'send_teardown' EXIT
  PROFILE="$OUT/profile"; send_profile "$PROFILE"
  COORD="$(fleet init --base 00000000 --name sendCoord --porcelain | awk -F'\t' '$1=="path"{print $2}')"
  [ -n "$COORD" ] && [ -d "$COORD" ] || { echo "send_setup: fleet init produced no coordinator" >&2; return 2; }
  fleet milestone --instant "$COORD" --id s1 --title "answer messages" > "$OUT/setup-milestone.out" 2>&1 \
    || { echo "send_setup: fleet milestone failed: $(head -2 "$OUT/setup-milestone.out" | tr '\n' ' ')" >&2; return 2; }
  fleet set-golden --path "$SLOT" > "$OUT/setup-golden.out" 2>&1 \
    || { echo "send_setup: set-golden failed: $(head -2 "$OUT/setup-golden.out" | tr '\n' ' ')" >&2; return 2; }
  fleet enroll --slot "$SLOT" >> "$OUT/setup-golden.out" 2>&1 \
    || { echo "send_setup: enroll failed: $(tail -2 "$OUT/setup-golden.out" | tr '\n' ' ')" >&2; return 2; }
  if [ "$2" = codex ]; then
    fleet runtime --set codex > "$OUT/setup-runtime.out" 2>&1 || { cat "$OUT/setup-runtime.out"; return 2; }
  fi
}
send_dispatch() {     # send_dispatch <title> -> W, TODO, TMUXN, W_PID; exit 1 on failure
  fleet dispatch --profile "$PROFILE" --title "$1" --base 00000000 --optype append \
        --from "$COORD" --milestone s1 --porcelain > "$OUT/dispatch.out" 2>&1
  local rc=$?
  W="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/dispatch.out")"
  TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/dispatch.out")"
  TMUXN="$(awk -F'\t' '$1=="tmux"{print $2}' "$OUT/dispatch.out")"
  [ "$rc" = 0 ] && [ -n "$W" ] && [ -d "$W" ] && [ -n "$TMUXN" ] || return 1
  W_PID="$(it_tmux list-panes -t "$TMUXN" -F '#{pane_pid}' 2>/dev/null | head -1)"
  return 0
}
send_case() {         # send_case <case id> <message file> -> writes <case>-send.out, <case>-pane.txt; rc of fleet send
  local case="$1" file="$2"
  fleet send --id "$TODO" --message-file "$file" --by "run-SEND.sh" --porcelain > "$OUT/$case-send.out" 2>&1
  local rc=$?
  sleep 1
  it_tmux capture-pane -e -p -t "$TMUXN" > "$OUT/$case-pane.txt" 2>&1 || true
  echo "$rc" > "$OUT/$case-send.rc"
  return "$rc"
}
send_clear_box() {    # after a FAILED case: empty whatever the verb left in the box so the next case measures its own draft
  local tries=0
  while [ "$tries" -lt 25 ]; do
    fleet pane-guard --pane "$TMUXN" >/dev/null 2>&1 && return 0
    it_tmux send-keys -t "$TMUXN" C-u; sleep 0.5; tries=$((tries+1))
  done
  return 1
}
send_teardown() {     # close + harvest the worker; never leaves the pane behind (FB-15/FB-73)
  local guard=11 waited=0
  if [ -z "${TMUXN:-}" ]; then      # setup failed before a dispatch: only the slot and the server can exist
    it_cleanup_tmux; it_tmux kill-server 2>/dev/null
    case "${SLOT:-}" in */send-fixture-slot-*) rm -rf "$SLOT" ;; esac
    return 0
  fi
  while [ "$waited" -lt 20 ]; do
    fleet pane-guard --pane "$TMUXN" > "$OUT/teardown-guard.out" 2>&1; guard=$?
    case "$guard" in 10|11) : ;; *) break ;; esac
    sleep 3; waited=$((waited+1))
  done
  fleet close --id "$TODO" --force --porcelain > "$OUT/teardown-close.out" 2>&1
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -n "${W_PID:-}" ] && kill -0 "$W_PID" 2>/dev/null || break
    sleep 2
  done
  fleet harvest --id "$TODO" --porcelain > "$OUT/teardown-harvest.out" 2>&1
  it_cleanup_tmux
  it_tmux kill-server 2>/dev/null
  #: The slot lives OUTSIDE the checkout (see send_setup); nothing else removes it.
  case "${SLOT:-}" in */send-fixture-slot-*) rm -rf "$SLOT" ;; esac
  #: RV-43 / FB-102: the private codex home holds a COPY of a credential; it must not outlive the run in a
  #: slot that will be re-leased.
  case "${CODEX_HOME:-}" in */codex-home) rm -rf "$CODEX_HOME" ;; esac
  case "${SEND_RELEASES:-}" in */tmp.*) rm -rf "$SEND_RELEASES" ;; esac
}
record_check() {      # record_check <child instant> <expected count> <outcome regex> [confirmations, comma-joined, one per row]
  #: RV-21. The CONFIRMATION per row is asserted, not only the outcome: a green SEND-2 that does not say
  #: `placeholder` is also consistent with some other way of delivering the message — the "alarm stopped
  #: firing" shape — and the first (killed) GREEN attempt PASSed SEND-2 with "placeholder seen: 0".
  python3 - "$1" "$2" "$3" "${4:-}" <<'PY'
import hashlib, json, pathlib, re, sys
child, want_n, want_outcome, want_conf = pathlib.Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
path = child / '.fleet' / 'sends.jsonl'
if not path.is_file():
    print(f'ABSENT {path}'); sys.exit(1)
rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
print(f'{len(rows)} row(s) in {path}')
ok = len(rows) == want_n
confirmations = want_conf.split(',') if want_conf else []
if confirmations and len(confirmations) != want_n:
    print(f'HARNESS ERROR: {len(confirmations)} expected confirmation(s) for {want_n} row(s)'); ok = False
for index, row in enumerate(rows):
    print(json.dumps(row, sort_keys=True))
    for key in ('at', 'by', 'todo_id', 'tmux', 'runtime', 'sha256', 'chars', 'lines', 'head', 'outcome', 'confirmation', 'schema_version'):
        if key not in row:
            print(f'MISSING key {key}'); ok = False
    if not re.fullmatch(want_outcome, str(row.get('outcome'))):
        print(f'OUTCOME {row.get("outcome")!r} does not match {want_outcome!r}'); ok = False
    if index < len(confirmations) and row.get('confirmation') != confirmations[index]:
        print(f'CONFIRMATION row {index + 1}: {row.get("confirmation")!r}, wanted {confirmations[index]!r}'); ok = False
    src = row.get('message_file')
    if src and pathlib.Path(src).is_file():
        digest = hashlib.sha256(pathlib.Path(src).read_text().encode()).hexdigest()
        if digest != row.get('sha256'):
            print(f'SHA mismatch for {src}'); ok = False
    else:
        #: RV-44. The pass text claims the digest was re-derived; a row whose file is gone cannot be, and
        #: saying nothing would let the claim stand on a check that never ran.
        print(f'SHA NOT RE-DERIVED: message_file {src!r} is not a file'); ok = False
sys.exit(0 if ok else 1)
PY
}

# ---- claude ------------------------------------------------------------------------------------------
if [ "${FLEET_IT_ALLOW_CLAUDE:-0}" != 1 ]; then
  it_section SEND
  it_skip SEND-1 "" "dispatches a real claude and spends the allowance; set FLEET_IT_ALLOW_CLAUDE=1 to run"
  it_assert_isolation SEND-leave
  echo "§SEND skipped"; exit 0
fi
if [ ! -x "$REAL_CLAUDE" ]; then
  it_section SEND
  it_skip SEND-1 "" "no real claude at $REAL_CLAUDE"
  it_assert_isolation SEND-leave
  echo "§SEND skipped"; exit 0
fi

send_setup SEND claude || exit 2
bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2
export FLEET_CLAUDE_BIN="$REAL_CLAUDE"
#: As §P: the real binary needs a real, authenticated config, so the resolver's own map decides (the operator's).
if [ -n "${P_CLAUDE_OWNERS_MAP:-}" ]; then export CLAUDE_OWNERS_MAP="$P_CLAUDE_OWNERS_MAP"; else unset CLAUDE_OWNERS_MAP; fi

if ! send_dispatch sendFixture; then
  it_fail SEND-1 "fleet/it/SEND/out/dispatch.out" "the real dispatch failed: $(head -3 "$OUT/dispatch.out" | tr '\n' ' ')"
  it_assert_isolation SEND-leave; exit 1
fi
if ! send_wait_ready "$TMUXN" 'READY'; then
  it_tmux capture-pane -p -t "$TMUXN" > "$OUT/not-ready-pane.txt" 2>&1 || true
  it_fail SEND-1 "fleet/it/SEND/out/not-ready-pane.txt" "the fixture worker never became idle showing READY within ${READY_TIMEOUT}s"
  it_assert_isolation SEND-leave; exit 1
fi

M1="$OUT/m1.txt"; printf 'Reply OK.\n' > "$M1"
M2="$OUT/m2.txt"; printf 'Reply OK.\nThis message has five lines on purpose.\nLine three.\nLine four.\nLine five, the last one.\n' > "$M2"

# ---- SEND-1: the control -----------------------------------------------------------------------------
send_case SEND-1 "$M1"; s1=$?
if [ "$s1" = 0 ] && grep -q $'^delivery\tsubmitted$' "$OUT/SEND-1-send.out" && send_wait_idle "$TMUXN"; then
  it_pass SEND-1 "fleet/it/SEND/out/SEND-1-send.out" "a one-line \`fleet send\` into a real claude pane exited 0 with delivery=submitted and the pane returned to idle with an empty box (the control: the path that always worked)"
else
  it_fail SEND-1 "fleet/it/SEND/out/SEND-1-send.out" "the one-line control send did not submit: rc=$s1 $(tr '\n' ' ' < "$OUT/SEND-1-send.out" | cut -c1-200)"
fi

# ---- SEND-2: five lines, on its own ------------------------------------------------------------------
send_case SEND-2 "$M2"; s2=$?
s2_idle=0; send_wait_idle "$TMUXN" && s2_idle=1
it_tmux capture-pane -e -p -t "$TMUXN" > "$OUT/SEND-2-pane-after.txt" 2>&1 || true
s2_placeholder=0; grep -q 'Pasted text' "$OUT/SEND-2-pane.txt" && s2_placeholder=1
if [ "$s2" = 0 ] && grep -q $'^delivery\tsubmitted$' "$OUT/SEND-2-send.out" && [ "$s2_idle" = 1 ]; then
  it_pass SEND-2 "fleet/it/SEND/out/SEND-2-send.out" "a FIVE-line \`fleet send\` into a real claude pane exited 0 with delivery=submitted and the pane returned to idle with an empty box — the verb delivered, confirmed and submitted a multi-line message on its own, with no human Enter (FB-27: before the fix this exited 1 'Delivery uncertain after insertion' and left Claude Code's '[Pasted text #N +4 lines]' placeholder unsubmitted; placeholder seen in the box during the send: $s2_placeholder)"
else
  it_fail SEND-2 "fleet/it/SEND/out/SEND-2-send.out" "the five-line send was not submitted on its own: rc=$s2 idle_after=$s2_idle placeholder_in_box=$s2_placeholder — $(tr '\n' ' ' < "$OUT/SEND-2-send.out" | cut -c1-200)"
  # the box is captured as the verb left it (SEND-2-pane.txt); clear it so SEND-4 measures its own draft
  send_clear_box || BOX_DIRTY=1
fi

# ---- SEND-3: the record ------------------------------------------------------------------------------
record_check "$W" 2 'submitted' 'draft,placeholder' > "$OUT/SEND-3-record.txt" 2>&1; s3=$?
fleet brief --instant "$W" --porcelain > "$OUT/SEND-3-brief.out" 2>&1
#: RV-44. Every messages row carries the word "submitted" ("N submitted, M uncertain"); the check must be
#: able to fail, so it wants the COUNT this section produced and the last outcome.
s3_brief=0; awk -F'\t' '$1=="messages"' "$OUT/SEND-3-brief.out" | grep -q '2 message(s) recorded.*(2 submitted, 0 uncertain).*: submitted (confirmed by placeholder)' && s3_brief=1
if [ "$s3" = 0 ] && [ "$s3_brief" = 1 ]; then
  it_pass SEND-3 "fleet/it/SEND/out/SEND-3-record.txt" "both sends are RECORDED in the worker's .fleet/sends.jsonl — sender, time, pane, sha256 of the message (re-derived from the file and matching), chars/lines/head, outcome=submitted and HOW each was confirmed (SEND-1 by the draft read back, SEND-2 by the paste placeholder's count — so the FB-27 branch is what submitted the five lines) — and \`fleet brief --instant <worker>\` reads them back on its 'messages' row (B13: before the fix \`_do_send\` wrote nothing, so 'who wrote into this pane' had no subject)"
else
  it_fail SEND-3 "fleet/it/SEND/out/SEND-3-record.txt" "the send record is missing or wrong: record_rc=$s3 brief_row=$s3_brief — $(head -2 "$OUT/SEND-3-record.txt" | tr '\n' ' ')"
fi

# ---- SEND-4: the guard survives — a pane holding a draft is refused ------------------------------------
#: RV-41. A case whose box could not be emptied after the previous failure is NOT measured: at the base,
#: SENDC-3 was refused for SENDC-2's leftover draft and read as its own failure.
if [ "${BOX_DIRTY:-0}" = 1 ]; then
  it_skip SEND-4 "fleet/it/SEND/out/SEND-2-pane-after.txt" "not measured: the box could not be emptied after SEND-2 failed, so a refusal here would be SEND-2's leftover draft, not this case's"
  s4=skipped; s4_kept=0
else
  it_tmux send-keys -t "$TMUXN" -l 'somebody else is typing here'; sleep 1
  send_case SEND-4 "$M2"; s4=$?
  s4_kept=0; grep -q 'somebody else is typing here' "$OUT/SEND-4-pane.txt" && ! grep -q 'Pasted text' "$OUT/SEND-4-pane.txt" && s4_kept=1
fi
if [ "$s4" = skipped ]; then
  :
elif [ "$s4" = 4 ] && [ "$s4_kept" = 1 ]; then
  it_pass SEND-4 "fleet/it/SEND/out/SEND-4-send.out" "with a human's draft in the box, the five-line send was REFUSED (exit 4) and typed nothing: the draft is still there alone, no placeholder beside it — the guarded-messaging rule (never submit into a pane holding someone else's draft) survives the multi-line fix"
else
  it_fail SEND-4 "fleet/it/SEND/out/SEND-4-send.out" "a pane holding a draft was not refused cleanly: rc=$s4 draft_intact=$s4_kept"
fi
send_clear_box
if record_check "$W" 2 'submitted' 'draft,placeholder' > "$OUT/SEND-5-record.txt" 2>&1; then
  it_pass SEND-5 "fleet/it/SEND/out/SEND-5-record.txt" "the refused send added NO row: the log records what was written into the pane, and a refusal before the paste wrote nothing"
else
  it_fail SEND-5 "fleet/it/SEND/out/SEND-5-record.txt" "the send log changed on a refused send: $(head -1 "$OUT/SEND-5-record.txt")"
fi

send_teardown; trap - EXIT
it_assert_isolation SEND-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }

# ---- codex (opt-in) ------------------------------------------------------------------------------------
if [ -z "${SEND_CODEX_HOME:-}" ] || [ ! -f "${SEND_CODEX_HOME}/auth.json" ] || [ -z "$REAL_CODEX" ] || [ ! -x "$REAL_CODEX" ]; then
  it_section SENDC
  it_skip SENDC-1 "" "no authenticated PRIVATE codex home in SEND_CODEX_HOME (needs auth.json) or no codex binary; the codex half did not run"
  it_assert_isolation SENDC-leave
  echo "§SEND done (codex half skipped): IT_FAILED=$IT_FAILED"; exit "$IT_FAILED"
fi
send_setup SENDC codex || exit 2
bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2
#: FB-102: a PRIVATE codex home per fixture, built here from the supplied one — auth only, our own config, and a
#: trust entry for the slot (codex keys trust by the git toplevel when inside a repo, else the exact folder; D-35).
export CODEX_HOME="$EV/codex-home"; rm -rf "$CODEX_HOME"; mkdir -p "$CODEX_HOME"; chmod 700 "$CODEX_HOME"
cp "$SEND_CODEX_HOME/auth.json" "$CODEX_HOME/auth.json"; chmod 600 "$CODEX_HOME/auth.json"
TRUST_KEY="$(git -C "$SLOT" rev-parse --show-toplevel 2>/dev/null || echo "$SLOT")"
{ [ -f "$SEND_CODEX_HOME/config.toml" ] && grep -E '^(approval_policy|sandbox_mode|model_reasoning_effort|model) *=' "$SEND_CODEX_HOME/config.toml"
  printf '\n[projects."%s"]\ntrust_level = "trusted"\n' "$TRUST_KEY"; } > "$CODEX_HOME/config.toml"
#: FB-111: a codex dispatch is refused when CODEX_HOME cannot see the superpowers skills. Link them in the way a root
#: does, through a releases area OUTSIDE the checkout (a `current -> checkout` link inside it is an rglob cycle).
SEND_RELEASES="$(mktemp -d)"
ln -s "$(cd "$IT_ROOT/../.." && pwd)" "$SEND_RELEASES/current"
if ! bash "$IT_ROOT/../../scripts/fleet-codex-skills.sh" --codex-home "$CODEX_HOME" --releases "$SEND_RELEASES" \
     > "$OUT/codex-skills.txt" 2>&1; then
  it_fail SENDC-1 "fleet/it/SENDC/out/codex-skills.txt" "SETUP, not a verdict: the codex skills link could not be installed"
  it_assert_isolation SENDC-leave; exit 1
fi
export FLEET_CODEX_BIN="$REAL_CODEX"
if ! send_dispatch sendCodexFixture; then
  it_fail SENDC-1 "fleet/it/SENDC/out/dispatch.out" "the real codex dispatch failed: $(head -3 "$OUT/dispatch.out" | tr '\n' ' ')"
  it_assert_isolation SENDC-leave; exit 1
fi
if ! send_wait_ready "$TMUXN" 'READY'; then
  it_tmux capture-pane -p -t "$TMUXN" > "$OUT/not-ready-pane.txt" 2>&1 || true
  it_fail SENDC-1 "fleet/it/SENDC/out/not-ready-pane.txt" "the codex fixture never became idle showing READY within ${READY_TIMEOUT}s"
  it_assert_isolation SENDC-leave; exit 1
fi
C1="$OUT/c1.txt"; printf 'Reply OK.\n' > "$C1"
C2="$OUT/c2.txt"; printf 'Reply OK.\nline two\nline three\nline four\nline five\nline six\nline seven\nline eight, the last one.\n' > "$C2"
#: A file as an editor or heredoc writes it: with a trailing newline. The RCA measured codex's placeholder
#: count on texts WITHOUT one (A2), so this case also measures whether the trailing newline is counted —
#: the count asserted below is DERIVED from the file, never typed (RV-40).
C3="$OUT/c3.txt"; python3 -c "print('Reply OK — ' + ('déjà·vu — ' * 100) + 'end')" > "$C3"
C3_CHARS="$(python3 -c "import sys; print(len(open(sys.argv[1], encoding='utf-8').read()))" "$C3")"
send_case SENDC-1 "$C1"; c1=$?
if [ "$c1" = 0 ] && grep -q $'^delivery\tsubmitted$' "$OUT/SENDC-1-send.out" && send_wait_idle "$TMUXN"; then
  it_pass SENDC-1 "fleet/it/SENDC/out/SENDC-1-send.out" "a one-line \`fleet send\` into a real codex pane exited 0 with delivery=submitted (the codex control)"
else
  it_fail SENDC-1 "fleet/it/SENDC/out/SENDC-1-send.out" "the codex one-line control did not submit: rc=$c1 $(tr '\n' ' ' < "$OUT/SENDC-1-send.out" | cut -c1-200)"
fi
send_case SENDC-2 "$C2"; c2=$?
c2_idle=0; send_wait_idle "$TMUXN" && c2_idle=1
if [ "$c2" = 0 ] && grep -q $'^delivery\tsubmitted$' "$OUT/SENDC-2-send.out" && [ "$c2_idle" = 1 ]; then
  it_pass SENDC-2 "fleet/it/SENDC/out/SENDC-2-send.out" "an EIGHT-line \`fleet send\` into a real codex pane exited 0 with delivery=submitted: codex renders it inline, taller than the observer's old 8-row caret window, and the verb still saw its own draft and submitted it"
else
  it_fail SENDC-2 "fleet/it/SENDC/out/SENDC-2-send.out" "the eight-line codex send was not submitted: rc=$c2 idle_after=$c2_idle — $(tr '\n' ' ' < "$OUT/SENDC-2-send.out" | cut -c1-200)"
  send_clear_box || CBOX_DIRTY=1
fi
if [ "${CBOX_DIRTY:-0}" = 1 ]; then
  it_skip SENDC-3 "fleet/it/SENDC/out/SENDC-2-pane.txt" "not measured: the box could not be emptied after SENDC-2 failed (RV-41)"
  c3=skipped; c3_idle=0; c3_placeholder=0
else
  send_case SENDC-3 "$C3"; c3=$?
  c3_idle=0; send_wait_idle "$TMUXN" && c3_idle=1
  c3_placeholder=0; grep -q 'Pasted Content' "$OUT/SENDC-3-pane.txt" && c3_placeholder=1
fi
if [ "$c3" = skipped ]; then
  :
elif [ "$c3" = 0 ] && grep -q $'^delivery\tsubmitted$' "$OUT/SENDC-3-send.out" && [ "$c3_idle" = 1 ]; then
  it_pass SENDC-3 "fleet/it/SENDC/out/SENDC-3-send.out" "a ${C3_CHARS}-character non-ASCII \`fleet send\` (trailing newline included, as an editor writes a file) into a real codex pane exited 0 with delivery=submitted: codex shows '[Pasted Content ${C3_CHARS} chars]' for it (placeholder seen in the box: $c3_placeholder) and the verb confirmed the count against the message and submitted"
else
  it_fail SENDC-3 "fleet/it/SENDC/out/SENDC-3-send.out" "the over-length codex send was not submitted: rc=$c3 idle_after=$c3_idle placeholder=$c3_placeholder — $(tr '\n' ' ' < "$OUT/SENDC-3-send.out" | cut -c1-200)"
fi
if [ "$c3" != 0 ]; then send_clear_box || true; fi
if record_check "$W" 3 'submitted' 'draft,draft,placeholder' > "$OUT/SENDC-4-record.txt" 2>&1; then
  it_pass SENDC-4 "fleet/it/SENDC/out/SENDC-4-record.txt" "all three codex sends are recorded in the worker's .fleet/sends.jsonl as submitted, with the sender, time, sha256 (re-derived and matching) and how each was confirmed — the one-line and eight-line sends by the draft read back, the over-length one by codex's '[Pasted Content C chars]' placeholder"
else
  it_fail SENDC-4 "fleet/it/SENDC/out/SENDC-4-record.txt" "codex sends were not all recorded as submitted: $(head -2 "$OUT/SENDC-4-record.txt" | tr '\n' ' ')"
fi
send_teardown; trap - EXIT
it_assert_isolation SENDC-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
echo "§SEND done: IT_FAILED=$IT_FAILED"
exit "$IT_FAILED"
