"""RTC (pt2, D-22/D-33): the per-dispatch runtime/model choice against the REAL native CLIs.

A private store whose box runtime is claude, a private itfleet-RTC- tmux server, trivial seeds:
  (a) `dispatch --model claude-fable-5-1` — the worker's own transcript records that model;
  (b) `dispatch --runtime codex` (codex's default model) — starts, seed-check VERIFIED, pane-guard classifies it;
  (d) each worker is killed and `fleet revive`d: the same runtime and model come back, and the revived session's
      next turn is answered by the same model (read from the transcript, never from fleet's own record).
The only keystrokes the harness sends itself answer codex's update modal ("2. Skip"); a folder-TRUST screen is never
answered, because the answer persists into the CLI's configuration.
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

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'fleet/src'))
from fleet.runtime import plain  # noqa: E402
from fleet.render import BOARD_COLUMNS  # noqa: E402
from fleet.store import Store  # noqa: E402

root = Path(os.environ['RT_ATTEMPT']).resolve()
socket = os.environ['FLEET_TMUX_SOCKET']
assert socket.startswith('itfleet-RTC-'), socket
assert root.is_relative_to(Path(__file__).resolve().parent)
MODEL = os.environ.get('RTC_CLAUDE_MODEL', 'claude-fable-5-1')
limit = float(os.environ.get('RT_LIVE_TIMEOUT', '600'))
claude_config = Path(os.environ.get('RTC_CLAUDE_CONFIG', '/home/ubuntu/davis_root/.claude')).resolve(strict=True)
#: The codex configuration this root uses, read ONLY: its credential and its top-level defaults are copied into a
#: PRIVATE `CODEX_HOME` below, so nothing codex writes (sessions, trust, history) lands in the shared one (D-35, PT2-I3).
codex_source = Path(os.environ.get('RTC_CODEX_HOME', '/home/ubuntu/davis_root/.codex')).resolve(strict=True)

# `IT_ENV_UNNAMED`: nothing ambient may name a fleet; this attempt names its own store and instants.
for key in ('FLEET_HOME', 'FLEET_INSTANTS', 'FLEET_ROOT', 'FLEET_INSTANT', 'FLEET_RELEASES', 'FLEET_BIN',
            'INSTANT'):
    os.environ.pop(key, None)
os.environ['FLEET_HOME'] = str(root / 'store')
os.environ['FLEET_INSTANTS'] = str(root / 'instants')
(root / 'instants').mkdir()


def private_codex_home():
    """A CODEX_HOME of this attempt's own: the source's auth.json (0600, removed at teardown), its top-level settings
    (so "no model flag" still means THIS root's configured default model), and trust for the checkout this attempt
    lives in. Codex keys trust by the main repository behind a worktree (the parent of `--git-common-dir`), so that, the
    toplevel and the attempt root are all listed."""
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
    toplevel = git('--show-toplevel')
    #: Measured (codex-cli 0.156.1): inside a git WORKTREE the trust screen says "Trusting will apply to the repository
    #: root" and names the MAIN repository — the parent of `--git-common-dir` — not the worktree's toplevel.
    common = git('--path-format=absolute', '--git-common-dir')
    repository = str(Path(common).parent) if common else ''
    trusted = list(dict.fromkeys(path for path in (repository, toplevel, str(root)) if path))
    body = '\n'.join(top).rstrip() + '\n\n' + ''.join(f'[projects."{path}"]\ntrust_level = "trusted"\n\n' for path in trusted)
    (home / 'config.toml').write_text(body)
    #: FB-111. A codex dispatch is refused when its CODEX_HOME cannot see the superpowers skills, so this home gets them
    #: the way a root's does: the installer's one link, through a releases area whose `current` is this checkout.
    #: Outside the checkout: `current` names the checkout itself, and a link to an ancestor inside it would be a cycle
    #: for any `rglob` over the tree. Removed when this process exits.
    releases = Path(tempfile.mkdtemp(prefix='rtc-releases-'))
    atexit.register(shutil.rmtree, releases, True)
    (releases / 'current').symlink_to(Path(__file__).resolve().parents[2], target_is_directory=True)
    subprocess.run(['bash', str(Path(__file__).resolve().parents[2] / 'scripts' / 'fleet-codex-skills.sh'),
                    '--codex-home', str(home), '--releases', str(releases)], check=True, capture_output=True)
    return home


codex_home = private_codex_home()
os.environ['CODEX_HOME'] = str(codex_home)
(root / '.claude').symlink_to(claude_config, target_is_directory=True)
(root / 'owners.tsv').write_text(f'{root}\truntime-choice-live-test\n')
os.environ['CLAUDE_OWNERS_MAP'] = str(root / 'owners.tsv')
evidence = root / 'evidence'
evidence.mkdir()
log = (evidence / 'commands.jsonl').open('w')
store = Store(root / 'store')
verdict = {}


def command(args, codes=(0,)):
    done = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90, cwd=root)
    log.write(json.dumps(dict(argv=args, code=done.returncode, out=done.stdout, err=done.stderr)) + '\n')
    log.flush()
    if done.returncode not in codes:
        raise RuntimeError(f'{args}: exit {done.returncode}: {done.stderr}{done.stdout}')
    return done


def fleet(*args, codes=(0,)):
    return command([os.environ['IT_FLEET'], *args, '--porcelain'], codes)   # the harness wrapper (B18)


def fields(output):
    return dict(line.split('\t', 1) for line in output.splitlines() if '\t' in line)


def tmux(*args, codes=(0,)):
    return command(['tmux', '-L', socket, *args], codes)


def frame(name, tag):
    text = tmux('capture-pane', '-e', '-p', '-t', '=' + name + ':', codes=(0, 1)).stdout
    (evidence / f'{name}.{tag}.frame').write_text(text)
    return text


def wait_for(label, predicate, step=2):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            print('PASS ' + label, flush=True)
            return value
        time.sleep(step)
    raise TimeoutError(f'{label} (after {limit:.0f}s); evidence in {root}')


#: The ONLY screen this harness answers in its own fixture sessions, with the row it selects: codex 0.156.0's
#: "Update available" modal, answered "2. Skip" (measured to leave `config.toml` untouched). Its hint row
#: `enter continue · esc …` is not yet a recognised dialog (`pane-guard 14`, ISSUES PT2-I2), so it is identified here
#: by its text. "Update now" (a global npm install) and "Skip until next version" (persisted) are never chosen.
#: A folder-TRUST screen is NEVER answered: both CLIs persist the answer into their configuration (ISSUES PT2-I3,
#: RV-19). For codex that is this attempt's PRIVATE `CODEX_HOME` (pre-trusted, so the screen means the private trust
#: list is wrong); for claude it is `.claude.json` under `RTC_CLAUDE_CONFIG`, the operator's shared config. The attempt
#: lives under `fleet/it/`, inside the checkout, so a trusted checkout needs no answer; an untrusted one stops the run
#: with the path to trust by hand.
SCREENS = (('update available', '2. skip'),)
TRUST = ('trust this folder', 'do you trust the contents', 'trust the files in this folder')


def answer_screen(name):
    """Answer a known startup screen in this harness's own session; False when the pane shows none of them."""
    text = plain(frame(name, 'screen')).lower()
    if any(marker in text for marker in TRUST):
        raise RuntimeError(f'{name} shows a folder-trust screen for {root}; this harness never answers one, because the '
                           f'answer is persisted into the CLI configuration. For a claude pane, trust the checkout by hand '
                           f'once under RTC_CLAUDE_CONFIG (or point it at a private copy); for a codex pane the private '
                           f'CODEX_HOME trust list (private_codex_home) missed a path — then re-run')
    wanted = [target for marker, target in SCREENS if marker in text]
    if not wanted:
        return False
    for _ in range(5):
        rows = [row.strip().lower() for row in plain(frame(name, 'screen')).splitlines()]
        chosen = [row for row in rows if row.startswith(('❯', '›', '>'))]
        if chosen and any(target in chosen[-1] for target in wanted):
            tmux('send-keys', '-t', '=' + name + ':', 'Enter')
            print(f'answered {chosen[-1]!r} on {name}', flush=True)
            time.sleep(2)
            return True
        tmux('send-keys', '-t', '=' + name + ':', 'Down')
        time.sleep(0.5)
    raise RuntimeError(f'could not select {wanted} on {name}; see its frames')


def guard(args):
    return fleet('pane-guard', *args, codes=tuple(range(16))).returncode


def settle(record):
    """Wait until the worker's pane is idle (0), answering only the update modal on the way; a trust screen stops the run."""
    seen = set()
    def idle():
        code = guard(['--id', record.todo_id])
        if code in (14, 15) and answer_screen(record.tmux):
            return False
        if code == 15:
            raise RuntimeError(f'{record.tmux} waits on an operator dialog this harness does not answer')
        if code not in (0, 11) and code not in seen:
            seen.add(code)
            frame(record.tmux, f'guard{code}-{int(time.time())}')      # the frame behind an unexpected code
        return code == 0
    wait_for(f'{record.todo_id} idle', idle, step=3)


def claude_transcript(slot):
    for path in (claude_config / 'projects').rglob('*.jsonl'):
        if 'subagents' in path.parts:
            continue
        try:
            with path.open() as handle:
                first = [json.loads(line) for _, line in zip(range(40), handle)]
        except (OSError, ValueError):
            continue
        if any(row.get('cwd') == str(slot) for row in first):
            return path
    return None


def claude_turns(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    out = []
    for row in rows:
        message = row.get('message') or {}
        if row.get('type') == 'assistant' and message.get('model') and message.get('model') != '<synthetic>':
            text = ''.join(part.get('text', '') for part in message.get('content', []) if isinstance(part, dict))
            out.append((message['model'], text))
    return out


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


def codex_turns(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    models = [row['payload'].get('model') for row in rows if row.get('type') == 'turn_context']
    said = []
    for row in rows:
        payload = row.get('payload') or {}
        if row.get('type') == 'event_msg' and payload.get('type') == 'agent_message':
            said.append(payload.get('message', ''))
        if (row.get('type') == 'response_item' and payload.get('type') == 'message'
                and payload.get('role') == 'assistant'):
            said.append(''.join(part.get('text', '') for part in payload.get('content', []) if isinstance(part, dict)))
    return models, said, rows[0]['payload']['id']


def worker_argv(record):
    """The argv of the native worker process in the record's pane (the launcher `exec`s it)."""
    pid = tmux('display-message', '-p', '-t', '=' + record.tmux + ':', '#{pane_pid}').stdout.strip()
    return Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]


def is_codex(argv):
    """codex-cli is a node script: the pane's process is `codex …` or `node /…/codex …`."""
    return bool(argv) and (Path(argv[0]).name == 'codex' or (Path(argv[0]).name == 'node' and len(argv) > 1
                                                             and Path(argv[1]).name == 'codex'))


def workspace_free(slot):
    for process in Path('/proc').iterdir():
        if process.name.isdigit():
            try:
                if (process / 'cwd').resolve(strict=True) == slot:
                    return False
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
    return True


def kill_and_wait(record, slot):
    tmux('kill-session', '-t', '=' + record.tmux)
    wait_for(f'{record.tmux} gone', lambda: tmux('has-session', '-t', '=' + record.tmux, codes=(0, 1)).returncode == 1)
    wait_for(f'{slot} free', lambda: workspace_free(slot))


# --- set-up: a claude box, two fresh slots, a trivial profile ---------------------------------------------
(evidence / 'environment.json').write_text(json.dumps(dict(
    revision=subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
    claude=command(['claude', '--version']).stdout.strip(), codex=command(['codex', '--version']).stdout.strip(),
    socket=socket, root=str(root), claude_config=str(claude_config), codex_home=str(codex_home),
    codex_source=str(codex_source),
    codex_configured_model=next((line.split('=', 1)[1].strip().strip('"') for line in
                                 (codex_home / 'config.toml').read_text().splitlines()
                                 if line.split('=')[0].strip() == 'model'), '')), indent=2) + '\n')
fleet('runtime', '--set', 'claude')
slots = {}
for name in ('slotA', 'slotB'):
    slots[name] = root / name
    slots[name].mkdir()
    fleet('enroll', '--slot', str(slots[name]))
profile = root / 'profile'
shutil.copytree(repo / 'fleet/tests/fixtures/profiles/workerCompliant', profile)
(profile / 'seed.txt').write_text(
    'This is an isolated fleet integration test ({{TITLE}}). Do not run any tool, command or skill and do not read '
    'any file. Reply with exactly the one word READY, then stop and wait for the next message.\n')
message = root / 'again.txt'
message.write_text('Reply with exactly the one word AGAIN, then stop. Do not run any tool.')

# --- (a) claude on a chosen model ----------------------------------------------------------------------------
out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'rtc claude', '--slot', 'slotA', '--cap', '2',
                   '--model', MODEL).stdout)
a = store.read(out['todo_id'])
assert (a.runtime, a.runtime_model) == ('claude', MODEL), a
argv_a = worker_argv(a)
assert '--model' in argv_a and argv_a[argv_a.index('--model') + 1] == MODEL, argv_a
settle(a)
transcript_a = wait_for('claude transcript', lambda: claude_transcript(slots['slotA']))
turns = wait_for('claude answered READY', lambda: [t for t in claude_turns(transcript_a) if 'READY' in t[1]] and claude_turns(transcript_a))
assert {model for model, _ in turns} == {MODEL}, turns
seed_a = fields(fleet('seed-check', '--id', a.todo_id).stdout)
verdict['a'] = dict(todo=a.todo_id, dispatch_rows={k: out[k] for k in ('runtime', 'model')},
                    argv=argv_a[:-1] + ['<seed>'], transcript=str(transcript_a), transcript_models=sorted({m for m, _ in turns}),
                    seed_check=fleet('seed-check', '--id', a.todo_id).stdout.strip().splitlines(),
                    pane_guard_id=guard(['--id', a.todo_id]), pane_guard_pane=guard(['--pane', a.tmux]))
assert verdict['a']['seed_check'][0].startswith('verified\t'), verdict['a']
assert verdict['a']['pane_guard_id'] == 0 and verdict['a']['pane_guard_pane'] == 0, verdict['a']   # RV-34

# --- (b) codex, default model, on the claude box ------------------------------------------------------------
out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'rtc codex', '--slot', 'slotB', '--cap', '2',
                   '--runtime', 'codex').stdout)
b = store.read(out['todo_id'])
assert (b.runtime, b.runtime_model) == ('codex', ''), b
argv_b = worker_argv(b)
assert is_codex(argv_b) and '-m' not in argv_b and '--model' not in argv_b, argv_b
settle(b)
transcript_b = wait_for('codex transcript', lambda: codex_transcript(slots['slotB']))
models_b, said_b, session_b = wait_for('codex answered READY', lambda: (lambda t: t if any('READY' in s for s in t[1]) else None)(codex_turns(transcript_b)))
assert fields(fleet('runtime').stdout)['runtime'] == 'claude'
configured = json.loads((evidence / 'environment.json').read_text())['codex_configured_model']
assert set(models_b) == {configured}, (models_b, configured)   # no -m = this root's configured default (D-35)
verdict['b'] = dict(todo=b.todo_id, dispatch_rows={k: out[k] for k in ('runtime', 'model')},
                    argv=argv_b[:-1] + ['<seed>'], transcript=str(transcript_b), default_models=sorted(set(models_b)),
                    seed_check=fleet('seed-check', '--id', b.todo_id).stdout.strip().splitlines(),
                    pane_guard_id=guard(['--id', b.todo_id]), pane_guard_pane=guard(['--pane', b.tmux]),
                    box_runtime='claude')
assert verdict['b']['seed_check'][0].startswith('verified\t'), verdict['b']
assert verdict['b']['pane_guard_id'] == 0 and verdict['b']['pane_guard_pane'] == 0, verdict['b']
board = fleet('board').stdout
runtime_col = BOARD_COLUMNS.index('runtime')
verdict['board_runtime'] = {line.split('\t')[0]: line.split('\t')[runtime_col] for line in board.splitlines()
                            if line.startswith((a.todo_id, b.todo_id))}
assert verdict['board_runtime'] == {a.todo_id: f'claude/{MODEL}', b.todo_id: 'codex'}, board

# --- (d) revive each with the same runtime and model ---------------------------------------------------------
session_a = transcript_a.stem
for record, slot, session in ((a, slots['slotA'], session_a), (b, slots['slotB'], session_b)):
    kill_and_wait(record, slot)
    revived = fields(fleet('revive', '--id', record.todo_id, '--session-id', session).stdout)
    argv = worker_argv(record)
    settle(record)
    fleet('send', '--id', record.todo_id, '--message-file', str(message))
    if record.runtime == 'claude':
        assert argv[argv.index('--model') + 1] == MODEL and '--resume' in argv, argv
        after = wait_for('claude answered AGAIN', lambda: (lambda t: t if any('AGAIN' in text for _, text in t) else None)(claude_turns(transcript_a)))
        assert {model for model, _ in after} == {MODEL}, after
        verdict['d_claude'] = dict(revive_rows=revived, argv=argv, transcript_models=sorted({m for m, _ in after}))
    else:
        assert is_codex(argv) and 'resume' in argv and session in argv and '-m' not in argv, argv
        models, said, _ = wait_for('codex answered AGAIN', lambda: (lambda t: t if any('AGAIN' in s for s in t[1]) else None)(codex_turns(transcript_b)))
        assert set(models) == set(models_b), (models, models_b)
        verdict['d_codex'] = dict(revive_rows=revived, argv=argv, models=sorted(set(models)))
    settle(record)
    kill_and_wait(record, slot)
    fleet('abort', '--instant', store.read(record.todo_id).child_instant, '--reason', 'RTC finished')

(evidence / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
(codex_home / 'auth.json').unlink()
print('PASS RTC: (a) model, (b) codex default on a claude box, (d) revive of both with the same runtime and model')
