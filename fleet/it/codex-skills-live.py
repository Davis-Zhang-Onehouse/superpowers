"""CXS (FB-111): a REAL codex worker, dispatched by fleet, finds the superpowers skills, reads them and acts on them.

A private store, a private itfleet-CXS- tmux server, and a private CODEX_HOME holding a COPY of the credential (removed
at exit) and this root's top-level codex settings. The skills reach that CODEX_HOME the way they reach a root's: the
installer's one link, through a releases area OUTSIDE the checkout whose `current` is the fleet under test.

  step 0  (the fleet under test ships the gate) with nothing installed, `dispatch --runtime codex` exits 4, names the
          install command, and claims nothing;
  step 1  install, then `--check` exits 0;
  step 2  dispatch a codex worker whose seed asks it to load superpowers:systematic-debugging and fix a failing test,
          then load superpowers:using-fleet and answer from it. The transcript must show both SKILL.md files READ
          (their distinctive text in a tool output), and the files the worker wrote must show it ACTED on them:
          an RCA written before the fix, naming the skill's Phase 1, a passing test, and fleet's exit codes 3 and 4
          as the skill states them (facts a model does not know without the skill).

`CXS_INSTALL=0` skips steps 0 and 1: that is the RED capture, run against the BASE fleet (`CXS_FLEET_REPO`), where
the same probe finds no skills. In that mode nothing is asserted; `verdict.json` records what was observed.

The only keystrokes this harness sends answer codex's update modal ("2. Skip"). A folder-trust screen is never
answered (it would persist into a CLI config); the private CODEX_HOME pre-trusts this attempt's paths instead.
"""
import atexit
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

here = Path(__file__).resolve().parent
repo = here.parents[1]
sys.path.insert(0, str(repo / 'fleet/src'))
from fleet.runtime import plain  # noqa: E402
from fleet.store import Store  # noqa: E402

root = Path(os.environ['CXS_ATTEMPT']).resolve()
socket = os.environ['FLEET_TMUX_SOCKET']
assert socket.startswith('itfleet-CXS-'), socket
assert root.is_relative_to(here)
#: The fleet whose dispatch is under test. Default: this checkout. The RED capture points it at a base worktree.
fleet_repo = Path(os.environ.get('CXS_FLEET_REPO', str(repo))).resolve(strict=True)
install = os.environ.get('CXS_INSTALL', '1') == '1'
limit = float(os.environ.get('CXS_TIMEOUT', '900'))
#: Read ONLY: its credential and top-level defaults are copied into the private CODEX_HOME (D-35, FB-102).
codex_source = Path(os.environ.get('CXS_CODEX_HOME', '/home/ubuntu/davis_root/.codex')).resolve(strict=True)

for key in ('FLEET_HOME', 'FLEET_INSTANTS', 'FLEET_ROOT', 'FLEET_INSTANT', 'FLEET_RELEASES', 'FLEET_BIN', 'INSTANT',
            'CODEX_HOME'):
    os.environ.pop(key, None)
os.environ['FLEET_HOME'] = str(root / 'store')
os.environ['FLEET_INSTANTS'] = str(root / 'instants')
(root / 'instants').mkdir()
evidence = root / 'evidence'
evidence.mkdir()
log = (evidence / 'commands.jsonl').open('w')
verdict = dict(mode='green' if install else 'red', fleet_repo=str(fleet_repo))


def command(args, codes=(0,), cwd=None):
    done = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, cwd=cwd or root)
    log.write(json.dumps(dict(argv=args, code=done.returncode, out=done.stdout, err=done.stderr)) + '\n')
    log.flush()
    if done.returncode not in codes:
        raise RuntimeError(f'{args}: exit {done.returncode}: {done.stderr}{done.stdout}')
    return done


def fleet(*args, codes=(0,)):
    return command([str(fleet_repo / 'bin/fleet'), *args, '--porcelain'], codes)


def fields(output):
    return dict(line.split('\t', 1) for line in output.splitlines() if '\t' in line)


def tmux(*args, codes=(0,)):
    return command(['tmux', '-L', socket, *args], codes)


def frame(name, tag):
    text = tmux('capture-pane', '-e', '-p', '-t', '=' + name + ':', codes=(0, 1)).stdout
    (evidence / f'{name}.{tag}.frame').write_text(text)
    return text


def wait_for(label, predicate, step=3):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            print('PASS ' + label, flush=True)
            return value
        time.sleep(step)
    raise TimeoutError(f'{label} (after {limit:.0f}s); evidence in {root}')


# --- the private CODEX_HOME -----------------------------------------------------------------------------------
def private_codex_home():
    home = root / 'codex-home'
    home.mkdir(mode=0o700)
    shutil.copy2(codex_source / 'auth.json', home / 'auth.json')
    (home / 'auth.json').chmod(0o600)
    top = []
    for line in (codex_source / 'config.toml').read_text().splitlines():
        if line.lstrip().startswith('['):
            break                                    # only the top-level keys; no [projects.*] or other tables
        top.append(line)
    git = lambda *a: subprocess.run(['git', '-C', str(root), 'rev-parse', *a], capture_output=True, text=True).stdout.strip()
    common = git('--path-format=absolute', '--git-common-dir')
    trusted = list(dict.fromkeys(p for p in (str(Path(common).parent) if common else '', git('--show-toplevel'),
                                             str(root), str(slot)) if p))
    body = '\n'.join(top).rstrip() + '\n\n' + ''.join(f'[projects."{p}"]\ntrust_level = "trusted"\n\n' for p in trusted)
    (home / 'config.toml').write_text(body)
    #: FB-110: record what the fixture runs under, so a stall can be told apart from a skills failure. Nothing here
    #: changes the policy: the private home inherits the root's top-level keys as they are.
    verdict['codex_policy'] = {line.split('=', 1)[0].strip(): line.split('=', 1)[1].strip() for line in top
                               if '=' in line and line.split('=', 1)[0].strip() in
                               ('approval_policy', 'sandbox_mode', 'model', 'check_for_update_on_startup')}
    return home


#: The worker's slot is a fresh git repository OUTSIDE any superpowers checkout. The first CXS run put it under
#: fleet/it/, and its worker, with nothing installed, found and read the checkout's own `skills/` next to its cwd:
#: that measures the fixture, not a real project slot, and it would read a branch copy rather than the deployed one.
slot = Path(tempfile.mkdtemp(prefix='cxs-slot-')).resolve()
atexit.register(shutil.rmtree, slot, True)
subprocess.run(['git', 'init', '-q', str(slot)], check=True)
codex_home = private_codex_home()
atexit.register(lambda: (codex_home / 'auth.json').unlink(missing_ok=True))
os.environ['CODEX_HOME'] = str(codex_home)
#: Outside the checkout: `current` names a checkout, and a link to an ancestor inside it is a cycle for any rglob.
releases = Path(tempfile.mkdtemp(prefix='cxs-releases-'))
atexit.register(shutil.rmtree, releases, True)
(releases / 'current').symlink_to(repo, target_is_directory=True)

# --- screens -----------------------------------------------------------------------------------------------------
SCREENS = (('update available', '2. skip'),)
TRUST = ('trust this folder', 'do you trust the contents', 'trust the files in this folder')


def answer_screen(name):
    text = plain(frame(name, 'screen')).lower()
    if any(marker in text for marker in TRUST):
        raise RuntimeError(f'{name} shows a folder-trust screen; the private CODEX_HOME trust list missed a path')
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


def guard(record):
    return fleet('pane-guard', '--id', record.todo_id, codes=tuple(range(16))).returncode


# --- the codex transcript ------------------------------------------------------------------------------------------
def codex_transcript(slot):
    for path in (codex_home / 'sessions').rglob('rollout-*.jsonl'):
        try:
            with path.open() as handle:
                head = json.loads(handle.readline())
        except (OSError, ValueError):
            continue
        if head.get('type') == 'session_meta' and head.get('payload', {}).get('cwd') == str(slot):
            return path
    return None


def rows_of(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def said(rows):
    """Every assistant reply, in each shape codex records one. Measured on 0.156.1: the reply is a `response_item`
    `message` (role assistant) and `task_complete.last_agent_message`; older builds used `event_msg/agent_message`.
    The first CXS run read only the last shape and timed out on a worker that had answered DONE in 80s."""
    out = []
    for row in rows:
        payload = row.get('payload') or {}
        kind = payload.get('type')
        if row.get('type') == 'event_msg' and kind == 'agent_message':
            out.append(payload.get('message', ''))
        elif row.get('type') == 'event_msg' and kind == 'task_complete' and payload.get('last_agent_message'):
            out.append(payload['last_agent_message'])
        elif row.get('type') == 'response_item' and kind == 'message' and payload.get('role') == 'assistant':
            out.append(''.join(part.get('text', '') for part in payload.get('content', []) if isinstance(part, dict)))
    return out


def tool_calls(rows):
    """(call text, output text) for every tool call, joined by call_id. The call text is the JSON of its arguments,
    so a `cat .../SKILL.md` shows up whatever the tool is called in this codex version."""
    calls, outputs = {}, {}
    for row in rows:
        payload = row.get('payload') or {}
        if row.get('type') != 'response_item':
            continue
        kind = payload.get('type', '')
        if kind.endswith('_call') and payload.get('call_id'):
            calls[payload['call_id']] = json.dumps(payload.get('arguments') or payload.get('input') or payload.get('action'))
        elif kind.endswith('_call_output') and payload.get('call_id'):
            body = payload.get('output')
            outputs[payload['call_id']] = body if isinstance(body, str) else json.dumps(body)
    return [(calls[k], outputs.get(k, '')) for k in calls]


def read_skill(calls, skill, marker):
    """The call that opened `<skill>/SKILL.md` AND whose output carries text only that file has."""
    hits = [(c, o) for c, o in calls if f'{skill}/SKILL.md' in c]
    paths = sorted({m for c, _ in hits for m in re.findall(r'[\w./~-]*' + re.escape(f'{skill}/SKILL.md'), c)})
    via_link = [p for p in paths if p.startswith(str(codex_home / 'skills' / 'superpowers'))]
    return dict(opened=len(hits), content_seen=any(marker in o for _, o in hits), paths=paths, via_link=bool(via_link))


# --- set-up ----------------------------------------------------------------------------------------------------------
(evidence / 'environment.json').write_text(json.dumps(dict(
    revision=subprocess.run(['git', '-C', str(fleet_repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
    codex=command(['codex', '--version']).stdout.strip(), socket=socket, root=str(root), codex_home=str(codex_home),
    releases=str(releases), install=install), indent=2) + '\n')
fleet('runtime', '--set', 'claude')
(slot / 'calc.py').write_text('def mean(xs):\n    return sum(xs) / (len(xs) + 1)\n')
(slot / 'test_calc.py').write_text('from calc import mean\n\nassert mean([2, 4]) == 3, mean([2, 4])\nassert mean([5]) == 5, mean([5])\n'
                                   'print("OK")\n')
fleet('enroll', '--slot', str(slot))
profile = root / 'profile'
shutil.copytree(repo / 'fleet/tests/fixtures/profiles/workerCompliant', profile)
(profile / 'seed.txt').write_text(
    'This is an isolated fleet integration test ({{TITLE}}). Work only inside your current directory; do not run '
    'any fleet command.\n'
    '1. Load the superpowers:systematic-debugging skill and follow it to fix the failing test here '
    '(`python3 test_calc.py` fails). Before you change any code, write rca.md: the phase of the skill you are in, '
    'the evidence you captured, and the root cause. Then fix calc.py and run the test again.\n'
    '2. Load the superpowers:using-fleet skill. Using only what it says, write exit-codes.md: what fleet exit codes '
    '3 and 4 mean. If you cannot find a skill, write SKILL-NOT-FOUND.md naming it instead, and do not guess.\n'
    '3. Reply with the one word DONE.\n')

# --- step 0 + 1: the gate, then the install ----------------------------------------------------------------------------
gate_ships = (fleet_repo / 'scripts/fleet-codex-skills.sh').is_file()
if install:
    if gate_ships:
        refused = fleet('dispatch', '--profile', str(profile), '--title', 'cxs refused', '--cap', '2', '--runtime', 'codex',
                        codes=(4,))
        store = Store(root / 'store')
        verdict['step0'] = dict(exit=4, names_install='fleet-codex-skills.sh' in refused.stderr,
                                records=len(store.all()), stderr=refused.stderr.strip().splitlines()[:3])
        assert verdict['step0']['names_install'] and verdict['step0']['records'] == 0, verdict['step0']
    done = command(['bash', str(repo / 'scripts/fleet-codex-skills.sh'), '--codex-home', str(codex_home),
                    '--releases', str(releases)])
    check = command(['bash', str(repo / 'scripts/fleet-codex-skills.sh'), '--check', '--codex-home', str(codex_home),
                     '--releases', str(releases)])
    verdict['step1'] = dict(install=done.stdout.strip().splitlines(), check=check.stdout.strip().splitlines(),
                            link=os.readlink(codex_home / 'skills/superpowers'))

# --- step 2: the real worker -------------------------------------------------------------------------------------------
out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'cxs codex skills', '--slot', slot.name, '--cap', '2',
                   '--runtime', 'codex').stdout)
store = Store(root / 'store')
record = store.read(out['todo_id'])
verdict['dispatch_rows'] = {k: v for k, v in out.items() if k in ('runtime', 'model', 'codex_skills')}
seed_text = (Path(record.child_instant) / '.fleet/seed.txt').read_text()
(evidence / 'seed.txt').write_text(seed_text)


def finished():
    code = guard(record)
    if code in (14, 15) and answer_screen(record.tmux):
        return None
    if code == 15:
        frame(record.tmux, 'awaiting-operator')
        raise RuntimeError(f'{record.tmux} waits on an operator dialog (approval?) this harness does not answer; '
                           f'see {evidence} and FB-110')
    path = codex_transcript(slot)
    if code == 0 and path and any('DONE' in s for s in said(rows_of(path))):
        return path
    return None


transcript = wait_for('codex worker replied DONE', finished)
frame(record.tmux, 'final')
shutil.copy2(transcript, evidence / 'transcript.jsonl')
rows = rows_of(transcript)
calls = tool_calls(rows)
(evidence / 'tool-calls.json').write_text(json.dumps([dict(call=c, output=o[:4000]) for c, o in calls], indent=2) + '\n')
test = subprocess.run(['python3', 'test_calc.py'], cwd=slot, capture_output=True, text=True)
rca, codes = slot / 'rca.md', slot / 'exit-codes.md'
verdict.update(
    systematic_debugging=read_skill(calls, 'systematic-debugging', 'NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST'),
    using_fleet=read_skill(calls, 'using-fleet', 'refused by an admission rule'),
    codex_tools_opened=any('codex-tools.md' in c for c, _ in calls),
    skill_not_found=(slot / 'SKILL-NOT-FOUND.md').read_text() if (slot / 'SKILL-NOT-FOUND.md').exists() else None,
    rca=rca.read_text() if rca.exists() else None,
    rca_before_fix=rca.exists() and rca.stat().st_mtime_ns <= (slot / 'calc.py').stat().st_mtime_ns,
    calc=(slot / 'calc.py').read_text(), test_exit=test.returncode,
    exit_codes=codes.read_text() if codes.exists() else None,
    replies=said(rows)[-3:])
verdict['slot'] = str(slot)
for name in ('rca.md', 'exit-codes.md', 'calc.py', 'SKILL-NOT-FOUND.md'):
    if (slot / name).exists():
        shutil.copy2(slot / name, evidence / f'worker-{name}')
(evidence / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')

tmux('kill-session', '-t', '=' + record.tmux, codes=(0, 1))
fleet('abort', '--instant', store.read(record.todo_id).child_instant, '--reason', 'CXS finished', codes=(0, 1, 4))

if install:
    lowered = (verdict['exit_codes'] or '').lower()
    problems = [msg for ok, msg in (
        (verdict['systematic_debugging']['content_seen'], 'systematic-debugging/SKILL.md was not read'),
        (verdict['using_fleet']['content_seen'], 'using-fleet/SKILL.md was not read'),
        (verdict['systematic_debugging']['via_link'] and verdict['using_fleet']['via_link'],
         'a skill was read from somewhere other than the CODEX_HOME link to the deployed release'),
        (verdict['rca'] is not None and 'phase 1' in verdict['rca'].lower(), 'rca.md missing or names no Phase 1'),
        (verdict['rca_before_fix'], 'rca.md was written after calc.py changed'),
        (verdict['test_exit'] == 0, 'the test still fails'),
        ('no capacity' in lowered and 'admission' in lowered, 'exit-codes.md does not state the skill\'s 3 and 4'),
        (verdict['skill_not_found'] is None, 'the worker reported a skill it could not find'),
    ) if not ok]
    if problems:
        print('FAIL CXS: ' + '; '.join(problems), flush=True)
        sys.exit(1)
    print('PASS CXS: a real codex worker found, read and followed systematic-debugging and using-fleet', flush=True)
else:
    print(f"RED capture: systematic-debugging {verdict['systematic_debugging']}, using-fleet {verdict['using_fleet']}, "
          f"skill-not-found={verdict['skill_not_found'] is not None}", flush=True)
