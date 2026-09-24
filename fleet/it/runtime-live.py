"""Opt-in native-TUI test: a coordinator and two workers on one private server.

Trust/permission dialogs are handled by the operator in tmux, never auto-accepted.
All command outcomes and terminal frames stay in this attempt's evidence directory.
"""
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

from fleet.runtime import LaunchSettings
from fleet.runtime_launch import prepare
from fleet.store import Store

runtime = sys.argv[1]
assert runtime in ('claude', 'codex')
root = Path(os.environ['RT_ATTEMPT']).resolve()
socket = os.environ['FLEET_TMUX_SOCKET']
assert socket.startswith('itfleet-RTL-')
assert root.is_relative_to(Path(__file__).resolve().parent)
repo = Path(__file__).resolve().parents[2]
config = Path(os.environ['RT_LIVE_CONFIG']).resolve(strict=True)
assert config.is_dir()
if runtime == 'claude':
    (root / '.claude').symlink_to(config, target_is_directory=True)
    owner = root / 'owners.tsv'
    owner.write_text(str(root) + '\truntime-live-test\n')
    os.environ['CLAUDE_OWNERS_MAP'] = str(owner)
else:
    os.environ['CODEX_HOME'] = str(config)
os.environ['PATH'] = str(repo / 'bin') + os.pathsep + os.environ['PATH']
os.environ['FLEET_HOME'] = str(root / 'store')
os.environ['FLEET_INSTANTS'] = str(root / 'instants')
(root / 'instants').mkdir()
evidence = root / 'evidence'
evidence.mkdir()
log = (evidence / 'commands.jsonl').open('w')
store = Store(root / 'store')
limit = float(os.environ.get('RT_LIVE_TIMEOUT', '900'))


def command(args, codes=(0,)):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=45, cwd=root)
    row = dict(argv=args, code=result.returncode, out=result.stdout, err=result.stderr)
    log.write(json.dumps(row) + '\n'); log.flush()
    if result.returncode not in codes:
        panes = subprocess.run(['tmux', '-L', socket, 'list-sessions', '-F', '#{session_name}'], capture_output=True, text=True)
        for name in panes.stdout.splitlines():
            frame = subprocess.run(['tmux', '-L', socket, 'capture-pane', '-e', '-p', '-t', '=' + name + ':'], capture_output=True, text=True)
            (evidence / ('failure-' + name + '.frame')).write_text(frame.stdout)
        raise RuntimeError(f'{args}: exit {result.returncode}: {result.stderr}')
    return result


def fleet(*args, codes=(0,)):
    return command([os.environ['IT_FLEET'], *args, '--porcelain'], codes).stdout   # the harness wrapper (B18)


def tmux(*args, codes=(0,)):
    return command(['tmux', '-L', socket, *args], codes).stdout


def fields(output):
    return dict(line.split('\t', 1) for line in output.splitlines() if '\t' in line)


def capture(name):
    frame = tmux('capture-pane', '-e', '-p', '-t', '=' + name + ':')
    (evidence / (name + '.frame')).write_text(frame)
    return frame


def wait_for(label, predicate):
    deadline = time.monotonic() + limit
    next_notice = 0
    while time.monotonic() < deadline:
        if predicate():
            print('PASS ' + label, flush=True)
            return
        if time.monotonic() >= next_notice:
            print(f'Waiting: {label}. Inspect trust/permission dialogs with tmux -L {socket} attach', flush=True)
            next_notice = time.monotonic() + 30
        time.sleep(2)
    raise TimeoutError(label + '; inspect evidence and retained leases in ' + str(root))


def idle(name):
    return command([os.environ['IT_FLEET'], 'pane-guard', '--pane', name, '--porcelain'],
                   tuple(range(15))).returncode == 0


def workspace_occupied(path):
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid == os.getuid() and (process / 'cwd').resolve(strict=True) == path:
                return True
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return False


def worker_ready(record):
    return (Path(record.child_instant) / 'evidence/ready.txt').exists() and idle(record.tmux)


binary = os.environ.get('FLEET_' + runtime.upper() + '_BIN') or shutil.which(runtime)
if not binary:
    raise RuntimeError('Install the selected native CLI first')
# Versions are metadata, not a substitute for process/seed proof from dispatch.
version = command([binary, '--version']).stdout.strip()
revision = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True, check=True).stdout.strip()
(evidence / 'environment.json').write_text(json.dumps(dict(runtime=runtime, version=version,
    revision=revision, socket=socket, root=str(root)), indent=2) + '\n')
os.environ.pop('FLEET_ROOT', None)
fleet('runtime', '--set', runtime)
coord = Path(fields(fleet('init', '--name', runtime + 'Coord'))['path'])
for number in (1, 2):
    fleet('milestone', '--instant', str(coord), '--id', 'm' + str(number), '--title', 'addition ' + str(number))
    slot = root / ('slot' + str(number)); slot.mkdir()
    (slot / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
    (slot / 'test_calc.py').write_text('import unittest\nfrom calc import add\nclass Addition(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n')
    fleet('enroll', '--slot', str(slot))

# A native coordinator loads the coordinating skill and observes the actual roadmap.
# It waits for the operator's next message; the harness exercises apply below and
# records that boundary rather than pretending the model issued those commands.
coord_seed = coord / '.fleet/seed.txt'
coord_seed.write_text(f'''This is an isolated fleet integration test. You are the coordinator at {coord}.
Load superpowers:coordinating-instants and superpowers:using-fleet. Read the roadmap with fleet roadmap --instant {shlex.quote(str(coord))}.
Do not dispatch or change files yet. Reply exactly COORDINATOR READY, then wait.
''')
coord_name = 'itfleet-' + runtime + '-coordinator'
settings = LaunchSettings(runtime, str(Path(binary).absolute()), str(config))
# Record is only a launch-settings carrier: unmanaged coordinator has no worker lease.
record = SimpleNamespace(todo_id='testCoordinator', tmux=coord_name, root='',
                child_instant=str(coord), runtime=runtime, tmux_socket=socket)
launcher = prepare(settings, record, coord_seed, os.environ)
tmux('new-session', '-d', '-s', coord_name, '-x', '100', '-y', '35', '-c', str(coord),
     'bash ' + shlex.quote(str(launcher)))
wait_for('native coordinator ready', lambda: re.search(r'(?m)^[●•] COORDINATOR READY\s*$', re.sub(r'\x1b\[[0-9;]*m', '', capture(coord_name))) and idle(coord_name))

records = []
for number in (1, 2):
    profile = root / ('profile' + str(number))
    shutil.copytree(repo / 'skills/using-fleet/profiles/worker', profile)
    (profile / 'charter.md').write_text('''# {{TITLE}}
## Scope
Work only in your leased slot and instant. Diagnose the failing addition test and fix it after receiving GO.
## Acceptance
Capture failing output and original source before editing. Run unittest afterward and retain the passing output.
Record a READY review, propose your assigned milestone done with captured evidence, and complete your instant.
Do not dispatch, harvest, push, change accounts, or modify another worker's files.
''')
    with (profile / 'seed.txt').open('a') as handle:
        handle.write('''\nThis is a bounded integration test. First load the named skills, read your brief and charter,
write READY to "$INSTANT/evidence/ready.txt", reply READY, and WAIT for a message saying GO.
Do not fix anything, review, propose, or complete until GO. Your todo ID and milestone are in fleet brief.
After GO, execute your charter independently. Use python3 -m unittest -v for the test.
Do not ask for confirmation, spawn subagents, commit or push. This two-file fixture needs no project design.
''')
    result = fields(fleet('dispatch', '--profile', str(profile), '--title', runtime + 'Worker' + str(number),
                         '--from', str(coord), '--milestone', 'm' + str(number), '--cap', '2'))
    worker = store.read(result['todo_id']); records.append(worker)
    wait_for('worker ' + str(number) + ' ready', lambda: worker_ready(worker))
    fleet('seed-check', '--id', worker.todo_id)

fleet('dispatch', '--profile', str(profile), '--title', 'overCap', '--cap', '2', codes=(4,))
fleet('runtime', '--set', 'codex' if runtime == 'claude' else 'claude', codes=(4,))
for worker in records:
    refusal = fields(fleet('complete', '--instant', worker.child_instant, codes=(2,)))
    assert refusal.get('allowed') == 'false' and refusal.get('gate') == 'review-undecidable'
    refusal = fleet('harvest', '--id', worker.todo_id, codes=(1,))
    assert 'harvest-refused' in refusal and not store.read(worker.todo_id).harvested_at
    message = root / 'message.txt'
    message.write_text('GO. Diagnose the failing addition test.\nSave evidence before fixing it.\nFinish the review, proposal, and completion contract.')
    fleet('send', '--id', worker.todo_id, '--message-file', str(message))

for worker in records:
    key = Path(worker.child_instant).name.split('-')
    final = Path(worker.child_instant).with_name('-'.join([*key[:2], 'complete', *key[3:]]))
    wait_for('worker completed ' + worker.todo_id, lambda: final.is_dir() and idle(worker.tmux))
    capture(worker.tmux)
    fleet('apply', '--instant', str(coord), '--milestone', worker.milestone)
    fleet('close', '--id', worker.todo_id)
    # Exit is asynchronous; observe an absent session before asking for harvest.
    wait_for('worker exited ' + worker.todo_id,
             lambda: command(['tmux', '-L', socket, 'has-session', '-t', '=' + worker.tmux], (0, 1)).returncode == 1)
    wait_for('workspace process exited ' + worker.todo_id,
             lambda: not workspace_occupied(root / worker.slot))
    fleet('harvest', '--id', worker.todo_id, codes=(0, 1))
    assert store.read(worker.todo_id).harvested_at
    fleet('send', '--id', worker.todo_id, '--message-file', str(message), codes=(4,))

fleet('roadmap', '--instant', str(coord))
assert idle(coord_name)
tmux('kill-session', '-t', '=' + coord_name)
wait_for('coordinator exited', lambda: command(['tmux', '-L', socket, 'has-session', '-t', '=' + coord_name], (0, 1)).returncode == 1)
wait_for('coordinator process exited',
         lambda: not workspace_occupied(coord))
# Two directions on the same store; the initial runtime is restored for inspection.
other = 'codex' if runtime == 'claude' else 'claude'
fleet('runtime', '--set', other)
fleet('runtime', '--set', runtime)
print('PASS native coordinator, two workers, proposals, review, close, harvest, switch-back', flush=True)
