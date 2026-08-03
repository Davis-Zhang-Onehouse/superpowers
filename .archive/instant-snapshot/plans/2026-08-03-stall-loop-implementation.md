# Stall Loop Implementation Plan (`G-1` + `G-2` + `G-10` + `G-11`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stalled dispatched instant is nudged automatically, through a verb that confirms delivery, and a child's parked question becomes visible to its coordinator — so the operator stops being the mitigation.

**Architecture:** `fleet` stays passive. `fleet pane-send` owns delivery (type → poll `pane-guard` for code `10` → Enter → confirm). `fleet nudge` owns the decision (it calls `reconcile()`, filters, and delivers). The existing `claude-watchdog.sh` `$INTERVAL` loop supplies the only heartbeat. Two state-model corrections land first: `PARKED` becomes actionable, and an `awaiting-ci` declaration requires a live watcher.

**Tech Stack:** Python 3.10 stdlib only (no third-party deps in `fleet/`), `unittest`, bash for the IT layer and the watchdog. tmux via injected `Probes`.

**Spec:** `../specs/2026-08-03-stall-loop-design.md` · **RCA:** `../investigations/g1-g2-stall-loop/analysis.md` · **State definitions:** `../investigations/g1-g2-stall-loop/state-vocabulary.md` · **Decisions:** `D-7`…`D-11` in `../DECISIONS.md`

## Global Constraints

- **Repo:** `/home/ubuntu/davis_root/superpowers`, branch `live`. Tests: `cd $REPO/fleet && PYTHONPATH=src python3 -m unittest discover -s tests` (~70s, **1183 tests green at `11f2f58`**).
- **TDD, red first, and CHECK THE FAILURE COUNT.** Three times in two days a filter or fixture made a test pass vacuously. A test that passes the moment you write it has proven nothing until a mutation shows it can fail.
- **Every fix to a check ships with a control** proving the check still fails when it should.
- **Never weaken an assertion to obtain a green.** A case that cannot pass is reported as one.
- **NEVER create, kill or write a `dt-` session on the DEFAULT tmux server.** `dt-*` on a *named* socket is a legitimate target — see Task 6.
- **Never touch** `~/.claude-dispatch-board`, `~/.claude-ws-pool`, or another effort's instant folder.
- **Push after every commit** (standing operator instruction).
- **One IT job at a time.** Concurrent runners contaminated a run already (`SI-36`).
- **Evidence into the instant by RELATIVE path, never `/tmp`.**
- `fleet/` has no third-party dependencies. Do not add one.
- Do not reformat or "tidy" code you are not changing. This codebase's comments carry findings; deleting one loses a measurement.

---

### Task 1: The `IDLE` detector gets a test (`G-10`)

`reconcile` produces `IDLE` and **no test drives it there** — disabling the detector leaves all 1183 tests green. `fleet nudge` actuates on `IDLE`, so this is step one, not a follow-up.

**Files:**
- Modify: `fleet/tests/test_reconcile.py` (add cases to the existing `SyntheticFleet`-based suite)
- Control (already written, do not modify): `bin/repro-g2-stall-loop.sh` in the instant

**Interfaces:**
- Consumes: `reconcile(store, pool, sessions, instants_dir, idle_after_s=1800)`; `SyntheticFleet` at `test_reconcile.py:60`; `QUIET_PANE`, `BUSY_PANE` module constants.
- Produces: nothing other tasks import. It is a guard.

**⚠️ This task's TDD cycle is inverted, deliberately.** The detector already works, so the new test passes the moment you write it. That proves nothing. **The red comes from the mutation control**: `M-1` and `M-3` currently SURVIVE, and after this task they must be KILLED. Do not skip step 2 or step 5.

- [ ] **Step 1: Record the control's CURRENT verdict (the red)**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure
bash bin/repro-g2-stall-loop.sh 2>&1 | tail -30
cp evidence/repro-g2/part3-mutations.tsv evidence/repro-g2/part3-mutations-BEFORE.tsv
cat evidence/repro-g2/part3-mutations-BEFORE.tsv
```

Expected, and this is the red you are fixing:
```
M-1	SURVIVED	AS-PREDICTED	the IDLE detector never fires …
M-2	KILLED	AS-PREDICTED	CONTROL: `FI-14`'s shipped one-line fix reverted …
M-3	SURVIVED	AS-PREDICTED	the activity probe always reports the instant as fresh …
```

- [ ] **Step 2: Add a helper to `SyntheticFleet` that ages an instant**

`_idle_for` reads the mtime of the instant directory, its direct children, and `.fleet/*`. Add this method to the `SyntheticFleet` class in `fleet/tests/test_reconcile.py`, after `launch`:

```python
    def age(self, todo_id, seconds):
        """Make an instant look untouched for `seconds`. `_idle_for` reads the instant directory, its
        direct children and `.fleet/*` — so all three must be aged, and aged LAST, because writing a
        declaration refreshes the mtime of the file it writes."""
        instant = self.paths[todo_id]
        old = time.time() - seconds
        paths = [instant] + list(instant.iterdir())
        for child in list(instant.iterdir()):
            if child.name == ".fleet" and child.is_dir():
                paths += list(child.iterdir())
        for path in paths:
            os.utime(path, (old, old))
```

Add `import os` and `import time` to the imports at the top of the file if they are not already there.

- [ ] **Step 3: Write the failing tests**

Add this class at the end of `fleet/tests/test_reconcile.py`:

```python
class TestTheIdleDetectorIsProduced(unittest.TestCase):
    """`G-10`. `FI-14` made `IDLE` actionable and shipped; nothing ever drove `reconcile` TO it.

    Its flagship test (`test_render.test_a_stalled_worker_is_counted_as_needing_a_human`) hand-builds a
    subject already labelled `IDLE` and asserts the banner counts it — so it passes whether or not the
    detector can ever produce one. Measured by mutation: disabling `_live_state`'s threshold branch, or
    making `_idle_for` always report fresh, leaves the whole suite green. The control that says the
    harness CAN kill is reverting `FI-14` itself, which dies in `test_render`.

    These cases drive the real join, so the detector has a guard for the first time.
    """

    def setUp(self):
        self.fleet = SyntheticFleet()

    def subjects(self, idle_after_s=1800):
        return {s.identity: s for s in reconcile(
            self.fleet.store, self.fleet.pool, self.fleet.sessions,
            self.fleet.instants, idle_after_s=idle_after_s)}

    def test_a_worker_untouched_past_the_threshold_is_produced_as_idle(self):
        self.fleet.dispatch("stalled-07300401", "00000000-07300401-inflight-append-stalled",
                            "ws9", "dt-stalled")
        self.fleet.launch("dt-stalled", 5101, "ws9", QUIET_PANE)
        self.fleet.age("stalled-07300401", 2700)

        subject = self.subjects()["stalled-07300401"]

        self.assertEqual(subject.state, IDLE,
                         f"a live worker with a quiet pane, untouched for 2700s against a 1800s "
                         f"threshold, is not IDLE: {subject.state} / {subject.note!r}")
        self.assertIn("1800", subject.note,
                      "the IDLE note does not name the threshold it crossed")
        self.assertTrue(needs_a_human(subject),
                        "a stalled worker is not in the population a human is asked to act on")

    def test_a_working_worker_is_never_idle_however_old_the_instant(self):
        """The other half, and the one that stops the fix being "call everything IDLE". A pane still
        offering a way to interrupt is progressing, whatever the filesystem says."""
        self.fleet.dispatch("busy-07300402", "00000000-07300402-inflight-append-busy",
                            "ws9", "dt-busy")
        self.fleet.launch("dt-busy", 5102, "ws9", BUSY_PANE)
        self.fleet.age("busy-07300402", 999999)

        subject = self.subjects()["busy-07300402"]

        self.assertEqual(subject.state, RUNNING,
                         f"a busy pane was reported {subject.state} because its files are old")
        self.assertFalse(needs_a_human(subject), "a working worker needs nobody")

    def test_the_threshold_is_the_boundary_not_a_suggestion(self):
        """`idle_after_s` is a parameter and the comparison is strict. A case that only ever tests
        2700-vs-1800 cannot tell a working threshold from a hard-coded one."""
        self.fleet.dispatch("edge-07300403", "00000000-07300403-inflight-append-edge",
                            "ws9", "dt-edge")
        self.fleet.launch("dt-edge", 5103, "ws9", QUIET_PANE)
        self.fleet.age("edge-07300403", 600)

        self.assertEqual(self.subjects(idle_after_s=300)["edge-07300403"].state, IDLE,
                         "600s idle against a 300s threshold is not IDLE")
        self.assertEqual(self.subjects(idle_after_s=1800)["edge-07300403"].state, RUNNING,
                         "600s idle against a 1800s threshold was reported IDLE")
```

Extend the import line at the top of the file to include the names these cases use:

```python
from fleet.reconcile import (COMPLETE, DEAD, IDLE, KINDS, RUNNING, STATES, UNREACHABLE,
                             Subject, needs_a_human, reconcile)
```

- [ ] **Step 4: Run the new tests**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_reconcile.TestTheIdleDetectorIsProduced -v
```
Expected: **3 tests, all PASS.** They pass immediately — the detector works. That is why step 5 exists.

- [ ] **Step 5: Prove the new tests CAN fail (the control — this is the real verification)**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure
bash bin/repro-g2-stall-loop.sh 2>&1 | tail -30
cat evidence/repro-g2/part3-mutations.tsv
```

**Required:** `M-1` and `M-3` now read `KILLED`, `M-2` still reads `KILLED`. If `M-1` still says `SURVIVED`, the new tests do not actually guard the detector — do not proceed; fix the test, not the mutation.

The `AS-PREDICTED`/`UNEXPECTED` column will now read `UNEXPECTED` for M-1 and M-3, because the script's `EXPECT` table encodes the pre-fix reality. Update it in the same commit — `EXPECT=( [1]="KILL" [2]="KILL" [3]="KILL" )` — and note in the script header that the expectations changed because the gap closed.

- [ ] **Step 6: Full suite, and check the count**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
```
Expected: `Ran 1186 tests`, `OK`. **1183 + 3.** A different total means something else changed; find out what before committing.

- [ ] **Step 7: Commit and push**

```bash
cd /home/ubuntu/davis_root/superpowers
git add fleet/tests/test_reconcile.py
git commit -m "fleet: the IDLE detector has a test at last (G-10)

FI-14 made IDLE actionable and shipped. Nothing ever drove reconcile TO it:
its flagship test hand-builds a subject already labelled IDLE and asserts the
banner counts it, so it passes whether or not a detector exists. Measured by
mutation - disabling the threshold branch, or making _idle_for always report
fresh, left all 1183 tests green, while reverting FI-14 itself dies. Harness
can kill; it never looked at the detector.

Three cases through the real join: produced-as-IDLE, a busy pane is never IDLE
however old its files, and the threshold is a boundary rather than a constant.
M-1 and M-3 now die."
git push
```

---

### Task 2: Collect `#{session_attached}` (the nudge's human-exemption)

A nudge must never land in a pane a human is typing in. The discriminator is `#{session_attached}` and `fleet` collects exactly one tmux format string today.

**Files:**
- Modify: `fleet/src/fleet/session.py` — `Probes` dataclass, add `SessionLayer.attached`, extend `default_probes`
- Test: `fleet/tests/test_session.py`

**Interfaces:**
- Produces: `Probes.attached_sessions: Callable[[], set]` (a set of attached session names) and `SessionLayer.attached(name: str) -> bool`. Task 8 consumes `sessions.attached(rec.tmux)`.

**Why a set-returning probe rather than a per-name query:** one tmux call answers for every session, and `list_processes` already has that shape. A per-name probe would mean N subprocesses per nudge pass.

- [ ] **Step 1: Write the failing test**

Add to `fleet/tests/test_session.py`:

```python
class TestAttachment(unittest.TestCase):
    """`G-4`'s discriminator, collected for `G-2`'s benefit only.

    A nudge must never go to a pane a human is attached to. This does NOT change what any state MEANS —
    `BLOCKED` still cannot tell a stuck worker from an attached human, which is `G-4` and stays open. It
    only makes the fact available to a caller that must not act on an occupied pane.
    """

    def layer(self, attached=()):
        return SessionLayer(Probes(
            list_processes=lambda: [],
            capture_pane=lambda name: "",
            has_session=lambda name: True,
            start_session=lambda name, cwd, cmd: None,
            kill_session=lambda name: None,
            attached_sessions=lambda: set(attached)))

    def test_an_attached_session_is_reported_attached(self):
        self.assertTrue(self.layer(attached=["dt-worker"]).attached("dt-worker"))

    def test_a_detached_session_is_not(self):
        self.assertFalse(self.layer(attached=["dt-other"]).attached("dt-worker"))

    def test_no_name_is_not_attached_rather_than_an_error(self):
        """A subject with no recorded tmux name must not raise inside a read-only join."""
        self.assertFalse(self.layer(attached=["dt-worker"]).attached(""))

    def test_a_probe_that_cannot_answer_reports_ATTACHED(self):
        """FAILS SAFE, and this is the whole point of the case. If tmux cannot be asked, the honest
        answer is 'I do not know whether a human is here' — and the action gated on it is typing into
        somebody's pane. Unknown must therefore mean 'do not touch', never 'go ahead'. A guard whose
        failure mode is 'proceed' is not a guard (the reasoning that put pane-guard's 14 outside the
        can-go set)."""
        layer = SessionLayer(Probes(
            list_processes=lambda: [], capture_pane=lambda name: "",
            has_session=lambda name: True, start_session=lambda name, cwd, cmd: None,
            kill_session=lambda name: None,
            attached_sessions=lambda: None))
        self.assertTrue(layer.attached("dt-worker"))
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_session.TestAttachment -v
```
Expected: **4 errors**, `TypeError: Probes.__init__() got an unexpected keyword argument 'attached_sessions'`.

- [ ] **Step 3: Add the probe field**

In `fleet/src/fleet/session.py`, in the `Probes` dataclass, after `kill_session`:

```python
    #: `G-2`. Session names a human is attached to, or None when tmux could not be asked. Set-valued so
    #: one tmux call answers for the whole fleet: a per-name probe would mean one subprocess per subject
    #: on every nudge pass. Defaulted, because every existing construction of `Probes` predates it and a
    #: required field here would break every caller and every fixture at once.
    attached_sessions: Callable[[], Optional[set]] = lambda: set()
```

- [ ] **Step 4: Add the accessor**

In `SessionLayer`, next to `alive`:

```python
    def attached(self, name: str) -> bool:
        """Whether a HUMAN is attached to this session's client.

        FAILS SAFE: an unanswerable probe reports True. The consumer is `nudge`, which types into a pane,
        and "I could not tell whether somebody is sitting there" must mean "leave it alone". A guard whose
        failure mode is 'go ahead' is not a guard — the same reasoning that keeps `pane-guard`'s `14`
        outside the can-go set.

        This collects the fact `G-4` needs and deliberately does NOT use it to change any state's
        meaning. `BLOCKED` still cannot distinguish a stuck worker from an attached human; that is `G-4`
        and it stays open.
        """
        if not name:
            return False
        attached = self.probes.attached_sessions()
        if attached is None:
            return True
        return name in attached
```

- [ ] **Step 5: Implement it in `default_probes`**

In `default_probes`, alongside the other real probes. Find the existing `run(...)` helper used by `list_processes` and follow it exactly; the tmux argv must go through the same socket-aware builder every other call uses:

```python
    def attached_sessions():
        #: `#{session_attached}` is a COUNT of attached clients, not a bool: >0 means somebody is looking.
        #: A tmux that answers non-zero (no server, no sessions) returns None — "could not ask" — which
        #: `SessionLayer.attached` reads as attached, not as free.
        done = run(tmux + ["list-sessions", "-F", "#{session_name} #{session_attached}"])
        if done.returncode != 0:
            return None
        names = set()
        for line in (done.stdout or "").splitlines():
            parts = line.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].strip() not in ("", "0"):
                names.add(parts[0].strip())
        return names
```

and pass `attached_sessions=attached_sessions` into the `Probes(...)` construction.

**Read `default_probes` before writing this.** Match how `run` and `tmux` are actually built there — do not assume the names above; if the local helper is spelled differently, use the local spelling.

- [ ] **Step 6: Run the tests**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_session.TestAttachment -v
```
Expected: **4 PASS.**

- [ ] **Step 7: Full suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
```
Expected `Ran 1190 tests`, `OK`. If any existing test fails on `Probes` construction, the default value in step 3 is missing.

- [ ] **Step 8: Commit and push**

```bash
cd /home/ubuntu/davis_root/superpowers
git add fleet/src/fleet/session.py fleet/tests/test_session.py
git commit -m "fleet: collect #{session_attached}, failing safe (for G-2)

A nudge must never land in a pane a human is typing in, and fleet collected
exactly one tmux format string. Set-valued so one call answers for the fleet.

Unanswerable probe reports ATTACHED: the consumer types into a pane, so 'I
could not tell whether somebody is sitting there' has to mean leave it alone.
Same reasoning that keeps pane-guard's 14 outside the can-go set.

Collects G-4's discriminator without touching what any state MEANS. G-4 stays
open and deferred."
git push
```

---

### Task 3: Measure the attention population BEFORE the tuple changes (`D-9` gate)

`PARKED` joining `ACTIONABLE_STATES` is the **third** change to that tuple. The standing constraint: *never change `ACTIONABLE_STATES` semantics twice without measuring in between*, or a counter regression is unattributable.

**Files:**
- Create: `bin/measure-attention.sh` (in the instant, not the repo)
- Create: `evidence/2026-08-03-attention-before.txt`

**Interfaces:**
- Produces: `bin/measure-attention.sh <label>` writing `evidence/<date>-attention-<label>.txt`. Task 4 runs it again with `after`.

- [ ] **Step 1: Write the measurement script**

```bash
cat > bin/measure-attention.sh <<'SH'
#!/usr/bin/env bash
# The attention population, on the REAL store, as a dated artifact.
#
# WHY: `D-9` adds PARKED to ACTIONABLE_STATES — the THIRD change to that tuple (`FI-14` widened it
# 2026-08-02; `G-4` would change it again). The standing constraint is that the counter is measured
# BETWEEN changes, because two semantic changes and one measurement make any regression unattributable.
#
# Read-only. `reconcile` mutates nothing (asserted by its own purity test).
#
# Usage: bash bin/measure-attention.sh before|after
set -uo pipefail
LABEL="${1:?usage: measure-attention.sh before|after}"
REPO="${REPO:-/home/ubuntu/davis_root/superpowers}"
INSTANT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$INSTANT_DIR/evidence/2026-08-03-attention-$LABEL.txt"

{
  echo "# attention population — $LABEL"
  echo "# when: $(TZ=UTC date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "# repo: $(git -C "$REPO" rev-parse --short HEAD)"
  echo "# FLEET_HOME=${FLEET_HOME:-/home/ubuntu/.fleet}"
  echo
  echo "## ACTIONABLE_STATES"
  ( cd "$REPO/fleet" && PYTHONPATH=src python3 -c \
      "from fleet.reconcile import ACTIONABLE_STATES; print(ACTIONABLE_STATES)" )
  echo
  echo "## every subject: state, needs-you, parked"
  ( cd "$REPO/fleet" && PYTHONPATH=src python3 - <<'PY'
import os, pathlib
from fleet.store import Store
from fleet.pool import Pool
from fleet.session import SessionLayer, default_probes
from fleet.reconcile import reconcile, needs_a_human

home = pathlib.Path(os.environ.get("FLEET_HOME", "/home/ubuntu/.fleet"))
sessions = SessionLayer(default_probes())
store, pool = Store(home), Pool(home, alive=sessions.alive)
instants = pathlib.Path(os.environ.get("FLEET_INSTANTS", home / "instants"))
subjects = reconcile(store, pool, sessions, instants)
wants = 0
for s in subjects:
    nah = needs_a_human(s)
    wants += 1 if nah else 0
    print(f"{s.kind}\t{s.identity}\t{s.state}\tneeds_you={nah}\t"
          f"parked={bool((s.evidence or {}).get('parked'))}")
print()
print(f"TOTAL subjects={len(subjects)}  NEEDS-YOU={wants}")
PY
  ) 2>&1
} | tee "$OUT"
echo
echo "captured -> evidence/$(basename "$OUT")"
SH
chmod +x bin/measure-attention.sh
```

- [ ] **Step 2: Run it and read the output**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure
bash bin/measure-attention.sh before
```

Expected: `ACTIONABLE_STATES` prints `('BLOCKED', 'IDLE')` and a `NEEDS-YOU=<n>` total.

**If the real store has no subjects at all**, the measurement is vacuous and cannot serve as a baseline. Say so explicitly in the artifact and in `HANDOFF.md` rather than treating an empty population as a passing gate — *absence is never success*. In that case satisfy the gate with the hermetic equivalent instead: a test asserting the needs-you population for a fixture containing one of every state, run before and after Task 4.

- [ ] **Step 3: Record it**

Add a row to `evidence/INDEX.md`:

```markdown
| `D-9` gate: attention population BEFORE `PARKED` joined the tuple | `2026-08-03-attention-before.txt` | `bin/measure-attention.sh before` against the real store at `<githash>` | `bash bin/measure-attention.sh before` |
```

- [ ] **Step 4: Commit (instant only — no repo change in this task)**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure
git -C /home/ubuntu/davis_root/superpowers status --porcelain   # expect EMPTY: this task touches no product code
```

---

### Task 4: `PARKED` becomes actionable (`G-11`, `D-9`)

A child's blocking question is invisible to the attention count until it times out into `IDLE` — `FI-14`'s defect, one state over.

**Files:**
- Modify: `fleet/src/fleet/reconcile.py` — `ACTIONABLE_STATES` and its comment
- Test: `fleet/tests/test_reconcile.py`, `fleet/tests/test_render.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ACTIONABLE_STATES == (BLOCKED, IDLE, PARKED)`. Task 8's nudge filter must exclude parked subjects **despite** this.

- [ ] **Step 1: Write the failing test**

Add to `fleet/tests/test_reconcile.py`:

```python
class TestAParkedQuestionAsksForAHuman(unittest.TestCase):
    """`G-11`. `fleet park --question` is how a child says "I cannot proceed without a decision", and
    *an empty park is not a park* — so a park is always a real question. It was not in
    `ACTIONABLE_STATES`, so `needs_a_human` said False and the child never entered the "N needs you"
    population. It surfaced only by timing out into `IDLE` after 30 minutes, which relabels a question
    as a stall.

    That is `FI-14` one state over: computed correctly, rendered correctly, read by nothing. Worse than
    `FI-14`, arguably — `IDLE` means "nobody knows why it stopped", `PARKED` means "your child is
    blocked on YOU specifically".
    """

    def test_a_parked_child_needs_a_human_immediately(self):
        fleet = SyntheticFleet()
        fleet.dispatch("asked-07300404", "00000000-07300404-inflight-append-asked", "ws9", "dt-asked")
        fleet.launch("dt-asked", 5201, "ws9", QUIET_PANE)
        Declarations(fleet.paths["asked-07300404"]).park(PARK_BLOCKED_Q)

        subject = {s.identity: s for s in reconcile(
            fleet.store, fleet.pool, fleet.sessions, fleet.instants)}["asked-07300404"]

        self.assertEqual(subject.state, PARKED, f"expected PARKED, got {subject.state}")
        self.assertTrue(needs_a_human(subject),
                        "a child waiting on its coordinator's ANSWER is not in the needs-you population")
        self.assertIn(PARK_BLOCKED_Q, subject.note, "the note does not carry the question")

    def test_the_widening_is_exactly_one_state(self):
        """A blanket widening is the defect `W2-14`/`OBS-57` recorded — a banner nobody can answer
        trains people to ignore the banner. AWAITING-CI and the terminal states stay out."""
        self.assertEqual(set(ACTIONABLE_STATES), {"BLOCKED", "IDLE", "PARKED"},
                         f"ACTIONABLE_STATES is {ACTIONABLE_STATES}")
        for state in (AWAITING_CI, DEAD, COMPLETE, RUNNING, UNREACHABLE):
            self.assertNotIn(state, ACTIONABLE_STATES,
                             f"{state} became actionable; nobody can answer it with a keystroke")
```

Extend the `fleet.reconcile` import to add `ACTIONABLE_STATES`, `AWAITING_CI`, `PARKED`.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_reconcile.TestAParkedQuestionAsksForAHuman -v
```
Expected: **2 failures.** The first on `needs_a_human(subject) is False`; the second on the set comparison. Read both messages — if the first fails on `state` instead, the fixture is wrong, not the product.

- [ ] **Step 3: Make the change**

In `fleet/src/fleet/reconcile.py`, replace the `ACTIONABLE_STATES` line and extend the comment block above it:

```python
#: `PARKED` added for `G-11`. `fleet park --question` is a child saying "I cannot proceed without a
#: decision" — and *an empty park is not a park*, so it is always a real question. It was excluded, so
#: `needs_a_human` said False and a blocked child reached nobody; it surfaced only by timing out into
#: `IDLE` after 30 minutes, which relabels a question as a stall. Same defect as `IDLE`'s above, one
#: state over, and sharper: `IDLE` means "nobody knows why it stopped", `PARKED` means "your child is
#: blocked on YOU". The remedy is an ANSWER, never a keystroke — so `nudge` excludes it explicitly
#: (`D-8`), which is why this widening is safe to make while an actuator exists.
ACTIONABLE_STATES = (BLOCKED, IDLE, PARKED)
```

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_reconcile.TestAParkedQuestionAsksForAHuman -v
PYTHONPATH=src python3 -m unittest tests.test_render -v 2>&1 | tail -5
```
Expected: the new class PASSes. `test_render` may now fail on `test_the_banner_counts_only_what_a_human_can_act_on`, which asserts `set(ACTIONABLE_STATES) == {"BLOCKED", "IDLE"}`. **That assertion is a deliberate tripwire and it fired correctly** — update it to the new set and add a line to its docstring recording that `PARKED` joined for `G-11`. Do **not** delete the assertion; it is the control that noticed.

- [ ] **Step 5: Full suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
```
Expected: `Ran 1192 tests`, `OK`. Any other failure is a real consumer of the tuple you have not considered — investigate; do not adjust the assertion to match.

- [ ] **Step 6: Measure AFTER (the other half of the `D-9` gate)**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure
bash bin/measure-attention.sh after
diff evidence/2026-08-03-attention-before.txt evidence/2026-08-03-attention-after.txt
```

Record the delta in `HANDOFF.md`'s live snapshot: the before count, the after count, and **which subjects moved and why**. A count that changed with no parked subject in the population is a regression, not the intended effect — stop and investigate.

- [ ] **Step 7: Commit and push**

```bash
cd /home/ubuntu/davis_root/superpowers
git add fleet/src/fleet/reconcile.py fleet/tests/test_reconcile.py fleet/tests/test_render.py
git commit -m "fleet: a parked question asks for a human (G-11)

fleet park --question is a child saying 'I cannot proceed without a decision',
and an empty park is not a park - so it is always a real question. PARKED was
not in ACTIONABLE_STATES, so needs_a_human said False and the child reached
nobody. It surfaced only by timing out into IDLE after 30 minutes, which
relabels a question as a stall.

FI-14's defect one state over, and sharper: IDLE means nobody knows why it
stopped, PARKED means your child is blocked on YOU.

Third change to this tuple, so the attention population is measured before and
after on the real store (D-9). test_render's set assertion fired correctly and
is updated, not removed - it is the control that noticed."
git push
```

---

### Task 5: `awaiting-ci` requires a live watcher (`D-10`)

`AWAITING-CI` is decided before `busy` and before the idle threshold, so a declared CI wait can never decay into `IDLE` — and it frees the WIP cap. A session that declares it and stops waits forever, hidden by its own declaration.

**Files:**
- Modify: `fleet/src/fleet/store.py` — `Declarations`
- Modify: `fleet/src/fleet/pool.py` — expose `pid_alive`
- Modify: `fleet/src/fleet/reconcile.py` — `_worker_subject`, `_state_of`, `_live_state`, `reconcile`
- Modify: `fleet/src/fleet/cli.py` — `_do_declare` (~line 1017) and its verb spec (~line 3280)
- Modify: `skills/working-as-a-dispatched-instant/SKILL.md`, `skills/using-fleet/profiles/worker/charter.md`, `skills/using-fleet/profiles/compaction/charter.md`
- Test: `fleet/tests/test_store.py`, `fleet/tests/test_reconcile.py`, `fleet/tests/test_cli.py`

**Interfaces:**
- Produces: `Declarations.set_phase(phase, watcher=None)`, `Declarations.watcher() -> int | None`, `Pool.pid_alive(pid) -> bool`, and `reconcile(..., pid_alive=None)`.

**Read `git log -3 -- skills/using-fleet/profiles/` before editing the templates** — `FI-13` edited them recently.

- [ ] **Step 1: Write the failing tests**

`fleet/tests/test_store.py`:

```python
class TestAPhaseCarriesItsWatcher(unittest.TestCase):
    """`D-10`. A declared CI wait outranks both `busy` and the idle threshold, so it can never decay into
    IDLE — and it frees the WIP cap. Declared with nothing watching, it is an infinite silent wait whose
    own declaration is what hides it. So the declaration names what will wake the session."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.decl = Declarations(self.tmp)

    def test_a_phase_records_and_returns_its_watcher(self):
        self.decl.set_phase("awaiting-ci", watcher=4242)
        self.assertEqual(self.decl.phase(), "awaiting-ci")
        self.assertEqual(self.decl.watcher(), 4242)

    def test_a_phase_declared_without_a_watcher_has_none(self):
        """Grandfathering: every declaration already on disk has no watcher. It must read as absent
        rather than raise, because the consumer's job is to stop TRUSTING it, not to crash on it."""
        self.decl.set_phase("awaiting-ci")
        self.assertIsNone(self.decl.watcher())

    def test_clearing_the_phase_clears_the_watcher(self):
        """A watcher outliving its phase would let a later undeclared instant inherit it."""
        self.decl.set_phase("awaiting-ci", watcher=4242)
        self.decl.set_phase(None)
        self.assertIsNone(self.decl.watcher())
```

`fleet/tests/test_reconcile.py`:

```python
class TestAnUnwatchedCiWaitStopsHiding(unittest.TestCase):
    """`D-10`'s consumer half. An `awaiting-ci` phase whose watcher is dead is treated as ABSENT, so
    derivation falls through to busy/idle as though nothing were declared. A stale declaration stops
    lying rather than needing a cleanup pass, and it fails in the safe direction: a dead watcher makes a
    worker MORE visible, never less."""

    def build(self, watcher, alive_pids):
        fleet = SyntheticFleet()
        fleet.dispatch("ci-07300405", "00000000-07300405-inflight-append-ci", "ws9", "dt-ci")
        fleet.launch("dt-ci", 5301, "ws9", QUIET_PANE)
        Declarations(fleet.paths["ci-07300405"]).set_phase("awaiting-ci", watcher=watcher)
        fleet.age("ci-07300405", 2700)
        subjects = reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants,
                             pid_alive=lambda pid: pid in alive_pids)
        return {s.identity: s for s in subjects}["ci-07300405"]

    def test_a_live_watcher_means_the_wait_is_real(self):
        subject = self.build(watcher=9001, alive_pids={9001})
        self.assertEqual(subject.state, AWAITING_CI)
        self.assertFalse(needs_a_human(subject), "a genuinely waiting worker needs nobody")

    def test_a_dead_watcher_falls_through_to_the_idle_detector(self):
        subject = self.build(watcher=9001, alive_pids=set())
        self.assertEqual(subject.state, IDLE,
                         "an awaiting-ci declaration with a DEAD watcher still suppressed the detector")
        self.assertTrue(needs_a_human(subject))
        self.assertIn("watcher", subject.note.lower(),
                      "the note does not say the declaration was disregarded, so a reader cannot tell "
                      "why a declared instant is reported IDLE")

    def test_a_declaration_with_no_watcher_at_all_falls_through(self):
        """Grandfathered declarations on disk. Intended direction: they stop suppressing detection."""
        subject = self.build(watcher=None, alive_pids={9001})
        self.assertEqual(subject.state, IDLE)
```

`fleet/tests/test_cli.py` — add to the class covering `declare`:

```python
    def test_declaring_awaiting_ci_without_a_watcher_is_refused(self):
        """`D-10`, producer half. Refused where it is made, like `park --question ""` and `propose`'s
        mandatory evidence: a declaration nothing backs is not a declaration. The refusal must name the
        flag that satisfies it — a refusal that states a rule and no route is `G-7`'s defect."""
        fleet = self.loaded()
        inst = fleet.paths["solo"]
        code, out, err = fleet.run(["declare", "--instant", str(inst), "--phase", "awaiting-ci"])
        self.assertEqual(code, EXIT_BAD_INPUT, f"an unwatched awaiting-ci was accepted: {out}")
        self.assertIn("--watcher", err, f"the refusal does not name the route that works: {err}")

    def test_declaring_awaiting_ci_with_a_watcher_is_accepted(self):
        fleet = self.loaded()
        inst = fleet.paths["solo"]
        code, out, err = fleet.run(["declare", "--instant", str(inst), "--phase", "awaiting-ci",
                                    "--watcher", str(os.getpid())])
        self.assertEqual(code, EXIT_OK, err)
        self.assertIn("awaiting-ci", out)

    def test_a_watcher_that_is_not_alive_is_refused_at_declaration_time(self):
        """A pid nobody is running is not a watcher. Refusing here is cheaper than discovering it in
        reconcile, and it catches the copy-paste of a stale pid."""
        fleet = self.loaded()
        inst = fleet.paths["solo"]
        code, out, err = fleet.run(["declare", "--instant", str(inst), "--phase", "awaiting-ci",
                                    "--watcher", "999999"])
        self.assertEqual(code, EXIT_BAD_INPUT, f"a dead watcher was accepted: {out}")

    def test_a_phase_other_than_awaiting_ci_needs_no_watcher(self):
        """The requirement is specific to the phase that suppresses detection. Do not tax the others."""
        fleet = self.loaded()
        code, out, err = fleet.run(["declare", "--instant", str(fleet.paths["solo"]), "--phase", "dev"])
        self.assertEqual(code, EXIT_OK, err)
```

`fleet.paths` may not exist on the `test_cli.Fleet` fixture — check how neighbouring `declare` tests obtain an instant path and follow that. Add `import os` if needed.

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_store.TestAPhaseCarriesItsWatcher tests.test_reconcile.TestAnUnwatchedCiWaitStopsHiding -v 2>&1 | tail -20
```
Expected: `TypeError: set_phase() got an unexpected keyword argument 'watcher'` and `reconcile() got an unexpected keyword argument 'pid_alive'`.

- [ ] **Step 3: `Declarations` carries the watcher**

In `fleet/src/fleet/store.py`, replace `set_phase` and add `watcher`:

```python
    def set_phase(self, phase: str | None, watcher: int | None = None) -> str | None:
        data = self._load()
        if phase is None:
            data.pop("phase", None)
            #: `D-10`. The watcher belongs to the phase, not to the instant. Leaving it behind would let
            #: a later, undeclared instant inherit a liveness token for a wait nobody declared.
            data.pop("watcher", None)
        else:
            data["phase"] = phase
            if watcher is None:
                data.pop("watcher", None)
            else:
                data["watcher"] = int(watcher)
        self._save(data)
        return Declarations(self.dir.parent).phase()      # re-read THROUGH the consumer

    def watcher(self) -> int | None:
        """`D-10`. The pid that will wake this instant when its wait ends, or None.

        None for every declaration written before this field existed. Absent, not an error: the
        consumer's job is to stop TRUSTING an unwatched declaration, not to crash on one.
        """
        value = self._load().get("watcher")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            #: A malformed watcher is no watcher. Same direction as absent: it makes the instant more
            #: visible, never less.
            return None
```

- [ ] **Step 4: Expose pid liveness on `Pool`**

In `fleet/src/fleet/pool.py`, add next to the other public methods:

```python
    def pid_alive(self, pid: int) -> bool:
        """Whether a pid is running. Public because `reconcile` needs it for `D-10`'s watcher check, and
        one home for pid liveness is the point — `_live_pid` reads `/proc`, which is what
        `session.default_probes` already reads, so this adds no platform assumption. Injectable through
        the constructor's `pid_alive`, so a test never needs a real process."""
        try:
            return bool(self._pid_alive(int(pid)))
        except (TypeError, ValueError):
            return False
```

- [ ] **Step 5: Thread the check through `reconcile`**

In `fleet/src/fleet/reconcile.py`:

1. `reconcile(store, pool, sessions, instants_dir: Path, idle_after_s: int = 1800, pid_alive=None)`. At the top of the body:

```python
    #: `D-10`. Defaults to the pool's, so the ONE implementation of pid liveness is shared and a test can
    #: still inject one without a real process.
    if pid_alive is None:
        pid_alive = pool.pid_alive
```

2. Where `phase` is read in `_worker_subject` (near `parked = declared.parked() ...`), compute the effective phase:

```python
    phase = declared.phase() if declared is not None else None
    watcher = declared.watcher() if declared is not None else None
    #: `D-10`. An `awaiting-ci` phase outranks `busy` AND the idle threshold, so declaring it and then
    #: stopping is an infinite silent wait that the declaration itself hides — while also freeing the WIP
    #: cap, so the coordinator dispatches onward and stops thinking about it. It is the only phase that
    #: suppresses the detector that would otherwise catch it. So it is trusted only while something is
    #: alive to end the wait. Disregarded here rather than cleaned up: a stale declaration stops lying
    #: without anybody having to run a sweep.
    phase_disregarded = ""
    if phase == PHASE_AWAITING_CI and not (watcher is not None and pid_alive(watcher)):
        phase_disregarded = (f"declared {PHASE_AWAITING_CI} with "
                             + (f"watcher {watcher} which is not running" if watcher is not None
                                else "no watcher") +
                             ": disregarded, because nothing is alive to end this wait")
        phase = None
```

Pass `phase` on as before, and append `phase_disregarded` to the resulting note when it is set — so a reader can tell why a declared instant reports `IDLE`. Put it in `evidence` too:

```python
        "declared_phase": phase or "",
        "phase_disregarded": phase_disregarded,
```

**Thread `pid_alive` down through `_state_of` to wherever `phase` is consumed** — follow the existing parameter chain rather than reaching for a module global.

- [ ] **Step 6: The producer refusal**

In `_do_declare` (`fleet/src/fleet/cli.py:1017`), after the existing empty-phase refusal:

```python
    #: `D-10`. `awaiting-ci` is the one phase that outranks both `busy` and the idle threshold, so an
    #: unwatched one is an infinite silent wait hidden by its own declaration — and it frees the WIP cap
    #: at the same time. Refused where it is made, like `park --question ""` and `propose`'s mandatory
    #: evidence. The message names the route, because a refusal that states a rule and no route is `G-7`.
    if phase == PHASE_AWAITING_CI:
        watcher = parsed.get("watcher")
        if not watcher:
            raise BadInput(
                f"--phase {PHASE_AWAITING_CI} needs --watcher <pid>: the pid of whatever will wake this "
                f"instant when the wait ends. This phase outranks both the busy check and the idle "
                f"threshold, so declared with nothing watching it is a wait that never ends and never "
                f"shows up — and it frees the WIP cap too. Pass the pid of your `gh run watch` (or "
                f"whatever you are waiting on), or declare a different phase.")
        try:
            pid = int(watcher)
        except (TypeError, ValueError):
            raise BadInput(f"--watcher {watcher!r} is not a pid")
        if not ctx.pool.pid_alive(pid):
            raise BadInput(
                f"--watcher {pid} is not running, so it will never wake this instant. A stale pid is the "
                f"copy-paste this check exists to catch. Start the watcher, then declare.")
```

Pass the watcher into `set_phase(phase, watcher=pid)` on the write path (and include it in the `--dry-run` emission). Add the flag to the verb spec at ~line 3280:

```python
        Flag("--watcher", True, False,
             "pid that will wake this instant when the wait ends; REQUIRED with --phase awaiting-ci"),
```

- [ ] **Step 7: Run the tests, then the full suite**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_store.TestAPhaseCarriesItsWatcher tests.test_reconcile.TestAnUnwatchedCiWaitStopsHiding -v
PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -6
```

Expected: the new classes PASS. **Existing `declare awaiting-ci` tests and IT fixtures will now be refused** — that is this change working. For each one, add a live `--watcher` (`str(os.getpid())` is a valid live pid in a test) rather than relaxing the rule. If a case exists specifically to assert the old permissive behaviour, update its docstring to record that `D-10` changed the contract.

- [ ] **Step 8: Teach the humans and the templates**

`skills/working-as-a-dispatched-instant/SKILL.md`, at the `awaiting-ci` paragraph — replace the command with the watched form and add one sentence:

```bash
fleet declare --instant "$INSTANT" --phase awaiting-ci --watcher <pid>
```
> The `--watcher` pid is whatever will wake you when the wait ends — your `gh run watch`, your poll loop. It is required, because this phase outranks both the busy check and the idle threshold: declared with nothing watching, you become a wait that never ends and that no report shows, while also freeing the coordinator's WIP cap. An unwatched declaration is disregarded and you will be reported IDLE.

Make the equivalent edit to the "When you are waiting on CI" section of **both** `skills/using-fleet/profiles/worker/charter.md` and `skills/using-fleet/profiles/compaction/charter.md`. `OBS-63`: the last clause of this shape landed in one profile and not the other because "where else does this shape live?" was answered by grepping for the text just fixed. Check both by name.

- [ ] **Step 9: Full suite again (the skill/profile tests read these files)**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
```
Expected: `OK`. `test_contracts` and `test_profiles` read `skills/` — if they fail, the templates and the verb surface disagree.

- [ ] **Step 10: Commit and push**

```bash
cd /home/ubuntu/davis_root/superpowers
git add fleet/src/fleet/store.py fleet/src/fleet/pool.py fleet/src/fleet/reconcile.py fleet/src/fleet/cli.py fleet/tests/ skills/
git commit -m "fleet: an awaiting-ci declaration needs a live watcher (D-10)

awaiting-ci is decided before busy AND before the idle threshold, so a declared
CI wait can never decay into IDLE - and declaring it frees the WIP cap. Declared
with nothing watching, a session becomes an infinite silent wait that its own
declaration is what hides, while the coordinator dispatches onward and stops
thinking about it. The only phase that suppresses the detector that would
otherwise catch it.

Refused at the producer (naming the route, per G-7) and disregarded at the
consumer, so a stale declaration stops lying without a cleanup pass. Liveness is
/proc via pool.pid_alive - one home, no new platform assumption, injectable.

Grandfathered declarations have no watcher and are therefore disregarded: the
intended direction, since it makes an instant more visible, never less."
git push
```

---

### Task 6: `fleet pane-send` — the delivery verb (`G-1`)

No verb in the package can deliver text to a pane. The correct contract exists once, in a test script.

**Files:**
- Modify: `fleet/src/fleet/session.py` — add the two send primitives to `Probes` + `SessionLayer`
- Modify: `fleet/src/fleet/cli.py` — `_do_pane_send`, a `_deliver` helper, exit codes, verb spec
- Modify: `fleet/it/bin/live-pane.sh` — `cmd_submit` re-points at the verb
- Test: `fleet/tests/test_cli.py`, `fleet/tests/test_session.py`

**Interfaces:**
- Consumes: `PANE_SAFE`, `PANE_QUEUED_TEXT`, `PANE_MID_TURN`, `PANE_NOT_CLAUDE`, `PANE_UNKNOWN`, `PANE_INDETERMINATE` from `cli.py`; `_do_pane_guard`'s classification logic.
- Produces: `_deliver(ctx, pane, text, timeout_s, poll_s) -> tuple[int, str]` returning `(exit_code, detail)`. **Task 8 calls `_deliver` directly**, not the verb.

**The measured justification, so nobody "simplifies" the poll into a sleep:** at gap=0 the Enter is dropped **1 in 5**; across 12 clean trials `pane-guard` after the type predicted the outcome **12/12** (`../evidence/2026-08-03-ra1-send-race.txt`). A delay buys a probability; the poll buys a guarantee.

**⚠️ Code `10` means opposite things either side of the type.** Before: *someone else's text is in the box* → refuse. After: *my text landed* → go. Get this backwards and the verb is worse than no verb.

- [ ] **Step 1: Write the failing tests**

Add to `fleet/tests/test_cli.py`:

```python
class TestPaneSend(CliCase):
    """`G-1`. `pane-guard` is "the send-keys contract, as an exit code" and nothing in the package could
    perform a send: six citations of a six-send-paths count that traces to no enumeration, two real
    implementations (both test-harness), and one production path in a vendored node package that sleeps
    150ms and hopes.

    The contract is a CONDITION, measured: at gap=0 the Enter is dropped 1 in 5, and pane-guard after the
    type predicted the outcome in 12 of 12 trials. So: type, poll for 10, then Enter — and REFUSE rather
    than press blind, because an Enter into an empty box submits nothing and looks like it worked.
    """

    def test_a_quiet_pane_gets_the_text_and_a_submitted_enter(self):
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]        # follow the fixture's own accessor; see note below
        fleet.panes[pane] = IDLE_PANE

        code, out, err = fleet.run(["pane-send", "--pane", pane, "--text", "hello"])

        self.assertEqual(code, EXIT_OK, err)
        typed = [c for c in fleet.sent if c[0] == pane]
        self.assertTrue(typed, f"nothing was sent to {pane}: {fleet.sent}")
        self.assertIn("hello", out)

    def test_the_text_is_typed_BEFORE_the_enter_and_they_are_separate_calls(self):
        """`FI-15`. "put text in the box" and "press Enter" are different acts, and collapsing them is
        what makes the race invisible."""
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = IDLE_PANE

        fleet.run(["pane-send", "--pane", pane, "--text", "hello"])

        kinds = [kind for target, kind, _ in fleet.sent if target == pane]
        self.assertEqual(kinds, ["text", "enter"],
                         f"expected a literal type then a separate Enter, got {kinds}")

    def test_a_pane_that_already_holds_text_is_REFUSED_before_typing(self):
        """Pre-gate. `10` here means SOMEBODY ELSE's text — an operator half-way through a sentence.
        Typing would produce `<their unfinished sentence>hello` and the Enter would submit it."""
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = "\n".join(["❯ half a sentence I was still typing"])

        code, out, err = fleet.run(["pane-send", "--pane", pane, "--text", "hello"])

        self.assertEqual(code, PANE_QUEUED_TEXT, f"a send concatenated onto queued text: {out}")
        self.assertEqual([c for c in fleet.sent if c[0] == pane], [],
                         "the refusal still sent something")

    def test_a_mid_turn_pane_is_refused(self):
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = BUSY_PANE
        code, out, err = fleet.run(["pane-send", "--pane", pane, "--text", "hello"])
        self.assertEqual(code, PANE_MID_TURN)
        self.assertEqual([c for c in fleet.sent if c[0] == pane], [])

    def test_when_the_text_never_lands_the_enter_is_NOT_pressed(self):
        """The heart of it. An Enter into an empty box submits nothing and LOOKS like it worked, so a
        verb that presses blind is worse than no verb: it reports success for a message nobody received."""
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = IDLE_PANE
        fleet.type_is_swallowed.add(pane)      # the pane never comes to hold the text

        code, out, err = fleet.run(["pane-send", "--pane", pane, "--text", "hello",
                                    "--timeout-s", "1"])

        self.assertNotEqual(code, EXIT_OK, "a swallowed type reported success")
        kinds = [kind for target, kind, _ in fleet.sent if target == pane]
        self.assertNotIn("enter", kinds, "Enter was pressed into a box that never held the text")
        self.assertIn("never reached", (out + err).lower())

    def test_a_dt_session_on_the_DEFAULT_server_is_refused(self):
        """The standing rule is 'never write a dt- session on the DEFAULT server'. Not 'never write a
        dt- session' — every dispatched worker IS one, so a blanket refusal would make this verb useless
        for its only caller. live-pane.sh refuses all dt- names because a TEST PROBE should; copying that
        here would be the bug."""
        fleet = self.loaded()
        fleet.tmux_socket = None                      # the default server
        fleet.panes["dt-somebody"] = IDLE_PANE
        fleet.tmux_live.add("dt-somebody")

        code, out, err = fleet.run(["pane-send", "--pane", "dt-somebody", "--text", "hello"])

        self.assertEqual(code, EXIT_REFUSED, f"a dt- send on the default server was allowed: {out}")
        self.assertEqual([c for c in fleet.sent if c[0] == "dt-somebody"], [])

    def test_a_dt_session_on_a_NAMED_socket_is_a_legal_target(self):
        """The other direction, and the one a blanket refusal breaks. Dispatched workers live on the
        `fleet` socket and are exactly who `nudge` must reach."""
        fleet = self.loaded()
        fleet.tmux_socket = "fleet"
        fleet.panes["dt-worker"] = IDLE_PANE
        fleet.tmux_live.add("dt-worker")

        code, out, err = fleet.run(["pane-send", "--pane", "dt-worker", "--text", "hello"])

        self.assertEqual(code, EXIT_OK, err)

    def test_dry_run_sends_nothing(self):
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = IDLE_PANE
        code, out, err = fleet.run(["pane-send", "--pane", pane, "--text", "hi", "--dry-run"])
        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual([c for c in fleet.sent if c[0] == pane], [])
        self.assertIn("would-send", out)
```

**The `test_cli.Fleet` fixture needs three additions to support these** — make them in this step, in `fleet/tests/test_cli.py`:
- `self.sent = []` in `__init__`, and `self.type_is_swallowed = set()`, and `self.tmux_socket = "fleet"`.
- Wire the two new probes (Step 3) to append `(name, "text", text)` / `(name, "enter", "")` to `self.sent`, and — unless the pane is in `type_is_swallowed` — make a typed pane subsequently read as holding that text, so the poll can succeed. The simplest faithful way: on `send_text`, set `self.panes[name] = f"❯ {text}"`.
- `ids_tmux`: if the fixture has no accessor mapping a friendly name to its tmux name, add one (`self.ids_tmux[name] = tmux` in `worker()`). Read the fixture first and follow its existing conventions.

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_cli.TestPaneSend -v 2>&1 | tail -20
```
Expected: every case fails — `pane-send` is not a verb. Confirm the count is **9**.

- [ ] **Step 3: Add the send primitives to the session layer**

`fleet/src/fleet/session.py`, in `Probes`:

```python
    #: `G-1`. The two halves of a submit, kept SEPARATE: `FI-15` is about their interaction, and a
    #: single "send this and submit it" probe makes the race it describes untestable. Defaulted so every
    #: existing construction keeps working.
    send_text: Callable[[str, str], None] = lambda name, text: None
    send_enter: Callable[[str], None] = lambda name: None
```

and in `SessionLayer`:

```python
    def type_text(self, name: str, text: str) -> None:
        """Put text in the pane's input box WITHOUT submitting. Literal (`-l`), so tmux key names inside
        the text ("Enter", "C-c") are typed rather than interpreted."""
        if not name:
            raise BadInput("a send needs a pane name")
        self.probes.send_text(name, text)

    def press_enter(self, name: str) -> None:
        """Submit whatever is in the box. Separate from `type_text` on purpose — see `Probes`."""
        if not name:
            raise BadInput("a send needs a pane name")
        self.probes.send_enter(name)
```

In `default_probes`, implement both with the socket-aware tmux argv, exactly as the other probes do:

```python
    def send_text(name, text):
        run(tmux + ["send-keys", "-t", exact_session_target(name), "-l", text])

    def send_enter(name):
        run(tmux + ["send-keys", "-t", exact_session_target(name), "Enter"])
```

`exact_session_target` (the `=` prefix) is **mandatory**: a bare target resolves by PREFIX, and `send-keys -t itfleet-N-pre-a` reaches `itfleet-N-pre-ab`.

- [ ] **Step 4: Add the exit codes**

In `fleet/src/fleet/cli.py`, beside the pane-guard code block (~line 158):

```python
#: `G-1`. The text was typed and the box never came to hold it, so the Enter was NOT pressed. Its own
#: code because the caller's response differs from every refusal above: those mean "not now, poll again",
#: this means "the channel accepted a keystroke and lost it" — which is `FI-15` happening live, and the
#: one outcome a caller must never read as success. Deliberately outside PANE_GUARD_CODES: it is an
#: answer about a SEND, not a classification of a pane.
PANE_TEXT_LOST = 15
```

Register it in the codes block that `usage()` renders, next to the pane-guard codes.

- [ ] **Step 5: Implement `_deliver` and the verb**

In `fleet/src/fleet/cli.py`. Factor the classification out of `_do_pane_guard` into a helper both verbs call — `_classify_pane(ctx, pane) -> tuple[int, str]` — rather than duplicating it. **A second derivation of the same judgement is the failure this codebase keeps re-learning.**

```python
def _deliver(ctx: Ctx, pane: str, text: str, timeout_s: float = 10.0,
             poll_s: float = 0.2) -> tuple:
    """Deliver `text` to `pane` and CONFIRM it was submitted. Returns `(code, detail)`.

    THE CONTRACT, and why it is a condition rather than a delay. Measured on a real claude pane
    (2.1.220, 12 clean trials, `RA-1`): with the Enter sent immediately after the text it is DROPPED
    1 time in 5 — and `pane-guard` polled after the type predicted the outcome in 12 of 12 trials. Every
    trial that read `10` submitted; the one that read `0` dropped. So the failure mode is exactly "the
    text has not landed yet", and `10` is exactly the question that answers. A fixed delay buys a
    probability (which is what the one production send path on this box does, at 150ms); this buys a
    guarantee.

    ⚠️ `10` MEANS OPPOSITE THINGS EITHER SIDE OF THE TYPE, and inverting them is the likeliest way this
    goes wrong:
      · BEFORE typing, `10` = "somebody ELSE's text is in the box" -> refuse, or we concatenate onto an
        operator's half-written sentence and then submit it.
      · AFTER typing, `10` = "MY text is in the box" -> go.
    The vendored `claude-auto-retry` patch uses only the first sense; `live-pane.sh submit` only the
    second. This is the first implementation that needs both.
    """
    code, detail = _classify_pane(ctx, pane)
    if code != PANE_SAFE:
        return code, f"refusing to send: {detail}"

    ctx.sessions.type_text(pane, text)

    deadline = ctx.now_monotonic() + timeout_s
    landed = False
    while True:
        if _classify_pane(ctx, pane)[0] == PANE_QUEUED_TEXT:
            landed = True
            break
        if ctx.now_monotonic() >= deadline:
            break
        time.sleep(poll_s)

    if not landed:
        #: NOT pressing Enter is the whole point. An Enter into an empty box submits nothing and looks
        #: exactly like success, which is how a channel silently drops instructions.
        return PANE_TEXT_LOST, (
            f"the text never reached {pane}'s input box within {timeout_s}s, so Enter was NOT pressed: "
            f"an Enter into an empty box submits nothing and looks like it worked")

    ctx.sessions.press_enter(pane)
    after = _classify_pane(ctx, pane)[0]
    if after == PANE_QUEUED_TEXT:
        return PANE_TEXT_LOST, (f"the text is still in {pane}'s box after Enter, so the submit was "
                                f"dropped — this is FI-15's race, observed live")
    return EXIT_OK, f"delivered to {pane} and confirmed submitted (pane-guard {after} after Enter)"


def _do_pane_send(ctx: Ctx, parsed: Parsed) -> int:
    """`G-1`. The verb that owns pane delivery, so a correction reaches every caller instead of one.

    A VERB rather than a library call, decided on evidence: the only production consumer is a node
    package, which can reach python only through a subprocess — and already does exactly that for
    `pane-guard`.
    """
    pane = parsed.get("pane")
    text = parsed.get("text")
    if not str(text or ""):
        raise BadInput("--text is empty; a send with nothing to send is not a send")

    #: The standing rule is 'never write a `dt-` session on the DEFAULT server' — NOT 'never write a
    #: dt- session'. Every dispatched worker IS one, on the `fleet` socket, and they are precisely who
    #: `nudge` exists to reach. `live-pane.sh` refuses all `dt-` names because a test probe should;
    #: copying that here would make this verb useless for its only caller.
    if pane.startswith("dt-") and not ctx.sessions.tmux_socket:
        _emit(ctx, "pane-send", [("refused", "dt- on the default server"), ("pane", pane)])
        return EXIT_REFUSED

    if ctx.dry_run:
        _emit(ctx, "pane-send", [("dry-run", "nothing was sent"), ("would-send", text),
                                 ("pane", pane)])
        return EXIT_OK

    code, detail = _deliver(ctx, pane, text,
                            timeout_s=float(parsed.get("timeout-s") or 10.0))
    _emit(ctx, "pane-send", [("pane", pane), ("code", str(code)), ("text", text),
                             ("detail", detail)])
    return code
```

`ctx.now_monotonic` does not exist — add it to `Ctx` as `now_monotonic: Callable = time.monotonic` so a test can freeze it, following how `now` is already injected. Import `time` in `cli.py` if it is not already imported. `ctx.sessions.tmux_socket` must be readable — if `SessionLayer` does not expose the socket, add a read-only property returning the probes' socket.

Register the verb (with the other read-only-adjacent pane verbs):

```python
    _verb("pane-send", _do_pane_send, False,
          "deliver text to a pane and CONFIRM it submitted: type, poll pane-guard for 10, then Enter", (
        Flag("--pane", True, True, "the pane (session) name"),
        Flag("--text", True, True, "the text to deliver"),
        Flag("--timeout-s", True, False, "how long to wait for the box to hold the text (default 10)"),
    )),
```

- [ ] **Step 6: Run the tests**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_cli.TestPaneSend -v
```
Expected: **9 PASS.** If `test_a_dt_session_on_a_NAMED_socket_is_a_legal_target` fails, the refusal is too broad — that case exists precisely to catch the blanket version.

- [ ] **Step 7: Check the spawn-seam audit — do not assume**

```bash
cd /home/ubuntu/davis_root/superpowers
PYTHONPATH=fleet/src python3 -c "from tests.test_cli import SPAWN_SEAMS; print(SPAWN_SEAMS)" 2>/dev/null \
  || grep -rn "SPAWN_SEAMS" fleet/tests/test_cli.py | head -3
bash fleet/it/run-group5.sh 2>&1 | grep -iE "M9|seam" | head -20
```

A *send* may or may not count as a new outward site. **Find out what the audit actually enumerates.** If it flags the new call, argue it in **both** registries (`II-3`) — the audit and `test_cli`'s declaration — never by adding an allowlist entry.

- [ ] **Step 8: Re-point `live-pane.sh submit` at the verb**

`G-1`'s closure criterion: two implementations of one primitive collapse into one. In `fleet/it/bin/live-pane.sh`, replace `cmd_submit`'s body with a call to the verb, keeping the refusal behaviour:

```bash
# submit <session> <text> — now a thin wrapper over `fleet pane-send`, which OWNS this contract (`G-1`).
# The polling logic that used to live here is the verb's, so a correction reaches every caller instead of
# this script alone. Kept as a verb of this tool because every §-runner and probe already calls it.
cmd_submit() {
  local session="$1" text="$2"
  check_name "$session"
  FLEET_TMUX_SOCKET="$PROBE_SOCKET" PYTHONPATH="$REPO/fleet/src" \
    python3 -m fleet.cli pane-send --pane "$session" --text "$text"
}
```

- [ ] **Step 9: Verify the harness still works, for free**

```bash
cd /home/ubuntu/davis_root/superpowers
bash fleet/it/bin/live-pane.sh selftest
```
Expected: `ALL SELFTEST CHECKS HOLD`. Then confirm the real path end-to-end on a real pane (authorised, `D-6`):

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure
FLEET_ALLOW_LIVE_CLAUDE=1 bash bin/probe-ra1-send-race.sh 2>&1 | tail -25
```
Expected: the `submit (condition)` control row still reports `submitted=YES`. It now exercises the VERB, so this is the verb's live integration proof. Capture it — the artifact is overwritten, so copy it to `evidence/2026-08-03-ra1-send-race-VIA-VERB.txt` and add an `INDEX.md` row.

- [ ] **Step 10: Full suite, commit, push**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
cd /home/ubuntu/davis_root/superpowers
git add fleet/src/fleet/session.py fleet/src/fleet/cli.py fleet/tests/ fleet/it/bin/live-pane.sh
git commit -m "fleet: pane-send owns pane delivery, and CONFIRMS it (G-1)

pane-guard was 'the send-keys contract, as an exit code' and nothing in the
package could perform a send. The correct contract existed once, in a test
script; the one production path sleeps 150ms and hopes.

The contract is a CONDITION, measured on a real pane (RA-1, 12 clean trials):
at gap=0 the Enter is dropped 1 in 5, and pane-guard after the type predicted
the outcome 12/12. So type, poll for 10, then Enter - and REFUSE rather than
press blind, because an Enter into an empty box submits nothing and looks like
it worked.

10 means opposite things either side of the type: before, somebody else's text
(refuse); after, mine (go). First implementation needing both senses.

A verb rather than a library call, on evidence: the only production consumer is
node and already shells out for pane-guard. Refuses dt- on the DEFAULT server
only - every dispatched worker is a dt- session and is a legal target on a named
socket. live-pane.sh submit is now a wrapper, so there is one implementation."
git push
```

---

### Task 7: Surface the declared profile kind (`D-11`)

Coordinators and workers get different nudges, and the kind must be READ, never inferred.

**Files:**
- Modify: `fleet/src/fleet/reconcile.py` — `_worker_subject` evidence
- Test: `fleet/tests/test_reconcile.py`

**Interfaces:**
- Produces: `subject.evidence["profile_kind"]` — `"worker"`, `"coordinator"`, `"compaction"`, or `""` when the manifest could not be read. Task 8 selects its text on this.

**Do NOT put this in `Subject.kind`.** `reconcile.KINDS` is `("worker", "unknown-session", "stale-lease")` — the JOIN's row kind — while `profiles.KINDS` is `("worker", "coordinator", "compaction")`. Two closed vocabularies that share a name; conflating them is the trap.

- [ ] **Step 1: Write the failing test**

```python
class TestTheProfileKindIsRead(unittest.TestCase):
    """`D-11`. `nudge` sends different text to a coordinator than to a worker, so it needs the kind — and
    the kind is a DECLARED field. `profiles.Profile.load` raises rather than defaulting, because a kind
    inferred from prose once made five shipped profiles silently fall back to `worker` (`OBS-5`): "a
    kind-aware linter that picks the wrong kind is worse than no linter, because it converts 'unchecked'
    into 'checked and fine'."

    So: read the manifest, or report that you could not. Never guess from the folder name or the title.
    """

    def fleet_with_profile(self, manifest):
        fleet = SyntheticFleet()
        profile_dir = fleet.tmp / "profiles" / "somekind"
        profile_dir.mkdir(parents=True)
        if manifest is not None:
            (profile_dir / "profile.json").write_text(manifest)
        fleet.dispatch("kinded-07300406", "00000000-07300406-inflight-append-kinded",
                       "ws9", "dt-kinded", profile=str(profile_dir))
        fleet.launch("dt-kinded", 5401, "ws9", QUIET_PANE)
        subjects = reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants)
        return {s.identity: s for s in subjects}["kinded-07300406"]

    def test_a_coordinator_is_reported_as_a_coordinator(self):
        subject = self.fleet_with_profile('{"kind": "coordinator"}')
        self.assertEqual(subject.evidence["profile_kind"], "coordinator")

    def test_a_worker_is_reported_as_a_worker(self):
        subject = self.fleet_with_profile('{"kind": "worker"}')
        self.assertEqual(subject.evidence["profile_kind"], "worker")

    def test_an_unreadable_manifest_reports_EMPTY_and_never_worker(self):
        """The `OBS-5` direction. Absent must not read as `worker`, or "unchecked" becomes "checked and
        fine" and a coordinator silently gets a worker's nudge."""
        subject = self.fleet_with_profile(None)
        self.assertEqual(subject.evidence["profile_kind"], "",
                         "a missing manifest was reported as a kind")

    def test_a_malformed_manifest_does_not_break_the_join(self):
        """`reconcile` is behind every view and `Profile.load` raises by design. One bad profile must
        degrade ONE row, never take down `board`."""
        subject = self.fleet_with_profile("{ this is not json")
        self.assertEqual(subject.evidence["profile_kind"], "")
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_reconcile.TestTheProfileKindIsRead -v
```
Expected: **4 failures**, `KeyError: 'profile_kind'`.

- [ ] **Step 3: Read the kind**

In `fleet/src/fleet/reconcile.py`, add near the other helpers:

```python
def _profile_kind(rec) -> str:
    """The DECLARED kind of this record's profile, or `""` if it could not be read.

    `D-11`. `profiles.Profile.load` raises rather than defaulting, deliberately — a kind inferred from
    prose once made five shipped profiles silently fall back to `worker` (`OBS-5`/`OBS-64`). So this
    reads the manifest and reports failure as EMPTY rather than as `worker`: "unchecked" must not become
    "checked and fine", or a coordinator silently receives a worker's nudge.

    Swallowing the error is right HERE and only here: `reconcile` is behind every view, so one unreadable
    profile must degrade one row rather than take down `board`. The consumer decides what to do with an
    unknown kind, and `nudge` REPORTS it rather than papering over it.
    """
    from fleet.profiles import Profile          # local: keeps reconcile importable without profiles
    try:
        return Profile.load(Path(rec.profile)).kind
    except Exception:
        return ""
```

and in the `evidence` dict in `_worker_subject`:

```python
        "profile_kind": _profile_kind(rec),
```

- [ ] **Step 4: Run the tests and the suite**

```bash
PYTHONPATH=src python3 -m unittest tests.test_reconcile.TestTheProfileKindIsRead -v
PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
```
Expected: 4 PASS; suite `OK`. A test asserting the exact set of `evidence` keys may need the new key added.

- [ ] **Step 5: Commit and push**

```bash
cd /home/ubuntu/davis_root/superpowers
git add fleet/src/fleet/reconcile.py fleet/tests/test_reconcile.py
git commit -m "fleet: surface the DECLARED profile kind on a subject (D-11)

nudge sends different text to a coordinator than to a worker. The kind is a
declared field and Profile.load raises rather than defaulting, because a kind
inferred from prose once made five shipped profiles fall back to worker (OBS-5).

Unreadable reports EMPTY, never 'worker': unchecked must not become checked and
fine. Errors are swallowed here and only here - reconcile is behind every view,
so one bad profile degrades one row rather than taking down board.

In evidence, not Subject.kind: reconcile.KINDS is the join's row kind and
profiles.KINDS is the profile's. Two closed vocabularies sharing a name."
git push
```

---

### Task 8: `fleet nudge` — the actuator (`G-2`)

**Files:**
- Create: `fleet/src/fleet/nudge.py` — the eligibility predicate and the episode ledger
- Modify: `fleet/src/fleet/cli.py` — `_do_nudge`, verb spec
- Test: `fleet/tests/test_nudge.py` (new), `fleet/tests/test_cli.py`

**Interfaces:**
- Consumes: `reconcile(...)`, `needs_a_human`, `IDLE`, `subject.evidence["parked"|"profile_kind"]`, `sessions.attached(name)`, `_deliver` from Task 6.
- Produces: `nudge.eligible(subject, sessions, ledger) -> tuple[bool, str]`; `nudge.Ledger(home)` with `.nudged_this_episode(subject) -> bool` and `.record(subject, delivered: bool)`; `nudge.text_for(profile_kind, instant, idle_after_s) -> str`.

A separate module because `cli.py` is already very large and this is a self-contained policy with its own state file.

- [ ] **Step 1: Write the failing tests for eligibility**

Create `fleet/tests/test_nudge.py`:

```python
"""`G-2`. Something finally ACTS on a detected stall.

`fleet` computed a correct, actionable judgement about a stalled worker and every consumer was a VIEW:
`render`'s "N needs you" banner and a `reconcile` row. The loop ended at a human's eyes, so the operator
was the mitigation — *"the entire system stuck forever until I send messages waking folks up"*.

The eligibility rules are the design, and each one is here because sending would have been WRONG:
a parked child needs an answer, an attached pane belongs to a human, a second nudge in one episode is
noise, and a coordinator needs different words than a worker.
"""
import pathlib
import tempfile
import unittest

from fleet import nudge
from fleet.reconcile import IDLE, PARKED, BLOCKED, RUNNING, AWAITING_CI, KIND_WORKER, Subject


def subject(state=IDLE, *, kind=KIND_WORKER, parked="", profile_kind="worker",
            identity="w-07300401", tmux="dt-w", activity="100.0"):
    return Subject(kind=kind, identity=identity, state=state, holds_slot=True,
                   evidence={"parked": parked, "profile_kind": profile_kind, "tmux": tmux,
                             "activity_mtime": activity},
                   note="")


class FakeSessions:
    def __init__(self, attached=()):
        self._attached = set(attached)

    def attached(self, name):
        return name in self._attached


class TestEligibility(unittest.TestCase):
    def setUp(self):
        self.ledger = nudge.Ledger(pathlib.Path(tempfile.mkdtemp()))
        self.sessions = FakeSessions()

    def eligible(self, subj, sessions=None):
        return nudge.eligible(subj, sessions or self.sessions, self.ledger)

    def test_an_idle_worker_is_eligible(self):
        ok, why = self.eligible(subject())
        self.assertTrue(ok, why)

    def test_a_parked_child_is_NOT_eligible_even_though_its_state_is_IDLE(self):
        """`D-8`, and the case the whole design turned on. `_live_state` APPENDS the park to the note and
        leaves the state IDLE, so a state-only filter hits a child that correctly asked a question. The
        remedy is an ANSWER; a nudge would tell it to carry on WITHOUT the answer, which is the guessing
        failure `G-3` is about. Measured before it was written."""
        ok, why = self.eligible(subject(state=IDLE, parked="which baseline is the ruler?"))
        self.assertFalse(ok, "a parked child was nudged")
        self.assertIn("park", why.lower())

    def test_a_blocked_pane_is_not_eligible(self):
        """The box already holds text: typing concatenates, a bare Enter submits somebody's sentence."""
        self.assertFalse(self.eligible(subject(state=BLOCKED))[0])

    def test_a_running_or_waiting_subject_is_not_eligible(self):
        for state in (RUNNING, AWAITING_CI, PARKED):
            self.assertFalse(self.eligible(subject(state=state))[0], f"{state} was nudged")

    def test_a_non_worker_row_is_never_touched(self):
        """*"some of those sessions are people's"* — an unknown session is reported and never acted on."""
        self.assertFalse(self.eligible(subject(kind="unknown-session"))[0])

    def test_a_pane_with_a_human_attached_is_not_nudged(self):
        ok, why = self.eligible(subject(), sessions=FakeSessions(attached=["dt-w"]))
        self.assertFalse(ok, "a nudge was sent to a pane a human is attached to")
        self.assertIn("attached", why.lower())

    def test_one_nudge_per_episode(self):
        subj = subject()
        self.assertTrue(self.eligible(subj)[0])
        self.ledger.record(subj, delivered=True)
        ok, why = self.eligible(subj)
        self.assertFalse(ok, "a second nudge was sent in the same stall episode")
        self.assertIn("episode", why.lower())

    def test_activity_since_the_last_nudge_starts_a_NEW_episode(self):
        """"One per episode" needs an episode boundary, and it reuses the activity notion the detector
        already uses rather than inventing a timer — so there is no second definition of "made progress"."""
        subj = subject(activity="100.0")
        self.ledger.record(subj, delivered=True)
        moved = subject(activity="200.0")
        self.assertTrue(self.eligible(moved)[0],
                        "a worker that made progress and stalled again was not eligible")
```

- [ ] **Step 2: Write the failing tests for the two texts**

Append to `fleet/tests/test_nudge.py`:

```python
class TestTheText(unittest.TestCase):
    """`D-11`. What is actually sent. A coordinator's next action is its WORKERS; a worker's is its own
    charter. And both are asked to reconcile their workspace first, because a stall is exactly when it is
    stale — the skill's own rule is 'end every session by updating HANDOFF.md', so an instant that runs it
    writes down where it got to and recovers its next action from the document instead of from a memory it
    no longer has."""

    def test_every_text_asks_for_the_workspace_to_be_brought_up_to_date(self):
        for kind in ("worker", "coordinator", "compaction", ""):
            text = nudge.text_for(kind, "/i/inst", 1800)
            self.assertIn("maintain-workspace", text, f"{kind!r} is not asked to update its workspace")

    def test_a_worker_is_told_how_to_park_rather_than_guess(self):
        text = nudge.text_for("worker", "/i/inst", 1800)
        self.assertIn("fleet park", text)
        self.assertIn("/i/inst", text, "the park command does not name the instant, so it cannot be run")

    def test_a_coordinator_is_sent_to_the_population_it_must_unblock(self):
        text = nudge.text_for("coordinator", "/i/inst", 1800)
        self.assertIn("fleet board", text)
        self.assertIn("unpark", text, "a coordinator is not told how to release a parked child")

    def test_an_unknown_kind_gets_the_worker_text(self):
        """`OBS-5`'s safe direction: the worker text tells a coordinator to park a question it has nobody
        to send to (harmless); the coordinator text would send a worker to unblock workers it does not
        have (confusing). The DEFAULTING is reported by the verb, so it never becomes silent."""
        self.assertEqual(nudge.text_for("", "/i/inst", 1800),
                         nudge.text_for("worker", "/i/inst", 1800))

    def test_the_text_is_a_single_line(self):
        """It is typed into an input box with `send-keys -l`. An embedded newline would submit early and
        deliver half a sentence."""
        for kind in ("worker", "coordinator"):
            self.assertNotIn("\n", nudge.text_for(kind, "/i/inst", 1800))
```

- [ ] **Step 3: Run both classes and watch them fail**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_nudge -v 2>&1 | tail -10
```
Expected: `ModuleNotFoundError: No module named 'fleet.nudge'`.

- [ ] **Step 4: Add `activity_mtime` to the subject's evidence**

The episode boundary needs the instant's newest mtime on the subject. In `fleet/src/fleet/reconcile.py`, `_worker_subject`'s evidence dict:

```python
        #: `G-2`'s episode boundary. The same activity notion `_idle_for` uses, exposed so `nudge` does
        #: not need a SECOND definition of "the worker made progress".
        "activity_mtime": f"{_newest_mtime(instant):.0f}" if instant is not None else "",
```

Factor `_newest_mtime(instant) -> float` out of `_idle_for` (which becomes `now - _newest_mtime(instant)`), so there is one implementation. Add a test that `_idle_for` still behaves — Task 1's threshold case already covers it, so re-run it.

- [ ] **Step 4b: Name the idle threshold, and annotate the note of a subject already nudged (spec §5)**

Two small pieces the rest of the task depends on.

**(a) A named constant.** `reconcile` has `idle_after_s: int = 1800` as a bare default, and `nudge` needs the
same number for its message. In `fleet/src/fleet/reconcile.py`:

```python
#: The idle threshold, named so `nudge` can state it in a message without re-typing the number and without
#: reaching for `harvest`'s `DEFAULT_MAX_AGE_S` — a different window that happens to hold the same value
#: today, which is how two knobs quietly become one.
IDLE_AFTER_S = 1800
```

Make the signature `reconcile(..., idle_after_s: int = IDLE_AFTER_S)` and import `IDLE_AFTER_S` into `cli.py`.

**(b) The escalation surface.** Spec §5: a nudged-and-still-idle subject keeps state `IDLE` (so it stays in
"N needs you") and gets its NOTE annotated — so the board can say *fleet already tried the thing that usually
works, this one is genuinely yours*. Without it a human sees a bare `IDLE` and cannot tell an un-nudged stall
from one that ignored a nudge, which is the difference that decides whether they need to intervene.

Write the failing test first, in `fleet/tests/test_reconcile.py`:

```python
class TestANudgedSubjectSaysSoOnTheBoard(unittest.TestCase):
    """Spec section 5. The escalation is not a new state - it is the note.

    A subject that was nudged and is STILL idle stays IDLE and actionable, and its note records the
    attempt, because a bare IDLE cannot distinguish "nobody has tried" from "fleet tried and it did not
    help". The second is the one that needs a person, and it is the one the operator was doing by hand.
    """

    def test_the_note_records_a_nudge_already_attempted_in_this_episode(self):
        fleet = SyntheticFleet()
        fleet.dispatch("nudged-07300407", "00000000-07300407-inflight-append-nudged", "ws9", "dt-nudged")
        fleet.launch("dt-nudged", 5501, "ws9", QUIET_PANE)
        fleet.age("nudged-07300407", 2700)

        def one():
            return {s.identity: s for s in reconcile(
                fleet.store, fleet.pool, fleet.sessions, fleet.instants)}["nudged-07300407"]

        first = one()
        self.assertNotIn("nudge", first.note.lower(), "an un-nudged subject already claims a nudge")

        from fleet.nudge import Ledger
        Ledger(fleet.home).record(first, delivered=True)

        again = one()
        self.assertEqual(again.state, IDLE, "the subject left the actionable population after a nudge")
        self.assertTrue(needs_a_human(again),
                        "a nudged-and-still-stuck subject stopped asking for a human")
        self.assertIn("nudge", again.note.lower(),
                      "the board cannot tell that fleet already tried this one")

    def test_activity_since_the_nudge_clears_the_annotation(self):
        """The annotation belongs to the EPISODE, not to the subject. A worker that got nudged, moved, and
        stalled again must not carry a scar from the previous episode - it is eligible again, and the note
        must not claim otherwise."""
        fleet = SyntheticFleet()
        fleet.dispatch("moved-07300408", "00000000-07300408-inflight-append-moved", "ws9", "dt-moved")
        fleet.launch("dt-moved", 5502, "ws9", QUIET_PANE)
        fleet.age("moved-07300408", 2700)

        def one():
            return {s.identity: s for s in reconcile(
                fleet.store, fleet.pool, fleet.sessions, fleet.instants)}["moved-07300408"]

        from fleet.nudge import Ledger
        Ledger(fleet.home).record(one(), delivered=True)
        (fleet.paths["moved-07300408"] / "HANDOFF.md").write_text("Updated: later\n")
        fleet.age("moved-07300408", 2700)

        self.assertNotIn("nudge", one().note.lower(),
                         "an annotation from a previous episode survived the worker making progress")
```

Run it: expected FAIL on the last assertion of the first case. Then, in `_worker_subject`, after the note is
computed:

```python
    #: Spec section 5. Read-only, and it must STAY read-only: `reconcile`'s purity test asserts this join
    #: writes nothing. Keyed by identity AND episode, so the annotation travels with the stall episode
    #: instead of becoming a permanent scar on the subject.
    if state == IDLE:
        note = _append_nudge_history(store, rec, evidence, note)
```

```python
def _append_nudge_history(store, rec, evidence, note: str) -> str:
    """If `nudge` already tried this subject in THIS stall episode, say so on the note.

    Swallows its own errors: a missing or corrupt ledger must degrade to "no annotation", never break the
    join that every view is built on.
    """
    from fleet.nudge import Ledger
    try:
        entry = Ledger(store.home).entry_for(rec.todo_id)
    except Exception:
        return note
    if not entry:
        return note
    if str(entry.get("activity_mtime", "")) != str(evidence.get("activity_mtime", "")):
        return note
    when = entry.get("at") or "an earlier pass"
    if entry.get("delivered"):
        return f"{note}; fleet nudged it at {when} and nothing has changed since"
    return f"{note}; fleet TRIED to nudge it at {when} and DELIVERY FAILED — this one needs a person"
```

This needs two additions to `Ledger` when you write it in Step 5: an `entry_for(identity) -> dict` accessor
returning `{}` for an unknown identity, and an `at` timestamp recorded by `record` beside `activity_mtime`
and `delivered`. Extend `test_nudge.py`'s ledger cases to cover `entry_for` on an unknown identity.

Re-run the case (expect PASS), then the full suite.

- [ ] **Step 5: Write `fleet/src/fleet/nudge.py`**

```python
"""`G-2`. The policy that decides who gets nudged, and the ledger that stops it repeating.

`fleet` DETECTED a stalled worker and every consumer of that judgement was a view — the "N needs you"
banner and a `reconcile` row. The loop ended at a human's eyes, so the operator was the mitigation:
*"the entire system stuck forever until I send messages waking folks up."*

Its own module because the policy is self-contained, has its own persistent state, and `cli.py` is already
very large. The DECISION lives here rather than in the shell caller so it is under the package's tests —
which is the half `G-10` proved matters.
"""
import json
from pathlib import Path

from fleet.atomic import atomic_write, held_for_update
from fleet.reconcile import IDLE, KIND_WORKER

LEDGER_NAME = "nudges.json"

#: Both texts are ONE LINE. They are typed with `send-keys -l` into an input box, and an embedded newline
#: submits early — delivering half a sentence and looking like it worked.
_WORKER = (
    "fleet: you look stalled — nothing has changed in your instant for over {idle}s and your pane is "
    "idle. Use the superpowers:maintain-workspace skill to bring this instant's workspace up to date "
    "(HANDOFF.md especially), then continue the next action. If you are BLOCKED on a decision, do not "
    "guess: run `fleet park --instant {instant} --question '<your question>'` so it reaches your "
    "coordinator."
)
_COORDINATOR = (
    "fleet: you look stalled — nothing has changed in your instant for over {idle}s and your pane is "
    "idle. Use the superpowers:maintain-workspace skill to bring this instant's workspace up to date "
    "(HANDOFF.md especially), then continue the next action. Your next action is probably your workers: "
    "run `fleet board` and act on EVERY subject that needs you — a PARKED child is waiting on your "
    "ANSWER, not on a nudge, so answer its question and then `fleet unpark --instant <child>`. If you "
    "are blocked on something only the operator can decide, park it yourself."
)


def text_for(profile_kind: str, instant: str, idle_after_s: int) -> str:
    """The nudge, chosen by the target's DECLARED profile kind (`D-11`).

    An unknown kind gets the WORKER text, in the safe direction: the worker text tells a coordinator to
    park a question it has nobody to send to, which is harmless; the coordinator text would send a worker
    to go unblock workers it does not have. The caller REPORTS that it defaulted — `OBS-5` is what happens
    when an unknown kind silently becomes `worker`.
    """
    template = _COORDINATOR if profile_kind == "coordinator" else _WORKER
    return template.format(idle=idle_after_s, instant=instant)


class Ledger:
    """Which subjects have already been nudged in their CURRENT stall episode.

    Not in the dispatch record: that has a different writer and a different lifecycle, and a verb that
    runs every `$INTERVAL` must not contend with `dispatch`. Written through the same
    `atomic_write` + `held_for_update` pattern as every other registry here.

    An episode ends when the instant shows activity again — `activity_mtime` on the subject, which is the
    same notion `_idle_for` uses. Deliberately NOT a timer: `D-7` puts the cadence in the watchdog's
    `$INTERVAL`, so this code cannot know how often it runs, and a back-off measured in "passes" would
    mean something different on every box.
    """

    def __init__(self, home):
        self.path = Path(home) / LEDGER_NAME

    def _load(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text()) or {}
        except (OSError, ValueError):
            #: A corrupt ledger must not stop a nudge. Losing the record costs one extra nudge; refusing
            #: to run costs the loop this verb exists to close.
            return {}

    def nudged_this_episode(self, subject) -> bool:
        entry = self._load().get(subject.identity)
        if not entry:
            return False
        return str(entry.get("activity_mtime", "")) == str(
            (subject.evidence or {}).get("activity_mtime", ""))

    def record(self, subject, delivered: bool) -> None:
        with held_for_update(self.path):
            data = self._load()
            data[subject.identity] = {
                "activity_mtime": str((subject.evidence or {}).get("activity_mtime", "")),
                "delivered": bool(delivered),
            }
            atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False))

    def forget_all_but(self, identities) -> None:
        """Drop entries for subjects that no longer exist. New persistent state with no removal rule
        grows forever."""
        keep = set(identities)
        with held_for_update(self.path):
            data = {k: v for k, v in self._load().items() if k in keep}
            atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False))


def eligible(subject, sessions, ledger) -> tuple:
    """Whether this subject should be nudged, and WHY NOT when it should not.

    Deliberately not a membership test on a state tuple. Three of the five rules are not state facts, and
    the parked one is the reason: `_live_state` appends a park to the NOTE and leaves the state `IDLE`, so
    a state-only filter nudges a child that correctly asked its coordinator a question — telling it to
    carry on WITHOUT the answer, which is the guessing failure `G-3` is about. Measured before this was
    written; see `evidence/2026-08-03-nudge-eligibility.txt`.
    """
    evidence = subject.evidence or {}
    if subject.kind != KIND_WORKER:
        return False, f"{subject.kind} is not a recorded instant; an unknown session is never touched"
    if subject.state != IDLE:
        return False, f"state is {subject.state}, and only IDLE is answered by a keystroke"
    if evidence.get("parked"):
        return False, ("parked: this instant asked a question and is waiting on an ANSWER, which a nudge "
                       "is not — its coordinator must reply and unpark it")
    tmux = evidence.get("tmux") or ""
    if sessions.attached(tmux):
        return False, f"a human is attached to {tmux}"
    if ledger.nudged_this_episode(subject):
        return False, ("already nudged this stall episode and nothing has changed since; escalated to "
                       "the board rather than nudged again")
    return True, "idle, unparked, unattended, and not yet nudged this episode"
```

- [ ] **Step 6: Run the tests**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_nudge -v
```
Expected: **14 PASS.**

- [ ] **Step 7: Write the verb's failing test**

Add to `fleet/tests/test_cli.py`:

```python
class TestNudge(CliCase):
    """`G-2`'s verb. The decision lives in the package; the watchdog only supplies the heartbeat."""

    def test_a_stalled_worker_is_nudged_and_the_send_is_reported(self):
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = IDLE_PANE
        fleet.age("solo", 2700)

        code, out, err = fleet.run(["nudge"])

        self.assertEqual(code, EXIT_OK, err)
        self.assertIn("nudged", out)
        self.assertIn("maintain-workspace", out, "the report does not show what was sent")
        kinds = [kind for target, kind, _ in fleet.sent if target == pane]
        self.assertEqual(kinds, ["text", "enter"])

    def test_dry_run_decides_but_does_not_send(self):
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = IDLE_PANE
        fleet.age("solo", 2700)

        code, out, err = fleet.run(["nudge", "--dry-run"])

        self.assertEqual(code, EXIT_OK, err)
        self.assertIn("would-nudge", out)
        self.assertEqual(fleet.sent, [], "a dry run sent something")

    def test_a_working_fleet_nudges_nobody_and_says_so(self):
        fleet = self.loaded()
        code, out, err = fleet.run(["nudge"])
        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual(fleet.sent, [])

    def test_a_skip_names_its_reason(self):
        """A verb that silently declines is indistinguishable from one that is broken."""
        fleet = self.loaded()
        pane = fleet.ids_tmux["solo"]
        fleet.panes[pane] = IDLE_PANE
        fleet.age("solo", 2700)
        fleet.attached.add(pane)

        code, out, err = fleet.run(["nudge"])

        self.assertEqual(fleet.sent, [])
        self.assertIn("attached", out.lower())
```

Add `self.attached = set()` to the `Fleet` fixture, wire it into the `attached_sessions` probe, and add an `age(name, seconds)` method mirroring Task 1's.

- [ ] **Step 8: Implement the verb**

In `fleet/src/fleet/cli.py`:

```python
def _do_nudge(ctx: Ctx, parsed: Parsed) -> int:
    """`G-2`. Act on the stall `fleet` already detects, instead of rendering it to somebody who has to
    remember to look.

    The judgement is `reconcile`'s — the same join `board` and `status` read, never a second derivation.
    This verb only decides who among the actionable is answerable BY A KEYSTROKE, and delivers.
    """
    #: `reconcile`'s OWN default idle threshold, not `ctx.max_age_s`. The latter is `harvest`'s staleness
    #: window; both are 1800 today, which is precisely how a conflation ships unnoticed and then diverges
    #: the day somebody tunes one of them.
    subjects = reconcile(ctx.store, ctx.pool, ctx.sessions, ctx.instants_dir)
    ledger = nudge.Ledger(ctx.home)
    ledger.forget_all_but([s.identity for s in subjects])

    override = parsed.get("text")
    rows, sent = [], 0
    #: Coordinators first: a stalled coordinator gates every worker beneath it, which is the case the
    #: original report actually described.
    ordered = sorted(subjects,
                     key=lambda s: 0 if (s.evidence or {}).get("profile_kind") == "coordinator" else 1)
    for subject in ordered:
        ok, why = nudge.eligible(subject, ctx.sessions, ledger)
        if not ok:
            if subject.state in ACTIONABLE_STATES:
                rows.append(("skipped", f"{subject.identity}: {why}"))
            continue
        evidence = subject.evidence or {}
        kind = evidence.get("profile_kind") or ""
        text = override or nudge.text_for(kind, evidence.get("instant", ""), IDLE_AFTER_S)
        if not kind:
            #: `OBS-5`. Defaulting to the worker text is the safe direction, but a SILENT default is the
            #: defect itself — so it is on the row.
            rows.append(("kind-unreadable",
                         f"{subject.identity}: profile kind could not be read; used the worker text"))
        if ctx.dry_run:
            rows.append(("would-nudge", f"{subject.identity}: {text}"))
            continue
        code, detail = _deliver(ctx, evidence.get("tmux", ""), text)
        ledger.record(subject, delivered=(code == EXIT_OK))
        sent += 1 if code == EXIT_OK else 0
        rows.append(("nudged" if code == EXIT_OK else "delivery-failed",
                     f"{subject.identity}: {text}" if code == EXIT_OK
                     else f"{subject.identity}: {detail}"))

    _emit(ctx, "nudge", rows + [("sent", str(sent)), ("population", str(len(subjects)))])
    return EXIT_OK
```

Import `nudge` and `ACTIONABLE_STATES` at the top of `cli.py`. Register:

```python
    _verb("nudge", _do_nudge, False,
          "nudge every stalled instant a keystroke can help; parked, attached and busy ones are left "
          "alone and the reason is reported", (
        Flag("--text", True, False, "override the nudge text"),
    )),
```

**`nudge` returns `EXIT_OK` even when a delivery failed.** It runs in a daemon loop; a non-zero exit there is a log line nobody reads, while the failure belongs on the row and in the note. A delivery failure is escalated by leaving the subject `IDLE` and actionable, which is `§5` of the spec.

- [ ] **Step 9: Run everything**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest tests.test_cli.TestNudge tests.test_nudge -v 2>&1 | tail -6
PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
```
Expected: all new cases PASS; suite `OK`.

- [ ] **Step 10: Commit and push**

```bash
cd /home/ubuntu/davis_root/superpowers
git add fleet/src/fleet/nudge.py fleet/src/fleet/cli.py fleet/src/fleet/reconcile.py fleet/tests/
git commit -m "fleet: nudge acts on the stall fleet already detects (G-2)

fleet computed a correct actionable judgement about a stalled worker and every
consumer was a VIEW - the needs-you banner and a reconcile row. The loop ended
at a human's eyes, so the operator was the mitigation: 'the entire system stuck
forever until I send messages waking folks up'.

Eligibility is not a membership test, and the parked rule is why: _live_state
appends a park to the NOTE and leaves the state IDLE, so a state-only filter
nudges a child that correctly asked a question - telling it to carry on WITHOUT
the answer. Measured before it was written.

One nudge per stall episode, bounded by the activity mtime the detector already
uses rather than a timer, since the cadence belongs to the watchdog. A second
nudge would be noise; the escalation is that the subject stays IDLE and
actionable with the attempt on its note.

Coordinators get their own text and are reported first - a stalled coordinator
gates every worker beneath it. Unknown profile kind uses the worker text and
SAYS so, because a silent default is OBS-5."
git push
```

---

### Task 9: The watchdog calls it (`D-7`)

**Files:**
- Modify: `scripts/claude-watchdog.sh`
- Test: `scripts/tests/` — follow the existing convention there

**Interfaces:**
- Consumes: `fleet nudge`.

- [ ] **Step 1: Add the call**

In `scripts/claude-watchdog.sh`, inside `cmd_reconcile` after `run_car_all_servers`:

```bash
# --- G-2: act on stalled instants ------------------------------------------------------------------
#
# NOT this script's usual duty, and that is deliberate (`D-7`). This daemon supervises claude-auto-retry
# monitors; nudging a stalled instant is a different job. It lives here because this is the only heartbeat
# on the box and it had already solved single-instance guarding, a pidfile, per-server scoping and an
# exclude list — re-solving those inside `fleet` would be rebuilding a mechanism that exists. DO NOT tidy
# this away as unrelated.
#
# `|| true` is REQUIRED, not defensive habit: a nudge bug must never be able to stop auto-resume, which is
# the thing this daemon exists for.
#
# Once PER SERVER, like the monitors: dispatched instants are deliberately not on the default server, and
# a nudge loop that looked at one server would be silently blind to every dispatched worker — the exact
# defect CLAUDE_WATCHDOG_TMUX_SOCKETS exists to prevent.
nudge_all_servers() {
  local sock
  FLEET_HOME="${FLEET_HOME:-/home/ubuntu/.fleet}" "$FLEET_BIN" nudge >/dev/null 2>&1 || true
  for sock in $CLAUDE_WATCHDOG_TMUX_SOCKETS; do
    [ -n "$sock" ] || continue
    tmux -L "$sock" has-session 2>/dev/null || continue
    FLEET_TMUX_SOCKET="$sock" FLEET_HOME="${FLEET_HOME:-/home/ubuntu/.fleet}" \
      "$FLEET_BIN" nudge >/dev/null 2>&1 || true
  done
}
```

Call `nudge_all_servers` from `cmd_reconcile`, and define `FLEET_BIN="${FLEET_BIN:-$DAVIS/superpowers/bin/fleet}"` beside the other path variables near the top.

- [ ] **Step 2: Verify the daemon still works and nudges nothing unexpected**

```bash
cd /home/ubuntu/davis_root/superpowers
bash -n scripts/claude-watchdog.sh && echo "syntax OK"
bash scripts/claude-watchdog.sh status 2>&1 | head -20
FLEET_HOME=/home/ubuntu/.fleet bin/fleet nudge --dry-run
```

Expected: syntax OK; `status` unchanged in shape; the dry run lists candidates and sends nothing. **Read the dry-run output before enabling anything** — if it names a subject you did not expect, stop and work out why.

- [ ] **Step 3: Commit and push**

```bash
git add scripts/claude-watchdog.sh
git commit -m "watchdog: call fleet nudge every interval (D-7)

The only heartbeat on the box, and it had already solved single-instance
guarding, a pidfile, per-server scoping and an exclude list. Re-solving those
inside fleet would rebuild a mechanism that exists.

Non-fatal by requirement: a nudge bug must never stop auto-resume, which is what
this daemon is for. Once per server, like the monitors - dispatched instants are
not on the default server and a one-server nudge loop would be silently blind to
every one of them."
git push
```

---

### Task 10: Re-run the red tests, then cut a release (`AC-2`)

**Files:** none modified. This task produces evidence.

- [ ] **Step 1: Re-run every red test from this plan and confirm it is green**

```bash
cd /home/ubuntu/davis_root/superpowers/fleet
PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -4
```
Expected: `OK`, with a total of roughly **1183 + ~35**. Record the exact number.

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure
bash bin/reverify-briefs.sh; echo "exit=$?"
bash bin/repro-g2-stall-loop.sh 2>&1 | tail -25
bash bin/probe-nudge-eligibility.sh 2>&1 | tail -20
```

Required, and each is a claim this whole effort rests on:
- `repro-g2` → **`M-1` and `M-3` KILLED** (were SURVIVED), `M-2` still KILLED.
- `probe-nudge-eligibility` → case 3 (parked + idle) still reports `state=IDLE`, and the design now excludes it (`D-8`) — the probe measures `reconcile`, so the row is unchanged; the *exclusion* is proven by `test_nudge`. Note that distinction in the artifact rather than expecting the probe's verdict line to flip.
- `reverify-briefs` → `G-1`'s and `G-2`'s premise rows should now MOVE, because the gaps are closed. **Update the script's expectations and the briefs' Status lines in the same commit** — a brief describing a fixed defect as open is the doc-rot this line of work has hit twice.

- [ ] **Step 2: Run the full IT gate**

```bash
cd /home/ubuntu/davis_root/superpowers
bash fleet/it/run-all.sh 2>&1 | tail -40
```
~25 min, **one job at a time**. It ends in a BATCH VERDICT. **Triage every FAIL row before going further** — read the per-runner registers, never the merged `it-RESULTS.tsv` (`II-6`).

- [ ] **Step 3: Cut the release**

```bash
cd /home/ubuntu/davis_root/superpowers
export FLEET_HOME=/home/ubuntu/.fleet FLEET_RELEASES=/home/ubuntu/davis_root/fleet-releases
git status --porcelain     # MUST be empty; a cut needs a clean tree
FLEET_HOME=$FLEET_HOME bin/fleet release-cut --version 0.4.0 --repo "$PWD" \
  --releases $FLEET_RELEASES \
  --notes "the stall loop closes: pane-send owns delivery (G-1), nudge acts on it (G-2), the IDLE detector has a test (G-10), a parked question asks for a human (G-11), and awaiting-ci needs a live watcher (D-10)"
```

**0.4.0, not 0.3.2** — new verbs and a widened `ACTIONABLE_STATES` are feature-level changes, and `declare --phase awaiting-ci` now refuses a form that used to be accepted.

- [ ] **Step 4: Verify, triage, promote**

```bash
FLEET_HOME=$FLEET_HOME bin/fleet release-verify --version 0.4.0 --releases $FLEET_RELEASES   # ~25 min
V=$FLEET_RELEASES/fleet-v0.4.0/.release/evidence
cat $V/VERDICT.tsv
grep -P '\tFAIL\t' $V/it-RESULTS-closeout-*.tsv | cut -f1,2,4
```

**Never promote over an unexplained red.** Every FAIL row gets attributed before the next command:

```bash
FLEET_HOME=$FLEET_HOME bin/fleet release-promote --version 0.4.0 --releases $FLEET_RELEASES
FLEET_HOME=$FLEET_HOME bin/fleet release-list --releases $FLEET_RELEASES
git -C /home/ubuntu/davis_root/superpowers worktree list    # a leaked verification worktree shows here
```

- [ ] **Step 5: Close the workspace out**

- `evidence/INDEX.md`: a row per new artifact — the green suite, the flipped mutation table, the release verdict — each with its regenerate command.
- Each closed brief (`G-1`, `G-2`) gets a **Status: FIXED** line naming the commit and the control. `G-10`, `G-11` the same in `ISSUES.md`. This is `AC-1`.
- `HANDOFF.md`: refresh the PR/branch table tip, the live snapshot, the before/after attention counts, and append a session-log row.
- `bin/reverify-briefs.sh`: update the rows whose premises are now closed, so the gate keeps telling the truth.
- Run `/review-workspace` as the advisory gate before any rename.
