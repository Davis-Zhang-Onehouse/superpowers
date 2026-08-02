#!/usr/bin/env bash
# Plan 6 §C — pool and workspace contents (13 cases). plans/plan-6-integration-tests.md:101-118.
#
# WHAT IS REAL HERE, AND WHAT IS NOT
# ----------------------------------
# Everything this section asserts runs against a real filesystem, a real git, a real /proc and (for C7)
# a real tmux server. Nothing is injected except where the product itself has no other entry point:
#
#   * `pool.claim` / `pool.release` have NO verb. `dispatch` is the only caller of `claim`, and the only
#     caller of `release` reachable from a command line is `unenroll --force`, which passes force=True
#     and so cannot exercise the OBS-48 refusal C6 is about. So C5/C6 drive `fleet.pool.Pool` directly
#     through `py/poolctl.py`, which wires the pool EXACTLY as `cli.default_context` does — the same
#     `cli._cwd_holders` probe and the same `SessionLayer(default_probes()).alive` — so the code under
#     test is the production wiring and only the entry point differs. Reported as a finding, not
#     silently worked around.
#   * `workspace.isolate_build_cache` (C11) and `workspace.base_check` (C12/C13) likewise have no verb;
#     `isolate_build_cache`'s only caller is inside `_do_dispatch`, past the point where a `dt-` session
#     is started. `py/wscheck.py` calls them directly with the real `default_git()`.
#   * Every exit code C1–C4 and C7–C9 assert comes from a REAL `python3 -m fleet.cli` subprocess.
#
# ISOLATION
# ---------
# `dispatch` hardcodes `tmux = f"dt-{name}"` and `ctx.sessions.start(...)`, and this section is forbidden
# to create a `dt-` session at all. That is compatible with C3/C4 only because `pool.claim` (C3) and the
# `pool-capacity` guard (C4) both raise BEFORE `_do_dispatch` reaches `sessions.start` — so the two
# dispatches this file runs are asserted to have created no session and no instant folder, on top of the
# section's live-server comparison. No dispatch here is ever expected to succeed, which is why no `dt-`
# session can be born. C10 needs a SUCCEEDING dispatch and is therefore unrunnable under this contract —
# see c10 below, where that is one of two independent reasons it cannot be asserted.
#
# Two composed layers, as §E/§K established: `-L itfleet-C` (via `it_tmux` and FLEET_TMUX_SOCKET, so the
# harness and the product agree which server they mean) AND a private TMUX_TMPDIR socket DIRECTORY, which
# is the layer that survives the first one being lost — `session.default_probes` degrades to a bare
# `tmux` when FLEET_TMUX_SOCKET is empty, and a bare `new-session` lands on the operator's server. The
# ordering rule that comes with TMUX_TMPDIR is honoured explicitly: reads of the LIVE server go through
# `c_live_tmux`, which is `env -u TMUX_TMPDIR tmux ls`, and TMUX_TMPDIR is unset before the leave-time
# `it_assert_isolation` (whose `it_live_tmux_sessions` is a bare `tmux ls`).
#
# C6 starts a REAL `sleep 300` inside a slot. Its pid is recorded in C_SLEEPS and killed BY PID from an
# EXIT/INT/TERM trap, so it cannot outlive this run however the run ends. Never `pkill`.
#
# Usage: IT_RESULTS=<file> bash fleet/it/run-C.sh [all|C1..C13]
set -uo pipefail

C_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$C_HERE/lib.sh"

#: NEVER the shared RESULTS.tsv — another runner owns it, and one register with two writers is
#: `FI-16`/`FI-29`'s own shape. `IT_RESULTS` is honoured so a concurrent run can be given its own file.
RESULTS="${IT_RESULTS:-$C_HERE/RESULTS-C.tsv}"
P_WORKER="$INSTANT/tests/fixtures/profiles/workerCompliant"
OURS=00000000
FOREIGN=07290101

IT_FAILED=0
C_SLEEPS=""
C_TMUX_BEFORE=""
C_CLAUDE_BEFORE=""

if [ ! -s "$RESULTS" ]; then
  printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"
fi

# --- recording: every evidence reference and every NOTE is INSTANT-RELATIVE -------------------------
#
# P-3 / `FI-32`. `bin/lint-evidence-paths.sh` rejects an absolute /tmp|/home|/var|/root path ANYWHERE in
# a results file, note text included — and a refusal message quoted into a note carries slot paths. So
# the scrub happens at the RECORDING boundary rather than at 13 call sites, for the same reason `it_tmux`
# exists instead of a rule about remembering `-L`.
c_rel() { case "${1:-}" in "$INSTANT"/*) printf '%s' "${1#"$INSTANT"/}" ;; *) printf '%s' "${1:-}" ;; esac; }
c_scrub() { printf '%s' "${1:-}" | sed -e "s|$INSTANT/||g" -e 's|/tmp/[^ ]*|(a private socket dir)|g' \
                                       -e "s|$HOME/|(home)/|g" | tr -d '\t' | tr '\n' ' '; }
c_pass() { it_pass "$1" "$(c_rel "${2:-}")" "$(c_scrub "${3:-}")"; }
c_fail() { it_fail "$1" "$(c_rel "${2:-}")" "$(c_scrub "${3:-}")"; }
c_skip() { it_skip "$1" "$(c_rel "${2:-}")" "$(c_scrub "${3:-}")"; }

#: The ONE bare-tmux reader in this file, used for the live-server pre- and post-image. Both are
#: READ-ONLY and both must stay on the DEFAULT server: a private-server read here would compare a
#: private server against a live pre-image, i.e. a vacuous compare. `env -u TMUX_TMPDIR` states that in
#: the call instead of leaving it to depend on statement order.
c_live_tmux() { env -u TMUX_TMPDIR tmux ls -F '#{session_name}' 2>/dev/null | sort; }

# --- the C6 sleeper: tracked by pid, killed by pid, trapped ----------------------------------------

c_track_sleep() { C_SLEEPS="$C_SLEEPS ${1:?pid}"; }

#: Kills ONLY the pids this run recorded, by exact pid. Never `pkill sleep` — §E's `claude` stub is
#: `exec sleep 100000`, so a pattern kill here would reach another section's panes and the operator's.
c_kill_sleeps() {
  local pid
  for pid in $C_SLEEPS; do
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    kill -0 "$pid" 2>/dev/null || continue
    kill -TERM "$pid" 2>/dev/null
  done
  for pid in $C_SLEEPS; do
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    kill -0 "$pid" 2>/dev/null && { sleep 0.3; kill -KILL "$pid" 2>/dev/null; }
  done
  true
}

# --- section enter / leave -------------------------------------------------------------------------

c_enter() {
  it_section C                               # own FLEET_HOME, own slots, own socket; isolation asserted
  #: Short socket DIRECTORY: a long TMUX_TMPDIR overflows sun_path. Not evidence, and never named in a
  #: note (`c_scrub` masks it). The literal-prefix test is what makes the rm -rf below safe to read.
  C_SOCK="/tmp/itfC"
  case "$C_SOCK" in /tmp/itfC) rm -rf "$C_SOCK"; mkdir -p "$C_SOCK" ;; *) echo "refusing" >&2; exit 2 ;; esac
  C_TMUX_BEFORE="$(c_live_tmux)"                             # the LIVE server, deliberately
  C_CLAUDE_BEFORE="$(pgrep -x claude 2>/dev/null | wc -l)"
  export TMUX_TMPDIR="$C_SOCK"
  #: Defence in depth only: nothing in §C launches `claude` (no dispatch here is expected to succeed, so
  #: `sessions.start` is never reached). If one ever were, the stub is a real process that is not claude
  #: and `exec sleep`s, so `pgrep -x claude` stays comparable.
  export PATH="$C_HERE/bin:$PATH"
  mkdir -p "$EV/out" "$EV/py" "$EV/fixtures"
  printf '%s\n' "$C_TMUX_BEFORE" > "$EV/out/live-tmux-before.txt"
  printf '%s\n' "$C_CLAUDE_BEFORE" > "$EV/out/claude-count-before.txt"
}

#: Every session on the PRIVATE server. §C creates exactly one (C7's live worker) and it carries the
#: `itfleet-C` prefix, so the filter is real rather than "kill everything"; the socket name is re-checked
#: anyway. `=$s` is an EXACT target — `kill-session -t itfleet-C-a` resolves BY PREFIX (`FI-23`/`SI-2`).
c_kill_sessions() {
  case "${IT_TMUX_SOCKET:-}" in
    itfleet-C) ;;
    *) echo "c_kill_sessions: socket is '${IT_TMUX_SOCKET:-}', not itfleet-C — refusing." >&2; return 2 ;;
  esac
  it_tmux ls -F '#{session_name}' 2>/dev/null | grep "^${TMUX_PREFIX}" | while read -r s; do
    it_tmux kill-session -t "=$s" 2>/dev/null
  done
  true
}

#: However this run ends — normally, on a signal, or on an error — the real `sleep 300`s C6 starts and
#: the one pane C7 starts must not outlive it. Sleepers are killed BY RECORDED PID; the pane is killed
#: with its session on the private server, and only after the socket name has been re-checked.
c_cleanup() {
  c_kill_sleeps
  case "${IT_TMUX_SOCKET:-}" in itfleet-C) c_kill_sessions ;; esac
}
trap 'c_cleanup' EXIT INT TERM

c_leave() {
  c_kill_sessions
  c_kill_sleeps
  local after_claude after_tmux
  after_claude="$(pgrep -x claude 2>/dev/null | wc -l)"
  unset TMUX_TMPDIR                          # BEFORE it_assert_isolation's bare `tmux ls`
  after_tmux="$(c_live_tmux)"
  printf '%s\n' "$after_tmux" > "$EV/out/live-tmux-after.txt"
  printf '%s\n' "$after_claude" > "$EV/out/claude-count-after.txt"
  #: `II-1`. Was a private byte-comparison; now the shared classifier, so the isolation contract has one
  #: implementation instead of four. The case id stays so the register keeps a per-section row.
  #:
  #: §C needs nothing beyond the classifier: every session it starts is named `$TMUX_PREFIX-*`, i.e.
  #: `itfleet-C-*` (see `c_kill_sessions`), and a name of that shape appearing on the default server is
  #: precisely what the classifier FAILs on. That is not true of §D and §group3, whose sessions the
  #: product names `dt-*` — they carry `it_assert_no_private_leak` as well.
  local c_classified
  c_classified="$(it_classify_session_delta "$C_TMUX_BEFORE" "$after_tmux")"
  if [ "${c_classified%%|*}" = FAIL ]; then
    c_fail "ISOLATION-C-live-tmux" "$EV/out/live-tmux-after.txt" "${c_classified#*|}"
  else
    c_pass "ISOLATION-C-live-tmux" "$EV/out/live-tmux-after.txt" \
           "${c_classified#*|} ($(printf '%s' "$after_tmux" | grep -c .) sessions, incl. $(printf '%s' "$after_tmux" | grep -c '^dt-') dt-); §C starts only ${TMUX_PREFIX}-* sessions and only on socket $IT_TMUX_SOCKET"
  fi
  if [ "$after_claude" = "$C_CLAUDE_BEFORE" ]; then
    c_pass "ISOLATION-C-claude-count" "$EV/out/claude-count-after.txt" \
           "pgrep -x claude: $after_claude before and after (A6); §C starts none"
  else
    c_fail "ISOLATION-C-claude-count" "$EV/out/claude-count-after.txt" \
           "pgrep -x claude went $C_CLAUDE_BEFORE -> $after_claude; §C must launch none"
  fi
  it_assert_isolation "C-leave"
  case "${C_SOCK:-}" in /tmp/itfC) rm -rf "$C_SOCK" ;; esac
}

# --- per-case sandbox ------------------------------------------------------------------------------

#: One FLEET_HOME, one slots dir and one log dir per case. The rm -rf targets are built from $EV and
#: $C_TAG and both are checked non-empty first: a prior agent lost 1333 tracked files to an rm -rf built
#: from an unset variable.
c_home() {                      # c_home <tag> [n_slots]
  C_TAG="${1:?a case tag is required}"; local want="${2:-0}" i
  case "${EV:-}" in ""|/) echo "c_home: EV is unset — refusing to build a path from it" >&2; exit 2 ;; esac
  case "$EV" in "$IT_ROOT"/*) ;; *) echo "c_home: EV ($EV) is not under the harness root" >&2; exit 2 ;; esac
  export FLEET_HOME="$EV/home/$C_TAG"
  export FLEET_INSTANTS="$EV/instants/$C_TAG"
  C_SLOTS="$SLOTS/$C_TAG"
  CD="$EV/out/$C_TAG"
  rm -rf "$FLEET_HOME" "$FLEET_INSTANTS" "$C_SLOTS" "$CD"
  mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$C_SLOTS" "$CD"
  for i in $(seq 1 "$want"); do
    mkdir -p "$C_SLOTS/s$i"
    fleet enroll --slot "$C_SLOTS/s$i" >> "$CD/enroll.out" 2>&1
  done
}

c_pool() { python3 "$EV/py/poolctl.py" "$FLEET_HOME" "$@"; }
c_ws()   { python3 "$EV/py/wscheck.py" "$@"; }

# --- the two python entry points, written from here so this runner stays the single source ----------

c_write_helpers() {
  cat > "$EV/py/poolctl.py" <<'PY'
"""Drive `fleet.pool.Pool` with the PRODUCTION wiring, from a command line the package does not offer.

`pool.claim` and `pool.release` have no verb. `dispatch` is `claim`'s only caller and `unenroll --force`
is `release`'s, and the second passes force=True — so the OBS-48 cwd refusal (§C6) and the FI-22
idempotence contract (§C5) are unreachable from any command line. This is that command line, and it is
deliberately NOT a reimplementation: the pool is built with `cli._cwd_holders` and
`SessionLayer(default_probes()).alive`, which is literally what `cli.default_context` constructs, and the
exit code is `FleetError.exit_code` — the same attribute `cli.main` returns. Nothing here decides a
verdict; it prints what the pool did and exits with the pool's own code.
"""
import sys
from pathlib import Path

from fleet.cli import _cwd_holders
from fleet.errors import FleetError
from fleet.pool import Pool
from fleet.session import SessionLayer, default_probes


def pool_of(home):
    return Pool(Path(home), cwd_probe=_cwd_holders,
                alive=SessionLayer(default_probes()).alive)


def main(argv):
    home, action, rest = argv[0], argv[1], argv[2:]
    pool = pool_of(home)
    if action == "claim":
        slot, todo, tmux, base = rest[0], rest[1], rest[2], rest[3]
        lease = pool.claim(todo_id=todo, tmux=tmux, base_instant=base,
                           child_instant="(none — §C never launches a worker)", slot=slot)
        print(f"claimed slot={lease.slot} todo={lease.todo_id} tmux={lease.tmux} "
              f"base={lease.base_instant} ns={lease.claimed_ns}")
    elif action == "claim-any":
        todo, tmux, base = rest[0], rest[1], rest[2]
        lease = pool.claim(todo_id=todo, tmux=tmux, base_instant=base, child_instant="(none)")
        print(f"claimed slot={lease.slot}")
    elif action == "release":
        print(f"freed={pool.release(rest[0], force=('--force' in rest[1:]))}")
    elif action == "cwd-holders":
        print(" ".join(str(pid) for pid in _cwd_holders(rest[0])))
    elif action == "interrupted":
        floor = float(rest[0]) if rest else 0.0
        for slot, why in pool.interrupted_claims(min_age_s=floor):
            print(f"{slot}\t{why}")
    elif action == "free":
        print(" ".join(pool.free_slots()))
    else:
        print(f"poolctl: unknown action {action!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except FleetError as exc:                       # the same mapping `cli.main` applies
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        for label in ("clears_when", "clears_who"):
            value = getattr(exc, label, None)
            if value:
                print(f"  {label}: {value}", file=sys.stderr)
        sys.exit(exc.exit_code)
PY

  cat > "$EV/py/wscheck.py" <<'PY'
"""§C9 / §C11 / §C12 / §C13 — `fleet.workspace` against real directories and a real git.

None of these three concerns has a verb. `isolate_build_cache`'s only caller is inside `_do_dispatch`,
past the point a `dt-` session is started, and `base_check` and `golden()` have no caller at all outside
`set-golden`'s own re-read. So they are called directly, with `workspace.default_git()` — the module's
real subprocess runner — and every observation printed comes from the product, not from this file.

Each subcommand prints its raw observations and then exactly one `VERDICT:` line, and exits 0/1. The
observations are the evidence; the verdict is the assertion. A summary line never contains an absolute
path, because it is quoted into a results-file note and `bin/lint-evidence-paths.sh` rejects those.
"""
import sys
from pathlib import Path

from fleet.errors import BadInput
from fleet.workspace import GOLDEN_FILE, REPO_LOCAL, Workspace, default_git

OUT = []


def obs(text):
    OUT.append(str(text))
    print(text)


def check(ok, label):
    obs(f"{'ok  ' if ok else 'BAD '} {label}")
    return bool(ok)


def c9(home, dummy):
    """`golden` unset ⇒ BadInput(2) naming a verb that EXISTS, with both controls."""
    from fleet import cli

    home, dummy = Path(home), Path(dummy)
    good = True
    workspace = Workspace(home)
    obs(f"golden file: {home / GOLDEN_FILE} exists={(home / GOLDEN_FILE).exists()}")
    try:
        value = workspace.golden()
        good = check(False, f"golden() returned {value} with nothing declared")
        message, code = "", None
    except BadInput as exc:
        message, code = str(exc), exc.exit_code
        obs(f"--- unset golden raised {type(exc).__name__} exit_code={code} ---")
        obs(message)
    good &= check(code == 2, f"the unset golden's exit code is 2 (got {code})")
    good &= check("no golden workspace is declared" in message, "the message says the golden is unset")
    good &= check("fleet set-golden --path" in message, "the message NAMES THE FIX as a command")
    good &= check("set-golden" in cli.VERBS, "the verb the message prescribes is a declared verb (FI-19a)")
    good &= check(str(home / GOLDEN_FILE) in message, "the message names the file it looked in")
    good &= check("fleet golden" not in message, "the message does not prescribe the verb that never existed")

    # POSITIVE CONTROL. Without it, "raises BadInput" would also pass for a golden() that always raises.
    workspace.set_golden(dummy)
    fresh = Workspace(home).golden()                # a FRESH consumer, not the writer's return value
    good &= check(fresh == dummy, f"after set_golden a fresh consumer reads it back (got {fresh.name})")

    # And the value, not the file's existence, is what governs.
    (home / GOLDEN_FILE).write_text("\n")
    try:
        Workspace(home).golden()
        good &= check(False, "an EMPTY golden file was accepted as a declaration")
    except BadInput as exc:
        good &= check(exc.exit_code == 2, "an empty golden file is exit 2, not a silent empty path")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} unset golden is BadInput/2 naming `fleet set-golden "
          f"--path`; a set golden reads back; an empty file is still unset")
    return 0 if good else 1


def c11(slot):
    """The config must name the POPULATED `.m2-old`, not the empty `.m2` that sorts first."""
    slot = Path(slot)
    workspace = Workspace(slot.parent)
    populated, empty = slot / ".m2-old", slot / ".m2"
    obs(f"before: .m2 exists={empty.is_dir()} jars={len(list(empty.rglob('*.jar')))} · "
        f".m2-old exists={populated.is_dir()} jars={len(list(populated.rglob('*.jar')))}")
    good = check(empty.is_dir() and not list(empty.rglob("*.jar")),
                 "the DECOY empty .m2 exists and sorts first, so `.m2*` alone cannot pick the right one")
    good &= check(populated.is_dir() and list(populated.rglob("*.jar")),
                  "the .m2-old the product must choose is populated")

    written = workspace.isolate_build_cache(slot)
    obs(f"isolate_build_cache wrote {len(written)} config(s): "
        f"{', '.join(str(p.relative_to(slot)) for p in written)}")
    want = f"{REPO_LOCAL}{populated}"
    good &= check(len(written) == 2, f"one .mvn/maven.config per pom at depth<=2 (got {len(written)})")
    for config in written:
        text = config.read_text()
        obs(f"--- {config.relative_to(slot)} ---\n{text.rstrip()}")
        good &= check(text.strip() == want,
                      f"{config.relative_to(slot)} names the populated cache and nothing else")
        good &= check(f"{REPO_LOCAL}{empty}\n" not in text,
                      f"{config.relative_to(slot)} does NOT name the empty .m2")
    good &= check(populated.is_dir(), "the target the config names EXISTS (OI-6: a cold cache is a failure)")
    caches = sorted(d.name for d in slot.glob(".m2*") if d.is_dir())
    good &= check(caches == [".m2", ".m2-old"], f"no third cache directory was invented (found {caches})")

    again = workspace.isolate_build_cache(slot)     # idempotent: never a stacked second line
    good &= check(again == [], f"a second call writes nothing (got {len(again)})")
    for config in written:
        good &= check(config.read_text().count(REPO_LOCAL) == 1,
                      f"{config.relative_to(slot)} still holds exactly one repo.local line")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} both maven.config files name the POPULATED .m2-old "
          f"(which exists) and not the empty .m2 that sorts first; re-running stacks nothing")
    return 0 if good else 1


def _report(checks):
    for item in checks:
        obs(f"  {item.repo:<8} expected={item.expected[:12]} actual="
            f"{(item.actual or '(none)')[:12]} -> {item.verdict}")


def c12(slot, at_base, ahead, absent):
    """Four repos, four positions, in ONE call — so a check that answers the same for everything fails."""
    slot = Path(slot)
    workspace = Workspace(slot.parent, git=default_git())
    expected = {"atbase": at_base, "desc": at_base, "present": ahead, "absent": absent}
    checks = workspace.base_check(slot, expected)
    _report(checks)
    by = {item.repo: item for item in checks}
    want_position = {"atbase": "at-base", "desc": "descendant", "present": "present", "absent": "absent"}
    want_verdict = {"atbase": "ok", "desc": "ok", "present": "advisory", "absent": "failed"}
    good = check(len(checks) == 4, f"four repos examined (got {len(checks)})")
    for repo in sorted(want_position):
        item = by.get(repo)
        if item is None:
            good = check(False, f"{repo} is missing from the report")
            continue
        good &= check(item.verdict == want_position[repo],
                      f"{repo}: position {item.verdict} == {want_position[repo]}")
        got = workspace.verdict([item])
        good &= check(got == want_verdict[repo], f"{repo}: verdict {got} == {want_verdict[repo]}")
    # THE DISCRIMINATING CONTROL. All four inputs are real repos with a readable HEAD, so `absent` here
    # is the object-missing branch and not "there is no git here" — the two share one label.
    good &= check(all(item.actual for item in checks),
                  "every repo has a readable HEAD, so `absent` is a MISSING OBJECT and not a missing repo")
    good &= check(len({item.verdict for item in checks}) == 4,
                  "the four inputs produced FOUR DISTINCT positions, so the check discriminates")
    good &= check(by["atbase"].actual == at_base, "at-base repo's HEAD really is the expected sha")
    good &= check(by["desc"].actual == ahead, "descendant repo's HEAD really is the 1-ahead sha")
    good &= check(by["present"].actual == at_base and by["present"].expected == ahead,
                  "present repo's HEAD is elsewhere and the expected sha is an object it holds")
    good &= check(workspace.verdict(checks) == "failed", "over all four together the WORST governs")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} at-base/descendant/present/absent -> "
          f"ok/ok/advisory/failed, four distinct positions from one call, every HEAD readable")
    return 0 if good else 1


def c13(slot, alpha_sha, beta_absent_sha, beta_head):
    """`alpha` ok, `beta` absent ⇒ overall failed — with the control that says the verdict can move."""
    slot = Path(slot)
    workspace = Workspace(slot.parent, git=default_git())
    checks = workspace.base_check(slot, {"alpha": alpha_sha, "beta": beta_absent_sha})
    _report(checks)
    by = {item.repo: item for item in checks}
    good = check(by["alpha"].verdict == "at-base", f"alpha is at-base (got {by['alpha'].verdict})")
    good &= check(by["beta"].verdict == "absent", f"beta is absent (got {by['beta'].verdict})")
    good &= check(bool(by["beta"].actual),
                  "beta HAS a readable HEAD, so `absent` means the expected object is missing from it")
    good &= check(workspace.verdict([by["alpha"]]) == "ok", "alpha ALONE is ok")
    good &= check(workspace.verdict([by["beta"]]) == "failed", "beta ALONE is failed")
    good &= check(workspace.verdict(checks) == "failed", "together the overall verdict is failed")
    # THE DISCRIMINATING CONTROL (OBS-49's inverse): a verdict that answered `failed` for every
    # multi-repo input would satisfy the assertion above. So the same two repos, both at base.
    both_ok = workspace.base_check(slot, {"alpha": alpha_sha, "beta": beta_head})
    _report(both_ok)
    good &= check(workspace.verdict(both_ok) == "ok",
                  "the SAME two repos with both expectations met are `ok`, so `failed` is not a constant")
    print(f"VERDICT: {'PASS' if good else 'FAIL'} alpha ok + beta absent -> failed (worst governs); "
          f"the same pair with both bases met -> ok, so the aggregate is not constant")
    return 0 if good else 1


if __name__ == "__main__":
    WHICH = {"c9": c9, "c11": c11, "c12": c12, "c13": c13}
    sys.exit(WHICH[sys.argv[1]](*sys.argv[2:]))
PY
}

# ===================================================================================================
# §C1 — enroll two fresh slots; `leases` lists both FREE.
#
# Written knowing `leases` has THREE states (`SI-7`): `free` is now a label a slot earns rather than the
# default for "no lease body", so asserting `free` twice would pass for a pool that cannot tell `free`
# from `interrupted`. The control is a third slot holding an interrupted claim in the SAME view.
# ===================================================================================================

c1_two_fresh_slots_are_free() {
  c_home c1 0
  local log="$CD/leases.txt" rows free
  mkdir -p "$C_SLOTS/s1" "$C_SLOTS/s2" "$C_SLOTS/s3"
  fleet enroll --slot "$C_SLOTS/s1" --porcelain >> "$CD/enroll.out" 2>&1
  fleet enroll --slot "$C_SLOTS/s2" --porcelain >> "$CD/enroll.out" 2>&1
  fleet leases --porcelain > "$log" 2>&1
  rows="$(grep -c . "$log")"
  free="$(awk -F'\t' '$2=="free"{print $1}' "$log" | tr '\n' ' ' | sed 's/ $//')"
  {
    printf -- '--- fleet leases --porcelain, two fresh slots ---\n'; cat "$log"
  } > "$CD/C1.txt"
  if [ "$rows" != 2 ] || [ "$free" != "s1 s2" ]; then
    c_fail C1 "$CD/C1.txt" "want 2 rows both free, got $rows row(s), free='$free'"
    return
  fi
  #: THE CONTROL. s3 gets a claim directory with no lease body — the `SI-7` state — and must read
  #: `interrupted`, not `free`. Without this, "both FREE" is satisfied by a view that calls every
  #: bodiless slot free, which is exactly the reporting half of the defect that lost a workspace.
  fleet enroll --slot "$C_SLOTS/s3" --porcelain >> "$CD/enroll.out" 2>&1
  mkdir -p "$FLEET_HOME/pool/leases/s3"
  fleet leases --porcelain > "$CD/leases-with-interrupted.txt" 2>&1
  fleet leases > "$CD/leases-human.txt" 2>&1
  local s3 still
  s3="$(awk -F'\t' '$1=="s3"{print $2}' "$CD/leases-with-interrupted.txt")"
  still="$(awk -F'\t' '$2=="free"{print $1}' "$CD/leases-with-interrupted.txt" | tr '\n' ' ' | sed 's/ $//')"
  {
    printf -- '\n--- CONTROL: s3 enrolled, claim dir created with no lease body ---\n'
    cat "$CD/leases-with-interrupted.txt"
    printf -- '\n--- human form (banner) ---\n'; cat "$CD/leases-human.txt"
  } >> "$CD/C1.txt"
  rmdir "$FLEET_HOME/pool/leases/s3"
  if [ "$s3" = "interrupted" ] && [ "$still" = "s1 s2" ]; then
    c_pass C1 "$CD/C1.txt" \
           "two freshly enrolled slots read exactly 'free' (s1 s2), 2 rows; CONTROL: a third slot holding a bodiless claim reads 'interrupted' in the same view, so 'free' is earned and not the default for 'no lease body' (SI-7)"
  else
    c_fail C1 "$CD/C1.txt" \
           "the interrupted-claim control failed: s3='$s3' (want interrupted), free='$still' (want 's1 s2')"
  fi
}

# ===================================================================================================
# §C2 — enroll a missing path ⇒ exit 2, and the pool is untouched.
# ===================================================================================================

c2_enroll_a_missing_path() {
  c_home c2 1
  local missing="$C_SLOTS/no-such-workspace" before after rc out
  before="$(it_manifest "$FLEET_HOME" "$C_SLOTS")"
  out="$(fleet enroll --slot "$missing" 2>&1)"; rc=$?
  after="$(it_manifest "$FLEET_HOME" "$C_SLOTS")"
  printf '%s\n' "$out" > "$CD/C2.txt"
  local named=no zero=no
  printf '%s' "$out" | grep -qF "$missing" && printf '%s' "$out" \
    | grep -qF "Enrolment never creates the workspace" && named=yes
  [ "$before" = "$after" ] && zero=yes
  if [ "$rc" = 2 ] && [ "$named" = yes ] && [ "$zero" = yes ]; then
    c_pass C2 "$CD/C2.txt" \
           "enroll of a path that is not a directory: exit 2, the message names the path and says enrolment never creates the workspace, and the store+slots manifest (content+mtime) is unchanged"
  else
    c_fail C2 "$CD/C2.txt" "rc=$rc (want 2), message-names-path=$named, zero-delta=$zero"
  fi
}

# ===================================================================================================
# §C3 — claim, then claim the same NAMED slot ⇒ exit 3.
#
# Two slots are enrolled and only one is claimed, so the `pool-capacity` guard PASSES (it sees s2 free)
# and the exit 3 can only come from `pool.claim`'s named-slot collision. That separation is the point:
# with both slots leased, the same exit 3 arrives from the guard and the named-slot lock is never
# exercised — one non-zero class standing in for two mechanisms is `OI-3`.
# ===================================================================================================

c3_named_slot_collision() {
  c_home c3 2
  local rc out
  c_pool claim s1 c3-first itfleet-C-c3-dead "$OURS" > "$CD/claim.out" 2>&1 || {
    c_fail C3 "$CD/claim.out" "the first claim failed; nothing to collide with"; return; }
  out="$(fleet dispatch --profile "$P_WORKER" --title "c3 collide" --base "$OURS" --cap 10 --slot s1 2>&1)"
  rc=$?
  { cat "$CD/claim.out"; printf -- '\n--- fleet dispatch --slot s1 (already leased) ---\nrc=%s\n%s\n' "$rc" "$out"; } \
    > "$CD/C3.txt"
  local names=no guard=no sessions instants
  printf '%s' "$out" | grep -qF "slot 's1' is already leased by todo 'c3-first'" && names=yes
  #: The exit 3 must NOT be the capacity guard's. If it were, this case would pass with the named-slot
  #: lock untested — so the guard's own sentence is asserted ABSENT.
  printf '%s' "$out" | grep -qF "every enrolled slot is leased" || guard=yes
  sessions="$(it_tmux ls -F '#{session_name}' 2>/dev/null | grep -c . )"
  instants="$(find "$FLEET_INSTANTS" -mindepth 1 -maxdepth 1 | grep -c . )"
  if [ "$rc" = 3 ] && [ "$names" = yes ] && [ "$guard" = yes ] \
     && [ "$sessions" = 0 ] && [ "$instants" = 0 ]; then
    c_pass C3 "$CD/C3.txt" \
           "second claim on the same named slot: exit 3 from pool.claim naming the holding todo (s2 was free, so the capacity guard passed and cannot be the source); no tmux session and no instant folder were created"
  else
    c_fail C3 "$CD/C3.txt" \
           "rc=$rc (want 3), names-holder=$names, not-the-capacity-guard=$guard, sessions=$sessions (want 0), instants=$instants (want 0)"
  fi
}

# ===================================================================================================
# §C4 — claim with no slot when the pool is full ⇒ exit 3, at BOTH levels, plus `SI-7`'s wrinkle.
# ===================================================================================================

c4_no_slot_when_full() {
  c_home c4 2
  local rc out prc pout
  c_pool claim s1 c4-a itfleet-C-c4-dead-a "$OURS" > "$CD/claim.out" 2>&1
  c_pool claim s2 c4-b itfleet-C-c4-dead-b "$OURS" >> "$CD/claim.out" 2>&1
  out="$(fleet dispatch --profile "$P_WORKER" --title "c4 full" --base "$OURS" --cap 10 2>&1)"; rc=$?
  #: The pool's OWN answer as well as the gate's. The `pool-capacity` guard fires first from the CLI, so
  #: a CLI-only assertion never reaches `pool.claim`'s exhaustion branch — and that branch is the one
  #: `SI-7` changed.
  pout="$(c_pool claim-any c4-c itfleet-C-c4-dead-c "$OURS" 2>&1)"; prc=$?
  { printf -- '--- fleet dispatch, pool full ---\nrc=%s\n%s\n' "$rc" "$out"
    printf -- '\n--- pool.claim() with no slot named, pool full ---\nrc=%s\n%s\n' "$prc" "$pout"; } > "$CD/C4.txt"
  local gate=no poolsays=no interrupted=no irc
  printf '%s' "$out" | grep -qF "every enrolled slot is leased (s1, s2)" && gate=yes
  printf '%s' "$pout" | grep -qF "Release or reap one, or enroll another workspace" && poolsays=yes
  #: `SI-7`'s wrinkle, because `free_slots()` tests the DIRECTORY: a slot holding a bodiless claim is
  #: NOT free, so it makes the pool full — and the exhaustion message has to say that rather than read
  #: identically to two busy workers.
  c_pool release s1 --force >> "$CD/C4.txt" 2>&1
  mkdir -p "$FLEET_HOME/pool/leases/s1"
  local iout; iout="$(c_pool claim-any c4-d itfleet-C-c4-dead-d "$OURS" 2>&1)"; irc=$?
  printf -- '\n--- pool.claim() with s1 holding an INTERRUPTED claim ---\nrc=%s\n%s\n' "$irc" "$iout" >> "$CD/C4.txt"
  printf '%s' "$iout" | grep -qF "hold an INTERRUPTED claim with no lease body" \
    && printf '%s' "$iout" | grep -qF "a reap clears those and names them" && interrupted=yes
  rmdir "$FLEET_HOME/pool/leases/s1"
  if [ "$rc" = 3 ] && [ "$prc" = 3 ] && [ "$gate" = yes ] && [ "$poolsays" = yes ] \
     && [ "$irc" = 3 ] && [ "$interrupted" = yes ]; then
    c_pass C4 "$CD/C4.txt" \
           "claim with no slot named on a full pool: exit 3 from the CLI (pool-capacity guard, naming both slots) AND exit 3 from pool.claim itself, whose message prescribes release/reap/enroll; with a bodiless claim in the pool the same exhaustion names it INTERRUPTED and prescribes reap (SI-7)"
  else
    c_fail C4 "$CD/C4.txt" \
           "cli rc=$rc / pool rc=$prc / interrupted rc=$irc (want 3,3,3), gate-message=$gate, pool-message=$poolsays, interrupted-named=$interrupted"
  fi
}

# ===================================================================================================
# §C5 — release twice ⇒ idempotent.
#
# `FI-22`: the contract is not "the second call does not throw", it is that the RETURN VALUE says who did
# the freeing. A release that answered True twice would announce one free twice.
# ===================================================================================================

c5_release_twice() {
  c_home c5 1
  local first second rc1 rc2
  c_pool claim s1 c5-a itfleet-C-c5-dead "$OURS" > "$CD/claim.out" 2>&1
  first="$(c_pool release s1 2>&1)"; rc1=$?
  second="$(c_pool release s1 2>&1)"; rc2=$?
  fleet leases --porcelain > "$CD/leases-after.txt" 2>&1
  { printf -- '--- release #1 ---\nrc=%s\n%s\n--- release #2 ---\nrc=%s\n%s\n' \
      "$rc1" "$first" "$rc2" "$second"
    printf -- '\n--- leases after ---\n'; cat "$CD/leases-after.txt"; } > "$CD/C5.txt"
  local state claimdir=absent
  state="$(awk -F'\t' '$1=="s1"{print $2}' "$CD/leases-after.txt")"
  [ -d "$FLEET_HOME/pool/leases/s1" ] && claimdir=present
  if [ "$rc1" = 0 ] && [ "$rc2" = 0 ] && [ "$first" = "freed=True" ] && [ "$second" = "freed=False" ] \
     && [ "$state" = free ] && [ "$claimdir" = absent ]; then
    c_pass C5 "$CD/C5.txt" \
           "release twice: exit 0 both times, freed=True then freed=False — the return value, not the absence of an exception, is what says which call did the freeing (FI-22); the claim directory is gone and leases reads 'free', not 'interrupted'"
  else
    c_fail C5 "$CD/C5.txt" \
           "rc=$rc1/$rc2 (want 0/0), first='$first' (want freed=True), second='$second' (want freed=False), leases='$state', claim-dir=$claimdir"
  fi
}

# ===================================================================================================
# §C6 — a REAL `sleep 300` with its cwd inside the slot.
#
# Three parts, all three required: the refusal NAMES THE REAL PID · killing that pid clears it · --force
# succeeds WHILE THE PROCESS IS STILL ALIVE (asserted alive at the moment of the force, so "force
# worked" cannot be the sleeper having exited on its own).
# ===================================================================================================

c6_sleeper_holds_the_slot() {
  c_home c6 1
  local slot="$C_SLOTS/s1" pid holders rc out good=1 why=""
  c_pool claim s1 c6-a itfleet-C-c6-dead "$OURS" > "$CD/claim.out" 2>&1

  ( cd "$slot" || exit 1; exec sleep 300 ) &
  pid=$!
  c_track_sleep "$pid"
  local tries=0
  while [ "$tries" -lt 40 ]; do
    holders="$(c_pool cwd-holders "$slot" 2>/dev/null)"
    case " $holders " in *" $pid "*) break ;; esac
    tries=$((tries + 1)); sleep 0.1
  done
  printf -- '--- a real sleep 300 with cwd inside the slot ---\npid=%s cwd-holders=%s\n' \
    "$pid" "$holders" > "$CD/C6.txt"
  case " $holders " in
    *" $pid "*) ;;
    *) c_fail C6 "$CD/C6.txt" "the sleeper never appeared as a cwd holder of the slot; nothing to refuse"
       kill -TERM "$pid" 2>/dev/null; return ;;
  esac

  # (a) refused, and the pid is in the sentence.
  out="$(c_pool release s1 2>&1)"; rc=$?
  printf -- '\n--- release (no --force) while it holds the cwd ---\nrc=%s\n%s\n' "$rc" "$out" >> "$CD/C6.txt"
  [ "$rc" = 4 ] || { good=0; why="$why release-rc=$rc(want 4);"; }
  printf '%s' "$out" | grep -qF "is held as cwd by live pid(s) $pid" \
    || { good=0; why="$why the refusal does not name the real pid $pid;"; }
  printf '%s' "$out" | grep -qF "OBS-48" || { good=0; why="$why no OBS-48 citation;"; }
  printf '%s' "$out" | grep -qF "clears_when: pid(s) $pid exit" \
    || { good=0; why="$why the clearing condition does not name the pid;"; }
  [ -f "$FLEET_HOME/pool/leases/s1/lease.json" ] \
    || { good=0; why="$why the refused release removed the lease body anyway;"; }

  # (b) kill exactly that pid, then release succeeds.
  kill -TERM "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  tries=0
  while [ "$tries" -lt 40 ] && kill -0 "$pid" 2>/dev/null; do tries=$((tries + 1)); sleep 0.1; done
  printf -- '\n--- after kill -TERM %s: alive=%s cwd-holders=[%s] ---\n' "$pid" \
    "$(kill -0 "$pid" 2>/dev/null && echo yes || echo no)" "$(c_pool cwd-holders "$slot" 2>/dev/null)" \
    >> "$CD/C6.txt"
  out="$(c_pool release s1 2>&1)"; rc=$?
  printf -- '--- release after the holder is gone ---\nrc=%s\n%s\n' "$rc" "$out" >> "$CD/C6.txt"
  { [ "$rc" = 0 ] && [ "$out" = "freed=True" ]; } \
    || { good=0; why="$why release-after-kill rc=$rc out='$out' (want 0/freed=True);"; }

  # (c) --force while a live holder is STILL THERE.
  c_pool claim s1 c6-b itfleet-C-c6-dead "$OURS" >> "$CD/C6.txt" 2>&1
  ( cd "$slot" || exit 1; exec sleep 300 ) &
  local pid2=$!
  c_track_sleep "$pid2"
  tries=0
  while [ "$tries" -lt 40 ]; do
    holders="$(c_pool cwd-holders "$slot" 2>/dev/null)"
    case " $holders " in *" $pid2 "*) break ;; esac
    tries=$((tries + 1)); sleep 0.1
  done
  local alive_at_force=no
  kill -0 "$pid2" 2>/dev/null && alive_at_force=yes
  out="$(c_pool release s1 --force 2>&1)"; rc=$?
  local alive_after=no
  kill -0 "$pid2" 2>/dev/null && alive_after=yes
  printf -- '\n--- release --force with pid %s STILL HOLDING the cwd ---\nholders=%s alive_at_force=%s rc=%s\n%s\nalive_after_force=%s\n' \
    "$pid2" "$holders" "$alive_at_force" "$rc" "$out" "$alive_after" >> "$CD/C6.txt"
  case " $holders " in *" $pid2 "*) ;; *) good=0; why="$why the second sleeper never held the cwd, so --force was not tested against a live holder;" ;; esac
  [ "$alive_at_force" = yes ] || { good=0; why="$why the sleeper was already dead when --force ran;"; }
  { [ "$rc" = 0 ] && [ "$out" = "freed=True" ]; } \
    || { good=0; why="$why force rc=$rc out='$out' (want 0/freed=True);"; }
  #: `pool.release` must not have KILLED anything: no verb in this package ends a process outside the
  #: three lifecycle transactions, and a force that tidied the holder away would pass (c) for the wrong
  #: reason entirely.
  [ "$alive_after" = yes ] || { good=0; why="$why --force ended the holding process; release must never kill;"; }

  kill -TERM "$pid2" 2>/dev/null; wait "$pid2" 2>/dev/null
  local leaked=no
  kill -0 "$pid" 2>/dev/null && leaked=yes
  kill -0 "$pid2" 2>/dev/null && leaked=yes
  printf -- '\n--- both sleepers gone: leaked=%s ---\n' "$leaked" >> "$CD/C6.txt"
  [ "$leaked" = no ] || { good=0; why="$why a tracked sleep outlived the case;"; }

  if [ "$good" = 1 ]; then
    c_pass C6 "$CD/C6.txt" \
           "a real sleep 300 with cwd inside the slot: release refused with exit 4 naming that exact pid in both the sentence and the clearing condition, and the lease body survived; killing exactly that pid made release return freed=True; a second live sleeper was force-released with exit 0 while asserted still alive, and was still alive afterwards (release kills nothing). Both pids reaped by this case."
  else
    c_fail C6 "$CD/C6.txt" "$why"
  fi
}

# ===================================================================================================
# §C7 — two leases, one tmux ALIVE and one DEAD ⇒ reap frees exactly the dead one.
#
# The warned-about vacuity is that a reap freeing everything also frees the dead one. Three controls:
# the live lease must SURVIVE; nothing may hold either slot as a cwd (so tmux liveness is provably the
# only discriminator in play); and after the live session is killed a SECOND reap must free that slot
# too — which is what proves the survival was caused by the liveness rather than by anything structural.
# ===================================================================================================

c7_reap_frees_exactly_the_dead_one() {
  c_home c7 2
  local alive="$TMUX_PREFIX-c7-alive" dead="$TMUX_PREFIX-c7-dead" good=1 why=""
  #: cwd is $CD, NOT a slot: if the pane sat in s1, the cwd-holder half of staleness would keep s1 too
  #: and the case would pass without tmux liveness ever mattering.
  it_tmux new-session -d -s "$alive" -c "$CD" "sleep 100000" 2>>"$CD/tmux.err" \
    || { c_fail C7 "$CD/tmux.err" "could not start the live pane on the private tmux server"; return; }
  c_pool claim s1 c7-alive "$alive" "$OURS" > "$CD/claim.out" 2>&1
  c_pool claim s2 c7-dead "$dead" "$OURS" >> "$CD/claim.out" 2>&1

  local h1 h2
  h1="$(c_pool cwd-holders "$C_SLOTS/s1" 2>/dev/null)"
  h2="$(c_pool cwd-holders "$C_SLOTS/s2" 2>/dev/null)"
  { printf -- '--- private tmux server ---\n'; it_tmux ls 2>&1
    printf -- '\n--- cwd holders: s1=[%s] s2=[%s] (both MUST be empty, so tmux liveness is the only discriminator) ---\n' "$h1" "$h2"
    printf -- '\n--- leases before reap ---\n'; fleet leases --porcelain 2>&1; } > "$CD/C7.txt"
  [ -z "$h1" ] && [ -z "$h2" ] || { good=0; why="$why a process holds a slot as cwd (s1=[$h1] s2=[$h2]), so staleness was not decided by tmux liveness alone;"; }

  local out rc
  out="$(fleet reap --porcelain --base "$OURS" 2>&1)"; rc=$?
  printf -- '\n--- fleet reap --base <ours> ---\nrc=%s\n%s\n' "$rc" "$out" >> "$CD/C7.txt"
  fleet leases --porcelain > "$CD/leases-after.txt" 2>&1
  { printf -- '\n--- leases after reap ---\n'; cat "$CD/leases-after.txt"; } >> "$CD/C7.txt"

  local reaped n_reaped n_reclaimed n_unfreed n_refused s1state s2state
  reaped="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reaped"{print $2}' | tr '\n' ' ' | sed 's/ $//')"
  n_reaped="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reaped"' | grep -c . )"
  n_reclaimed="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reap-reclaimed"' | grep -c . )"
  n_unfreed="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reap-unfreed"' | grep -c . )"
  n_refused="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reap-refused"' | grep -c . )"
  s1state="$(awk -F'\t' '$1=="s1"{print $2}' "$CD/leases-after.txt")"
  s2state="$(awk -F'\t' '$1=="s2"{print $2}' "$CD/leases-after.txt")"
  [ "$rc" = 0 ] || { good=0; why="$why reap rc=$rc (want 0);"; }
  [ "$reaped" = s2 ] && [ "$n_reaped" = 1 ] || { good=0; why="$why reaped='$reaped' in $n_reaped row(s), want exactly s2;"; }
  [ "$n_reclaimed" = 0 ] && [ "$n_unfreed" = 0 ] && [ "$n_refused" = 0 ] \
    || { good=0; why="$why unexpected rows: reclaimed=$n_reclaimed unfreed=$n_unfreed refused=$n_refused;"; }
  [ "$s1state" = held ] || { good=0; why="$why the LIVE lease did not survive: s1='$s1state';"; }
  #: `free`, not `interrupted`: a release that removed the body but left the lock directory would look
  #: like a successful reap in the report and like a lost slot in the view.
  [ "$s2state" = free ] || { good=0; why="$why s2='$s2state' after being freed (want free, not interrupted);"; }
  printf '%s\n' "$out" | grep -qF "1 freed by this call, 0 interrupted claim(s) reclaimed" \
    || { good=0; why="$why the population row does not say 1 freed / 0 reclaimed;"; }

  #: THE CAUSAL CONTROL. Kill the live pane and reap again: s1 must now free. If it did not, s1's
  #: survival above was not caused by its session being alive and the case proved nothing.
  it_tmux kill-session -t "=$alive" 2>/dev/null
  local out2 rc2
  out2="$(fleet reap --porcelain --base "$OURS" 2>&1)"; rc2=$?
  fleet leases --porcelain > "$CD/leases-after2.txt" 2>&1
  { printf -- '\n--- CONTROL: the live pane killed, reap again ---\nrc=%s\n%s\n' "$rc2" "$out2"
    printf -- '\n--- leases after the second reap ---\n'; cat "$CD/leases-after2.txt"; } >> "$CD/C7.txt"
  local reaped2 s1after
  reaped2="$(printf '%s\n' "$out2" | awk -F'\t' '$1=="reaped"{print $2}' | tr '\n' ' ' | sed 's/ $//')"
  s1after="$(awk -F'\t' '$1=="s1"{print $2}' "$CD/leases-after2.txt")"
  { [ "$reaped2" = s1 ] && [ "$s1after" = free ]; } \
    || { good=0; why="$why control failed: after killing the pane the second reap freed '$reaped2' and s1='$s1after' — so s1's earlier survival was not caused by its session being alive;"; }

  if [ "$good" = 1 ]; then
    c_pass C7 "$CD/C7.txt" \
           "two leases on one pool, one tmux session really running on the private server and one name that never existed: reap freed exactly the dead slot (1 reaped row, 0 reclaimed/unfreed/refused) and left the live one held. Controls: neither slot had a cwd holder, so tmux liveness was the only discriminator; the freed slot reads 'free' not 'interrupted'; and after killing the live pane a second reap freed that slot too, so the survival was caused by the liveness."
  else
    c_fail C7 "$CD/C7.txt" "$why"
  fi
}

# ===================================================================================================
# §C8 — a lease tagged with a FOREIGN base ⇒ reap frees nothing of it and NAMES the owning base;
#       `--all` frees it.
#
# The control against a blanket refusal: a lease of OUR OWN sits in the same pool and the same reap, and
# must be freed while the foreign one is refused. "Frees nothing" is therefore scoped to the foreign
# lease and is not the same statement as "this reap did nothing".
# ===================================================================================================

c8_foreign_lease_is_named_not_freed() {
  c_home c8 2
  local good=1 why="" out rc
  c_pool claim s1 c8-ours itfleet-C-c8-dead-a "$OURS" > "$CD/claim.out" 2>&1
  c_pool claim s2 c8-theirs itfleet-C-c8-dead-b "$FOREIGN" >> "$CD/claim.out" 2>&1
  { printf -- '--- leases before ---\n'; fleet leases --porcelain 2>&1; } > "$CD/C8.txt"

  out="$(fleet reap --porcelain --base "$OURS" 2>&1)"; rc=$?
  fleet leases --porcelain > "$CD/leases-after.txt" 2>&1
  { printf -- '\n--- fleet reap --base <ours>, with a foreign lease present ---\nrc=%s\n%s\n' "$rc" "$out"
    printf -- '\n--- leases after ---\n'; cat "$CD/leases-after.txt"; } >> "$CD/C8.txt"
  local reaped refused s2state
  reaped="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reaped"{print $2}' | tr '\n' ' ' | sed 's/ $//')"
  refused="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reap-refused"' | grep -c . )"
  s2state="$(awk -F'\t' '$1=="s2"{print $2}' "$CD/leases-after.txt")"
  [ "$rc" = 4 ] || { good=0; why="$why reap rc=$rc (want 4, refused);"; }
  [ "$refused" = 1 ] || { good=0; why="$why $refused reap-refused row(s), want 1;"; }
  printf '%s\n' "$out" | grep -qF "$FOREIGN" || { good=0; why="$why the refusal does not NAME the owning base;"; }
  printf '%s\n' "$out" | grep -qF "Not yours to clear" || { good=0; why="$why the refusal does not say 'not yours to clear';"; }
  printf '%s\n' "$out" | grep -qF 'Override: `fleet reap --all`' || { good=0; why="$why the refusal does not quote the exact override token;"; }
  printf '%s\n' "$out" | grep -qF "1 left to their owners" || { good=0; why="$why the population row does not count the skipped lease;"; }
  [ "$s2state" = held ] || { good=0; why="$why the foreign lease was freed anyway: s2='$s2state';"; }
  #: THE CONTROL. Our own stale lease in the same call must be freed, or "frees nothing" is just "this
  #: reap is broken" and the ownership scope is untested.
  [ "$reaped" = s1 ] || { good=0; why="$why our own stale lease was not freed by the same call (reaped='$reaped'), so the refusal is not provably ownership-scoped;"; }

  out="$(fleet reap --porcelain --all 2>&1)"; rc=$?
  fleet leases --porcelain > "$CD/leases-after-all.txt" 2>&1
  { printf -- '\n--- fleet reap --all ---\nrc=%s\n%s\n' "$rc" "$out"
    printf -- '\n--- leases after --all ---\n'; cat "$CD/leases-after-all.txt"; } >> "$CD/C8.txt"
  local reaped_all s2final
  reaped_all="$(printf '%s\n' "$out" | awk -F'\t' '$1=="reaped"{print $2}' | tr '\n' ' ' | sed 's/ $//')"
  s2final="$(awk -F'\t' '$1=="s2"{print $2}' "$CD/leases-after-all.txt")"
  [ "$rc" = 0 ] || { good=0; why="$why reap --all rc=$rc (want 0);"; }
  [ "$reaped_all" = s2 ] || { good=0; why="$why reap --all freed '$reaped_all' (want s2);"; }
  [ "$s2final" = free ] || { good=0; why="$why s2='$s2final' after --all (want free);"; }

  if [ "$good" = 1 ]; then
    c_pass C8 "$CD/C8.txt" \
           "a stale lease owned by another base: reap --base <ours> exited 4, named that base, said 'Not yours to clear' and quoted the exact override token, and left the lease held; the SAME call freed our own stale lease in the same pool, so the refusal is provably ownership-scoped rather than a blanket no-op; reap --all then freed the foreign lease and the slot reads free."
  else
    c_fail C8 "$CD/C8.txt" "$why"
  fi
}

# ===================================================================================================
# §C9 — `golden` unset ⇒ exit 2 naming the fix.
#
# `Workspace.golden()` has NO consumer anywhere in the package (see c10), so no verb can be run into
# this state and there is no CLI exit code to read for it. What IS asserted: the raise is `BadInput`,
# whose `exit_code` is the 2 `cli.main` returns for any FleetError; the sentence names `fleet set-golden
# --path`, and that verb is in `VERBS` (`FI-19a`); and a real `python3 -m fleet.cli` subprocess is shown
# returning 2 for the same module's BadInput, so the class-to-code mapping is measured and not assumed.
# ===================================================================================================

c9_unset_golden() {
  c_home c9 0
  local rc out crc cout good=1 why=""
  out="$(c_ws c9 "$FLEET_HOME" "$DUMMY" 2>&1)"; rc=$?
  printf '%s\n' "$out" > "$CD/C9.txt"
  [ "$rc" = 0 ] || { good=0; why="$why $(printf '%s' "$out" | grep '^BAD ' | tr '\n' ' ');"; }
  #: The mapping, measured through a real process: `workspace.set_golden` raises BadInput for a path that
  #: is not a directory and the CLI returns 2 for it. Same class, same module, real subprocess.
  cout="$(fleet set-golden --path "$C_SLOTS/no-such-golden" 2>&1)"; crc=$?
  printf -- '\n--- fleet set-golden --path <missing> (the class-to-code mapping, measured) ---\nrc=%s\n%s\n' \
    "$crc" "$cout" >> "$CD/C9.txt"
  [ "$crc" = 2 ] || { good=0; why="$why a real CLI BadInput from workspace returned $crc, not 2;"; }
  #: And the refusal was a refusal: the golden file wscheck left blank must still be blank. A validator
  #: that rejects at SET time and writes anyway would exit 2 and still have declared the bad path.
  [ -f "$FLEET_HOME/golden" ] || { good=0; why="$why the golden file is missing, so nothing was inspected;"; }
  [ -n "$(tr -d '[:space:]' < "$FLEET_HOME/golden" 2>/dev/null)" ] \
    && { good=0; why="$why the REFUSED set-golden wrote a value into the golden file anyway;"; }
  if [ "$good" = 1 ]; then
    c_pass C9 "$CD/C9.txt" \
           "an undeclared golden raises BadInput whose exit_code is 2, and the sentence names the fix as \`fleet set-golden --path\` — a verb that is really in VERBS (FI-19a) — while naming the file it read; controls: a set golden reads back through a fresh consumer and an empty golden file is still unset. The class-to-code mapping is measured through a real CLI subprocess (exit 2), because NO verb consumes golden() and so the state itself is not reachable from a command line."
  else
    c_fail C9 "$CD/C9.txt" "$why"
  fi
}

# ===================================================================================================
# §C10 — set_golden to the dummy project, then dispatch CLONES it. Unrunnable, for two reasons.
# ===================================================================================================

c10_dispatch_clones_the_golden() {
  c_home c10 1
  local ev="$CD/C10-no-producer.txt"
  { printf -- '--- §C10 asserts a clone. Every mention of "clone" in src/fleet: ---\n'
    grep -rn --include='*.py' 'clone' "$INSTANT/src/fleet" || printf '(none)\n'
    printf -- '\n--- every caller of Workspace.golden() in src/: ---\n'
    grep -rn --include='*.py' '\.golden()' "$INSTANT/src" || printf '(none)\n'
    printf -- '\n--- what _do_dispatch records as the golden: ---\n'
    grep -n 'golden=' "$INSTANT/src/fleet/cli.py" || true
    printf -- '\n--- and what it does to the slot instead of cloning into it: ---\n'
    grep -n 'isolate_build_cache\|sessions.start' "$INSTANT/src/fleet/cli.py" || true
    printf -- '\n--- set-golden itself DOES work (the half of C10 that has a producer): ---\n'
    fleet set-golden --porcelain --path "$DUMMY" 2>&1
    printf -- '\n--- and the declared golden is a real git repo tree: ---\n'
    printf 'golden file: %s\n' "$(cat "$FLEET_HOME/golden" 2>/dev/null)"
    git -C "$DUMMY/alpha" rev-parse HEAD 2>&1
  } > "$ev"
  c_skip C10 "$ev" \
         "UNRUNNABLE, two independent reasons, both evidenced in the attached grep. (1) NO PRODUCER: nothing in src/fleet clones anything — the only occurrences of the word are three doc-comments — and _do_dispatch never calls Workspace.golden(); it records golden=str(lease.path), i.e. the slot itself, and the only thing it does to a slot is isolate_build_cache. Workspace.golden() has no consumer in the package at all, so the declared golden is write-only. A test would have to clone with git itself and then assert git cloned, which is K6's shape exactly. (2) The clone step would sit inside a SUCCEEDING dispatch, and dispatch hardcodes tmux=dt-<name> plus sessions.start, which this section is forbidden to create. Reported as a gap, not failed as a defect: set-golden works and is asserted here, so the missing piece is a consumer."
}

# ===================================================================================================
# §C11 — build-cache isolation names the POPULATED `.m2-old`, not a new empty `.m2`; the target exists.
# ===================================================================================================

c11_build_cache_isolation() {
  c_home c11 0
  local slot="$EV/fixtures/c11/slot" rc out
  case "$slot" in "$EV"/fixtures/*) rm -rf "${slot%/slot}" ;; *) echo "refusing" >&2; return ;; esac
  mkdir -p "$slot/.m2" "$slot/alpha"
  #: The DECOY is the whole point: `_cache_dir` globs `.m2*` and sorts, so an empty `.m2` is examined
  #: FIRST and must be rejected for holding no jar (OI-6). The populated one is called `.m2-old` because
  #: R5I-4's live instance was populated under a non-canonical name.
  cp -a "$DUMMY/alpha/.m2-old" "$slot/.m2-old"
  cp "$DUMMY/alpha/pom.xml" "$slot/pom.xml"
  cp "$DUMMY/alpha/pom.xml" "$slot/alpha/pom.xml"
  out="$(c_ws c11 "$slot" 2>&1)"; rc=$?
  printf '%s\n' "$out" > "$CD/C11.txt"
  if [ "$rc" = 0 ]; then
    c_pass C11 "$CD/C11.txt" \
           "$(printf '%s' "$out" | sed -n 's/^VERDICT: PASS //p'). A decoy EMPTY .m2 sits beside a populated .m2-old and sorts first, so a check that merely found a .m2* would have named the cold one."
  else
    c_fail C11 "$CD/C11.txt" "$(printf '%s' "$out" | grep '^BAD ' | tr '\n' ' ')"
  fi
}

# ===================================================================================================
# §C12 — base-check on real repos: at-base · descendant · present · absent ⇒ ok / ok / advisory / failed.
# ===================================================================================================

c12_base_check_four_positions() {
  c_home c12 0
  local slot="$EV/fixtures/c12/slot" rc out
  case "$slot" in "$EV"/fixtures/*) rm -rf "${slot%/slot}" ;; *) echo "refusing" >&2; return ;; esac
  mkdir -p "$slot"
  #: Four REAL clones of the dummy repo, one per position. `-b feature` rather than a checkout, so this
  #: runner never runs `git checkout` anywhere. A plain clone brings the feature branch's objects too,
  #: which is what makes `present` reachable: the expected sha is an object the repo HOLDS while HEAD is
  #: elsewhere and it is not an ancestor.
  git clone -q "$DUMMY/alpha" "$slot/atbase" 2>>"$CD/clone.err"
  git clone -q -b feature "$DUMMY/alpha" "$slot/desc" 2>>"$CD/clone.err"
  git clone -q "$DUMMY/alpha" "$slot/present" 2>>"$CD/clone.err"
  git clone -q "$DUMMY/alpha" "$slot/absent" 2>>"$CD/clone.err"
  { printf -- '--- the four fixture repos ---\n'
    for r in atbase desc present absent; do
      printf '%s HEAD=%s\n' "$r" "$(git -C "$slot/$r" rev-parse HEAD 2>&1)"
    done
    printf 'feature object visible in present: %s\n' "$(git -C "$slot/present" cat-file -t "$ALPHA_AHEAD" 2>&1)"
  } > "$CD/C12.txt"
  out="$(c_ws c12 "$slot" "$ALPHA_BASE" "$ALPHA_AHEAD" "$ALPHA_ABSENT" 2>&1)"; rc=$?
  printf '%s\n' "$out" >> "$CD/C12.txt"
  if [ "$rc" = 0 ]; then
    c_pass C12 "$CD/C12.txt" \
           "$(printf '%s' "$out" | sed -n 's/^VERDICT: PASS //p') All four verdicts come from ONE base_check call over four real clones, so a check answering the same for every input cannot pass."
  else
    c_fail C12 "$CD/C12.txt" "$(printf '%s' "$out" | grep '^BAD ' | tr '\n' ' ')"
  fi
}

# ===================================================================================================
# §C13 — multi-repo: `alpha` ok, `beta` absent ⇒ overall `failed` (worst governs).
# ===================================================================================================

c13_worst_governs() {
  c_home c13 0
  local slot="$EV/fixtures/c13/slot" rc out
  case "$slot" in "$EV"/fixtures/*) rm -rf "${slot%/slot}" ;; *) echo "refusing" >&2; return ;; esac
  mkdir -p "$slot"
  git clone -q "$DUMMY/alpha" "$slot/alpha" 2>>"$CD/clone.err"
  git clone -q "$DUMMY/beta" "$slot/beta" 2>>"$CD/clone.err"
  { printf -- '--- fixture: two sibling repos in one slot ---\n'
    printf 'alpha HEAD=%s\nbeta  HEAD=%s\n' \
      "$(git -C "$slot/alpha" rev-parse HEAD 2>&1)" "$(git -C "$slot/beta" rev-parse HEAD 2>&1)"
    #: beta's expected sha is alpha's base: a REAL commit that simply is not an object in beta. Harder
    #: than a zeroed sha and closer to the live failure — a worker pointed at the wrong repo's baseline.
    printf 'alpha-base object in beta: %s\n' "$(git -C "$slot/beta" cat-file -t "$ALPHA_BASE" 2>&1)"
  } > "$CD/C13.txt"
  out="$(c_ws c13 "$slot" "$ALPHA_BASE" "$ALPHA_BASE" "$BETA_HEAD" 2>&1)"; rc=$?
  printf '%s\n' "$out" >> "$CD/C13.txt"
  if [ "$rc" = 0 ]; then
    c_pass C13 "$CD/C13.txt" \
           "$(printf '%s' "$out" | sed -n 's/^VERDICT: PASS //p') beta's expected sha is a real commit that is simply not an object in beta, and beta's own HEAD is readable, so 'absent' is a missing object rather than a missing repo."
  else
    c_fail C13 "$CD/C13.txt" "$(printf '%s' "$out" | grep '^BAD ' | tr '\n' ' ')"
  fi
}

# ===================================================================================================

run_all() {
  c1_two_fresh_slots_are_free
  c2_enroll_a_missing_path
  c3_named_slot_collision
  c4_no_slot_when_full
  c5_release_twice
  c6_sleeper_holds_the_slot
  c7_reap_frees_exactly_the_dead_one
  c8_foreign_lease_is_named_not_freed
  c9_unset_golden
  c10_dispatch_clones_the_golden
  c11_build_cache_isolation
  c12_base_check_four_positions
  c13_worst_governs
}

#: This runner OWNS its rows (`SI-4`): the prior rows for the cases it is about to write are dropped
#: first, so the file is the CURRENT verdict per case rather than an append-only log read backwards.
#: The two extra ISOLATION ids are included because this runner WRITES them — an unowned row is a
#: duplicate on the next run, which is the same "read it backwards" defect one layer down.
C_ARG="${1:-all}"
case "$C_ARG" in
  all)     it_own_cases 'C[0-9]+[a-z]?|ISOLATION-C-(enter|leave)|ISOLATION-C-(live-tmux|claude-count)' ;;
  C[0-9]*) it_own_cases "$C_ARG"'|ISOLATION-C-(enter|leave)|ISOLATION-C-(live-tmux|claude-count)' ;;
  *)       echo "usage: $0 [all|C1..C13]" >&2; exit 2 ;;
esac

c_enter
c_write_helpers
case "$C_ARG" in
  all) run_all ;;
  C1)  c1_two_fresh_slots_are_free ;;
  C2)  c2_enroll_a_missing_path ;;
  C3)  c3_named_slot_collision ;;
  C4)  c4_no_slot_when_full ;;
  C5)  c5_release_twice ;;
  C6)  c6_sleeper_holds_the_slot ;;
  C7)  c7_reap_frees_exactly_the_dead_one ;;
  C8)  c8_foreign_lease_is_named_not_freed ;;
  C9)  c9_unset_golden ;;
  C10) c10_dispatch_clones_the_golden ;;
  C11) c11_build_cache_isolation ;;
  C12) c12_base_check_four_positions ;;
  C13) c13_worst_governs ;;
  *)   echo "usage: $0 [all|C1..C13]" >&2; exit 2 ;;
esac
c_leave

#: P-3. The recording boundary already relativises, and this is the belt-and-braces the other runners
#: end with: `bin/lint-evidence-paths.sh` fails the register on any absolute path in a results file.
sed -i "s|$INSTANT/||g" "$RESULTS"

printf '\n--- %s ---\n' "$(basename "$RESULTS")"
column -t -s "$(printf '\t')" "$RESULTS" 2>/dev/null || cat "$RESULTS"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
