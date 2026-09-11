#!/usr/bin/env bash
# Real record/config paths, including spaces; no model or worker is started.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$REPO/fleet/src"
python3 - "$REPO" <<'PY'
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from fleet.pool import Pool
from fleet.store import Record, Store
from fleet.runtime_config import write_runtime

repo = Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='fleet helper ') as directory:
    root = Path(directory)
    home = root/'store'
    instant = root/'instants/00000000-09110000-inflight-append-recover'
    instant.mkdir(parents=True)
    slot = root/'slot'; slot.mkdir()
    config = root/'codex config'; (config/'sessions').mkdir(parents=True)
    uuid = '12345678-1234-1234-1234-123456789abc'
    (config/'sessions'/('rollout-'+uuid+'.jsonl')).write_text(json.dumps(dict(type='session_meta',payload=dict(id=uuid,cwd=str(slot))))+'\n')
    record = Record(todo_id='recover-09110000', child_instant=str(instant),base_instant='00000000',slot='slot',tmux='itfleet-helper-recover',profile='',golden=str(slot),lineage_base='',title='recover',dispatched_at='2026-09-11T00:00:00Z', runtime='codex',runtime_executable='/bin/true',runtime_config_dir=str(config),tmux_socket='itfleet-helper-'+str(os.getpid()))
    pool=Pool(home,cwd_probe=lambda path:[],alive=lambda name:False)
    pool.enroll(slot)
    pool.claim(todo_id=record.todo_id,tmux=record.tmux,base_instant='00000000',child_instant=str(instant),slot='slot')
    Store(home).write(record);write_runtime(home,'codex')
    env=dict(os.environ,FLEET_BIN=str(repo/'bin/fleet'),FLEET_HOME=str(home),FLEET_INSTANTS=str(instant.parent),FLEET_TMUX_SOCKET=record.tmux_socket)
    helper=['bash',str(repo/'scripts/fleet-revive.sh')]
    for command in ('plan','transcripts'):
        result=subprocess.run(helper+[command,record.todo_id],env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        assert ('codex' if command=='plan' else uuid) in result.stdout,result.stdout
    assert not (instant/'.fleet/revive-launcher.sh').exists()
    result=subprocess.run(helper+['launcher',record.todo_id,uuid],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    launcher=(instant/'.fleet/revive-launcher.sh').read_text()
    argv=shlex.split(launcher.splitlines()[-1])[1:]
    assert argv[:2]==[str(repo/'bin/fleet'),'revive'],argv
    assert argv[argv.index('--home')+1]==str(home),argv
    assert '--last' not in argv
    result=subprocess.run(['bash',str(repo/'scripts/fleet-dispatch-launcher.sh')],env=env,capture_output=True,text=True)
    assert result.returncode==2
    assert 'dispatch' in result.stderr
    fake=root/'fake-fleet'
    fake.write_text('#!/usr/bin/env python3\nimport os,sys\nif sys.argv[1]=="reconcile": print("armed\\tid\\tinfo\\tstate COMPLETE, test")\nelse: print("kind\\tworker\\nevidence.pid\\t123\\nevidence.runtime\\t"+os.environ["TEST_RUNTIME"])\n')
    fake.chmod(0o700)
    for runtime,expected in [('claude','123'),('codex','')]:
        result=subprocess.run(['bash',str(repo/'scripts/fleet-finished-pids.sh'),'--finished-pids'],env=dict(env,FLEET_BIN=str(fake),TEST_RUNTIME=runtime),capture_output=True,text=True)
        assert result.returncode==0 and result.stdout.strip()==expected,(runtime,result.stdout,result.stderr)
print('PASS: exact-session helper quotes paths and watchdog exclusions remain Claude-only')
PY
