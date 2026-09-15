#!/usr/bin/env bash
# scripts/tests/fleet-revive.sh — `scripts/fleet-revive.sh` against real roots, real stores and real
# transcripts under mktemp -d. Spends no claude: `fleet revive` is intercepted by a logging shim for the
# start, and everything else (`board`, `status`, `leases`, `runtime`, `pane-guard`) is the real binary.
#
#   bash scripts/tests/fleet-revive.sh      # ~10s
#
# What is asserted, and why each case exists:
#   outside-root      no marker above the cwd → rc 2, nothing called (the partner's "error out" rule)
#   stale-env         FLEET_HOME/FLEET_TMUX_SOCKET exported for another root are dropped, not honoured
#   claude-seed-match one DEAD Claude record → its transcript is the one carrying its seed, not the decoy
#                     (same cwd, another seed), not the subagent file, not the older occupant
#   latest-of-two     two transcripts carry one seed → the latest-started is chosen and both are printed
#   revive-all        `revive` dry-runs every record, then starts every record, then reports pane-guard
#   runtime-mismatch  the fleet set to codex while the records ran on claude → rc 2, no start
#   abort-recorded    an abort.json in one instant → rc 2, no start (the other record is not started either)
#   no-seed-match     a seed no transcript received → rc 2, no start
#   codex-seed-match  a DEAD Codex record in a codex fleet → its rollout by session_meta cwd + seed
#   nothing-dead      an empty board → rc 0
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$REPO/fleet/src"
python3 - "$REPO" <<'PY'
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fleet.pool import Pool
from fleet.store import Record, Store
from fleet.runtime_config import write_runtime

repo = Path(sys.argv[1])
script = repo / 'scripts/fleet-revive.sh'
real_fleet = repo / 'bin/fleet'
pid = os.getpid()
failures = []


def check(name, condition, detail=''):
    print(('  ok   ' if condition else '  FAIL ') + name + ('' if condition else '  ' + str(detail)[:600]))
    if not condition:
        failures.append(name)


home = Path(tempfile.mkdtemp(prefix='fleet-revive-test-'))
try:
    # The marker walk stops BELOW $HOME, so every fixture root lives one level under a fake HOME.
    env_base = dict(os.environ, HOME=str(home), FLEET_BIN=str(real_fleet))
    for key in ('FLEET_HOME', 'FLEET_ROOT', 'FLEET_TMUX_SOCKET', 'FLEET_RELEASES', 'FLEET_INSTANTS'):
        env_base.pop(key, None)

    log = home / 'revive-calls.log'
    shim = home / 'fleet-shim'
    shim.write_text('#!/usr/bin/env bash\n'
                    'if [ "${1:-}" = revive ]; then printf "%s\\n" "$*" >> ' + str(log) + '; exit 0; fi\n'
                    'exec ' + str(real_fleet) + ' "$@"\n')
    shim.chmod(0o700)

    def run(cwd, mode, env=None, fleet=None):
        e = dict(env_base if env is None else env)
        if fleet:
            e['FLEET_BIN'] = str(fleet)
        return subprocess.run(['bash', str(script), mode], cwd=str(cwd), env=e, capture_output=True, text=True)

    def calls():
        return log.read_text().splitlines() if log.exists() else []

    def make_root(name, runtime=None):
        root = home / (name + '_root')
        root.mkdir()
        (root / '.fleet-root').write_text(json.dumps({'name': name}) + '\n')
        (root / 'instants').mkdir()
        if runtime:
            write_runtime(root / '.fleet', runtime)
        return root

    def claude_transcript(config, slot, uuid, seed_text, started, subagent=False):
        project = config / 'projects' / ('-' + str(slot).strip('/').replace('/', '-'))
        path = (project / uuid / 'subagents' / 'agent-abc.jsonl') if subagent else (project / (uuid + '.jsonl'))
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [dict(type='mode', sessionId=uuid),
                dict(type='attachment', sessionId=uuid, cwd=str(slot), timestamp=started),
                dict(type='user', sessionId=uuid, cwd=str(slot), timestamp=started,
                     message=dict(role='user', content=seed_text)),
                dict(type='assistant', sessionId=uuid, cwd=str(slot), timestamp=started,
                     message=dict(role='assistant', content=[dict(type='text', text='ok')]))]
        path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        return path

    def codex_transcript(config, slot, uuid, seed_text, started):
        path = config / 'sessions' / '2026' / '09' / '15' / ('rollout-2026-09-15T00-00-00-' + uuid + '.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [dict(timestamp=started, type='session_meta', payload=dict(id=uuid, cwd=str(slot), timestamp=started)),
                dict(timestamp=started, type='response_item',
                     payload=dict(type='message', role='user', content=[dict(type='input_text', text='<environment_context>\n<cwd>' + str(slot) + '</cwd>\n</environment_context>')])),
                dict(timestamp=started, type='response_item',
                     payload=dict(type='message', role='user', content=[dict(type='input_text', text=seed_text)]))]
        path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        return path

    def dead_record(root, name, slot_name, runtime, config, when, socket):
        instant = root / 'instants' / ('00000000-0915' + when + '-inflight-append-' + name)
        (instant / '.fleet').mkdir(parents=True)
        seed = ('You are a dispatched worker instant. Your workspace is ' + str(instant) +
                '.\n\nFIRST, orient yourself.\n    export INSTANT=' + str(instant) + '\n')
        (instant / '.fleet/seed.txt').write_text(seed)
        slot = root / slot_name
        slot.mkdir(exist_ok=True)
        record = Record(todo_id=name + '-0915' + when, child_instant=str(instant), base_instant='00000000',
                        slot=slot_name, tmux='dt-' + name, profile='', golden=str(slot), lineage_base='',
                        title=name, dispatched_at='2026-09-15T00:' + when[-2:] + ':00Z', runtime=runtime,
                        runtime_executable='/bin/true', runtime_config_dir=str(config),
                        tmux_socket=socket, launched_at='2026-09-15T00:' + when[-2:] + ':05Z',
                        root=str(root))
        pool = Pool(root / '.fleet', cwd_probe=lambda path: [], alive=lambda n: False)
        pool.enroll(slot)
        pool.claim(todo_id=record.todo_id, tmux=record.tmux, base_instant='00000000',
                   child_instant=str(instant), slot=slot_name)
        Store(root / '.fleet').write(record)
        return record, instant, slot, seed

    socket = 'itrevive-%d' % pid          # no server of that name exists, so every record reads DEAD

    # ---- root A: a claude fleet (legacy default), two DEAD records ------------------------------------
    A = make_root('revivea')
    cfgA = A / '.claude'
    r1, i1, s1, seed1 = dead_record(A, 'one', 'ws1', 'claude', cfgA, '0001', socket)
    r3, i3, s3, seed3 = dead_record(A, 'three', 'ws3', 'claude', cfgA, '0003', socket)
    U1 = '11111111-1111-4111-8111-111111111111'
    DECOY = '22222222-2222-4222-8222-222222222222'
    OLD = '33333333-3333-4333-8333-333333333333'
    U3a = 'aaaaaaaa-3333-4333-8333-333333333333'
    U3b = 'bbbbbbbb-3333-4333-8333-333333333333'
    claude_transcript(cfgA, s1, U1, seed1, '2026-09-15T00:01:10Z')
    claude_transcript(cfgA, s1, DECOY, 'You are a dispatched worker instant. Your workspace is /elsewhere.', '2026-09-15T00:01:20Z')
    claude_transcript(cfgA, s1, OLD, seed1.replace('0915', '0901'), '2026-09-01T00:01:10Z')
    claude_transcript(cfgA, s1, DECOY, seed1, '2026-09-15T00:01:30Z', subagent=True)   # seed text, but a subagent file
    claude_transcript(cfgA, s3, U3a, seed3, '2026-09-15T00:03:10Z')
    claude_transcript(cfgA, s3, U3b, seed3, '2026-09-15T00:09:10Z')                     # later-started: the resumed one

    # outside-root
    r = run(home, 'plan')
    check('outside-root: rc 2', r.returncode == 2, r.stderr)
    check('outside-root: names the marker', '.fleet-root' in r.stderr, r.stderr)

    # usage
    r = run(A, 'launcher')
    check('unknown subcommand: rc 2 with usage', r.returncode == 2 and 'usage' in r.stderr, r.stderr)

    # stale-env + claude-seed-match + latest-of-two, from a subdirectory of the root
    stale = dict(env_base, FLEET_HOME=str(home / 'nowhere/.fleet'), FLEET_TMUX_SOCKET='fleet-other',
                 FLEET_ROOT=str(home / 'nowhere'))
    r = run(A / 'ws1', 'plan', env=stale)
    check('stale-env: rc 0 from a subdirectory', r.returncode == 0, r.stderr + r.stdout)
    check('stale-env: says which exports it ignored', 'ignoring exported FLEET_HOME' in r.stderr, r.stderr)
    check('plan: names the root and its server', ('fleet root ' + str(A)) in r.stdout and 'fleet-revivea' in r.stdout, r.stdout)
    check('plan: both DEAD records', '2 DEAD record(s)' in r.stdout, r.stdout)
    check('claude-seed-match: record one → U1', re.search(r'transcript\s+' + U1, r.stdout) is not None, r.stdout)
    check('claude-seed-match: the decoy, the older occupant and the subagent file are not chosen',
          DECOY not in r.stdout and OLD not in r.stdout, r.stdout)
    check('latest-of-two: record three → the later-started U3b', re.search(r'transcript\s+' + U3b, r.stdout) is not None, r.stdout)
    check('latest-of-two: both candidates printed', ('2 transcripts carry this seed' in r.stdout) and U3a in r.stdout, r.stdout)
    check('plan: nothing started', 'plan only' in r.stdout and not calls(), r.stdout)

    # revive-all
    r = run(A, 'revive', fleet=shim)
    lines = calls()
    check('revive-all: rc 0', r.returncode == 0, r.stderr + r.stdout)
    dry = [l for l in lines if '--dry-run' in l]
    real = [l for l in lines if '--dry-run' not in l]
    check('revive-all: dry-run for every record before any start', len(dry) == 2 and len(real) == 2 and
          lines.index(dry[-1]) < lines.index(real[0]), lines)
    check('revive-all: exact session ids and roots on the start', any(('--id ' + r1.todo_id) in l and ('--session-id ' + U1) in l and ('--root ' + str(A)) in l for l in real)
          and any(('--id ' + r3.todo_id) in l and ('--session-id ' + U3b) in l for l in real), lines)
    check('revive-all: pane-guard reported per record', r.stdout.count('pane-guard') == 2, r.stdout)
    check('revive-all: summary', 'revived 2 of 2' in r.stdout, r.stdout)
    log.unlink()

    # runtime-mismatch
    write_runtime(A / '.fleet', 'codex')
    r = run(A, 'revive', fleet=shim)
    check('runtime-mismatch: rc 2', r.returncode == 2, r.stderr)
    check('runtime-mismatch: says so for both records', r.stdout.count('the record ran on claude and the fleet is set to codex') == 2, r.stdout)
    check('runtime-mismatch: nothing started', not calls(), calls())
    (A / '.fleet/runtime.json').unlink()

    # abort-recorded
    (i1 / '.fleet/abort.json').write_text('{"reason": "test"}\n')
    r = run(A, 'revive', fleet=shim)
    check('abort-recorded: rc 2', r.returncode == 2, r.stderr)
    check('abort-recorded: names fleet abort', 'fleet abort --id ' + r1.todo_id in r.stdout, r.stdout)
    check('abort-recorded: the other record is not started either', not calls(), calls())
    (i1 / '.fleet/abort.json').unlink()

    # no-seed-match
    (i1 / '.fleet/seed.txt').write_text('A seed nobody received.\n')
    r = run(A, 'revive', fleet=shim)
    check('no-seed-match: rc 2, nothing started', r.returncode == 2 and not calls(), r.stderr + r.stdout)
    check('no-seed-match: names the hand path', '--session-id <uuid>' in r.stdout, r.stdout)
    (i1 / '.fleet/seed.txt').write_text(seed1)

    # ---- root B: a codex fleet, one DEAD record ------------------------------------------------------
    B = make_root('reviveb', runtime='codex')
    cfgB = B / 'codex config'
    r2, i2, s2, seed2 = dead_record(B, 'two', 'ws2', 'codex', cfgB, '0002', socket)
    U2 = '01a0a164-0c0f-7f61-8683-08d4cfd7da59'
    codex_transcript(cfgB, s2, U2, seed2, '2026-09-15T00:02:10Z')
    codex_transcript(cfgB, s2, '01a0a164-0c0f-7f61-8683-000000000000', 'another prompt', '2026-09-15T00:02:20Z')
    r = run(B, 'plan')
    check('codex-seed-match: rc 0', r.returncode == 0, r.stderr + r.stdout)
    check('codex-seed-match: record two → U2', re.search(r'transcript\s+' + U2, r.stdout) is not None, r.stdout)
    check('codex-seed-match: runtime line', 'codex   (fleet selection: codex)' in r.stdout, r.stdout)

    # ---- root C: nothing dead ------------------------------------------------------------------------
    C = make_root('revivec')
    (C / 'ws1').mkdir()
    Pool(C / '.fleet', cwd_probe=lambda path: [], alive=lambda n: False).enroll(C / 'ws1')
    r = run(C, 'revive', fleet=shim)
    check('nothing-dead: rc 0 and says so', r.returncode == 0 and 'nothing to revive' in r.stdout, r.stderr + r.stdout)
    check('nothing-dead: nothing started', not calls(), calls())
finally:
    shutil.rmtree(home, ignore_errors=True)

if failures:
    print('FAIL: ' + ', '.join(failures))
    sys.exit(1)
print('PASS: fleet-revive.sh derives root, server, slot, configuration and transcript from the directory and the records, refuses outside a root, on a runtime mismatch, on a recorded abort and on an unmatched seed without starting anything, and revives every DEAD record of the root otherwise')
PY
