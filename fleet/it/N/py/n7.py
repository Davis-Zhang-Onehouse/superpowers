"""N7 — liveness must never confuse a session with a longer one that it is a prefix of."""
import os
from fleet.session import SessionLayer, default_probes
sl = SessionLayer(default_probes())
long_name, short_name = os.environ["LONG"], os.environ["SHORT"]
print("sessions on the box that start with the prefix:")
print(open(os.environ["EV"] + "/N7-sessions.txt").read())
alive_long = sl.alive(long_name)
alive_short = sl.alive(short_name)
pane_long = sl.pane(long_name)
pane_short = sl.pane(short_name)
print(f"alive({long_name})={alive_long}  alive({short_name})={alive_short}")
print(f"pane({short_name}) first line: {pane_short.splitlines()[:1]}")
fails = []
if not alive_long:
    fails.append(f"{long_name} exists and alive() says False")
if alive_short:
    fails.append(f"{short_name} does NOT exist and alive() says True — the liveness probe resolved a "
                 f"prefix to {long_name}")
if pane_short.strip() and pane_short.strip() == pane_long.strip():
    fails.append(f"pane({short_name}) returned {long_name}'s screen: "
                 f"{pane_short.splitlines()[:1]}")
assert not fails, "\n".join(fails)
print("OK N7: the prefix name is not alive and does not capture the longer session's pane")
