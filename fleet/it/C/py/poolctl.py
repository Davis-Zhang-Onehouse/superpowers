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
