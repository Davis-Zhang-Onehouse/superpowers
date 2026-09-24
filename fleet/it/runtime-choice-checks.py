"""RT2 (pt2, D-22/D-33): per-dispatch runtime and model on a box whose saved runtime is claude. Stand-ins only.

The worker is the attributed stand-in (`bin/claude`), which records the argv it was launched with, so each case
asserts the exact launch command rather than the absence of a flag. (a) `--model` reaches the argv; (b) `--runtime
codex` launches the codex executable with codex's own flags and no model flag, the box selection untouched;
(c) no flags = the base's exact argv. Real models, revive and pane classification: `--choice-live`.
"""
import json
import os
from pathlib import Path
import subprocess

from fleet.store import Store

socket = os.environ.get('FLEET_TMUX_SOCKET', '')
assert socket.startswith('itfleet-'), 'A private socket is mandatory'
home = Path(os.environ['FLEET_HOME'])
repo = Path(__file__).resolve().parents[2]
stand_in = str(Path(os.environ['FLEET_CLAUDE_BIN']).absolute())
steps = []


def fleet(*args, codes=(0,)):
    done = subprocess.run([os.environ['IT_FLEET'], *args, '--porcelain'],   # the harness wrapper, never the launcher (B18)
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    steps.append(dict(args=args, code=done.returncode, out=done.stdout, err=done.stderr))
    print(json.dumps(steps[-1]), flush=True)
    assert done.returncode in codes, steps[-1]
    return done.stdout


def fields(output):
    return dict(line.split('\t', 1) for line in output.splitlines() if '\t' in line)


def launched(todo_id):
    record = Store(home).read(todo_id)
    child = Path(record.child_instant)
    argv = json.loads((child / '.fleet/it-stand-in-argv.json').read_text())
    # The launcher passes `"$(cat -- "$seed_file")"`, and command substitution strips trailing newlines.
    seed = (child / '.fleet/seed.txt').read_text().rstrip('\n')
    body = json.loads((home / 'records' / (todo_id + '.json')).read_text())
    return record, argv, seed, body


assert not Store(home).all(), 'Use a fresh RT2 store'
for name in ('slotA', 'slotB', 'slotC'):
    slot = home.parent / 'slots' / name
    slot.mkdir(parents=True, exist_ok=True)
    fleet('enroll', '--slot', str(slot))
profile = repo / 'fleet/tests/fixtures/profiles/workerCompliant'
fleet('runtime', '--set', 'claude')
box_file = home / 'runtime.json'
# `--set claude` on a fresh store is a no-op (claude is the legacy default), so the box's state is presence + bytes.
box = box_file.read_bytes() if box_file.exists() else None
results = {}

# (c) no flags: the base's argv, character for character, and no runtime_model key in the record.
out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'rt2 default', '--cap', '3'))
record, argv, seed, body = launched(out['todo_id'])
assert argv == [stand_in, '--permission-mode', 'auto', '--remote-control', record.tmux, '--', seed], argv
assert record.runtime == 'claude' and 'runtime_model' not in body, body
assert out['model'].startswith('(none'), out
results['c'] = dict(todo=record.todo_id, argv=argv[:-1] + ['<seed>'])

# (a) --model: on the argv, on the record, seed still delivered.
out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'rt2 model', '--cap', '3',
                   '--model', 'claude-fable-5-1'))
record, argv, seed, body = launched(out['todo_id'])
assert argv == [stand_in, '--permission-mode', 'auto', '--model', 'claude-fable-5-1', '--remote-control',
                record.tmux, '--', seed], argv
assert (record.runtime, record.runtime_model) == ('claude', 'claude-fable-5-1'), body
assert 'attested' in fleet('seed-check', '--id', record.todo_id).lower()
results['a'] = dict(todo=record.todo_id, argv=argv[:-1] + ['<seed>'])

# (b) --runtime codex on the claude box: codex executable + flags, no model flag, box file untouched.
out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'rt2 codex', '--cap', '3',
                   '--runtime', 'codex'))
record, argv, seed, body = launched(out['todo_id'])
codex = str(Path(os.environ['FLEET_CODEX_BIN']).absolute())
assert argv[0] == codex and '--add-dir' in argv and argv[-2:] == ['--', seed], argv
assert '-m' not in argv and '--model' not in argv and '--permission-mode' not in argv, argv
assert (record.runtime, record.runtime_model) == ('codex', ''), body
assert out['runtime'].startswith('codex (flag)'), out
assert (box_file.read_bytes() if box_file.exists() else None) == box
assert fields(fleet('runtime'))['runtime'] == 'claude'
assert 'attested' in fleet('seed-check', '--id', record.todo_id).lower()
board = fleet('board')
row = [line.split('\t') for line in board.splitlines() if line.startswith(record.todo_id)]
assert row and row[0][-1] == 'codex', board
results['b'] = dict(todo=record.todo_id, argv=argv[:-1] + ['<seed>'], board_runtime=row[0][-1])

# Tear down through the public path, like RT1.
for todo in [results[k]['todo'] for k in ('a', 'b', 'c')]:
    child = Store(home).read(todo).child_instant
    fleet('abort', '--instant', child, '--reason', 'finite RT2 stand-in finished')
print(json.dumps(dict(RT2=results)), flush=True)
