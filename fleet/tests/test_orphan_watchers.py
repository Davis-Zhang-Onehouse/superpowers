"""V23-H (v2-16): a completed worker's orphaned watcher pipelines held its slot, `harvest` refused with the pid list
and nothing could reap them. The attribution rule decides which slot holders are the torn-down instant's own; only
those are ever signalled."""

import os
import shlex
import shutil
import signal
import subprocess
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
    return (Proc(root, ppid, "s500", ("zsh", "-c", "tail -n0 -F $INSTANT/evidence/INDEX.md | grep DONE")),
            Proc(root + 1, root, "s501", ("tail", "-n0", "-F", f"{path}/evidence/INDEX.md")),
            Proc(root + 2, root, "s502", ("grep", "--line-buffered", "DONE")))


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
        facts = table(Proc(700, 1, "s", ("sleep", "900")))
        att = orphans.attribute([700], facts.get, self.spell())
        self.assertEqual(att.pids(REFUSE), [700])

    def test_an_unreadable_holder_is_refused_even_when_named(self):
        facts = table(Proc(800, 1, "s", ("tail", "-F", f"{INST}/x")))
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
        facts = table(Proc(600, 1, "s600", ("node", "worker.js")))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"})
        self.assertEqual(att.pids(REAP), [600])
        self.assertIn("session", att.of(REAP)[0].why)

    def test_a_recycled_pid_is_not_the_sessions_process(self):
        facts = table(Proc(600, 1, "s-new", ("node", "worker.js")))
        att = orphans.attribute([600], facts.get, self.spell(), session_own={600: "s600"})
        self.assertEqual(att.pids(REAP), [])

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
        self.live[501] = Proc(501, 1, "someone-else", ("vim",))
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
