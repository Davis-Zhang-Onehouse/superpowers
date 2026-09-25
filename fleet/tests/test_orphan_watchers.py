"""V23-H (v2-16): a completed worker's orphaned watcher pipelines held its slot, `harvest` refused with the pid list
and nothing could reap them. The attribution rule decides which slot holders are the torn-down instant's own; only
those are ever signalled."""

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from fleet import orphans
from fleet.orphans import NAME, REAP, REFUSE, Proc
from fleet.pool import UnreadableHolder
from fleet.session import Probes, SessionLayer, default_probes

INST = "/i/00000000-09251054-inflight-append-orphanw"
DONE = "/i/00000000-09251054-complete-append-orphanw"


def table(*procs):
    return {p.pid: p for p in procs}


def pipeline(root=500, ppid=1, path=INST):
    """The measured harness shape: zsh wrapper (argv carries `$INSTANT` unexpanded), tail (argv names the path),
    grep (argv names nothing). `evidence/01-repro/base-334fb1d5.txt`."""
    return (Proc(root, ppid, "s500", ("zsh", "-c", "tail -n0 -F $INSTANT/evidence/INDEX.md | grep DONE"),
                 sid=root, children=(root + 1, root + 2)),
            Proc(root + 1, root, "s501", ("tail", "-n0", "-F", f"{path}/evidence/INDEX.md"), sid=root, children=()),
            Proc(root + 2, root, "s502", ("grep", "--line-buffered", "DONE"), sid=root, children=()))


class AttributionRule(unittest.TestCase):

    def spell(self):
        return orphans.instant_spellings(DONE)

    def test_spellings_cover_every_state_of_the_instant(self):
        spelled = self.spell()
        self.assertIn(INST, spelled)
        self.assertIn(DONE, spelled)
        self.assertIn("/i/00000000-09251054-abort-append-orphanw", spelled)

    def test_an_orphaned_pipeline_naming_the_instant_is_reaped_whole(self):
        facts = table(*pipeline())
        att = orphans.attribute([500, 501, 502], facts.get, self.spell())
        self.assertEqual(sorted(att.pids(REAP)), [500, 501, 502])
        self.assertIn("501", att.of(REAP)[0].why)

    def test_a_prefix_sharing_sibling_is_not_this_instant(self):
        facts = table(*pipeline(path=INST + "2"))
        att = orphans.attribute([500, 501, 502], facts.get, self.spell())
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(sorted(att.pids(REFUSE)), [500, 501, 502])

    def test_boundaries(self):
        s = (INST,)
        self.assertTrue(orphans.names_instant(("x", f"--instant={INST}"), s))
        self.assertTrue(orphans.names_instant((f"'{INST}/evidence'",), s))
        self.assertTrue(orphans.names_instant((INST,), s))
        self.assertFalse(orphans.names_instant((INST + "2/evidence",), s))
        self.assertFalse(orphans.names_instant(("/prefix" + INST,), s))
        self.assertFalse(orphans.names_instant((INST + ".bak",), s))

    def test_named_but_parented_by_a_live_process_is_named_never_reaped(self):
        facts = table(*pipeline(ppid=4242))          # an operator's shell, NOT a slot holder, is its parent
        att = orphans.attribute([500, 501, 502], facts.get, self.spell())
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(sorted(att.pids(NAME)), [500, 501, 502])
        command = att.of(NAME)[0].kill_command()
        self.assertTrue(command.startswith("kill -TERM 500 501 502"), command)
        self.assertIn("4242", command)

    def test_an_orphan_that_names_nothing_is_refused(self):
        facts = table(Proc(700, 1, "s", ("sleep", "900"), sid=700, children=()))
        att = orphans.attribute([700], facts.get, self.spell())
        self.assertEqual(att.pids(REFUSE), [700])

    def test_an_unreadable_holder_is_refused_even_when_named(self):
        facts = table(Proc(800, 1, "s", ("tail", "-F", f"{INST}/x"), sid=800, children=()))
        att = orphans.attribute([UnreadableHolder(800)], facts.get, self.spell())
        self.assertEqual(att.pids(REFUSE), [800])

    def test_a_holder_whose_facts_cannot_be_read_is_refused(self):
        att = orphans.attribute([900], {}.get, self.spell())
        self.assertEqual(att.pids(REFUSE), [900])

    def test_the_callers_own_lineage_is_never_a_target(self):
        facts = table(*pipeline())
        att = orphans.attribute([500, 501, 502], facts.get, self.spell(), exclude={502})
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(sorted(att.pids(REFUSE)), [500, 501, 502])

    def test_the_sessions_own_process_that_survived_the_kill_is_reaped_unnamed(self):
        facts = table(Proc(600, 1, "s600", ("node", "worker.js"), sid=600, children=()))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"})
        self.assertEqual(att.pids(REAP), [600])
        self.assertIn("session", att.of(REAP)[0].why)

    def test_a_recycled_pid_is_not_the_sessions_process(self):
        facts = table(Proc(600, 1, "s-new", ("node", "worker.js"), sid=600, children=()))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"})
        self.assertEqual(att.pids(REAP), [])

    def test_a_slot_started_tmux_server_is_never_reaped_with_its_panes(self):
        """Task-1 review, Critical: a server started from inside the slot is ppid 1 and holds the slot; one pane naming
        the instant must not take down the server and every other pane."""
        facts = table(
            Proc(300, 1, "t", ("tmux", "-L", "priv", "new-session", "-d"), sid=300, children=(310, 320)),
            Proc(310, 300, "p1", ("bash",), sid=310, tty=34817, children=(311,)),
            Proc(311, 310, "l", ("less", f"{INST}/evidence/INDEX.md"), sid=310, tty=34817, children=()),
            Proc(320, 300, "p2", ("bash",), sid=320, tty=34818, children=(321,)),
            Proc(321, 320, "v", ("vim", "notes"), sid=320, tty=34818, children=()))
        att = orphans.attribute(list(facts), facts.get, self.spell())
        self.assertEqual(att.pids(REAP), [])
        self.assertNotIn(300, att.pids(NAME) + att.pids(REAP))
        self.assertIn(300, att.pids(REFUSE))
        self.assertEqual(sorted(att.pids(NAME)), [310, 311])

    def test_a_named_server_with_children_outside_is_named_not_reaped(self):
        facts = table(
            Proc(300, 1, "t", ("tmux", "new-session", "-c", INST), sid=300, children=(310,)),
            Proc(310, 300, "p1", ("bash",), sid=310, tty=34817, children=()))
        att = orphans.attribute(list(facts), facts.get, self.spell())
        self.assertEqual(att.pids(REAP), [])
        self.assertIn(300, att.pids(NAME))

    def test_a_member_in_another_session_is_its_own_unit(self):
        facts = table(*pipeline())
        facts[503] = Proc(503, 501, "s503", ("sleep", "9"), sid=503, children=())
        facts[501] = Proc(501, 500, "s501", ("tail", "-F", f"{INST}/x"), sid=500, children=(503,))
        att = orphans.attribute(list(facts), facts.get, self.spell())
        self.assertIn(503, att.pids(REFUSE))
        self.assertNotIn(501, att.pids(REAP), "a unit with a child outside it was reaped")

    def test_an_orphan_that_is_not_a_session_leader_is_named(self):
        facts = table(Proc(700, 1, "s", ("tail", "-F", f"{INST}/x"), sid=650, children=()))
        att = orphans.attribute([700], facts.get, self.spell())
        self.assertEqual(att.pids(NAME), [700])

    def test_an_orphan_with_a_terminal_is_named(self):
        facts = table(Proc(700, 1, "s", ("tail", "-F", f"{INST}/x"), sid=700, tty=34817, children=()))
        att = orphans.attribute([700], facts.get, self.spell())
        self.assertEqual(att.pids(NAME), [700])

    def test_unobserved_children_fail_closed(self):
        facts = table(Proc(700, 1, "s", ("tail", "-F", f"{INST}/x"), sid=700, children=None))
        att = orphans.attribute([700], facts.get, self.spell())
        self.assertEqual(att.pids(REAP), [])
        self.assertEqual(att.pids(NAME), [700])

    def test_a_sessions_own_survivor_with_an_outside_child_is_named(self):
        facts = table(Proc(600, 1, "s600", ("node",), sid=600, children=(999,)))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"})
        self.assertEqual(att.pids(NAME), [600])

    def test_naming_holders_lists_only_naming_pids_outside_the_lineage(self):
        facts = table(*pipeline(ppid=77))
        found = orphans.naming_holders([500, 501, 502], facts.get, self.spell(), exclude={77})
        self.assertEqual([p.pid for p in found], [501])


class Reap(unittest.TestCase):
    """TERM, a bounded wait, then KILL — each signal re-checks the start time so a recycled pid is never hit."""

    def setUp(self):
        self.live = table(*pipeline())
        self.sent = []
        self.slept = []

    def signal_pid(self, pid, sig):
        self.sent.append((pid, sig))
        return True

    def units(self):
        return orphans.attribute(list(self.live), self.live.get, orphans.instant_spellings(INST))

    def test_term_ends_them_and_nothing_is_killed(self):
        att = self.units()
        def signal_pid(pid, sig):
            self.sent.append((pid, sig))
            self.live.pop(pid, None)
            return True
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, signal_pid, self.slept.append)
        self.assertEqual(sorted((pid, how) for pid, how, _ in done), [(500, "TERM"), (501, "TERM"), (502, "TERM")])
        self.assertEqual({sig for _, sig in self.sent}, {signal.SIGTERM})

    def test_a_term_ignorer_is_killed_after_the_bound(self):
        att = self.units()
        def signal_pid(pid, sig):
            self.sent.append((pid, sig))
            if sig == signal.SIGKILL:
                self.live.pop(pid, None)
            return True
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, signal_pid, self.slept.append, wait_s=0.3)
        self.assertEqual({how for _, how, _ in done}, {"KILL"})
        self.assertAlmostEqual(sum(self.slept[:3]), 0.3, places=5)

    def test_a_recycled_pid_is_never_signalled(self):
        att = self.units()
        self.live[501] = Proc(501, 1, "someone-else", ("vim",), sid=501, children=())
        def signal_pid(pid, sig):
            self.sent.append((pid, sig))
            self.live.pop(pid, None)
            return True
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, signal_pid, self.slept.append)
        self.assertNotIn(501, [pid for pid, _ in self.sent])
        self.assertIn((501, "gone"), [(pid, how) for pid, how, _ in done])

    def test_a_process_that_survives_kill_is_reported_survived(self):
        att = self.units()
        done = orphans.reap(att.of(REAP), att.procs, self.live.get, self.signal_pid, self.slept.append, wait_s=0.2)
        self.assertEqual({how for _, how, _ in done}, {"survived"})


class RealProcessFacts(unittest.TestCase):
    """The real `/proc` reader and signal seam `default_probes` hands the attribution rule."""

    def probes(self):
        return default_probes(tmux_socket="itfleet-v23h-unused")

    def test_facts_of_a_real_process(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (child.kill(), child.wait()))
        fact = self.probes().proc_facts(child.pid)
        self.assertEqual((fact.pid, fact.ppid, fact.argv), (child.pid, os.getpid(), ("sleep", "30")))
        self.assertTrue(fact.start.isdigit())
        self.assertEqual(fact.children, ())
        own = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
        self.assertEqual((fact.sid, fact.tty), (int(own[3]), int(own[4])), "a child inherits session and terminal")

    def test_a_zombie_child_is_dropped_and_a_live_one_kept(self):
        code = ("import os, subprocess, sys, time\n"
                "if os.fork() == 0:\n    os._exit(0)\n"                  # never waited for: stays a zombie
                "p = subprocess.Popen(['sleep', '30'])\n"
                "print(p.pid, flush=True)\n"
                "time.sleep(30)\n")
        parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        sleeper = int(parent.stdout.readline())
        self.addCleanup(lambda: (os.kill(sleeper, signal.SIGKILL), parent.kill(), parent.wait(),
                                 parent.stdout.close()))
        time.sleep(0.2)
        states = {int(c): Path(f"/proc/{c}/stat").read_text().rsplit(")", 1)[1].split()[0]
                  for t in Path(f"/proc/{parent.pid}/task").iterdir()
                  for c in (t / "children").read_text().split()}
        self.assertIn("Z", states.values(), f"control: the fixture made no zombie ({states})")
        self.assertEqual(self.probes().proc_facts(parent.pid).children, (sleeper,))

    def test_a_gone_pid_has_no_facts(self):
        child = subprocess.Popen(["true"])
        child.wait()
        self.assertIsNone(self.probes().proc_facts(child.pid))

    def test_signal_pid_ends_the_process_it_was_given(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (child.poll() is None and child.kill(), child.wait()))
        self.assertTrue(self.probes().signal_pid(child.pid, signal.SIGTERM))
        self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)

    def test_an_absent_probe_is_not_observable(self):
        layer = SessionLayer(Probes(list_processes=list, capture_pane=lambda n: "", has_session=lambda n: False,
                                    start_session=lambda *a: None, kill_session=lambda n: None))
        self.assertFalse(layer.facts_observable())
        self.assertIsNone(layer.proc_facts(1))
        self.assertFalse(layer.signal_pid(1, 0))
