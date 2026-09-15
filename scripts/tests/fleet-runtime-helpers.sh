#!/usr/bin/env bash
# The dispatch launcher outside a dispatch, and the watchdog's finished-pid shim on both runtimes; no model
# or worker is started. The revive helper is covered by scripts/tests/fleet-revive.sh.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$REPO/fleet/src"
python3 - "$REPO" <<'PY'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='fleet helper ') as directory:
    root = Path(directory)
    env=dict(os.environ,FLEET_BIN=str(repo/'bin/fleet'))
    for key in ('FLEET_HOME','FLEET_INSTANTS','FLEET_TMUX_SOCKET'): env.pop(key, None)
    result=subprocess.run(['bash',str(repo/'scripts/fleet-dispatch-launcher.sh')],env=env,capture_output=True,text=True)
    assert result.returncode==2
    assert 'dispatch' in result.stderr
    fake=root/'fake-fleet'
    fake.write_text('#!/usr/bin/env python3\nimport os,sys\nif sys.argv[1]=="reconcile": print("armed\\tid\\tinfo\\tstate COMPLETE, test")\nelse: print("kind\\tworker\\nevidence.pid\\t123\\nevidence.runtime\\t"+os.environ["TEST_RUNTIME"])\n')
    fake.chmod(0o700)
    for runtime,expected in [('claude','123'),('codex','')]:
        result=subprocess.run(['bash',str(repo/'scripts/fleet-finished-pids.sh'),'--finished-pids'],env=dict(env,FLEET_BIN=str(fake),TEST_RUNTIME=runtime),capture_output=True,text=True)
        assert result.returncode==0 and result.stdout.strip()==expected,(runtime,result.stdout,result.stderr)
print('PASS: the dispatch launcher refuses outside a dispatch and watchdog exclusions remain Claude-only')
PY
