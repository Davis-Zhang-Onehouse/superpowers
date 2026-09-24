"""OR (v23-k, FB-113): a REAL codex worker on a claude box is observed as codex, by every reader, in every state.

A private store whose box runtime is claude, a private itfleet-OR- tmux server, a private CODEX_HOME (a COPY of the
credential, removed at teardown). One codex worker is dispatched with `--runtime codex` and driven through:

  idle      `pane-guard --id` and `--pane` read 0, and `board` reads RUNNING;
  nested    the worker runs `./bin/claude 40` in the foreground: `bin/claude` is a copy of /bin/sleep, so the process
            is named claude and its binary is named claude — what `pgrep -x claude` and `recognizes_process` accept,
            exactly like the real `claude agents --json` that `fleet peers` and the hermetic suite start under a
            worker. While it lives, every `pane-guard --id` reads 11 and `board` never reads BLOCKED "live runtime
            claude differs from record runtime codex" (the FB-113 flap);
  bgterm    the worker starts `sleep 40` as a background terminal and waits on it: codex 0.156 draws
            `• Waiting for background terminal (… • esc to interrupt) · 1 background terminal running · …` with a
            `└ <command>` row beneath it, and `pane-guard --id` must read 11, never 0 (the FB-113 false-safe);
  idle      back to 0, with the box runtime still claude.

Every frame the verdicts were computed from is kept under evidence/frames/, so a hermetic fixture can be cut from it.
The harness never answers a trust screen (the answer persists into configuration); it answers only codex 0.156.0's
"Update available" modal with "2. Skip", as `runtime-choice-live.py` does.
"""
import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'fleet/src'))
from fleet.runtime import plain  # noqa: E402
from fleet.store import Store  # noqa: E402

root = Path(os.environ['OR_ATTEMPT']).resolve()
socket = os.environ['FLEET_TMUX_SOCKET']
assert socket.startswith('itfleet-OR-'), socket
limit = float(os.environ.get('OR_LIVE_TIMEOUT', '300'))
codex_source = Path(os.environ.get('OR_CODEX_HOME', '/home/ubuntu/davis_root/.codex')).resolve(strict=True)

for key in ('FLEET_HOME', 'FLEET_INSTANTS', 'FLEET_ROOT', 'FLEET_INSTANT', 'FLEET_RELEASES', 'FLEET_BIN', 'INSTANT'):
    os.environ.pop(key, None)
os.environ['FLEET_HOME'] = str(root / 'store')
os.environ['FLEET_INSTANTS'] = str(root / 'instants')
(root / 'instants').mkdir()
evidence = root / 'evidence'
(evidence / 'frames').mkdir(parents=True)
log = (evidence / 'commands.jsonl').open('w')
store = Store(root / 'store')
verdict = {}


def private_codex_home():
    """The same private home `runtime-choice-live.py` builds: the credential (0600, removed at exit), the top-level
    settings, trust for this checkout, and the superpowers skills link a codex dispatch requires (FB-111)."""
    home = root / 'codex-home'
    home.mkdir(mode=0o700)
    shutil.copy2(codex_source / 'auth.json', home / 'auth.json')
    (home / 'auth.json').chmod(0o600)
    atexit.register(lambda: (home / 'auth.json').unlink(missing_ok=True))
    top = []
    for line in (codex_source / 'config.toml').read_text().splitlines():
        if line.lstrip().startswith('['):
            break
        top.append(line)
    git = lambda *a: subprocess.run(['git', '-C', str(root), 'rev-parse', *a], capture_output=True, text=True).stdout.strip()
    common = git('--path-format=absolute', '--git-common-dir')
    trusted = list(dict.fromkeys(p for p in (str(Path(common).parent) if common else '', git('--show-toplevel'),
                                             str(root)) if p))
    (home / 'config.toml').write_text('\n'.join(top).rstrip() + '\n\n' + ''.join(
        f'[projects."{path}"]\ntrust_level = "trusted"\n\n' for path in trusted))
    releases = Path(tempfile.mkdtemp(prefix='or-releases-'))
    atexit.register(shutil.rmtree, releases, True)
    (releases / 'current').symlink_to(repo, target_is_directory=True)
    subprocess.run(['bash', str(repo / 'scripts' / 'fleet-codex-skills.sh'), '--codex-home', str(home),
                    '--releases', str(releases)], check=True, capture_output=True)
    return home


os.environ['CODEX_HOME'] = str(private_codex_home())
(root / 'owners.tsv').write_text(f'{root}\tobserve-runtime-live-test\n')
os.environ['CLAUDE_OWNERS_MAP'] = str(root / 'owners.tsv')


def command(args, codes=(0,)):
    done = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90, cwd=root)
    log.write(json.dumps(dict(at=time.time(), argv=args, code=done.returncode, out=done.stdout, err=done.stderr)) + '\n')
    log.flush()
    if done.returncode not in codes:
        raise RuntimeError(f'{args}: exit {done.returncode}: {done.stderr}{done.stdout}')
    return done


def fleet(*args, codes=(0,)):
    return command([os.environ['IT_FLEET'], *args, '--porcelain'], codes)


def fields(output):
    return dict(line.split('\t', 1) for line in output.splitlines() if '\t' in line)


def tmux(*args, codes=(0,)):
    return command(['tmux', '-L', socket, *args], codes)


def frame(name, tag):
    text = tmux('capture-pane', '-e', '-p', '-t', '=' + name + ':', codes=(0, 1)).stdout
    (evidence / 'frames' / f'{tag}.frame').write_text(text)
    return text


def wait_for(label, predicate, step=2.0):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            print('PASS ' + label, flush=True)
            return value
        time.sleep(step)
    raise TimeoutError(f'{label} (after {limit:.0f}s); evidence in {root}')


def guard(*args):
    return fleet('pane-guard', *args, codes=tuple(range(16))).returncode


def board_row(todo):
    for line in fleet('board').stdout.splitlines():
        if line.startswith(todo + '\t'):
            return line
    return ''


def pane_pid(name):
    return int(tmux('display-message', '-p', '-t', '=' + name + ':', '#{pane_pid}').stdout.strip())


def descendants(pid):
    """Every live pid under `pid`, from /proc/<pid>/task/*/children."""
    out, todo = [], [pid]
    while todo:
        current = todo.pop()
        for task in Path(f'/proc/{current}/task').glob('*'):
            try:
                children = [int(c) for c in (task / 'children').read_text().split()]
            except OSError:
                continue
            out.extend(children)
            todo.extend(children)
    return out


def comm(pid):
    try:
        return Path(f'/proc/{pid}/comm').read_text().strip()
    except OSError:
        return ''


def argv_of(pid):
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]
    except OSError:
        return []


SCREENS = (('update available', '2. skip'),)
TRUST = ('trust this folder', 'do you trust the contents', 'trust the files in this folder')


def answer_screen(name):
    text = plain(frame(name, f'screen-{int(time.time())}')).lower()
    if any(marker in text for marker in TRUST):
        raise RuntimeError(f'{name} shows a folder-trust screen; this harness never answers one')
    wanted = [target for marker, target in SCREENS if marker in text]
    if not wanted:
        return False
    for _ in range(5):
        rows = [row.strip().lower() for row in plain(frame(name, 'screen')).splitlines()]
        chosen = [row for row in rows if row.startswith(('❯', '›', '>'))]
        if chosen and any(target in chosen[-1] for target in wanted):
            tmux('send-keys', '-t', '=' + name + ':', 'Enter')
            time.sleep(2)
            return True
        tmux('send-keys', '-t', '=' + name + ':', 'Down')
        time.sleep(0.5)
    raise RuntimeError(f'could not select {wanted} on {name}')


def settle(record, tag):
    def idle():
        code = guard('--id', record.todo_id)
        if code in (14, 15) and answer_screen(record.tmux):
            return False
        return code == 0
    wait_for(f'{record.todo_id} idle ({tag})', idle, step=3)
    frame(record.tmux, f'{tag}-idle')
    return dict(pane_guard_id=guard('--id', record.todo_id), pane_guard_pane=guard('--pane', record.tmux),
                board=board_row(record.todo_id))


def watch_turn(record, tag, alive, seconds):
    """Sample every ~1s while `alive()` names a live process: the pane-guard code, the board row and the frame."""
    samples, started = [], time.monotonic()
    first = wait_for(f'{tag} process started', alive, step=0.5)
    while time.monotonic() - started < seconds:
        pids = alive()
        if not pids:
            break
        index = len(samples)
        text = frame(record.tmux, f'{tag}-{index:03d}')
        code = guard('--id', record.todo_id)
        row = board_row(record.todo_id)
        still = alive()
        samples.append(dict(i=index, pids=pids, code=code, board=row, alive_after=bool(still),
                            last_rows=[plain(r) for r in text.rstrip('\n').splitlines()[-6:]]))
        time.sleep(1)
    return first, samples


# --- set-up: a claude box, one slot holding a stand-in claude binary ------------------------------------
(evidence / 'environment.json').write_text(json.dumps(dict(
    revision=subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
    codex=command(['codex', '--version']).stdout.strip(), socket=socket, root=str(root)), indent=2) + '\n')
fleet('runtime', '--set', 'claude')
slot = root / 'slotC'
(slot / 'bin').mkdir(parents=True)
shutil.copy2('/bin/sleep', slot / 'bin' / 'claude')          # comm "claude", exe basename "claude"
fleet('enroll', '--slot', str(slot))
profile = root / 'profile'
shutil.copytree(repo / 'fleet/tests/fixtures/profiles/workerCompliant', profile)
(profile / 'seed.txt').write_text(
    'This is an isolated fleet integration test ({{TITLE}}). Do not run any tool, command or skill and do not read '
    'any file. Reply with exactly the one word READY, then stop and wait for the next message.\n')

out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'or codex', '--slot', 'slotC', '--cap', '1',
                   '--runtime', 'codex').stdout)
record = store.read(out['todo_id'])
assert record.runtime == 'codex', record
verdict['record'] = dict(todo=record.todo_id, tmux=record.tmux, runtime=record.runtime)
verdict['idle_1'] = settle(record, 'idle1')
root_pid = pane_pid(record.tmux)

# --- nested: a process named claude runs under the codex worker, mid-turn ------------------------------------
nested_msg = root / 'nested.txt'
nested_msg.write_text('Run exactly this shell command from your working directory, in the foreground, and wait for it '
                      'to finish: ./bin/claude 40   When it has finished, reply with exactly the one word DONE.')
fleet('send', '--id', record.todo_id, '--message-file', str(nested_msg))
nested = lambda: [p for p in descendants(root_pid) if comm(p) == 'claude' and argv_of(p)[-1:] == ['40']]
first, samples = watch_turn(record, 'nested', nested, 60)
verdict['nested'] = dict(first_pids=first, samples=samples)
verdict['idle_2'] = settle(record, 'idle2')

# --- bgterm: a background terminal the worker waits on ------------------------------------------------------
bg_msg = root / 'bgterm.txt'
bg_msg.write_text('Start the shell command `sleep 41` so that it keeps running as a background terminal (start it with '
                  'a short yield, do not wait for it in the same call), then keep polling that background terminal '
                  'until the command has exited. Then reply with exactly the one word DONE2.')
fleet('send', '--id', record.todo_id, '--message-file', str(bg_msg))
bg = lambda: [p for p in descendants(root_pid) if comm(p) == 'sleep' and argv_of(p)[-1:] == ['41']]
first, samples = watch_turn(record, 'bgterm', bg, 70)
verdict['bgterm'] = dict(first_pids=first, samples=samples)
verdict['idle_3'] = settle(record, 'idle3')
verdict['box_runtime'] = fields(fleet('runtime').stdout).get('runtime')

tmux('kill-session', '-t', '=' + record.tmux)
fleet('abort', '--instant', store.read(record.todo_id).child_instant, '--reason', 'OR finished', codes=(0, 1, 4))

# --- verdicts -----------------------------------------------------------------------------------------------
def while_alive(samples):
    return [s for s in samples if s['alive_after']]


problems = []
for key in ('idle_1', 'idle_2', 'idle_3'):
    v = verdict[key]
    if v['pane_guard_id'] != 0 or v['pane_guard_pane'] != 0:
        problems.append(f'{key}: an idle codex pane read {v["pane_guard_id"]}/{v["pane_guard_pane"]}, not 0')
    if '\tRUNNING\t' not in v['board'] and '\tIDLE\t' not in v['board']:
        problems.append(f'{key}: board row {v["board"]!r}')
for key in ('nested', 'bgterm'):
    live = while_alive(verdict[key]['samples'])
    if not live:
        problems.append(f'{key}: no sample was taken while the process lived')
    for s in live:
        if s['code'] != 11:
            problems.append(f'{key} sample {s["i"]}: pane-guard {s["code"]} while the worker was mid-turn (want 11)')
        if 'differs from record runtime' in s['board'] or '\tBLOCKED\t' in s['board']:
            problems.append(f'{key} sample {s["i"]}: board {s["board"]!r}')
if verdict['box_runtime'] != 'claude':
    problems.append(f'box runtime moved to {verdict["box_runtime"]!r}')
verdict['problems'] = problems
(evidence / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
if problems:
    print('FAIL OR:\n  ' + '\n  '.join(problems), flush=True)
    sys.exit(1)
print('PASS OR: a codex worker on a claude box reads 0 idle, 11 mid-turn (nested claude and background terminal), '
      'and the board never calls it a runtime mismatch', flush=True)
