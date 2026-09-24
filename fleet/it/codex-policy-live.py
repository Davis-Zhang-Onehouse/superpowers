"""CXP (FB-110, D-45): a codex worker that fleet launches or revives runs UNATTENDED with the operator's policy —
approval=never, inside the workspace-write sandbox, network on — on a REAL codex pane.

A private store, a private itfleet-CXP- tmux server and a private CODEX_HOME (the root's credential and top-level keys
copied read-only, so "no policy on the argv" means exactly what a production worker inherits: on-request). The slot is
the ws5 shape: a LINKED WORKTREE of a repository outside the slot. The seed asks the worker to run one probe script,
which:
  - commits in the slot repo (git writes the common dir, outside the slot);
  - writes into FLEET_INSTANTS;
  - does a network operation: a read-only `git ls-remote` of the fork over ssh (never a push);
  - writes OUTSIDE every writable root, which the sandbox must DENY (not prompt, not allow).
Then the pane is killed and `fleet revive`d (dry-run first), and the resumed session runs the probe again.

CXP_EXPECT=green (the fix) asserts all of that with NO keystroke from this harness. CXP_EXPECT=red (the base) asserts the
defect instead: the worker stops at an operator dialog, or the probe's commit/network steps fail. At red the harness
answers only codex's update modal ("2. Skip", as RTC does), so that what stops the worker is the policy, not the modal.
A folder-trust screen is never answered: the answer persists into the CLI configuration.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'fleet/src'))
from fleet.runtime import plain  # noqa: E402
from fleet.store import Store  # noqa: E402

root = Path(os.environ['RT_ATTEMPT']).resolve()
socket = os.environ['FLEET_TMUX_SOCKET']
assert socket.startswith('itfleet-CXP-'), socket
assert root.is_relative_to(Path(__file__).resolve().parent)
EXPECT = os.environ.get('CXP_EXPECT', 'green')
assert EXPECT in ('green', 'red'), EXPECT
limit = float(os.environ.get('RT_LIVE_TIMEOUT', '600'))
codex_source = Path(os.environ.get('CXP_CODEX_HOME', '/home/ubuntu/davis_root/.codex')).resolve(strict=True)
FORK = os.environ.get('CXP_REMOTE', 'git@github.com:Davis-Zhang-Onehouse/superpowers.git')

for key in ('FLEET_HOME', 'FLEET_INSTANTS', 'FLEET_ROOT', 'FLEET_INSTANT', 'FLEET_RELEASES', 'FLEET_BIN',
            'INSTANT', 'GH_TOKEN'):
    os.environ.pop(key, None)
os.environ['FLEET_HOME'] = str(root / 'store')
os.environ['FLEET_INSTANTS'] = str(root / 'instants')
(root / 'instants').mkdir()
evidence = root / 'evidence'
evidence.mkdir()
log = (evidence / 'commands.jsonl').open('w')
store = Store(root / 'store')
verdict = dict(expect=EXPECT)
keystrokes = []                       # every key this harness sends, so "no human keystroke" is a count, not a claim


def git(*args, cwd=None):
    return subprocess.run(['git', '-c', 'user.email=it@fleet', '-c', 'user.name=it', *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


def command(args, codes=(0,)):
    done = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, cwd=root)
    log.write(json.dumps(dict(argv=args, code=done.returncode, out=done.stdout, err=done.stderr)) + '\n')
    log.flush()
    if done.returncode not in codes:
        raise RuntimeError(f'{args}: exit {done.returncode}: {done.stderr}{done.stdout}')
    return done


def fleet(*args, codes=(0,)):
    return command([str(repo / 'bin/fleet'), *args, '--porcelain'], codes)


def fields(output):
    return dict(line.split('\t', 1) for line in output.splitlines() if '\t' in line)


def tmux(*args, codes=(0,)):
    return command(['tmux', '-L', socket, *args], codes)


def send_key(name, key):
    keystrokes.append(key)
    tmux('send-keys', '-t', '=' + name + ':', key)


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


# --- the private codex configuration -----------------------------------------------------------------------
def private_codex_home(trusted):
    """The root's credential (0600, removed at teardown) and ONLY its top-level keys — so the approval and sandbox
    defaults a worker inherits here are this root's (on-request, workspace-write) — plus trust for the paths the
    worker opens, so no trust screen can appear."""
    home = root / 'codex-home'
    home.mkdir(mode=0o700)
    shutil.copy2(codex_source / 'auth.json', home / 'auth.json')
    (home / 'auth.json').chmod(0o600)
    top = []
    for line in (codex_source / 'config.toml').read_text().splitlines():
        if line.lstrip().startswith('['):
            break
        top.append(line)
    body = '\n'.join(top).rstrip() + '\n\n' + ''.join(f'[projects."{path}"]\ntrust_level = "trusted"\n\n'
                                                      for path in dict.fromkeys(map(str, trusted)))
    (home / 'config.toml').write_text(body)
    return home


# --- set-up: a worktree-shaped slot, a probe, a trivial profile ------------------------------------------------
main = root / 'main'
slot = root / 'slot'
outside = root / 'outside'
for path in (main, slot, outside):
    path.mkdir()
git('init', '-q', str(main))
git('commit', '-q', '--allow-empty', '-m', 'init', cwd=main)
git('worktree', 'add', '-q', '--detach', str(slot / 'repo'), cwd=main)
codex_home = private_codex_home((slot, main, slot / 'repo', root))
os.environ['CODEX_HOME'] = str(codex_home)
(root / 'owners.tsv').write_text(f'{root}\tcodex-policy-live-test\n')
os.environ['CLAUDE_OWNERS_MAP'] = str(root / 'owners.tsv')

probe = root / 'probe.sh'
probe.write_text(f'''#!/usr/bin/env bash
# CXP probe, run BY the codex worker inside its sandbox. Every step reports; none stops the next.
n="${{1:?run number}}"
out="$INSTANT/cxp-result-$n.txt"
{{
echo "start $n"
if git -C {slot / 'repo'} -c user.email=it@fleet -c user.name=it commit -q --allow-empty -m "cxp probe $n" 2>&1; then
  echo "commit:OK"; else echo "commit:FAIL"; fi
if echo "written by the codex worker" > "$FLEET_INSTANTS/cxp-instants-write-$n.txt"; then
  echo "instants-write:OK"; else echo "instants-write:FAIL"; fi
if timeout 30 git ls-remote {FORK} HEAD >/dev/null 2>&1; then echo "network:OK"; else echo "network:FAIL"; fi
err=$(touch {outside}/cxp-outside-$n 2>&1)
if [ -e {outside}/cxp-outside-$n ]; then echo "outside-write:ALLOWED"; else echo "outside-write:DENIED $err"; fi
echo "end $n"
}} 2>&1 | tee "$out"
''')
probe.chmod(0o755)

fleet('runtime', '--set', 'claude')          # the davis box's own selection; codex is chosen per dispatch
fleet('enroll', '--slot', str(slot))
profile = root / 'profile'
shutil.copytree(repo / 'fleet/tests/fixtures/profiles/workerCompliant', profile)
ASK = ('This is an isolated fleet integration test. Run exactly this one shell command, once, with your shell tool: '
       '`bash {probe} {n}`. Do not retry it, do not change it, do not request approval or escalated permissions, '
       'and run nothing else. Then reply with exactly the word {word} and stop.')
#: `CXP_ESCALATE=1` (red only): the seed invites the worker to retry a failed step with escalated permissions — what a
#: real worker does when its commit or push fails — so the base's on-request policy shows its approval prompt.
ESCALATE = os.environ.get('CXP_ESCALATE') == '1'
assert not (ESCALATE and EXPECT == 'green'), 'the green case never asks for escalation'
seed = ASK.format(probe=probe, n=1, word='DONE')
if ESCALATE:
    seed = (f'This is an isolated fleet integration test. Step 1: run `bash {probe} 1` with your shell tool. Step 2: if '
            f'its output contains commit:FAIL or network:FAIL, you MUST run exactly the same command `bash {probe} 1` '
            f'once more, this time requesting escalated permissions (sandbox_permissions="require_escalated", '
            f'justification "integration test needs git and network"). Step 3: reply with exactly the word DONE.')
(profile / 'seed.txt').write_text('({{TITLE}}) ' + seed + '\n')
#: The resumed turn is asked in ONE short line through `fleet send`: a 358-char line that wraps in codex 0.156's input
#: box read `uncertain-after-insertion` (routed as ISSUES I-3 of the FB-110 instant; not this case's subject).
shutil.copy2(probe, slot / 'p.sh')
message = root / 'again.txt'
message.write_text('Run `bash p.sh 2` once with your shell tool, then reply with exactly the word AGAIN.')


# --- observation --------------------------------------------------------------------------------------------
def guard(record):
    return fleet('pane-guard', '--id', record.todo_id, codes=tuple(range(16))).returncode


def worker_argv(record):
    pid = tmux('display-message', '-p', '-t', '=' + record.tmux + ':', '#{pane_pid}').stdout.strip()
    return Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]


def result(record, n):
    path = Path(record.child_instant) / f'cxp-result-{n}.txt'
    text = path.read_text() if path.exists() else ''
    return text if f'end {n}' in text else None


def codex_transcript():
    for path in (codex_home / 'sessions').rglob('rollout-*.jsonl'):
        with path.open() as handle:
            head = json.loads(handle.readline())
        if head.get('type') == 'session_meta' and head.get('payload', {}).get('cwd') == str(slot):
            return path
    return None


def transcript_facts(path):
    """What the SESSION recorded, never fleet's own view: the policy of every turn, any approval request, and the
    probe's output as the tool returned it to the model."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    turns = [row['payload'] for row in rows if row.get('type') == 'turn_context']
    approvals = [row for row in rows if 'approval' in json.dumps(row.get('payload', {}).get('type', '')).lower()
                 or 'approval' in str(row.get('type', '')).lower()]
    outputs = [row['payload'].get('output') for row in rows
               if row.get('type') == 'response_item' and row.get('payload', {}).get('type') in
               ('function_call_output', 'custom_tool_call_output')]
    outputs = [o if isinstance(o, str) else json.dumps(o) for o in outputs]
    return dict(session=rows[0]['payload']['id'],
                policies=[dict(approval=t.get('approval_policy'), sandbox=t.get('sandbox_policy')) for t in turns],
                approval_rows=approvals,
                probe_outputs=[o for o in outputs if 'outside-write:' in o])


#: The only screen this harness ever answers, and only at red (see the module docstring).
UPDATE = ('update available', '2. skip')
TRUST = ('trust this folder', 'do you trust the contents', 'trust the files in this folder')


def answer_update(name, text):
    lowered = plain(text).lower()
    if any(marker in lowered for marker in TRUST):
        raise RuntimeError(f'{name} shows a folder-trust screen: the private trust list missed a path; never answered')
    if UPDATE[0] not in lowered:
        return False
    if EXPECT == 'green':
        raise RuntimeError(f'{name} shows the update modal although fleet disables the startup update check')
    for _ in range(5):
        rows = [row.strip().lower() for row in plain(frame(name, 'update')).splitlines()]
        chosen = [row for row in rows if row.startswith(('❯', '›', '>'))]
        if chosen and UPDATE[1] in chosen[-1]:
            send_key(name, 'Enter')
            time.sleep(2)
            return True
        send_key(name, 'Down')
        time.sleep(0.5)
    raise RuntimeError(f'could not select "2. Skip" on {name}')


def run_probe(record, n, tag):
    """Wait for probe run `n` to finish with the pane idle (green), or for the defect (red). Returns the outcome."""
    codes = []
    stuck = dict(since=None)

    def step():
        code = guard(record)
        if not codes or codes[-1] != code:
            codes.append(code)
            frame(record.tmux, f'{tag}-guard{code}-{len(codes)}')
        text = tmux('capture-pane', '-p', '-t', '=' + record.tmux + ':', codes=(0, 1)).stdout
        if code in (14, 15) and answer_update(record.tmux, text):
            return None
        done = result(record, n)
        if done is not None and code == 0:
            return dict(kind='finished', result=done)
        #: A pane that is not idle and has not changed for 30 s is waiting on something that is not the model — whatever
        #: `pane-guard` calls it (an unrecognised modal reads 14, FB-105). A recognised dialog (15) is a stall at once.
        if code != 0 and text == stuck.get('text'):
            if code == 15 or time.monotonic() - stuck['since'] > 30:
                frame(record.tmux, f'{tag}-stalled{code}')
                return dict(kind='stalled', code=code, result=result(record, n) or '', frame=plain(text))
        else:
            stuck.update(text=text, since=time.monotonic())
        return None
    outcome = wait_for(f'{record.todo_id} probe {n} ({EXPECT})', step, step=3)
    outcome['guard_codes'] = codes
    return outcome


def assert_green(outcome, n):
    assert outcome['kind'] == 'finished', outcome
    lines = outcome['result']
    for needle in ('commit:OK', 'instants-write:OK', 'network:OK', 'outside-write:DENIED'):
        assert needle in lines, (needle, lines)
    assert 'Read-only file system' in lines, lines          # denied BY THE SANDBOX, not by permissions or a prompt
    assert f'cxp probe {n}' in git('log', '--format=%s', '-3', cwd=slot / 'repo'), 'the commit is not in the repo'
    assert (root / 'instants' / f'cxp-instants-write-{n}.txt').exists()
    assert not (outside / f'cxp-outside-{n}').exists()
    #: No dialog, ever; and no unrecognised frame once the worker has started working. A LEADING 14 is codex's own
    #: startup frame ("model: loading", before the seed is submitted), seen identically at the base.
    codes = outcome['guard_codes']
    assert 15 not in codes, codes
    assert 14 not in codes[1:] and (not codes or codes[0] in (14, 11, 0)), codes


POLICY = ['-a', 'never', '-s', 'workspace-write', '-c', 'sandbox_workspace_write.network_access=true']


def argv_has_policy(argv):
    joined = ' '.join(argv)
    return all(' '.join(POLICY[i:i + 2]) in joined for i in range(0, len(POLICY), 2))


(evidence / 'environment.json').write_text(json.dumps(dict(
    revision=subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
    dirty=subprocess.run(['git', '-C', str(repo), 'status', '--porcelain', 'fleet/src'], capture_output=True,
                         text=True).stdout.strip(),
    codex=command(['codex', '--version']).stdout.strip(), socket=socket, root=str(root), expect=EXPECT,
    codex_home=str(codex_home), codex_source=str(codex_source),
    codex_home_config=(codex_home / 'config.toml').read_text()), indent=2) + '\n')

# --- (1) dispatch a codex worker; it runs the probe with no keystroke ----------------------------------------
out = fields(fleet('dispatch', '--profile', str(profile), '--title', 'cxp codex', '--slot', 'slot', '--cap', '1',
                   '--runtime', 'codex').stdout)
record = store.read(out['todo_id'])
verdict['dispatch_rows'] = out
verdict['argv'] = worker_argv(record)[:-1] + ['<seed>']
verdict['argv_has_policy'] = argv_has_policy(verdict['argv'])
verdict['brief'] = fleet('brief', '--instant', record.child_instant).stdout
first = run_probe(record, 1, 'launch')
verdict['launch'] = first
transcript = wait_for('codex transcript', codex_transcript)
verdict['launch_transcript'] = transcript_facts(transcript)
verdict['keystrokes_after_launch'] = list(keystrokes)

if EXPECT == 'red':
    #: RED: the base policy stops or cripples the unattended worker. Either shape is the defect; a clean finish is not.
    red = first['kind'] == 'stalled' or (not ESCALATE and any(bad in first.get('result', '')
                                                              for bad in ('commit:FAIL', 'network:FAIL')))
    verdict['escalate'] = ESCALATE
    verdict['red_observed'] = red
    verdict['red_shape'] = ('stalled at an operator dialog' if first['kind'] == 'stalled' else
                            'probe steps failed: ' + ' '.join(l for l in first.get('result', '').split('\n') if 'FAIL' in l))
    (evidence / 'verdict.json').write_text(json.dumps(verdict, indent=2, default=str) + '\n')
    tmux('kill-session', '-t', '=' + record.tmux)
    fleet('abort', '--instant', record.child_instant, '--reason', 'CXP red finished', codes=(0, 1, 2, 4))
    (codex_home / 'auth.json').unlink()
    assert red, verdict
    print(f'PASS CXP red: {verdict["red_shape"]}')
    sys.exit(0)

assert verdict['argv_has_policy'], verdict['argv']
assert 'codex_policy' in out and 'approval=never' in out['codex_policy'], out
assert 'approval=never' in verdict['brief'], verdict['brief']
assert_green(first, 1)
facts = verdict['launch_transcript']
assert facts['policies'] and all(p['approval'] == 'never' for p in facts['policies']), facts['policies']
assert all((p['sandbox'] or {}).get('type') == 'workspace-write' and (p['sandbox'] or {}).get('network_access') is True
           for p in facts['policies']), facts['policies']
assert not facts['approval_rows'], facts['approval_rows']
assert any('outside-write:DENIED' in o and 'Read-only file system' in o for o in facts['probe_outputs']), facts
assert keystrokes == [], keystrokes

# --- (2) kill and revive: the resumed session has the same policy, still with no keystroke -------------------
session_id = facts['session']
tmux('kill-session', '-t', '=' + record.tmux)
wait_for(f'{record.tmux} gone', lambda: tmux('has-session', '-t', '=' + record.tmux, codes=(0, 1)).returncode == 1)
verdict['revive_dry_run'] = fields(fleet('revive', '--id', record.todo_id, '--session-id', session_id, '--dry-run').stdout)
assert 'approval=never' in verdict['revive_dry_run'].get('codex_policy', ''), verdict['revive_dry_run']
verdict['revive_rows'] = fields(fleet('revive', '--id', record.todo_id, '--session-id', session_id).stdout)
verdict['revive_argv'] = worker_argv(record)
assert 'resume' in verdict['revive_argv'] and session_id in verdict['revive_argv'], verdict['revive_argv']
assert argv_has_policy(verdict['revive_argv']), verdict['revive_argv']
wait_for(f'{record.todo_id} idle after revive', lambda: guard(record) == 0, step=3)
try:
    fleet('send', '--id', record.todo_id, '--message-file', str(message))
except RuntimeError:
    frame(record.tmux, 'send-failed')
    raise
second = run_probe(record, 2, 'revive')
verdict['revive'] = second
assert_green(second, 2)
facts2 = transcript_facts(transcript)
verdict['revive_transcript'] = facts2
assert facts2['session'] == session_id
assert all(p['approval'] == 'never' for p in facts2['policies']), facts2['policies']
assert not facts2['approval_rows'], facts2['approval_rows']
assert keystrokes == [], keystrokes
verdict['keystrokes_total'] = len(keystrokes)

tmux('kill-session', '-t', '=' + record.tmux)
fleet('abort', '--instant', record.child_instant, '--reason', 'CXP finished', codes=(0, 1, 2, 4))
(evidence / 'verdict.json').write_text(json.dumps(verdict, indent=2, default=str) + '\n')
(codex_home / 'auth.json').unlink()
print('PASS CXP: launch and revive ran unattended with approval=never inside workspace-write+network; commit, '
      'FLEET_INSTANTS write and ssh ls-remote succeeded; the write outside every root was denied by the sandbox')
