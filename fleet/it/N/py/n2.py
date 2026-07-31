"""N2 — the captured pane round-trips through the predicates: what the probe captures is what the
predicates are handed, and both agree with pane-guard's own answer."""
import os, subprocess, sys
from pathlib import Path
from fleet.session import SessionLayer, default_probes
name = os.environ["W1"]
sl = SessionLayer(default_probes())
captured = sl.pane(name)
on_disk = Path(os.environ["EV"], "N2-pane.txt").read_text()
print("probe capture lines:", len(captured.splitlines()), "tmux capture lines:", len(on_disk.splitlines()))
assert captured.rstrip("\n") == on_disk.rstrip("\n"), "the probe's capture differs from tmux's own"
print("busy:", sl.busy(captured), "unsubmitted:", repr(sl.unsubmitted(captured)))
assert sl.busy(captured) is False
assert sl.unsubmitted(captured) is None, "a quiet shell reported queued text"
done = subprocess.run([sys.executable, "-m", "fleet.cli", "pane-guard", "--pane", name],
                      capture_output=True, text=True, env=dict(os.environ))
print("pane-guard rc:", done.returncode)
print(done.stdout)
assert done.returncode in (0, 12), f"pane-guard rc={done.returncode}"
print("OK N2: the captured text round-trips — probe == tmux, busy=False, unsubmitted=None, and "
      f"pane-guard agrees (rc={done.returncode}: a bash pane carries no claude marker)")
