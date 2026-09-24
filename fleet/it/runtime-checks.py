"""Finite public-CLI infrastructure test. The worker is an attributed stand-in, not a model."""
import json
import os
from pathlib import Path
import subprocess
import time

from fleet.store import Store

socket = os.environ.get('FLEET_TMUX_SOCKET', '')
assert socket.startswith('itfleet-'), 'A private socket is mandatory'
home = Path(os.environ['FLEET_HOME'])
instants = Path(os.environ['FLEET_INSTANTS'])
repo = Path(__file__).resolve().parents[2]
steps = []


def fleet(*args, codes=(0,)):
    done = subprocess.run([os.environ['IT_FLEET'], *args, '--porcelain'],   # the harness wrapper, never the launcher (B18)
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    steps.append(dict(args=args, code=done.returncode, out=done.stdout, err=done.stderr))
    print(json.dumps(steps[-1]), flush=True)
    assert done.returncode in codes, steps[-1]
    return done.stdout


# This section can be rerun after a failure, but never discards unfinished state.
assert not Store(home).all(), 'Use a fresh RT test store; previous records need inspection'
slot = home.parent / 'slots/runtime-slot'
slot.mkdir(parents=True, exist_ok=True)
fleet('enroll', '--slot', str(slot))
profile = repo / 'fleet/tests/fixtures/profiles/workerCompliant'
for runtime in ('claude', 'codex'):
    fleet('runtime', '--set', runtime)
    fleet('dispatch', '--profile', str(profile), '--title', 'runtime ' + runtime, '--cap', '1')
    record = [r for r in Store(home).all() if not r.harvested_at][0]
    assert record.runtime == runtime
    assert record.runtime_executable and record.runtime_config_dir
    result = fleet('seed-check', '--id', record.todo_id)
    assert 'attested' in result.lower(), result
    fleet('runtime', '--set', 'codex' if runtime == 'claude' else 'claude', codes=(4,))
    fleet('dispatch', '--profile', str(profile), '--title', 'over cap ' + runtime, '--cap', '1', codes=(4,))
    if runtime == 'codex':
        fleet('declare', '--instant', record.child_instant, '--phase', 'awaiting-ci', codes=(4,))
    # Public abandonment path is finite and exercises close/lease release. This
    # proves infrastructure, not the model's review/complete/proposal contract.
    fleet('review', '--instant', record.child_instant, '--scope', 'all', '--verdict', 'READY',
          '--finding', 'RT:Minor:applied:.fleet/seed-delivery.json:stand-in received the expected seed:none')
    fleet('abort', '--instant', record.child_instant, '--reason', 'finite IT stand-in finished')
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        done = subprocess.run(['tmux', '-L', socket, 'has-session', '-t', '=' + record.tmux],
                              capture_output=True)
        if done.returncode:
            break
        time.sleep(.05)
    fleet('harvest', '--id', record.todo_id, codes=(0, 1))
    assert Store(home).read(record.todo_id).harvested_at
fleet('runtime', '--set', 'claude')
